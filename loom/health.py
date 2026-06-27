"""Minimal unauthenticated probes for container and load-balancer health."""

import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _response(status: str, *, http_status: int = 200) -> JsonResponse:
    response = JsonResponse({"status": status}, status=http_status)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def liveness(_request):
    """Confirm that the Django process can serve requests."""
    return _response("ok")


@require_GET
def readiness(_request):
    """Confirm that required infrastructure is available."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Readiness probe could not reach the database")
        return _response("unavailable", http_status=503)
    return _response("ok")
