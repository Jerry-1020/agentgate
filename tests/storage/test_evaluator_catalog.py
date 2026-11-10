"""Run the same bulk catalog contract against SQLite and opt-in real MySQL."""

from test_evaluator_catalog_performance import create, team

from agentgate.application.evaluator_management import build_default_evaluator_management


def test_bulk_catalog_contract(repository):
    management = build_default_evaluator_management(repository)
    with team("team-a"):
        eid = create(management, versions=3)
        management.create_draft(eid, based_on_version="3")
    versions, drafts = repository.get_evaluator_catalog_definitions([eid], user_team_id="team-a")
    assert versions[eid].version == "3"
    assert drafts[eid].evaluator_id == eid
    assert repository.get_evaluator_catalog_definitions([eid], user_team_id="team-b") == ({}, {})
