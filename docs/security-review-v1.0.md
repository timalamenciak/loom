# Security review — v1.0.0 release hardening

Targeted review of the views added in v0.4–v0.9 (`apps/schemas/views.py`,
`apps/ontology/views.py`, `apps/llm/views.py`) plus the file-upload and
XSS-relevant surfaces those views touch. Findings and fixes below; regression
tests for every fix live in `tests/test_security_review.py`.

## File upload validation

**Checked:** every upload endpoint (`schema-upload`, `ontology-manage-upload`,
plus the pre-existing PDF/RIS/ZIP endpoints in `apps/projects`) for extension
allowlisting, a size cap, and content validation independent of the
extension/filename.

**Findings and fixes:**

- `SchemaUploadView` (`apps/schemas/views.py`) had no extension check and no
  size limit — `upload.read()` loaded the entire file into memory regardless
  of size. **Fixed:** added a `.yaml`/`.yml` extension allowlist and a
  `settings.MAX_SCHEMA_UPLOAD_BYTES` size check (new setting,
  `LOOM_MAX_SCHEMA_UPLOAD_MB`, default 1024MB), both checked before the file
  is read. Content validation was already present and correct: the upload is
  rejected unless it parses as a LinkML `SchemaView` — this is the "YAML must
  parse" magic-byte-equivalent check.
- `OntologyUploadView` (`apps/ontology/views.py`) already had an extension
  allowlist (`.obo .owl .yaml .yml`) but no size limit, and no content check
  independent of the parser. **Fixed:** added a
  `settings.MAX_ONTOLOGY_UPLOAD_BYTES` size check (new setting,
  `LOOM_MAX_ONTOLOGY_UPLOAD_MB`, default 1024MB) and an explicit `.obo`
  magic-byte check (`format-version:` must appear in the first 2KB) so a
  mislabeled non-OBO file is rejected before it reaches `pronto`, matching
  the same fail-fast pattern `validate_pdf_upload` already uses for `%PDF-`.
- Pre-existing PDF/RIS/ZIP upload paths
  (`apps/projects/upload_validation.py`) already had size limits and, for
  PDF, a `%PDF-` magic-byte check — reviewed, no changes needed.

**New settings** (both default to 1024MB, matching the "reject > 1024MB"
requirement): `LOOM_MAX_SCHEMA_UPLOAD_MB`, `LOOM_MAX_ONTOLOGY_UPLOAD_MB`.
Added to `loom/settings/base.py` and `.env.example`.

## Authentication + authorization

**Checked:** every view in `apps/schemas/views.py`, `apps/ontology/views.py`,
`apps/llm/views.py`, and `apps/annotation/views.py` for `LoginRequiredMixin`
plus the appropriate permission check.

**Findings:** none — every staff-only view already gates on
`UserPassesTestMixin`/`test_func` (`is_staff`) or an explicit
`_require_superuser` call; every annotation-editing view already goes through
`require_annotation_assignment` / `require_editable_assignment`
(`apps/annotation/policies.py`), which checks both `ProjectMembership` *and*
an `Assignment` for the specific document — stricter than plain project
membership. Reviewer-tier views (`ReviewDocumentView`, `ReturnAssignmentView`,
`AdjudicateEdgeView`) correctly gate on `_require_reviewer_or_admin`, not just
any project member. `HeartbeatView` scopes its `WorkSession` lookup to
`annotator=request.user`, so one annotator cannot heartbeat another's session.

The LLM review queue (`apps/llm/views.py::_require_review_access`) already
checks the requesting user is a superuser, a project admin, **or** has an
`Assignment` in the project — i.e. is assigned to the project, as required.
No change needed.

## XSS

**Checked:** every `mark_safe()` / `|safe` call site, and every `<script>`
block in a template that embeds a Django template variable, for whether the
embedded value is genuinely safe or needs escaping/sanitization.

**Findings and fixes:**

