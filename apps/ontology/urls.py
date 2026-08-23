from django.urls import path

from .views import (
    OntologyBrowseView,
    OntologyDeleteView,
    OntologyManageListView,
    OntologyReloadView,
    OntologySearchView,
    OntologyTermSearchView,
    OntologyUploadView,
)

urlpatterns = [
    path("search/", OntologySearchView.as_view(), name="ontology-search"),
    path("manage/", OntologyManageListView.as_view(), name="ontology-manage-list"),
    path("manage/upload/", OntologyUploadView.as_view(), name="ontology-manage-upload"),
    path(
        "manage/<int:pk>/reload/",
        OntologyReloadView.as_view(),
        name="ontology-manage-reload",
    ),
    path(
        "manage/<int:pk>/delete/",
        OntologyDeleteView.as_view(),
        name="ontology-manage-delete",
    ),
    path(
        "manage/<int:pk>/browse/",
        OntologyBrowseView.as_view(),
        name="ontology-manage-browse",
    ),
    path(
        "manage/<int:pk>/search/",
        OntologyTermSearchView.as_view(),
        name="ontology-manage-search",
    ),
]
