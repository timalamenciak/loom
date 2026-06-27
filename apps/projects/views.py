import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.audit.models import AuditEvent
from apps.documents.services import extract_text_from_pdf
from apps.ontology.models import OntologySnapshot
from apps.ontology.project_service import request_project_ontologies
from apps.schemas.models import SchemaVersion
from apps.schemas.ontology_inference import infer_ontologies
from apps.schemas.services import get_or_create_schema_version

from .forms import (
    AddMemberForm,
    AssignmentForm,
    AttachPDFForm,
    PDFUploadForm,
    ProjectDeleteForm,
    ProjectForm,
    ProjectSettingsForm,
    RISBundleImportForm,
    RISImportForm,
)
from .models import Assignment, Document, Project, ProjectMembership
from .services import (
    assign_document,
    attach_pdf_to_document,
    delete_project,
    import_ris_file,
    import_zipped_ris_bundle,
)

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def _get_membership(request, project):
    """Return (project, membership_or_None). Raises PermissionDenied if not a member."""
    if request.user.is_superuser:
        membership = ProjectMembership.objects.filter(
            project=project, user=request.user
        ).first()
        return project, membership
    try:
        membership = ProjectMembership.objects.get(project=project, user=request.user)
        return project, membership
    except ProjectMembership.DoesNotExist:
        raise PermissionDenied


def _require_admin(request, project):
    """Return project if the user is a project admin or superuser."""
    project, membership = _get_membership(request, project)
    if request.user.is_superuser:
        return project
    if membership and membership.role == ProjectMembership.ROLE_ADMIN:
        return project
    raise PermissionDenied


def _is_admin(request, membership):
    return request.user.is_superuser or (
        membership and membership.role == ProjectMembership.ROLE_ADMIN
    )


def _require_owner(request, project):
    """Project configuration and deletion belong to the creator, not all admins."""
    if request.user.is_superuser or project.created_by_id == request.user.pk:
        return project
    raise PermissionDenied


# ---------------------------------------------------------------------------
# Queue (annotator-facing, no project scope)
# ---------------------------------------------------------------------------


class MyQueueView(LoginRequiredMixin, ListView):
    template_name = "projects/my_queue.html"
    context_object_name = "assignments"

    def get_queryset(self):
        return (
            Assignment.objects.filter(annotator=self.request.user)
            .select_related("document", "project")
            .order_by("status", "-assigned_at")
        )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class ProjectListView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.is_superuser:
            projects = Project.objects.annotate(
                doc_count=Count("documents", distinct=True),
                member_count=Count("memberships", distinct=True),
            )
        else:
            projects = Project.objects.filter(memberships__user=request.user).annotate(
                doc_count=Count("documents", distinct=True),
                member_count=Count("memberships", distinct=True),
            )
        return render(request, "projects/project_list.html", {"projects": projects})


class ProjectCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "projects/project_form.html", {"form": ProjectForm()})

    def post(self, request):
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.created_by = request.user
            project.active_schema = SchemaVersion.get_active()
            project.ontology_snapshot = OntologySnapshot.get_active()
            if project.ontology_snapshot:
                project.ontology_names = sorted(
                    meta.get("name", prefix.lower())
                    for prefix, meta in project.ontology_snapshot.source_versions.items()
                )
            project.save()
            ProjectMembership.objects.create(
                project=project,
                user=request.user,
                role=ProjectMembership.ROLE_ADMIN,
            )
            messages.success(request, f'Project "{project.name}" created.')
            return redirect("project-detail", pk=project.pk)
        return render(request, "projects/project_form.html", {"form": form})


class ProjectDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        project, membership = _get_membership(request, project)
        admin = _is_admin(request, membership)
        owner = request.user.is_superuser or project.created_by_id == request.user.pk

        if admin:
            documents = (
                Document.objects.filter(project=project)
                .prefetch_related(
                    Prefetch(
                        "assignments",
                        queryset=Assignment.objects.select_related("annotator"),
                        to_attr="assignment_list",
                    )
                )
                .order_by("title")
            )
            members = ProjectMembership.objects.filter(project=project).select_related(
                "user"
            )

            # Active time per document (sum across all annotators and sessions)
            from apps.annotation.models import WorkSession

            times = (
                WorkSession.objects.filter(assignment__project=project)
                .values("assignment__document_id")
                .annotate(total_active=Sum("active_seconds"))
            )
            active_time_by_doc = {
                str(t["assignment__document_id"]): t["total_active"] or 0 for t in times
            }
        else:
            documents = None
            members = None
            active_time_by_doc = {}

        my_assignments = (
            Assignment.objects.filter(
                project=project, annotator=request.user
            ).select_related("document")
            if not admin
            else None
        )

        return render(
            request,
            "projects/project_detail.html",
            {
                "project": project,
                "membership": membership,
                "is_admin": admin,
                "is_owner": owner,
                "documents": documents,
                "members": members,
                "my_assignments": my_assignments,
                "active_time_by_doc": active_time_by_doc,
            },
        )


