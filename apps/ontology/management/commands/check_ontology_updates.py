import sys
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand

from apps.ontology.models import OntologyRelease

_TIMEOUT = 10


class Command(BaseCommand):
    help = (
        "HEAD-check every ready OntologyRelease with an upstream_url against its "
        "stored ETag/Last-Modified, flagging update_available on any that changed."
    )

    def handle(self, *args, **options):
        releases = OntologyRelease.objects.filter(
            upstream_url__isnull=False, status=OntologyRelease.STATUS_READY
        )

        any_updates = False
        for release in releases:
            request = urllib.request.Request(release.upstream_url, method="HEAD")
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                    headers = response.headers
            except urllib.error.URLError as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"  {release.name} ({release.prefix}): could not reach "
                        f"{release.upstream_url} — {exc}"
                    )
                )
                continue

            current = headers.get("ETag") or headers.get("Last-Modified") or ""
            if current and current != release.source_etag:
                release.update_available = True
                release.save(update_fields=["update_available"])
                any_updates = True
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {release.name} ({release.prefix}): update available "
                        f"({release.source_etag or '(none)'!r} -> {current!r})"
                    )
                )
            else:
                self.stdout.write(f"  {release.name} ({release.prefix}): up to date")

        sys.exit(1 if any_updates else 0)
