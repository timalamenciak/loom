# Django Feature Skill

Use this skill for Django model, view, form, template, admin, API, or migration work.

## Workflow

1. Read project instructions and architecture notes.
2. Locate the relevant app.
3. Inspect models, URLs, views, forms/serializers, templates, tests, and migrations.
4. Make the smallest coherent change.
5. Add or update tests.
6. Run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Use narrower test commands first when possible.

## Guardrails

- Do not rewrite migration history casually.
- Do not put business logic in templates.
- Do not change models without considering migrations.
- Do not introduce dependencies without justification.
