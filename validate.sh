#!/usr/bin/env bash
# validate.sh — loom. Mirrors .github/workflows/ci.yml so local == CI.
# Run directly, from CI, and from each agent's turn-end hook.
#
# Blocking checks must pass (exit non-zero on failure). Advisory checks
# (pip-audit, mypy) only warn — matching `continue-on-error: true` in CI.
#
# Prereq: a running Postgres reachable with the creds below (Django migration
# and test steps connect to it). Quick start:
#   docker run --rm -d -p 5432:5432 \
#     -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom postgres:16

set -uo pipefail

# --- env (matches CI; override by exporting before running) ------------------
export SECRET_KEY="${SECRET_KEY:-ci-test-key}"
export DB_HOST="${DB_HOST:-localhost}"
export DB_NAME="${DB_NAME:-loom}"
export DB_USER="${DB_USER:-loom}"
export DB_PASSWORD="${DB_PASSWORD:-loom}"
# -----------------------------------------------------------------------------

fail=0
run () {  # run "label" cmd...   -> BLOCKING
  local label="$1"; shift
  if "$@" >/tmp/v_out 2>&1; then
    echo "✓ ${label}"
  else
    echo "✗ ${label}"; sed 's/^/    /' /tmp/v_out; fail=1
  fi
}
advisory () {  # advisory "label" cmd...   -> WARN ONLY (mirrors continue-on-error)
  local label="$1"; shift
  if "$@" >/tmp/v_out 2>&1; then
    echo "✓ ${label}"
  else
    echo "⚠ ${label} (advisory — not blocking)"; sed 's/^/    /' /tmp/v_out
  fi
}

echo "── loom validate.sh (mirrors ci.yml) ───────────────────────"

# Preflight: Postgres must be reachable (migration + test steps need it)
if command -v pg_isready >/dev/null 2>&1; then
  if ! pg_isready -h "$DB_HOST" -p 5432 >/dev/null 2>&1; then
    echo "✗ Postgres not reachable at ${DB_HOST}:5432 — start it before running:"
    echo "    docker run --rm -d -p 5432:5432 \\"
    echo "      -e POSTGRES_USER=loom -e POSTGRES_PASSWORD=loom -e POSTGRES_DB=loom postgres:16"
    fail=1
  fi
fi

# 1. Dependency vulnerability scan (advisory)
if command -v pip-audit >/dev/null 2>&1; then
  advisory "pip-audit" pip-audit
else
  echo "⚠ pip-audit (advisory — not installed locally, skipped)"
fi

# 2. Lint
run "ruff check" ruff check .

# 3. Format check (black — NOT ruff format)
run "black --check" black --check .

# 4. Migration drift
run "migration drift" python manage.py makemigrations --check --dry-run

# 5. Production deployment checks (own long SECRET_KEY, own settings + env)
run "deploy checks" env \
  SECRET_KEY="ci-test-key-that-is-long-enough-for-django-deploy-checks-123456" \
  ALLOWED_HOSTS="localhost" \
  SECURE_HSTS_PRELOAD="True" \
  python manage.py check --deploy --fail-level WARNING --settings=loom.settings.prod

# 6. Type check (advisory)
if command -v mypy >/dev/null 2>&1; then
  advisory "mypy" mypy apps/ loom/ --ignore-missing-imports
else
  echo "⚠ mypy (advisory — not installed locally, skipped)"
fi

# 7. Tests + coverage gate (85%). Drops the xml report (that's for Codecov only).
run "pytest (cov>=85)" pytest --cov=apps --cov=loom \
  --cov-report=term-missing --cov-fail-under=85

echo "────────────────────────────────────────────────────────────"
if [ "$fail" -ne 0 ]; then
  echo "RESULT: FAIL — fix the ✗ items above, then re-run. Do not hand back red."
  exit 1
fi
echo "RESULT: PASS"
