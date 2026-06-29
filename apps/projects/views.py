import csv
import re

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


def _sd_slots(project) -> list[str]:
    """Return SourceDocument slot names from the project's active schema."""
    sv = project.active_schema
    if not sv:
        return []
    try:
        from apps.schemas.schema_engine import get_schema_view

        lsv = get_schema_view(sv)
        return [s.name for s in lsv._sv.class_induced_slots("SourceDocument")]
    except Exception:
        return []


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
        from apps.annotation.models import CausalGraph

        sample_graphs = list(
            CausalGraph.objects.filter(document__project=project)
            .select_related("document", "annotator")
            .order_by("-updated_at")[:10]
        )
        return {
            "project": project,
            "form": form,
            "inferred": inferred,
            "latest_load": latest_load,
            "sd_slots": _sd_slots(project),
            "sample_graphs": sample_graphs,
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
# Ad-hoc ontology registration
# ---------------------------------------------------------------------------

_VALID_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_VALID_URL_SCHEMES = ("http://", "https://")


class RegisterOntologySourceView(LoginRequiredMixin, View):
    """POST-only: register an OBO/OWL URL for an unresolved ontology prefix
    and immediately load it into the project's ontology snapshot."""

    def _project(self, request, pk):
        return _require_owner(request, get_object_or_404(Project, pk=pk))

    def post(self, request, pk):
        project = self._project(request, pk)

        prefix = request.POST.get("prefix", "").strip()
        name = request.POST.get("name", "").strip()
        url = request.POST.get("url", "").strip()
        description = request.POST.get("description", "").strip()

        # --- validate inputs ---
        if not prefix:
            messages.error(request, "Prefix is required.")
            return redirect("project-settings", pk=project.pk)
        if not name or not _VALID_NAME.match(name):
            messages.error(
                request,
                "Name must start with a letter and contain only lowercase "
                "letters, digits, underscores, or hyphens.",
            )
            return redirect("project-settings", pk=project.pk)
        if not url or not any(url.startswith(s) for s in _VALID_URL_SCHEMES):
            messages.error(request, "A valid http:// or https:// URL is required.")
            return redirect("project-settings", pk=project.pk)

        # Don't let the GUI shadow a curated YAML entry
        from apps.ontology.loaders import _load_config

        yaml_names = {e["name"].lower() for e in _load_config().get("ontologies", [])}
        yaml_prefixes = {
            e["prefix"].lower() for e in _load_config().get("ontologies", [])
        }
        if name.lower() in yaml_names or prefix.lower() in yaml_prefixes:
            messages.error(
                request,
                f'"{name}" / "{prefix}" is already defined in config/ontologies.yaml '
                "and cannot be overridden here.",
            )
            return redirect("project-settings", pk=project.pk)

        # --- register in DB ---
        from apps.ontology.models import AdHocOntologySource

        # Guard against the `name` unique constraint being violated by a
        # different prefix that already uses this name.
        name_taken = (
            AdHocOntologySource.objects.filter(name=name).exclude(prefix=prefix).first()
        )
        if name_taken:
            messages.error(
                request,
                f'Name "{name}" is already used for prefix "{name_taken.prefix}". '
                "Choose a different name.",
            )
            return redirect("project-settings", pk=project.pk)

        source_obj, created = AdHocOntologySource.objects.update_or_create(
            prefix=prefix,
            defaults={
                "name": name,
                "url": url,
                "description": description,
                "created_by": request.user,
            },
        )

        # --- load synchronously (120 s download timeout via urllib) ---
        from apps.ontology.loaders import load_ontology_release

        try:
            release, term_count = load_ontology_release(name)
        except Exception as exc:
            messages.error(request, f"Failed to load ontology: {exc}")
            return redirect("project-settings", pk=project.pk)

        # --- add to project and rebuild snapshot ---
        names = set(project.ontology_names or [])
        names.add(name)
        project.ontology_names = sorted(names)
        project.save(update_fields=["ontology_names", "updated_at"])

        from apps.ontology.project_service import request_project_ontologies

        load_request = request_project_ontologies(
            project, request.user, project.ontology_names
        )

        AuditEvent.objects.create(
            actor=request.user,
            action="ontology.source.registered",
            target_type="Project",
            target_id=str(project.pk),
            diff={
                "prefix": prefix,
                "name": name,
                "url": url,
                "term_count": term_count,
                "created": created,
            },
        )

        if load_request.status == load_request.STATUS_COMPLETE:
            messages.success(
                request,
                f'Registered "{name}" ({prefix}, {term_count:,} terms) and '
                "added it to the project snapshot.",
            )
        else:
            messages.success(
                request,
                f'Registered "{name}" ({prefix}, {term_count:,} terms); '
                "snapshot rebuild is queued.",
            )
        return redirect("project-settings", pk=project.pk)


# ---------------------------------------------------------------------------
# Source document rollup configuration
# ---------------------------------------------------------------------------


class RollupAddRuleView(LoginRequiredMixin, View):
    """POST: append a rollup rule to the project; redirect back to settings."""

    def post(self, request, pk):
        project = _require_owner(request, get_object_or_404(Project, pk=pk))
        slot = request.POST.get("slot", "").strip()
        source = request.POST.get("source", "").strip()
        attribute = request.POST.get("attribute", "").strip()
        operation = request.POST.get("operation", "list_unique").strip()

        rules = list(project.source_document_rollup or [])
        errors = []
        if not slot:
            errors.append("Slot is required.")
        elif any(r.get("slot") == slot for r in rules):
            errors.append(f"A rule for slot '{slot}' already exists.")
        if source not in ("node", "edge"):
            errors.append("Source must be 'node' or 'edge'.")
        if not attribute:
            errors.append("Attribute path is required.")
        if operation not in ("list_unique", "list_all"):
            errors.append("Invalid operation.")

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            rules.append(
                {
                    "slot": slot,
                    "source": source,
                    "attribute": attribute,
                    "operation": operation,
                }
            )
            project.source_document_rollup = rules
            project.save(update_fields=["source_document_rollup", "updated_at"])
            AuditEvent.objects.create(
                actor=request.user,
                action="project.rollup.add",
                target_type="Project",
                target_id=str(project.pk),
                diff={
                    "slot": slot,
                    "source": source,
                    "attribute": attribute,
                    "operation": operation,
                },
            )
            messages.success(request, f"Rollup rule for '{slot}' added.")

        return redirect("project-settings", pk=project.pk)


class RollupRemoveRuleView(LoginRequiredMixin, View):
    """POST: remove a rollup rule by slot name; redirect back to settings."""

    def post(self, request, pk, slot):
        project = _require_owner(request, get_object_or_404(Project, pk=pk))
        rules = [
            r for r in (project.source_document_rollup or []) if r.get("slot") != slot
        ]
        project.source_document_rollup = rules
        project.save(update_fields=["source_document_rollup", "updated_at"])
        AuditEvent.objects.create(
            actor=request.user,
            action="project.rollup.remove",
            target_type="Project",
            target_id=str(project.pk),
            diff={"slot": slot},
        )
        messages.success(request, f"Rollup rule for '{slot}' removed.")
        return redirect("project-settings", pk=project.pk)


class RollupPreviewView(LoginRequiredMixin, View):
    """POST: apply rollup rules to a selected graph and return a preview partial."""

    def post(self, request, pk):
        project = _require_owner(request, get_object_or_404(Project, pk=pk))
        from apps.annotation.models import CausalGraph

        graph_pk = request.POST.get("graph_pk", "").strip()
        if not graph_pk:
            return render(
                request,
                "projects/partials/rollup_preview.html",
                {"error": "No graph selected."},
            )

        graph = get_object_or_404(CausalGraph, pk=graph_pk, document__project=project)
        rules = project.source_document_rollup or []
        if not rules:
            return render(
                request,
                "projects/partials/rollup_preview.html",
                {"error": "No rollup rules configured."},
            )

        from apps.annotation.rollup import roll_up_source_document

        nodes_data = list(graph.nodes.values_list("data", flat=True))
        edges_data = list(graph.edges.values_list("data", flat=True))
        rolled = roll_up_source_document(nodes_data, edges_data, rules)

        # Pre-pair rules with their resulting values for the template
        rule_results = [
            {"rule": rule, "values": rolled.get(rule["slot"], [])} for rule in rules
        ]

        return render(
            request,
            "projects/partials/rollup_preview.html",
            {
                "graph": graph,
                "rule_results": rule_results,
            },
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
