"""
Unit tests for apps.export.renderers.render_graph_preview.

Pure Python — no database. Fixtures are dicts shaped like serialize_graph()
output: nodes carry `node_id` (+ optionally the CURIE `id` from node.data),
edges link via `subject`/`object` == `node_id`.
"""

from apps.export.renderers import render_graph_preview


def _node(node_id, name, entity_type=None, **extra):
    node = {"node_id": node_id, "name": name}
    if entity_type is not None:
        node["entity_type"] = entity_type
    node.update(extra)
    return node


def _edge(edge_id, subject, obj, predicate=None, **extra):
    edge = {"edge_id": edge_id, "subject": subject, "object": obj}
    if predicate is not None:
        edge["predicate"] = predicate
    edge.update(extra)
    return edge


def test_happy_path():
    data = {
        "graph_id": "7",
        "nodes": [
            _node("n-a", "Seed addition", "management_intervention"),
            _node("n-b", "Forb richness", "taxon"),
        ],
        "edges": [_edge("e-1", "n-a", "n-b", "causes")],
    }
    out = render_graph_preview(data)

    assert out["counts"] == {"nodes": 2, "edges": 1}
    assert {n["id"] for n in out["nodes"]} == {"n-a", "n-b"}
    assert out["edges"][0]["from"] == "n-a"
    assert out["edges"][0]["to"] == "n-b"
    assert out["edges"][0]["label"] == "causes"
    assert out["node_group_counts"] == {"management_intervention": 1, "taxon": 1}
    assert out["edge_group_counts"] == {"causes": 1}
    assert out["node_groups"] == ["management_intervention", "taxon"]
    assert out["warnings"] == []


def test_edges_keyed_on_node_id_not_curie():
    """Edge endpoints reference node_id, even when a CURIE `id` is also present."""
    data = {
        "nodes": [
            {"node_id": "n-a", "id": "causal_mosaic:seed_addition", "name": "A"},
            {"node_id": "n-b", "id": "causal_mosaic:richness", "name": "B"},
        ],
        "edges": [_edge("e-1", "n-a", "n-b", "causes")],
    }
    out = render_graph_preview(data)

    assert out["counts"] == {"nodes": 2, "edges": 1}
    assert all(not n["placeholder"] for n in out["nodes"])
    assert not any("undefined node" in w for w in out["warnings"])


def test_empty_graph():
    out = render_graph_preview({"nodes": [], "edges": []})
    assert out["nodes"] == []
    assert out["edges"] == []
    assert out["counts"] == {"nodes": 0, "edges": 0}
    assert any("empty" in w for w in out["warnings"])


def test_edge_missing_predicate():
    data = {
        "nodes": [_node("n-a", "A"), _node("n-b", "B")],
        "edges": [{"edge_id": "e-1", "subject": "n-a", "object": "n-b"}],
    }
    out = render_graph_preview(data)
    assert out["edges"][0]["label"] == "unspecified"
    assert out["edges"][0]["group"] == "unspecified"
    assert out["edge_group_counts"] == {"unspecified": 1}


def test_node_missing_entity_type():
    data = {
        "nodes": [
            {"node_id": "n-a", "name": "A"},
            {"node_id": "n-b", "name": "B", "entity_type": ""},
        ],
        "edges": [],
    }
    out = render_graph_preview(data)
    assert all(n["group"] == "unspecified" for n in out["nodes"])
    assert out["node_group_counts"] == {"unspecified": 2}


def test_dangling_endpoint():
    data = {
        "nodes": [_node("n-a", "A", "taxon")],
        "edges": [_edge("e-1", "n-a", "n-missing", "causes")],
    }
    out = render_graph_preview(data)

    placeholder = [n for n in out["nodes"] if n["placeholder"]]
    assert len(placeholder) == 1
    assert placeholder[0]["id"] == "n-missing"
    assert placeholder[0]["group"] == "missing"
    assert out["counts"]["edges"] == 1
    assert any("n-missing" in w for w in out["warnings"])


def test_subject_object_fallback_keys():
    data = {
        "nodes": [_node("n-a", "A"), _node("n-b", "B")],
        "edges": [
            {"edge_id": "e-1", "source": "n-a", "target": "n-b", "relation": "linked"}
        ],
    }
    out = render_graph_preview(data)
    assert out["edges"][0]["from"] == "n-a"
    assert out["edges"][0]["to"] == "n-b"
    assert out["edges"][0]["label"] == "linked"


def test_group_lists_sorted_and_deduped():
    data = {
        "nodes": [
            _node("n-a", "A", "taxon"),
            _node("n-a", "A repeated", "environmental_variable"),
            _node("n-b", "B", "management_intervention"),
        ],
        "edges": [],
    }
    out = render_graph_preview(data)

    assert out["counts"]["nodes"] == 2
    assert out["node_groups"] == ["environmental_variable", "management_intervention"]
    assert "taxon" not in out["node_group_counts"]
    assert any("Duplicate node id" in w for w in out["warnings"])


def test_node_without_identifier_skipped():
    data = {
        "nodes": [{"entity_type": "taxon"}, _node("n-b", "B")],
        "edges": [],
    }
    out = render_graph_preview(data)
    assert out["counts"]["nodes"] == 1
    assert out["nodes"][0]["id"] == "n-b"
    assert any("no identifier" in w for w in out["warnings"])


def test_node_id_falls_back_to_curie_then_name():
    data = {
        "nodes": [
            {"id": "causal_mosaic:only_curie", "name": "Curie node"},
            {"name": "Name only"},
        ],
        "edges": [],
    }
    out = render_graph_preview(data)
    assert {n["id"] for n in out["nodes"]} == {"causal_mosaic:only_curie", "Name only"}
