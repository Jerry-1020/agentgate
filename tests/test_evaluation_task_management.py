from fastapi.testclient import TestClient
from agentgate.server.app import create_app


class Dispatcher:
    def submit(self, run_id):
        pass


def client(path):
    return TestClient(create_app(path, dispatcher=Dispatcher()))


def launch(c, version="loan-agent-v1-risky"):
    response = c.post("/api/evaluations", json={
        "version": version, "dataset_id": "loan-risk-policy", "dataset_version": 1,
        "evaluator_ids": ["final-state"],
    })
    assert response.status_code == 202, response.text
    return response.json()["data"]["run_id"]


def test_single_task_survives_new_app_and_idempotent_save(tmp_path):
    path = tmp_path / "test.db"
    with client(path) as c:
        run_id = launch(c)
        body = {"kind": "single", "run_ids": [run_id]}
        first = c.get("/api/evaluation-tasks/" + run_id).json()["data"]
        assert c.put("/api/evaluation-tasks/" + run_id, json=body).json()["data"] == first
        assert c.put("/api/evaluation-tasks/other", json=body).status_code == 409
    with client(path) as c:
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"] == first
        assert len(c.get("/api/evaluation-tasks").json()["data"]) == 1


def test_unknown_and_wrong_report_rejected(tmp_path):
    with client(tmp_path / "test.db") as c:
        assert c.get("/api/evaluation-tasks/missing").status_code == 404
        assert c.put("/api/evaluation-tasks/x", json={"kind": "single", "run_ids": ["missing"]}).status_code == 404
        run_id = launch(c)
        response = c.put("/api/evaluation-tasks/" + run_id, json={
            "kind": "single", "run_ids": [run_id], "static_report_ids": ["missing"],
        })
        assert response.status_code == 404
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"]["static_report_ids"] == []


def test_ab_launch_and_reversed_association_conflict(tmp_path):
    with client(tmp_path / "test.db") as c:
        response = c.post("/api/run-comparisons", json={
            "baseline_version": "loan-agent-v1-risky", "candidate_version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluators": [{"id": "final-state", "version": "1"}],
        })
        assert response.status_code == 202, response.text
        pair = response.json()["data"]
        ids = [pair["baseline"]["run_id"], pair["candidate"]["run_id"]]
        task = c.get("/api/evaluation-tasks/" + ids[0]).json()["data"]
        assert task["kind"] == "ab"
        assert task["run_ids"] == ids
        assert c.put("/api/evaluation-tasks/" + ids[0], json={"kind": "ab", "run_ids": ids[::-1]}).status_code == 409


def test_same_version_ab_rejected(tmp_path):
    with client(tmp_path / "test.db") as c:
        a, b = launch(c), launch(c)
        response = c.put("/api/evaluation-tasks/" + a, json={"kind": "ab", "run_ids": [a, b]})
        assert response.status_code == 409
        assert "distinct" in response.text


def test_static_report_replacement_preserves_history_and_rejects_wrong_target(tmp_path):
    from agentgate.domain import SkillAnalysisReport
    with client(tmp_path / "test.db") as c:
        risky = launch(c)
        fixed = launch(c, "loan-agent-v2-fixed")
        repo = c.app.state.dependencies.repository
        reports = []
        for run_id in (risky, risky, fixed):
            target = repo.get_run(run_id).manifest.target
            report = SkillAnalysisReport(target_ref=target.ref, target_descriptor_sha256=target.descriptor_sha256,
                                         analyzer_version="test", status="completed")
            repo.save_skill_analysis_report(report)
            reports.append(report)
        for report in reports[:2]:
            response = c.put("/api/evaluation-tasks/"+risky, json={"kind":"single", "run_ids":[risky], "static_report_ids":[report.id]})
            assert response.status_code == 200, response.text
        assert c.get("/api/evaluation-tasks/"+risky).json()["data"]["static_report_ids"] == [reports[1].id]
        assert repo.get_skill_analysis_report(reports[0].id) == reports[0]
        assert c.put("/api/evaluation-tasks/"+risky, json={"kind":"single", "run_ids":[risky], "static_report_ids":[reports[2].id]}).status_code == 409
