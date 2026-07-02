# Accessibility Audit Skill

Use this skill when auditing web UI for accessibility, reviewing templates or frontend changes, or preparing for release.

## Workflow

1. Read `.ecoweaver/accessibility.md`.
2. Inspect HTML templates and frontend components for the affected pages or features.
3. Check semantic structure: headings, landmarks, lists, tables.
4. Check all form inputs have associated `<label>` elements or `aria-label`.
5. Check that color is not the only information channel (errors, required fields, status).
6. Check keyboard navigation: interactive elements reachable by Tab, focus visible, no traps.
7. Check ARIA usage: roles, states, and `aria-live` regions are correct and not overused.
8. Check dynamic content: `aria-live` announces updates; focus is managed after route changes.
9. Run axe-core or Lighthouse on key pages if tooling is available.
10. Separate findings into blockers, important issues, and minor improvements.

## Guardrails

- Do not remove accessibility attributes to simplify markup.
- Do not suppress CSS `outline` without providing a visible focus replacement.
- Do not attach interactive handlers to non-interactive HTML elements.
- Do not skip heading levels in templates.
- Do not use `aria-hidden` on focusable content.

## Output format

```
Accessibility findings:

Blockers (WCAG AA failures):
- ...

Important:
- ...

Minor:
- ...

Tooling run:
- axe/Lighthouse — result
```
