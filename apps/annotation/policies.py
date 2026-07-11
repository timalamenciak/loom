"""Authorization policy for annotator-owned graph and span operations.

Views should use these helpers instead of treating project membership as write
authorization.  Reviewers and project administrators have their own review
surface; they may annotate a document only when they also have an assignment.
"""

from django.core.exceptions import PermissionDenied

from apps.projects.models import Assignment, ProjectMembership

EDITABLE_ASSIGNMENT_STATUSES = frozenset(
    {
        Assignment.STATUS_ASSIGNED,
        Assignment.STATUS_IN_PROGRESS,
        Assignment.STATUS_RETURNED,
    }
)


def require_annotation_assignment(document, user) -> Assignment:
    """Return the user's assignment for *document* or deny access."""
    if not ProjectMembership.objects.filter(
        project=document.project,
        user=user,
    ).exists():
        raise PermissionDenied("You are not a member of this project.")
    try:
        return Assignment.objects.select_related("graph__schema_version").get(
            document=document,
            project=document.project,
            annotator=user,
        )
    except Assignment.DoesNotExist as exc:
        raise PermissionDenied(
            "This document is not assigned to you for annotation."
        ) from exc


def assignment_is_editable(assignment: Assignment) -> bool:
    """Return whether an annotator may mutate this assignment's graph."""
    return assignment.status in EDITABLE_ASSIGNMENT_STATUSES


def require_editable_assignment(document, user) -> Assignment:
    """Return an editable assignment or deny graph/span mutation."""
    assignment = require_annotation_assignment(document, user)
    if not assignment_is_editable(assignment):
        raise PermissionDenied(
            "Submitted or reviewed annotations are read-only unless returned."
        )
    return assignment
