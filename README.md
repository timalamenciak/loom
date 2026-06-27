# Loom

Self-hosted annotation workbench for the **Causal Mosaic (CAMO)** schema. Annotators open PDFs, highlight evidence, decompose entities into ELMO nodes, and annotate causal edges across CAMO's four layers. Loom exports LinkML-validated CAMO instance graphs for downstream EcoWeaver pipelines.

Current package version: **0.1.0** (semantic versioning). The single source of
truth is `loom.__version__`; build metadata and export provenance derive.

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

## Running without Docker

```bash
# Install dependencies
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

# Export and validation
python manage.py export_graph <graph_id> --validate -o out.yaml
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

The repository currently contains 206 automated tests. CI also runs Ruff and
Black checks before the PostgreSQL-backed suite.

## Production deployment

1. Set `DEBUG=False` and `ALLOWED_HOSTS` in `.env`.
2. Use `loom.settings.prod` as the settings module (`DJANGO_SETTINGS_MODULE`).
3. Serve static files with WhiteNoise (already configured) or an upstream proxy.
4. Run `python manage.py collectstatic --noinput` during deployment.
5. Run with gunicorn: `gunicorn loom.wsgi:application --bind 0.0.0.0:8000`
6. Put Nginx or Caddy in front for TLS termination.

`prod.py` enforces `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and a one-year HSTS header — ensure your proxy passes the `X-Forwarded-Proto` header.

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

## Versioning

Loom follows semantic versioning while it is pre-1.0:

- Patch releases fix behavior without changing supported workflows.
- Minor releases may add or revise application workflows.
- The CAMO schema has its own independently pinned version on every graph.

Update `loom/__init__.py` for an application release. Do not manually change
the exporter version or duplicate the package version elsewhere.
