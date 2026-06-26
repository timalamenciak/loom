from django.urls import path

from .views import OntologySearchView

urlpatterns = [
    path("search/", OntologySearchView.as_view(), name="ontology-search"),
]
