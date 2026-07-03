from django.contrib import admin

from .models import (
    OntologyLoadItem,
    OntologyLoadRequest,
    OntologyRelease,
    OntologySnapshot,
    OntologyTerm,
    OntologyTermSuggestion,
)


@admin.register(OntologyRelease)
class OntologyReleaseAdmin(admin.ModelAdmin):
    list_display = ["prefix", "name", "status", "term_count", "loaded_at"]
    list_filter = ["status", "prefix"]
    readonly_fields = ["source_sha256", "loaded_at", "term_count"]


@admin.register(OntologySnapshot)
class OntologySnapshotAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "built_at", "prefix_summary"]
    list_filter = ["is_active"]
    readonly_fields = ["built_at", "source_versions", "manifest_sha256"]
    actions = ["set_active"]

    @admin.display(description="Prefixes loaded")
    def prefix_summary(self, obj):
        return ", ".join(obj.source_versions.keys()) or "—"

    @admin.action(description="Set as active snapshot")
    def set_active(self, request, queryset):
        for snap in queryset:
            snap.is_active = True
            snap.save()
        self.message_user(request, f"Activated {queryset.count()} snapshot(s).")


@admin.register(OntologyTerm)
class OntologyTermAdmin(admin.ModelAdmin):
    list_display = ["curie", "label", "prefix", "obsolete", "release", "snapshot"]
    list_filter = ["prefix", "obsolete", "release", "snapshot"]
    search_fields = ["curie", "label", "synonym_labels"]
    readonly_fields = ["snapshot", "release", "curie", "prefix"]


@admin.register(OntologyLoadRequest)
class OntologyLoadRequestAdmin(admin.ModelAdmin):
    list_display = ["project", "status", "requested_by", "created_at", "finished_at"]
    list_filter = ["status"]
    readonly_fields = ["created_at", "started_at", "finished_at", "error"]


@admin.register(OntologyLoadItem)
class OntologyLoadItemAdmin(admin.ModelAdmin):
    list_display = ["request", "name", "prefix", "status", "term_count"]
    list_filter = ["status", "prefix"]
    search_fields = ["name", "prefix", "error"]


@admin.register(OntologyTermSuggestion)
class OntologyTermSuggestionAdmin(admin.ModelAdmin):
    list_display = [
        "label",
        "target_ontology",
        "project",
        "created_by",
        "status",
        "created_at",
    ]
    list_filter = ["status", "target_ontology"]
    search_fields = ["label", "suggested_parent", "definition"]
    readonly_fields = ["project", "graph", "created_by", "slot_name", "created_at"]
    actions = ["mark_submitted_upstream", "mark_resolved"]

    @admin.action(description="Mark as submitted upstream")
    def mark_submitted_upstream(self, request, queryset):
        queryset.update(status=OntologyTermSuggestion.STATUS_SUBMITTED)

    @admin.action(description="Mark as resolved")
    def mark_resolved(self, request, queryset):
        from django.utils import timezone

        queryset.update(
            status=OntologyTermSuggestion.STATUS_RESOLVED, resolved_at=timezone.now()
        )
