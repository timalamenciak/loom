"""
Phase 3 tests: canonical-text extraction, span creation, highlight rendering.

Pure-Python tests run without Postgres.
DB tests (TestCreateSpan, TestSetAbstractAsCanonical, etc.) need:
  docker compose up -d db
"""

import pytest

from apps.documents.services import (
    create_span,
    render_highlighted_text,
    set_abstract_as_canonical,
)


# ---------------------------------------------------------------------------
# Pure-Python rendering tests — no DB, no pdfplumber
# ---------------------------------------------------------------------------


class _FakeSpan:
    def __init__(self, pk, start_char, end_char, text=""):
        self.pk = pk
        self.start_char = start_char
        self.end_char = end_char
        self.text = text


class TestRenderHighlightedText:
    def test_empty_text(self):
        assert render_highlighted_text("", []) == ""

    def test_no_spans_escapes_html(self):
        text = "Hello <world> & everyone"
        result = render_highlighted_text(text, [])
        assert "&lt;world&gt;" in result
        assert "&amp;" in result
        assert "<mark" not in result

    def test_single_span_wrapped_in_mark(self):
        text = "The quick brown fox"
        spans = [_FakeSpan(pk=1, start_char=4, end_char=9, text="quick")]
        result = render_highlighted_text(text, spans)
        assert '<mark class="span-highlight"' in result
        assert "quick" in result
        assert result.startswith("The ")

    def test_span_at_start(self):
        text = "Hello world"
        spans = [_FakeSpan(pk=1, start_char=0, end_char=5, text="Hello")]
        result = render_highlighted_text(text, spans)
        assert result.startswith("<mark")

    def test_span_at_end(self):
        text = "Hello world"
        spans = [_FakeSpan(pk=1, start_char=6, end_char=11, text="world")]
        result = render_highlighted_text(text, spans)
        assert result.endswith("</mark>")

    def test_multiple_non_overlapping_spans(self):
        text = "one two three"
        spans = [
            _FakeSpan(pk=1, start_char=0, end_char=3, text="one"),
            _FakeSpan(pk=2, start_char=8, end_char=13, text="three"),
        ]
        result = render_highlighted_text(text, spans)
        assert result.count("<mark") == 2
        assert result.count("</mark>") == 2
        # Text between spans is preserved
        assert " two " in result

    def test_span_text_escaped_in_title(self):
        text = "some text here"
        spans = [_FakeSpan(pk=1, start_char=5, end_char=9, text='te"xt')]
        result = render_highlighted_text(text, spans)
        assert "te&quot;xt" in result or 'te"xt' not in result  # title attr is escaped

    def test_out_of_range_span_skipped(self):
        text = "Hello"
        spans = [_FakeSpan(pk=1, start_char=0, end_char=100, text="x")]
        # end is clamped; should not raise
        result = render_highlighted_text(text, spans)
        assert "Hello" in result

    def test_data_span_pk_in_mark(self):
        text = "test text"
        spans = [_FakeSpan(pk=42, start_char=0, end_char=4, text="test")]
        result = render_highlighted_text(text, spans)
        assert 'data-span-pk="42"' in result


# ---------------------------------------------------------------------------
# DB-backed tests (need Postgres)
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.create_user("reader_test", password="x")


@pytest.fixture
def document(db, user):
    from apps.projects.models import Document, Project
    proj = Project.objects.create(name="Reader Test", created_by=user)
    return Document.objects.create(
        project=proj,
        source=Document.SOURCE_MANUAL,
        title="Test paper about nitrogen",
        abstract="Nitrogen deposition increases plant biomass in temperate grasslands.",
    )


