import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from bank_agents.reporting import report_events, report_file
from bank_agents.telemetry import Evidence


@pytest.fixture
def receiver(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            value = json.loads(raw)
            calls.append((self.headers["Authorization"], value))
            root = next(e for e in value["events"] if e["event_type"] == "trace")
            body = json.dumps(
                {
                    "trace_id": root["trace_id"],
                    "project_id": root["project_id"],
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "event_count": len(value["events"]),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TRACE_REPORT_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("TRACE_REPORT_TOKEN", "x" * 32)
    yield calls
    server.shutdown()
    server.server_close()
    thread.join()


def test_evidence_finish_uploads_original_sdk_events(tmp_path, receiver):
    evidence = Evidence(tmp_path, "trace-1", "session-1", "base", "hello")
    with evidence.span("actual-step", inputs={"txt": "hello"}) as span:
        span["output"] = {"output": "world"}
    evidence.finish({"output": "world"})
    assert len(receiver) == 1
    authorization, bundle = receiver[0]
    assert authorization == "Bearer " + "x" * 32 and bundle["provenance"] == "sdk"
    assert bundle["events"] == [json.loads(l) for l in evidence.path.read_text().splitlines()]
    report_file(evidence.path)
    assert receiver[1][1] == bundle


def test_failed_upload_keeps_spool_and_does_not_repeat_business(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_REPORT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("TRACE_REPORT_TOKEN", "x" * 32)
    evidence = Evidence(tmp_path, "trace-failed", "session-1", "base", "hello")
    with evidence.span("business-operation") as span:
        span["output"] = "done"
    with pytest.raises(RuntimeError, match="local evidence retained"):
        evidence.finish({"output": "done"})
    assert evidence.path.is_file()
    assert (
        len(
            [
                e
                for e in map(json.loads, evidence.path.read_text().splitlines())
                if e["event_type"] == "span"
            ]
        )
        == 1
    )


def test_remote_reporting_rejects_plaintext_and_missing_token(monkeypatch):
    monkeypatch.setenv("TRACE_REPORT_URL", "http://collector.example")
    with pytest.raises(ValueError, match="HTTPS"):
        report_events([])
    monkeypatch.setenv("TRACE_REPORT_URL", "https://collector.example")
    monkeypatch.delenv("TRACE_REPORT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="TRACE_REPORT_TOKEN"):
        report_events([])
