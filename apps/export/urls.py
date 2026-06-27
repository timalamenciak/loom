from django.urls import path

from apps.export.views import ExportGraphView, ValidateGraphView

urlpatterns = [
    path("graphs/<int:graph_pk>/", ExportGraphView.as_view(), name="export-graph"),
    path(
        "graphs/<int:graph_pk>/validate/",
        ValidateGraphView.as_view(),
        name="validate-graph",
    ),
]
