# Review Checklist

Use this before finalizing an AI-generated change, commit, or PR.

## Linting and formatting

- Did `ruff check --fix .` pass with no remaining errors?
- Did `black .` produce no changes (or were all format changes intentional)?
- Did `mypy .` pass (if configured)?
- Did `bandit -r src/` produce no HIGH or MEDIUM findings (if configured)?
- Did `python manage.py check` pass (Django projects)?
- Are any `# noqa` or `# type: ignore` suppressions justified in an inline comment?

## Correctness

- Does the change solve the requested problem?
- Is the implementation minimal and understandable?
- Are edge cases handled?
- Are errors explicit rather than hidden?

## Schema and data integrity

- Are authoritative source files changed instead of generated artifacts only?
- Are generated artifacts current?
- Is provenance preserved?
- Are migrations intentional?
- Is backward compatibility considered?

## Ontology and semantics

- Are ontology terms real and sourced?
- Is uncertainty preserved where appropriate?
- Are local/practitioner terms preserved?
- Are semantic meanings stable?

## Tests

- Were focused tests run?
- Were broader checks run if appropriate?
- Are new tests added for new behaviour?
- Are failures reported honestly?

## Security

- Are all external inputs validated before use?
- Are secrets absent from source files, logs, and responses?
- Are authentication and authorization enforced at the correct layer?
- Are new dependencies audited for known CVEs?
- Is `shell=True` avoided in subprocess calls with user input?
- Are HTTP security headers in place for web endpoints?
- Is CSRF protection active on non-API views?

## Accessibility (web UI only)

- Do all form inputs have associated labels?
- Is color used as the only channel for any information?
- Are all new interactive elements keyboard-reachable?
- Is focus visible and managed correctly for modals and dynamic updates?
- Are ARIA attributes used correctly (not overused, not misapplied)?
- Has axe or Lighthouse been run on new pages?

## Maintainability

- Is the code readable?
- Are names domain-appropriate?
- Are dependencies justified?
- Is documentation updated?
- Are error messages informative and logged at the right level?

## Final response template

Use this structure when reporting back:

```markdown
Changed:
- ...

Linting:
- `ruff check --fix .` — N issues fixed, 0 remaining / not run (reason)
- `black .` — N files reformatted / no changes / not run (reason)
- `mypy .` — passed / N errors / not configured
- `bandit -r src/` — clean / N findings / not configured
- `python manage.py check` — passed / N issues / not applicable

Verified:
- `command` — result

Notes:
- ...

Not verified:
- ...
```
