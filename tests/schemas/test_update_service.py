"""Tests for apps.schemas.update_service — the persisted, non-CLI form of the
schema/ontology update checks. All network calls are mocked.
"""

from unittest.mock import patch

from apps.schemas.models import UpdateCheckRecord
from apps.schemas.update_service import (
    apply_ontology_update,
    apply_schema_update,
    check_all_updates,
    check_ontology_updates,
    check_schema_update,
)
from apps.schemas.upstream import ReleaseAsset, ReleaseInfo, UpstreamCheckError
from tests.schema_fixtures import latest_schema_path


class _FakeDownloadResponse:
    def __init__(self, content: bytes):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self._content


def _release(tag: str, body: str = "", yaml_content: str | None = None) -> ReleaseInfo:
    assets = []
    if yaml_content is not None:
        assets.append(
            ReleaseAsset(
                name=f"causal_mosaic_{tag}.yaml", download_url="https://example/asset"
            )
        )
    return ReleaseInfo(
        tag_name=tag, published_at="2026-01-01T00:00:00Z", body=body, assets=assets
    )


class _FakeHeadResponse:
    def __init__(self, headers):
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestCheckSchemaUpdate:
    def test_schema_update_detected(self, latest_schema):
        new_yaml = latest_schema_path().read_text(encoding="utf-8")
        release = _release("v99.0.0", body="Big changes.", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.update_service.get_latest_release", return_value=release
            ),
            patch("apps.schemas.update_service.download_asset", return_value=new_yaml),
        ):
            record = check_schema_update()

        assert record.is_update_available is True
        assert record.available_version == "99.0.0"
        assert record.current_version == latest_schema.version
        assert record.download_url == "https://example/asset"
        assert record.release_notes == "Big changes."
        assert set(record.diff_summary) == {
            "added_slots",
            "removed_slots",
            "changed_enums",
        }

        stored = UpdateCheckRecord.objects.get(module_type="schema", module_name="camo")
        assert stored.pk == record.pk

    def test_schema_no_update(self, latest_schema):
        release = _release(f"v{latest_schema.version}")

        with patch(
            "apps.schemas.update_service.get_latest_release", return_value=release
        ):
            record = check_schema_update()

        assert record.is_update_available is False
        assert record.available_version == ""
        assert record.diff_summary == {}

    def test_no_active_schema_returns_none(self, db):
        assert check_schema_update() is None
        assert not UpdateCheckRecord.objects.exists()


class TestCheckOntologyUpdates:
    def test_ontology_update_detected(self, db):
        from apps.ontology.models import OntologyRelease

        OntologyRelease.objects.create(
            name="ENVO",
            prefix="ENVO",
            source_url="https://example/envo.owl",
            upstream_url="https://example/envo.owl",
            source_etag="etag-old",
            status=OntologyRelease.STATUS_READY,
        )

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            return_value=_FakeHeadResponse({"ETag": "etag-new"}),
        ):
            records = check_ontology_updates()

        assert len(records) == 1
        record = records[0]
        assert record.module_type == "ontology"
        assert record.module_name == "ENVO"
        assert record.is_update_available is True
        assert record.diff_summary == {"etag_changed": True}
        assert record.available_version == "etag-new"

    def test_ontology_no_update(self, db):
        from apps.ontology.models import OntologyRelease

        OntologyRelease.objects.create(
            name="ENVO",
            prefix="ENVO",
            source_url="https://example/envo.owl",
            upstream_url="https://example/envo.owl",
            source_etag="etag-same",
            status=OntologyRelease.STATUS_READY,
        )

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            return_value=_FakeHeadResponse({"ETag": "etag-same"}),
        ):
            records = check_ontology_updates()

        assert len(records) == 1
        assert records[0].is_update_available is False


class TestCheckAllUpdates:
    def test_network_failure_soft(self, latest_schema):
        from apps.ontology.models import OntologyRelease

        OntologyRelease.objects.create(
            name="ENVO",
            prefix="ENVO",
            source_url="https://example/envo.owl",
            upstream_url="https://example/envo.owl",
            source_etag="etag-old",
            status=OntologyRelease.STATUS_READY,
        )

        with (
            patch(
                "apps.schemas.update_service.get_latest_release",
                side_effect=UpstreamCheckError("offline"),
            ),
            patch(
                "apps.schemas.update_service.urllib.request.urlopen",
                return_value=_FakeHeadResponse({"ETag": "etag-new"}),
            ),
        ):
            result = check_all_updates()  # must not raise

        assert result["schema"] is None
        assert len(result["ontology"]) == 1
        assert UpdateCheckRecord.objects.filter(module_type="ontology").exists()
        assert not UpdateCheckRecord.objects.filter(module_type="schema").exists()


