"""Explicit local-demo evaluator initialization using the recipient's model."""

import json
from importlib.resources import files

from agentgate.application.evaluator_management import EvaluatorManagement
from agentgate.domain import Evaluator, EvaluatorDraft


def ensure_loan_evaluators(manager: EvaluatorManagement) -> dict[str, str]:
    records = json.loads(
        files("agentgate.demo").joinpath("loan-core-evaluators.json").read_text(encoding="utf-8")
    )
    model = None
    if any(e.id == "answer-quality" for e in manager.list_evaluators()):
        model = manager.get_version("answer-quality", "1").config.to_dict()["model"]
    result = {}
    for record in records:
        definition = record["draft"]
        if definition["kind"] != "rule" and model is None:
            continue
        identity = record["id"]
        existing = manager.repository.get_evaluator(identity, user_team_id="")
        if existing is not None:
            result[record["key"]] = identity
            continue
        definition = {**definition, "config": dict(definition.get("config", {}))}
        if definition["kind"] == "llm_judge":
            definition["config"]["model"] = model
        evaluator = Evaluator(
            id=identity,
            name=record["name"],
            description="工程自带贷款专项评估器；使用本机配置的模型。",
        )
        draft = EvaluatorDraft(evaluator_id=identity, **definition)
        manager.repository.save_evaluator_with_draft(evaluator, draft)
        manager.publish_draft(identity)
        manager.update_evaluator(identity, enabled=True)
        result[record["key"]] = identity
    return result
