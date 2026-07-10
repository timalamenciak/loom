# Changelog

All notable changes to Loom are documented here. The project follows
Semantic Versioning. Application versions are independent of CAMO schema
versions.

---

## [0.3.0] — 2026-07-10

First stable release of Loom, the self-hosted annotation workbench for the
Causal Mosaic (CAMO) schema.

### Core annotation workflow

**Two-pane annotation interface.** A resizable split view places the source
document on the left and the annotation sidebar on the right. Annotators drag a
handle to adjust the split to their screen.

**Document views.** The document pane has three switchable views: PDF rendered
page-by-page via PDF.js, extracted plain text with inline span highlights, and
rendered Markdown when available.

**Text span selection.** Selecting any text in the canonical-text or Markdown
view surfaces a floating "Create span" tooltip. Character offsets are computed
by TreeWalker over the live DOM so highlights survive `<mark>` injections and
other inline elements. Spans are stored with `start_char`/`end_char` offsets
into the canonical text and can be linked to any node or edge.

**Schema-driven forms.** Annotation forms for nodes and edges are generated at
runtime from the active CAMO LinkML schema via `linkml-runtime SchemaView`. No
CAMO slot names are hardcoded in Python; when the schema changes, forms follow
automatically.

**CAMO four-layer edge annotation.** The edge form is organised into collapsible
layers defined in `config/loom_ui.yaml`:
- Layer 1 — Claim & Predicate: predicate, claim strength, negated, original sentence
- Layer 2 — Philosophical Account
- Layer 3 — Causal Features: fifteen slots, collapsed by default
- Layer 4 — Evidential Basis: source spans, evidential basis, annotation confidence, notes

**ELMO nodes.** Nodes carry entity type, name, description, taxonomic scope,
measured attribute, and applied-to relationships. The `applied_to` slot uses a
dedicated widget that routes ontology lookups by `entity_type` value (taxon →
Wikidata, management_intervention → ELMO, environmental_process → ENVO, etc.).

**Edge status lifecycle.** Edges follow `draft → complete → reviewed → gold`.
Annotators advance their own edges to `complete`; reviewers and admins can mark
`gold`. Nothing but a human transitions to `complete` or `gold`.

**SourceDocument form.** A dedicated form pre-populated from bibliographic
metadata captures study-level attributes (geographic scope, temporal scope, study
coordinates, sample size, etc.) and stores them once per graph rather than per
edge.

**Study coordinates widget.** A `coordinate_list` widget lets annotators enter
`lat,lng` pairs one at a time, stored as a multivalued nested list. When
`LOOM_GEONAMES_USERNAME` is set, saving a coordinate automatically fills
`study_country` and `study_state_or_province` via GeoNames reverse-geocode.

**Excerpt bin.** Source spans gathered from the document are held in a sidebar
bin before being attached to a node or edge, letting annotators collect
supporting passages from multiple locations before committing.

**Active-time tracking.** A `WorkSession` accrues `active_seconds` only while
the tab is visible and the annotator has interacted within the last 90 seconds
(Page Visibility API + idle threshold). Heartbeats are sent every 15 seconds; a
final keepalive is sent on page unload. `active_seconds`, `idle_seconds`, and
`open_seconds` are stored separately so wall-clock tab-open time is never
reported as labour.

### Project and document management

**Projects with roles.** Projects have three membership roles: `admin`,
`reviewer`, and `annotator`. Admins create projects, manage members, and load
references. Reviewers adjudicate submissions. Annotators see only their queue.

**My Queue dashboard.** A cross-project view shows every assignment an annotator
holds and its current status.

**Per-document assignment.** Admins assign individual documents to annotators.
Each assignment follows its own status workflow:
`assigned → in_progress → submitted → reviewed → returned`.
A reviewer can return an assignment; the annotator picks it back up as
in-progress.

**RIS import.** Bibliographic records can be imported from a `.ris` file via the
web UI or the `import_ris` management command. Records without a PDF are
accepted; the abstract is used as canonical text if no PDF is later attached.

**PDF upload and attachment.** PDFs can be uploaded at import time or attached
later with `attach_pdf`. SHA-256 fingerprints are stored at upload.

**ZIP bundle import.** A ZIP containing a `.ris` file, one or more PDFs, and
optional `.md` Markdown sidecars can be imported in a single web request.
Sidecars produced by `helper-scripts/marker_convert.py` are ingested
automatically.

