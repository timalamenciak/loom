import pytest

from tests.schema_fixtures import (
    frozen_schema_path,
    latest_schema_path,
    oldest_schema_path,
)


@pytest.fixture
def superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser("admin", "admin@test.example", "password123")


@pytest.fixture
def latest_schema_yaml() -> str:
    """Raw YAML text of the newest schema in config/schema/ — no DB required.

    Use this (via a stub SchemaVersion) for engine-mechanics tests that only
    care about slot/class names and structural rules, not specific enum
    values, so they keep tracking whatever CAMO looks like today.
    """
    return latest_schema_path().read_text(encoding="utf-8")


@pytest.fixture
def latest_schema(db):
    """The newest schema in config/schema/, loaded and activated in the DB."""
    from apps.schemas.schema_engine import invalidate_cache
    from apps.schemas.services import get_or_create_schema_version

    content = latest_schema_path().read_text(encoding="utf-8")
    schema, _ = get_or_create_schema_version(content)
    if not schema.is_active:
        schema.is_active = True
        schema.save(update_fields=["is_active"])
    yield schema
    invalidate_cache(schema.pk)


@pytest.fixture
def oldest_schema(db):
    """The oldest schema in config/schema/, loaded (not activated) in the DB.

    Paired with `latest_schema` for tests that legitimately need two distinct
    versions on purpose — schema switching / migrate_graph diffing.
    """
    from apps.schemas.schema_engine import invalidate_cache
    from apps.schemas.services import get_or_create_schema_version

    content = oldest_schema_path().read_text(encoding="utf-8")
    schema, _ = get_or_create_schema_version(content)
    yield schema
    invalidate_cache(schema.pk)


@pytest.fixture
def frozen_schema_040(db):
    """CAMO 0.4.0, loaded and activated — deliberately pinned, not stale.

    A number of input-binding / annotation-service tests use payloads written
    in 0.4.x-era enum vocabulary (entity_type="abiotic"/"biotic",
    claim_strength="tendency", etc.). CAMO's EntityTypeEnum/ClaimStrengthEnum
    were redesigned (not just extended) by 0.7.x, so these tests are pinned
    here rather than repointed at `latest` — migrating the payloads to the
    current vocabulary is tracked as separate follow-up work, not silently
    folded into this fixture rename.
    """
    from apps.schemas.schema_engine import invalidate_cache
    from apps.schemas.services import get_or_create_schema_version

    content = frozen_schema_path("0.4.0").read_text(encoding="utf-8")
    schema, _ = get_or_create_schema_version(content)
    if not schema.is_active:
        schema.is_active = True
        schema.save(update_fields=["is_active"])
    yield schema
    invalidate_cache(schema.pk)


@pytest.fixture
def frozen_schema_042(db):
    """CAMO 0.4.2, loaded and activated — deliberately pinned, not stale.

    0.4.2 is the last version where SourceDocument had a `study_ecosystem`
    slot with schema-embedded ontology annotations (both were later removed/
    restructured; see causalmosaic CHANGELOG 0.4.2->0.6.0). Tests using this
    fixture are intentionally exercising that historical behaviour, not
    accidentally stuck on an old version — do not repoint them at `latest`.
    """
    from apps.schemas.schema_engine import invalidate_cache
    from apps.schemas.services import get_or_create_schema_version

    content = frozen_schema_path("0.4.2").read_text(encoding="utf-8")
    schema, _ = get_or_create_schema_version(content)
    if not schema.is_active:
        schema.is_active = True
        schema.save(update_fields=["is_active"])
    yield schema
    invalidate_cache(schema.pk)
