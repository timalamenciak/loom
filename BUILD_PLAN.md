# BUILD_PLAN.md — Loom

A self-hosted Django platform for annotating journal articles with the Causal
Mosaic (CAMO) schema. Work is organized by **project**: an admin creates a
project, loads references (PDFs and/or RIS records with no PDF), and assigns
documents to annotators. Built schema-driven so it tracks CAMO as it evolves,
with PDF display, ontology-backed term entry, per-document **time-on-task**
tracking, and one-click export to validated CAMO YAML. A seam for LLM-proposed
annotation exists but ships **disabled**.

---

## 1. Goal and success criteria

**Goal.** An admin sets up a project and assigns articles; a student opens an
assigned document, builds a CAMO causal graph from the text, and exports a graph
that validates against the active CAMO LinkML schema — with the whole UI
generated from that schema so a v0.5 bump needs no rewrite. Active time-on-task
is captured per document so the labour cost of human annotation can be measured.

**Done looks like (MVP acceptance):**

- Admin creates a project, imports a RIS file (records appear with no PDF),
  uploads/attaches PDFs to some records, and assigns documents to an annotator.
- The annotator sees **only their assigned documents** ("my queue"), annotates
  ones that have text (a PDF, or an abstract from the RIS record), and submits.
- Admin sees a per-file view: who is assigned, current status, last activity,
  and **active time spent** — who did what on each file, and for how long.
- A student annotates the buckthorn / grassland-restoration paper end to end:
  8 nodes, 8 edges, all four layers, spans grounded to character offsets.
- Export produces YAML that passes `linkml-validate` against `camo-0.4.0.yaml`
  and round-trips into the structure of the existing sample data.
- Loading `camo-0.5.0.yaml` and re-activating it changes the forms with **zero
  code changes** and **no database migration**.
- Ontology fields autocomplete against a locally loaded ENVO/NCBITaxon/PATO/
  GO/CHEBI index while offline.
- `LLM_PROPOSALS_ENABLED = False`: no suggestion UI appears; the seam is inert.

## 2. Constraints and assumptions (stated, not asked)

- **Postgres is required** (JSONB + `pg_trgm`). SQLite is not a target.
- **Project-scoped.** Documents, assignments, graphs, work sessions, the active
  schema, and the ontology snapshot all belong to a project.
- **A document is a reference, not a file.** It may have a PDF, or be a
  bibliographic record only (from RIS). PDFs can be attached later or never.
- **CAMO schema is the source of truth.** The repo ships the canonical LinkML
  file(s) under `config/schema/`. Loom never hardcodes CAMO slots.
- **Annotation captures the causal/universal graph only.** Observational data
  and GloBI are out of scope (sibling graphs, handled elsewhere).
- **Char offsets index a server-extracted canonical text.** Matches
  `TextSpan.start_char/end_char`; for PDF-less records the RIS abstract (if
  present) is the canonical text.
- **Time means active engagement, not tab-open wall clock.** See §9.
- **Self-hosted, possibly network-restricted** (Nibi). Ontologies preload
  locally; external APIs are optional conveniences.
- **LLM proposals are off by default.** The data model and seam are built now;
  no proposer is wired up for MVP.

## 3. Tech stack and rationale

| Layer | Choice | Why |
|---|---|---|
| Web framework | Django | Mature, batteries-included, easy self-host. |
| DB | Postgres (JSONB, `pg_trgm`) | JSONB = schema-update resilience; trigram = fuzzy ontology search. |
| Schema engine | `linkml-runtime` (`SchemaView`), `linkml` validator | Introspect CAMO at runtime; validate exports. |
| Front end | Django templates + HTMX + Alpine.js | No SPA build step; maintainable for a research group. |
| PDF display | PDF.js | Standard, in-browser, text layer for overlays. |
| PDF text extract | PyMuPDF *or* pdfplumber | Canonical text + char/word boxes. **License note:** PyMuPDF is AGPL; pdfplumber (MIT, on pdfminer.six) is the permissive fallback. Decide before Phase 3. |
| RIS parsing | `rispy` | MIT; parse RIS reference exports into records. |
| Ontology parse | `pronto` (OBO/OWL) | Lightweight loader into the local index. |
| Time tracking | Page Visibility API + heartbeat (vanilla JS) | Active-time accrual with idle pause; no extra dependency. |
| Auth | Django auth + per-project roles | Low-friction student onboarding. |

The only substantial bespoke JS: the PDF viewer + span-selection module, the
ontology autocomplete, and the session-timer heartbeat. Everything else is
server-rendered with HTMX swaps.

