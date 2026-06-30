# Schema Changelog

Schema changes recorded here are temporary Loom-side patches that need to be
migrated into the canonical Causal Mosaic schema repository. Loom keeps local
copies under `config/schema/` for development and UI testing, but the schema
repository remains the source of truth.

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
