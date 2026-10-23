"""HTTP identity headers preserve request scope and diagnostic values."""
import logging

import pytest
from fastapi.testclient import TestClient

from agentgate.server.app import create_app
from agentgate.server.user_context import get_user_info


@pytest.mark.parametrize(
    "headers, expected",
    [
        ({"X-Team-Id": "team-a", "X-User-Id": "user-a", "X-User-Name": "User"},
         ("team-a", "user-a", "User")),
        ({"x-team-id": "team-b", "x-user-id": "user-b"},
         ("team-b", "user-b", "匿名用户")),
        ({"X-Team-Id": "", "X-User-Id": "", "X-User-Name": ""},
         ("", "anonymous", "匿名用户")),
        ({}, ("", "anonymous", "匿名用户")),
        ({"user_team_id": "old-team", "user_id": "old-user"},
         ("", "anonymous", "匿名用户")),
    ],
)
def test_identity_headers_and_logs(tmp_path, caplog, headers, expected):
    app = create_app(tmp_path / "identity.db")

    @app.post("/api/identity-probe")
    def identity_probe():
        info = get_user_info()
        return {"team": info.user_team_id, "user": info.user_id, "name": info.user_name}

    headers = {**headers, "token": "secret-must-not-appear"}
    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="agentgate.server.app"):
        response = client.post("/api/identity-probe", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == dict(zip(("team", "user", "name"), expected))
        normalized = {k.lower(): v for k, v in headers.items()}
        assert (
            f"Request identity: path=/api/identity-probe "
            f"user_team_id={normalized.get('x-team-id')!r} "
            f"user_id={normalized.get('x-user-id')!r}"
        ) in caplog.text
        assert f"API request: POST /api/identity-probe user_id={expected[1]}" in caplog.text
        assert "secret-must-not-appear" not in caplog.text
        # A following request cannot inherit the preceding caller's identity.
        cleared = client.post("/api/identity-probe").json()["data"]
        assert cleared == {"team": "", "user": "anonymous", "name": "匿名用户"}
    assert get_user_info() is None
