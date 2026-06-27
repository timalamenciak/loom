"""Phase 0 smoke tests: app boots and auth works."""

from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_login_page(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert b"Loom" in response.content


@pytest.mark.django_db
def test_unauthenticated_root_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_authenticated_home(client, superuser):
    client.force_login(superuser)
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"Loom" in response.content


@pytest.mark.django_db
def test_admin_accessible_to_superuser(client, superuser):
    client.force_login(superuser)
    response = client.get("/admin/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_blocked_for_anonymous(client):
    response = client.get("/admin/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_custom_user_model():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    assert User.__module__ == "apps.accounts.models"


@pytest.mark.django_db
def test_llm_proposals_disabled():
    from django.conf import settings

    assert settings.LLM_PROPOSALS_ENABLED is False


def test_package_exposes_semantic_version():
    import re

    from apps.export.serializer import EXPORTER_VERSION
    from loom import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", __version__)
    assert EXPORTER_VERSION == f"loom-{__version__}"


def test_liveness_probe_is_public(client):
    response = client.get(reverse("health-live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_readiness_probe_checks_database(client):
    response = client.get(reverse("health-ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_probe_reports_database_failure(client):
    with patch("loom.health.connection.cursor", side_effect=RuntimeError("offline")):
        response = client.get(reverse("health-ready"))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
