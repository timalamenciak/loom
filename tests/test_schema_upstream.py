"""Tests for the causalmosaic GitHub Releases client and the
check_schema_updates / update_schema management commands.

All network calls are mocked — these must never hit the real GitHub API.
"""

from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.schemas.upstream import (
    ReleaseAsset,
    ReleaseInfo,
    UpstreamCheckError,
    get_latest_release,
    version_tuple,
)
from tests.schema_fixtures import latest_schema_path


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


class TestVersionTuple:
    def test_orders_numerically(self):
        assert version_tuple("v0.7.1") < version_tuple("v0.10.0")

    def test_strips_leading_v(self):
        assert version_tuple("v1.2.3") == (1, 2, 3)

    def test_non_numeric_sorts_last(self):
        assert version_tuple("not-a-version") == (-1,)


class TestGetLatestRelease:
    def test_parses_release_json(self, settings):
        settings.CAMO_SCHEMA_GITHUB_REPO = "owner/repo"
        payload = {
            "tag_name": "v0.7.2",
            "published_at": "2026-01-01T00:00:00Z",
            "body": "Added a slot.",
            "assets": [
                {
                    "name": "causal_mosaic_v0.7.2.yaml",
                    "browser_download_url": "https://x/asset.yaml",
                }
            ],
        }
        with patch("apps.schemas.upstream._get_json", return_value=payload) as mock_get:
            release = get_latest_release()
        mock_get.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/releases/latest"
        )
        assert release.tag_name == "v0.7.2"
        assert release.version == "0.7.2"
        assert release.schema_asset().name == "causal_mosaic_v0.7.2.yaml"

    def test_network_failure_raises_upstream_check_error(self):
        import urllib.error

        with patch(
            "apps.schemas.upstream.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no network"),
        ):
            with pytest.raises(UpstreamCheckError):
                get_latest_release()

    def test_no_schema_asset_returns_none(self):
        release = _release("v0.7.2")
        assert release.schema_asset() is None


class TestCheckSchemaUpdatesCommand:
    def test_reports_up_to_date(self, latest_schema, capsys):
        release = _release(f"v{latest_schema.version}")
        with patch(
            "apps.schemas.management.commands.check_schema_updates.get_latest_release",
            return_value=release,
        ):
            call_command("check_schema_updates")
        assert "Up to date" in capsys.readouterr().out

    def test_reports_update_available_and_exits_nonzero(self, oldest_schema, capsys):
        oldest_schema.is_active = True
        oldest_schema.save(update_fields=["is_active"])
        new_yaml = latest_schema_path().read_text(encoding="utf-8")
        release = _release("v99.0.0", body="Big changes.", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.management.commands.check_schema_updates.get_latest_release",
                return_value=release,
            ),
            patch(
                "apps.schemas.management.commands.check_schema_updates.download_asset",
                return_value=new_yaml,
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                call_command("check_schema_updates")

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "Update available" in out
        assert "Big changes." in out

    def test_no_active_schema_raises_command_error(self, db):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("check_schema_updates")

    def test_network_failure_exits_2(self, latest_schema, capsys):
        with patch(
            "apps.schemas.management.commands.check_schema_updates.get_latest_release",
            side_effect=UpstreamCheckError("offline"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                call_command("check_schema_updates")
        assert exc_info.value.code == 2
        assert "Could not check for updates" in capsys.readouterr().out


class TestUpdateSchemaCommand:
    def test_downloads_loads_and_activates_with_yes(
        self, db, tmp_path, settings, capsys
    ):
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)

        new_yaml = latest_schema_path().read_text(encoding="utf-8")
        release = _release("v9.9.9", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.management.commands.update_schema.get_latest_release",
                return_value=release,
            ),
            patch(
                "apps.schemas.management.commands.update_schema.download_asset",
                return_value=new_yaml,
            ),
        ):
            call_command("update_schema", "--activate", "--yes")

        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.get(version="9.9.9")
        assert schema.is_active
        assert (tmp_path / "config" / "schema" / "camo-9.9.9.yaml").exists()

    def test_declines_activation_without_yes(self, db, tmp_path, settings):
        settings.BASE_DIR = tmp_path
        (tmp_path / "config" / "schema").mkdir(parents=True)

        new_yaml = latest_schema_path().read_text(encoding="utf-8")
        release = _release("v9.9.8", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.management.commands.update_schema.get_latest_release",
                return_value=release,
            ),
            patch(
                "apps.schemas.management.commands.update_schema.download_asset",
                return_value=new_yaml,
            ),
            patch("builtins.input", return_value="n"),
        ):
            call_command("update_schema", "--activate")

        from apps.schemas.models import SchemaVersion

        schema = SchemaVersion.objects.get(version="9.9.8")
        assert not schema.is_active

    def test_prune_removes_old_file_only_when_unreferenced(
        self, tmp_path, settings, latest_schema
    ):
        schema_dir = tmp_path / "config" / "schema"
        schema_dir.mkdir(parents=True)
        settings.BASE_DIR = tmp_path

        old_path = schema_dir / f"camo-{latest_schema.version}.yaml"
        old_path.write_text(latest_schema.linkml_yaml, encoding="utf-8")

        new_yaml = latest_schema.linkml_yaml.replace(
            f"version: {latest_schema.version}", "version: 9.9.7"
        )
        release = _release("v9.9.7", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.management.commands.update_schema.get_latest_release",
                return_value=release,
            ),
            patch(
                "apps.schemas.management.commands.update_schema.download_asset",
                return_value=new_yaml,
            ),
        ):
            call_command("update_schema", "--activate", "--yes", "--prune-old")

        assert not old_path.exists()

    def test_prune_skipped_when_graph_still_references_old_schema(
        self, tmp_path, settings, latest_schema, annotator=None
    ):
        from django.contrib.auth import get_user_model

        from apps.annotation.models import CausalGraph
        from apps.projects.models import Document, Project

        user = get_user_model().objects.create_user("pruner", password="x")
        project = Project.objects.create(name="Prune Test", created_by=user)
        doc = Document.objects.create(
            project=project,
            source=Document.SOURCE_MANUAL,
            title="Doc",
            canonical_text="Text.",
        )
        CausalGraph.objects.create(
            document=doc, annotator=user, schema_version=latest_schema
        )

        schema_dir = tmp_path / "config" / "schema"
        schema_dir.mkdir(parents=True)
        settings.BASE_DIR = tmp_path
        old_path = schema_dir / f"camo-{latest_schema.version}.yaml"
        old_path.write_text(latest_schema.linkml_yaml, encoding="utf-8")

        new_yaml = latest_schema.linkml_yaml.replace(
            f"version: {latest_schema.version}", "version: 9.9.6"
        )
        release = _release("v9.9.6", yaml_content=new_yaml)

        with (
            patch(
                "apps.schemas.management.commands.update_schema.get_latest_release",
                return_value=release,
            ),
            patch(
                "apps.schemas.management.commands.update_schema.download_asset",
                return_value=new_yaml,
            ),
        ):
            call_command("update_schema", "--activate", "--yes", "--prune-old")

        assert old_path.exists()
