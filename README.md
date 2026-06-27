# Loom

Self-hosted annotation workbench for the **Causal Mosaic (CAMO)** schema. Annotators open PDFs, highlight evidence, decompose entities into ELMO nodes, and annotate causal edges across CAMO's four layers. Loom exports LinkML-validated CAMO instance graphs for downstream EcoWeaver pipelines.

Current package version: **0.1.0** (semantic versioning). The single source of
truth is `loom.__version__`; build metadata and export provenance derive.

Loom is released under the [MIT License](LICENSE).

## What is implemented

- Project membership, per-document assignment, review, and adjudication
- PDF upload, RIS and RIS/PDF bundle import, canonical-text extraction, and spans
- Schema-derived node and edge forms pinned to each project and graph
- Project-pinned ontology snapshots with local search and queued loading
- Active/idle/open time tracking for annotation sessions
- Audited graph writes and LinkML-validated YAML export with SHA-256 provenance
- Deterministic Rosetta statements and fuzzy cognitive map weights

Loom stores schema payloads in JSON rather than CAMO-specific relational
columns. Adding or changing a CAMO slot belongs in the LinkML schema and, when
presentation needs help, `config/loom_ui.yaml`—not in a Django form or model.

Generated forms are also bound on the server: unknown fields are rejected,
values are coerced from their induced LinkML ranges, and enum, cardinality,
numeric-bound, pattern, nested-class, and required-field constraints follow the
graph-pinned schema. Full graph validation runs before submission and export.

## Requirements

- Python 3.11+
- PostgreSQL 16 (via Docker or native)
- Docker + Docker Compose (recommended for development)

## Quick start (Docker)

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd loom

# 2. Configure environment
cp .env.example .env
# Edit .env: set SECRET_KEY to a long random string

# 3. Build and start
make build
docker compose up -d

# 4. Run migrations and create the first admin user
make migrate
make superuser

# 5. Load a bundled CAMO schema
docker compose exec web python manage.py load_schema config/schema/camo-0.5.0.yaml --activate

# 6. (Optional) Preload ontologies
docker compose exec web python manage.py load_ontology --all
```

Open http://localhost:8000 and log in.

Project owners can then open **Project → Settings** to pin a LinkML schema,
review automatically inferred ontology requirements, select additional
configured ontologies, or delete the project. Ontology downloads run in the
`ontology-worker` Compose service so large term sets do not block web requests.

## Environment variables

All variables live in `.env` (copied from `.env.example`). Never commit `.env`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | Django secret key — generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | No | `True` | Set to `False` in production |
| `DB_NAME` | No | `loom` | Postgres database name |
| `DB_USER` | No | `loom` | Postgres user |
| `DB_PASSWORD` | No | `loom` | Postgres password |
| `DB_HOST` | No | `db` | Postgres host (`db` = Docker service name) |
| `DB_PORT` | No | `5432` | Postgres port |
| `ALLOWED_HOSTS` | Prod | — | Comma-separated hostnames, e.g. `loom.example.com` |
| `CSRF_TRUSTED_ORIGINS` | Prod proxy | — | Comma-separated HTTPS origins |
| `DB_CONN_MAX_AGE` | No | `60` | Persistent database connection lifetime in seconds |
| `LOOM_MAX_PDF_UPLOAD_MB` | No | `100` | Per-PDF upload limit |
| `LOOM_MAX_RIS_UPLOAD_MB` | No | `10` | RIS upload limit |
| `LOOM_MAX_BUNDLE_UPLOAD_MB` | No | `500` | Compressed RIS/PDF bundle limit |
| `LOOM_MAX_BUNDLE_UNCOMPRESSED_MB` | No | `1000` | Expanded bundle safety limit |

## Running without Docker

```bash
# Install dependencies (pinned versions for reproducibility)
pip install -r requirements.lock
pip install -e ".[dev]"

# Start Postgres separately (must match .env credentials)

# Apply migrations
python manage.py migrate

# Load a schema and (optionally) ontologies
python manage.py load_schema config/schema/camo-0.5.0.yaml --activate
python manage.py load_ontology --all

# Create admin user
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

## Management commands

```bash
# Schema
python manage.py load_schema config/schema/camo-0.5.0.yaml --activate
python manage.py list_schemas

# Projects and documents
python manage.py create_project "My Project" --admin <username>
python manage.py import_ris <project_id> refs.ris
python manage.py attach_pdf <document_id> paper.pdf

# Ontologies
python manage.py load_ontology envo
python manage.py load_ontology --all
python manage.py process_ontology_loads       # process queued project loads once
python manage.py process_ontology_loads --watch

# Export and validation (export always validates before writing)
python manage.py export_graph <graph_id> -o out.yaml
python manage.py validate_graph <graph_id>

# Schema migration assistant (read-only report)
python manage.py migrate_graph <graph_id> --to-version 0.5.0 --report
```

## Development workflow

```bash
make dev          # docker compose up (attach)
make stop         # docker compose down
make migrate      # run pending migrations
make lint         # ruff + black check
make fmt          # ruff + black auto-fix
make test         # pytest against the configured database
make clean        # remove containers, volumes, caches
```

`make test` uses the configured PostgreSQL database. When PostgreSQL or Docker
is unavailable, run the complete suite with the local SQLite fallback:

```bash
# macOS/Linux
DJANGO_SETTINGS_MODULE=loom.settings.test_sqlite pytest

# PowerShell
$env:DJANGO_SETTINGS_MODULE="loom.settings.test_sqlite"; pytest
```

