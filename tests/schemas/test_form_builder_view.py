"""Tests for the staff-only FormBuilderView/FormBuilderSaveView
(apps/schemas/views.py)."""

import html
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.ontology.models import OntologyRelease
from apps.schemas.models import SchemaUIConfig, SchemaVersion
from tests.schema_fixtures import latest_schema_path

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user("form-builder-staff", password="x", is_staff=True)


@pytest.fixture
def schema_version(db):
    content = latest_schema_path().read_text(encoding="utf-8")
    return SchemaVersion.objects.create(
        version="form-builder-test", linkml_yaml=content
    )


class TestFormBuilderView:
    def test_form_builder_get_200(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("schema-form-builder", kwargs={"pk": schema_version.pk})
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "claim_strength" in body
        assert "original_sentence" in body

    def test_form_builder_get_includes_ready_ontology_choices(
        self, staff_user, schema_version
    ):
        OntologyRelease.objects.create(
            name="envo",
            prefix="ENVO",
            source_url="https://example.org/envo.obo",
            status=OntologyRelease.STATUS_READY,
        )
        OntologyRelease.objects.create(
            name="chebi",
            prefix="CHEBI",
            source_url="https://example.org/chebi.obo",
            status=OntologyRelease.STATUS_LOADING,
        )
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("schema-form-builder", kwargs={"pk": schema_version.pk})
        )

        assert response.status_code == 200
        # form_builder.html embeds the JSON inside a <script> block without
        # |safe, so Django HTML-escapes the quotes (harmless — the browser's
        # JSON.parse(el.textContent) sees the un-escaped text); unescape here
        # to check content rather than hand-writing the escaped form.
        body = html.unescape(response.content.decode())
        assert '"prefix": "ENVO"' in body
        assert '"CHEBI"' not in body


def _slot(name, *, hidden=False, widget="", help_text="", ontology_sources=None):
    return {
        "name": name,
        "hidden": hidden,
        "widget": widget,
        "help_text": help_text,
        "required_override": None,
        "ontology_sources": ontology_sources or [],
    }


class TestFormBuilderSaveView:
    def test_save_creates_config(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)

        payload = {
            "layers": [
                {
                    "name": "Claim Basics",
                    "slots": [
                        _slot(
                            "claim_strength",
                            widget="select",
                            help_text="How strong is the claim?",
                        ),
                        _slot("original_sentence", hidden=True),
                    ],
                }
            ],
            "unassigned": ["predicate"],
        }

        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert SchemaUIConfig.objects.filter(schema_version=schema_version).count() == 1
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert [layer["slots"] for layer in config.layers] == [
            ["claim_strength", "original_sentence"]
        ]
        assert config.widget_overrides == {"claim_strength": "select"}
        assert config.globally_hidden_slots == ["original_sentence"]
        assert config.slot_help_text == {"claim_strength": "How strong is the claim?"}

    def test_save_updates_existing(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)
        url = reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk})

        first = {
            "layers": [
                {"name": "Section A", "slots": [_slot("claim_strength")]},
            ],
            "unassigned": [],
        }
        client.post(url, data=json.dumps(first), content_type="application/json")
        assert SchemaUIConfig.objects.filter(schema_version=schema_version).count() == 1

        second = {
            "layers": [
                {"name": "Section B", "slots": [_slot("predicate", hidden=True)]},
            ],
            "unassigned": [],
        }
        response = client.post(
            url, data=json.dumps(second), content_type="application/json"
        )

        assert response.status_code == 200
        assert SchemaUIConfig.objects.filter(schema_version=schema_version).count() == 1
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert [layer["slots"] for layer in config.layers] == [["predicate"]]
        assert config.globally_hidden_slots == ["predicate"]

    def test_save_persists_ontology_routing(self, staff_user, schema_version):
        # Start from an explicit empty DB row rather than relying on
        # SchemaUIConfig.for_schema_version()'s config/loom_ui.yaml fallback,
        # so the assertion below isn't coupled to that file's current content.
        SchemaUIConfig.objects.create(
            schema_version=schema_version, project=None, ontology_routing={}
        )
        client = Client()
        client.force_login(staff_user)

        payload = {
            "layers": [
                {
                    "name": "Claim Basics",
                    "slots": [
                        _slot("claim_strength", ontology_sources=["ENVO", "ELMO"]),
                    ],
                }
            ],
            "unassigned": [],
        }

        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 200
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert config.ontology_routing == {
            "claim_strength": [{"prefix": "ENVO"}, {"prefix": "ELMO"}]
        }

    def test_save_preserves_conditional_routing_for_untouched_slot(
        self, staff_user, schema_version
    ):
        """entity_term's condition_slot routing isn't representable in the
        builder's plain multi-select — saving edits to an unrelated slot must
        not wipe it out."""
        SchemaUIConfig.objects.create(
            schema_version=schema_version,
            project=None,
            ontology_routing={
                "entity_term": {
                    "condition_slot": "entity_type",
                    "allow_free_text": True,
                    "routes": {"taxon": {"wikidata_live": {"root_qid": "Q16521"}}},
                    "default": {"prefixes": ["ENVO"]},
                }
            },
        )
        client = Client()
        client.force_login(staff_user)

        payload = {
            "layers": [
                {
                    "name": "Claim Basics",
                    "slots": [_slot("claim_strength", ontology_sources=["PATO"])],
                }
            ],
            "unassigned": [],
        }
        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 200
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert config.ontology_routing["claim_strength"] == [{"prefix": "PATO"}]
        assert config.ontology_routing["entity_term"]["condition_slot"] == "entity_type"

    def test_save_clears_previously_simple_routing(self, staff_user, schema_version):
        SchemaUIConfig.objects.create(
            schema_version=schema_version,
            project=None,
            ontology_routing={"measured_attribute": [{"prefix": "PATO"}]},
        )
        client = Client()
        client.force_login(staff_user)

        payload = {
            "layers": [
                {
                    "name": "Section A",
                    "slots": [_slot("measured_attribute", ontology_sources=[])],
                }
            ],
            "unassigned": [],
        }
        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps(payload),
            content_type="application/json",
        )

        assert response.status_code == 200
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert "measured_attribute" not in config.ontology_routing

    def test_save_requires_staff(self, db, schema_version):
        client = Client()  # anonymous — never logged in

        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps({"layers": [], "unassigned": []}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not SchemaUIConfig.objects.filter(schema_version=schema_version).exists()
