# AGENTS.md

Guidance for working in the **Loom** repository. Read this before generating
code, schema, or migrations.

---

## What Loom is

Loom is a self-hosted Django web application for annotating scientific journal
articles with the **Causal Mosaic (CAMO)** schema. It is the human-in-the-loop
annotation workbench for EcoWeaver: an annotator opens a PDF, highlights the
text that expresses a causal claim, decomposes the entities into ELMO nodes
(entity + attribute + direction), and annotates the causal edge across CAMO's
four layers (claim strength, philosophical account, fifteen causal features,
evidential basis). Loom exports a LinkML-validated CAMO instance graph that
downstream EcoWeaver pipelines (ingestion, RAG, evidence gap maps) consume.

Work is organized by **project**. An admin creates a project, loads references
into it — PDF uploads and/or RIS bibliographic records that may carry no PDF —
and assigns documents to annotators. Loom tracks who is responsible for each
file and what they have done to it. A seam for LLM-proposed annotations and
their human review exists but is **disabled by default**.

Primary audience: **students annotating at speed** (e.g. Evidence Jam). Ease
and correctness of annotation is the product. Everything else is plumbing.

The name fits the EcoWeaver family — threads of evidence woven into a mosaic.

## The one defining constraint

**Loom is driven by the LinkML schema, not by hardcoded fields.** When CAMO
moves from v0.4 to v0.5 (e.g. a `biotic_interaction_type` slot, a
`HypothesisRecord` class, `hypothesis_tags` on `CausalEdge`), the annotation
forms, validation, and export must follow automatically — no model migration,
minimal code change. If you find yourself writing a Django model field or a
form widget that names a CAMO slot directly, stop: that belongs in the schema
engine, driven from `SchemaView`.

A useful side effect: because forms and exports can only emit field names the
*active schema* defines, Loom cannot reproduce the v0.3.1→v0.4 field-name /
enum drift that currently blocks the sample graph. The schema is the single
source of truth.

---

## Non-negotiable principles

1. **Schema-first / schema-driven.** Annotation structure comes from the
   active LinkML schema via `linkml-runtime` `SchemaView`. Forms, validation,
   and serialization are derived, never duplicated.

2. **Config over code.** UI hints (which ontology a slot draws from, layer
   grouping, collapsed-by-default features, widget overrides) live in
   `config/loom_ui.yaml`, a sidecar that augments the schema *without editing
   it*. Ontology sources live in `config/ontologies.yaml`. Search terms,
   routing, and parameters are declarative, not hardcoded in Python.

3. **JSONB storage, validated at the edges.** Node and edge payloads are stored
   as Postgres JSONB. A thin relational layer promotes only what we query or
   index (ids, labels, predicate, annotator, status, schema_version, span
   offsets). Validation against the active schema happens on export and
   optionally on save — never trust the JSONB blindly, never widen the
   relational schema to chase CAMO slots.

4. **Audit everything.** Append-only `AuditEvent` log for every create/update/
   delete on nodes, edges, spans, and status transitions. SHA-256 fingerprint
   uploaded PDFs and exported graphs. Pin the schema version *and* the ontology
   snapshot version per project so any export is reproducible.

5. **Humans propose and approve; automation never writes to the graph
   silently.** Loom is a human survey instrument. The LLM pre-annotation seam
   (`apps/llm`) exists but is **disabled by default** (`LLM_PROPOSALS_ENABLED =
   False`); when enabled it only populates *drafts* an annotator must accept —
   it never lands a `complete` or `gold` edge on its own. Deterministic
   rendering (Rosetta Statements, FCM weights) is exempt: it is computed output,
   not a causal claim.

6. **Scope discipline.** Loom annotates the **causal (universal) graph only** —
   generalised claims extracted from literature. Observational particulars
   (PREDICTS/TRY records) and sibling graphs (GloBI) live elsewhere and are not
   ingested here as causal edges. Don't grow Loom into the observational store.

7. **Minimal-footprint changes.** Prefer edits that work within existing
   structures over new insertions. Precise names over buzzwords. Small, legible
   diffs.

---

## Architecture at a glance

- **Stack:** Django + Postgres (JSONB + `pg_trgm`). Front end is Django
  templates + HTMX + Alpine.js + PDF.js — no SPA build pipeline. The only
  substantial bespoke JS is the PDF viewer / span-selection component and the
  ontology autocomplete.
- **Projects** (`apps/projects`): projects, membership/roles, and per-document
  **assignment** of work to annotators with status tracking.
- **Schema engine** (`apps/schemas`): loads CAMO LinkML files as versioned
  records; `SchemaView` introspection → a *form spec* → rendered forms and an
  export serializer.
- **Documents** (`apps/documents`): PDF upload **and RIS import** (references
  with or without a PDF), server-side canonical-text extraction with character
  offsets, span storage.
- **Annotation** (`apps/annotation`): graphs, nodes, edges, the annotation UI,
  and timed work sessions (active time-on-task per document).
- **Ontology** (`apps/ontology`): local term index (label/synonym/definition
  search), OLS fallback.
- **Export** (`apps/export`): LinkML validation, YAML serialization, Rosetta /
  FCM rendering, schema-migration assistant.
- **LLM seam** (`apps/llm`): a pluggable `Proposer` interface that emits *draft*
  nodes/edges for human review. Ships with a no-op proposer and is gated off by
  `LLM_PROPOSALS_ENABLED = False`.
