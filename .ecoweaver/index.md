# EcoWeaver AI Development Layer

This folder provides durable project context for coding agents working on EcoWeaver-related research software and schema.

Use it to make agent work more accurate, less speculative, and easier to review.

## Files

- `architecture.md` — system structure, services, data flow, boundaries
- `linkml.md` — schema editing, generation, validation, and migration rules
- `ontology.md` — ontology grounding, term selection, and no-invention policy
- `style.md` — coding, documentation, naming, and formatting conventions
- `testing.md` — verification workflow and test expectations
- `security.md` — input validation, authentication, secrets, dependency security
- `accessibility.md` — WCAG 2.1 AA, keyboard navigation, ARIA, form labeling
- `publication.md` — research software, JOSS, reproducibility, and citation expectations
- `review.md` — checklist before final answer, commit, or PR
- `prompts/` — reusable task prompts for coding agents

## Default workflow

1. Identify the subsystem and relevant files.
2. Read the relevant `.ecoweaver/` guidance.
3. Make the smallest correct change.
4. Preserve provenance and compatibility.
5. Add or update tests when behaviour changes.
6. Run the narrowest useful verification command.
7. Always run the full lint sequence before finishing: `ruff check --fix .`, `black .`, `mypy .` (if configured), `bandit -r src/` (if configured), `python manage.py check` (Django). Or `pre-commit run --all-files` if configured. Fix all errors; never suppress them to pass.
8. For web UI changes, check `accessibility.md` and verify keyboard navigation.
9. For any externally-facing code, check `security.md` and verify input validation.
10. Report what changed, what was checked, and what remains uncertain.

## Agent behaviour

Agents should prefer explicit evidence from the repository over assumptions. When uncertain, inspect files before editing. Avoid broad rewrites unless specifically requested.

Linting is mandatory on every task. See the `lint` global skill for the full command sequence. Report lint results in every final summary, even if all checks pass.

## Project adaptation

Each repository should customize `architecture.md`, `testing.md`, and any project-specific commands. Keep shared principles stable across Loom, Heddle, CAMO, LexWeaver, and related EcoWeaver tools.

For web-facing projects, also read `security.md` and `accessibility.md` before any UI or API work.
