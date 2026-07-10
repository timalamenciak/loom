# Loom v1.0.0 Roadmap

**Current:** v0.3.0 · **Target:** v1.0.0 · **Detailed plans:** [`docs/roadmap/`](docs/roadmap/)

## Milestones

| Version | Name | Epic | Status |
|---------|------|------|--------|
| [v0.4.0](docs/roadmap/v0.4.0-schema-admin.md) | Schema Admin Foundation | E1: Schema | ⬜ Not started |
| [v0.5.0](docs/roadmap/v0.5.0-form-builder.md) | Visual Form Builder | E1: Schema | ⬜ Not started |
| [v0.6.0](docs/roadmap/v0.6.0-ontology-manager.md) | Ontology Manager | E2: Ontology | ⬜ Not started |
| [v0.7.0](docs/roadmap/v0.7.0-update-manager.md) | Module Update Manager | E3: Updates | ⬜ Not started |
| [v0.8.0](docs/roadmap/v0.8.0-llm-pipeline.md) | LLM Pipeline Core | E4: LLM | ⬜ Not started |
| [v0.9.0](docs/roadmap/v0.9.0-few-shot-metrics.md) | Few-Shot & Metrics | E4: LLM | ⬜ Not started |
| [v1.0.0](docs/roadmap/v1.0.0-release.md) | Release Hardening | All | ⬜ Not started |

## Development Sequence

E1 (Schema) must complete v0.4 before E2 (Ontology) or E4 (LLM) can start — both depend on the DB-backed `SchemaUIConfig` model. E3 (Updates) is independent and can run in parallel with E2 after v0.4.

```
v0.3.0 → v0.4.0 → v0.5.0 ─┬─ v0.6.0 ─┐
                             │           ├─ v0.8.0 → v0.9.0 → v1.0.0
                             └─ v0.7.0 ─┘
                              (parallel)
```

**Solo developer:** run linearly v0.4 → v0.5 → v0.6 → v0.7 → v0.8 → v0.9 → v1.0.

**Two-person split:** one takes E1+E4 (v0.4→v0.5→v0.8→v0.9), other takes E2+E3 (v0.6→v0.7) once v0.4 lands.

## Cross-cutting Conventions

These apply to every milestone. Any prompt you give Claude Code for this project should reinforce them:

- **No new npm dependencies.** Alpine.js and HTMX are already in `static/`. Use them for all frontend interactivity.
- **No new Python packages without updating `pyproject.toml`.** The only anticipated new dep is `anthropic` for E4.
- **Every new model requires a migration**, and migrations must be tested (`pytest --migrations` in CI).
- **Every admin-only view must be `login_required` + `user.is_staff`.** Test both the authorized and unauthorized cases.
- **Writes to nodes/edges go through the service layer.** Do not call ORM directly from views; use `apps/annotation/services.py`.
- **No CAMO slot names in new Python code.** If you find yourself writing `claim_strength` or `causal_mechanism` in a new view, model, or form, the field belongs in the schema engine, not Python.
- **Schema-agnostic forms.** All form structure derives from `LoomSchemaView(schema_version).form_spec()`. Never hardcode a class or slot list.

## Baseline (v0.3.0)

The following are already production-quality — do not reimplement them:

| Component | Location | State |
|-----------|----------|-------|
| Schema form-spec builder | `apps/schemas/schema_engine.py` | Full, schema-driven |
| Input binding & validation | `apps/schemas/input_binding.py` | Full |
| UI config sidecar | `config/loom_ui.yaml` | Real, 209 lines |
| OBO/OWL ontology loader | `apps/ontology/loaders.py` | Full |
| Trigram + Wikidata search | `apps/ontology/services.py` | Full |
| Graph serializer + export | `apps/export/serializer.py` | Full |
| Schema update CLI | `apps/schemas/management/commands/` | Working, no UI |
| LLM proposer protocol | `apps/llm/proposer.py` | Protocol + NoOp only |

## Nightly Workflow

See [`docs/roadmap/NIGHTLY_WORKFLOW.md`](docs/roadmap/NIGHTLY_WORKFLOW.md) for the evening/morning routine for running Claude Code autonomously overnight and reviewing results the next day.
