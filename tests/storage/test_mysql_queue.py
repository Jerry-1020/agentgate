"""Exercise actual Redis delivery to a separate Celery worker process."""

import os
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from celery import Celery
from fastapi.testclient import TestClient
from redis import Redis

from agentgate.application import TargetCatalog
from agentgate.demo.bootstrap import ensure_demo_dataset, ensure_demo_target_descriptors
from agentgate.integrations.job_dispatchers.celery import TASK_NAME
from agentgate.server.app import create_app


def test_api_to_real_worker_and_mysql(mysql_repository, mysql_config, monkeypatch, tmp_path):
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is required for real queue verification")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    redis_url = f"redis://127.0.0.1:{port}/0"
    queue = f"agentgate-test-{uuid4().hex}"
    for name, value in {
        "AGENTGATE_DB_TYPE": "tdsql",
        "AGENTGATE_TDSQL_URL": mysql_config.url,
        "AGENTGATE_TDSQL_USER": mysql_config.username,
        "AGENTGATE_TDSQL_PASSWORD": mysql_config.password.get_secret_value(),
        "AGENTGATE_REDIS_URL": redis_url,
    }.items():
        monkeypatch.setenv(name, value)
    for name in tuple(os.environ):
        if name.startswith("AGENTGATE_JUDGE_"):
            monkeypatch.delenv(name)
    ensure_demo_dataset(mysql_repository)
    ensure_demo_target_descriptors(TargetCatalog(mysql_repository))
    processes = []
    broker = Redis(host="127.0.0.1", port=port, socket_connect_timeout=1, socket_timeout=1)
    sender = Celery("mysql-queue-test", broker=redis_url)

    class Dispatcher:
        def submit(self, run_id):
            sender.send_task(TASK_NAME, args=[run_id], task_id=run_id, queue=queue)

        def cancel(self, run_id):
            sender.control.revoke(run_id)

    with (tmp_path / "queue.log").open("w") as log:
        try:
            processes.append(
                subprocess.Popen(
                    [
                        executable,
                        "--bind",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--save",
                        "",
                        "--appendonly",
                        "no",
                        "--dir",
                        str(tmp_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
            deadline = time.monotonic() + 10
            while True:
                try:
                    if broker.ping():
                        break
                except ConnectionError:
                    pass
                except OSError:
                    pass
                except Exception as exc:
                    from redis.exceptions import ConnectionError as RedisConnectionError

                    if not isinstance(exc, RedisConnectionError):
                        raise
                assert time.monotonic() < deadline, "test Redis did not start"
                time.sleep(0.05)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "agentgate.integrations.job_dispatchers.celery:celery_app",
                        "worker",
                        "--pool=solo",
                        "--concurrency=1",
                        "--queues",
                        queue,
                        "--without-gossip",
                        "--without-mingle",
                        "--without-heartbeat",
                        "--loglevel=WARNING",
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
            with TestClient(create_app(dispatcher=Dispatcher())) as client:
                response = client.post(
                    "/api/evaluations",
                    json={
                        "version": "loan-agent-v2-fixed",
                        "dataset_id": "loan-risk-policy",
                        "dataset_version": 1,
                    },
                )
                assert response.status_code == 202, response.text
                run_id = response.json()["run_id"]
                deadline = time.monotonic() + 30
                while True:
                    run = mysql_repository.get_run(run_id)
                    if run.status in {"completed", "failed", "cancelled"}:
                        break
                    assert processes[-1].poll() is None, "test worker exited"
                    assert time.monotonic() < deadline, "test worker did not complete the Run"
                    time.sleep(0.1)
                assert run.status == "completed"
                assert mysql_repository.list_results(run_id)
                assert mysql_repository.list_traces(run_id)
                assert client.get(f"/api/runs/{run_id}").status_code == 200
        finally:
            sender.close()
            broker.close()
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
