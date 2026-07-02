# Security Guidelines

Security in EcoWeaver research software protects data integrity, researcher privacy, and the trustworthiness of scientific outputs.

## Core principles

- Validate all input at system boundaries; trust nothing from external sources.
- Manage secrets through environment variables or a secrets manager, never in source code or version control.
- Apply least-privilege access to services, database roles, and API endpoints.
- Prefer deny-by-default in authorization decisions.
- Treat authentication failures and authorization denials as auditable events.
- Use well-audited libraries for cryptography, authentication, and token handling; do not implement these from scratch.

## Input validation

- Validate and sanitize all user-supplied input before use in queries, file paths, shell commands, or templates.
- Use Django forms, DRF serializers, or LinkML validators as the primary validation layer.
- Reject unexpected input types explicitly; do not silently coerce or discard invalid data.
- For file uploads: validate MIME type server-side (not only the Content-Type header), enforce size limits, and store uploaded files outside the web root.
- Never pass user input to shell commands. Use `subprocess` with an argument list, never `shell=True`.

## Authentication and authorization

- Use Django's built-in authentication system as the foundation; do not reinvent it.
- Implement object-level permissions for annotation, curation, and data records.
- Never rely on client-supplied user IDs for authorization decisions.
- Invalidate sessions and tokens on logout and password change.
- Enforce HTTPS in production; set `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, and `SESSION_COOKIE_SECURE`.
- All API endpoints must require authentication unless explicitly designed to be public and documented as such.

## Secrets management

- Store secrets (API keys, database passwords, OAuth credentials) in environment variables or a `.env` file excluded from version control.
- Add `.env` to `.gitignore` before the first commit; verify it is absent from the repository history.
- Do not log secret values, even at debug level.
- Rotate secrets after accidental exposure; treat any committed secret as compromised.

## Django-specific

- Keep `DEBUG=False` in production; verify `ALLOWED_HOSTS` is configured.
- Use Django's ORM for all database queries; avoid raw SQL unless it is parameterized with `cursor.execute(sql, params)`.
- CSRF protection is enabled by default; do not disable it on non-API views without documented justification.
- Use `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers.
- Review the Django deployment checklist before each release: https://docs.djangoproject.com/en/stable/howto/deployment/checklist/

## Dependency management

- Pin dependencies with exact versions in `requirements.txt`, `requirements-dev.txt`, or `pyproject.toml`.
- Audit dependencies periodically: `pip-audit` or `safety check`.
- Do not add a new dependency without documenting its purpose and checking its maintenance status.
- Remove unused dependencies.
- When adding a dependency from an unfamiliar source, check for known CVEs before merging.

## API security

- Require authentication on all API endpoints; document any intentional exceptions.
- Implement rate limiting on public-facing endpoints (e.g., `django-ratelimit`).
- Return generic error messages to clients; log detailed diagnostics server-side only.
- Validate and constrain all query parameters (pagination limits, filter fields, sort columns).
- Avoid exposing raw internal database identifiers in URLs where surrogate identifiers can be used.

## Data and provenance security

- Treat provenance records as append-only where possible; restrict deletion to privileged roles.
- Log data modifications with timestamp, user, and old/new values where applicable.
- Do not expose another researcher's unpublished annotations, drafts, or records without explicit authorization.
- Apply access control at the query layer, not only at the UI layer.

## Knowledge graph and export

- Validate and parameterize graph queries (SPARQL, Cypher, etc.) to prevent injection.
- Enforce access control before export; redact sensitive fields prior to data release.
- Apply the same validation rigor to import paths as to user-submitted forms.

## Agent instructions

When adding or reviewing security-sensitive code:

1. Read this file.
2. Identify all external inputs (user-supplied, file upload, API response, environment variable).
3. Verify each external input is validated before use.
4. Confirm secrets are not in source files or committed `.env` files.
5. Confirm authorization is enforced at the correct layer (not only in the UI).
6. Run `pip-audit` or `safety check` if dependencies changed.
7. Flag any findings, even if they fall outside the immediate task scope.
