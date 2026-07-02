# Bugfix Prompt Template

Objective:

Fix the following bug:

[describe observed behavior]

Expected behavior:

[describe correct behavior]

Relevant context:

- Read `.ecoweaver/index.md`.
- Read `.ecoweaver/testing.md`.
- Inspect: [files/logs/tests]

Constraints:

- Diagnose before fixing.
- Do not weaken validation or tests to hide the bug.
- Make the smallest fix that addresses the root cause.
- Preserve unrelated behavior.

Required workflow:

1. Reproduce or explain the failure.
2. Identify likely root cause.
3. Make the smallest fix.
4. Add or update a regression test if possible.
5. Run the failing test and adjacent tests.

Final response:

Explain the root cause, changed files, tests run, and any remaining uncertainty.
