from django.contrib import admin

from .models import OntologySnapshot, OntologyTerm


@admin.register(OntologySnapshot)
class OntologySnapshotAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "built_at", "prefix_summary"]
    list_filter = ["is_active"]
    readonly_fields = ["built_at", "source_versions"]
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
    list_display = ["curie", "label", "prefix", "obsolete", "snapshot"]
    list_filter = ["prefix", "obsolete", "snapshot"]
    search_fields = ["curie", "label", "synonym_labels"]
    readonly_fields = ["snapshot", "curie", "prefix"]