**Hidden-slot configuration.** Admins can hide specific schema slots from their
project's annotation forms without touching the schema or code.

**Source-document rollup rules.** Admins configure `{slot, source, attribute,
operation}` rules in project settings. The rollup engine in
`apps/annotation/rollup.py` aggregates JSONB attribute values from nodes and
edges into the `SourceDocument` at form-display and export time.

**Time report and IRR export.** Project admins can download a CSV of
active/idle/open seconds per annotator, and a CSV of edge-level inter-rater
metrics.

### Text extraction and Markdown

**pdfplumber extraction (default).** Text is extracted from PDFs using pdfplumber
with `layout=True` for multi-column reading-order preservation. A `page_map` of
`{page, start_char, end_char}` entries is stored so the PDF viewer can scroll to
the page containing any character offset.

**Marker Markdown (optional).** An optional heavy dependency
(`pip install "loom[marker]"`) enables GPU-accelerated PDF-to-Markdown conversion
via Marker. The `helper-scripts/marker_convert.py` script runs on a separate
machine with or without an LLM endpoint for post-processing, producing `.md`
sidecars named after the source PDF. The `extract_markdown` management command
backfills or refreshes `canonical_markdown` for documents already in the
database. When Markdown is present, a third tab appears in the annotation pane
with full syntax rendering and span-selection support.

### Ontology support

**Local ontology index.** OBO/OWL ontologies are loaded into a local
`OntologyTerm` index with trigram (`pg_trgm`) GIN indexes on label and synonyms
for sub-100 ms prefix search. Sources are configured in `config/ontologies.yaml`.

**OntologyRelease and OntologySnapshot.** Each load of an ontology file produces
an immutable `OntologyRelease` content-addressed by the SHA-256 of the source
file and the scope root CURIEs. A project pins an `OntologySnapshot` (a manifest
of releases) so every export is reproducible against the exact ontology state
active when annotation was done.

**Term scoping.** Ontologies can be loaded scoped to a set of root CURIEs plus
descendants (MIREOT pattern), keeping the local index focused without fetching a
full OBO dump.

**Slot-level ontology routing.** `config/loom_ui.yaml` maps each slot to the
ontology prefix(es) or Wikidata live-search configuration appropriate for it.
The autocomplete widget respects these routes and never hardcodes ontology names
in JavaScript.

**Live Wikidata search.** Slots configured with `wikidata_live` perform a
two-step call (wbsearchentities → SPARQL filter against an optional root QID) so
annotators can pick taxa, ecosystems, and other Wikidata entities without
pre-loading a full dump. Terms picked this way are accumulated in a per-project
ad-hoc `OntologyRelease`.

**Free-text fallback and term suggestions.** Slots configured with
`allow_free_text: true` accept unmatched input as free text. Unmatched terms are
logged as `OntologyTermSuggestion` records with `pending` status for curator
review and upstream filing.

**Ad-hoc ontology registration.** Admins can register additional OBO/OWL sources
via the UI without editing `ontologies.yaml`.

**Queued ontology loads.** Large ontology loads run as background jobs tracked
via `OntologyLoadRequest` and `OntologyLoadItem`, keeping the web request
non-blocking. A `process_ontology_loads` management command drives the queue.

### Schema management

**Versioned schema store.** CAMO LinkML YAML files are loaded into a versioned
`SchemaVersion` model (SHA-256 fingerprinted). Only one schema is active at a
time; loading a new version does not drop the old one. Graphs and nodes pin their
schema version at creation.

**Schema update check.** `check_schema_updates` compares on-disk schema files in
`config/schema/` against the database and reports versions not yet loaded.

**UI config validation.** `check_ui_config` cross-references `loom_ui.yaml`
against the active schema and warns about slots referenced in the sidecar that
no longer exist in the schema.

Schemas shipped with this release: CAMO 0.4.0, 0.4.1, 0.4.2, 0.7.1, 0.7.2,
0.7.3, 0.7.4.

### Export and validation

**YAML export.** `export_graph` serializes a `CausalGraph` to a CAMO-compatible
YAML file. Provenance (schema version SHA-256, ontology snapshot SHA-256,
exporter version, output SHA-256, export timestamp) is embedded in every file.

