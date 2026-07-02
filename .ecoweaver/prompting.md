# EcoWeaver Prompting Guide

This file defines reusable prompting practices for OpenCode and other coding agents working on EcoWeaver projects.

The goal is not to write clever prompts. The goal is to give the agent enough structure to behave like a careful research software engineer.

## Prompt hierarchy

Use prompts as the final layer on top of durable context:

1. Project documentation in `.ecoweaver/`
2. Persistent rules in `AGENTS.md`
3. Reusable skills
4. Task-specific prompts

Do not compensate for missing project knowledge with huge one-off prompts. Improve the durable context instead.

## Standard prompt shape

Every substantial coding prompt should include:

```text
Objective

Background

Relevant files

Constraints

Plan first

Implementation

Verification

Summary
```

### Objective

State the concrete outcome. Avoid vague instructions such as "improve this" unless paired with measurable criteria.

Good:

```text
Add CSV export for validated annotations.
```

Weak:

```text
Make exports better.
```

### Background

Explain why the change matters and how it fits the research software.

For EcoWeaver work, include whether the change affects:

- LinkML schemas
- ontology grounding
- provenance
- annotation workflows
- Django models or migrations
- publication/reproducibility requirements

### Relevant files

Name the files, directories, or docs the agent should inspect first. Keep this list short.

Example:

```text
Relevant files:
- .ecoweaver/linkml.md
- schema/causal_mosaic.yaml
- tests/test_schema_validation.py
```

### Constraints

Say what must not change.

Common EcoWeaver constraints:

- Do not invent ontology terms.
- Preserve provenance.
- Preserve backward compatibility unless explicitly told otherwise.
- Do not edit generated files directly.
- Do not weaken validation to make tests pass.
- Do not introduce new dependencies without explaining why.
- Prefer small, reviewable changes.

### Plan first

For non-trivial tasks, require the agent to plan before editing.

```text
Do not edit immediately. First inspect the relevant files, identify affected components, state risks, and propose a concise implementation plan.
```

### Implementation

Ask for the smallest coherent change.

```text
Implement the smallest change that satisfies the objective. Avoid broad refactors unless necessary.
```

### Verification

Define exactly how the work should be checked.

```text
Run focused tests first. Then run the broader relevant test suite if the focused tests pass. Report any commands that could not be run.
```

### Summary

Require an end-of-task report.

```text
Summarize files changed, why each changed, what was verified, and any remaining risks.
```

## Prompt patterns

### Planning prompt

Use this when the design is unclear.

```text
Do not write code yet.

Read the relevant project context and propose a design.

Include:
1. affected files
2. data model implications
3. migration/schema implications
4. testing strategy
5. risks or ambiguity
6. smallest safe implementation path
```

### Implementation prompt

Use this when the design is clear.

```text
Implement the approved plan.

Make the smallest coherent change.
Preserve existing behavior unless the plan explicitly changes it.
Update tests and docs as needed.
Run focused verification.
End with a concise summary of changes and checks.
```

### Debugging prompt

Use this when something is failing.

```text
Diagnose before fixing.

First identify the failing behavior, likely cause, and minimal reproduction.
Then make the smallest fix.
Do not mask the failure by weakening tests or validation.
After fixing, run the failing test plus adjacent tests.
```

### Refactor prompt

Use this when improving structure without changing behavior.

```text
Refactor without changing external behavior.

Before editing, identify the current behavior that must be preserved.
After editing, explain why behavior is unchanged.
Add or update tests if behavior was previously untested.
Do not combine refactoring with unrelated feature work.
```

### LinkML/schema prompt

Use this for schema changes.

```text
This is a LinkML schema change.

Read `.ecoweaver/linkml.md` and `.ecoweaver/ontology.md` first.
Preserve backward compatibility unless explicitly told otherwise.
Do not edit generated artifacts directly.
Update examples, validation tests, and docs.
Regenerate artifacts using the documented command.
Explain any ontology mappings and provenance implications.
```

### Review prompt

Use this before merging or opening a PR.

```text
Review this change as if preparing it for a research software release.

Check:
- correctness
- minimality
- tests
- docs
- provenance
- ontology/schema consistency
- backward compatibility
- generated artifacts
- security (input validation, auth, secrets)
- accessibility (labels, keyboard nav, ARIA) for any UI changes
- publication/JOSS readiness where relevant

Return actionable findings only, grouped by severity.
```

### Security review prompt

Use this when auditing security-sensitive code or before release.

```text
Review for security issues.

Read `.ecoweaver/security.md` first.

Check:
- all external inputs are validated before use
- secrets are not in source or logs
- authentication and authorization are enforced at the correct layer
- dependencies are audited for CVEs
- Django security settings are configured for production

Return findings grouped by: blockers, important, minor.
```

### Accessibility prompt

Use this for any web UI change.

```text
Audit and fix accessibility for this feature.

Read `.ecoweaver/accessibility.md` first.

Check:
- semantic HTML structure
- form labels
- color as sole information channel
- keyboard navigation
- ARIA usage
- dynamic content announcements

Run axe or Lighthouse if available. Report findings by severity.
```

## Definition of done

For EcoWeaver projects, a task is done when:

- the smallest coherent change has been made
- `ruff check --fix .` passes with no remaining errors
- `black .` produces no changes (or all format changes are intentional)
- `mypy .` passes, or failures are explicitly reported (if configured)
- `bandit -r src/` is clean at HIGH/MEDIUM, or findings are explicitly reported (if configured)
- `python manage.py check` passes (Django projects)
- relevant tests pass, or failures are clearly reported
- schema artifacts are regenerated when applicable
- documentation is updated when behavior changes
- provenance and ontology constraints are preserved
- generated files are not edited by hand
- security: all external inputs are validated; no secrets in source; auth enforced
- accessibility: all new form inputs labeled; keyboard navigation verified for UI changes
- the final response lists changed files, lint results, verification, and known risks

## Anti-patterns

Avoid these:

- dumping the entire repository into context
- asking for broad changes without success criteria
- mixing feature work, refactoring, and formatting in one task
- asking the agent to "just fix it" without requiring diagnosis
- accepting ontology terms or citations invented by the model
- allowing generated files to be modified directly
- treating green tests as sufficient when schema/docs are stale
- accepting a web UI change without checking keyboard navigation
- accepting a security-relevant change without checking input validation and auth
- treating "it works in the browser" as sufficient accessibility verification

## Compact prompt template

Use this when speed matters:

```text
Objective:

Background:

Relevant files:

Constraints:

Plan first, then implement the smallest safe change.
Verify with focused tests.
Summarize changed files, checks run, and remaining risks.
```
