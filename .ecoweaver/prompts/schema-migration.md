# Schema Migration Prompt Template

Objective:

Change the schema while preserving existing data compatibility where possible.

Schema change:

[describe new class/slot/enum/rule]

Relevant context:

- Read `.ecoweaver/linkml.md`.
- Read `.ecoweaver/ontology.md`.
- Read `.ecoweaver/testing.md`.
- Inspect: [schema files, examples, validation tests]

Constraints:

- Preserve backward compatibility unless explicitly authorized.
- Do not invent ontology terms.
- Preserve provenance fields.
- Do not edit generated artifacts directly.
- Update examples and tests.
- Regenerate artifacts with the documented command.

Plan first:

Explain model implications, migration risk, and compatibility strategy before editing.

Verification:

Validate schema, regenerate artifacts, run schema tests, and check examples.

Final response:

Summarize schema changes, generated artifacts, validation results, and compatibility notes.
