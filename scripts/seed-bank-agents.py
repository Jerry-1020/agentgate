"""Persist the standalone runtime's synthetic acceptance cases in AgentGate."""
import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from agentgate.application.dataset_management import DatasetManagement
from agentgate.domain import Case, CaseTurn
from agentgate.integrations.targets.local_bank import LocalBankClient
from agentgate.storage.sqlite import SQLiteRepository


def seed(database):
    repo = SQLiteRepository(database)
    datasets = DatasetManagement(repo)
    records = LocalBankClient().call("/test-cases")
    output = []
    for mode in ("base", "workflow", "cloudshrimp"):
        name = f"独立贷款智能体 · {mode} · test-policy-v1"
        existing = next((d for d in datasets.list_datasets() if d.name == name), None)
        if existing:
            output.append({"mode": mode, "dataset_id": existing.id, "existing": True})
            continue
        dataset = datasets.create_dataset(name, "数据库持久化的合成测试用例；不是行内生产贷款规则")
        datasets.create_draft(dataset.id)
        for record in records:
            if record["mode"] != mode:
                continue
            turns = []
            for index, text in enumerate(record["turns"]):
                final = index == len(record["turns"]) - 1
                expected = record["expected_status"] if final else "no_application"
                expectations = [{"kind": "state", "path": "status", "condition": {"kind": "equals", "expected": expected}}]
                if expected in {"approved", "pending_review", "rejected"}:
                    tool = {"approved": "approve_loan", "pending_review": "request_human_review", "rejected": "reject_loan"}[expected]
                    expectations.extend([{"kind": "tool_call", "mode": "required", "tool": "credit_inquiry"},
                                         {"kind": "tool_call", "mode": "required", "tool": tool}])
                if expected != "approved":
                    expectations.append({"kind": "tool_call", "mode": "forbidden", "tool": "approve_loan"})
                turns.append(CaseTurn(id=f"{record['id']}-turn-{index+1}", input={"txt": text}, expectations=tuple(expectations)))
            datasets.save_case(dataset.id, Case(id=record["id"], name=record["id"], turns=tuple(turns),
                initial_state={"customer": record["customer"]}, tags=("bank-runtime", mode, "synthetic")))
        version = datasets.publish_draft(dataset.id)
        output.append({"mode": mode, "dataset_id": dataset.id, "version": version.version, "cases": len(version.cases)})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=root / "runtime/agentgate.db")
    print(json.dumps(seed(parser.parse_args().database), ensure_ascii=False, indent=2))
