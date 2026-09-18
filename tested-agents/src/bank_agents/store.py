"""Real SQLite state for isolated, synthetic loan applications and conversations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


PROFILES = {
    "test-low": {"risk": "low", "credit_score": 720, "blocked": False},
    "test-high": {"risk": "high", "credit_score": 580, "blocked": False},
    "test-blocked": {"risk": "high", "credit_score": 400, "blocked": True},
}


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, mode TEXT NOT NULL,
                    customer TEXT NOT NULL REFERENCES profiles(id), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id),
                    digest TEXT NOT NULL, status TEXT NOT NULL, trace_id TEXT NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, session TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                    data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY, request TEXT NOT NULL REFERENCES requests(id),
                    name TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
            for key, value in PROFILES.items():
                db.execute("INSERT OR IGNORE INTO profiles VALUES (?,?)", (key, json.dumps(value)))
            scenarios = [
                ("low", "test-low", ["我要申请8万元贷款，用于购买农机"], "approved"),
                ("high", "test-high", ["申请8万元贷款，购买农机"], "pending_review"),
                ("blocked", "test-blocked", ["申请5万元贷款，购买农机"], "rejected"),
                ("large", "test-low", ["申请30万元贷款，扩大种植"], "pending_review"),
                ("missing", "test-low", ["我想申请贷款"], "no_application"),
                ("multi", "test-low", ["我想申请贷款", "8万元，用于购买农机"], "approved"),
                ("boundary", "test-low", ["申请20万元贷款，购买设备"], "approved"),
                ("status", "test-low", ["查询我的贷款申请进度"], "no_application"),
            ]
            for mode in ("base", "workflow", "cloudshrimp"):
                for name, customer, turns, expected in scenarios:
                    key = f"{mode}-{name}"
                    db.execute("INSERT OR IGNORE INTO cases VALUES (?,?)", (key, json.dumps({
                        "id": key, "mode": mode, "customer": customer, "turns": turns,
                        "expected_status": expected, "policy_version": "test-policy-v1",
                    }, ensure_ascii=False)))

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create_session(self, mode, customer, session_id=None):
        session_id = session_id or str(uuid4())
        with self.db() as db:
            if db.execute("SELECT 1 FROM profiles WHERE id=?", (customer,)).fetchone() is None:
                raise ValueError("only registered synthetic test customers are permitted")
            db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?,?)",
                       (session_id, mode, customer, json.dumps({"slots": {}, "messages": []})))
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row["mode"] != mode or row["customer"] != customer:
                raise Conflict("session belongs to another mode or customer")
        return session_id

    def session(self, session_id, mode):
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None or row["mode"] != mode:
                raise ValueError("unknown session for this agent")
            return {**dict(row), "data": json.loads(row["data"])}

    def reserve(self, request_id, session_id, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if existing:
                if existing["session"] != session_id or existing["digest"] != digest:
                    raise Conflict("request ID already used with different input")
                if existing["status"] != "completed":
                    raise Conflict("request is in progress or failed; inspect before retrying")
                return json.loads(existing["result"])
            if db.execute("SELECT 1 FROM requests WHERE session=? AND status='running'", (session_id,)).fetchone():
                raise Conflict("another turn is running in this session")
            db.execute("INSERT INTO requests VALUES (?,?,?,'running',?,NULL)",
                       (request_id, session_id, digest, str(uuid4())))
        return None

    def request(self, request_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise ValueError("unknown request")
            return dict(row)

    def finish(self, request_id, result, session_data=None, failed=False):
        with self.db() as db:
            row = db.execute("SELECT session FROM requests WHERE id=?", (request_id,)).fetchone()
            db.execute("UPDATE requests SET status=?,result=? WHERE id=?",
                       ("failed" if failed else "completed", json.dumps(result, ensure_ascii=False), request_id))
            if session_data is not None:
                db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session_data, ensure_ascii=False), row[0]))

    def application(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT data FROM applications WHERE session=?", (session_id,)).fetchone()
            return json.loads(row[0]) if row else {"status": "no_application", "approved": False, "human_review": False}

    def profile(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT p.data FROM profiles p JOIN sessions s ON s.customer=p.id WHERE s.id=?", (session_id,)).fetchone()
            return json.loads(row[0])

    def save_application(self, session_id, data):
        with self.db() as db:
            db.execute("INSERT INTO applications VALUES (?,?,?) ON CONFLICT(session) DO UPDATE SET data=excluded.data",
                       (data["application_id"], session_id, json.dumps(data, ensure_ascii=False)))

    def audit(self, request_id, name, arguments, result):
        with self.db() as db:
            db.execute("INSERT INTO tool_audit(request,name,arguments,result) VALUES (?,?,?,?)",
                       (request_id, name, json.dumps(arguments), json.dumps(result, ensure_ascii=False)))

    def cases(self):
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM cases ORDER BY id")]
