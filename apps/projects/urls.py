from django.urls import path

from apps.ontology.views import ProjectOntologySearchView

from . import views

urlpatterns = [
    # Cross-cutting
    path("queue/", views.MyQueueView.as_view(), name="my-queue"),
    # Phase 7 exports
    path(
        "<int:pk>/time-report.csv",
        views.TimeReportView.as_view(),
        name="project-time-report",
    ),
    path(
        "<int:pk>/irr-export.csv",
        views.IRRExportView.as_view(),
        name="project-irr-export",
    ),
    # Projects
    path("", views.ProjectListView.as_view(), name="project-list"),
    path("new/", views.ProjectCreateView.as_view(), name="project-create"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="project-detail"),
    path(
        "<int:pk>/settings/",
        views.ProjectSettingsView.as_view(),
        name="project-settings",
    ),
    path(
        "<int:pk>/settings/register-ontology/",
        views.RegisterOntologySourceView.as_view(),
        name="project-register-ontology",
    ),
    path(
        "<int:pk>/settings/rollup/add/",
        views.RollupAddRuleView.as_view(),
        name="project-rollup-add",
    ),
    path(
        "<int:pk>/settings/rollup/remove/<slug:slot>/",
        views.RollupRemoveRuleView.as_view(),
        name="project-rollup-remove",
    ),
    path(
        "<int:pk>/settings/rollup/preview/",
        views.RollupPreviewView.as_view(),
        name="project-rollup-preview",
    ),
    path("<int:pk>/delete/", views.ProjectDeleteView.as_view(), name="project-delete"),
    path(
        "<int:pk>/ontology/search/",
        ProjectOntologySearchView.as_view(),
        name="project-ontology-search",
    ),
    path(
        "<int:pk>/members/", views.ProjectMembersView.as_view(), name="project-members"
    ),
    # Documents (project-scoped)
    path(
        "<int:pk>/import-ris/", views.RISImportView.as_view(), name="project-import-ris"
    ),
    path(
        "<int:pk>/import-ris-bundle/",
        views.RISBundleImportView.as_view(),
        name="project-import-ris-bundle",
    ),
    path(
        "<int:pk>/upload-pdf/", views.PDFUploadView.as_view(), name="project-upload-pdf"
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/",
        views.DocumentDetailView.as_view(),
        name="document-detail",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/attach-pdf/",
        views.AttachPDFView.as_view(),
        name="document-attach-pdf",
    ),
    path(
        "<int:pk>/documents/<int:doc_pk>/assign/",
        views.AssignDocumentView.as_view(),
        name="document-assign",
    ),
]