class TestSetAbstractAsCanonical:
    def test_sets_canonical_text_from_abstract(self, document):
        result = set_abstract_as_canonical(document)
        assert result is True
        document.refresh_from_db()
        assert document.canonical_text == document.abstract
        assert document.page_map == []

    def test_returns_false_when_no_abstract(self, document):
        document.abstract = ""
        document.save(update_fields=["abstract"])
        assert set_abstract_as_canonical(document) is False

    def test_abstract_already_set_in_ris_import(self, db, user):
        """RIS import sets canonical_text=abstract for PDF-less records."""
        import io

        from apps.projects.models import Project
        from apps.projects.services import import_ris_file

        proj = Project.objects.create(name="RIS Test", created_by=user)
        ris_content = (
            "TY  - JOUR\n"
            "TI  - Grassland nitrogen study\n"
            "AB  - Nitrogen increases biomass in temperate grasslands.\n"
            "ER  -\n\n"
        )
        created, _ = import_ris_file(proj, io.BytesIO(ris_content.encode()))
        assert len(created) == 1
        doc = created[0]
        assert doc.canonical_text == "Nitrogen increases biomass in temperate grasslands."


class TestCreateSpan:
    def test_creates_span_with_snapped_text(self, document, user):
        document.canonical_text = "The quick brown fox jumps."
        document.save(update_fields=["canonical_text"])

        span = create_span(document, 4, 9, created_by=user)
        assert span.pk is not None
        assert span.text == "quick"
        assert span.start_char == 4
        assert span.end_char == 9
        assert span.document == document
        assert span.created_by == user

    def test_span_text_snapped_accurately(self, document):
        document.canonical_text = "Nitrogen increases plant biomass."
        document.save(update_fields=["canonical_text"])

        span = create_span(document, 9, 18)
        assert span.text == "increases"

    def test_multiple_spans_ordered_by_start(self, document):
        document.canonical_text = "A B C D E F G"
        document.save(update_fields=["canonical_text"])

        create_span(document, 4, 5)  # C
        create_span(document, 0, 1)  # A
        create_span(document, 8, 9)  # E

        from apps.documents.models import TextSpan
        spans = list(TextSpan.objects.filter(document=document))
        assert [s.start_char for s in spans] == [0, 4, 8]

    def test_span_with_empty_canonical_text(self, document):
        document.canonical_text = ""
        document.save(update_fields=["canonical_text"])
        # create_span should not raise even if range is degenerate
        # (validation is the view's job)
        span = create_span(document, 0, 0)
        assert span.text == ""


class TestDocumentReaderView:
    def test_reader_returns_200_for_abstract_doc(self, db, user, document):
        from django.test import Client
        from apps.projects.models import ProjectMembership

        ProjectMembership.objects.create(
            project=document.project,
            user=user,
            role=ProjectMembership.ROLE_ANNOTATOR,
        )

        document.canonical_text = "Nitrogen deposition increases biomass."
        document.save(update_fields=["canonical_text"])

        client = Client()
        client.force_login(user)
        resp = client.get(f"/reader/{document.pk}/")
        assert resp.status_code == 200
        assert b"canonical-text" in resp.content

    def test_reader_403_for_non_member(self, db, user, document):
        from django.test import Client
        other = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
        other_user = other.objects.create_user("outsider", password="x")

        client = Client()
        client.force_login(other_user)
        resp = client.get(f"/reader/{document.pk}/")
        assert resp.status_code == 403

    def test_span_create_persists(self, db, user, document):
        from django.test import Client
        from apps.documents.models import TextSpan
        from apps.projects.models import ProjectMembership

        ProjectMembership.objects.create(
            project=document.project,
            user=user,
            role=ProjectMembership.ROLE_ANNOTATOR,
        )
        document.canonical_text = "The quick brown fox."
        document.save(update_fields=["canonical_text"])

        client = Client()
        client.force_login(user)
        resp = client.post(
            f"/reader/{document.pk}/spans/",
            {"start_char": 4, "end_char": 9},
        )
        assert resp.status_code in (200, 302)
        span = TextSpan.objects.filter(document=document).first()
        assert span is not None
        assert span.text == "quick"
        assert span.start_char == 4
        assert span.end_char == 9