## 4. Data model

Promote only what we query; keep CAMO payloads in JSONB. Project, assignment,
and session models are stable Loom concerns (not CAMO slots), so they use real
columns.

**Project & people**

- **Project** — `name`, `description`, `created_by`, `active_schema` (FK),
  `ontology_snapshot` (FK). The unit of work, access, and configuration.
- **ProjectMembership** — `project` (FK), `user` (FK), `role`
  (`admin | reviewer | annotator`). A user's capabilities are per project.
- **Assignment** — `project` (FK), `document` (FK), `annotator` (FK user),
  `assigned_by` (FK), `assigned_at`, `status`
  (`assigned | in_progress | submitted | reviewed | returned`), `graph`
  (FK CausalGraph, nullable until work starts). One per (document, annotator);
  multiple per document supports multi-annotator / IRR. **The record of who is
  responsible for each file.**

**References & text**

- **Document** — `project` (FK), `source` (`pdf_upload | ris_import | manual`),
  `pdf_file` (**nullable**), `sha256` (of the PDF, when present),
  `canonical_text` (**nullable**; from PDF extraction, else the RIS abstract),
  `page_map` (offset→page/bbox, when a PDF exists), bibliographic fields
  mirrored from `SourceDocument` (`title`, `authors[]`, `year`, `doi`,
  `journal`, `abstract`), and `ris_raw` (JSONB; the original RIS entry preserved
  verbatim). Dedup within a project by DOI, then title.
- **TextSpan** — `document` (FK), `start_char`, `end_char`, `text`, optional
  `node`/`edge` FK. Promoted so highlights render fast and spans are queryable.

**Annotation (CAMO payloads as JSONB)**

- **SchemaVersion** — `version`, `linkml_yaml` (file ref), `sha256`,
  `is_active`, `loaded_at`. One active per project.
- **CausalGraph** — `document` (FK), `annotator` (FK), `schema_version` (FK),
  `provenance` JSONB (`GraphProvenance`), `status`.
- **Node** — `graph` (FK), `node_id`, `name`, `category` (promoted), `data`
  JSONB (full `CausalNode`), `origin` (`human | llm_proposed`, default
  `human`), `schema_version`.
- **Edge** — `graph` (FK), `edge_id`, `subject`/`object` (FK Node), `predicate`
  & `claim_strength` (promoted), `status`
  (`draft | complete | reviewed | gold`), `origin` (`human | llm_proposed`),
  `data` JSONB (full `CausalEdge`).

**Time, ontology & audit**

- **WorkSession** — `assignment` (FK), `annotator` (FK), `started_at`,
  `ended_at`, `active_seconds` (headline), `idle_seconds`, `open_seconds`
  (wall clock first→last heartbeat), `source` (`auto | manual`). Sessions sum to
  per-document and per-project time. See §9.
- **OntologyTerm** — `prefix`, `curie`, `label`, `synonyms[]`, `definition`,
  `obsolete`, `snapshot` (FK). Indexes: `pg_trgm` on label/synonyms, btree on
  curie/prefix.
- **OntologySnapshot** — `name`, `built_at`, source versions; pinned per project.
- **AuditEvent** — `actor`, `ts`, `action`, `target_type`, `target_id`,
  `diff` JSONB. Append-only; exportable as JSONL. Drives the per-file activity
  view and the within-document time distribution (§9).

Status lifecycles: assignments `assigned → in_progress → submitted → reviewed`
(or `returned`); edges `draft → complete → reviewed → gold`. Only humans advance
edges to `complete`/`gold`; `llm_proposed` origin is allowed only at `draft`.

## 5. Schema-driven form engine (the core)

`SchemaView(active_schema)` → a **form spec** (plain dict the template renderer
consumes), built by walking class slots and mapping each slot's `range` to a
widget:

- **enum range** → `select`/radio. Render permissible-value `description`s as
  option help, and surface `annotations` like `linguistic_cues` / `exemplars`
  (already in the schema for `PhilosophicalAccountEnum`, `ClaimStrengthEnum`) as
  inline guidance. This turns the schema's own prose into an in-context
  annotation guide.
- **inlined class range** (`DirectionAnnotation`, `MediationAnnotation`,
  `ModerationAnnotation`, `StrengthAnnotation`, `ContextAnnotation`,
  `EvidentialBasis`, `TemporalExtent`, `StudySite`) → nested fieldset, rendered
  recursively by the same engine.
- **`range: CausalNode`** (edge `subject`/`object`) → node picker over nodes in
  the current graph (with "create node from selection" inline).
