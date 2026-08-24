from django.urls import path

from apps.export.views import (
    ExportExcelView,
    ExportGraphView,
    ImportApplyView,
    ImportPreviewView,
    ImportUploadView,
    ValidateGraphView,
)

urlpatterns = [
    path("graphs/<int:graph_pk>/", ExportGraphView.as_view(), name="export-graph"),
    path(
        "graphs/<int:graph_pk>/validate/",
        ValidateGraphView.as_view(),
        name="validate-graph",
    ),
    path(
        "graphs/<int:graph_pk>/import/",
        ImportUploadView.as_view(),
        name="import-graph",
    ),
    path(
        "graphs/<int:graph_pk>/import/preview/",
        ImportPreviewView.as_view(),
        name="import-graph-preview",
    ),
    path(
        "graphs/<int:graph_pk>/import/apply/",
        ImportApplyView.as_view(),
        name="import-graph-apply",
    ),
    path(
        "graphs/<int:graph_pk>/export.xlsx",
        ExportExcelView.as_view(),
        name="export-graph-xlsx",
    ),
]
