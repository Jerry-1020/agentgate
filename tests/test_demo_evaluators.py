from agentgate.demo.evaluators import ensure_loan_evaluators
from agentgate.server.dependencies import build_dependencies


def test_seed_without_model_then_configure_preserves_user_edits(tmp_path, monkeypatch):
    for name in ("PROVIDER_ID", "BASE_URL", "API_KEY", "MODEL_ID", "TRANSPORT"):
        monkeypatch.delenv("AGENTGATE_JUDGE_" + name, raising=False)
    path = tmp_path / "portable.db"
    dependencies = build_dependencies(path)
    try:
        seeded = ensure_loan_evaluators(dependencies.evaluators)
        assert set(seeded) == {"path"}
        dependencies.evaluators.update_evaluator(seeded["path"], name="用户修改名称", enabled=False)
    finally:
        dependencies.close()
    for name, value in {
        "PROVIDER_ID": "recipient",
        "BASE_URL": "https://example.com/v1",
        "API_KEY": "test-only-key",
        "MODEL_ID": "recipient-model",
        "TRANSPORT": "api",
    }.items():
        monkeypatch.setenv("AGENTGATE_JUDGE_" + name, value)
    dependencies = build_dependencies(path)
    try:
        seeded = ensure_loan_evaluators(dependencies.evaluators)
        assert len(seeded) == 7
        assert ensure_loan_evaluators(dependencies.evaluators) == seeded
        changed = dependencies.repository.get_evaluator(seeded["path"], user_team_id="")
        assert changed.name == "用户修改名称" and not changed.enabled
        for key, identity in seeded.items():
            version = dependencies.evaluators.get_version(identity, "1")
            if key.endswith("-llm"):
                assert version.config.to_dict()["model"]["model_id"] == "recipient-model"
                assert "test-only-key" not in version.model_dump_json()
            if key.endswith("-hybrid"):
                assert len(version.children) >= 6
    finally:
        dependencies.close()
