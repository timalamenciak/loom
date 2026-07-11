"""Tests for the staff-only SchemaUploadView (apps/schemas/views.py)."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.schemas.models import SchemaVersion
from tests.schema_fixtures import latest_schema_path

User = get_user_model()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user("schema-uploader", password="x", is_staff=True)


@pytest.fixture
def regular_user(db):
    return User.objects.create_user("schema-uploader-non-staff", password="x")


class TestSchemaUploadView:
    def test_upload_valid_yaml(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        content = latest_schema_path().read_text(encoding="utf-8")
        upload = SimpleUploadedFile(
            "camo.yaml", content.encode("utf-8"), content_type="application/x-yaml"
        )

        response = client.post(reverse("schema-upload"), {"schema_file": upload})

        assert response.status_code == 302
        assert SchemaVersion.objects.count() == 1

    def test_upload_invalid_yaml(self, db, staff_user):
        client = Client()
        client.force_login(staff_user)
        garbage = SimpleUploadedFile(
            "garbage.yaml",
            b"this is definitely not a valid linkml schema {{{ [[[",
            content_type="application/x-yaml",
        )

        response = client.post(reverse("schema-upload"), {"schema_file": garbage})

        assert response.status_code == 200
        assert SchemaVersion.objects.count() == 0

    def test_upload_requires_staff(self, db, regular_user):
        client = Client()
        client.force_login(regular_user)
        content = latest_schema_path().read_text(encoding="utf-8")
        upload = SimpleUploadedFile(
            "camo.yaml", content.encode("utf-8"), content_type="application/x-yaml"
        )

        response = client.post(reverse("schema-upload"), {"schema_file": upload})

        assert response.status_code == 403
        assert SchemaVersion.objects.count() == 0
