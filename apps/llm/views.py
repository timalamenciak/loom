"""Review queue and admin config for the LLM proposal seam.

Per the seam guarantees in apps/llm/proposer.py, a proposal is inert until a
human acts on it here — accept advances it through the normal human status
lifecycle (services.advance_edge_status), reject deletes it. Neither path
writes to the graph outside the annotation service layer.
"""

import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from apps.annotation import services as annotation_services
from apps.annotation.models import Edge
from apps.projects.models import Assignment, Project, ProjectMembership

from .forms import ProposerConfigForm
from .models import FewShotExample, ProposalOutcome, ProposerConfig


def _can_review_proposals(user, project) -> bool:
    if user.is_superuser:
        return True
    if ProjectMembership.objects.filter(
        project=project, user=user, role=ProjectMembership.ROLE_ADMIN
    ).exists():
        return True
    return Assignment.objects.filter(project=project, annotator=user).exists()


def _require_review_access(user, project) -> None:
    if not _can_review_proposals(user, project):
        raise PermissionDenied("You may not review proposals for this project.")


def _require_project_admin(user, project) -> None:
    if user.is_superuser:
        return
    if ProjectMembership.objects.filter(
        project=project, user=user, role=ProjectMembership.ROLE_ADMIN
    ).exists():
        return
    raise PermissionDenied("Only project admins may configure the LLM seam.")


def _draft_proposals(project):
    return (
        Edge.objects.filter(
            graph__document__project=project,
            origin=Edge.ORIGIN_LLM_PROPOSED,
            status=Edge.STATUS_DRAFT,
        )
        .select_related("subject", "object", "graph__document")
        .order_by("created_at")[:50]
    )


class ProposalReviewView(LoginRequiredMixin, View):
    def get(self, request, project_pk):
        project = get_object_or_404(Project, pk=project_pk)
        _require_review_access(request.user, project)
        return render(
            request,
            "llm/proposal_review.html",
            {"project": project, "proposals": _draft_proposals(project)},
        )


class _ProposalActionView(LoginRequiredMixin, View):
    def act_on(self, edge: Edge, user, project, document) -> None:
        raise NotImplementedError

    def post(self, request, edge_pk):
        edge = get_object_or_404(
            Edge.objects.select_related("graph__document__project"),
            pk=edge_pk,
            origin=Edge.ORIGIN_LLM_PROPOSED,
            status=Edge.STATUS_DRAFT,
        )
        document = edge.graph.document
        project = document.project
        _require_review_access(request.user, project)
        self.act_on(edge, request.user, project, document)
        return render(
            request,
            "llm/partials/proposal_list.html",
            {"project": project, "proposals": _draft_proposals(project)},
        )


def _get_or_init_outcome(edge: Edge, project, document) -> ProposalOutcome:
    """Fetch this edge's ProposalOutcome, creating it with today's data as
    the "as proposed" baseline if the trigger somehow never wrote one."""
    outcome, _ = ProposalOutcome.objects.get_or_create(
        edge=edge,
        defaults={
            "project": project,
            "document": document,
            "proposed_data": dict(edge.data),
        },
    )
    return outcome


def _count_changed_keys(original: dict, current: dict) -> int:
    return len(
        [
            key
            for key in {**original, **current}
            if original.get(key) != current.get(key)
        ]
    )


class ProposalAcceptView(_ProposalActionView):
    def act_on(self, edge: Edge, user, project, document) -> None:
        outcome = _get_or_init_outcome(edge, project, document)
        created_at = edge.created_at
        proposed_data = outcome.proposed_data

        annotation_services.advance_edge_status(edge, user)
        edge.refresh_from_db()

        now = timezone.now()
        outcome.accepted_at = now
        outcome.edit_distance = _count_changed_keys(proposed_data, edge.data)
        outcome.time_to_review_seconds = int((now - created_at).total_seconds())
        outcome.save(
            update_fields=["accepted_at", "edit_distance", "time_to_review_seconds"]
        )


class ProposalRejectView(_ProposalActionView):
    def act_on(self, edge: Edge, user, project, document) -> None:
        outcome = _get_or_init_outcome(edge, project, document)
        created_at = edge.created_at

        now = timezone.now()
        outcome.rejected_at = now
        outcome.time_to_review_seconds = int((now - created_at).total_seconds())
        outcome.save(update_fields=["rejected_at", "time_to_review_seconds"])

        annotation_services.delete_edge(edge, user)


class LLMConfigView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)
        config = getattr(project, "llm_config", None) or ProposerConfig(project=project)
        form = ProposerConfigForm(instance=config, project=project)
        return render(
            request, "llm/llm_config.html", {"project": project, "form": form}
        )

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)
        instance = getattr(project, "llm_config", None) or ProposerConfig(
            project=project
        )
        form = ProposerConfigForm(request.POST, instance=instance, project=project)
        if form.is_valid():
            form.save()
            messages.success(request, "LLM configuration saved.")
            return redirect("llm-config", pk=project.pk)
        return render(
            request, "llm/llm_config.html", {"project": project, "form": form}
        )


