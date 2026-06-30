# Schema Changelog

Schema changes recorded here are temporary Loom-side patches that need to be
migrated into the canonical Causal Mosaic schema repository. Loom keeps local
copies under `config/schema/` for development and UI testing, but the schema
repository remains the source of truth.

## 2026-06-30 - CAMO 0.4.2 ontology routing annotations

Status: pending upstream migration

Local Loom file patched:

- `config/schema/camo-0.4.2.yaml`

Canonical schema change to apply:

- Class: `CausalNode`
- Slot: `entity_term`
- Add annotation `loom_ontologies: "NCBITaxon, CHEBI, ENVO, GO, PATO"`.
- Slot: `variable_attribute`
- Add annotation `loom_ontologies: "PATO, GO"`.
- Class: `CausalEdge`
- Slot: `conditioned_by`
- Add annotation `loom_ontologies: "ENVO, PATO, GO"`.

Reason:

- Loom now derives ontology autocomplete routing from LinkML slot annotations
  before falling back to `config/loom_ui.yaml`.
- The affected slots already have `range: uriorcurie` and schema descriptions
  that identify preferred ontology families, but that routing was only encoded
  in Loom's UI sidecar.

Expected Loom behavior after migration:

- `uriorcurie` fields render with ontology autocomplete.
- Slots with `loom_ontologies` query those ontology prefixes first.
- Older schemas without this annotation continue to use Loom's sidecar routing
  as a compatibility fallback.

## 2026-06-30 - CAMO 0.4.2 SourceDocument ecosystem enum

Status: pending upstream migration

Local Loom file patched:

- `config/schema/camo-0.4.2.yaml`

Canonical schema change to apply:

- Class: `SourceDocument`
- Slot: `study_ecosystem`
- Change `range` from `string` to `EcosystemFunctionalGroupEnum`.
- Update the slot description so it instructs annotators to submit the enum
  value, for example `temperate_woodlands`, while the UI can display labels such
  as `T4.4 Temperate woodlands`.

Reason:

- `EcosystemFunctionalGroupEnum` already exists in CAMO 0.4.2 with IUCN GET
  display labels.
- `CausalEdge.ecosystem_context` already uses this enum.
- `SourceDocument.study_ecosystem` was still typed as `string`, so Loom's
  schema-driven form engine correctly rendered it as a plain text input instead
  of the large enum autocomplete.

Expected Loom behavior after migration:

- `SourceDocument.study_ecosystem` renders with the `enum_autocomplete` widget.
- The visible field filters labels such as `T4.5 Temperate subhumid grasslands`.
- The submitted hidden value is the enum key, for example
  `temperate_subhumid_grasslands`.
- A display label posted without the hidden enum value is rejected by schema
  validation.

Loom follow-up after upstream schema update:

- Refresh Loom's local copy of `config/schema/camo-0.4.2.yaml` from the schema
  repository.
- Reload or reactivate the patched 0.4.2 schema in any development/project
  database; existing `SchemaVersion` rows do not automatically change when the
  YAML file changes on disk.

Temporary Loom test-server reload:

```bash
python manage.py load_schema config/schema/camo-0.4.2.yaml --schema-version 0.4.2 --activate --replace-version
```

For Docker Compose:

```bash
docker compose exec web python manage.py load_schema config/schema/camo-0.4.2.yaml --schema-version 0.4.2 --activate --replace-version
```

`--replace-version` updates existing `SchemaVersion(version="0.4.2")` rows in
place so existing projects and graphs keep their foreign-key pins but receive
the patched YAML content. Without this, `load_schema --activate` creates a new
row that existing graphs may never use.
