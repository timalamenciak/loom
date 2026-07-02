# Style Guide

This guide defines default style for EcoWeaver research software. Project-specific conventions override this file when documented.

## General

- Prefer simple, explicit code over clever abstractions.
- Use descriptive names that reflect domain meaning.
- Keep changes small and reviewable.
- Preserve comments that explain scientific or data-model intent.
- Avoid broad formatting-only diffs unless requested.

## Linting and formatting (mandatory)

These tools must be run before every task is considered complete. No exceptions.

### Python

```bash
# Lint and auto-fix safe issues (replaces flake8, isort, pyupgrade, pep8-naming)
ruff check --fix .

# Format (non-negotiable)
black .

# Type check (run if mypy is configured)
mypy .

# Security static analysis (run if bandit is configured)
bandit -r src/

# Django system check (Django projects only)
python manage.py check
```

If `pre-commit` is configured, run `pre-commit run --all-files` instead.

### JavaScript / TypeScript

```bash
eslint .
prettier --check .
```

### Rules

- Fix all errors; do not silence them with `# noqa`, `# type: ignore`, or inline suppressions without a documented reason in a comment on the same line.
- Do not disable lint rules globally in config files to make a task pass.
- If a tool is not installed, report the install command rather than skipping.
- Include lint results in every task summary.

## Python

- Use type hints for new public functions.
- Prefer dataclasses or Pydantic models only when they clarify boundaries.
- Keep IO, validation, and transformation logic separable.
- Raise specific exceptions where possible.
- Avoid silent failure in data pipelines.

## Error handling and logging

- Raise specific, informative exceptions at the point of failure; do not swallow exceptions silently.
- Catch exceptions at the boundary where recovery or logging is possible, not everywhere.
- Use Python's `logging` module; do not use `print` for diagnostic output in library or service code.
- Log enough context to reproduce the failure (input type, key identifiers, operation) without logging secret values or personally identifiable information.
- For data pipelines: log input source, record count, validation failures, and output destination at INFO level.
- Distinguish recoverable errors (logged at WARNING) from unrecoverable errors (logged at ERROR or CRITICAL).

## Configuration management

- Store all environment-specific values (database URLs, secret keys, feature flags) in environment variables, not in committed source files.
- Provide a `.env.example` file documenting required variables without real values.
- Validate required configuration at startup and fail fast with a clear message if values are missing.
- Do not use different code paths for dev vs production; use configuration differences only.

## Security

- Validate all external input before use. See `.ecoweaver/security.md` for details.
- Never construct shell commands or SQL strings with user-supplied values.
- Do not store secrets in source code, log output, or error messages.
- Apply the same validation rigour to data import paths as to user-submitted forms.

## Django

- Keep model changes intentional and migration-aware.
- Avoid business logic in templates.
- Put reusable query logic in managers, services, or well-named helpers.
- Use forms/serializers for validation boundaries.
- Do not change migration history unless explicitly requested.

## JavaScript/TypeScript

- Prefer readable state flow over hidden side effects.
- Keep API contracts explicit.
- Avoid adding frontend dependencies without need.
- Use `<button>` and `<a>` for interactive elements; do not attach handlers to `<div>` or `<span>`.
- Announce dynamic content changes with `aria-live` regions.

## Accessibility

All web UI must meet WCAG 2.1 Level AA. See `.ecoweaver/accessibility.md` for full guidance.

Minimum requirements:
- Every form input has an associated label.
- Color is not the only way to convey information.
- All interactive elements are keyboard-reachable.
- Focus is visible at all times.

## Markdown and docs

- Write for future maintainers and collaborators.
- Put commands in fenced code blocks.
- Include expected outputs when useful.
- Keep README quick-start instructions accurate.

## Naming

Use domain language consistently. Avoid vague names such as `data`, `thing`, `item`, or `object` when a domain term exists.

## Commits and PRs

A good change report includes:

- what changed
- why it changed
- how it was verified
- what remains uncertain
