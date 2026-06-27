# Security policy

Loom handles uploaded documents and research annotations. Please do not include
PDFs, credentials, private annotations, or exploit details in a public issue.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature for this repository. Include
the affected version or commit, deployment assumptions, reproduction steps, and
the likely impact. If private reporting is unavailable, contact a repository
maintainer privately before opening an issue.

Maintainers will acknowledge a complete report within seven days, investigate it,
and coordinate disclosure after a fix or mitigation is available. No response
time is guaranteed for unsupported development snapshots.

## Supported versions

Until Loom reaches 1.0, only the latest tagged release and the current `main`
branch receive security fixes. Deployments should keep Django, PostgreSQL, the
LinkML stack, and the container base image current.

## Deployment responsibilities

Operators must use TLS, a production secret key, non-default database
credentials, restricted media storage, and tested backups. Uploaded PDFs should
be treated as untrusted content. Never expose Django's development server or the
PostgreSQL port to the public internet.
