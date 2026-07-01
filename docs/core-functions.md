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
def create_node(graph, data, origin=Node.ORIGIN_HUMAN, actor=None)
```
Create a new node.

**Parameters:**
- `data`: Dict with CAMO fields (entity_term, measured_attribute, etc.)
- `origin`: "human" or "llm_proposed"

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
def create_edge(graph, subject, object_node, data, origin=Edge.ORIGIN_HUMAN, actor=None)
```
Create a new edge between two nodes.

**Parameters:**
- `subject`: Node (cause)
- `object_node`: Node (effect)
- `data`: Dict with CAMO causal features

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

## Settings (`loom/settings/`)

### Common Settings

```python
MAX_PDF_UPLOAD_BYTES = 2048 * 1024 * 1024  # 2 GB
MAX_RIS_UPLOAD_BYTES = 10 * 1024 * 1024    # 10 MB
MAX_BUNDLE_UPLOAD_BYTES = 2048 * 1024 * 1024
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
