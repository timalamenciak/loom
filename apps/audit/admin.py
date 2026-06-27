from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["ts", "actor", "action", "target_type", "target_id"]
    list_filter = ["action", "target_type"]
    readonly_fields = ["ts", "actor", "action", "target_type", "target_id", "diff"]
    ordering = ["-ts"]
    date_hierarchy = "ts"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
