from django.contrib import admin

from .models import SchemaVersion


@admin.register(SchemaVersion)
class SchemaVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "is_active", "sha256_short", "loaded_at"]
    list_filter = ["is_active"]
    readonly_fields = ["sha256", "loaded_at"]
    actions = ["set_active"]

    @admin.display(description="SHA-256")
    def sha256_short(self, obj):
        return obj.sha256[:12] + "…" if obj.sha256 else ""

    @admin.action(description="Set selected schema as active")
    def set_active(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one schema to activate.", level="error")
            return
        sv = queryset.first()
        sv.is_active = True
        sv.save()
        self.message_user(request, f"CAMO {sv.version} is now active.")
