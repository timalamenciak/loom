# Loom documentation

Loom is a workbench for recording causal claims from scientific articles with
the Causal Mosaic (CAMO) schema.

## Annotators

The [annotator guide](user-guide/index.md) follows a complete assignment from
the queue through submission. Start there if you are using Loom to annotate an
article. The one-page [annotator guide](annotator-guide.md) covers what the
multi-page guide doesn't yet: reviewing and accepting LLM proposals.

The core workflow is:

1. Open an article from **My queue**.
2. Read the article and collect excerpts that support causal claims.
3. Record article-level context in **Source doc**.
4. Create nodes for the cause and effect in each claim.
5. Connect those nodes with a causal edge.
6. Save and check each annotation.
7. Mark finished edges complete and select **Submit for review**.

## Administrators and developers

The [admin guide](admin-guide.md) covers day-to-day admin tasks: loading and
activating schemas, tuning the form builder, loading ontologies, and
configuring the LLM pipeline. [`operations.md`](operations.md) covers
deployment, backups, and health checks; [`migration-v0-to-v1.md`](migration-v0-to-v1.md)
covers upgrading from v0.x. The rest of the technical reference covers
Loom's architecture, data model, and service layer, separate from the
task-focused guides above.
