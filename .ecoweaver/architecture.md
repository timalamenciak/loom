# Architecture

Describe the project architecture here. Keep this file current enough that an AI agent can orient itself quickly.

## Project purpose

This repository is part of the EcoWeaver research software ecosystem.

EcoWeaver projects generally support one or more of:

- ecological evidence synthesis
- LinkML-native data modelling
- ontology-grounded annotation
- labeled property graph construction
- human-in-the-loop knowledge curation
- reproducible research workflows

## System overview

Fill in the project-specific architecture:

```text
User interface
  -> application/service layer
  -> schema/validation layer
  -> persistence layer
  -> export/integration layer
```

## Important directories

Update this section for each repository.

```text
src/ or app/       primary application code
schema/            LinkML schemas or schema fragments
tests/             automated tests
docs/              human documentation
scripts/           maintenance or generation scripts
migrations/        database migrations, if applicable
```

## Data flow

Document how data enters, is validated, is transformed, and is exported.

For annotation or knowledge graph projects, include:

1. source artifact
2. fragment or span
3. annotation/evidence unit
4. schema-conformant record
5. graph/export representation
6. provenance trail

## Boundaries

Agents should not blur these boundaries:

- source schema vs generated artifacts
- human annotation vs model suggestion
- ontology term selection vs free-text labels
- persistent data model vs UI convenience fields
- migration intent vs incidental database changes
- user-supplied input vs trusted internal data (validate all external input at the boundary)
- public API response vs internal state (redact before returning)

## Security architecture

Document the security controls for this repository:

| Concern | Mechanism | Notes |
|---|---|---|
| Authentication | Django auth / session / token | |
| Authorization | Object-level permissions | |
| Input validation | Django forms / DRF serializers / LinkML | |
| Secrets management | Environment variables / `.env` excluded from VCS | |
| SQL safety | Django ORM; parameterized queries only | |
| File uploads | MIME validation, size limits, stored outside web root | |
| HTTP security | CSRF, CSP, HSTS, `X-Frame-Options` | |
| Dependency auditing | `pip-audit` on CI | |

Update this table when adding new external-facing components.

## Accessibility architecture (web projects)

- Target: WCAG 2.1 Level AA.
- Primary template engine: [Django templates / Jinja2 / React]
- Accessible form toolkit: [crispy-forms / custom]
- Automated accessibility testing: [axe-core / Playwright / Lighthouse]
- Known screen reader testing: [NVDA on Windows / VoiceOver on macOS]

## Generated artifacts

List generated files here and identify their source commands. Generated files should not be edited by hand unless the source is also updated.

| Generated artifact | Source | Regeneration command |
|---|---|---|
| Example: JSON Schema | LinkML schema | `make schema` |
| Example: docs | LinkML schema | `make docs` |

## External services

List any external services, APIs, databases, or hosted components.

| Service | Purpose | Local/dev equivalent |
|---|---|---|
| PostgreSQL | persistent data | docker compose service |
| Redis | async jobs/cache | docker compose service |
