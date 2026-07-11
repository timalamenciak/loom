# Performance sanity check — v1.0.0 release hardening

Target: the operations below stay under 2 seconds for a project with 500
documents and 2000 edges. Query-count regression tests live in
`tests/annotation/test_annotation_performance.py` and
`tests/export/test_export_performance.py`; they catch N+1 regressions by
capping total queries per request, not by measuring wall-clock time, since
query count is what actually scales with dataset size (wall-clock time on a
given machine is not a stable CI signal).

## Annotation page load

**Checked:** query count for `GET /annotation/<pk>/documents/<doc_pk>/annotate/`
against a graph with 10 edges (20 nodes) — the query most likely to develop an
N+1 as edge count grows.

**Finding:** the edges/nodes/spans querysets already fetch in a single query
each (no per-item N+1) — `_graph_nodes_edges()` and the spans query in
`AnnotationView._get()` all use plain `.all()`/`.filter()` calls, so the query
count here does **not** grow with the number of edges or nodes in the graph.
What was over budget was fixed per-request overhead: the same `Project` row
was fetched twice (once directly, once implicitly via `document.project`
inside `require_annotation_assignment()`), and the same `SchemaVersion` row
was fetched twice (`project.active_schema` and `graph.schema_version`),
because neither the `Project` nor the `Assignment`/`Document` lookups
declared the join. 21 queries total, 1 over the 20-query budget.

**Fixed:**
- `AnnotationView._get()` (`apps/annotation/views.py`) now fetches `Project`
  with `select_related("active_schema")` and `Document` with
  `select_related("project")`.
- `require_annotation_assignment()` (`apps/annotation/policies.py`) now uses
  `select_related("graph__schema_version")` instead of `select_related("graph")`
  — purely additive (one more join column, same rows), so every other caller
  of this shared policy function benefits too, not just `AnnotationView`.

Down to 18 queries, and — because none of the eliminated queries scaled with
edge/node count — the total stays flat regardless of graph size.

`form_spec()` (`apps/schemas/schema_engine.py`) is **not** LRU-cached, despite
what the write-up in this epic's spec assumed — there is no `@lru_cache` on it
or on `_node_form_spec`/`_edge_form_spec`. What *is* cached is the parsed
`LoomSchemaView` wrapper object itself (`get_schema_view()`, keyed by
`(schema_version.pk, project.pk)`), which avoids the actually-expensive part
(re-parsing the raw LinkML YAML via `SchemaView(yaml)` on every request).
`form_spec()` re-walks the already-parsed schema's induced slots on every
call, which is cheap pure-Python dict-building, not a query or a parse — not
worth caching further without a demonstrated bottleneck.

## Ontology search (pg_trgm)

**Checked:** whether the GIN trigram index on `OntologyTerm.synonym_labels`
exists and is usable, via `EXPLAIN ANALYZE`.

**Finding:** the index exists —
`ontologyterm_synonyms_trgm_idx` (`apps/ontology/models.py`, migration
`0008_trigram_search.py`), a `GinIndex(fields=["synonym_labels"],
opclasses=["gin_trgm_ops"])`, alongside the equivalent index on `label`. At
the current dev database's term count (2,969 rows), `EXPLAIN ANALYZE` on a
representative trigram-similarity query shows Postgres choosing a **sequential
scan** over the index — correct planner behavior at this scale, not a defect:
```
Seq Scan on ontology_ontologyterm (cost=0.00..106.12 rows=1 width=31)
  (actual time=8.276..8.276 rows=0 loops=1)
  Filter: (synonym_labels % 'nitrogen cycling'::text)
```
Forcing `SET enable_seqscan = off` confirms the index is valid and usable —
the planner switches to it immediately:
```
Bitmap Index Scan on ontologyterm_synonyms_trgm_idx
  (cost=0.00..151.73 rows=1 width=0) (actual time=0.336..0.336 rows=0 loops=1)
```
A real deployment loading ENVO/CHEBI/GO/PATO/etc. from `config/ontologies.yaml`
has tens of thousands of terms, well past the row count where Postgres's
planner switches to the index automatically. No change needed.

## Proposal review queue

**Checked:** query count for `GET /projects/<pk>/review-proposals/` against a
project with 50 draft `llm_proposed` edges — the queue's `_draft_proposals()`
query already declared
`.select_related("subject", "object", "graph__document")`.

**Finding:** 5 queries total regardless of proposal count (session/user auth,
project lookup, the schema/ontology update-check banner's context processor,
and the proposals query itself) — well under the 9-query budget, no N+1. No
change needed.

## Export (`serialize_graph`)

**Checked:** query count for `serialize_graph()` against a graph with 50
edges, half of them carrying a grounding `TextSpan`.

**Finding — a real N+1**: `_serialize_spans()` calls `edge.spans.all()` per
edge, and the edges queryset in `serialize_graph()` only had
`select_related("subject", "object")` — no `prefetch_related` for the
`spans` reverse relation. This issued one extra query *per edge*: for a
50-edge graph that's 1 query for the edges themselves plus 50 more for their
spans (51 total before the fix), and a single document with 2000 edges would
have cost over 2,000 additional round trips on export.

**Fixed:** `serialize_graph()` (`apps/export/serializer.py`) now uses
`prefetch_related(Prefetch("spans", queryset=TextSpan.objects.order_by("start_char")))`
on the edges queryset — a `Prefetch` object rather than a bare
`"spans"` string so the existing `start_char` ordering `_serialize_spans()`
needs is baked into the prefetch itself (re-calling `.order_by()` on an
already-prefetched relation would silently re-issue a query per edge and
defeat the fix). Measured 3 queries total for the 50-edge/25-span regression
test fixture (nodes, edges, and the single prefetched spans query) — down
from 51, and flat regardless of edge count, well under the 19-query budget.