- No `{{ value|safe }}` usage exists anywhere in `templates/`.
- `mark_safe()` is used in three places. Two
  (`apps/annotation/views.py`'s `highlighted_text`,
  `apps/documents/views.py`'s `highlighted_text`) call
  `render_highlighted_text()`, which HTML-escapes the document text and every
  interpolated attribute (`_html.escape(...)`) *before* building the marked-up
  string — correct, no change needed.
- **Found and fixed a real stored-XSS vector**: `apps/annotation/views.py`'s
  `markdown_html` ran `document.canonical_markdown` through `python-markdown`
  and `mark_safe()`'d the result directly, with no sanitization.
  `canonical_markdown` is not trusted input — it can be set from an arbitrary
  `.md` sidecar file inside an uploaded ZIP bundle
  (`apps/projects/services.py::import_zipped_ris_bundle`), and python-markdown
  passes raw HTML in its source straight through to its output by default. A
  `.md` sidecar containing `<script>...</script>` would have rendered
  unescaped on every annotator's screen who opened that document. **Fixed:**
  added `nh3` (an allowlist HTML sanitizer) as a dependency and sanitize the
  rendered HTML with `nh3.clean()` before `mark_safe()`. `nh3`'s default
  allowlist keeps everything `python-markdown`'s `tables`/`fenced_code`
  extensions legitimately produce (headings, tables, code blocks, lists,
  links, images) while stripping `<script>` and event-handler attributes.
- `templates/schemas/form_builder.html` embedded four JSON payloads
  (`config_json`, `slot_meta_json`, `widget_choices_json`,
  `ontology_choices_json`) into `<script type="application/json">` blocks by
  hand-writing `<script>{{ value }}</script>` around a pre-`json.dumps()`'d
  string. Since the value was never marked `|safe`, Django's default
  autoescaping already neutralized `<`/`>`/`&` in the JSON string, so this
  was not an active vulnerability — but it depended on every future consumer
  reading the tag via `.textContent` (as the current JS does) rather than
  `.innerHTML`, and didn't get Django's extra `</script`-sequence hardening
  that the `json_script` filter provides. **Fixed for defense in depth:**
  `apps/schemas/views.py::FormBuilderView` now passes the raw Python
  objects instead of pre-serialized strings, and the template uses
  `{{ value|json_script:"element-id" }}`, which generates the `<script>` tag
  itself with Django's recommended escaping.
- No other `<script>` block embeds untrusted data: the remaining instances
  interpolate an integer PK, `active_seconds`, `{% url %}` output, or
  `{{ csrf_token }}` (Django's own token, alphanumeric by construction) — all
  safe to embed as bare JS/string literals.

## API keys

**Checked:** `ProposerConfig` and every model across the codebase for any
column that could hold a plaintext credential.

**Findings:** none. `ProposerConfig.api_key_env_var` (`apps/llm/models.py`)
stores only the *name* of an environment variable — the actual key is read
from `os.environ` at call time (`apps/llm/claude_proposer.py`) and never
persisted. `grep -rn "api_key" apps/*/models.py` across the whole codebase
turns up only this one field. No plaintext key/secret/token columns exist in
any model.

## CSRF

**Checked:** the whole codebase for `@csrf_exempt`.

**Findings:** none — `grep -rn "csrf_exempt" apps/ loom/` returns no matches.
Django's CSRF middleware is on by default (`MIDDLEWARE` in
`loom/settings/base.py`) and every non-GET view in this review relies on it
unmodified.

## Out of scope for this review, flagged for follow-up

- `apps/export/serializer.py` unconditionally emits a graph-level
  `source_document` key and several bookkeeping fields (`node_id`, `edge_id`,
  `id`, `annotator`) that the *current* CAMO schema
  (`config/schema/camo-0.7.4.yaml`) no longer declares at the class level it's
  written to. This means `validate_graph_data()` can fail closed-schema
  validation for graphs annotated under the current active schema — a
  correctness gap, not a security one, discovered while building
  `tests/e2e/test_full_annotation_workflow.py`. Recorded here rather than
  fixed, since it's outside this review's scope and touches export logic
  broader than the auth/upload/XSS/CSRF/secrets surface this review covers.