- **Audit** (`apps/audit`) and **Accounts** (`apps/accounts`): roles are
  `annotator`, `reviewer` (adjudicator), `admin`, set per project membership.

## Why these choices (so they don't get "fixed")

- **HTMX over React.** Self-hosting and long-term maintainability for a research
  group beat SPA ergonomics. The existing React author-validation tool is a
  *different* instrument (expert elicitation); Loom is the annotation bench and
  intentionally has no node build step for its core.
- **JSONB over per-slot columns.** This is what buys schema-update resilience.
  Do not normalize CAMO slots into columns.
- **Canonical-text offsets over PDF-coordinate spans.** Robust, stable, and
  aligned with `TextSpan.start_char/end_char` in the schema. PDF.js is for
  display; offsets come from the extracted canonical text.
- **Local ontology index over live API-only.** Nibi and other self-hosted
  deployments may be network-restricted. Preload; treat OLS as a convenience.

---

## Repo layout

```
loom/
  manage.py
  pyproject.toml              # deps: django, psycopg, linkml-runtime, linkml,
                              #       pronto, PyMuPDF (or pdfplumber), pyyaml,
                              #       ruff, black, pytest, pytest-django
  loom/                       # project config (settings/, urls.py, asgi/wsgi)
  apps/
    projects/                 # Project, ProjectMembership, Assignment (per-file work tracking)
    schemas/                  # SchemaVersion model, SchemaView wrapper, form-spec builder
    documents/                # Document (PDF and/or RIS), RIS import, text extraction, TextSpan
    annotation/               # CausalGraph, Node, Edge, annotation views/templates
    ontology/                 # OntologyTerm, loaders, search
    export/                   # serializer, linkml validation, renderers, migration assistant
    llm/                      # Proposer seam (no-op default; disabled by flag)
    audit/                    # AuditEvent
    accounts/                 # users, roles
  config/
    schema/                   # canonical CAMO LinkML files, e.g. camo-0.4.0.yaml
    loom_ui.yaml              # UI hints sidecar (ontology routing, layer groups, widgets)
    ontologies.yaml           # ontology sources + which to preload
  static/js/                  # pdf-viewer.js, span-select.js, ontology-autocomplete.js
  templates/
  tests/
```

## Commands

```bash
# Environment
make dev                                  # or: docker compose up

# Projects & references
python manage.py create_project "Grassland Map" --admin <user>
python manage.py import_ris <project_id> refs.ris        # bibliographic records, PDF optional
python manage.py attach_pdf <document_id> paper.pdf

# Schema
python manage.py load_schema config/schema/camo-0.4.0.yaml --activate
python manage.py list_schemas

# Ontologies (loaded from config/ontologies.yaml sources)
python manage.py load_ontology envo
python manage.py load_ontology --all

# Validate / export
python manage.py validate_graph <graph_id>
python manage.py export_graph <graph_id> --format yaml --validate -o out.yaml

# Schema migration assistant (move an existing graph to a newer schema)
python manage.py migrate_graph <graph_id> --to-version 0.5.0 --report

# Quality
ruff check . && black . && pytest
```

---

## Conventions

- **Forms come from the schema engine.** To add a field to the annotation UI,
  add the slot to the CAMO schema and (if needed) a hint to `loom_ui.yaml`.
  Do not add it to a Django form class.
- **Validation is LinkML's job.** Surface LinkML validation messages mapped to
  the offending field; don't reimplement constraint checks in Python.
- **Every graph write goes through the annotation service layer**, which emits
  an `AuditEvent`. No direct ORM writes to nodes/edges from views.
- **Status lifecycle for edges:** `draft → complete → (reviewed) → gold`.
  Adjudication produces `gold`. Nothing but a human transitions to `complete`
  or `gold`.
- **Spans are first-class.** A node or edge created from a highlight carries its
  `source_spans` and `original_sentence` automatically. Never discard offsets.
- **Reproducibility fields are mandatory on export:** active `schema_version`,
  ontology snapshot id, exporter version, SHA-256 of the output.
- **Time is active engagement, not wall clock.** A `WorkSession` accrues only
  while the tab is visible and the annotator is active (heartbeat + idle pause).
  Store `active_seconds` alongside `open_seconds`/`idle_seconds`; never report
  tab-open time as labour. This is the human baseline for the LLM-savings
  question, so the measure must be defensible.

## What Loom is NOT

- Not the observational data graph, and not a GloBI ingestion path.
- Not an automated extractor that writes causal edges. The LLM seam is off by
  default and, when on, only proposes drafts for human review.
- Not the expert-elicitation / construct-validity instrument (that's the
  separate React author-validation tool). Loom is for annotators; ecologists
  judge validity elsewhere.

## Working with AI on this repo

- Before changing annotation forms or export, re-read "The one defining
  constraint." If a change names a CAMO slot in Python, it's probably wrong.
- Don't introduce a JS build step into the core. PDF/span/ontology JS stays as
  plain modules served from `static/js/`.
- Keep diffs minimal and within existing structures. Prefer extending the
  sidecar config or the schema over adding code paths.
- Ask before: changing the storage model (JSONB → columns), adding a new
  ontology source format, or altering the span offset model. These are
  load-bearing decisions documented above.
