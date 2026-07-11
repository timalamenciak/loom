# Migrating from v0.x to v1.0.0

v1.0.0 adds the LLM proposal pipeline (`apps/llm`: `ProposerConfig`,
`FewShotExample`, `ProposalOutcome`), new upload/XSS hardening (see
[`security-review-v1.0.md`](security-review-v1.0.md)), and a couple of
`select_related`/`prefetch_related` fixes (see
[`performance-review-v1.0.md`](performance-review-v1.0.md)). None of it
changes `CausalGraph`/`Node`/`Edge` storage — existing annotation data is
untouched by this upgrade. Take a database backup before starting (see
[`operations.md`](operations.md#backup-set)); every step below is safe to
re-run, but a backup is still the fastest way back to a known-good state if
something upstream of Loom goes wrong.

## 1. Apply migrations

```bash
python manage.py migrate
```

Picks up every new model from v0.4–v0.9 in one pass: `ProposerConfig`,
`FewShotExample`, `ProposalOutcome`, and their fields — nothing here is
destructive, and none of it touches existing `annotation_*` tables.

## 2. Confirm the active schema

v1.0.0 doesn't change the CAMO schema itself. If you're already running an
active schema, there's nothing to do — skip to step 3. This step only
matters if your instance somehow ended up with **no** active schema (check
**Schemas** in the UI, or `SchemaVersion.objects.filter(is_active=True)`
in a shell), in which case load and activate one:

```bash
python manage.py load_schema config/schema/camo-0.4.0.yaml --activate
```

Substitute whichever version your projects actually annotate under —
`config/schema/` ships every CAMO release Loom has seen;
`python manage.py list_schemas` shows what's currently loaded. Don't treat
`camo-0.4.0.yaml` as a recommendation to downgrade a running instance to an
older schema version; it's an example path, not a target version.

## 3. Re-load ontologies (only if you want the latest term sets)

```bash
python manage.py load_ontology --all
```

Optional — this re-fetches every ontology listed in
`config/ontologies.yaml` from its source, which can take a while for the
larger ones (ENVO, CHEBI, GO). It's not required by the v1.0.0 upgrade
itself; run it if you want the latest upstream term sets, or skip it and
your existing `OntologyRelease` rows are untouched.

## 4. Check for upstream schema/ontology updates (optional)

```bash
python manage.py check_all_updates
```

Populates the update-notification banner staff users see in the UI (see
[`admin-guide.md`](admin-guide.md#reviewing-update-notifications-and-applying-updates)).
Informational only — it doesn't apply anything by itself.

## 5. Verify existing graphs still export cleanly

```bash
python manage.py validate_graph --all
```

Runs every `CausalGraph` through `serialize_graph()` +
`validate_graph_data()` against the schema *that graph is pinned to*
(`CausalGraph.schema_version` — not necessarily whatever is currently
active), and reports pass/fail per graph plus a summary line. `--all` is new
in v1.0.0; earlier versions only supported a single `graph_pk`.

**This step is not just a formality.** While building this release's
end-to-end test (see `tests/e2e/test_full_annotation_workflow.py`), we found
that `serialize_graph()` emits some graph- and edge-level bookkeeping fields
(`source_document`, `node_id`, `edge_id`, `annotator`) that the *current*
CAMO schema no longer declares at the class level it's written to — meaning
`validate_graph_data()` can fail closed-schema validation for graphs
annotated under a recent schema version, independent of anything in this
migration. Run this step and read the output; if you see validation
failures, that's a real, pre-existing gap between `apps/export/serializer.py`
and the active CAMO schema, not something this migration introduced or that
re-running these steps will fix. Treat it as a finding to track, not a
migration error to retry.

## Rollback

Every step above is additive or read-only except step 1
(`migrate`). To roll back the schema migration specifically:

```bash
python manage.py migrate llm zero
```

This only removes the v1.0.0 `apps/llm` tables (`ProposerConfig`,
`FewShotExample`, `ProposalOutcome`) — it does not touch `CausalGraph`,
`Node`, or `Edge`. Restore from the pre-upgrade backup instead if you need to
undo anything beyond that.
