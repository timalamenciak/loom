# Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Django)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   HTMX UI    │->│   Views.py   │->│ Services.py  │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│         │                  │                  │                   │
│         └──────────────────┼──────────────────┘                   │
│                            │                                      │
│                  ┌─────────▼─────────┐                           │
│                  │   Schema Engine   │                           │
│                  │  (SchemaView)     │                           │
│                  └─────────┬─────────┘                           │
└────────────────────────────┼──────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│  Database   │    │  Ontology   │    │   Export/    │
│ (Postgres)  │    │  Index      │    │  Serialization│
└─────────────┘    └─────────────┘    └──────────────┘
```

## Core Data Models

### Node

Represents a causal entity (state or change in state).

```python
class Node(models.Model):
    graph = ForeignKey(CausalGraph)
    node_id = UUIDField()  # Unique within graph
    name = CharField()  # Display name
    category = CharField()  # Promoted for querying
    data = JSONField()  # CAMO fields: entity_term, measured_attribute, etc.
    origin = CharField()  # human | llm_proposed
    schema_version = ForeignKey(SchemaVersion)
```

**CAMO fields stored in `data`:**
- `entity_term` (required): Ontology term, or free text if uncached (Wikidata for taxa, ELMO/ENVO for processes, ENVO for environments)
- `measured_attribute` (required): Attribute, or free text if uncached (PATO, GO, etc.)
- `entity_type`: routes entity_term to the right ontology (taxon -> Wikidata, management_intervention -> ELMO, environmental_process -> ENVO, environmental_variable -> ELMO+ENVO)

### Edge

Represents a causal relationship between two nodes.

```python
class Edge(models.Model):
    graph = ForeignKey(CausalGraph)
    subject = ForeignKey(Node)  # Cause
    object = ForeignKey(Node)  # Effect
    edge_id = UUIDField()
    predicate = CharField()  # Promoted
    claim_strength = CharField()  # Promoted
    status = CharField()  # draft|complete|reviewed|gold
    origin = CharField()  # human|llm_proposed
    data = JSONField()  # All CAMO causal features
    schema_version = ForeignKey(SchemaVersion)
```

**CAMO layers (all in `data`):**
1. **Layer 1:** Claim strength, predicate
2. **Layer 2:** Philosophical accounts
3. **Layer 3:** Causal features (necessity, sufficiency, strength, etc.)
4. **Layer 4:** Evidential basis

### CausalGraph

Top-level container for annotations of a document.

```python
class CausalGraph(models.Model):
    document = ForeignKey(Document)
    annotator = ForeignKey(User)
    schema_version = ForeignKey(SchemaVersion)  # Pinned version
    ontology_snapshot = ForeignKey(OntologySnapshot)
    provenance = JSONField()
    source_document = JSONField()  # Bibliographic metadata
    status = CharField()  # draft|complete|gold
```

### WorkSession

Tracks active annotation time per user.

```python
class WorkSession(models.Model):
    assignment = ForeignKey(Assignment)
    annotator = ForeignKey(User)
    started_at = DateTimeField()
    ended_at = DateTimeField()
    active_seconds = IntegerField()  # Actual work time
    idle_seconds = IntegerField()
    open_seconds = IntegerField()  # Tab open time
```

## Form Generation Pipeline

```
1. User clicks "Add Node"
   ↓
2. views.py: NodeFormView.get()
   ↓
3. schema_engine.py: form_spec(class_name="CausalNode")
   ↓
4. SchemaView.class_induced_slots() → slot list
   ↓
5. For each slot, extract:
   - Name, label, description
   - Range → widget type (string→text, enum→select)
   - Required, multivalued
   - Enum choices
   - Ontology prefixes for autocomplete
   ↓
6. Return layered form spec
   ↓
7. Template renders fields with widget-specific HTML
   ↓
8. User fills form
   ↓
9. Form POST → views.py: NodeCreateView.post()
   ↓
10. input_binding.py:bind_form_data()
   ↓
11. SchemaView.bind_form_data() validates per schema
   ↓
12. Services.py: create_node() saves to JSONB
```

## Input Binding

The `bind_form_data()` function converts HTML form data to typed Python objects.

```python
from apps.schemas.input_binding import bind_form_data

# For a CausalNode
bound = bind_form_data(
    schema_view,
    "CausalNode",
    form_data,
    excluded_slots={"node_id", "source_spans"}
)

if bound.is_valid:
    # bound.data is typed and validated
    node.data = bound.data
else:
    # bound.errors dict with field names → error messages
    pass
```

**What validation it performs:**
- Required fields
- Range/type coercion (string, integer, float, boolean)
- Enum membership (via permissible_values)
- Numeric bounds (minimum_value, maximum_value)
- Pattern matching (regex patterns)

## JSONB Storage Strategy

**Relational columns** (for querying/filtering):
- `Node.category` (from `data['entity_type']`)
- `Edge.predicate`
- `Edge.claim_strength`
- `Edge.status`
- `Edge.created_at`, `updated_at`

**JSONB column** (`data`):
- All other CAMO fields
- Can evolve with schema without migrations
- Validated on write/export via SchemaView

## Audit Trail

Every mutation emits an `AuditEvent`:

```python
@transaction.atomic
def create_node(graph, data, actor=None) -> Node:
    node = Node.objects.create(...)
    emit_audit(actor or graph.annotator, "node.create", "Node", node.pk, data)
    return node
```

**AuditEvent fields:**
- `actor`: User who performed action
- `action`: "node.create", "edge.update", etc.
- `target_type`: "Node", "Edge", etc.
- `target_id`: Primary key
- `diff`: Changes made (for updates)

## Schema Versioning

Each graph pins the schema version at creation:

```python
graph.schema_version  # SchemaVersion model
graph.schema_version.linkml_yaml  # Complete CAMO YAML
graph.schema_version.version  # "0.7.0", "0.4.0", etc.
graph.schema_version.sha256  # Content hash
```

**Why?**
- Schema can evolve (new slots, enums, constraints)
- Existing graphs should validate against schema at time of creation
- Migration assistant can update old graphs to new schema

## Migration Path

To migrate a graph to a newer schema:

```python
# In migration assistant
from linkml_runtime.utils.schemaview import SchemaView

# Load old and new schemas
old_schema = SchemaView(graph.schema_version.linkml_yaml)
new_schema = SchemaView(new_linkml_yaml)

# Transform data
for node in graph.nodes.all():
    data = node.data
    # Map old field names to new
    if "variable_attribute" in data:
        data["measured_attribute"] = data.pop("variable_attribute")
    node.data = data
    node.schema_version = new_version
    node.save()
```

## The One Defining Constraint

> **Loom is driven by the LinkML schema, not by hardcoded fields.**

This means:
- Never add Django model fields for CAMO slots
- Never hardcode form field names
- Never validate CAMO constraints in Python
- Always use SchemaView to introspect and validate

If you find yourself writing code that names a CAMO slot, you should stop and reconsider: that belongs in the schema.
