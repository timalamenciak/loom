# Changelog

All notable changes to Loom will be documented here. The project follows
Semantic Versioning and keeps application versions separate from CAMO schema
versions.

## Unreleased

### Added

- Central annotation authorization policy for assignment-owned graph writes.
- Reviewer workflow for returning submitted assignments.
- Security and contribution guidance for public repository users.

### Changed

- Submitted and reviewed assignments are server-side read-only.
- Returned assignments resume as in-progress when reopened.
- Span creation, display, linking, and deletion are scoped to the assigned
  annotator who created the span.
- The container build uses separate build/runtime stages and a non-root runtime
  user.

### Security

- Docker build context now excludes environment files, uploaded media, Git
  metadata, caches, and local build artifacts.

## 0.1.0 - Unreleased

- Initial private development version.