_FEW_SHOT_EDGE_STATUSES = [Edge.STATUS_COMPLETE, Edge.STATUS_GOLD]


class FewShotSelectorView(LoginRequiredMixin, View):
    """Let a project admin curate which approved edges are shown to the model
    as few-shot examples — see FewShotExample.clean() for the same
    complete/gold eligibility rule enforced here at the query level.
    """

    def _eligible_edges(self, project):
        return (
            Edge.objects.filter(
                graph__document__project=project,
                status__in=_FEW_SHOT_EDGE_STATUSES,
            )
            .select_related("subject", "object", "graph__document")
            .order_by("-created_at")[:200]
        )

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)
        examples = FewShotExample.objects.filter(project=project)
        selected_edge_ids = set(examples.values_list("edge_id", flat=True))
        selected_labels = {str(ex.edge_id): ex.label for ex in examples}
        return render(
            request,
            "llm/few_shot_selector.html",
            {
                "project": project,
                "edges": self._eligible_edges(project),
                "selected_edge_ids": selected_edge_ids,
                "selected_labels": selected_labels,
            },
        )

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)
        selected_count = 0
        for edge in self._eligible_edges(project):
            if request.POST.get(f"selected_{edge.pk}"):
                FewShotExample.objects.get_or_create(
                    project=project,
                    edge=edge,
                    defaults={
                        "selected_by": request.user,
                        "label": request.POST.get(f"label_{edge.pk}", ""),
                    },
                )
                selected_count += 1
            else:
                FewShotExample.objects.filter(project=project, edge=edge).delete()
        messages.success(request, f"{selected_count} few-shot example(s) selected.")
        return redirect("llm-few-shot-selector", pk=project.pk)


class EnvVarCheckView(LoginRequiredMixin, View):
    """HTMX partial: is the named env var set on this server?

    Never reveals the value itself — only presence/absence — so this stays
    safe even though it's reachable by any project admin.
    """

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)
        name = (request.POST.get("api_key_env_var") or "").strip()
        is_set = bool(name) and bool(os.environ.get(name))
        return render(
            request,
            "llm/partials/env_var_status.html",
            {"name": name, "is_set": is_set},
        )


class LLMMetricsView(LoginRequiredMixin, View):
    """Read-only acceptance-rate / edit-distance dashboard for a project.

    Built on ProposalOutcome, not Edge — origin='llm_proposed' Edge rows
    disappear on rejection (see ProposalRejectView), so Edge alone can only
    ever show "proposals nobody rejected yet." ProposalOutcome is written
    once per proposal at trigger time and never deleted, so it's the only
    complete record of every proposal this project has ever received.
    """

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_project_admin(request.user, project)

        outcomes = ProposalOutcome.objects.filter(project=project)
        total = outcomes.count()
        accepted = outcomes.filter(accepted_at__isnull=False).count()
        rejected = outcomes.filter(rejected_at__isnull=False).count()
        pending = total - accepted - rejected
        acceptance_rate = round((accepted / total) * 100, 1) if total else 0
        if acceptance_rate >= 75:
            acceptance_rate_color = "#065f46"  # matches .message-success text
        elif acceptance_rate >= 40:
            acceptance_rate_color = "#92400e"  # amber
        else:
            acceptance_rate_color = "#7f1d1d"  # matches .message-error text

        avg_edit_distance = outcomes.filter(accepted_at__isnull=False).aggregate(
            avg=Avg("edit_distance")
        )["avg"]
        avg_review_seconds = outcomes.filter(
            time_to_review_seconds__isnull=False
        ).aggregate(avg=Avg("time_to_review_seconds"))["avg"]
        avg_review_minutes = (
            round(avg_review_seconds / 60, 1)
            if avg_review_seconds is not None
            else None
        )

        by_document = (
            outcomes.filter(document__isnull=False)
            .values("document_id", "document__title")
            .annotate(
                accepted=Count("pk", filter=Q(accepted_at__isnull=False)),
                rejected=Count("pk", filter=Q(rejected_at__isnull=False)),
                total=Count("pk"),
            )
            .order_by("document__title")
        )

        return render(
            request,
            "llm/llm_metrics.html",
            {
                "project": project,
                "total": total,
                "accepted": accepted,
                "rejected": rejected,
                "pending": pending,
                "acceptance_rate": acceptance_rate,
                "acceptance_rate_color": acceptance_rate_color,
                "avg_edit_distance": (
                    round(avg_edit_distance, 1)
                    if avg_edit_distance is not None
                    else None
                ),
                "avg_review_minutes": avg_review_minutes,
                "by_document": by_document,
            },
        )
