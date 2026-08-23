"""Template context processor exposing pending schema/ontology updates to
every staff-facing page, so the notification banner doesn't need each view to
pass it in explicitly.
"""

from .models import UpdateCheckRecord


def pending_updates(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return {}

    updates = UpdateCheckRecord.objects.filter(is_update_available=True)
    session = request.session
    updates = [u for u in updates if not session.get(u.dismiss_session_key())]
    return {"pending_updates": updates}
