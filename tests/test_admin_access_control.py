"""Every staff/superuser-gated ("admin-tier") view must return 403 for a
logged-in user who is neither. There's no literal "/admin/" URL prefix in
this app (Django's own admin site is separate and unrelated) — this covers
every view in apps/schemas/views.py and apps/ontology/views.py that gates on
is_staff or is_superuser, which is what "admin view" means here.

Permission checks in every one of these views run before any database
lookup (UserPassesTestMixin.test_func(), or a manual _require_superuser()/
_require_staff() call at the top of get()/post()) — so a dummy, possibly
nonexistent pk is safe to use throughout: a 403 must come back before a 404
would ever have a chance to.
"""

import pytest
from django.urls import reverse

DUMMY_PK = 999999

# (url_name, http_method, url_kwargs)
ADMIN_TIER_ENDPOINTS = [
    ("schema-list", "get", {}),
    ("schema-upload", "get", {}),
    ("schema-upload", "post", {}),
    ("dismiss-update", "post", {"pk": DUMMY_PK}),
    ("update-diff", "get", {"pk": DUMMY_PK}),
    ("apply-update", "get", {"pk": DUMMY_PK}),
    ("apply-update", "post", {"pk": DUMMY_PK}),
    ("schema-detail", "get", {"pk": DUMMY_PK}),
    ("schema-activate", "post", {"pk": DUMMY_PK}),
    ("schema-form-builder", "get", {"pk": DUMMY_PK}),
    ("schema-form-builder-save", "post", {"pk": DUMMY_PK}),
    ("schema-form-builder-export", "get", {"pk": DUMMY_PK}),
    ("schema-form-builder-import", "post", {"pk": DUMMY_PK}),
    ("ontology-manage-list", "get", {}),
    ("ontology-manage-upload", "get", {}),
    ("ontology-manage-upload", "post", {}),
    ("ontology-manage-reload", "post", {"pk": DUMMY_PK}),
    ("ontology-manage-delete", "post", {"pk": DUMMY_PK}),
    ("ontology-manage-browse", "get", {"pk": DUMMY_PK}),
    ("ontology-manage-search", "get", {"pk": DUMMY_PK}),
]


@pytest.fixture
def annotator(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        "access-control-annotator", password="x"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,method,kwargs", ADMIN_TIER_ENDPOINTS)
def test_admin_view_requires_staff(client, annotator, url_name, method, kwargs):
    client.force_login(annotator)
    url = reverse(url_name, kwargs=kwargs)

    response = getattr(client, method)(url)

    assert response.status_code == 403, (
        f"{method.upper()} {url_name} ({url}) returned {response.status_code} "
        f"for a non-staff user, expected 403"
    )
