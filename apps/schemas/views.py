from pathlib import Path

import yaml
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import SchemaVersion
from .schema_engine import get_schema_view, invalidate_cache


def _load_ui_config():
    config_path = Path(settings.BASE_DIR) / "config" / "loom_ui.yaml"
    try:
        with config_path.open() as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


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
        ui = _load_ui_config()
        edge_spec = lsv.form_spec(
            "CausalEdge",
            ui_layers=ui.get("layers"),
            ontology_routing=ui.get("ontology_routing", {}),
            widget_overrides=ui.get("widget_overrides", {}),
            globally_hidden_slots=ui.get("globally_hidden_slots", []),
        )
        return render(
            request,
            "schemas/schema_detail.html",
            {
                "schema_version": sv,
                "edge_spec": edge_spec,
                "all_classes": lsv.class_names(),
            },
        )