- **`uriorcurie` entity slots** (`entity_term`, `variable_attribute`,
  `process_context`, `ecosystem_context`, `conditioned_by`, `part_qualifiers`)
  → ontology autocomplete, routed by `loom_ui.yaml` (e.g. `entity_term` for taxa
  prefers NCBITaxon; `variable_attribute` prefers PATO; contexts prefer
  ENVO/GO). Routing comes from the slot descriptions in CAMO, encoded once in
  the sidecar.
- **string / integer / float / boolean** → text / number / checkbox; honor
  `minimum_value` / `maximum_value` and `ifabsent` defaults (many features
  default to `not_addressed`, which keeps the form short).
- **`multivalued: true`** → repeatable group / multiselect.

`loom_ui.yaml` (sidecar, never edits the schema) carries layer grouping (Layer
1–4 sections), which features collapse by default, ontology routing per slot,
and widget overrides. When CAMO changes, regenerate forms; only touch the
sidecar if a *new* slot needs a non-default widget or ontology route.

**Validation.** On save (optional) and export (required), run the LinkML
validator and map messages back to fields. No hand-rolled constraint logic.

**Migration assistant** (`migrate_graph`): diff two SchemaVersions (added /
removed / renamed slots, changed enum values), report affected instances, offer
guided remapping. The durable fix for the v0.3.1→v0.4 drift in the sample graph.

## 6. References: RIS import + PDF + spans

- **RIS import.** Parse with `rispy` into `Document` records; map RIS tags
  (`TI`/`T1`, `AU`, `PY`/`Y1`, `DO`, `AB`, `JO`/`JF`/`T2`) to bibliographic
  fields; keep the raw entry in `ris_raw`; dedup by DOI then title. Records
  arrive with `source = ris_import` and **no PDF**.
- **PDF attach/upload.** A PDF can be uploaded standalone or attached to an
  existing RIS record. On attach: extract canonical text deterministically;
  store it plus `page_map` and PDF `sha256`.
- **Canonical text.** Offsets index canonical text. For a PDF, that's the
  extraction; for a PDF-less record with an abstract, the abstract is the
  canonical text (abstract-level annotation). A record with neither sits in a
  "needs PDF" state and isn't yet annotatable.
- **Display & selection.** PDF.js renders pages; the text layer enables
  highlight overlays positioned via `page_map`. A parallel selectable
  canonical-text pane is the primary selection surface so offsets are always
  exact. Selecting text yields `start_char`/`end_char` and pre-fills
  `source_spans` + `original_sentence`. Highlights persist and jump to their
  annotation on click.

## 7. Ontology service

- **Load** OBO/OWL via `pronto` into `OntologyTerm` under an `OntologySnapshot`;
  preload the set CAMO uses: ENVO, NCBITaxon, PATO, CHEBI, GO, BFO, RO, ECO
  (SEPIO/OBI as needed). Sources declared in `config/ontologies.yaml`.
- **Search:** trigram fuzzy match on label/synonyms + exact curie lookup;
  return `label — curie — short definition`. Recent/favourite terms per
  annotator speed repeat entry.
- **Fallback:** optional OLS4 lookup when a term isn't local; never required.
- **Reproducibility:** the project pins an `OntologySnapshot`; exports record
  which snapshot resolved each term.

## 8. Annotation UX (the priority)

Designed around *decomposition before solving* — give a scaffold, don't demand
a single exhaustive pass:

- **My queue.** An annotator's landing page is the list of documents assigned to
  them, with status; they cannot see unassigned or others' work. Opening a
  document moves the assignment to `in_progress` and starts a `WorkSession`.
- **Span-first flow.** Highlight → "create node from selection" or "create
  edge." The decomposed node form (entity_type + entity_term + attribute +
  direction) is short and ontology-assisted; the composed `name` auto-builds.
- **Progressive layers.** Layer 1 (claim strength + predicate) and the two node
  endpoints come first. Layers 2–4 are collapsible, defaulting to the schema's
  `not_addressed` values, so a usable edge is a few fields and depth is opt-in.
- **Inline guidance from the schema.** Tooltips pull enum descriptions and
  `linguistic_cues`/`exemplars` directly, so the annotation guide lives where
  the decision is made.
- **Session timer.** A small, always-visible readout shows active time on the
  current document, with Pause/Resume. Time accrues only while the tab is
  visible and the RA is active (§9).
- **Graph view.** A live diagram of nodes/edges so students see the mosaic
  forming and catch dangling nodes.
- **Submit.** "Submit" closes the open session and moves the assignment to
  `submitted` for review.