class ProjectSettingsView(LoginRequiredMixin, View):
    template_name = "projects/project_settings.html"

    def _project(self, request, pk):
        return _require_owner(request, get_object_or_404(Project, pk=pk))

    def _context(self, project, form):
        schema = form["active_schema"].value()
        schema_obj = None
        if schema:
            schema_obj = SchemaVersion.objects.filter(pk=schema).first()
        schema_obj = schema_obj or project.active_schema
        inferred = (
            infer_ontologies(schema_obj)
            if schema_obj
            else {"matched": [], "unresolved": []}
        )
        latest_load = project.ontology_load_requests.first()
        return {
            "project": project,
            "form": form,
            "inferred": inferred,
            "latest_load": latest_load,
        }

    def get(self, request, pk):
        project = self._project(request, pk)
        form = ProjectSettingsForm(instance=project, project=project)
        return render(request, self.template_name, self._context(project, form))

    def post(self, request, pk):
        project = self._project(request, pk)
        form = ProjectSettingsForm(
            request.POST,
            request.FILES,
            instance=project,
            project=project,
        )
        if not form.is_valid():
            return render(request, self.template_name, self._context(project, form))

        old = {
            "name": project.name,
            "description": project.description,
            "active_schema_id": project.active_schema_id,
            "ontology_names": list(project.ontology_names or []),
            "auto_infer_ontologies": project.auto_infer_ontologies,
        }
        configured = form.save(commit=False)
        if form.cleaned_data.get("schema_file"):
            configured.active_schema, _ = get_or_create_schema_version(
                form.schema_content,
                fallback_name=form.cleaned_data["schema_file"].name,
            )

        names = set(form.cleaned_data["ontology_names"])
        if configured.auto_infer_ontologies and configured.active_schema:
            inferred = infer_ontologies(configured.active_schema)
            names.update(item["name"] for item in inferred["matched"])
        configured.ontology_names = sorted(names)
        configured.save()

        AuditEvent.objects.create(
            actor=request.user,
            action="project.settings.update",
            target_type="Project",
            target_id=str(project.pk),
            diff={
                "before": old,
                "after": {
                    "name": configured.name,
                    "description": configured.description,
                    "active_schema_id": configured.active_schema_id,
                    "ontology_names": configured.ontology_names,
                    "auto_infer_ontologies": configured.auto_infer_ontologies,
                },
            },
        )
        load_request = request_project_ontologies(
            configured, request.user, configured.ontology_names
        )
        if load_request.status == load_request.STATUS_COMPLETE:
            messages.success(request, "Project settings and ontology snapshot updated.")
        else:
            messages.success(
                request, "Project settings saved; ontology loading is queued."
            )
        return redirect("project-settings", pk=project.pk)


class ProjectDeleteView(LoginRequiredMixin, View):
    template_name = "projects/project_confirm_delete.html"

    def _project(self, request, pk):
        return _require_owner(request, get_object_or_404(Project, pk=pk))

    def get(self, request, pk):
        project = self._project(request, pk)
        form = ProjectDeleteForm(project=project)
        return render(request, self.template_name, {"project": project, "form": form})

    def post(self, request, pk):
        project = self._project(request, pk)
        form = ProjectDeleteForm(request.POST, project=project)
        if not form.is_valid():
            return render(
                request, self.template_name, {"project": project, "form": form}
            )
        name = project.name
        delete_project(project, request.user)
        messages.success(request, f'Project "{name}" was deleted.')
        return redirect("project-list")


