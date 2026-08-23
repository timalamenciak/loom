import hashlib
import json
import threading
from pathlib import Path

import yaml
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connections
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views import View
from linkml_runtime.utils.schemaview import SchemaView

from apps.ontology.models import OntologyRelease

from .models import SchemaUIConfig, SchemaVersion, UpdateCheckRecord
from .schema_engine import WIDGET_MAP, LoomSchemaView, get_schema_view, invalidate_cache
from .update_service import (
    apply_ontology_update,
    apply_schema_update,
    check_all_updates,
)
from .upstream import UpstreamCheckError

_UPDATE_CHECK_CACHE_KEY = "loom:update_check_last_run"
_UPDATE_CHECK_INTERVAL_SECONDS = 60 * 60 * 12  # 12 hours


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


def _run_in_background(target, *args):
    """Fire-and-forget *target(*args)* on a daemon thread.

    Django's per-thread DB connection is normally closed by the
    request_finished signal, which a thread spawned off a view never gets —
    without this, each background trigger leaks a connection. Closing it
    here, in the same thread that opened it, is the standard fix.
    """

    def _wrapped():
        try:
            target(*args)
        finally:
            connections.close_all()

    threading.Thread(target=_wrapped, daemon=True).start()


def _maybe_trigger_update_check():
    """Kick off a background schema/ontology update check at most once per
    12-hour window, without Celery.

    A daemon thread running check_all_updates() is fire-and-forget: it never
    blocks this request, and it persists its results to UpdateCheckRecord for
    the *next* page load to read. cache.add() (not get-then-set) is what
    debounces repeat triggers — it's atomic, so two requests racing on a cold
    cache can't both win and both spawn a check. Note this debounce is only
    as global as the cache backend: with the default per-process LocMemCache
    under multiple worker processes, each worker gets its own 12-hour window.
    """
    if not cache.add(_UPDATE_CHECK_CACHE_KEY, True, _UPDATE_CHECK_INTERVAL_SECONDS):
        return
    _run_in_background(check_all_updates)


class SchemaListView(LoginRequiredMixin, View):
    def get(self, request):
        _require_superuser(request)
        _maybe_trigger_update_check()
        schemas = SchemaVersion.objects.all().order_by("-loaded_at")
        return render(request, "schemas/schema_list.html", {"schemas": schemas})


