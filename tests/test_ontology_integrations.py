"""Tests for ontology loading and Wikidata's failure-tolerant boundaries."""

import hashlib
import io
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import reverse

from apps.ontology import adhoc, loaders, wikidata_search
from apps.ontology.models import (
    OntologyLoadRequest,
    OntologyRelease,
    OntologySnapshot,
    OntologyTerm,
)
from apps.ontology.project_service import (
    compose_snapshot,
    process_load_request,
    request_project_ontologies,
)
from apps.projects.models import Project, ProjectMembership

MINI_OBO = b"""\
format-version: 1.2
ontology: test

[Term]
id: TEST:1
name: first term
def: "A definition." []
synonym: "one" EXACT []

[Term]
id: OTHER:2
name: filtered term
"""


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


@pytest.fixture
def project(db):
    user = get_user_model().objects.create_user("ontology-owner")
    return Project.objects.create(name="Ontology project", created_by=user)


def test_loader_config_helpers_and_local_source(tmp_path):
    config = tmp_path / "ontologies.yaml"
    config.write_text(
        "ontologies:\n"
        "  - name: test\n"
        "    prefix: TEST\n"
        "  - name: other\n"
        "    prefix: OTHER\n"
        "preload: [test]\n",
        encoding="utf-8",
    )
    source = tmp_path / "source.obo"
    source.write_bytes(MINI_OBO)

    with patch.object(loaders, "_CONFIG_PATH", config):
        assert loaders.ontology_config("test")["prefix"] == "TEST"
        assert loaders.ontology_config("missing") is None
        assert len(loaders.ontology_entries()) == 2
        assert loaders.list_ontology_names() == ["test", "other"]
        assert loaders.preload_names() == ["test"]
    assert loaders._read_source(str(source)) == MINI_OBO


def test_loader_reads_network_source():
    with patch("urllib.request.urlopen", return_value=Response(b"remote")) as opened:
        assert loaders._read_source("https://example.org/source.obo") == b"remote"
    assert opened.call_args.kwargs["timeout"] == 120


def test_get_or_create_active_snapshot_is_idempotent(db):
    first = loaders.get_or_create_active_snapshot("created")
    second = loaders.get_or_create_active_snapshot("ignored")
    assert first == second
    assert first.is_active


def test_load_release_parses_terms_reuses_digest_and_records_failure(db):
    config = {"name": "test", "prefix": "TEST", "url": "unused"}
    output = io.StringIO()
    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "_read_source", return_value=MINI_OBO),
    ):
        release, count = loaders.load_ontology_release("test", stdout=output)
        same, same_count = loaders.load_ontology_release("test")
    assert count == same_count == 1
    assert same == release
    assert release.status == OntologyRelease.STATUS_READY
    assert release.terms.get().synonyms == ["one"]
    assert "Fetching test" in output.getvalue()

    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "_read_source", return_value=b"different"),
        patch("pronto.Ontology", side_effect=ValueError("bad ontology")),
    ):
        with pytest.raises(ValueError, match="bad ontology"):
            loaders.load_ontology_release("test")
    failed = OntologyRelease.objects.get(
        source_sha256=hashlib.sha256(b"different").hexdigest()
    )
    assert failed.status == OntologyRelease.STATUS_FAILED
    assert failed.error == "bad ontology"


@pytest.mark.parametrize("config", [None, {"name": "test", "prefix": "TEST"}])
def test_load_release_rejects_missing_configuration(db, config):
    with patch.object(loaders, "ontology_config", return_value=config):
        with pytest.raises(ValueError):
            loaders.load_ontology_release("test")


def test_load_ontology_builds_successor_for_pinned_snapshot(db):
    old_release = OntologyRelease.objects.create(
        name="old",
        prefix="OLD",
        source_url="old",
        source_sha256="a" * 64,
        status=OntologyRelease.STATUS_READY,
    )
    new_release = OntologyRelease.objects.create(
        name="test",
        prefix="TEST",
        source_url="new",
        source_sha256="b" * 64,
        status=OntologyRelease.STATUS_READY,
        term_count=4,
    )
    snapshot = OntologySnapshot.objects.create(
        name="pinned", source_versions={"OLD": {}}, is_active=True
    )
    snapshot.releases.add(old_release)
    config = {"name": "test", "prefix": "TEST", "url": "source.obo"}

    with (
        patch.object(loaders, "ontology_config", return_value=config),
        patch.object(loaders, "load_ontology_release", return_value=(new_release, 4)),
    ):
        successor, count = loaders.load_ontology("test", snapshot=snapshot)

    assert count == 4
    assert successor != snapshot
    assert set(successor.releases.all()) == {old_release, new_release}
    assert successor.source_versions["TEST"]["sha256"] == "b" * 64
    assert successor.manifest_sha256


