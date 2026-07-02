# Performance Prompt Template

Objective:

Improve performance of:

[workflow/query/view/export/import]

Observed issue:

[slow endpoint, memory use, N+1 query, large schema generation, etc.]

Relevant context:

- Read `.ecoweaver/architecture.md`.
- Read `.ecoweaver/testing.md`.
- Inspect: [files]

Constraints:

- Measure or reason from evidence before optimizing.
- Do not reduce correctness, validation, or provenance.
- Prefer simple, explainable optimizations.
- Avoid caching unless invalidation is clear.

Required workflow:

1. Identify the bottleneck or likely bottleneck.
2. Explain the proposed optimization.
3. Implement the smallest safe change.
4. Add tests or checks for correctness.
5. Report before/after evidence if available.

Final response:

Summarize performance rationale, changed files, verification, and tradeoffs.
