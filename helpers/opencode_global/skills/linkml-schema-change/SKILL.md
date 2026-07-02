# LinkML Schema Change Skill

Use this skill when editing LinkML schemas or schema-derived artifacts.

## Workflow

1. Find the authoritative schema file.
2. Read `.ecoweaver/linkml.md` if present.
3. Inspect related classes, slots, enums, mixins, examples, and tests.
4. Determine whether the change is additive or breaking.
5. Edit the source schema first.
6. Regenerate artifacts using the repository command.
7. Validate examples and generated outputs.
8. Update tests and documentation.
9. Report migration or compatibility implications.

## Guardrails

- Do not edit generated artifacts without updating the source schema.
- Do not invent ontology terms.
- Do not remove provenance or evidence fields.
- Do not silently weaken validation.
