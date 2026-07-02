# Feature Prompt Template

Objective:

Add or change the following feature:

[describe the feature]

Background:

[why this matters; user/research workflow; related issue if any]

Relevant context:

- Read `.ecoweaver/index.md`.
- Read `.ecoweaver/architecture.md`.
- Read `.ecoweaver/style.md`.
- Read `.ecoweaver/testing.md`.
- Also inspect: [files/directories]

Constraints:

- Preserve existing behavior unless explicitly changed here.
- Prefer the smallest coherent implementation.
- Do not introduce dependencies without explaining why.
- Update docs if user-facing behavior changes.
- Add or update tests.

Plan first:

Before editing, identify affected files, risks, and the implementation plan.

Implementation:

Implement the plan after it is internally consistent.

Verification:

Run focused tests first, then broader relevant tests if appropriate.

Final response:

List changed files, verification commands, results, and remaining risks.