class DismissUpdateView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: suppress one UpdateCheckRecord's banner for this user's
    session. Per-session, not per-record: the update-check itself isn't
    touched, so the next scheduled check still runs and other admins still
    see the banner until they dismiss it too.

    Called from two places that need different responses: the base.html
    banner posts via hx-swap="none" and just wants the row gone client-side
    (204, no body), while the update-diff page's plain Dismiss button is a
    normal form submit that needs a real redirect to go anywhere. HTMX tags
    every request it makes with HX-Request, so that header is what tells the
    two apart.
    """

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def post(self, request, pk):
        record = get_object_or_404(UpdateCheckRecord, pk=pk)
        request.session[record.dismiss_session_key()] = True
        if request.headers.get("HX-Request"):
            return HttpResponse(status=204)
        return redirect("schema-list")


class UpdateDiffView(LoginRequiredMixin, View):
    """Superuser-only, matching every other schema-admin view in this app
    (SchemaListView, SchemaActivateView, SchemaDetailView) — this is where
    Apply/Dismiss redirect back to, so gating it any looser than schema-list
    itself would just move the 403 one click later instead of avoiding it.
    The notification banner (staff-visible, per apps/schemas/context_processors.py)
    can link here even for staff-non-superuser users; they'll hit the same
    403 a superuser-only page always gives them, same as any other admin link
    in the nav.
    """

    def get(self, request, pk):
        _require_superuser(request)
        record = get_object_or_404(UpdateCheckRecord, pk=pk)
        return render(request, "schemas/update_diff.html", {"record": record})


class ApplyUpdateView(LoginRequiredMixin, View):
    """Superuser-only — see UpdateDiffView's docstring.

    GET renders a confirmation page (the diff again, plus an "activate
    immediately" checkbox for schema updates) rather than applying anything.
    POST only acts when confirm=1 is present in the body, so a bare/replayed
    POST — someone re-submitting a form, a proxy retry — bounces back to the
    confirmation page instead of silently re-applying.

    Schema updates are one small YAML file, so they're applied synchronously
    and the admin gets an immediate success/failure message. Ontology
    reloads can be large, so they're kicked off on a background daemon
    thread instead — the same no-Celery pattern
    _maybe_trigger_update_check() already uses for the check itself — and
    the admin is told to check back shortly rather than waiting on it.
    """

    def get(self, request, pk):
        _require_superuser(request)
        record = get_object_or_404(UpdateCheckRecord, pk=pk)
        return render(request, "schemas/apply_update.html", {"record": record})

    def post(self, request, pk):
        _require_superuser(request)
        record = get_object_or_404(UpdateCheckRecord, pk=pk)

        if request.POST.get("confirm") != "1":
            return redirect("apply-update", pk=pk)

        if record.module_type == UpdateCheckRecord.MODULE_SCHEMA:
            activate = request.POST.get("activate") == "on"
            try:
                schema, created = apply_schema_update(record, activate=activate)
            except UpstreamCheckError as exc:
                messages.error(request, f"Could not apply update: {exc}")
                return redirect("apply-update", pk=pk)
            if not created:
                messages.info(request, f"CAMO {schema.version} was already loaded.")
            elif schema.is_active:
                messages.success(
                    request, f"CAMO {schema.version} loaded and activated."
                )
            else:
                messages.success(request, f"CAMO {schema.version} loaded.")
        else:
            _run_in_background(apply_ontology_update, record)
            messages.success(
                request,
                f"Reloading {record.module_name} in the background — "
                "check back shortly.",
            )

        return redirect("schema-list")


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


class SchemaUploadView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: upload a new CAMO LinkML YAML file as a SchemaVersion."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request):
        return render(request, "schemas/upload.html", {})

    def post(self, request):
        upload = request.FILES.get("schema_file")
        if not upload:
            return render(
                request,
                "schemas/upload.html",
                {"error": "Choose a schema YAML file to upload."},
            )

        ext = Path(upload.name).suffix.lower()
        if ext not in {".yaml", ".yml"}:
            return render(
                request,
                "schemas/upload.html",
                {
                    "error": f"Unsupported file type {ext or upload.name!r}. Allowed: .yaml, .yml."
                },
            )
        if upload.size > settings.MAX_SCHEMA_UPLOAD_BYTES:
            limit_mb = settings.MAX_SCHEMA_UPLOAD_BYTES // (1024 * 1024)
            return render(
                request,
                "schemas/upload.html",
                {"error": f"Schema files may not exceed {limit_mb} MB."},
            )

        yaml_bytes = upload.read()
        try:
            yaml_str = yaml_bytes.decode("utf-8")
            schema_view = SchemaView(yaml_str)
            version = str(schema_view.schema.version or "uploaded")
        except Exception as exc:
            return render(
                request,
                "schemas/upload.html",
                {"error": f"Could not parse schema: {exc}"},
            )

        digest = hashlib.sha256(yaml_bytes).hexdigest()
        existing = SchemaVersion.objects.filter(sha256=digest).first()
        if existing:
            return render(
                request,
                "schemas/upload.html",
                {
                    "error": f"This exact schema is already loaded as version "
                    f"{existing.version!r}."
                },
            )

        try:
            schema = SchemaVersion.objects.create(
                version=version,
                linkml_yaml=yaml_str,
            )
        except IntegrityError:
            return render(
                request,
                "schemas/upload.html",
                {"error": f"Schema version {version!r} is already loaded."},
            )

        invalidate_cache(schema.pk)
        messages.success(request, f"Schema {schema.version} uploaded.")
        return redirect("schema-detail", pk=schema.pk)


def _slot_meta(schema_view) -> dict:
    """name -> {range, description, multivalued, required} for every slot."""
    return {
        name: {
            "range": slot.range or "string",
            "description": slot.description or "",
            "multivalued": bool(slot.multivalued),
            "required": bool(slot.required),
        }
        for name, slot in sorted(schema_view.all_slots().items())
    }


def _simple_ontology_prefixes(routing) -> list[str]:
    """Extract prefixes from a slot's ontology_routing entry if it's one of
    the two "simple" list shapes (flat prefix strings, or the form builder's
    ``[{"prefix": ...}]`` shape) — see LoomSchemaView._slot_spec. Dict-shaped
    entries (condition_slot routing, wikidata_live, allow_free_text) aren't
    representable in the builder's multi-select, so this returns [] for them
    and the caller leaves those entries untouched rather than clobbering them.
    """
    if not isinstance(routing, list):
        return []
    prefixes = [
        item.get("prefix") if isinstance(item, dict) else item for item in routing
    ]
    return [p for p in prefixes if p]


def _ontology_choices() -> list[dict]:
    """{prefix, name} for every ready OntologyRelease, one entry per prefix."""
    seen: dict[str, str] = {}
    releases = OntologyRelease.objects.filter(
        status=OntologyRelease.STATUS_READY
    ).order_by("prefix", "-loaded_at")
    for release in releases:
        seen.setdefault(release.prefix, release.name)
    return [{"prefix": prefix, "name": name} for prefix, name in sorted(seen.items())]


def _builder_state(config, slot_names: list[str]) -> dict:
    """Reshape a SchemaUIConfig into the drag-and-drop editor's working
    state: layers (each with its slots expanded into per-slot override
    dicts) plus whichever schema slots aren't placed in any layer yet."""
    hidden = set(config.globally_hidden_slots or [])
    widget_overrides = config.widget_overrides or {}
    slot_help_text = config.slot_help_text or {}
    ontology_routing = config.ontology_routing or {}
    known = set(slot_names)

    assigned: set[str] = set()
    layers = []
    for layer in config.layers or []:
        layer_slot_names = [n for n in (layer.get("slots") or []) if n in known]
        assigned.update(layer_slot_names)
        layers.append(
            {
                "name": layer.get("label") or layer.get("id") or "Untitled",
                "slots": [
                    {
                        "name": name,
                        "hidden": name in hidden,
                        "widget": widget_overrides.get(name, ""),
                        "help_text": slot_help_text.get(name, ""),
                        "required_override": None,
                        "ontology_sources": _simple_ontology_prefixes(
                            ontology_routing.get(name)
                        ),
                    }
                    for name in layer_slot_names
                ],
            }
        )

    unassigned = [n for n in slot_names if n not in assigned]
    return {"layers": layers, "unassigned": unassigned}


class FormBuilderView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: drag-and-drop editor for a schema's UI config (layer
    grouping, per-slot widget override, hidden flag, help text, ontology
    sources)."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request, pk):
        sv = get_object_or_404(SchemaVersion, pk=pk)
        config = SchemaUIConfig.for_schema_version(sv)
        schema_view = SchemaView(sv.linkml_yaml)
        slot_meta = _slot_meta(schema_view)

        return render(
            request,
            "schemas/form_builder.html",
            {
                "sv": sv,
                "builder_state": _builder_state(config, list(slot_meta)),
                "slot_meta": slot_meta,
                "widget_choices": list(WIDGET_MAP.keys()),
                "ontology_choices": _ontology_choices(),
            },
        )


