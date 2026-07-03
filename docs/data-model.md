# Data Model

## Database Schema

### User (accounts)

Extended Django User model with ORCID support.

**Fields:**
- `orcid`: ORCID iD (format: 0000-0000-0000-0000)
- All standard Django User fields (username, email, first_name, last_name)

### Project (projects)

Top-level organizational unit for annotation work.

**Fields:**
- `name`: Project name
- `source_document_layers`: UI layer config (JSON)
- `source_document_rollup`: Aggregation rules (JSON)
- `ontology_snapshot`: Active ontology snapshot

**Relationships:**
- Has many `ProjectMembership` (users and roles)
- Has many `Document` (references)
- Has one active `OntologySnapshot`

### ProjectMembership (projects)

Links users to projects with roles.

**Fields:**
- `role`: annotator|reviewer|admin

### Assignment (projects)

Assigns a document to an annotator for work tracking.

**Status lifecycle:**
```
assigned → in_progress → submitted → completed
                         ↘ returned → in_progress
```

### Document (projects)

A reference document (PDF and/or RIS).

**Fields:**
- `canonical_text`: Extracted text with character offsets
- `canonical_markdown`: PDF → Markdown
- `source_metadata`: BibTeX/RIS data

### TextSpan (documents)

A span of text in a document (annotations are grounded here).

**Fields:**
- `start_char`, `end_char`: Character offsets
- `text`: Verbatim text
- `node`, `edge`: Foreign keys to grounded annotations

### SchemaVersion (schemas)

A version of the CAMO LinkML schema.

**Purpose:**
- Schema can evolve without breaking existing graphs
- Each graph pins to specific schema version
- Migration assistant can update graphs to new schema

### OntologySnapshot (ontology)

A point-in-time copy of ontology terms.

**Relationships:**
- Has many `OntologyTerm` (the terms)
- Used by `CausalGraph.ontology_snapshot`

### OntologyTerm (ontology)

A single ontology term.

**Fields:**
- `ontology`: ENVO, PATO, ELMO, etc. (taxa resolve live against Wikidata, not cached locally)
- `term_id`: e.g., "PATO:0000070"
- `label`, `synonyms`, `definition`

### CausalGraph (annotation)

Top-level container for a document's annotation graph.

**Fields:**
- `source_document`: Bibliographic metadata (JSONB)
- `provenance`: Graph creation metadata (JSONB)

### Node (annotation)

A node in the causal graph (a causal entity).

**CAMO fields in `data` (JSONB):**
- `entity_term`: Ontology term (required)
- `measured_attribute`: Attribute (required)
- `category`: Biolink-compatible category

**Promoted fields (for querying):**
- `category` (from data['entity_type'])

### Edge (annotation)

An edge in the causal graph (a causal relationship).

**CAMO fields in `data` (JSONB):**
1. **Layer 1:** predicate, claim_strength
2. **Layer 2:** philosophical_accounts, account_families
3. **Layer 3:** necessity, sufficiency, direction, strength, etc.
4. **Layer 4:** evidential_basis, annotation_confidence

**Promoted fields (for querying):**
- `predicate`
- `claim_strength`
- `status`

### WorkSession (annotation)

Tracks active annotation time.

**Fields:**
- `active_seconds`: Time user was typing/making changes
- `idle_seconds`: No activity detected
- `open_seconds`: Tab open (not all is productive work)

### AuditEvent (audit)

Records all mutations.

**Fields:**
- `actor`: User who performed action
- `action`: node.create, edge.update, etc.
- `target_type`: Node, Edge, Assignment, etc.
- `target_id`: Primary key
- `diff`: Changes made (JSON)
