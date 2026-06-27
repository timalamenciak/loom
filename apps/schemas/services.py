from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from linkml_runtime.utils.schemaview import SchemaView

from .models import SchemaVersion
from .schema_engine import invalidate_cache

REQUIRED_CAMO_CLASSES = {"CausalGraph", "CausalNode", "CausalEdge"}
SUPPORTED_IMPORTS = {"linkml:types"}


def validate_schema_yaml(content: str) -> dict:
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("The uploaded schema must be a LinkML YAML mapping.")

    unsupported = set(document.get("imports") or []) - SUPPORTED_IMPORTS
    if unsupported:
        raise ValueError(
            "External schema imports are not supported yet: "
            + ", ".join(sorted(unsupported))
        )

    try:
        view = SchemaView(content)
    except Exception as exc:
        raise ValueError(f"Invalid LinkML schema: {exc}") from exc

    missing = REQUIRED_CAMO_CLASSES - set(view.all_classes())
    if missing:
        raise ValueError(
            "Schema is missing required classes: " + ", ".join(sorted(missing))
        )
    return document


def get_or_create_schema_version(content: str, *, fallback_name: str = "uploaded"):
    document = validate_schema_yaml(content)
    digest = hashlib.sha256(content.encode()).hexdigest()
    existing = SchemaVersion.objects.filter(sha256=digest).first()
    if existing:
        return existing, False

    version = str(document.get("version") or fallback_name)
    schema = SchemaVersion.objects.create(
        version=version,
        linkml_yaml=content,
        is_active=False,
    )
    invalidate_cache(schema.pk)
    return schema, True


def load_schema_path(path: Path, *, version: str | None = None, activate: bool = False):
    content = path.read_text(encoding="utf-8")
    schema, created = get_or_create_schema_version(content, fallback_name=path.stem)
    if version and schema.version != version:
        schema.version = version
        schema.save(update_fields=["version"])
    if activate and not schema.is_active:
        schema.is_active = True
        schema.save(update_fields=["is_active"])
        invalidate_cache()
    return schema, created
