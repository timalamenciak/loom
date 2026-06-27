# Contributing to Loom

Thank you for improving Loom. The central design constraint is that CAMO
annotation structure comes from the active LinkML schema. Do not add a Django
model field or handwritten form field for a CAMO slot; extend the schema engine
or `config/loom_ui.yaml` instead.

## Development setup

Follow the README quick start, create a focused branch, and keep unrelated work
out of the change. Before submitting a pull request, run:

```bash
ruff check .
black --check .
pytest
python manage.py makemigrations --check --dry-run
```

PostgreSQL is the authoritative test database. The SQLite settings are a fast
fallback and do not cover PostgreSQL-specific behavior.

## Change requirements

- Route graph, span, assignment-status, and other audited mutations through a
  service boundary.
- Add authorization tests for every new project-scoped endpoint.
- Add migrations for model changes and test upgrade behavior.
- Add schema contract tests when changing generated forms or serialization.
- Preserve source spans, schema pins, ontology pins, and audit provenance.
- Update user and operator documentation in the same pull request.
- Do not enable LLM proposals or allow automation to complete human claims.

Use precise commit messages that explain the behavior changed. Pull requests
should describe risk, migrations, validation performed, and rollback behavior.
See `AGENTS.md` for the complete repository architecture and invariants.

## Bias and fairness considerations

Loom collects inter-annotator reliability (IRR) CSVs to monitor agreement.
When adding annotation features or enabling the LLM proposal seam, consider:

- **Annotator bias.** Complex or ambiguous CAMO slots may introduce systematic
  differences between annotators. Track IRR per slot, not just per edge.
- **LLM proposal bias.** LLM pre-fills may reflect publication bias (positive
  results over null findings) or taxonomic bias (common species over rare ones).
  Compare IRR metrics with and without LLM pre-fills before enabling in
  production. See `docs/llm-proposals.md` for detailed guidance.
- **Adjudication transparency.** When a reviewer overrides an annotator's edge
  to `gold`, the original annotation and the reviewer's justification should be
  retained in the `diff` field of the `AuditEvent` so disagreements are
  auditable, not silently erased.