- **Admin/reviewer dashboard.** Per project: each document's assignee, status,
  last activity, and total active time.
- **Speed.** Autosave drafts, keyboard shortcuts, friendly per-field validation,
  "duplicate last edge scaffold."

## 9. Time-on-task tracking

The measurement instrument for the project's core efficiency question: *how much
labour does LLM-assisted annotation save?* Answering that needs a defensible
human baseline first.

**What is measured.** *Active* time-on-task per (annotator, document) — not
tab-open wall clock. Leaving a tab open overcounts; the headline number is
active engagement.

**Mechanism.**

- A `WorkSession` opens when a document is opened. The client sends heartbeats
  (~15 s) while the tab is visible (Page Visibility API) **and** the annotator
  has been active within an idle threshold (default 90 s, reset by
  key/mouse/scroll/text-selection).
- Accrual pauses on tab blur/hide and on idle; resumes on return/activity.
- A manual **Pause/Resume** control gives the RA agency and a transparent
  override for legitimate breaks.
- Stored per session: `active_seconds` (headline), `open_seconds` (wall clock),
  `idle_seconds`. The active/open ratio is a built-in quality check on the
  measurement. Multiple sessions per document sum (annotation across sittings).

**Free within-document detail.** The `AuditEvent` log already timestamps every
node/edge/span action, so the *distribution* of time inside a document (reading
vs. node creation vs. which edge layers consume effort) can be reconstructed
post-hoc with no extra instrumentation — useful for asking *which parts* LLM
pre-annotation actually saves, not just the total.

**Honest caveats (so the numbers are interpretable).**

- Active-time is a proxy for effort, not a measure of cognitive load or quality.
- Learning curve: the RA speeds up across documents; treat document order as a
  covariate or counterbalance it.
- Document heterogeneity: papers differ in length and claim density; compare
  matched documents or stratify.
- A single RA gives a within-subject baseline, not a population estimate.

**The payoff.** With the same RA annotating *matched documents* under two
conditions — unaided vs. LLM-proposed drafts (the Phase 8 seam) — in
counterbalanced order, the timer yields a paired, within-subject comparison of
time-on-task. Because "time saved" is only meaningful *at equal quality*, pair
the timing with the gold/IRR machinery (§11): the claim becomes **time at
equivalent annotation quality**, which is the honest form of the efficiency
result.

## 10. Export, validation, rendering

- **Export** a `CausalGraph` to YAML matching the active schema; run
  `linkml-validate`; refuse (or warn) on failure. Output mirrors the existing
  sample-data shape so EcoWeaver pipelines ingest it unchanged. Project-level
  export bundles all gold (or selected) graphs.
- **Rendering (computed, not annotated):** Rosetta Statements from predicate
  `rosetta_template` + `certainty_grade` verb modifiers; FCM weights from
  predicate sign + `claim_strength` + strength annotation. Deterministic,
  overridable by expert elicitation.
- **Provenance on every export:** schema version, ontology snapshot, exporter
  version, output SHA-256 — written into `GraphProvenance`.

## 11. Multi-annotator, gold, IRR (later, but modeled now)

The model already supports multiple assignments and graphs per document.
Deferred until after MVP:

- **Reviewer/adjudication view:** compare annotators on the same document,
  resolve to a `gold` graph.
- **IRR export:** per-layer agreement (claim_strength, philosophical account,
  certainty grade) for the planned reliability study.
- **Gold set export:** curated graphs that seed Evidence Jam and validation.
- **Time-on-task report:** per-document and per-condition active time as CSV,
  for the labour analysis (§9).

## 12. LLM proposal seam (disabled by default)

Built now so the data model is right; **not wired up for MVP**.

- **Flag.** `LLM_PROPOSALS_ENABLED = False` hides all suggestion UI and disables
  the endpoints. Nothing in the MVP path touches it.
- **Interface.** `apps/llm` defines `Proposer.propose(document, schema_view) ->
  list[ProposedNode | ProposedEdge]`. Default `NoOpProposer` returns nothing.
- **Origin & status.** Proposals are written with `origin = llm_proposed` and
  edge `status = draft`. An annotator must accept (optionally edit) a draft;
  acceptance is a logged human action that may advance status. Proposals never
  auto-promote to `complete`/`gold`.
- **Human-in-the-loop UI (when enabled later).** A "Suggestions" panel beside
  the annotation surface with accept / edit / reject per item, each grounded to
  its source span like any human annotation. The session timer keeps running, so
  assisted time is captured the same way as unaided time.
