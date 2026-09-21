"""Read-only checks against new browser-created runs, SQLite and SDK JSONL."""
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agentgate.storage.configuration import create_repository, load_database_config
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runtime/bank-acceptance"


def main():
    browser = json.loads((OUT / "browser.json").read_text())
    if browser.get("accepted") is not True:
        raise RuntimeError("browser acceptance has not passed")
    checks = []
    client = httpx.Client(timeout=30, trust_env=False)
    with closing(create_repository(load_database_config())) as platform, \
         sqlite3.connect(f"file:{ROOT / 'runtime/bank-agents/bank.db'}?mode=ro", uri=True) as bank, client:
        bank.row_factory = sqlite3.Row
        for run in browser["runs"]:
            rid = run["run_id"]
            for case in run["samples"]["run"]["manifest"]["dataset"]["cases"]:
                stored_trace = platform.get_trace(rid, case["id"])
                if stored_trace is None:
                    raise RuntimeError("expected platform Trace is missing")
                trace = stored_trace.model_dump(mode="json")
                response = client.get(f"http://127.0.0.1:8097/api/runs/{rid}/traces/{case['id']}")
                response.raise_for_status()
                public = {s["span_id"]: s for s in response.json()["data"]["spans"]}
                for span in trace["spans"]:
                    if span["operation_type"] != "turn":
                        continue
                    a = span["attributes"]
                    ridx, sid, tid = a["bank.request_id"], a["trace_sdk.session_id"], a["trace_sdk.trace_id"]
                    path = ROOT / "runtime/bank-agents/traces/bank-tested-agents" / sid / (tid + ".jsonl")
                    raw = path.read_bytes()
                    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
                    root = next(e for e in events if e["event_type"] == "trace")
                    record = bank.execute("SELECT * FROM requests WHERE id=?", (ridx,)).fetchone()
                    result = json.loads(record["result"])
                    turn = trace["turn_outcomes"][a["agentgate.turn.id"]]
                    expected = next(t["input"] for t in case["turns"] if t["id"] == a["agentgate.turn.id"])
                    sdk_spans = [e for e in events if e["event_type"] == "span"]
                    downloaded = client.get(f"http://127.0.0.1:8107/requests/{ridx}/trace")
                    downloaded.raise_for_status()
                    tool_names = [row[0] for row in bank.execute("SELECT name FROM tool_audit WHERE request=?", (ridx,))]
                    result_checks = {
                        "ids_survive_api_redaction": all(public[span["span_id"]]["attributes"].get(k) == a[k]
                            for k in ("bank.request_id", "trace_sdk.session_id", "trace_sdk.trace_id", "trace_sdk.export_sha256")),
                        "raw_sha_matches": hashlib.sha256(raw).hexdigest() == a["trace_sdk.export_sha256"],
                        "download_matches_raw": downloaded.content == raw,
                        "request_session_trace_match": record["session"] == sid and record["trace_id"] == tid and result["request_id"] == ridx,
                        "root_matches_business_db": root["output"] == result,
                        "input_matches": root["input"] == expected == turn["input"],
                        "output_matches": turn["output"] == {"output": result["output"]},
                        "state_matches": turn["state"] == result["final_state"],
                        "tools_match": Counter(tool_names) == Counter(e["tool_name"] for e in sdk_spans if e.get("tool_name")),
                        "live_execution": a["trace_sdk.replay"] is False,
                        "has_model_evidence": any(e.get("span_type") == "llm" for e in sdk_spans),
                    }
                    checks.append({"run_id": rid, "case_id": case["id"], "request_id": ridx,
                                   "raw_path": str(path.relative_to(ROOT)), "checks": result_checks})
    report = {"turns": len(checks), "checks": checks, "passed": len(checks) == 27 and all(all(c["checks"].values()) for c in checks)}
    (OUT / "trace-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"turns": len(checks), "checks": sum(len(c["checks"]) for c in checks), "passed": report["passed"]}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
