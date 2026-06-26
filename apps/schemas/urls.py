from django.urls import path

from .views import SchemaActivateView, SchemaDetailView, SchemaListView

urlpatterns = [
    path("", SchemaListView.as_view(), name="schema-list"),
    path("<int:pk>/", SchemaDetailView.as_view(), name="schema-detail"),
    path("<int:pk>/activate/", SchemaActivateView.as_view(), name="schema-activate"),
]
