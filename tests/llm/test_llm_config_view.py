"""Tests for the LLM config admin UI — apps/llm/views.py's LLMConfigView and
EnvVarCheckView.
"""

import pytest
from django.urls import reverse

from apps.llm.models import ProposerConfig
from apps.projects.models import Project, ProjectMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_superuser(
        "llm-config-admin", "llm-config-admin@test.example", "password"
    )


@pytest.fixture
def project(admin_user):
    p = Project.objects.create(name="LLM Config Test Project", created_by=admin_user)
    ProjectMembership.objects.create(
        project=p, user=admin_user, role=ProjectMembership.ROLE_ADMIN
    )
    return p


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user("llm-config-annotator", password="x")


class TestLLMConfigView:
    def test_get_renders_form_for_admin(self, client, project, admin_user):
        client.force_login(admin_user)

        response = client.get(reverse("llm-config", args=[project.pk]))

        assert response.status_code == 200
        assert not ProposerConfig.objects.filter(project=project).exists()

    def test_get_denied_for_non_admin(self, client, project, annotator):
        ProjectMembership.objects.create(
            project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(annotator)

        response = client.get(reverse("llm-config", args=[project.pk]))

        assert response.status_code == 403

    def test_post_creates_disabled_config(self, client, project, admin_user):
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config", args=[project.pk]),
            {
                "model": "claude-sonnet-5",
                "api_key_env_var": "",
                "trigger": ProposerConfig.TRIGGER_MANUAL,
                "max_proposals_per_document": 20,
                "max_shots": 5,
            },
        )

        assert response.status_code == 302
        config = ProposerConfig.objects.get(project=project)
        assert config.is_enabled is False
        assert config.model == "claude-sonnet-5"

    def test_post_enabling_without_env_var_fails_validation(
        self, client, project, admin_user
    ):
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config", args=[project.pk]),
            {
                "is_enabled": "on",
                "model": "claude-sonnet-5",
                "api_key_env_var": "",
                "trigger": ProposerConfig.TRIGGER_MANUAL,
                "max_proposals_per_document": 20,
                "max_shots": 5,
            },
        )

        assert response.status_code == 200
        assert not ProposerConfig.objects.filter(project=project).exists()
        assert "api_key_env_var" in response.context["form"].errors

    def test_post_enabling_with_unset_env_var_fails_validation(
        self, client, project, admin_user, monkeypatch
    ):
        monkeypatch.delenv("LLM_CONFIG_TEST_UNSET_KEY", raising=False)
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config", args=[project.pk]),
            {
                "is_enabled": "on",
                "model": "claude-sonnet-5",
                "api_key_env_var": "LLM_CONFIG_TEST_UNSET_KEY",
                "trigger": ProposerConfig.TRIGGER_MANUAL,
                "max_proposals_per_document": 20,
                "max_shots": 5,
            },
        )

        assert response.status_code == 200
        assert "api_key_env_var" in response.context["form"].errors

    def test_post_enabling_with_set_env_var_succeeds(
        self, client, project, admin_user, monkeypatch
    ):
        monkeypatch.setenv("LLM_CONFIG_TEST_SET_KEY", "sk-test")
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config", args=[project.pk]),
            {
                "is_enabled": "on",
                "model": "claude-opus-4-8",
                "api_key_env_var": "LLM_CONFIG_TEST_SET_KEY",
                "trigger": ProposerConfig.TRIGGER_ON_ASSIGNMENT,
                "max_proposals_per_document": 10,
                "max_shots": 3,
            },
        )

        assert response.status_code == 302
        config = ProposerConfig.objects.get(project=project)
        assert config.is_enabled is True
        assert config.model == "claude-opus-4-8"
        assert config.trigger == ProposerConfig.TRIGGER_ON_ASSIGNMENT


class TestEnvVarCheckView:
    def test_check_reports_set_variable(self, client, project, admin_user, monkeypatch):
        monkeypatch.setenv("LLM_CONFIG_TEST_CHECK_SET", "sk-test")
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config-check-env-var", args=[project.pk]),
            {"api_key_env_var": "LLM_CONFIG_TEST_CHECK_SET"},
        )

        assert response.status_code == 200
        body = response.content.decode()
        assert "is set" in body
        assert "sk-test" not in body

    def test_check_reports_unset_variable(
        self, client, project, admin_user, monkeypatch
    ):
        monkeypatch.delenv("LLM_CONFIG_TEST_CHECK_UNSET", raising=False)
        client.force_login(admin_user)

        response = client.post(
            reverse("llm-config-check-env-var", args=[project.pk]),
            {"api_key_env_var": "LLM_CONFIG_TEST_CHECK_UNSET"},
        )

        assert response.status_code == 200
        assert "not set" in response.content.decode()

    def test_check_denied_for_non_admin(self, client, project, annotator):
        ProjectMembership.objects.create(
            project=project, user=annotator, role=ProjectMembership.ROLE_ANNOTATOR
        )
        client.force_login(annotator)

        response = client.post(
            reverse("llm-config-check-env-var", args=[project.pk]),
            {"api_key_env_var": "ANYTHING"},
        )

        assert response.status_code == 403