class ProjectMembersView(LoginRequiredMixin, View):
    def _setup(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return _require_admin(request, project)

    def get(self, request, pk):
        project = self._setup(request, pk)
        members = ProjectMembership.objects.filter(project=project).select_related(
            "user"
        )
        return render(
            request,
            "projects/members.html",
            {"project": project, "members": members, "form": AddMemberForm()},
        )

    def post(self, request, pk):
        project = self._setup(request, pk)
        members = ProjectMembership.objects.filter(project=project).select_related(
            "user"
        )

        if "remove_user" in request.POST:
            user_id = request.POST.get("remove_user")
            if str(project.created_by_id) == str(user_id):
                messages.error(request, "The project owner cannot be removed.")
                return redirect("project-members", pk=project.pk)
            ProjectMembership.objects.filter(project=project, user_id=user_id).delete()
            messages.success(request, "Member removed.")
            return redirect("project-members", pk=project.pk)

        form = AddMemberForm(request.POST)
        if form.is_valid():
            user = form.cleaned_data["username"]  # cleaned to User instance
            role = form.cleaned_data["role"]
            if (
                user.pk == project.created_by_id
                and role != ProjectMembership.ROLE_ADMIN
            ):
                form.add_error("role", "The project owner must remain an admin.")
                return render(
                    request,
                    "projects/members.html",
                    {"project": project, "members": members, "form": form},
                )
            _, created = ProjectMembership.objects.update_or_create(
                project=project, user=user, defaults={"role": role}
            )
            verb = "Added" if created else "Updated role for"
            messages.success(request, f"{verb} {user.username} as {role}.")
            return redirect("project-members", pk=project.pk)

        return render(
            request,
            "projects/members.html",
            {"project": project, "members": members, "form": form},
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class RISImportView(LoginRequiredMixin, View):
    def _setup(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return _require_admin(request, project)

    def get(self, request, pk):
        project = self._setup(request, pk)
        return render(
            request,
            "projects/ris_import.html",
            {"project": project, "form": RISImportForm()},
        )

    def post(self, request, pk):
        project = self._setup(request, pk)
        form = RISImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request, "projects/ris_import.html", {"project": project, "form": form}
            )

        try:
            created, skipped = import_ris_file(project, request.FILES["ris_file"])
        except ValueError as exc:
            form.add_error("ris_file", str(exc))
            return render(
                request, "projects/ris_import.html", {"project": project, "form": form}
            )

        messages.success(
            request,
            f"Imported {len(created)} record(s); {len(skipped)} duplicate(s) skipped.",
        )
        return redirect("project-detail", pk=project.pk)


class RISBundleImportView(LoginRequiredMixin, View):
    def _setup(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return _require_admin(request, project)

    def get(self, request, pk):
        project = self._setup(request, pk)
        return render(
            request,
            "projects/ris_bundle_import.html",
            {"project": project, "form": RISBundleImportForm()},
        )

    def post(self, request, pk):
        project = self._setup(request, pk)
        form = RISBundleImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                "projects/ris_bundle_import.html",
                {"project": project, "form": form},
            )

        try:
            result = import_zipped_ris_bundle(project, request.FILES["bundle_file"])
        except ValueError as exc:
            form.add_error("bundle_file", str(exc))
            return render(
                request,
                "projects/ris_bundle_import.html",
                {"project": project, "form": form},
            )

        messages.success(
            request,
            (
                f"Imported {len(result.created)} record(s); "
                f"{len(result.skipped)} duplicate(s) skipped; "
                f"attached {len(result.attached)} PDF(s)."
            ),
        )
        if result.already_had_pdf:
            messages.info(
                request,
                (
                    f"{len(result.already_had_pdf)} matched PDF(s) were skipped "
                    "because the document already had a PDF."
                ),
            )
        if result.unmatched_pdfs:
            messages.warning(
                request,
                "Could not match PDF(s): " + ", ".join(result.unmatched_pdfs[:10]),
            )
        if result.extraction_deferred:
            messages.info(
                request,
                (
                    f"Text extraction was deferred for {len(result.extraction_deferred)} "
                    "PDF(s). Run the extract_text command for this project before full-text "
                    "annotation."
                ),
            )
        if result.extraction_failed:
            messages.warning(
                request,
                f"Text extraction failed for {len(result.extraction_failed)} attached PDF(s).",
            )
        return redirect("project-detail", pk=project.pk)


class PDFUploadView(LoginRequiredMixin, View):
    def _setup(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return _require_admin(request, project)

    def get(self, request, pk):
        project = self._setup(request, pk)
        return render(
            request,
            "projects/pdf_upload.html",
            {"project": project, "form": PDFUploadForm()},
        )

    def post(self, request, pk):
        project = self._setup(request, pk)
        form = PDFUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request, "projects/pdf_upload.html", {"project": project, "form": form}
            )

        upload = request.FILES["pdf_file"]
        title = form.cleaned_data["title"] or upload.name.removesuffix(".pdf")

        doc = Document.objects.create(
            project=project,
            source=Document.SOURCE_PDF_UPLOAD,
            title=title,
        )
        doc = attach_pdf_to_document(doc, upload, upload.name)
        extract_text_from_pdf(doc)
        messages.success(request, f'Uploaded "{doc.title}".')
        return redirect("document-detail", pk=project.pk, doc_pk=doc.pk)


class DocumentDetailView(LoginRequiredMixin, View):
    def get(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _get_membership(request, project)  # raises PermissionDenied if not member
        doc = get_object_or_404(Document, pk=doc_pk, project=project)
        assignments = Assignment.objects.filter(document=doc).select_related(
            "annotator"
        )
        return render(
            request,
            "projects/document_detail.html",
            {"project": project, "document": doc, "assignments": assignments},
        )


class AttachPDFView(LoginRequiredMixin, View):
    def _setup(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_admin(request, project)
        return project, get_object_or_404(Document, pk=doc_pk, project=project)

    def get(self, request, pk, doc_pk):
        project, doc = self._setup(request, pk, doc_pk)
        return render(
            request,
            "projects/attach_pdf.html",
            {"project": project, "document": doc, "form": AttachPDFForm()},
        )

    def post(self, request, pk, doc_pk):
        project, doc = self._setup(request, pk, doc_pk)
        form = AttachPDFForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                "projects/attach_pdf.html",
                {"project": project, "document": doc, "form": form},
            )
        upload = request.FILES["pdf_file"]
        attach_pdf_to_document(doc, upload, upload.name)
        extract_text_from_pdf(doc)
        messages.success(request, f'PDF attached to "{doc.title[:60]}".')
        return redirect("document-detail", pk=project.pk, doc_pk=doc.pk)


class AssignDocumentView(LoginRequiredMixin, View):
    def _setup(self, request, pk, doc_pk):
        project = get_object_or_404(Project, pk=pk)
        _require_admin(request, project)
        return project, get_object_or_404(Document, pk=doc_pk, project=project)

    def get(self, request, pk, doc_pk):
        project, doc = self._setup(request, pk, doc_pk)
        form = AssignmentForm(project=project)
        existing = Assignment.objects.filter(document=doc).select_related("annotator")
        return render(
            request,
            "projects/document_assign.html",
            {"project": project, "document": doc, "form": form, "existing": existing},
        )

    def post(self, request, pk, doc_pk):
        project, doc = self._setup(request, pk, doc_pk)
        form = AssignmentForm(request.POST, project=project)
        if form.is_valid():
            annotator = form.cleaned_data["annotator"]
            assign_document(project, doc, annotator, request.user)
            messages.success(request, f"Assigned to {annotator.username}.")
            return redirect("project-detail", pk=project.pk)
        existing = Assignment.objects.filter(document=doc).select_related("annotator")
        return render(
            request,
            "projects/document_assign.html",
            {"project": project, "document": doc, "form": form, "existing": existing},
        )


# ---------------------------------------------------------------------------
# Phase 7 exports
# ---------------------------------------------------------------------------


class TimeReportView(LoginRequiredMixin, View):
    """CSV: active time per (document, annotator) for the project."""

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_admin(request, project)

        from apps.annotation.models import WorkSession

        rows = (
            WorkSession.objects.filter(assignment__project=project)
            .values(
                "assignment__document__id",
                "assignment__document__title",
                "annotator__username",
            )
            .annotate(
                session_count=Count("id"),
                active_seconds=Sum("active_seconds"),
                open_seconds=Sum("open_seconds"),
            )
            .order_by("assignment__document__title", "annotator__username")
        )

        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="time-report-project-{pk}.csv"'
        )
        w = csv.writer(resp)
        w.writerow(
            [
                "document_id",
                "document_title",
                "annotator",
                "sessions",
                "active_seconds",
                "active_minutes",
                "open_seconds",
            ]
        )
        for r in rows:
            active = r["active_seconds"] or 0
            w.writerow(
                [
                    r["assignment__document__id"],
                    r["assignment__document__title"],
                    r["annotator__username"],
                    r["session_count"],
                    active,
                    round(active / 60, 1),
                    r["open_seconds"] or 0,
                ]
            )
        return resp


class IRRExportView(LoginRequiredMixin, View):
    """CSV: per-annotator edge values for inter-rater reliability analysis."""

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        _require_admin(request, project)

        from apps.annotation.models import Edge

        edges = (
            Edge.objects.filter(graph__document__project=project)
            .select_related("graph__annotator", "graph__document", "subject", "object")
            .order_by(
                "graph__document__title", "graph__annotator__username", "-created_at"
            )
        )

        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="irr-export-project-{pk}.csv"'
        )
        w = csv.writer(resp)
        w.writerow(
            [
                "document_id",
                "document_title",
                "graph_id",
                "annotator",
                "edge_id",
                "edge_status",
                "subject_name",
                "object_name",
                "predicate",
                "claim_strength",
                "philosophical_account",
                "certainty_grade",
            ]
        )
        for edge in edges:
            data = edge.data
            w.writerow(
                [
                    edge.graph.document.pk,
                    edge.graph.document.title,
                    edge.graph.pk,
                    edge.graph.annotator.username,
                    edge.edge_id,
                    edge.status,
                    edge.subject.name,
                    edge.object.name,
                    edge.predicate,
                    edge.claim_strength,
                    data.get("philosophical_account", ""),
                    data.get("certainty_grade", ""),
                ]
            )
        return resp
