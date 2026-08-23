# Administrator guide

This guide covers the tasks a Loom **staff/superuser account** and a
**project admin** perform outside the annotation workspace itself: loading
the schema and ontologies the whole instance runs on, tuning how a project's
annotation forms look, and — for projects that opt in — configuring the LLM
proposal seam. It complements [`operations.md`](operations.md) (deployment,
backups, health checks) and the [annotator guide](annotator-guide.md) (the
day-to-day annotation workflow).

Two permission tiers matter here:

- **Staff/superuser** — instance-wide actions: loading a schema or ontology,
  activating a schema, applying upstream updates. Gated by `is_staff` (schema
  and ontology uploads) or `is_superuser` (activation, updates).
- **Project admin** — a `ProjectMembership` with `role=admin` on a specific
  project: form-builder tuning, hidden slots, rollup rules, and the LLM
  pipeline are all scoped to one project and available to that project's
  admins, not just instance staff.

## Uploading and activating a schema

Schema versions are instance-wide; a project's `active_schema` field pins it
to one of them.

1. **Schemas → Upload** (`/schemas/upload/`, staff-only). Upload a `.yaml`/
   `.yml` LinkML file. It's parsed with `linkml_runtime.SchemaView` before
   being stored — a file that doesn't parse as LinkML is rejected with the
   parse error shown inline, and nothing is written. Files over 1024MB are
   rejected outright (`LOOM_MAX_SCHEMA_UPLOAD_MB`, configurable). Uploading
   the exact same content twice (matched by SHA-256) is a no-op with a
   message, not a duplicate row.
2. **Schemas → Activate** (`/schemas/<pk>/activate/`, superuser-only). Marks
   one `SchemaVersion` as `is_active=True`; Loom enforces there is at most one
   active schema at a time. A new project with no explicit `active_schema`
   picks up whatever is currently active
   (`apps/projects/management/commands/create_project.py`).
3. Existing `CausalGraph` rows are **not** retroactively repinned — a graph
   stays on the schema version it was created under
   (`CausalGraph.schema_version`), by design (see CLAUDE.md's audit/
   reproducibility principle). Activating a new schema only changes what
   *new* graphs get pinned to.

Equivalent from the command line (useful for scripted deploys):

```bash
python manage.py load_schema config/schema/camo-0.7.4.yaml --activate
python manage.py list_schemas
```

## Configuring the form builder

**Schemas → \[a schema\] → Form Builder** (`/schemas/<pk>/form-builder/`,
staff-only) is a drag-and-drop editor over `SchemaUIConfig` — a sidecar
config keyed to `(schema_version, project)`, so the same schema can render
differently across projects without editing the LinkML file itself (this is
exactly the `config/loom_ui.yaml` sidecar pattern CLAUDE.md describes, just
with a UI over it and a DB-backed per-project override layer on top).

From this page you can, per `CausalNode`/`CausalEdge` slot:

- Drag it between layers (sections) or the "unassigned" pool, and rename
  layers — this controls grouping and display order in the annotation form.
- Toggle **hidden** — removes the field from the form entirely for that
  project (see also the standalone hidden-slots page below).
- Override the **widget** (text, select, ontology autocomplete, etc.) —
  independent of what the schema's `range` would default to.
- Set **help text** shown under the field.
- **Map ontology sources** — which ontology prefix(es) (`ENVO`, `CHEBI`,
  `WD`, …) the autocomplete widget searches for that slot. This is the "map
  ontologies to slots" task: it's not a separate screen, it's a per-slot
  setting right here in the form builder.

Nothing is saved until you click **Save**. Config can also be exported/
imported as YAML (`schema-form-builder-export`/`-import`) to move a layout
between environments or check it into version control alongside the schema.

A narrower, project-only alternative for just hiding fields (no layer/widget/
ontology editing) is **Project settings → Hidden slots**
(`/projects/<pk>/settings/hidden-slots/`), scoped to a project admin rather
than instance staff.

## Loading and browsing ontologies

**Ontology → Manage** (`/ontology/manage/`, staff-only) lists every loaded
`OntologyRelease` with its term count and status.

- **Upload** (`/ontology/manage/upload/`): give it a name and a short prefix
  (max 10 chars, e.g. `ENVO`), then upload an `.obo`, `.owl`, `.yaml`, or
  `.yml` source file directly — this registers an ad hoc source and loads it
  synchronously in the same request. `.obo` files are checked for a
  `format-version:` header before parsing; files over 1024MB are rejected
  (`LOOM_MAX_ONTOLOGY_UPLOAD_MB`, configurable).
