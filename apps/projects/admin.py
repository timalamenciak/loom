from django.contrib import admin

from .models import Assignment, Document, Project, ProjectMembership


class MembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 1
    autocomplete_fields = ["user"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at"]
    search_fields = ["name"]
    inlines = [MembershipInline]
    raw_id_fields = ["created_by"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "source", "has_pdf", "year", "doi"]
    list_filter = ["project", "source"]
    search_fields = ["title", "doi"]
    readonly_fields = ["sha256", "created_at", "updated_at"]

    @admin.display(boolean=True)
    def has_pdf(self, obj):
        return obj.has_pdf


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["document", "annotator", "project", "status", "assigned_at", "updated_at"]
    list_filter = ["project", "status"]
    search_fields = ["document__title", "annotator__username"]
    raw_id_fields = ["document", "annotator", "assigned_by"]
