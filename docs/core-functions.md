# Core Functions Reference

## Service Layer (`apps/annotation/services.py`)

All ORM mutations go through the service layer. This ensures audit trail and schema validation.

### Graph Operations

```python
@transaction.atomic
def create_graph(document, annotator, schema_version, ontology_snapshot=None)
```
Create a new annotation graph.

**Returns:** CausalGraph instance

```python
@transaction.atomic
def update_graph_source_document(graph: CausalGraph, data: dict, actor)
```
Update the source document metadata.

**Returns:** Updated graph

```python
@transaction.atomic
def upgrade_graph_ontology_snapshot(graph: CausalGraph, snapshot, actor)
```
Move a graph to a newer ontology snapshot.

**Returns:** Updated graph

```python
@transaction.atomic
def delete_graph(graph: CausalGraph, actor)
```
Delete a graph and all its nodes/edges.

### Node Operations

```python
@transaction.atomic
def create_node(graph, data, origin=Node.ORIGIN_HUMAN, actor=None, node_id=None)
```
Create a new node.

**Parameters:**
- `data`: Dict with CAMO fields (entity_term, measured_attribute, etc.)
- `origin`: "human" or "llm_proposed"
- `node_id`: explicit id to assign instead of the model's random-UUID default
  — used by the bulk importer (`apps/export/graph_import.py`) so a created
  row lands with the file's own id and re-imports resolve as updates, not
  duplicate creates

**Returns:** Node instance

```python
@transaction.atomic
def update_node(node: Node, data: dict, actor=None)
```
Update an existing node.

**Returns:** Updated node

```python
@transaction.atomic
def set_node_source_spans(node: Node, spans, actor)
```
Associate text spans with a node.

```python
@transaction.atomic
def delete_node(node: Node, actor)
```
Delete a node and its connected edges.

### Edge Operations

```python
@transaction.atomic
def create_edge(graph, subject, object_node, data, origin=Edge.ORIGIN_HUMAN, actor=None, edge_id=None)
```
Create a new edge between two nodes.

**Parameters:**
- `subject`: Node (cause)
- `object_node`: Node (effect)
- `data`: Dict with CAMO causal features
- `edge_id`: explicit id to assign instead of the model's random-UUID
  default — same purpose as `create_node`'s `node_id`, for the bulk importer

**Returns:** Edge instance

```python
@transaction.atomic
def update_edge(edge: Edge, data, subject=None, object_node=None, actor=None)
```
Update an existing edge.

**Returns:** Updated edge

```python
@transaction.atomic
def set_edge_source_spans(edge: Edge, spans, actor)
```
Associate text spans with an edge.

```python
@transaction.atomic
def delete_edge(edge: Edge, actor)
```
Delete a single edge, leaving its endpoint nodes untouched.

```python
@transaction.atomic
def advance_edge_status(edge: Edge, actor)
```
Advance edge status: draft → complete.

**Returns:** Updated edge

```python
@transaction.atomic
def adjudicate_edge(edge: Edge, actor)
```
Reviewer operation: complete → reviewed or reviewed → gold.

**Returns:** Updated edge

### Session Operations

```python
def heartbeat(session: WorkSession, active_delta, idle_delta)
```
Update session time tracking.

**Parameters:**
- `active_delta`: Seconds of active work
- `idle_delta`: Seconds of idle time

```python
@transaction.atomic
def close_session(session: WorkSession)
```
End a session and calculate total open time.

### Audit Operations

```python
def emit_audit(actor, action: str, target_type: str, target_id="", diff=None)
```
Append one `AuditEvent` row. Every mutating service function above calls this
— it's the only place `AuditEvent` rows get created.

```python
def emit_import_audit(actor, graph, *, format: str, full_sync: bool, counts: dict)
```
Append one wrapping `graph.import` `AuditEvent` after a bulk import applies,
summarizing format/full_sync/row counts — the individual
create/update/delete calls it wraps already emitted their own events via
`emit_audit`.

### Utility Functions

```python
def _annotate_with_orcid(data: dict, user) -> dict
```
Add annotator identifier to data.

**Purpose:** Automatically includes ORCID if available

**Returns:** Updated data dict

```python
def _derive_name(data: dict) -> str
```
Generate a node name from CAMO fields.

**Format:** "entity_type — entity_term — measured_attribute"

```python
def _preprocess_source_document(data: dict) -> dict
```
Calculate derived fields for source document data.

**Purpose:** Auto-calculate `study_duration_months` from start/end dates

**Returns:** Updated data dict with calculated fields

## Schema Engine (`apps/schemas/schema_engine.py`)

Wraps linkml-runtime SchemaView to build form specs.

### LoomSchemaView

```python
class LoomSchemaView:
    def __init__(self, schema_version)
    def class_names() -> list[str]
    def enum_names() -> list[str]
    def form_spec(class_name, ui_layers, ontology_routing, widget_overrides) -> list[dict]
    def bind_form_data(class_name, form_data, excluded_slots) -> BindingResult
```

### Form Spec Structure

```python
[
    {
        "id": "layer1",
        "label": "Layer 1: Claim & Predicate",
        "collapsed_by_default": False,
        "slots": [
            {
                "name": "predicate",
                "label": "Predicate",
                "widget": "select",  # text|number|checkbox|select|ontology_autocomplete|fieldset
                "required": False,
                "multivalued": False,
                "description": "...",
                "choices": [{"value": "causes", "label": "Causes", ...}],
                "ontology_prefixes": [],
            },
            ...
        ]
    },
    ...
]
```

