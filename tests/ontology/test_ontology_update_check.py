"""Tests for the check_ontology_updates management command."""

import io
import urllib.error

import pytest
from django.core.management import call_command

from apps.ontology.models import OntologyRelease


class _HeadResponse:
    def __init__(self, headers):
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def ready_release(db):
    return OntologyRelease.objects.create(
        name="envo",
        prefix="ENVO",
        source_url="https://example.org/envo.obo",
        upstream_url="https://example.org/envo.obo",
        source_sha256="abc123",
        source_etag="etag-v1",
        status=OntologyRelease.STATUS_READY,
    )


def test_update_detected(db, ready_release, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _HeadResponse({"ETag": "etag-v2"}),
    )

    out = io.StringIO()
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_ontology_updates", stdout=out)

    assert exc_info.value.code == 1
    ready_release.refresh_from_db()
    assert ready_release.update_available is True
    assert "update available" in out.getvalue()


def test_no_update(db, ready_release, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=None: _HeadResponse({"ETag": "etag-v1"}),
    )

    out = io.StringIO()
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_ontology_updates", stdout=out)

    assert exc_info.value.code == 0
    ready_release.refresh_from_db()
    assert ready_release.update_available is False
    assert "up to date" in out.getvalue()


def test_network_error_continues(db, monkeypatch):
    unreachable = OntologyRelease.objects.create(
        name="broken",
        prefix="BRK",
        source_url="https://example.org/broken.obo",
        upstream_url="https://example.org/broken.obo",
        source_sha256="a1a1",
        source_etag="etag-a",
        status=OntologyRelease.STATUS_READY,
    )
    reachable = OntologyRelease.objects.create(
        name="envo",
        prefix="ENVO",
        source_url="https://example.org/envo.obo",
        upstream_url="https://example.org/envo.obo",
        source_sha256="b2b2",
        source_etag="etag-b",
        status=OntologyRelease.STATUS_READY,
    )

    def fake_urlopen(request, timeout=None):
        if request.full_url == unreachable.upstream_url:
            raise urllib.error.URLError("connection refused")
        return _HeadResponse({"ETag": "etag-b"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises(SystemExit) as exc_info:
        call_command("check_ontology_updates", stdout=out, stderr=err)

    assert exc_info.value.code == 0
    unreachable.refresh_from_db()
    reachable.refresh_from_db()
    assert unreachable.update_available is False
    assert reachable.update_available is False
    assert "could not reach" in err.getvalue()
    assert "up to date" in out.getvalue()
