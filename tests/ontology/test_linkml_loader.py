"""Tests for the LinkML-schema branch of apps.ontology.loaders.load_ontology_release."""

from unittest.mock import patch

from apps.ontology import loaders
from apps.ontology.models import OntologyRelease, OntologyTerm

MINI_LINKML = b"""\
id: https://example.org/test-schema
name: test-schema
prefixes:
  linkml: https://w3id.org/linkml/
default_range: string
imports:
  - linkml:types
enums:
  ClaimStrength:
    permissible_values:
      Weak:
        description: "A weak causal claim."
      Moderate:
        description: "A moderate causal claim."
      Strong:
        description: "A strong causal claim."
  EvidenceType:
    permissible_values:
      Observational:
        description: "Observational evidence."
      Experimental:
        description: "Experimental evidence."
      Modeled:
        description: "Modeled evidence."
      Expert:
        description: "Expert opinion evidence."
"""

MINI_OBO = b"""\
format-version: 1.2
ontology: test

[Term]
id: TEST:1
name: first term
def: "A definition." []

[Term]
id: TEST:2
name: second term
"""


def _config(name="test", prefix="TEST", **extra):
    return {
        "name": name,
        "prefix": prefix,
        "url": f"https://example.org/{name}",
        **extra,
    }


def test_linkml_load_creates_terms(db):
    config = _config()
    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "_read_source", return_value=MINI_LINKML),
    ):
        release, count = loaders.load_ontology_release("test")

    assert count == 7
    assert release.term_count == 7
    assert release.status == OntologyRelease.STATUS_READY

    curies = set(
        OntologyTerm.objects.filter(release=release).values_list("curie", flat=True)
    )
    assert curies == {
        "ClaimStrength:Weak",
        "ClaimStrength:Moderate",
        "ClaimStrength:Strong",
        "EvidenceType:Observational",
        "EvidenceType:Experimental",
        "EvidenceType:Modeled",
        "EvidenceType:Expert",
    }

    strong = OntologyTerm.objects.get(release=release, curie="ClaimStrength:Strong")
    assert strong.label == "Strong"
    assert strong.definition == "A strong causal claim."
    assert strong.prefix == "ClaimStrength"


def test_linkml_load_root_terms_filter(db):
    config = _config(root_terms=["ClaimStrength"])
    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "_read_source", return_value=MINI_LINKML),
    ):
        release, count = loaders.load_ontology_release("test")

    assert count == 3
    curies = set(
        OntologyTerm.objects.filter(release=release).values_list("curie", flat=True)
    )
    assert curies == {
        "ClaimStrength:Weak",
        "ClaimStrength:Moderate",
        "ClaimStrength:Strong",
    }


def test_obo_path_unchanged(db):
    config = _config()
    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "_read_source", return_value=MINI_OBO),
    ):
        release, count = loaders.load_ontology_release("test")

    assert count == 2
    assert release.term_count == 2
    assert release.status == OntologyRelease.STATUS_READY
    curies = set(
        OntologyTerm.objects.filter(release=release).values_list("curie", flat=True)
    )
    assert curies == {"TEST:1", "TEST:2"}
