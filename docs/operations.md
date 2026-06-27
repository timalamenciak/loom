# Operating Loom

This runbook covers the minimum production checks, backups, restores, and
upgrades expected for a self-hosted Loom deployment. Test every command against
a non-production copy before relying on it.

## Production configuration

Run Loom with `DJANGO_SETTINGS_MODULE=loom.settings.prod`. Production startup
requires `SECRET_KEY` and `ALLOWED_HOSTS`; set `CSRF_TRUSTED_ORIGINS` when Loom
is served from an HTTPS origin behind a reverse proxy. Use unique database
credentials and keep PostgreSQL and uploaded media on persistent storage.

Before starting a release:

```bash
python manage.py check --deploy --fail-level WARNING --settings=loom.settings.prod
python manage.py migrate --check
python manage.py collectstatic --noinput
```

The reverse proxy must set `X-Forwarded-Proto` accurately and terminate TLS.
Do not expose the Django development server or PostgreSQL port publicly.
Enable `SECURE_HSTS_PRELOAD` only after every subdomain is permanently HTTPS
and the organization has reviewed the browser preload-list requirements.

## Health probes

- `GET /health/live/` confirms the Django process is responding.
- `GET /health/ready/` confirms Django can query PostgreSQL.

Both endpoints return a small JSON response and disable caching. Readiness
returns HTTP 503 when the database is unavailable. They intentionally do not
expose version, configuration, or database details.

## Backup set

A recoverable backup contains all of the following from the same deployment:

1. A PostgreSQL custom-format dump.
2. The complete media directory containing uploaded PDFs.
3. The deployed Git revision and environment/configuration manifest, excluding
   secret values.

Example database backup from the Compose deployment:

```bash
docker compose exec -T db sh -c \
  'pg_dump --format=custom --no-owner --file=/tmp/loom.dump \
  --username="$POSTGRES_USER" "$POSTGRES_DB"'
docker compose cp db:/tmp/loom.dump ./loom.dump
```

Archive the media volume or bind-mounted media directory separately, then
record SHA-256 checksums for both artifacts. Encrypt backups at rest, restrict
access, retain more than one generation, and copy at least one generation off
the application host. A scheduler outside Loom should perform this nightly and
alert on failure.

## Restore drill

Restore into a fresh, isolated deployment—not over a running production
database:

```bash
docker compose cp ./loom.dump db:/tmp/loom.dump
docker compose exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner \
  --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" /tmp/loom.dump'
python manage.py migrate
python manage.py check --deploy --settings=loom.settings.prod
```

Restore the matching media archive, then verify that `/health/ready/` succeeds,
an uploaded PDF opens, a pinned schema loads, and a representative graph
validates and exports. Perform and document a restore drill before the first
Evidence Jam and at least quarterly thereafter.

## Upgrades and rollback

1. Back up PostgreSQL and media.
2. Record the current image tag or Git revision.
3. Review `CHANGELOG.md`, especially data migrations and configuration changes.
4. Deploy the new revision and run migrations once.
5. Verify readiness, login, document access, annotation save, and validated
   export.

Application rollback is safe only when the previous release understands the
new database schema. Prefer a forward fix after irreversible migrations; if a
database rollback is required, restore the matching database and media backup
as a pair.