- **Why a seam, not an integration, now.** Keeps Loom a clean human instrument
  for the hackathon while leaving an unambiguous insertion point — and a
  matching timing baseline — for the upstream LLM-extraction / LLM-as-judge
  steps when they're ready.

## 13. Phased roadmap

Each phase ends shippable. MVP = Phases 0–6.

- **Phase 0 — Scaffold.** Django, Postgres, Docker compose, Django auth, CI
  (`ruff`/`black`/`pytest`), `config/` skeleton.
  *Accept:* app boots; a superuser logs in.

- **Phase 1 — Projects, references, assignment.** Project + ProjectMembership
  (roles), Document as PDF-or-RIS reference, RIS import, PDF upload/attach,
  Assignment + statuses, annotator "my queue", admin per-file dashboard.
  *Accept:* admin creates a project, imports a 50-record RIS, attaches a few
  PDFs, assigns 10 documents to an annotator who sees exactly those in their
  queue; admin sees status per file.

- **Phase 2 — Schema engine + storage.** `SchemaVersion` load/activate;
  `SchemaView` wrapper; form-spec builder; JSONB Node/Edge/Graph; `loom_ui.yaml`.
  Scaffold the LLM seam: `origin` fields, `LLM_PROPOSALS_ENABLED` flag,
  `NoOpProposer`. Ship `camo-0.4.0.yaml`.
  *Accept:* a node/edge is created via generated forms and stored as JSONB;
  swapping a stub `camo-0.5.0.yaml` changes the form with no code/DB change.

- **Phase 3 — PDF + spans.** Canonical-text extraction, `page_map`, PDF.js
  viewer, span selection → offsets, RIS-abstract fallback text. (Resolve PyMuPDF
  vs pdfplumber.)
  *Accept:* highlight a sentence; a span with correct `start_char/end_char`
  persists and renders as a clickable highlight; an abstract-only record is
  annotatable.

- **Phase 4 — Ontology service.** Loaders, snapshot, trigram search, autocomplete
  widget; preload ENVO/NCBITaxon/PATO/GO/CHEBI.
  *Accept:* typing "buckthorn" / "canopy" / "abundance" returns correct curies
  offline; selections write to the right slots.

- **Phase 5 — Annotation UX + session timer.** Queue-aware flow, span-first
  creation, progressive layers, inline schema guidance, graph view, autosave,
  submit, and active-time `WorkSession` capture (heartbeat + idle pause).
  *Accept:* the buckthorn paper is annotated end to end comfortably; submitting
  updates the assignment status; active time is recorded for the session.
  *Note:* timing is on from the first real annotation — un-timed sessions can't
  be recovered, which is why it lands in the MVP.

- **Phase 6 — Export + validation + rendering.** YAML export, `linkml-validate`,
  Rosetta/FCM rendering, provenance + SHA-256. **MVP complete.**
  *Accept:* exported graph validates and matches sample-data structure.

- **Phase 7 — Multi-annotator + gold + IRR + migration assistant.** Reviewer
  view, adjudication to `gold`, IRR export, per-document time-on-task CSV,
  `migrate_graph` version-diff/remap.

- **Phase 8 — Enable LLM seam (optional, post-MVP).** Implement a real
  `Proposer`, build the Suggestions accept/edit/reject UI, run the
  counterbalanced unaided-vs-assisted timing study (§9). No change to the
  human-only guarantees.

- **Phase 9 — Hardening + deploy.** Backups, rate limits, OCR for scanned PDFs
  (optional), Evidence Jam runbook for Nibi, cohort-size load test.

## 14. Deployment (self-hosted)

- Docker compose: web (gunicorn/uvicorn), Postgres, static via WhiteNoise or
  nginx. Single `.env`. `make deploy` runs migrations, loads the active schema,
  builds the ontology snapshot.
- Backups: nightly `pg_dump` + media; restore documented.
- Nibi: bundle ontology dumps so first boot needs no network; document running
  on the cluster's web-accessible node for the 48-hour event.

## 15. Open decisions (deferred, not blocking)

- **PyMuPDF vs pdfplumber** — licensing vs. richer geometry. Decide at Phase 3.
- **Idle threshold & heartbeat interval** — defaults 90 s / 15 s; tune with the
  RA so genuine breaks aren't counted but normal reading pauses are.
- **OCR** — only if scanned PDFs enter the corpus (Phase 9).
- **Auth model for students** — invite links vs. institutional SSO; per
  deployment.
- **LLM proposer** — which upstream step feeds it, and at what granularity
  (document vs. paragraph). Out of scope until Phase 8; flag stays `False`.
