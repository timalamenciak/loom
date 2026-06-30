from django import forms
from django.contrib.auth import get_user_model

from apps.ontology.loaders import ontology_entries
from apps.schemas.models import SchemaVersion
from apps.schemas.ontology_inference import infer_ontologies
from apps.schemas.services import validate_schema_yaml

from .models import Project, ProjectMembership
from .upload_validation import (
    UploadValidationError,
    validate_bundle_upload,
    validate_pdf_upload,
    validate_ris_upload,
)


def _validated_upload(upload, validator):
    if not upload:
        return upload
    try:
        validator(upload)
    except UploadValidationError as exc:
        raise forms.ValidationError(str(exc)) from exc
    return upload


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class ProjectSettingsForm(forms.ModelForm):
    active_schema = forms.ModelChoiceField(
        queryset=SchemaVersion.objects.none(),
        required=False,
        empty_label="— select a loaded schema —",
    )
    schema_file = forms.FileField(
        required=False,
        label="Upload LinkML schema",
        help_text="YAML only, maximum 2 MB. External imports are not supported.",
        widget=forms.ClearableFileInput(attrs={"accept": ".yaml,.yml,text/yaml"}),
    )
    ontology_names = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Ontologies",
    )
    other_ontologies = forms.CharField(
        required=False,
        help_text="Additional configured ontology names or prefixes, comma-separated.",
    )

    class Meta:
        model = Project
        fields = [
            "name",
            "description",
            "active_schema",
            "auto_infer_ontologies",
            "ontology_names",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project=None, **kwargs):
        self.project = project or kwargs.get("instance")
        super().__init__(*args, **kwargs)
        self.fields["active_schema"].queryset = SchemaVersion.objects.order_by(
            "-loaded_at"
        )
        entries = ontology_entries()
        self.fields["ontology_names"].choices = [
            (entry["name"], f'{entry["description"]} ({entry["prefix"]})')
            for entry in entries
        ]
        if not self.is_bound and self.project:
            initial_names = set(self.project.ontology_names or [])
            if self.project.auto_infer_ontologies and self.project.active_schema:
                inferred = infer_ontologies(self.project.active_schema)
                initial_names.update(item["name"] for item in inferred["matched"])
            self.initial["ontology_names"] = sorted(initial_names)

    def clean_schema_file(self):
        upload = self.cleaned_data.get("schema_file")
        if not upload:
            return None
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError("Schema files may not exceed 2 MB.")
        try:
            content = upload.read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError("Schema must be UTF-8 text.") from exc
        try:
            validate_schema_yaml(content)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        upload.seek(0)
        self.schema_content = content
        return upload

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("active_schema") and not cleaned.get("schema_file"):
            self.add_error("active_schema", "Select or upload a LinkML schema.")

        entries = ontology_entries()
        aliases = {}
        for entry in entries:
            aliases[entry["name"].lower()] = entry["name"]
            aliases[entry["prefix"].lower()] = entry["name"]
        names = set(cleaned.get("ontology_names") or [])
        unknown = []
        for token in (cleaned.get("other_ontologies") or "").split(","):
            token = token.strip()
            if not token:
                continue
            resolved = aliases.get(token.lower())
            if resolved:
                names.add(resolved)
            else:
                unknown.append(token)
        if unknown:
            self.add_error(
                "other_ontologies",
                "Not a registered ontology (not in config/ontologies.yaml or the "
                "project-registered sources): " + ", ".join(unknown),
            )
        cleaned["ontology_names"] = sorted(names)
        return cleaned


class ProjectDeleteForm(forms.Form):
    confirmation = forms.CharField(label="Type the project name to confirm")

    def __init__(self, *args, project, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"]
        if value != self.project.name:
            raise forms.ValidationError("Project name does not match.")
        return value


class RISImportForm(forms.Form):
    ris_file = forms.FileField(
        label="RIS file (.ris)",
        help_text="Export from Zotero, Mendeley, PubMed, Web of Science, etc.",
    )

    def clean_ris_file(self):
        return _validated_upload(self.cleaned_data.get("ris_file"), validate_ris_upload)


class RISBundleImportForm(forms.Form):
    bundle_file = forms.FileField(
        label="RIS + PDF ZIP file",
        help_text=(
            "Upload a .zip file containing exactly one .ris file and the article PDFs. "
            "PDFs are matched by RIS attachment filename, DOI, or title. "
            "Full text is extracted when a document is first opened for annotation."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,application/zip"}),
    )

    def clean_bundle_file(self):
        return _validated_upload(
            self.cleaned_data.get("bundle_file"), validate_bundle_upload
        )


class PDFUploadForm(forms.Form):
    title = forms.CharField(
        max_length=500,
        required=False,
        help_text="Leave blank to use the filename.",
    )
    pdf_file = forms.FileField(
        label="PDF file",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf"}),
    )

    def clean_pdf_file(self):
        return _validated_upload(self.cleaned_data.get("pdf_file"), validate_pdf_upload)


class AttachPDFForm(forms.Form):
    pdf_file = forms.FileField(
        label="PDF file",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf"}),
    )

    def clean_pdf_file(self):
        return _validated_upload(self.cleaned_data.get("pdf_file"), validate_pdf_upload)


class AssignmentForm(forms.Form):
    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        member_ids = (
            ProjectMembership.objects.filter(project=project).values_list(
                "user_id", flat=True
            )
            if project
            else []
        )
        self.fields["annotator"] = forms.ModelChoiceField(
            queryset=User.objects.filter(pk__in=member_ids).order_by("username"),
            label="Assign to",
            empty_label="— select member —",
        )


class AddMemberForm(forms.Form):
    username = forms.CharField(max_length=150, label="Username")
    role = forms.ChoiceField(choices=ProjectMembership.ROLE_CHOICES)

    def clean_username(self):
        username = self.cleaned_data["username"]
        User = get_user_model()
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            raise forms.ValidationError(f'No user with username "{username}".')
