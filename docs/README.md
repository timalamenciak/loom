# Loom Code Documentation

This documentation describes Loom's code architecture and implementation details.

## Overview

Loom is a self-hosted Django web application for annotating scientific journal articles with the Causal Mosaic (CAMO) schema. It is the human-in-the-loop annotation workbench for EcoWeaver.

## Architecture

Loom follows a **schema-driven** architecture where the LinkML CAMO schema drives all form generation, validation, and serialization. This means:

- forms come from the schema via SchemaView introspection
- validation is LinkML's job (not reimplemented in Python)
- JSONB storage in Postgres with a thin relational layer for querying

### Stack

- **Backend:** Django + PostgreSQL (JSONB + pg_trgm)
- **Frontend:** Django templates + HTMX + Alpine.js + PDF.js
- **Schema:** LinkML (CAMO) via linkml-runtime

## Core Apps

### `apps/annotation`

The annotation engine - nodes, edges, form specs, and export.

**Key modules:**
- `models.py` - Node, Edge, CausalGraph, WorkSession
- `services.py` - Service layer for all ORM mutations
- `schema_engine.py` - Wraps SchemaView to build form specs
- `input_binding.py` - Binds HTML form data to LinkML classes
- `utils.py` - Utility functions (study_duration, geographic lookups)
- `views.py` - HTMX views for annotation UI

**Key concepts:**
- **Form specs** are generated per-graph from the active schema version
- **Input binding** validates against the graph-pinned schema
- **Audit events** are emitted for all mutations

### `apps/schemas`

Schema version management and form spec generation.

**Key modules:**
- `models.py` - SchemaVersion model storing LinkML YAML
- `schema_engine.py` - `LoomSchemaView` wraps SchemaView
- `input_binding.py` - `bind_form_data()` helper
- `services.py` - Schema load/validation

### `apps/ontology`

Local ontology term index with OLS fallback.

**Key modules:**
- `models.py` - OntologyTerm, OntologyRelease, OntologySnapshot
- `loaders.py` - Term loaders (ENVO, PATO, ELMO, etc.)
- `validation.py` - adds_ontology_errors() for form validation

### `apps/projects`

Projects, membership, assignments, and document tracking.

**Key modules:**
- `models.py` - Project, ProjectMembership, Assignment, Document
- `services.py` - Assignment status transitions

### `apps/accounts`

User model with ORCID support.

**Key modules:**
- `models.py` - Custom User model with orcid field

### `apps/audit`

Append-only audit event log.

**Key modules:**
- `models.py` - AuditEvent model
- `middleware.py` - Request-level audit event collection

### `apps/documents`

Document handling (PDF upload, text extraction, canonical text).

**Key modules:**
- `models.py` - Document, TextSpan models
- `services.py` - Text extraction, canonicalization

### `apps/export`

Export to LinkML YAML with validation.

**Key modules:**
- `serializer.py` - `serialize_graph()` to YAML
- `renderers.py` - Rosetta statements, FCM weights
- `validation.py` - LinkML schema validation

### `apps/llm`

LLM proposal seam (disabled by default).

**Key modules:**
- `interfaces.py` - `Proposer` interface
- `noop.py` - No-op proposer (default, always disabled)

## Key Patterns

### 1. Form Generation from Schema

```python
# Get schema view for graph's pinned schema version
lsv = get_schema_view(graph.schema_version)

# Generate form spec (layered, with widgets)
form_spec = lsv.form_spec(
    "CausalEdge",
    ui_layers=ui.get("layers"),
    ontology_routing=ui.get("ontology_routing"),
)
```

### 2. Input Binding

```python
# Bind form data to typed payload
bound = lsv.bind_form_data("CausalEdge", form_data, excluded_slots=_EDGE_MANAGED_SLOTS)

if bound.is_valid:
    # Save with schema-pinned version
    edge.data = bound.data
    edge.schema_version = graph.schema_version
    edge.save()
```

### 3. Service Layer for All Writes

```python
# All ORM mutations go through service layer
from apps.annotation.services import create_node, update_node

# Service emits audit events
node = create_node(graph, data, actor=request.user)
# AuditEvent emitted automatically
```

### 4. JSONB Storage with Relational Promotion

```python
# Node data stored as JSONB
class Node(models.Model):
    data = models.JSONField(default=dict)  # CAMO fields go here
    category = models.CharField(...)  # Promoted field for querying

# Promoted fields enable filtering/querying
Node.objects.filter(category="environmental_variable")
```

## Configuration Files

### `config/loom_ui.yaml`

UI sidecar that augments the schema without editing it:
- Layer grouping for form sections
- Ontology routing per slot
- Widget overrides
- Globally hidden slots

### `config/ontologies.yaml`

Ontology sources:
- Local term loading (ENVO, PATO, ELMO, etc.), optionally scoped to a branch via `root_terms`/`include_descendants`
- Taxa resolve live against Wikidata (`ontology_routing`'s `wikidata_live`), not cached locally
- Preload commands

## Development

### Running Tests

```bash
docker exec loom-web-1 pytest tests/
```

### Linting

```bash
black apps/ annotation/ accounts/ schemas/
ruff check apps/ annotation/ accounts/ schemas/
```

### Schema Migration

```bash
# Load new schema
python manage.py load_schema config/schema/camo-0.7.0.yaml --activate

# List schemas
python manage.py list_schemas

# Validate graph against schema
python manage.py validate_graph <graph_id>
```
