"""
Phase 6 tests: Authorization policies for annotation operations.

Verify the policies module enforces permission checks for annotator-owned
graph and span operations. Tests are pure Python - no database required.
"""

from unittest.mock import Mock

import pytest
from django.core.exceptions import PermissionDenied

from apps.annotation.policies import (
    EDITABLE_ASSIGNMENT_STATUSES,
    assignment_is_editable,
    require_annotation_assignment,
    require_editable_assignment,
)
from apps.projects.models import Assignment, Document, Project, ProjectMembership

# ---------------------------------------------------------------------------
# Fixtures
# ------ ------ -----


@pytest.fixture
def mock_project():
    project = Mock()
    project.pk = 1
    return project


@pytest.fixture
def mock_document(mock_project):
    document = Mock()
    document.pk = 1
    document.project = mock_project
    return document


@pytest.fixture
def mock_user():
    user = Mock()
    user.pk = 1
    user.username = "testuser"
    return user


@pytest.fixture
def mock_assignment(mock_document, mock_user):
    assignment = Mock()
    assignment.pk = 1
    assignment.document = mock_document
    assignment.project = mock_document.project
    assignment.annotator = mock_user
    return assignment


# ---------------------------------------------------------------------------
# require_annotation_assignment tests
# ------------------- ------ ---------------------- ---------------


class TestRequireAnnotationAssignment:
    """Verify require_annotation_assignment checks permissions."""

    def test_returns_assignment_when_member_and_has_assignment(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="testuser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        ProjectMembership.objects.create(project=project, user=user)

        assignment = Assignment.objects.create(
            document=document,
            project=project,
            annotator=user,
            assigned_by=admin,
            status=Assignment.STATUS_ASSIGNED,
        )

        result = require_annotation_assignment(document, user)

        assert result == assignment

    def test_denies_when_not_project_member(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="otheruser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        with pytest.raises(PermissionDenied) as exc_info:
            require_annotation_assignment(document, user)

        assert "not a member" in str(exc_info.value).lower()

    def test_denies_when_no_assignment(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="testuser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        ProjectMembership.objects.create(project=project, user=user)

        with pytest.raises(PermissionDenied) as exc_info:
            require_annotation_assignment(document, user)

        assert "not assigned" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# assignment_is_editable tests
# ------------------- ------ ---------------------- ---------------


class TestAssignmentIsEditable:
    """Verify assignment_is_editable checks status."""

    def test_status_assigned_is_editable(self):
        assignment = Mock()
        assignment.status = "assigned"
        assert assignment_is_editable(assignment) is True

    def test_status_in_progress_is_editable(self):
        assignment = Mock()
        assignment.status = "in_progress"
        assert assignment_is_editable(assignment) is True

    def test_status_returned_is_editable(self):
        assignment = Mock()
        assignment.status = "returned"
        assert assignment_is_editable(assignment) is True

    def test_status_submitted_is_not_editable(self):
        assignment = Mock()
        assignment.status = "submitted"
        assert assignment_is_editable(assignment) is False

    def test_status_reviewed_is_not_editable(self):
        assignment = Mock()
        assignment.status = "reviewed"
        assert assignment_is_editable(assignment) is False

    def test_status_gold_is_not_editable(self):
        assignment = Mock()
        assignment.status = "gold"
        assert assignment_is_editable(assignment) is False

    def test_unknown_status_is_not_editable(self):
        assignment = Mock()
        assignment.status = "unknown"
        assert assignment_is_editable(assignment) is False


# ---------------------------------------------------------------------------
# require_editable_assignment tests
# ------------------- ------ ---------------------- ---------------


class TestRequireEditableAssignment:
    """Verify require_editable_assignment enforces editability."""

    def test_returns_editable_assignment(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="testuser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        ProjectMembership.objects.create(project=project, user=user)

        assignment = Assignment.objects.create(
            document=document,
            project=project,
            annotator=user,
            assigned_by=admin,
            status=Assignment.STATUS_IN_PROGRESS,  # Editable
        )

        result = require_editable_assignment(document, user)

        assert result == assignment

    def test_denies_when_not_member(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="otheruser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        with pytest.raises(PermissionDenied) as exc_info:
            require_editable_assignment(document, user)

        assert "not a member" in str(exc_info.value).lower()

    def test_denies_when_not_assigned(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="testuser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        ProjectMembership.objects.create(project=project, user=user)

        with pytest.raises(PermissionDenied) as exc_info:
            require_editable_assignment(document, user)

        assert "not assigned" in str(exc_info.value).lower()

    def test_denies_when_not_editable_status(self, db):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        admin = User.objects.create(username="admin")
        project = Project.objects.create(name="Test Project", created_by=admin)
        user = User.objects.create(username="testuser")
        document = Document.objects.create(
            project=project,
            title="Test Doc",
            source=Document.SOURCE_RIS_IMPORT,
            canonical_text="Abstract",
        )

        ProjectMembership.objects.create(project=project, user=user)

        Assignment.objects.create(
            document=document,
            project=project,
            annotator=user,
            assigned_by=admin,
            status=Assignment.STATUS_SUBMITTED,  # Not editable
        )

        with pytest.raises(PermissionDenied) as exc_info:
            require_editable_assignment(document, user)

        assert "read-only" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# EDITABLE_ASSIGNMENT_STATUSES tests
# ------------------- ------ ---------------------- ---------------


class TestEditableAssignmentStatuses:
    """Verify the set of editable statuses is correct."""

    def test_expected_statuses(self):
        expected = {
            "assigned",
            "in_progress",
            "returned",
        }
        assert EDITABLE_ASSIGNMENT_STATUSES == expected

    def test_not_editable_statuses(self):
        not_editable = {
            "submitted",
            "reviewed",
            "gold",
        }
        for status in not_editable:
            assert status not in EDITABLE_ASSIGNMENT_STATUSES
