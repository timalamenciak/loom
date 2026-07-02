# Lint Skill

Run this skill before finishing any task. Linting is not optional.

## When to use

After every code change, before reporting a task complete. This applies to all EcoWeaver projects regardless of task size.

## Python linting sequence

Run these in order. Fix failures before proceeding; do not suppress them.

```bash
# 1. Lint and auto-fix safe issues (covers flake8, isort, pyupgrade, pep8-naming, and more)
ruff check --fix .

# 2. Format code
black .

# 3. Type check (run if mypy is configured in the project)
mypy .

# 4. Security static analysis (run if bandit is configured)
bandit -r src/

# 5. Django system check (for Django projects)
python manage.py check
```

If `pre-commit` is configured in the repository, run it instead of the individual commands above:

```bash
pre-commit run --all-files
```

## JavaScript / TypeScript linting (if applicable)

```bash
# Lint
eslint .

# Format check
prettier --check .
```

## Handling failures

- Fix all ruff and black failures before finishing. Do not report a task complete with outstanding lint errors.
- For mypy failures: fix type errors in code you changed; do not add `# type: ignore` without a documented reason.
- For bandit findings: treat HIGH and MEDIUM severity findings as blockers; LOW as informational.
- Do not suppress lint rules project-wide without raising it with the user.

## Reporting

Include lint results in the final task summary:

```
Linting:
- ruff check --fix — N issues fixed, 0 remaining
- black — reformatted N files / no changes
- mypy — passed / N errors (listed)
- bandit — N HIGH, N MEDIUM (described if any)
- manage.py check — passed
```

## Guardrails

- Never use `# noqa` or `# type: ignore` to silence a lint rule unless the suppression is justified in a comment.
- Never disable lint rules in `ruff.toml`, `pyproject.toml`, or `.flake8` to make a task pass.
- If a lint tool is not installed, say so explicitly and provide the install command rather than skipping it.
