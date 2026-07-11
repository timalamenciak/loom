"""Tests for the staff-only pending-updates notification banner.

The banner is rendered in templates/base.html from the `pending_updates`
context processor (apps/schemas/context_processors.py), so any page that
extends base.html carries it — exercised here via the plain `home` view.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.schemas.models import UpdateCheckRecord


class TestUpdateBanner:
    def test_banner_shown_when_updates_exist(self, client, db):
        UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        staff = get_user_model().objects.create_user(
            "staff-user", password="x", is_staff=True
        )
        client.force_login(staff)

        response = client.get(reverse("home"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "update available" in content.lower()
        assert "camo" in content
        assert "0.8.0" in content

    def test_banner_hidden_for_annotators(self, client, db):
        UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        annotator = get_user_model().objects.create_user(
            "annotator-user", password="x", is_staff=False
        )
        client.force_login(annotator)

        response = client.get(reverse("home"))

        assert response.status_code == 200
        content = response.content.decode()
        assert "update available" not in content.lower()
        assert "0.8.0" not in content

    def test_dismiss_via_htmx_returns_204(self, client, db):
        """The base.html banner posts with hx-swap="none" — htmx tags the
        request with HX-Request, and the view responds 204 with no body so
        Alpine's client-side hide is all that changes the DOM."""
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        staff = get_user_model().objects.create_user(
            "staff-dismisser", password="x", is_staff=True
        )
        client.force_login(staff)

        dismiss_response = client.post(
            reverse("dismiss-update", args=[record.pk]), HTTP_HX_REQUEST="true"
        )
        assert dismiss_response.status_code == 204

        response = client.get(reverse("home"))
        assert "0.8.0" not in response.content.decode()

    def test_dismiss_via_plain_form_redirects(self, client, db):
        """The update-diff page's Dismiss button is a plain (non-htmx) form
        submit, so it needs a real redirect to go anywhere."""
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        staff = get_user_model().objects.create_user(
            "staff-dismisser-plain", password="x", is_staff=True
        )
        client.force_login(staff)

        dismiss_response = client.post(reverse("dismiss-update", args=[record.pk]))
        assert dismiss_response.status_code == 302
        assert dismiss_response.url == reverse("schema-list")

        response = client.get(reverse("home"))
        assert "0.8.0" not in response.content.decode()

    def test_dismiss_requires_staff(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        annotator = get_user_model().objects.create_user(
            "annotator-dismisser", password="x", is_staff=False
        )
        client.force_login(annotator)

        response = client.post(reverse("dismiss-update", args=[record.pk]))
        assert response.status_code == 403
