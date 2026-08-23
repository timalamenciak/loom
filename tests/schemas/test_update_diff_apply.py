"""Tests for the update-diff viewer and the confirm-then-apply update flow.

Both are superuser-only, matching every other schema-admin view in this app
(SchemaListView, SchemaActivateView, SchemaDetailView) — a staff-but-not-
superuser user is enough to see the notification banner, but not enough to
act on it, so those negative-path tests use a staff (not superuser) user.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.schemas.models import SchemaVersion, UpdateCheckRecord
from tests.schema_fixtures import latest_schema_path


def _superuser(username="update-admin"):
    return get_user_model().objects.create_superuser(username, password="x")


def _staff_non_superuser(username="staff-only"):
    return get_user_model().objects.create_user(username, password="x", is_staff=True)


class _FakeDownloadResponse:
    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._content


class TestUpdateDiffView:
    def test_diff_view_shows_schema_diff(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
            release_notes="Added a slot.",
            diff_summary={
                "added_slots": ["hypothesis_tags"],
                "removed_slots": ["legacy_field"],
                "changed_enums": ["ClaimStrengthEnum"],
            },
        )
        client.force_login(_superuser())

        response = client.get(reverse("update-diff", args=[record.pk]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "hypothesis_tags" in content
        assert "legacy_field" in content
        assert "ClaimStrengthEnum" in content
        assert "Added a slot." in content
        assert reverse("apply-update", args=[record.pk]) in content
        assert reverse("dismiss-update", args=[record.pk]) in content

    def test_diff_view_shows_ontology_diff(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_ONTOLOGY,
            module_name="ENVO",
            current_version="etag-old",
            available_version="etag-new",
            is_update_available=True,
            diff_summary={"etag_changed": True},
            download_url="https://example/envo.owl",
        )
        client.force_login(_superuser())

        response = client.get(reverse("update-diff", args=[record.pk]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "ETag" in content or "etag" in content.lower()

    def test_diff_view_requires_superuser(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        client.force_login(_staff_non_superuser())

        response = client.get(reverse("update-diff", args=[record.pk]))
        assert response.status_code == 403


class TestApplyUpdateViewGet:
    def test_get_shows_confirmation_page_with_activate_checkbox(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
            diff_summary={"added_slots": ["hypothesis_tags"]},
        )
        client.force_login(_superuser())

        response = client.get(reverse("apply-update", args=[record.pk]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "hypothesis_tags" in content
        assert 'name="confirm" value="1"' in content
        assert 'name="activate"' in content

    def test_get_requires_superuser(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        client.force_login(_staff_non_superuser())

        response = client.get(reverse("apply-update", args=[record.pk]))
        assert response.status_code == 403


class TestApplyUpdateViewPost:
    def test_apply_requires_confirm(self, client, latest_schema):
        """A bare POST (no confirm=1) is a no-op that bounces back to the
        confirmation page — guards against replayed/duplicate submits."""
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version=latest_schema.version,
            available_version="99.0.0",
            is_update_available=True,
            download_url="https://example/camo-99.0.0.yaml",
        )
        client.force_login(_superuser())

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen"
        ) as mock_urlopen:
            response = client.post(reverse("apply-update", args=[record.pk]))

        assert response.status_code == 302
        assert response.url == reverse("apply-update", args=[record.pk])
        mock_urlopen.assert_not_called()
        assert not SchemaVersion.objects.filter(version="99.0.0").exists()

        record.refresh_from_db()
        assert record.is_update_available is True

    def test_apply_schema_creates_version(
        self, client, latest_schema, tmp_path, settings
    ):
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)

        new_yaml = (
            latest_schema_path()
            .read_text(encoding="utf-8")
            .replace(f"version: {latest_schema.version}", "version: 99.0.0")
        )
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version=latest_schema.version,
            available_version="99.0.0",
            is_update_available=True,
            download_url="https://example/camo-99.0.0.yaml",
        )
        client.force_login(_superuser())

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            return_value=_FakeDownloadResponse(new_yaml.encode("utf-8")),
        ) as mock_urlopen:
            response = client.post(
                reverse("apply-update", args=[record.pk]),
                {"confirm": "1", "activate": "on"},
            )

        assert response.status_code == 302
        mock_urlopen.assert_called_once()

        schema = SchemaVersion.objects.get(version="99.0.0")
        assert schema.is_active

        record.refresh_from_db()
        assert record.is_update_available is False
        assert record.available_version == ""

    def test_apply_schema_already_loaded(
        self, client, latest_schema, tmp_path, settings
    ):
        """If a SchemaVersion for available_version already exists (e.g. a
        double-submit slipped past the confirm guard), reuse it instead of
        downloading again or creating a duplicate row."""
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)

        existing = SchemaVersion.objects.create(
            version="99.0.0",
            linkml_yaml=latest_schema.linkml_yaml.replace(
                f"version: {latest_schema.version}", "version: 99.0.0"
            ),
            is_active=False,
        )
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version=latest_schema.version,
            available_version="99.0.0",
            is_update_available=True,
            download_url="https://example/camo-99.0.0.yaml",
        )
        client.force_login(_superuser())

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen"
        ) as mock_urlopen:
            response = client.post(
                reverse("apply-update", args=[record.pk]),
                {"confirm": "1", "activate": "on"},
                follow=True,
            )

        assert response.status_code == 200
        mock_urlopen.assert_not_called()
        assert SchemaVersion.objects.filter(version="99.0.0").count() == 1

        existing.refresh_from_db()
        assert existing.is_active

        messages = [str(m) for m in response.context["messages"]]
        assert any("already loaded" in m for m in messages)

        record.refresh_from_db()
        assert record.is_update_available is False

    def test_apply_schema_update_failure_shows_message(self, client, latest_schema):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version=latest_schema.version,
            available_version="99.0.0",
            is_update_available=True,
            download_url="https://example/camo-99.0.0.yaml",
        )
        client.force_login(_superuser())

        import urllib.error

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            response = client.post(
                reverse("apply-update", args=[record.pk]),
                {"confirm": "1", "activate": "on"},
                follow=True,
            )

        assert response.status_code == 200
        messages = [str(m) for m in response.context["messages"]]
        assert any("Could not apply update" in m for m in messages)

        record.refresh_from_db()
        assert record.is_update_available is True

    def test_apply_ontology_update_runs_in_background_thread(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_ONTOLOGY,
            module_name="ENVO",
            current_version="etag-old",
            available_version="etag-new",
            is_update_available=True,
            diff_summary={"etag_changed": True},
        )
        client.force_login(_superuser())

        with (
            patch("apps.schemas.views.apply_ontology_update") as mock_apply,
            patch("apps.schemas.views.threading.Thread") as mock_thread_cls,
            patch("apps.schemas.views.connections") as mock_connections,
        ):
            mock_thread = mock_thread_cls.return_value
            response = client.post(
                reverse("apply-update", args=[record.pk]), {"confirm": "1"}
            )

            assert response.status_code == 302
            mock_thread_cls.assert_called_once()
            _, kwargs = mock_thread_cls.call_args
            assert kwargs["daemon"] is True
            # The thread target is a closure that runs apply_ontology_update(record)
            # and closes DB connections afterward — invoke it while the
            # patches are still active to prove that.
            kwargs["target"]()
            mock_apply.assert_called_once_with(record)
            mock_connections.close_all.assert_called_once()
            mock_thread.start.assert_called_once()

    def test_apply_update_requires_superuser(self, client, db):
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version="0.7.0",
            available_version="0.8.0",
            is_update_available=True,
        )
        client.force_login(_staff_non_superuser())

        response = client.post(
            reverse("apply-update", args=[record.pk]), {"confirm": "1"}
        )
        assert response.status_code == 403
