import io
import logging
from types import SimpleNamespace

import pytest

from agentgate.server import logging_config

POLLING_PATHS = (
    "/api/overview",
    "/api/runs",
    "/api/evaluation-tasks",
    "/api/evaluation-overview/summary",
    "/api/evaluation-task-summaries",
)
ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


@pytest.fixture
def configured_logging(tmp_path, monkeypatch):
    output = io.StringIO()
    monkeypatch.setenv("AGENTGATE_LOG_PATH", str(tmp_path))
    monkeypatch.setattr(logging_config, "sys", SimpleNamespace(stdout=output))
    for name in ("", "agentgate", "uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [])
        monkeypatch.setattr(logger, "filters", [])
        monkeypatch.setattr(logger, "level", logging.NOTSET)
        monkeypatch.setattr(logger, "propagate", True)
    logging_config.setup_logging()
    try:
        yield output, tmp_path
    finally:
        for handler in logging.getLogger().handlers:
            handler.close()


@pytest.mark.parametrize("path", POLLING_PATHS)
@pytest.mark.parametrize("status", [200, 204, 299])
@pytest.mark.parametrize("query", ["", "?limit=200&page=1"])
def test_successful_polling_access_is_not_written(configured_logging, path, status, query):
    output, log_dir = configured_logging
    logging.getLogger("uvicorn.access").info(
        ACCESS_FORMAT, "127.0.0.1:1234", "GET", path + query, "1.1", status
    )

    assert '"GET ' not in output.getvalue()
    assert '"GET ' not in (log_dir / "agentgate.log").read_text()


@pytest.mark.parametrize("path", POLLING_PATHS)
@pytest.mark.parametrize("status", [301, 304, 400, 401, 404, 429, 500, 503])
def test_polling_redirects_and_failures_are_kept(configured_logging, path, status):
    output, log_dir = configured_logging
    logging.getLogger("uvicorn.access").info(
        ACCESS_FORMAT, "127.0.0.1:1234", "GET", path + "?limit=200", "1.1", status
    )

    expected = f'"GET {path}?limit=200 HTTP/1.1" {status}'
    assert expected in output.getvalue()
    assert expected in (log_dir / "agentgate.log").read_text()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/evaluation-tasks"),
        ("PUT", "/api/evaluation-tasks"),
        ("PATCH", "/api/evaluation-tasks"),
        ("DELETE", "/api/evaluation-tasks"),
        ("OPTIONS", "/api/overview"),
        ("HEAD", "/api/overview"),
        ("GET", "/health"),
        ("GET", "/api/runs/run-123"),
        ("GET", "/api/evaluation-tasks/task-123"),
        ("GET", "/api/evaluation-task-summaries/export"),
        ("GET", "/api/datasets"),
    ],
)
def test_other_access_logs_are_kept(configured_logging, method, path):
    output, log_dir = configured_logging
    logging.getLogger("uvicorn.access").info(
        ACCESS_FORMAT, "127.0.0.1:1234", method, path, "1.1", 200
    )

    expected = f'"{method} {path} HTTP/1.1" 200'
    assert expected in output.getvalue()
    assert expected in (log_dir / "agentgate.log").read_text()


def test_business_and_unexpected_access_logs_are_kept(configured_logging):
    output, log_dir = configured_logging
    logging.getLogger("agentgate.application.run_management").warning("Run throttled to waiting")
    logging.getLogger("agentgate.integrations.bjs").error("BJS submit failed")
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.info("Unknown access log format")
    access_logger.info("Access path: %s", "/api/overview")
    access_logger.warning(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/overview", "1.1", 200)

    for message in (
        "Run throttled to waiting",
        "BJS submit failed",
        "Unknown access log format",
        "Access path: /api/overview",
        '[WARNING] uvicorn.access - 127.0.0.1:1234 - "GET /api/overview HTTP/1.1" 200',
    ):
        assert message in output.getvalue()
        assert message in (log_dir / "agentgate.log").read_text()
    assert "BJS submit failed" in (log_dir / "agentgate-error.log").read_text()


def test_repeated_setup_does_not_duplicate_or_disable_logs(configured_logging):
    output, log_dir = configured_logging
    logging_config.setup_logging()
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/overview", "1.1", 200)
    access_logger.info(ACCESS_FORMAT, "127.0.0.1:1234", "GET", "/api/overview", "1.1", 503)

    for content in (output.getvalue(), (log_dir / "agentgate.log").read_text()):
        assert '"GET /api/overview HTTP/1.1" 200' not in content
        assert content.count('"GET /api/overview HTTP/1.1" 503') == 1
