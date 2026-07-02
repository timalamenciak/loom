# Accessibility Guidelines

EcoWeaver tools should be usable by researchers with a range of abilities and assistive technologies. Accessibility is a quality requirement, not an optional enhancement.

## Target standard

Aim for WCAG 2.1 Level AA compliance on all web interfaces.

## Core principles (POUR)

- **Perceivable**: information is not conveyed by color or visual formatting alone.
- **Operable**: all functionality works with keyboard alone; no timing traps.
- **Understandable**: error messages are human-readable; labels are clear and consistent.
- **Robust**: works with current assistive technologies; prefer semantic HTML over ARIA.

## HTML and Django templates

- Use semantic elements: `<nav>`, `<main>`, `<header>`, `<footer>`, `<section>`, `<article>`, `<aside>`.
- Every form input has an associated `<label>` via the `for` attribute or by wrapping.
- Every image has an `alt` attribute; decorative images use `alt=""`.
- Headings are hierarchical (`h1` → `h2` → `h3`); do not skip levels.
- Tables have `<thead>`, `<th scope="col">` or `<th scope="row">`, and a `<caption>` where appropriate.
- Links and buttons have descriptive text; icon-only interactive elements require `aria-label`.

## Color and contrast

- Body text contrast ratio ≥ 4.5:1; large text (≥ 18pt or ≥ 14pt bold) ≥ 3:1.
- Do not use color as the only way to convey information (error state, required field, status indicator).
- Pair color with a visible icon, border, or text label to communicate state.
- Verify contrast with axe DevTools, Lighthouse, or the WebAIM Contrast Checker.

## Keyboard navigation

- All interactive elements are reachable by Tab key in a logical visual order.
- A visible focus indicator is present at all times; do not suppress `outline` without providing a visible replacement.
- Modal dialogs trap focus inside and return focus to the trigger element on close.
- No keyboard traps: the user can always Tab or press Escape to move on.
- Implement skip-navigation links at the top of pages with repetitive header navigation.

## ARIA

- Prefer native HTML semantics over ARIA roles; ARIA supplements, it does not replace semantic HTML.
- Use `aria-label` or `aria-labelledby` for elements whose visible label is absent or ambiguous.
- Use `aria-describedby` to link help text or error messages to their associated control.
- Use `role="status"` or `aria-live="polite"` to announce dynamic content updates (success messages, search results, loading states).
- Use `aria-expanded`, `aria-selected`, `aria-checked` correctly for interactive widgets.
- Do not apply `aria-hidden` to focusable elements.

## Forms and error handling

- Display inline error messages adjacent to the field, not only at the top of the page.
- Link error messages to inputs using `aria-describedby`.
- Mark required fields with the `required` attribute and indicate requirement in the label or legend.
- On form submission failure, move focus to the first error field or to an error summary at the top.
- Provide clear confirmation or success feedback after successful submission.

## Dynamic content

- Announce dynamic content changes using `aria-live` regions.
- For pagination, filtering, and table updates: announce the result count after the update completes.
- Manage focus explicitly after route changes in JavaScript-heavy views.
- Avoid content that flashes more than three times per second.

## Django patterns

- Use accessible form rendering tools (e.g., crispy-forms with accessible templates) rather than unstyled custom HTML.
- Add `required`, `aria-invalid="true"`, and `aria-describedby` to fields that fail validation.
- Ensure admin interface customizations preserve Django admin's accessibility baseline.
- For custom widgets, test keyboard and screen reader interaction before deploying.

## JavaScript and TypeScript

- Do not attach click handlers to non-interactive elements; use `<button>` or `<a>` instead.
- Custom interactive components (dropdowns, autocomplete, tabs, modals, accordions) should follow ARIA Authoring Practices Guide (APG) patterns.
- Do not rely on hover alone to reveal important content; provide keyboard-accessible equivalents.
- Test each custom component with keyboard navigation and at least one screen reader.

## Testing accessibility

- Run axe-core or Lighthouse against key pages before each release.
- Test primary user workflows with keyboard only (no mouse).
- Test with at least one screen reader (NVDA on Windows, VoiceOver on macOS) for high-traffic pages.
- Include accessibility findings in pull request reviews alongside functional correctness.

## Agent instructions

When building or modifying any web UI:

1. Read this file.
2. Confirm semantic HTML is used in templates.
3. Confirm all form inputs have associated labels.
4. Confirm color is not the only information channel.
5. Confirm focus management is correct for any dynamic content or modals.
6. Run axe or Lighthouse on any new page if tooling is available.
7. Flag accessibility issues found even if they fall outside the immediate task scope.
