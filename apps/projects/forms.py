from django import forms
from django.contrib.auth import get_user_model

from .models import Project, ProjectMembership


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class RISImportForm(forms.Form):
    ris_file = forms.FileField(
        label="RIS file (.ris)",
        help_text="Export from Zotero, Mendeley, PubMed, Web of Science, etc.",
    )


class RISBundleImportForm(forms.Form):
    bundle_file = forms.FileField(
        label="RIS + PDF ZIP file",
        help_text=(
            "Upload a .zip file containing exactly one .ris file and the article PDFs. "
            "PDFs are matched by RIS attachment filename, DOI, or title."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,application/zip"}),
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


class AttachPDFForm(forms.Form):
    pdf_file = forms.FileField(
        label="PDF file",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf"}),
    )


class AssignmentForm(forms.Form):
    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        member_ids = (
            ProjectMembership.objects.filter(project=project).values_list("user_id", flat=True)
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
