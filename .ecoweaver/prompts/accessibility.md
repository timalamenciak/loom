# Accessibility Prompt Template

Objective:

[Audit for accessibility issues / Fix the following accessibility issue / Add accessible UI for the following feature]:

[describe target or issue]

Relevant context:

- Read `.ecoweaver/accessibility.md`.
- Inspect: [templates, frontend components, forms, views]

Constraints:

- Target WCAG 2.1 Level AA.
- Do not remove semantic HTML or ARIA attributes to simplify markup.
- Do not suppress focus indicators without providing a visible replacement.
- Preserve existing behavior while adding accessibility improvements.

Required workflow:

1. Inspect the target templates and components.
2. Check semantic structure, labels, contrast, keyboard navigation, and ARIA.
3. Make the smallest correct improvements.
4. Run axe or Lighthouse if tooling is available.
5. Test keyboard navigation for any interactive component changed.

Output:

List:

- Findings (file, issue, WCAG criterion)
- Changes made
- Tooling run and result
- Remaining risks or items needing manual testing
