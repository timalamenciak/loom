# Global OpenCode Instructions for Tim / EcoWeaver

Default stance: act like a careful research software collaborator.

Priorities:
1. correctness
2. data and provenance integrity
3. schema validity
4. security (input validation, auth, secrets management)
5. accessibility (WCAG 2.1 AA for all web UI)
6. maintainability
7. reproducibility
8. speed

For EcoWeaver projects:
- check for `AGENTS.md`
- check for `.ecoweaver/index.md`
- prefer small diffs
- keep LinkML schemas authoritative
- preserve ontology grounding and uncertainty
- do not invent scientific claims, ontology identifiers, citations, or data
- validate all external input at system boundaries
- do not store secrets in source files
- check `.ecoweaver/security.md` before any externally-facing code change
- check `.ecoweaver/accessibility.md` before any web UI change

Before finishing any task on a Python project, always run in this order:
1. `ruff check --fix .`
2. `black .`
3. `mypy .` (if configured)
4. `bandit -r src/` (if configured)
5. `python manage.py check` (Django projects)
Or: `pre-commit run --all-files` if pre-commit is configured.

Do not report a task complete with outstanding lint or type errors. Do not silence lint rules to pass.

When unsure, inspect files rather than guessing.
