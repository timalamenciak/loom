# LinkML Workflow

LinkML schemas are authoritative. Generated artifacts derive from schemas and should not be edited directly.

## Core rules

- Preserve semantic clarity over convenience.
- Prefer explicit slots over ambiguous overloaded fields.
- Reuse existing classes, slots, enums, and types when appropriate.
- Do not introduce breaking changes without identifying affected data and migrations.
- Do not invent ontology terms or identifiers.
- Keep provenance and evidence fields intact.
- Update examples and tests when schema behaviour changes.

## Before editing a schema

1. Locate the authoritative LinkML source file.
2. Identify generated artifacts derived from it.
3. Search for existing related classes, slots, enums, and mixins.
4. Determine whether the change is additive, refining, or breaking.
5. Check downstream code that loads, validates, exports, or displays the affected element.

## Schema change checklist

For each schema change, verify:

- class or slot name is clear and stable
- description explains meaning, not just UI usage
- range is appropriate
- cardinality is intentional
- required status is justified
- examples or annotations are updated
- generated artifacts are regenerated
- validation passes
- tests are updated
- migration impact is documented

## Additive changes

Prefer additive changes for early-stage schemas:

- new optional slot
- new enum permissible value
- new class that does not replace an existing class
- new annotation metadata

Additive does not mean harmless. Check import/export, validation, serializers, UI forms, and tests.

## Breaking changes

Breaking changes include:

- renaming classes or slots
- changing requiredness
- narrowing ranges
- removing permissible values
- changing identifiers
- changing meaning without changing name

For breaking changes, provide a migration note:

```markdown
## Migration note

Old:
New:
Reason:
Affected data:
Migration strategy:
Compatibility risk:
```

## Common commands

Customize these per repository.

```bash
make schema
make test
make docs
linkml-validate --schema schema/main.yaml data/example.yaml
```

## Agent instructions

When asked to change a LinkML schema:

1. Read this file.
2. Inspect the current schema.
3. Propose the minimal schema change.
4. Update source schema first.
5. Regenerate derived artifacts using the project command.
6. Update tests/examples.
7. Report commands run and any failures.
