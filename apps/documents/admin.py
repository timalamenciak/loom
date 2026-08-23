from django.contrib import admin

from .models import TextSpan


@admin.register(TextSpan)
class TextSpanAdmin(admin.ModelAdmin):
    list_display = [
        "document",
        "start_char",
        "end_char",
        "text_excerpt",
        "created_at",
    ]
    search_fields = ["text", "document__title"]
    raw_id_fields = ["document", "created_by"]
    filter_horizontal = ["nodes", "edges"]
    readonly_fields = ["created_at"]

    @admin.display(description="Text")
    def text_excerpt(self, obj):
        return obj.text[:60]
