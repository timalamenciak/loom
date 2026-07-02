# Testing and Verification

Testing is part of the change, not an afterthought.

## Default approach

1. Run linting and formatting first (see below). Fix all issues before proceeding.
2. Run the narrowest relevant test.
3. Add or update tests for changed behaviour.
4. Run broader checks only after focused checks pass.
5. Report commands and outcomes honestly.

## Linting (always run before finishing)

Run the full lint sequence after every code change. This is mandatory regardless of task size.

```bash
# Python — run in this order
ruff check --fix .
black .
mypy .           # if configured
bandit -r src/   # if configured
python manage.py check   # Django projects

# Or, if pre-commit is configured:
pre-commit run --all-files

# JavaScript / TypeScript
eslint .
prettier --check .
```

Do not report a task complete with outstanding lint, format, or type errors. If a tool is not installed, say so and provide the install command.

## Test categories

Use the relevant categories for the project:

- unit tests
- integration tests
- schema validation tests
- fixture/example validation
- export/import round-trip tests
- UI smoke tests
- migration checks
- documentation build checks
- security tests (input validation boundaries, auth enforcement)
- accessibility checks (axe-core, keyboard navigation)

## LinkML/schema tests

For schema projects, verify:

- schema compiles
- examples validate
- generated artifacts are current
- round-trip export/import still works where applicable
- old data compatibility is understood

## Django tests

For Django projects, verify:

```bash
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

Customize commands as needed.

## When tests cannot be run

If a command cannot be run because dependencies, services, credentials, or data are missing, say so explicitly and provide the exact command that should be run by a human.

## Security testing

For any code that handles external input, authentication, or authorization, verify:

- Invalid, malformed, and boundary inputs are rejected with appropriate errors.
- Unauthenticated requests to protected endpoints receive a 401 or 403.
- Object-level authorization is enforced: a user cannot access another user's records via URL manipulation.
- File upload limits and MIME type validation are enforced.
- No secrets appear in log output or HTTP responses.

```bash
# Run dependency audit when requirements change
pip-audit
```

## Accessibility testing

For any web UI change, verify:

- New form inputs have associated labels (inspect template or run axe).
- Keyboard navigation reaches all new interactive elements.
- Any dynamic content update announces via `aria-live` or focus management.

Run automated checks if tooling is available:

```bash
# Example: axe-core via pytest-axe or a Playwright test
pytest tests/accessibility/
```

If automated tooling is not available, manually tab through the affected page and confirm all interactions work without a mouse.

## CI/CD integration

Keep CI fast and honest:

- Run unit and schema tests on every push.
- Run integration tests and migration checks on pull requests.
- Run `pip-audit` on dependency changes.
- Report failures without hiding them; never adjust tests to force green CI.

## Do not

- claim tests passed when they were not run
- weaken tests to pass without preserving intended behaviour
- delete tests without explaining why
- skip migration checks after model changes
- skip security tests for "internal" endpoints
- accept all-green CI as proof the feature is correct
