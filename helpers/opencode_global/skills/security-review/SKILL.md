# Security Review Skill

Use this skill when auditing code for vulnerabilities, reviewing security-sensitive changes, or preparing for release.

## Workflow

1. Read `.ecoweaver/security.md`.
2. Identify all external input paths (user forms, file uploads, API calls, environment variables).
3. Check that each input is validated before use in queries, file paths, or commands.
4. Check that secrets are not in source files or version-controlled `.env` files.
5. Check authentication and authorization at the model/service layer, not only the UI.
6. Check Django deployment settings: `DEBUG`, `ALLOWED_HOSTS`, `SECURE_*`, `CSRF_*`.
7. Review HTTP security headers: CSP, `X-Frame-Options`, `X-Content-Type-Options`.
8. Check dependency security: run `pip-audit` or `safety check` if dependencies changed.
9. Separate findings into blockers, important issues, and minor improvements.

## Guardrails

- Do not weaken validation or authentication to satisfy other requirements.
- Do not commit secrets or example credentials to any file.
- Do not use `shell=True` in subprocess calls with user-derived input.
- Do not bypass CSRF protection on non-API views without documented justification.
- Do not expose internal database identifiers where surrogate identifiers can be used.

## Output format

```
Security findings:

Blockers:
- ...

Important:
- ...

Minor:
- ...

Commands run:
- pip-audit — result
```
