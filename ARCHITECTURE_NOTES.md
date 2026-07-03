# Architecture Notes

## Ontology autocomplete: request/response contract and search pipeline

### Which endpoint the annotation UI actually calls

`static/js/ontology-autocomplete.js` defaults to `/ontology/search/` (backed by
`OntologySearchView`), but the annotation template overrides this at initialisation:

```html
<!-- templates/annotation/annotate.html:296 -->
window.loomOntologySearchUrl =
    "{% url 'project-ontology-search' project.pk %}?graph={{ graph.pk }}";
OntologyAutocomplete.init(window.loomOntologySearchUrl);
```

So in practice the annotation form always calls
**`GET /projects/<pk>/ontology/search/?graph=<graph_pk>&...`**
(`ProjectOntologySearchView` in `apps/ontology/views.py:44`).
The bare `/ontology/search/` endpoint (`OntologySearchView`) is the un-pinned
fallback used in contexts outside the annotation page (e.g. admin utilities).

---

### Request parameters

| Param | Source | Description |
|-------|--------|-------------|
| `q` | user keypress | Free-text search string; must be ≥ 2 chars or the view returns `{"results": []}` immediately |
| `prefixes` | `data-ontology-prefixes` attribute (comma-separated string) | Bare ontology prefix tokens, e.g. `ELMO,ENVO` |
| `limit` | optional, default 20 | Clamped to 1–50 |
| `graph` | injected by template | PK of the `CausalGraph`; used to resolve the pinned ontology snapshot |

The JS builds the URL in `_fetch()` (`ontology-autocomplete.js:115`):

```js
const url = `${searchUrl}&q=${encodeURIComponent(q)}&prefixes=${encodeURIComponent(prefixes)}`;
```

`prefixes` comes from `input.dataset.ontologyPrefixes`, which is populated by the
form-field partial (`templates/annotation/partials/form_field.html:82`):

```html
data-ontology-prefixes="{{ slot.ontology_prefixes|join:',' }}"
```

`slot.ontology_prefixes` is the list from `loom_ui.yaml → ontology_routing` for
that slot, e.g. `["ELMO", "ENVO"]` → attribute value `"ELMO,ENVO"`.

---

### Response shape

```json
{
  "results": [
    {
      "curie":       "ENVO:00001001",
      "label":       "forest biome",
      "definition":  "A biome …",          // truncated at 200 chars
      "synonyms":    ["forest", "…"]        // up to 4 items
    }
  ]
}
```

Empty result: `{"results": []}`.

---

### Snapshot pinning — pure local-DB, no network call

`ProjectOntologySearchView.get()` (`views.py:47`) resolves the snapshot to query:

1. Start with `project.ontology_snapshot`.
2. If `?graph=<pk>` is present, resolve that `CausalGraph` and use
   `graph.ontology_snapshot` instead (if set), falling back to the project
   snapshot if the graph has none.
3. Pass the resolved snapshot to `search_terms(snapshot=snapshot, ...)`.

`search_terms()` (`apps/ontology/services.py:20`) then queries only
`OntologyTerm` rows that belong to that snapshot:

```python
qs = OntologyTerm.objects.filter(
    Q(snapshot=snapshot) | Q(release__snapshots=snapshot),
    obsolete=False,
).distinct()
```

**There is no live network call in this path.** Every query is a local Postgres
lookup. The search strategy is:

1. Exact CURIE match if `query` contains `:`.
2. Trigram similarity (`TrigramSimilarity("label", query) > 0.15`) if
   `pg_trgm` is installed — wrapped in a savepoint so it degrades gracefully.
3. `label__icontains` OR `synonym_labels__icontains` fallback.

---

### The OLS fallback: aspirational, not implemented

`CLAUDE.md`, `AGENTS.md`, and `README.md` all mention an "OLS fallback" as a
convenience for terms not in the local index. **This code does not exist.**
`services.py` has no HTTP client, no `ebi.ac.uk` reference, no conditional
network branch. The OLS fallback is planned documentation that was never
implemented.

Implication for new live-lookup paths (e.g. Wikidata): there is no existing
"sometimes go live" trigger pattern in the search stack to follow. The natural
place to add one is inside `search_terms()` as a fourth fallback tier — after
the local-DB strategies return empty — guarded by a feature flag in settings.

---

### How `ontology_prefixes` flows from config to DB query

