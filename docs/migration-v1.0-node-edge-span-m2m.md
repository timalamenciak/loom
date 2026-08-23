# Updating a live server: node/edge/span grounding becomes many-to-many

This release changes how excerpt ("snippet") grounding works: a `TextSpan`
can now ground **any number of** nodes and edges, instead of at most one of
each. Alongside that: node/edge names no longer clip in the annotate view,
the excerpt bin is vertically resizable, and node-level `source_spans` are
now included in exported graphs (a pre-existing gap where node grounding was
silently dropped from every export is fixed as part of this change).

**Unlike the v0→v1.0.0 upgrade, this one is not purely additive.** The
migration (`apps/documents/migrations/0004_span_node_edge_m2m.py`) copies
every existing `TextSpan.node`/`TextSpan.edge` link into new join tables and
then **drops the `node`/`edge` columns**. The copy step is safe and
lossless when run against a healthy database, but once the columns are
dropped there is no way back except restoring a backup — read this whole
document before running `migrate` on production, and do not skip the
backup step.

## 1. Back up first — mandatory, not optional

Use the exact backup set from [`operations.md`](operations.md#backup-set):
a PostgreSQL custom-format dump, the complete `media/` directory, and the
deployed Git revision.

```bash
docker compose exec -T db sh -c \
  'pg_dump --format=custom --no-owner --file=/tmp/loom.dump \
  --username="$POSTGRES_USER" "$POSTGRES_DB"'
docker compose cp db:/tmp/loom.dump ./loom.dump
```

Archive `media/` separately, record SHA-256 checksums for both, and keep
them somewhere other than the application host. Do not proceed to step 2
without a dump you're confident you could restore from.

## 2. Pre-flight

```bash
python manage.py check --deploy --fail-level WARNING --settings=loom.settings.prod
python manage.py migrate --check
python scripts/check_migration_readiness.py
```

`check_migration_readiness.py` confirms an active `SchemaVersion` and
`OntologySnapshot` exist, no `Node`/`Edge` belongs to a graph with a null
`schema_version`, and every `CausalGraph` currently validates — run it
*before* the migration as a sanity check that you're starting from clean
state, not only as a post-deploy gate.

Also review `CHANGELOG.md` for this release, per the standard upgrade
sequence in [`operations.md`](operations.md#upgrades-and-rollback).

## 3. Deploy

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

The `migrate` one-shot service runs automatically and gates `web`/
`ontology-worker` (`depends_on: condition: service_completed_successfully`)
— if the migration fails, those services never start, which is the signal
to stop and investigate rather than something to work around.

If you run migrations manually instead of via the `migrate` service:

```bash
python manage.py migrate
```

## 4. Post-deploy verification specific to this release

Beyond the standard checks in `operations.md` (`/health/ready/`, login,
document access), verify the things this specific migration and these
specific UI changes touch:

1. **Existing span links survived the migration.** Open the annotate view
   for a document that had spans linked to nodes/edges before the upgrade
   and confirm they still show as linked. This is the direct proof the
   `copy_fk_links_to_m2m` data-migration step worked, not just that the
   schema change applied.
2. **A span can ground more than one node.** Pick any excerpt, link it to
   two different nodes via the node form's excerpt picker, and confirm both
   persist after reload — this is the actual feature, not just schema
   plumbing.
3. **Node-level `source_spans` now export.** Export a graph that has at
   least one node with a linked excerpt and confirm `source_spans` appears
   under that node in the output YAML — it did not appear there before this
   release (see `apps/export/serializer.py::_serialize_node`).
4. **Node/edge names no longer clip.** In the annotate view's graph panel,
   confirm a long node name or edge subject/object pair wraps instead of
   being cut off with an ellipsis, and that hovering shows the correct
   tooltip (not a raw UUID).
5. **The excerpt bin resizes.** Drag the new handle below the excerpt bin
   and confirm it resizes and the size persists across a reload.

## Rollback

Steps 2–4 above are otherwise routine — application rollback is only safe
if the previous release still understands the database schema, per
[`operations.md`](operations.md#upgrades-and-rollback). That rule applies
with extra force here: because this migration **drops** the `TextSpan.node`
and `TextSpan.edge` columns, the previous application version cannot run
against a post-migration database at all (those columns are gone). If you
need to roll back after this migration has run, restore the matching
database and media backup pair from step 1 — do not attempt to redeploy the
old image against the already-migrated database.