@pytest.mark.parametrize("config", [None, {"name": "test", "prefix": "TEST"}])
def test_load_ontology_rejects_missing_configuration(db, config):
    with patch.object(loaders, "ontology_config", return_value=config):
        with pytest.raises(ValueError):
            loaders.load_ontology("test")


def test_wikidata_search_cache_hit_and_stale_cleanup():
    wikidata_search._cache.clear()
    now = 1000.0
    wikidata_search._cache[("stale", None, 10)] = (0.0, [])
    with (
        patch.object(wikidata_search.time, "monotonic", return_value=now),
        patch.object(
            wikidata_search,
            "_search_uncached",
            return_value=[{"curie": "WD:Q1"}],
        ) as uncached,
    ):
        first = wikidata_search.search("Oak")
        second = wikidata_search.search("OAK")
    assert first == second == [{"curie": "WD:Q1"}]
    uncached.assert_called_once()
    assert ("stale", None, 10) not in wikidata_search._cache


def test_wikidata_uncached_filters_and_limits_candidates():
    candidates = [
        {"qid": "Q1", "label": "one"},
        {"qid": "Q2", "label": "two", "description": "second"},
        {"qid": "Q3", "label": "three"},
    ]
    with (
        patch.object(wikidata_search, "_wbsearch", return_value=candidates),
        patch.object(wikidata_search, "_sparql_filter", return_value={"Q2", "Q3"}),
    ):
        assert wikidata_search._search_uncached("q", None, 1) == [
            {"curie": "WD:Q2", "label": "two", "description": "second"}
        ]
    with patch.object(wikidata_search, "_wbsearch", return_value=[]):
        assert wikidata_search._search_uncached("q", None, 10) == []