```
config/loom_ui.yaml
  ontology_routing:
    entity_term: [ELMO, ENVO]   # list of bare prefix strings
                ↓
schema engine builds slot.ontology_prefixes = ["ELMO", "ENVO"]
                ↓
form_field.html renders data-ontology-prefixes="ELMO,ENVO"
                ↓
JS sends ?prefixes=ELMO%2CENVO
                ↓
ProjectOntologySearchView splits on ',' → {"ELMO", "ENVO"}
  intersects with allowed_prefixes from the project's snapshot
                ↓
search_terms(prefixes=["ENVO", "ELMO"], ...)
                ↓
OntologyTerm.objects.filter(prefix__in=["ENVO", "ELMO"], ...)
```

The intersection step in `ProjectOntologySearchView` (`views.py:87–98`) is the
security/correctness gate: even if a caller sends arbitrary prefixes, only
prefixes present in the project's pinned snapshot can match. If the intersection
is empty the view short-circuits with `{"results": []}` rather than falling back
to an unrestricted query.

---

### Conditional routing: prefixes that depend on a sibling field

The flat `ontology_routing.<slot>: [PREFIX, ...]` shape above is one of two
shapes. The other lets a slot's routing depend on the current value of a
sibling slot on the same class — CAMO's `entity_term` needs a different
ontology depending on `entity_type` (`taxon` → Wikidata only,
`management_intervention` → ELMO, `environmental_process` → ENVO,
`environmental_variable` → ELMO + ENVO):

```yaml
ontology_routing:
  entity_term:
    condition_slot: entity_type
    allow_free_text: true
    routes:
      taxon:
        wikidata_live: {root_qid: "Q16521"}
      management_intervention:
        prefixes: [ELMO]
      environmental_process:
        prefixes: [ENVO]
      environmental_variable:
        prefixes: [ELMO, ENVO]
    default:
      prefixes: [ENVO]
```

