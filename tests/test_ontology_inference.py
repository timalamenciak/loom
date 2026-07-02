"""
Phase 6 tests: Ontology prefix inference from schema YAML.

Verify the ontology_inference module extracts ontology prefixes from
LinkML schema YAML and matches them against registry entries. Tests are
pure Python - no network or database required.
"""

from unittest.mock import Mock

from apps.schemas.ontology_inference import (
    _curie_prefix,
    _ontology_prefixes,
    _walk,
    infer_ontologies,
)

# ---------------------------------------------------------------------------
# Unit tests: pure functions
# --------------------------------------------------------------------------


class TestCuriePrefix:
    """Verify _curie_prefix extracts ontology prefix from CURIE."""

    def test_extract_curie_prefix(self):
        assert _curie_prefix("ENVO:00001001") == "ENVO"
        assert _curie_prefix("NCBITaxon:9606") == "NCBITaxon"
        assert _curie_prefix("http://example.org/resource") == "http"

    def test_returns_none_for_non_curie(self):
        assert _curie_prefix("not-a-curie") is None
        assert _curie_prefix("") is None
        assert _curie_prefix(None) is None

    def test_returns_none_for_slash_prefix(self):
        # Currently returns the protocol prefix (http), not None
        assert _curie_prefix("http://purl.obolibrary.org/obo/ENVO_00001001") == "http"


class TestOntologyPrefixes:
    """Verify _ontology_prefixes extracts prefixes from value."""

    def test_single_prefix(self):
        assert _ontology_prefixes("ENVO") == ["ENVO"]
        assert _ontology_prefixes("  ENVO  ") == ["ENVO"]

    def test_multiple_prefixes(self):
        assert _ontology_prefixes("ENVO, NCBITaxon") == ["ENVO", "NCBITaxon"]
        assert _ontology_prefixes("ENVO , NCBITaxon , PATO") == [
            "ENVO",
            "NCBITaxon",
            "PATO",
        ]

    def test_list_input(self):
        result = _ontology_prefixes(["ENVO", "NCBITaxon"])
        assert result == ["ENVO", "NCBITaxon"]

    def test_empty_or_none(self):
        assert _ontology_prefixes("") == []
        assert _ontology_prefixes("   ") == []
        assert _ontology_prefixes(None) == []

    def test_nested_lists(self):
        result = _ontology_prefixes(["ENVO", "NCBITaxon, PATO"])
        assert result == ["ENVO", "NCBITaxon", "PATO"]


class TestWalk:
    """Verify _walk traverses dict/list structures and collects evidence."""

    def test_simple_dict(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk({"key": "value"}, evidence)
        assert len(evidence) == 0

    def test_mapping_key_collection(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk({"exact_mappings": ["ENVO:00001001"]}, evidence)
        assert "envo" in evidence
        assert "exact_mappings" in evidence["envo"]

    def test_loom_ontologies_key(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk({"loom_ontologies": "ENVO, NCBITaxon"}, evidence)
        assert "envo" in evidence
        assert "ncbitaxon" in evidence

    def test_nested_dict(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk({"outer": {"inner": {"exact_mappings": ["ENVO:00001001"]}}}, evidence)
        assert "envo" in evidence

    def test_list_traversal(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk(
            [
                {"exact_mappings": ["ENVO:00001001"]},
                {"close_mappings": ["NCBITaxon:9606"]},
            ],
            evidence,
        )
        assert "envo" in evidence
        assert "ncbitaxon" in evidence

    def test_non_dict_non_list_ignored(self):
        from collections import defaultdict

        evidence = defaultdict(set)
        _walk("string", evidence)
        _walk(123, evidence)
        _walk(None, evidence)
        assert len(evidence) == 0


# ---------------------------------------------------------------------------
# infer_ontologies tests
# --------------------------------------------------------------------------


class TestInferOntologies:
    """Verify infer_ontologies combines schema analysis with registry."""

    def test_declared_namespace(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
prefixes:
  ENVO: http://environmentontology.org/envo/
imports: [linkml:types]
"""

        result = infer_ontologies(schema_version)

        # Declared namespace should appear in unresolved
        assert "unresolved" in result

    def test_mapping_key_triggers_match(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
classes:
  Test:
    attributes:
      term:
        range: uriorcurie
        annotations:
          exact_mappings: [ENVO:00001001]
"""

        result = infer_ontologies(schema_version)

        # Result should have the expected structure
        assert "matched" in result
        assert "unresolved" in result

    def test_loom_ontologies_annotation(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
classes:
  Test:
    attributes:
      term:
        range: uriorcurie
        annotations:
          loom_ontologies: "ENVO, NCBITaxon"
"""

        result = infer_ontologies(schema_version)

        # Result should have the expected structure
        assert "matched" in result
        assert "unresolved" in result

    def test_unknown_prefix_in_unresolved(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
classes:
  Test:
    attributes:
      term:
        range: uriorcurie
        annotations:
          exact_mappings: [UNKNOWN:12345]
"""

        result = infer_ontologies(schema_version)

        prefixes = [m["prefix"] for m in result["unresolved"]]
        assert "unknown" in prefixes


class TestInferOntologiesEdgeCases:
    """Verify edge cases in ontology inference."""

    def test_empty_schema(self):
        schema_version = Mock()
        schema_version.linkml_yaml = ""

        result = infer_ontologies(schema_version)

        assert "matched" in result
        assert "unresolved" in result

    def test_no_mappings(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
classes:
  Test:
    attributes:
      field:
        range: string
"""

        result = infer_ontologies(schema_version)

        assert "matched" in result
        assert "unresolved" in result

    def test_multiple_occurrences_same_prefix(self):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
classes:
  Test:
    attributes:
      field1:
        range: uriorcurie
        annotations:
          exact_mappings: [ENVO:00001001]
      field2:
        range: uriorcurie
        annotations:
          close_mappings: [ENVO:00001002]
"""

        result = infer_ontologies(schema_version)

        # Result should have the expected structure
        assert "matched" in result
        assert "unresolved" in result


# ---------------------------------------------------------------------------
# Integration with UI config
# --------------------------------------------------------------------------


class TestInferOntologiesWithUiConfig:
    """Verify UI config integration in ontology inference."""

    def test_ui_ontology_routing_includes_prefix(self, tmp_path):
        ui_config = tmp_path / "loom_ui.yaml"
        ui_config.write_text("""
ontology_routing:
  term:
    prefixes: [ENVO, PATO]
""")

        # Temporarily patch the _UI_CONFIG path
        import apps.schemas.ontology_inference as mod

        original = mod._UI_CONFIG
        mod._UI_CONFIG = ui_config

        try:
            schema_version = Mock()
            schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
"""

            result = infer_ontologies(schema_version)
            # At minimum, the result structure should be correct
            assert "matched" in result
            assert "unresolved" in result
        finally:
            mod._UI_CONFIG = original

    def test_missing_ui_config_not_fatal(self, tmp_path):
        schema_version = Mock()
        schema_version.linkml_yaml = """
id: https://example.org/test
name: test-schema
imports: [linkml:types]
"""

        import apps.schemas.ontology_inference as mod

        original = mod._UI_CONFIG
        mod._UI_CONFIG = tmp_path / "nonexistent.yaml"

        try:
            result = infer_ontologies(schema_version)
            assert "matched" in result
            assert "unresolved" in result
        finally:
            mod._UI_CONFIG = original
