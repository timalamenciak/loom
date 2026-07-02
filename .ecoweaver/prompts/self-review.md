# Self-Review Prompt Template

Before finalizing, review your own work.

Check:

- Did you run `ruff check --fix .` and is it clean?
- Did you run `black .` and is formatting correct?
- Did you run `mypy .` (if configured) and are type errors resolved?
- Did you run `bandit -r src/` (if configured) and are HIGH/MEDIUM findings resolved?
- Did you run `python manage.py check` (Django) and did it pass?
- Does the implementation satisfy the objective?
- Is the change minimal?
- Did you introduce unnecessary abstractions?
- Did you preserve backward compatibility?
- Did you preserve provenance?
- Did you avoid inventing ontology terms?
- Are generated files handled correctly?
- Are tests meaningful and passing?
- Are docs updated if behavior changed?
- Are security constraints preserved (input validation, auth, no secrets in source)?
- Are accessibility constraints met for any UI changes (labels, keyboard nav)?
- Are there remaining risks or uncertainty?

If you find a problem, fix it before responding.

Final response format:

- Changed files
- Linting: ruff / black / mypy / bandit / manage.py check — results
- Verification run
- Result
- Remaining risks
