from django.urls import path

from .views import (
    FormBuilderExportView,
    FormBuilderImportView,
    FormBuilderSaveView,
    FormBuilderView,
    SchemaActivateView,
    SchemaDetailView,
    SchemaListView,
    SchemaUploadView,
)

urlpatterns = [
    path("", SchemaListView.as_view(), name="schema-list"),
    path("upload/", SchemaUploadView.as_view(), name="schema-upload"),
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
