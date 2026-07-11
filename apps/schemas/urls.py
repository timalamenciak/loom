from django.urls import path

from .views import (
    ApplyUpdateView,
    DismissUpdateView,
    FormBuilderExportView,
    FormBuilderImportView,
    FormBuilderSaveView,
    FormBuilderView,
    SchemaActivateView,
    SchemaDetailView,
    SchemaListView,
    SchemaUploadView,
    UpdateDiffView,
)

urlpatterns = [
    path("", SchemaListView.as_view(), name="schema-list"),
    path("upload/", SchemaUploadView.as_view(), name="schema-upload"),
    path(
        "updates/<int:pk>/dismiss/",
        DismissUpdateView.as_view(),
        name="dismiss-update",
    ),
    path(
        "updates/<int:pk>/diff/",
        UpdateDiffView.as_view(),
        name="update-diff",
    ),
    path(
        "updates/<int:pk>/apply/",
        ApplyUpdateView.as_view(),
        name="apply-update",
    ),
    path("<int:pk>/", SchemaDetailView.as_view(), name="schema-detail"),
    path("<int:pk>/activate/", SchemaActivateView.as_view(), name="schema-activate"),
    path(
        "<int:pk>/form-builder/",
        FormBuilderView.as_view(),
        name="schema-form-builder",
    ),
    path(
        "<int:pk>/form-builder/save/",
        FormBuilderSaveView.as_view(),
        name="schema-form-builder-save",
    ),
    path(
        "<int:pk>/form-builder/export/",
        FormBuilderExportView.as_view(),
        name="schema-form-builder-export",
    ),
    path(
        "<int:pk>/form-builder/import/",
        FormBuilderImportView.as_view(),
        name="schema-form-builder-import",
    ),
]
