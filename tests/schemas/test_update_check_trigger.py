"""Tests for the debounced background update-check trigger on SchemaListView
(the schema-admin landing page) — see apps/schemas/views.py::_maybe_trigger_update_check.
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.urls import reverse

_CACHE_KEY = "loom:update_check_last_run"


class TestAdminDashboardUpdateCheckTrigger:
    def setup_method(self):
        cache.delete(_CACHE_KEY)

    def teardown_method(self):
        cache.delete(_CACHE_KEY)

    def test_admin_dashboard_triggers_check_when_stale(self, client, superuser):
        client.force_login(superuser)

        with (
            patch("apps.schemas.views.check_all_updates") as mock_check,
            patch("apps.schemas.views.threading.Thread") as mock_thread_cls,
            patch("apps.schemas.views.connections") as mock_connections,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            response = client.get(reverse("schema-list"))

            assert response.status_code == 200
            mock_thread_cls.assert_called_once()
            _, kwargs = mock_thread_cls.call_args
            assert kwargs["daemon"] is True
            # The thread target is a closure that runs check_all_updates() and
            # closes DB connections afterward — invoke it while the patches
            # are still active to prove that.
            kwargs["target"]()
            mock_check.assert_called_once_with()
            mock_connections.close_all.assert_called_once()
            mock_thread.start.assert_called_once()

        assert cache.get(_CACHE_KEY) is True

    def test_admin_dashboard_no_check_when_fresh(self, client, superuser):
        cache.set(_CACHE_KEY, True, 43200)
        client.force_login(superuser)

        with patch("apps.schemas.views.check_all_updates") as mock_check:
            response = client.get(reverse("schema-list"))

        assert response.status_code == 200
        mock_check.assert_not_called()

    def test_trigger_uses_atomic_cache_add_not_get_then_set(self, client, superuser):
        """cache.add() is atomic (unlike get()-then-set()), so two requests
        racing on a cold cache can't both pass the debounce and both spawn a
        background check."""
        client.force_login(superuser)

        with (
            patch("apps.schemas.views.cache") as mock_cache,
            patch("apps.schemas.views.threading.Thread"),
        ):
            mock_cache.add.return_value = True
            client.get(reverse("schema-list"))

        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()
        mock_cache.add.assert_called_once_with(_CACHE_KEY, True, 43200)
