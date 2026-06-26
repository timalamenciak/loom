from django.urls import path

from .views import DocumentReaderView, SpanCreateView, SpanDeleteView

urlpatterns = [
    path("<int:doc_pk>/", DocumentReaderView.as_view(), name="document-read"),
    path("<int:doc_pk>/spans/", SpanCreateView.as_view(), name="span-create"),
    path("<int:doc_pk>/spans/<int:span_pk>/delete/", SpanDeleteView.as_view(), name="span-delete"),
]
