"""Tests for the staff-only FormBuilderView/FormBuilderSaveView
(apps/schemas/views.py)."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.schemas.models import SchemaUIConfig, SchemaVersion
from tests.schema_fixtures import latest_schema_path

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user("form-builder-staff", password="x", is_staff=True)


@pytest.fixture
def schema_version(db):
    content = latest_schema_path().read_text(encoding="utf-8")
    return SchemaVersion.objects.create(version="form-builder-test", linkml_yaml=content)


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


def _slot(name, *, hidden=False, widget="", help_text=""):
    return {
        "name": name,
        "hidden": hidden,
        "widget": widget,
        "help_text": help_text,
        "required_override": None,
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
        response = client.post(url, data=json.dumps(second), content_type="application/json")

        assert response.status_code == 200
        assert SchemaUIConfig.objects.filter(schema_version=schema_version).count() == 1
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert [layer["slots"] for layer in config.layers] == [["predicate"]]
        assert config.globally_hidden_slots == ["predicate"]

    def test_save_requires_staff(self, db, schema_version):
        client = Client()  # anonymous — never logged in

        response = client.post(
            reverse("schema-form-builder-save", kwargs={"pk": schema_version.pk}),
            data=json.dumps({"layers": [], "unassigned": []}),
            content_type="application/json",
        )

        assert response.status_code == 403
        assert not SchemaUIConfig.objects.filter(schema_version=schema_version).exists()
