# Changelog

All notable changes to Loom will be documented here. The project follows
Semantic Versioning and keeps application versions separate from CAMO schema
versions.

## Unreleased

### Added

- MIT licensing for source and distribution artifacts.
- Schema-derived server binding for typed, nested, and multivalued form data.
- Database constraints for active schema/ontology selection, valid span
  offsets, nonnegative session counters, and one open work session.
- Central annotation authorization policy for assignment-owned graph writes.
- Reviewer workflow for returning submitted assignments.
- Security and contribution guidance for public repository users.
- Public liveness and database-readiness probes for deployment orchestration.
- A production operations runbook covering backups, restore drills, and
  upgrades.

### Changed

- Unknown, invalid, or Loom-managed annotation fields now fail closed with
  field-level errors; full LinkML validation runs before submission and every
  export.
- LinkML validation supports both legacy and current validator APIs and fails
  closed when validation is unavailable.
- Submitted and reviewed assignments are server-side read-only.
- Returned assignments resume as in-progress when reopened.
- Span creation, display, linking, and deletion are scoped to the assigned
  annotator who created the span.
- The container build uses separate build/runtime stages and a non-root runtime
  user.
- CI checks migration drift and Django's production deployment configuration.

### Security

- Docker build context now excludes environment files, uploaded media, Git
  metadata, caches, and local build artifacts.
- PDF, RIS, and bundle uploads have configurable service-level size limits;
  PDF signatures and ZIP expansion, entry count, encryption, and compression
  ratios are checked before processing.

## 0.1.0 - Unreleased

- Initial private development version.
