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


def test_delete_completed_task_removes_evidence_and_preserves_other_tasks(tmp_path):
    from agentgate.domain import OptimizationReport, RoutingConfusionMatrix

    with client(tmp_path / "delete.db") as c:
        other_id = launch(c)
        dependencies = c.app.state.dependencies
        run = dependencies.execute_demo_run("loan-agent-v1-risky")
        repo = dependencies.repository
        assert c.put("/api/evaluation-tasks/" + run.id, json={
            "kind": "single", "run_ids": [run.id],
        }).status_code == 200
        assert repo.list_traces(run.id)
        assert repo.list_results(run.id)
        report = OptimizationReport(
            run_id=run.id,
            target_ref=run.manifest.target.ref,
            target_content_sha256=run.manifest.target.descriptor_sha256,
            dataset_id=run.manifest.dataset.id,
            dataset_version=1,
            dataset_content_sha256="b" * 64,
            analyzer_version="1",
            failed_result_count=0,
            confusion_matrix=RoutingConfusionMatrix(eligible_count=0),
        )
        repo.save_optimization_report("delete-evidence", report)
        response = c.delete("/api/evaluation-tasks/" + run.id)
        assert response.status_code == 200, response.text
        assert c.get("/api/evaluation-tasks/" + run.id).status_code == 404
        assert repo.get_run(run.id) is None
        assert repo.list_traces(run.id) == []
        assert repo.list_results(run.id) == []
        assert repo.get_optimization_report("delete-evidence") is None
        assert c.get("/api/evaluation-tasks/" + other_id).status_code == 200
        assert repo.get_run(other_id) is not None
        assert c.delete("/api/evaluation-tasks/" + run.id).status_code == 404


def test_delete_ab_task_removes_both_runs(tmp_path):
    with client(tmp_path / "delete-ab.db") as c:
        response = c.post("/api/run-comparisons", json={
            "baseline_version": "loan-agent-v1-risky",
            "candidate_version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy", "dataset_version": 1,
            "evaluators": [{"id": "final-state", "version": "1"}],
        })
        assert response.status_code == 202, response.text
        pair = response.json()["data"]
        ids = [pair["baseline"]["run_id"], pair["candidate"]["run_id"]]
        response = c.delete("/api/evaluation-tasks/" + ids[0])
        assert response.status_code == 200, response.text
        repo = c.app.state.dependencies.repository
        assert all(repo.get_run(run_id) is None for run_id in ids)
        assert c.get("/api/evaluation-tasks").json()["data"] == []


def test_task_name_persists_and_old_tasks_are_named_once(tmp_path):
    from datetime import datetime, UTC
    from agentgate.domain.evaluation_task import EvaluationTask

    path = tmp_path / "names.db"
    with client(path) as c:
        run_id = launch(c)
        repo = c.app.state.dependencies.repository
        # Model and repository retain explicit user names through metadata updates.
        body = {"kind": "single", "run_ids": [run_id], "name": "  自定义回归任务  "}
        response = c.put("/api/evaluation-tasks/" + run_id, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["name"] == "自定义回归任务"
        c.put("/api/evaluation-tasks/" + run_id, json={"kind": "single", "run_ids": [run_id]})
        assert repo.get_evaluation_task(run_id).name == "自定义回归任务"
        old_id = "historical-name-test"
        old_run = repo.get_run(run_id).model_copy(update={"id": old_id})
        old = EvaluationTask(id=old_id, kind="single", run_ids=(old_id,),
                             created_at=datetime(2026, 9, 24, tzinfo=UTC))
        repo.save_task_runs(old, [old_run])
        response = c.get("/api/evaluation-tasks").json()["data"]
        assert next(t for t in response if t["id"] == old_id)["name"] == "贷款智能体924"
        assert repo.get_evaluation_task(old_id).name == "贷款智能体924"
    with client(path) as c:
        assert c.get("/api/evaluation-tasks/" + run_id).json()["data"]["name"] == "自定义回归任务"
        assert c.get("/api/evaluation-tasks/" + old_id).json()["data"]["name"] == "贷款智能体924"


def test_blank_or_overlong_task_name_is_rejected(tmp_path):
    with client(tmp_path / "invalid-name.db") as c:
        run_id = launch(c)
        for name in ("   ", "a" * 129):
            response = c.put("/api/evaluation-tasks/" + run_id, json={
                "kind": "single", "run_ids": [run_id], "name": name,
            })
            assert response.status_code == 409