**LinkML validation.** Validation against the pinned schema runs on every export
and on assignment submission. Validation messages are mapped back to the
offending field. Supports both legacy and current LinkML validator APIs and fails
closed when validation is unavailable.

**Rosetta Statements.** Natural-language edge summaries are rendered from the
`rosetta_template` annotation on `PredicateEnum` permissible values and included
in the export view.

**FCM weights.** Signed numeric weights (`sign × strength`) are derived from the
`fcm_sign` annotation on `PredicateEnum` and the `claim_strength` of each edge.
Both Rosetta and FCM rendering operate on the serialized dict, not Django models,
so they are equally available from the web UI and from management commands.

**Schema migration assistant.** `migrate_graph` generates a diff report between a
graph's pinned schema version and a target version, identifying slots that have
been renamed, dropped, or added.

### Audit and reproducibility

**Append-only audit log.** Every create, update, and delete on nodes, edges,
spans, and status transitions emits an `AuditEvent` with actor, timestamp,
action, target type/id, and a JSON diff. No direct ORM writes to graph objects
bypass this log.

**SHA-256 content addressing.** PDF uploads, schema versions, ontology releases,
ontology snapshots, and YAML exports are all content-addressed. Every exported
graph is self-describing: it carries the exact schema version SHA and ontology
snapshot SHA used to produce it.

### Authorization and security

**Assignment-owned graph writes.** Annotators can only mutate their own graphs.
Submitted and reviewed assignments are server-side read-only. Reviewer
adjudication is gated to users with the `reviewer` or `admin` role in the
project.

**Upload validation.** PDF, RIS, and bundle uploads have configurable
service-level size limits. PDF signatures and ZIP expansion, entry count,
encryption status, and compression ratios are checked before processing.

**Container security.** The Docker build uses separate build/runtime stages and a
non-root runtime user. The build context excludes environment files, uploaded
media, Git metadata, caches, and local build artefacts.

### LLM seam (disabled by default)

A pluggable `Proposer` interface in `apps/llm` defines the contract for
LLM-proposed draft nodes and edges. The default implementation is a no-op. The
seam is gated by `LLM_PROPOSALS_ENABLED = False` in settings. When enabled,
proposals land as `origin=llm_proposed` drafts that an annotator must explicitly
accept — no automated transition to `complete` or `gold` is possible.

### Management commands

| Command | Description |
|---|---|
| `create_project` | Create a project and set its admin |
| `import_ris` | Import a RIS file into a project |
| `attach_pdf` | Attach a PDF to an existing document |
| `extract_text` | (Re)extract canonical text from PDFs |
| `extract_markdown` | Backfill or refresh Markdown from PDFs or `.md` sidecars |
| `load_schema` | Load a CAMO LinkML YAML file and optionally activate it |
| `update_schema` | Load and activate a new schema file |
| `list_schemas` | List all loaded schema versions |
| `check_schema_updates` | Compare on-disk schema files to the database |
| `check_ui_config` | Validate `loom_ui.yaml` against the active schema |
| `load_ontology` | Load one or all configured ontologies |
| `process_ontology_loads` | Process queued per-project ontology load requests |
| `create_trgm_index` | Create `pg_trgm` GIN indexes for ontology search |
| `validate_graph` | Validate a graph against its pinned schema |
| `export_graph` | Export a graph to CAMO YAML |
| `migrate_graph` | Report schema migration diff for a graph |

### Stack

- Python ≥ 3.11, Django ≥ 5.1, PostgreSQL with `pg_trgm`
- `linkml-runtime` and `linkml` for schema introspection and validation
- `pdfplumber` for default text and Markdown extraction
- `pronto` for OBO/OWL ontology loading
- `rispy` for RIS bibliographic import
- `markdown` for server-side Markdown rendering in the annotation view
- `marker-pdf` as an optional heavy dependency for GPU-accelerated PDF
  conversion (`pip install "loom[marker]"`)
- Front end: Django templates, HTMX, Alpine.js, PDF.js — no SPA build step

### Helper scripts

`helper-scripts/marker_convert.py` — run on a GPU-equipped machine (or against
a local Ollama endpoint) to convert a directory of PDFs to Markdown. Supports
filtering by RIS file attachment tags, optional LLM post-processing, and
`--force` re-conversion. Output `.md` files can be bundled into a Loom ZIP
import or ingested individually with `extract_markdown`.

---

## [0.1.0] — Initial private development

- Initial private development version.