class TestApplySchemaUpdate:
    def _record(self, latest_schema, **overrides):
        defaults = dict(
            module_type=UpdateCheckRecord.MODULE_SCHEMA,
            module_name="camo",
            current_version=latest_schema.version,
            available_version="99.0.0",
            is_update_available=True,
            download_url="https://example/camo-99.0.0.yaml",
        )
        defaults.update(overrides)
        return UpdateCheckRecord.objects.create(**defaults)

    def _new_yaml(self, latest_schema):
        return (
            latest_schema_path()
            .read_text(encoding="utf-8")
            .replace(f"version: {latest_schema.version}", "version: 99.0.0")
        )

    def test_apply_without_activate_keeps_update_flagged(
        self, latest_schema, tmp_path, settings
    ):
        """Loading (but not activating) a schema must not clear the banner —
        the live app is still running the old version until someone actually
        activates it."""
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)
        new_yaml = self._new_yaml(latest_schema)
        record = self._record(latest_schema)

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            return_value=_FakeDownloadResponse(new_yaml.encode("utf-8")),
        ):
            schema, created = apply_schema_update(record, activate=False)

        assert created is True
        assert schema.is_active is False

        record.refresh_from_db()
        assert record.is_update_available is True
        assert record.current_version == latest_schema.version
        assert record.available_version == "99.0.0"

    def test_resubmit_after_success_is_a_no_op_not_a_redownload(
        self, latest_schema, tmp_path, settings
    ):
        """A browser back-button resubmit after a successful apply must not
        re-download — available_version was cleared by the first apply, so
        the guard has to fall back to current_version instead of treating an
        empty version string as 'nothing to reuse'."""
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)
        new_yaml = self._new_yaml(latest_schema)
        record = self._record(latest_schema)

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen",
            return_value=_FakeDownloadResponse(new_yaml.encode("utf-8")),
        ) as mock_urlopen:
            schema, created = apply_schema_update(record, activate=True)

        assert created is True
        mock_urlopen.assert_called_once()

        # Simulate the view re-fetching the record fresh on a resubmit.
        record.refresh_from_db()
        assert record.available_version == ""

        with patch(
            "apps.schemas.update_service.urllib.request.urlopen"
        ) as mock_urlopen_2:
            schema_2, created_2 = apply_schema_update(record, activate=True)

        mock_urlopen_2.assert_not_called()
        assert created_2 is False
        assert schema_2.pk == schema.pk


class TestApplyOntologyUpdate:
    def test_relinks_upstream_url_to_the_new_release(self, db):
        from apps.ontology.models import OntologyRelease

        old_release = OntologyRelease.objects.create(
            name="ENVO",
            prefix="ENVO",
            source_url="https://example/envo.owl",
            upstream_url="https://example/envo.owl",
            source_etag="etag-old",
            source_sha256="a" * 64,
            status=OntologyRelease.STATUS_READY,
        )
        record = UpdateCheckRecord.objects.create(
            module_type=UpdateCheckRecord.MODULE_ONTOLOGY,
            module_name="ENVO",
            current_version="etag-old",
            available_version="etag-new",
            is_update_available=True,
            diff_summary={"etag_changed": True},
        )

        def _fake_load_ontology(name):
            # Mirrors apps.ontology.loaders.load_ontology_release(): creates a
            # new, immutable release with no upstream_url/source_etag set.
            new_release = OntologyRelease.objects.create(
                name=name,
                prefix="ENVO",
                source_url="https://example/envo.owl",
                source_sha256="b" * 64,
                status=OntologyRelease.STATUS_READY,
            )
            return new_release, 0

        with patch(
            "apps.ontology.loaders.load_ontology", side_effect=_fake_load_ontology
        ):
            apply_ontology_update(record)

        old_release.refresh_from_db()
        assert old_release.upstream_url is None

        new_release = OntologyRelease.objects.exclude(pk=old_release.pk).get(
            name="ENVO"
        )
        assert new_release.upstream_url == "https://example/envo.owl"
        assert new_release.source_etag == "etag-new"

        record.refresh_from_db()
        assert record.is_update_available is False