CI runs Ruff, Black, migration-drift and production-deployment checks before
the PostgreSQL-backed automated test suite.

## Production deployment

1. Set `DEBUG=False` and `ALLOWED_HOSTS` in `.env`.
2. Use `loom.settings.prod` as the settings module (`DJANGO_SETTINGS_MODULE`).
3. Serve static files with WhiteNoise (already configured) or an upstream proxy.
4. Run `python manage.py collectstatic --noinput` during deployment.
5. Run with gunicorn: `gunicorn loom.wsgi:application --bind 0.0.0.0:8000`
6. Put Nginx or Caddy in front for TLS termination.

`prod.py` enforces `SECURE_SSL_REDIRECT`, secure cookies, and HSTS. Ensure your
proxy passes the `X-Forwarded-Proto` header accurately. See the
[operations runbook](docs/operations.md) for health probes, backups, restore
drills, and upgrade guidance.

## Project structure

```
loom/
  manage.py
  pyproject.toml
  loom/settings/        # base.py, dev.py, prod.py
  apps/
    accounts/           # users and roles (annotator, reviewer, admin)
    projects/           # projects, memberships, document assignments
    schemas/            # CAMO LinkML versions, SchemaView wrapper
    documents/          # PDF upload, RIS import, text extraction
    annotation/         # graphs, nodes, edges, annotation UI
    ontology/           # local ontology term index and search
    export/             # YAML serializer, LinkML validation, Rosetta/FCM rendering
    audit/              # append-only AuditEvent log
  config/
    schema/             # CAMO LinkML files (e.g. camo-0.4.0.yaml)
    loom_ui.yaml        # UI hints sidecar (ontology routing, widget overrides)
    ontologies.yaml     # ontology sources and preload list
  static/js/            # pdf-viewer.js, span-select.js, ontology-autocomplete.js
  templates/
  tests/
```

## Roles

| Role | Capabilities |
|---|---|
| `annotator` | Create/edit nodes and edges on assigned documents; submit work |
| `reviewer` | View all annotators' graphs; adjudicate edges (complete→reviewed→gold) |
| `admin` | All reviewer capabilities + manage members, assignments, export CSVs |

Roles are per-project. A user can be an admin in one project and an annotator in another.

## Annotation access and lifecycle

Project membership permits document viewing, but graph and span changes require a
document assignment for the current user. Assignments in `assigned`,
`in_progress`, or `returned` state are editable. Opening assigned or returned
work moves it to `in_progress`; submitting it moves it to `submitted` and makes
the annotation read-only. A reviewer or project admin can return submitted work
from the review screen, after which the annotator can resume it.

Reviewers and administrators use the document review screen to inspect all
assigned graphs and adjudicate completed edges. Their project role does not, by
itself, allow them to modify an annotator's graph through the annotation UI.

Spans are private working records belonging to the annotator who created them.
Reviewers see their effect through the graph and exported edge provenance rather
than sharing a mutable document-wide span list.

## Related software

Several general-purpose annotation platforms exist, but none target the Causal
Mosaic schema or the ELMO node decomposition that CAMO requires:

- **brat** — lightweight span-and-relation annotator; no schema introspection,
  no LinkML export, no multi-layer causal decomposition.
- **INCEpTION** — feature-rich Java platform with ontology linking and custom
  annotation layers, but not designed around a LinkML schema as the single
  source of truth. A schema update requires reconfiguring INCEpTION project
  settings manually.
- **Doccano** — sequence-labelling focus; good for NER but lacks the
  edge-attribute depth CAMO demands (15 causal features, evidential basis,
  philosophical account).
- **Prodigy** — commercial tool with strong active-learning integration; no
  LinkML support; per-seat licensing limits Evidence Jam scale-up.
- **CATMA** — TEI-based; well suited to literary text; not designed for
  structured causal claims or graph export.

Loom's distinguishing features are: (1) forms and validation derived directly
from the active LinkML schema so adding a CAMO slot requires no code change;
(2) JSONB storage that survives schema evolution without migrations; and (3)
SHA-256 provenance and schema pinning on every export for reproducibility.

---

## Limitations

- **Single-user span model.** Spans are private to the annotator who created
  them. Real-time collaborative span editing on the same document is not
  supported.
- **OLS fallback requires network access.** The local ontology index is the
  primary term source; the OLS fallback will silently degrade in
  network-restricted deployments.
- **No real-time collaborative editing.** Two annotators can work on the same
  project simultaneously but not on the same document at the same time without
  risking conflicting graph states.
- **Pre-1.0 API stability.** Minor version bumps may revise annotation
  workflows or management command interfaces before v1.0.
- **PDF display only.** Loom uses PDF.js for document display; span offsets
  are derived from extracted canonical text, not PDF coordinates. Heavily
  scanned or image-only PDFs may have reduced extraction quality.

---

## Versioning

Loom follows semantic versioning while it is pre-1.0:

- Patch releases fix behavior without changing supported workflows.
- Minor releases may add or revise application workflows.
- The CAMO schema has its own independently pinned version on every graph.

Update `loom/__init__.py` for an application release. Do not manually change
the exporter version or duplicate the package version elsewhere.

## Citing Loom

If you use Loom in published research, please cite it using the metadata in
[`CITATION.cff`](CITATION.cff). A formatted citation is:

> Alamenciak, T. (2026). *Loom: A Schema-Driven Annotation Workbench for
> Causal Mosaic Graphs* (v0.1.0). RacoonLab.
> https://github.com/racoonlab/loom

GitHub's "Cite this repository" button (upper right of the repo page) will
generate formatted citations from `CITATION.cff` automatically.