### Binding Result

```python
class BindingResult:
    data: dict[str, Any]  # Validated, typed data
    errors: dict[str, list[str]]  # Field errors
    is_valid: bool
```

## Input Binding (`apps/schemas/input_binding.py`)

Converts HTML form data to typed Python objects validated against the schema.

```python
def bind_form_data(schema_view, class_name, form_data, excluded_slots) -> BindingResult
```

**What it does:**
1. Walks schema-induced slots for class
2. Coerces values to correct types (int, float, bool)
3. Validates enum membership
4. Checks numeric bounds
5. Validates patterns
6. Handles nested fields (via `__` separator)
7. Validates cardinality (minimum/maximum values)

**Excluded slots:** Auto-generated fields like `node_id`, `source_spans`

## Bulk Import/Export (`apps/export/`)

Format-agnostic diff-then-apply core for bulk-editing a graph's nodes/edges
from Excel or YAML. Excel/YAML readers hand off plain row dicts; everything
else (column validation, diffing, writing) is shared and schema-driven —
never a hardcoded CAMO slot name.

```python
# apps/export/graph_import.py
def build_import_plan(graph, node_rows, edge_rows, *, schema_view, full_sync,
                       source_sha256, format, uploaded_by_id) -> ImportPlan
```
Diff uploaded rows against the graph's current state. No writes. Each row
gets a `RowResult.verdict`: `create` / `update` / `noop` / `would_delete`
(full_sync only) / `error`. Matches `subject_node_id`/`object_node_id`
against nodes in the same file *or* already on the graph. Under `full_sync`,
an edge that would survive but references a node about to be deleted
becomes an `error` instead of landing orphaned.

```python
def apply_import_plan(plan: ImportPlan, actor) -> dict[str, int]
```
Commit an approved plan inside one transaction, via the normal
`create_node`/`update_node`/`create_edge`/`update_edge`/`delete_node`/
`delete_edge` service calls (never `bulk_create`, so audit events still
fire). Re-resolves ids against the database at apply time rather than
trusting the plan's cached verdicts, so a plan a few minutes stale still
applies safely. Returns the same counts dict `ImportPlan.counts()` produces.

```python
def render_plan_text(plan: ImportPlan) -> str
```
Human-readable per-row report; the CLI's stdout output and the web preview
page's content are the same string.

```python
# apps/export/import_excel.py
def write_graph_xlsx(graph, *, blank: bool = False) -> bytes
def parse_xlsx_import(file_obj) -> tuple[list[dict], list[dict]]

# apps/export/import_yaml.py
def parse_yaml_import(file_obj) -> tuple[list[dict], list[dict]]

# apps/export/import_store.py — preview/apply carry-over for the web flow
def stash_plan(plan: ImportPlan) -> str    # returns a cache token
def load_plan(token: str) -> ImportPlan | None
def discard_plan(token: str) -> None
```

**Authorization:** `apps.annotation.policies.require_import_access(document,
user)` — admins bypass `Assignment` status entirely; everyone else needs an
editable assignment (same rule as manual edits).

## Views (`apps/annotation/views.py`)

### HTMX Endpoints

#### Form Views

```python
class NodeFormView
class EdgeFormView
class SourceDocumentFormView
```
GET → render form partial

#### Creation Views

```python
class NodeCreateView
class EdgeCreateView
```
POST → validate, save, return graph panel

#### Edit Views

```python
class NodeEditView
class EdgeEditView
```
GET → load form with existing data
POST → save changes

#### Status Views

```python
class NodeDeleteView
class EdgeAdvanceView
class EdgeAdvanceView
```

#### Utility Views

```python
class AutoSaveView
```
PATCH → save field update via debounced auto-save

#### Session Views

```python
class HeartbeatView
```
POST → update active/idle time

#### Submission Views

```python
class SubmitAnnotationView
```
POST → mark assignment as submitted and close sessions

## Export/Import Views (`apps/export/views.py`)

```python
class ExportGraphView       # GET → export detail page; ?download=1 streams YAML
class ValidateGraphView     # GET → LinkML validation report
class ExportExcelView       # GET → .xlsx download; ?blank=1 for the import template
class ImportUploadView      # GET → upload form; POST → parse/diff, stash plan, redirect to preview
class ImportPreviewView     # GET → per-row diff report for a stashed plan (no writes)
class ImportApplyView       # POST → apply_import_plan(), discard the stashed plan
```

## Settings (`loom/settings/`)

### Common Settings

```python
MAX_PDF_UPLOAD_BYTES = 2048 * 1024 * 1024  # 2 GB
MAX_RIS_UPLOAD_BYTES = 10 * 1024 * 1024    # 10 MB
MAX_BUNDLE_UPLOAD_BYTES = 2048 * 1024 * 1024
MAX_GRAPH_IMPORT_UPLOAD_BYTES = 25 * 1024 * 1024  # Bulk Excel/YAML import upload limit
LOOM_IMPORT_PLAN_TTL_SECONDS = 15 * 60  # Stashed import preview lifetime
LOOM_MARKER_ENABLED = False  # Use MarkerPDF instead of pdfplumber
LLM_PROPOSALS_ENABLED = False  # LLM proposal seam (disabled by default)
GEONAMES_USERNAME = None  # Optional for geographic lookups
```

### Database

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "loom"),
        "USER": os.environ.get("DB_USER", "loom"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "loom"),
    }
}
```