class FormBuilderSaveView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: persist the form builder's edited layers/widget-overrides/
    hidden-slots/help-text back to this schema's schema-level SchemaUIConfig.

    Scoped to the whole schema (project=None), matching FormBuilderView,
    which has no project in its URL — this editor isn't project-scoped.
    """

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def post(self, request, pk):
        sv = get_object_or_404(SchemaVersion, pk=pk)
        try:
            payload = json.loads(request.body)

            # Seed from the existing config rather than starting empty: the
            # builder's ontology-sources multi-select only edits "simple"
            # (list-shaped) routing entries (see _simple_ontology_prefixes).
            # Dict-shaped entries — condition_slot routing, wikidata_live,
            # allow_free_text — aren't represented in that control, so a save
            # from this view must not silently delete them.
            existing_config = SchemaUIConfig.for_schema_version(sv)
            ontology_routing = dict(existing_config.ontology_routing or {})

            layers = []
            widget_overrides = {}
            globally_hidden_slots = []
            slot_help_text = {}
            for index, layer in enumerate(payload.get("layers") or []):
                label = (layer.get("name") or "").strip() or f"Section {index + 1}"
                slot_names = []
                for slot in layer.get("slots") or []:
                    name = (slot.get("name") or "").strip()
                    if not name:
                        continue
                    slot_names.append(name)
                    if slot.get("hidden"):
                        globally_hidden_slots.append(name)
                    widget = (slot.get("widget") or "").strip()
                    if widget:
                        widget_overrides[name] = widget
                    help_text = (slot.get("help_text") or "").strip()
                    if help_text:
                        slot_help_text[name] = help_text

                    sources = [
                        str(p).strip()
                        for p in (slot.get("ontology_sources") or [])
                        if str(p).strip()
                    ]
                    if sources:
                        ontology_routing[name] = [{"prefix": p} for p in sources]
                    elif isinstance(ontology_routing.get(name), list):
                        # Was builder-editable and is now empty: the user
                        # cleared every selection, so drop the entry.
                        del ontology_routing[name]
                # Stored as id/label (not the client's bare "name") because
                # schema_engine.LoomSchemaView.form_spec() and every other
                # loom_ui.yaml-shaped consumer index a layer by "id" and
                # display "label" — persisting "name" here would silently
                # break layer rendering (and this config's own name field on
                # the next GET, since FormBuilderView reads label/id back)
                # the next time this SchemaUIConfig is read.
                layers.append(
                    {
                        "id": slugify(label) or f"section-{index + 1}",
                        "label": label,
                        "slots": slot_names,
                    }
                )

            SchemaUIConfig.objects.update_or_create(
                schema_version=sv,
                project=None,
                defaults={
                    "layers": layers,
                    "ontology_routing": ontology_routing,
                    "widget_overrides": widget_overrides,
                    "globally_hidden_slots": globally_hidden_slots,
                    "slot_help_text": slot_help_text,
                },
            )
            invalidate_cache(sv.pk)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)

        return JsonResponse({"ok": True})


def _config_yaml_dict(config) -> dict:
    return {
        "layers": config.layers,
        "ontology_routing": config.ontology_routing,
        "widget_overrides": config.widget_overrides,
        "globally_hidden_slots": config.globally_hidden_slots,
        "slot_help_text": config.slot_help_text,
    }


class FormBuilderExportView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: download this schema's SchemaUIConfig as loom_ui.yaml-
    shaped YAML, for editing offline or copying to another schema."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def get(self, request, pk):
        sv = get_object_or_404(SchemaVersion, pk=pk)
        config = SchemaUIConfig.for_schema_version(sv)
        yaml_text = yaml.safe_dump(_config_yaml_dict(config), sort_keys=False)

        response = HttpResponse(yaml_text, content_type="application/x-yaml")
        response["Content-Disposition"] = (
            f'attachment; filename="form_config_{sv.version}.yaml"'
        )
        return response


class FormBuilderImportView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Staff-only: upload a loom_ui.yaml-shaped YAML file to replace this
    schema's schema-level SchemaUIConfig. Every slot name referenced by a
    layer must exist in this schema, or the whole import is rejected."""

    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff

    def post(self, request, pk):
        sv = get_object_or_404(SchemaVersion, pk=pk)
        upload = request.FILES.get("config_file")
        if not upload:
            return JsonResponse(
                {"errors": ["Choose a config YAML file to upload."]}, status=400
            )

        try:
            data = yaml.safe_load(upload.read())
        except yaml.YAMLError as exc:
            return JsonResponse({"errors": [f"Invalid YAML: {exc}"]}, status=400)

        if not isinstance(data, dict):
            return JsonResponse(
                {"errors": ["Config file must be a YAML mapping."]}, status=400
            )

        known_slots = set(LoomSchemaView(sv).all_slots())
        errors = []
        for layer in data.get("layers") or []:
            layer_name = layer.get("label") or layer.get("id") or "(unnamed layer)"
            for slot_name in layer.get("slots") or []:
                if slot_name not in known_slots:
                    errors.append(
                        f"Unknown slot {slot_name!r} in layer {layer_name!r}: "
                        f"not defined on any class in schema {sv.version}."
                    )
        if errors:
            return JsonResponse({"errors": errors}, status=400)

        SchemaUIConfig.objects.update_or_create(
            schema_version=sv,
            project=None,
            defaults={
                "layers": data.get("layers") or [],
                "ontology_routing": data.get("ontology_routing") or {},
                "widget_overrides": data.get("widget_overrides") or {},
                "globally_hidden_slots": data.get("globally_hidden_slots") or [],
                "slot_help_text": data.get("slot_help_text") or {},
            },
        )
        invalidate_cache(sv.pk)
        return JsonResponse({"ok": True})
