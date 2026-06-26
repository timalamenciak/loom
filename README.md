# Loom

Self-hosted annotation workbench for the **Causal Mosaic (CAMO)** schema. Annotators open PDFs, highlight evidence, decompose entities into ELMO nodes, and annotate causal edges across CAMO's four layers. Loom exports LinkML-validated CAMO instance graphs for downstream EcoWeaver pipelines.

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

# 5. Load the CAMO schema
docker compose exec web python manage.py load_schema config/schema/camo-0.4.0.yaml --activate

# 6. (Optional) Preload ontologies
docker compose exec web python manage.py load_ontology --all
```

Open http://localhost:8000 and log in.

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

# Load schema and (optionally) ontologies
python manage.py load_schema config/schema/camo-0.4.0.yaml --activate
python manage.py load_ontology --all

# Create admin user
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

## Management commands

```bash
# Schema
python manage.py load_schema config/schema/camo-0.4.0.yaml --activate
python manage.py list_schemas

# Projects and documents
python manage.py create_project "My Project" --admin <username>
python manage.py import_ris <project_id> refs.ris
python manage.py attach_pdf <document_id> paper.pdf

# Ontologies
python manage.py load_ontology envo
python manage.py load_ontology --all

# Export and validation
python manage.py export_graph <graph_id> --format yaml --validate -o out.yaml
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
make test         # pytest (pure-Python tests; DB tests require Postgres)
make clean        # remove containers, volumes, caches
```

## Production deployment

1. Set `DEBUG=False` and `ALLOWED_HOSTS` in `.env`.
2. Use `loom.settings.prod` as the settings module (`DJANGO_SETTINGS_MODULE`).
3. Serve static files with WhiteNoise (already configured) or an upstream proxy.
4. Run with gunicorn: `gunicorn loom.wsgi:application --bind 0.0.0.0:8000`
5. Put Nginx or Caddy in front for TLS termination.

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
    ontology/           # local term index, OLS fallback
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
