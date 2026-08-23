"""Tests for FormBuilderExportView / FormBuilderImportView
(apps/schemas/views.py)."""

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.schemas.models import SchemaUIConfig, SchemaVersion
from tests.schema_fixtures import latest_schema_path

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        "form-builder-io-staff", password="x", is_staff=True
    )


@pytest.fixture
def schema_version(db):
    content = latest_schema_path().read_text(encoding="utf-8")
    return SchemaVersion.objects.create(
        version="form-builder-io-test", linkml_yaml=content
    )


class TestFormBuilderExportView:
    def test_export_yaml_parseable(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)

        response = client.get(
            reverse("schema-form-builder-export", kwargs={"pk": schema_version.pk})
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/x-yaml"
        assert "attachment" in response["Content-Disposition"]
        assert (
            f"form_config_{schema_version.version}.yaml"
            in response["Content-Disposition"]
        )

        data = yaml.safe_load(response.content.decode())
        assert isinstance(data, dict)
        for key in (
            "layers",
            "ontology_routing",
            "widget_overrides",
            "globally_hidden_slots",
            "slot_help_text",
        ):
            assert key in data


class TestFormBuilderImportView:
    def test_import_valid_yaml(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)

        config_yaml = yaml.safe_dump(
            {
                "layers": [
                    {"id": "claims", "label": "Claims", "slots": ["claim_strength"]},
                ],
                "ontology_routing": {},
                "widget_overrides": {"claim_strength": "select"},
                "globally_hidden_slots": ["original_sentence"],
                "slot_help_text": {"claim_strength": "How strong is the claim?"},
            }
        )
        upload = SimpleUploadedFile(
            "config.yaml",
            config_yaml.encode("utf-8"),
            content_type="application/x-yaml",
        )

        response = client.post(
            reverse("schema-form-builder-import", kwargs={"pk": schema_version.pk}),
            {"config_file": upload},
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        config = SchemaUIConfig.objects.get(schema_version=schema_version, project=None)
        assert config.layers == [
            {"id": "claims", "label": "Claims", "slots": ["claim_strength"]}
        ]
        assert config.widget_overrides == {"claim_strength": "select"}
        assert config.globally_hidden_slots == ["original_sentence"]
        assert config.slot_help_text == {"claim_strength": "How strong is the claim?"}

    def test_import_unknown_slots(self, staff_user, schema_version):
        client = Client()
        client.force_login(staff_user)

        config_yaml = yaml.safe_dump(
            {
                "layers": [
                    {
                        "id": "bogus",
                        "label": "Bogus",
                        "slots": ["this_slot_does_not_exist"],
                    },
                ],
            }
        )
        upload = SimpleUploadedFile(
            "config.yaml",
            config_yaml.encode("utf-8"),
            content_type="application/x-yaml",
        )

        response = client.post(
            reverse("schema-form-builder-import", kwargs={"pk": schema_version.pk}),
            {"config_file": upload},
        )

        assert response.status_code == 400
        body = response.json()
        assert "errors" in body
        assert any("this_slot_does_not_exist" in err for err in body["errors"])
        assert not SchemaUIConfig.objects.filter(schema_version=schema_version).exists()
