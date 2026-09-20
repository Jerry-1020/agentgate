"""Backend selection is shared by HTTP and scheduled submission."""

import pytest

from agentgate.integrations.job_dispatchers.bjs_job_dispatcher import BjsJobDispatcher
from agentgate.integrations.job_dispatchers.celery import CeleryJobDispatcher
from agentgate.integrations.job_dispatchers.configuration import (
    create_dispatcher,
    load_dispatcher_type,
)
from agentgate.server.dependencies import build_dependencies


def test_default_backend_is_celery(monkeypatch):
    monkeypatch.delenv("AGENT_TASK_DISPATCHER_TYPE", raising=False)
    assert load_dispatcher_type({}) == "celery"
    assert isinstance(create_dispatcher(), CeleryJobDispatcher)


@pytest.mark.parametrize("value", ["bjs", "BJS", " bjs "])
def test_api_selects_supported_bjs_backend(tmp_path, monkeypatch, value):
    monkeypatch.setenv("AGENT_TASK_DISPATCHER_TYPE", value)
    monkeypatch.setenv("AGENTGATE_DB_TYPE", "sqlite")
    monkeypatch.setenv("AGENTGATE_BJS_SUBMIT_URL", "https://bjs.example/submit")
    monkeypatch.setenv("AGENTGATE_BJS_JOB_ID", "ai11")
    dependencies = build_dependencies(tmp_path / "api.db")
    try:
        assert isinstance(dependencies.dispatcher, BjsJobDispatcher)
    finally:
        dependencies.close()


def test_missing_bjs_configuration_fails_before_submission(monkeypatch):
    monkeypatch.setenv("AGENT_TASK_DISPATCHER_TYPE", "bjs")
    monkeypatch.delenv("AGENTGATE_BJS_SUBMIT_URL", raising=False)
    with pytest.raises(ValueError, match="AGENTGATE_BJS_SUBMIT_URL"):
        create_dispatcher()
