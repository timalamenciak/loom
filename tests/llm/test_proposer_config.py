"""Tests for ProposerConfig.clean() — the only place that guards against
enabling the LLM seam without a resolvable API key."""

import pytest
from django.core.exceptions import ValidationError

from apps.llm.models import ProposerConfig
from apps.projects.models import Project


@pytest.fixture
def project(db):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user("proposer-config-user", password="x")
    return Project.objects.create(name="Proposer Config Test Project", created_by=user)


class TestProposerConfigClean:
    def test_clean_passes_when_disabled(self, project):
        config = ProposerConfig(project=project, is_enabled=False, api_key_env_var="")
        config.clean()

    def test_clean_fails_no_env_var(self, project, monkeypatch):
        monkeypatch.delenv("LOOM_TEST_UNSET_API_KEY", raising=False)
        config = ProposerConfig(
            project=project,
            is_enabled=True,
            api_key_env_var="LOOM_TEST_UNSET_API_KEY",
        )
        with pytest.raises(ValidationError) as exc_info:
            config.clean()
        assert "api_key_env_var" in exc_info.value.error_dict

    def test_clean_fails_blank_env_var_name(self, project):
        config = ProposerConfig(project=project, is_enabled=True, api_key_env_var="")
        with pytest.raises(ValidationError) as exc_info:
            config.clean()
        assert "api_key_env_var" in exc_info.value.error_dict

    def test_clean_passes_with_valid_env_var(self, project, monkeypatch):
        monkeypatch.setenv("LOOM_TEST_SET_API_KEY", "sk-test-value")
        config = ProposerConfig(
            project=project,
            is_enabled=True,
            api_key_env_var="LOOM_TEST_SET_API_KEY",
        )
        config.clean()