def test_wbsearch_parses_results_and_fails_closed():
    payload = json.dumps(
        {
            "search": [
                {"id": "Q1", "label": "Oak", "description": "tree"},
                {"id": "P2", "label": "not an item"},
                {"id": "Q3"},
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=Response(payload)) as opened:
        results = wikidata_search._wbsearch("oak", 5)
    assert results == [
        {"qid": "Q1", "label": "Oak", "description": "tree"},
        {"qid": "Q3", "label": "Q3", "description": ""},
    ]
    assert "wbsearchentities" in opened.call_args.args[0].full_url

    for error in (URLError("offline"), ValueError("bad json")):
        with patch("urllib.request.urlopen", side_effect=error):
            assert wikidata_search._wbsearch("oak", 5) == []


def test_sparql_filter_builds_queries_parses_results_and_fails_closed():
    payload = json.dumps(
        {
            "results": {
                "bindings": [
                    {"item": {"value": "http://www.wikidata.org/entity/Q1"}},
                    {"item": {"value": "not-an-entity"}},
                ]
            }
        }
    ).encode()
    assert wikidata_search._sparql_filter([], None) == set()
    with patch("urllib.request.urlopen", return_value=Response(payload)) as opened:
        assert wikidata_search._sparql_filter(["Q1"], "Q16521") == {"Q1"}
    url = opened.call_args.args[0].full_url
    assert "P171%2B" in url  # wdt:P171+ (transitive taxon hierarchy)
    assert "P279" in url  # P31/P279* branch for metaclass roots like Q16521

    with patch("urllib.request.urlopen", return_value=Response(payload)):
        assert wikidata_search._sparql_filter(["Q1"], None) == {"Q1"}
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        assert wikidata_search._sparql_filter(["Q1"], None) == set()


def test_adhoc_term_creation_uses_authority_hint_existing_and_invalid(project):
    assert adhoc.get_or_create_adhoc_wikidata_term(project, "ENVO:1") is None

    with patch.object(adhoc, "_wbgetentities", return_value=("Authoritative", "Def")):
        term = adhoc.get_or_create_adhoc_wikidata_term(
            project, "WD:Q1", hint_label="Untrusted"
        )
    assert term.label == "Authoritative"
    term.release.refresh_from_db()
    assert term.release.term_count == 1
    assert term.release.source_sha256 != hashlib.sha256(b"").hexdigest()

    with patch.object(adhoc, "_wbgetentities") as network:
        assert adhoc.get_or_create_adhoc_wikidata_term(project, "WD:Q1") == term
    network.assert_not_called()

    with patch.object(adhoc, "_wbgetentities", return_value=("", "")):
        hinted = adhoc.get_or_create_adhoc_wikidata_term(
            project,
            "WD:Q2",
            hint_label="Hint",
            hint_definition="Hint definition",
        )
        assert hinted.label == "Hint"
        assert hinted.definition == "Hint definition"
        assert adhoc.get_or_create_adhoc_wikidata_term(project, "WD:Q3") is None


def test_adhoc_scanner_handles_nested_dicts_and_lists(project):
    data = {
        "entity": "WD:Q1",
        "nested": {"term": "WD:Q2"},
        "items": ["WD:Q3", {"term": "WD:Q4"}, "ENVO:1"],
    }
    post = QueryDict(mutable=True)
    post.update(
        {
            "entity_wd_label": "one",
            "nested__term_wd_label": "two",
            "items_wd_label": "three",
            "items__1__term_wd_label": "four",
        }
    )
    with patch.object(adhoc, "get_or_create_adhoc_wikidata_term") as create:
        adhoc.resolve_wd_curies_in_data(project, data, post)
    assert [call.args[1] for call in create.call_args_list] == [
        "WD:Q1",
        "WD:Q2",
        "WD:Q3",
        "WD:Q4",
    ]


def test_adhoc_release_hash_is_deterministic(project):
    release = adhoc._get_or_create_adhoc_release(project)
    OntologyTerm.objects.create(
        release=release, prefix="WD", curie="WD:Q2", label="two"
    )
    OntologyTerm.objects.create(
        release=release, prefix="WD", curie="WD:Q1", label="one"
    )
    adhoc._update_release_hash(release)
    release.refresh_from_db()
    expected = hashlib.sha256(b"WD:Q1\tone\nWD:Q2\ttwo").hexdigest()
    assert release.source_sha256 == expected
    assert release.term_count == 2


def test_wbgetentities_success_missing_and_failure():
    payload = json.dumps(
        {
            "entities": {
                "Q1": {
                    "labels": {"en": {"value": "Oak"}},
                    "descriptions": {"en": {"value": "tree"}},
                }
            }
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=Response(payload)):
        assert adhoc._wbgetentities("Q1") == ("Oak", "tree")

    missing = json.dumps({"entities": {"Q1": {"missing": ""}}}).encode()
    with patch("urllib.request.urlopen", return_value=Response(missing)):
        assert adhoc._wbgetentities("Q1") == ("", "")
    with patch("urllib.request.urlopen", side_effect=URLError("offline")):
        assert adhoc._wbgetentities("Q1") == ("", "")


def _release(name, prefix, digest):
    return OntologyRelease.objects.create(
        name=name,
        prefix=prefix,
        source_url=f"https://example.org/{name}.obo",
        source_sha256=digest,
        status=OntologyRelease.STATUS_READY,
        term_count=3,
    )


def test_compose_snapshot_rejects_missing_reuses_and_records_manifest(db):
    with pytest.raises(ValueError, match="not loaded: missing"):
        compose_snapshot(["missing"])

    envo = _release("envo", "ENVO", "a" * 64)
    pato = _release("pato", "PATO", "b" * 64)
    first = compose_snapshot(["pato", "envo", "envo"])
    second = compose_snapshot(["envo", "pato"])
    assert first == second
    assert set(first.releases.all()) == {envo, pato}
    assert first.source_versions["ENVO"]["term_count"] == 3


def test_project_ontology_request_validates_supersedes_and_completes(project):
    with patch(
        "apps.ontology.project_service.list_ontology_names", return_value=["envo"]
    ):
        with pytest.raises(ValueError, match="Unknown ontologies"):
            request_project_ontologies(project, project.created_by, ["unknown"])

        older = OntologyLoadRequest.objects.create(
            project=project,
            requested_by=project.created_by,
            ontology_names=["envo"],
        )
        request = request_project_ontologies(
            project, project.created_by, ["envo", "envo"]
        )
    older.refresh_from_db()
    assert older.status == OntologyLoadRequest.STATUS_FAILED
    assert request.status == OntologyLoadRequest.STATUS_PENDING

    _release("envo", "ENVO", "c" * 64)
    with patch(
        "apps.ontology.project_service.list_ontology_names", return_value=["envo"]
    ):
        ready = request_project_ontologies(project, project.created_by, ["envo"])
    assert ready.status == OntologyLoadRequest.STATUS_COMPLETE
    project.refresh_from_db()
    assert project.ontology_snapshot is not None


def test_process_load_request_download_failure_and_terminal_noop(project):
    request = OntologyLoadRequest.objects.create(
        project=project,
        requested_by=project.created_by,
        ontology_names=["missing"],
    )
    failed = process_load_request(request, allow_download=False)
    assert failed.status == OntologyLoadRequest.STATUS_FAILED
    assert "has not been loaded" in failed.error

    failed.status = OntologyLoadRequest.STATUS_COMPLETE
    failed.save(update_fields=["status"])
    assert process_load_request(failed).status == OntologyLoadRequest.STATUS_COMPLETE


def test_merge_wikidata_deduplicates_and_fails_closed():
    from apps.ontology.views import _merge_wikidata

    request = RequestFactory().get(
        "/ontology/search/", {"wikidata_live": "1", "root_qid": "Q1"}
    )
    local = [{"curie": "WD:Q1", "label": "local"}]
    with patch(
        "apps.ontology.views.wikidata_search",
        return_value=[
            {"curie": "WD:Q1", "label": "duplicate"},
            {"curie": "WD:Q2", "label": "new", "description": "desc"},
        ],
    ):
        results = _merge_wikidata(request, local, "term", 5)
    assert [result["curie"] for result in results] == ["WD:Q1", "WD:Q2"]
    assert results[-1]["source"] == "wikidata"

    with patch("apps.ontology.views.wikidata_search", side_effect=RuntimeError):
        assert _merge_wikidata(request, local, "term", 5) == local
    request = RequestFactory().get("/ontology/search/")
    assert _merge_wikidata(request, local, "term", 5) == local


def test_project_search_falls_back_to_active_snapshot(client, project):
    """ProjectOntologySearchView must use the active snapshot when the project
    has no snapshot pinned, so annotators see results without manual snapshot
    configuration."""
    user = project.created_by
    ProjectMembership.objects.create(
        project=project, user=user, role=ProjectMembership.ROLE_ADMIN
    )
    client.force_login(user)

    # Build an active snapshot with a term
    release = OntologyRelease.objects.create(
        name="test",
        prefix="TEST",
        source_url="https://example.org/test.obo",
        source_sha256="a" * 64,
        status=OntologyRelease.STATUS_READY,
        term_count=1,
    )
    snapshot = OntologySnapshot.objects.create(is_active=True)
    snapshot.releases.add(release)
    OntologyTerm.objects.create(
        release=release,
        curie="TEST:999",
        label="fallback term",
        prefix="TEST",
        obsolete=False,
    )

    # Project intentionally has no ontology_snapshot pinned.
    assert project.ontology_snapshot is None

    url = reverse("project-ontology-search", args=[project.pk])
    response = client.get(url, {"q": "fallback"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert any(
        r["curie"] == "TEST:999" for r in results
    ), "Expected fallback to active snapshot to surface TEST:999"


def test_ontology_search_live_and_project_permissions(client, project):
    ProjectMembership.objects.create(
        project=project,
        user=project.created_by,
        role=ProjectMembership.ROLE_ADMIN,
    )
    client.force_login(project.created_by)
    with patch(
        "apps.ontology.views.wikidata_search",
        return_value=[{"curie": "WD:Q1", "label": "Oak"}],
    ):
        response = client.get(
            reverse("ontology-search"),
            {"q": "oak", "wikidata_live": "1"},
        )
    assert response.json()["results"][0]["source"] == "wikidata"

    project_url = reverse("project-ontology-search", args=[project.pk])
    assert client.get(project_url, {"q": "x"}).json() == {"results": []}
    assert client.get(project_url, {"q": "oak", "limit": "bad"}).status_code == 200

    stranger = get_user_model().objects.create_user("ontology-stranger")
    client.force_login(stranger)
    assert client.get(project_url, {"q": "oak"}).status_code == 403
