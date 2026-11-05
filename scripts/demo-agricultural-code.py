"""Create synthetic agricultural-loan examples through the existing API.

For a local demonstration only. These thresholds are not a lending policy.
Each invocation creates a separate dataset and two published evaluators.
"""
import argparse
import json


AREA_SOURCE = '''def exec_evaluation(turn_data):
    data = turn_data["evaluate_dataset_fields"]["input"]
    target = turn_data["evaluate_target_output_fields"]
    # 演示规则：亩均额度由样本给定，不代表真实信贷政策。
    limit = data["planting_area_mu"] * data["demo_limit_per_mu"]
    if data["amount"] <= limit:
        return EvalOutput(score=1, reason="申请金额未超过演示亩均额度，无需额外复核")
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    passed = len(calls) > 0 and target["final_state"].get("human_review") == True and target["final_state"].get("approved") == False
    return EvalOutput(score=1 if passed else 0, reason="亩均额度超限，已转人工复核" if passed else "亩均额度超限，应转人工复核且不得直接批准", span_ids=[s["span_id"] for s in calls])
'''

DISASTER_SOURCE = '''def exec_evaluation(turn_data):
    data = turn_data["evaluate_dataset_fields"]["input"]
    target = turn_data["evaluate_target_output_fields"]
    # 演示规则：受灾标记必须是布尔值，字段缺失应报错。
    if data["disaster_affected"] == False:
        return EvalOutput(score=1, reason="未标记受灾，无需受灾专项复核")
    calls = [s for s in target["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    passed = len(calls) > 0 and target["final_state"].get("human_review") == True and target["final_state"].get("approved") == False
    return EvalOutput(score=1 if passed else 0, reason="受灾农户已转人工复核" if passed else "受灾农户应转人工复核且不得直接批准", span_ids=[s["span_id"] for s in calls])
'''

RULES = [
    ("农贷演示 · 亩均额度复核", "agri_demo_area_review", AREA_SOURCE),
    ("农贷演示 · 受灾农户复核", "agri_demo_disaster_review", DISASTER_SOURCE),
]

# A native whole-Trace example; kept separate from the original legacy demo.
HANDOFF_SOURCE = '''def exec_evaluation(trace):
    reviews = [s for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") == "request_human_review"]
    approvals = [s for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") == "approve_loan"]
    if len(reviews) == 0:
        return EvalOutput(score=1, reason="未转人工，不触发互斥检查")
    if len(approvals) > 0:
        return EvalOutput(score=0, reason="同一申请既转人工又自动批准，处理动作冲突", span_ids=[s["span_id"] for s in trace["spans"] if s.get("operation_type") == "tool" and s.get("name") in ["request_human_review", "approve_loan"]])
    return EvalOutput(score=1, reason="已转人工，且整条 Trace 未自动批准", span_ids=[s["span_id"] for s in reviews])
'''


def cases():
    scenarios = [
        ("agri-normal", "正常农资申请：全部通过", 50000, False, "low"),
        ("agri-over-limit", "额度超限：通用通过，亩均复核失败", 80000, False, "low"),
        ("agri-disaster", "受灾申请：通用通过，受灾复核失败", 50000, True, "low"),
        ("agri-reviewed", "超限且受灾：已转人工，全部通过", 80000, True, "high"),
    ]
    return [{
        "id": cid, "name": name, "category": "boundary", "difficulty": "easy",
        "tags": ["农贷", "模拟数据", "组合评估"],
        "turns": [{
            "id": cid + "-turn", "input": {
                "skill": "loan_approval", "application_id": cid,
                "risk": risk, "amount": amount, "loan_purpose": "春耕农资采购",
                "crop": "水稻", "planting_area_mu": 20, "demo_limit_per_mu": 3000,
                "disaster_affected": disaster,
            },
            "expectations": [
                {"id": "credit-check", "kind": "tool_call", "tool": "credit_inquiry", "mode": "required"},
                {"id": "generic-status", "kind": "state", "path": "status",
                 "condition": {"kind": "equals", "expected": "pending_review" if risk == "high" else "approved"}},
            ],
            "notes": "仅演示：通用状态按 risk 判断；农贷专属条件由自定义规则独立检查。",
        }],
    } for cid, name, amount, disaster, risk in scenarios]


def create_demo(client):
    def call(method, path, payload=None):
        response = client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()["data"]

    created = call("POST", "/api/datasets", {
        "name": "农贷演示 · 预置与自定义规则组合",
        "description": "4 个合成样本；亩均 3000 元仅为演示阈值。运行现有本地 Loan Agent，不代表真实农贷审批。",
    })
    dataset_id = created["dataset"]["id"]
    for case in cases():
        call("POST", f"/api/datasets/{dataset_id}/drafts/cases", case)
    version = call("POST", f"/api/datasets/{dataset_id}/drafts/publish")
    ids = ["required-tool", "final-state"]
    for name, metric, source in RULES:
        config = {"language": "python-subset-v1", "source": source, "pass_threshold": 1}
        call("POST", "/api/evaluators/code/validate", {"config": config})
        evaluator = call("POST", "/api/evaluators", {
            "name": name, "description": "模拟农贷业务规则，仅用于说明自定义评估能力；可修改 Python。",
            "draft": {"kind": "rule", "dimension": "tool_use", "metric": metric,
                      "severity": "standard", "implementation_id": "code_rule",
                      "implementation_version": "1", "config": config},
        })
        eid = evaluator["evaluator"]["id"]
        call("POST", f"/api/evaluators/{eid}/drafts/publish")
        call("PATCH", f"/api/evaluators/{eid}", {"enabled": True})
        ids.append(eid)
    run = call("POST", "/api/evaluations", {
        "version": "loan-agent-v2-fixed", "dataset_id": dataset_id,
        "dataset_version": version["version"], "evaluator_ids": ids,
    })
    return {"dataset_id": dataset_id, "evaluator_ids": ids, "run_id": run["run_id"]}


if __name__ == "__main__":
    import httpx
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8200")
    args = parser.parse_args()
    # Prevent accidental seeding of a production service.
    if args.api != "http://127.0.0.1:8200":
        parser.error("This demo is restricted to the local review API on port 8200")
    with httpx.Client(base_url=args.api, timeout=30) as client:
        print(json.dumps(create_demo(client), ensure_ascii=False, indent=2))
