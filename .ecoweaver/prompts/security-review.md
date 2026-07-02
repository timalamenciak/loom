# Security Review Prompt Template

Objective:

Review the following for security issues:

[describe target: module, endpoint, feature, or full codebase]

Relevant context:

- Read `.ecoweaver/security.md`.
- Read `.ecoweaver/architecture.md`.
- Inspect: [specific files, views, models, serializers]

Constraints:

- Do not weaken validation, authentication, or authorization to simplify any findings.
- Do not add workarounds that trade security for convenience.
- Report findings even if outside the immediate task scope.

Required workflow:

1. Identify all external input paths.
2. Check each input is validated before use.
3. Check secrets management.
4. Check authentication and authorization layers.
5. Check dependency security if changed.
6. Check HTTP security headers and Django deployment settings.

Output:

Separate findings into:

1. Blockers (must fix before release)
2. Important (should fix soon)
3. Minor (low risk, fix when convenient)

For each finding, include the file and line where relevant, the risk, and the recommended fix.