`schema_engine._slot_spec()` (`apps/schemas/schema_engine.py`) flattens the
`default` route into `slot.ontology_prefixes`/`slot.wikidata_live` as before
(for any renderer that isn't sibling-aware), and additionally emits
`slot.ontology_condition_slot` and `slot.ontology_routes` (the full per-value
table). `form_field.html` writes these as `data-ontology-condition-slot`
(the sibling field's DOM id) and `data-ontology-routes` (JSON). At runtime,
`ontology-autocomplete.js`'s `_wireConditionalRouting()` reads the sibling's
current value, looks up the matching route, and overwrites
`input.dataset.ontologyPrefixes`/`wikidataLive`/`wikidataRootQid` before each
search — so the request/response contract described above is unchanged, only
which prefixes get sent depends on `entity_type` at query time. Changing
`entity_type` after a term was already picked clears the stale pick rather
than silently keeping a term grounded in the wrong ontology.

`allow_free_text: true` additionally makes the widget accept typed text that
matched nothing (schema permitting — see the CAMO `any_of: [uriorcurie,
string]` note below) and offers to log an `OntologyTermSuggestion`
(`apps/ontology/models.py`) for a curator to review and submit upstream.

**Widget-selection pitfall:** LinkML reports the base `range` of an
`any_of: [{range: uriorcurie}, {range: string}]` slot as plain `"string"`,
which would otherwise fall through to a bare text widget and silently lose
ontology autocomplete entirely (this was a real, pre-existing bug —
`measured_attribute` had this exact `any_of` shape and had never actually
rendered as `ontology_autocomplete`). `_slot_spec()` now checks `slot.any_of`
and prefers the `uriorcurie`/`curie` member for widget selection when present.

---

---

## Live ontology lookups: Wikidata (implemented) and OLS (sketch)

### Design principle

Live network calls live **at the view layer**, not inside `search_terms()`.
`search_terms()` is a pure DB function and must stay that way.  The view calls
the live helper *after* building the local results and merges the two lists,
with local results taking precedence (CURIEs already present in local results
are dropped from the live batch).

The JS signals that a live lookup is wanted via extra query params synthesised
from `data-*` attributes on the input element.  Those attributes are emitted by
the form-field partial, which reads them from the slot spec.  The slot spec is
built by `schema_engine._slot_spec()` from `loom_ui.yaml → ontology_routing`.
No view code hard-codes slot names; everything flows from config.

```
loom_ui.yaml (ontology_routing)
  → schema_engine._slot_spec()  → slot.wikidata_live / slot.ontology_prefixes
  → form_field.html             → data-wikidata-live / data-wikidata-root-qid
  → ontology-autocomplete.js    → ?wikidata_live=1&root_qid=<QID>
  → ProjectOntologySearchView   → _merge_wikidata() → wikidata_search.search()
```

### Wikidata live search (implemented)

**Config shape** (`loom_ui.yaml`):

```yaml
ontology_routing:
  entity_term:
    prefixes: [ELMO, ENVO]   # local prefixes — still searched first
    wikidata_live:
      root_qid: "Q16521"          # optional; omit to allow any taxon
```

`wikidata_live` is intentionally **not** a prefix named `"WD"`.  A `WD` prefix
would imply a pre-loaded `OntologyTerm` set (the local-DB path); `wikidata_live`
triggers two live HTTP calls and must never appear in `prefix__in` queries.

**`apps/ontology/wikidata_search.py`** — `search(query, root_qid, limit)`:

1. `wbsearchentities` — fetches ~2× *limit* candidate QIDs ordered by
   Wikidata relevance.
2. One batched SPARQL `VALUES` query — keeps only items that:
   - have `wdt:P105` (taxon rank) — confirms they are taxa, not arbitrary items
   - (when `root_qid` set) reach `root_qid` via `wdt:P171*` (transitive parent
     taxon, zero or more hops, so the root itself is included)
3. Relevance order from step 1 is preserved; SPARQL only filters.
4. Results: `[{curie: "WD:Q<n>", label, description}]`, deduplicated against
   local results in `_merge_wikidata()` before being added to the response.

**Cache**: 60 s in-process dict keyed on `(query.lower(), root_qid, limit)`,
protected by a `threading.Lock()`.  Stale entries are pruned opportunistically
on each cache write.  This absorbs repeated keystrokes from a single annotator
without hitting both APIs on every debounced request.

**Degradation**: any `URLError`, `OSError`, or JSON parse failure in either
network call returns an empty set / empty list.  The view always returns at
least local results; Wikidata failure is silent to the annotator.

**User-Agent**: `Loom/<version> (EcoWeaver causal-mosaic annotation workbench;
mailto:tim.alamenciak@gmail.com)` — required by Wikidata policy regardless of
request volume.  Uses `loom.__version__` so it stays accurate automatically.

### OLS fallback (sketch — not yet implemented)

The EBI Ontology Lookup Service (OLS4) exposes a search endpoint at
`https://www.ebi.ac.uk/ols4/api/search?q=<term>&ontology=<id>&type=class`.

**Where it would plug in** — same pattern as Wikidata:

1. New config key in `loom_ui.yaml`:
   ```yaml
   ontology_routing:
     some_slot:
       prefixes: [GO]
       ols_live:
         ontology: go    # OLS ontology ID — maps to ?ontology= param
   ```

2. `schema_engine._slot_spec()` extracts `ols_live` dict into the slot spec
   alongside `wikidata_live`.

3. Template emits `data-ols-live="true"` and `data-ols-ontology="go"`.

4. JS appends `&ols_live=1&ols_ontology=go` to the search URL.

5. New `apps/ontology/ols_search.py` module — `search(query, ontology, limit)`
   — single GET to OLS4, same cache/timeout/degradation pattern as
   `wikidata_search.py`.  No SPARQL step needed; OLS returns pre-filtered terms
   for the requested ontology.

6. `_merge_ols()` helper in `views.py` (alongside `_merge_wikidata()`) appends
   OLS results after local results, deduplicating by CURIE.

**Trigger condition** — the original README suggested "empty local result" as
the trigger.  The Wikidata implementation instead fires on every search when the
slot is configured for it (local + live in parallel via sequential calls).  For
OLS the same "always if configured" pattern is simpler and more consistent than
"only on empty local" — annotators at a self-hosted instance with no network
access can simply leave `ols_live` unconfigured, and the view degrades cleanly
because network failure returns [].

---

### Two views, different scoping

| View | URL | Snapshot | Prefix scope |
|------|-----|----------|--------------|
| `OntologySearchView` | `GET /ontology/search/` | Global active snapshot | Caller-supplied prefixes, no intersection guard |
| `ProjectOntologySearchView` | `GET /projects/<pk>/ontology/search/` | Project- or graph-pinned snapshot | Caller prefixes intersected with snapshot's prefixes |

The annotation UI always uses `ProjectOntologySearchView`. `OntologySearchView`
is the un-pinned convenience endpoint.
