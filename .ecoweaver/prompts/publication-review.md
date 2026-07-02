# Publication Review Prompt Template

Objective:

Review this repository as publication-quality research software.

Relevant context:

- Read `.ecoweaver/publication.md`.
- Read `.ecoweaver/review.md`.
- Read README, license, citation metadata, tests, examples, and docs.

Review dimensions:

- statement of need
- installation
- examples/tutorials
- tests and CI
- reproducibility
- documentation
- license
- citation metadata
- contribution guidelines
- schema/provenance quality where applicable

Output:

Return actionable findings grouped by severity:

1. Blockers
2. Important improvements
3. Nice-to-have improvements

Do not rewrite the whole project. Focus on the smallest changes that would improve publication readiness.
