"""Directory contract, isolation and query-count regression tests."""

from contextlib import contextmanager
from time import perf_counter
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql

from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.evaluators import catalog_router, router
from agentgate.server.user_context import UserInfo, reset_user_info, set_user_info
from agentgate.storage import mysql_schema as schema
from agentgate.storage.mysql import MySQLRepository, _values


@contextmanager
def team(value):
    token = set_user_info(UserInfo(user_team_id=value, user_id="tester", user_name="tester"))
    try:
        yield
    finally:
        reset_user_info(token)


def create(management, name="custom", versions=0):
    identity, _draft = management.create_evaluator(
        name,
        kind="rule",
        dimension="answer",
        metric="final_output_match",
        implementation_id="final_output",
        implementation_version="1",
        config={},
    )
    for version in range(versions):
        if version:
            management.create_draft(identity.id, based_on_version=str(version))
        management.publish_draft(identity.id)
    if versions:
        management.update_evaluator(identity.id, enabled=True)
    return identity.id


@pytest.fixture
def deps(tmp_path):
    return build_dependencies(tmp_path / "catalog.db")


def client_for(deps):
    app = FastAPI()
    app.state.dependencies = deps
    app.include_router(router)
    app.include_router(catalog_router)
    return TestClient(app)


def test_new_and_old_catalog_match_with_drafts_versions_disabled_and_team(deps):
    with team("a"):
        unpublished = create(deps.evaluators)
        published = create(deps.evaluators, "published", 3)
        deps.evaluators.create_draft(published, based_on_version="3")
    with team("b"):
        other = create(deps.evaluators, "other", 1)
    with team("a"), client_for(deps) as client:
        for disabled in (False, True):
            params = {"include_disabled": disabled}
            old = client.get("/api/evaluators", params=params)
            new = client.get("/api/evaluator-catalog", params=params)
            assert new.status_code == 200
            assert new.json() == old.json()
            ids = {x["id"] for x in new.json()}
            assert other not in ids
            assert (unpublished in ids) == disabled
            summary = next(x for x in new.json() if x["id"] == published)
            assert summary["latest_version"] == "3" and summary["has_draft"]
        description = client.get("/openapi.json").json()["paths"]["/api/evaluators"]["get"][
            "description"
        ]
        assert "/api/evaluator-catalog" in description
    with team("b"), client_for(deps) as client:
        assert published not in {x["id"] for x in client.get("/api/evaluator-catalog").json()}


@pytest.mark.parametrize("count", [40, 100])
def test_directory_query_count_and_payload_match(deps, monkeypatch, count):
    for index in range(count):
        create(deps.evaluators, f"entry-{index}", 3)
    statements = []
    original = deps.repository._connect

    @contextmanager
    def observed():
        with original() as db:
            db.set_trace_callback(
                lambda sql: (
                    statements.append(sql) if sql.lstrip().upper().startswith("SELECT") else None
                )
            )
            yield db

    monkeypatch.setattr(deps.repository, "_connect", observed)
    with client_for(deps) as client:
        started = perf_counter()
        old = client.get("/api/evaluators")
        old_ms = (perf_counter() - started) * 1000
        old_queries = len(statements)
        statements.clear()
        started = perf_counter()
        new = client.get("/api/evaluator-catalog")
        new_ms = (perf_counter() - started) * 1000
    assert new.json() == old.json()
    assert len(statements) == 3
    assert old_queries == 1 + 4 * count
    print(
        f"catalog benchmark count={count} old_queries={old_queries} new_queries=3 old_ms={old_ms:.1f} new_ms={new_ms:.1f} bytes={len(new.content)}"
    )


def test_empty_and_multiple_batches(deps):
    assert deps.repository.get_evaluator_catalog_definitions([], user_team_id="") == ({}, {})
    eid = create(deps.evaluators, versions=1)
    versions, drafts = deps.repository.get_evaluator_catalog_definitions(
        [f"missing-{i}" for i in range(400)] + [eid], user_team_id=""
    )
    assert list(versions) == [eid] and not drafts


def test_directory_error_is_logged_and_legacy_remains_usable(deps, monkeypatch, caplog):
    monkeypatch.setattr(
        deps.repository,
        "get_evaluator_catalog_definitions",
        Mock(side_effect=ValueError("invalid persisted definition")),
    )
    with client_for(deps) as client:
        assert client.get("/api/evaluator-catalog").status_code == 422
        assert client.get("/api/evaluators").status_code == 200
    assert "Evaluator catalog query failed" in caplog.text


def test_mysql_bulk_query_compiles_and_validates_rows(deps):
    eid = create(deps.evaluators, versions=2)
    deps.evaluators.create_draft(eid, based_on_version="2")
    version = deps.repository.get_latest_evaluator_version(eid, user_team_id="")
    draft = deps.repository.get_evaluator_draft(eid, user_team_id="")
    repo = object.__new__(MySQLRepository)
    db = Mock()

    @contextmanager
    def transaction():
        yield db

    repo._transaction = transaction

    def response(rows):
        result = Mock()
        result.mappings.return_value.all.return_value = rows
        return result

    db.execute.side_effect = [
        response([_values(schema.evaluator_versions, version)]),
        response([_values(schema.evaluator_drafts, draft)]),
    ]
    versions, drafts = repo.get_evaluator_catalog_definitions([eid], user_team_id="")
    assert versions == {eid: version} and drafts == {eid: draft}
    queries = [
        str(call.args[0].compile(dialect=mysql.dialect())) for call in db.execute.call_args_list
    ]
    assert len(queries) == 2 and "max(" in queries[0].lower() and "GROUP BY" in queries[0]
    assert all("user_team_key" in q for q in queries)
    db.execute.reset_mock()
    assert repo.get_evaluator_catalog_definitions([], user_team_id="") == ({}, {})
    db.execute.assert_not_called()


def test_group_children_and_archived_evaluators_are_not_directory_entries(deps):
    from test_llm_evaluator_groups import RecordingJudge, payload, publish

    from agentgate.application.evaluator_management import build_default_evaluator_management

    deps.evaluators = build_default_evaluator_management(
        deps.repository,
        judge_client=RecordingJudge(),
        judge_model_id="test-model",
        judge_credential_ref="env:TEST_GROUP_KEY",
    )

    with client_for(deps) as client:
        response = client.post("/api/evaluators/llm-groups", json=payload())
        assert response.status_code == 201
        group = publish(client, response.json())
        parent_id = group["evaluator"]["id"]
        for disabled in (False, True):
            params = {"include_disabled": disabled}
            old = client.get("/api/evaluators", params=params).json()
            new = client.get("/api/evaluator-catalog", params=params).json()
            assert old == new
            if any(item["id"] == parent_id for item in new):
                assert next(item for item in new if item["id"] == parent_id)["child_count"] == 2
            child_ids = {child["evaluator"]["id"] for child in group["children"]}
            assert not child_ids.intersection(item["id"] for item in new)
        assert client.delete(f"/api/evaluators/{parent_id}").status_code == 204
        new = client.get("/api/evaluator-catalog?include_disabled=true").json()
        assert parent_id not in {item["id"] for item in new}
        assert new == client.get("/api/evaluators?include_disabled=true").json()