- **Reload** re-fetches a release from its original source URL (not
  applicable to ad hoc uploads, which have no stable URL) and reports the new
  term count.
- **Browse** (`/ontology/manage/<pk>/browse/`) and its search endpoint let
  you spot-check what actually loaded — label, definition, synonyms — before
  trusting it in production forms.
- **Delete** removes a release and every one of its terms.

Ontologies configured in `config/ontologies.yaml` (the preload list) can also
be loaded from the command line:

```bash
python manage.py load_ontology envo
python manage.py load_ontology --all
```

Per-project, a project admin can additionally request specific ontologies be
included in that project's snapshot from **Project settings** — matched
prefixes show up with their source and reasons (inferred from the active
schema's ontology routing), and an admin can register a one-off OBO/OWL URL
for a prefix nothing already covers. Project-level loading runs
asynchronously via `OntologyLoadRequest` rows drained by the
`process_ontology_loads --watch` worker (see `docker-compose.yml`'s
`ontology-worker` service) — the settings page polls
`/projects/<pk>/settings/ontology-status/` for progress.

## Configuring the LLM pipeline

The LLM proposal seam is **disabled by default** and configured **per
project**, not instance-wide — there is no global on/off switch. A project
admin manages it from **Project → LLM Config**
(`/projects/<pk>/settings/llm/`):

- **Enable LLM proposals for this project** — off by default. Turning it on
  requires the API key env var (below) to actually resolve on the server;
  saving fails validation otherwise, so a project can never end up "enabled"
  with no working key.
- **Model** — one of the three supported model IDs (`claude-haiku-4-5-...`,
  `claude-sonnet-5`, `claude-opus-4-8`).
- **API key environment variable name** — you type the *name* of a server
  environment variable (e.g. `ANTHROPIC_API_KEY_PROJECT_X`), never the key
  itself. The page checks live (as you type) whether a variable by that name
  is actually set on the server, showing a green check or a red warning — it
  only ever reports presence/absence, never the value. The key must already
  be set in the server's environment (e.g. added to `.env` and the container
  restarted) before you type its name here.
- **Trigger** — `manual` (an admin/annotator explicitly requests proposals)
  or `on_assignment` (proposals are generated automatically, in the
  background, the moment a document is assigned to an annotator).
- **Max proposals per document** and **max few-shot examples per prompt**.

**Few-shot examples** (**Project → LLM Config → Choose few-shot examples**,
`/projects/<pk>/settings/llm/few-shot/`): pick from this project's own
`complete`/`gold` edges — only human-approved annotations are eligible — to
show the model as worked examples before it drafts new proposals. Check the
edges to include, optionally leave yourself a label explaining why each one
is a good example, and save. Selection persists via `FewShotExample` rows;
unchecking an edge removes it as an example (it does not touch the edge
itself).

**Metrics** (**Project → LLM Config → View metrics**,
`/projects/<pk>/settings/llm/metrics/`): acceptance rate (with a colour-coded
bar), average edit distance between what the model proposed and what the
annotator ultimately accepted, average time-to-review, and a per-document
accepted/rejected/total breakdown — the numbers behind "is the LLM saving
time" for this project specifically.

Draft proposals — whether triggered manually or `on_assignment` — surface for
review at **Project → Review Proposals** (`/projects/<pk>/review-proposals/`),
covered from the annotator's side in the
[annotator guide](annotator-guide.md#reviewing-and-accepting-llm-proposals).
Nothing an LLM proposes ever lands as `complete` or `gold` without a human
explicitly accepting it there.

## Reviewing update notifications and applying updates

Loom can periodically check whether newer CAMO schema releases or ontology
sources are available upstream (`check_all_updates`), independent of any
specific project. When one is found, a dismissible banner appears for staff
users across the app (`apps/schemas/context_processors.py`).

From the banner or **Schemas** (`/schemas/`):

- **View diff** (`/schemas/updates/<pk>/diff/`, superuser-only) shows what
  changed — added/removed classes and slots for a schema update, or new
  terms for an ontology update.
- **Apply** (`/schemas/updates/<pk>/apply/`, superuser-only): schema updates
  apply synchronously with an "activate immediately" option; ontology
  updates apply on a background thread since a full reload can take a while,
  and you're told to check back rather than waiting on the request.
- **Dismiss** hides that banner for your session only — it doesn't cancel
  the update check or hide it from other staff.

Equivalent from the command line:

```bash
python manage.py check_all_updates
python manage.py check_schema_updates
python manage.py update_schema --to-version v0.7.4 --activate --yes
```
