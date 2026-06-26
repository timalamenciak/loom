from django.contrib import admin

from .models import CausalGraph, Edge, Node


class NodeInline(admin.TabularInline):
    model = Node
    extra = 0
    fields = ["node_id", "name", "category", "origin", "created_at"]
    readonly_fields = ["node_id", "created_at"]


class EdgeInline(admin.TabularInline):
    model = Edge
    extra = 0
    fields = ["edge_id", "subject", "object", "predicate", "status", "origin"]
    readonly_fields = ["edge_id"]
    raw_id_fields = ["subject", "object"]


@admin.register(CausalGraph)
class CausalGraphAdmin(admin.ModelAdmin):
    list_display = ["__str__", "document", "annotator", "schema_version", "status", "created_at"]
    list_filter = ["status", "schema_version"]
    search_fields = ["document__title", "annotator__username"]
    inlines = [NodeInline, EdgeInline]
    raw_id_fields = ["document", "annotator"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ["name", "graph", "category", "origin", "created_at"]
    list_filter = ["origin", "category"]
    search_fields = ["name", "node_id"]
    readonly_fields = ["node_id", "created_at"]


@admin.register(Edge)
class EdgeAdmin(admin.ModelAdmin):
    list_display = ["__str__", "graph", "predicate", "claim_strength", "status", "origin"]
    list_filter = ["status", "origin", "predicate"]
    raw_id_fields = ["subject", "object"]
    readonly_fields = ["edge_id", "created_at", "updated_at"]
