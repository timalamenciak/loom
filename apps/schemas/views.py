from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import SchemaVersion
from .schema_engine import get_schema_view, invalidate_cache


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


class SchemaListView(LoginRequiredMixin, View):
    def get(self, request):
        _require_superuser(request)
        schemas = SchemaVersion.objects.all().order_by("-loaded_at")
        return render(request, "schemas/schema_list.html", {"schemas": schemas})


class SchemaActivateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        _require_superuser(request)
        sv = get_object_or_404(SchemaVersion, pk=pk)
        sv.is_active = True
        sv.save()
        invalidate_cache()
        messages.success(request, f"Schema {sv.version} is now active.")
        return redirect("schema-list")


class SchemaDetailView(LoginRequiredMixin, View):
    """Preview the form spec for a schema version."""

    def get(self, request, pk):
        _require_superuser(request)
        sv = get_object_or_404(SchemaVersion, pk=pk)
        lsv = get_schema_view(sv)
        edge_spec = lsv.form_spec("CausalEdge")
        return render(
            request,
            "schemas/schema_detail.html",
            {"schema_version": sv, "edge_spec": edge_spec, "all_classes": lsv.class_names()},
        )
