"""Launch an isolated, restartable local acceptance stack."""

from __future__ import annotations

import base64
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/agent-platform/local"


def seed():
    from agentgate.application.dataset_management import DatasetManagement
    from agentgate.domain import Case, CaseTurn
    from agentgate.storage.configuration import create_repository, load_database_config

    repository = create_repository(load_database_config())
    try:
        manager = DatasetManagement(repository)
        name = "平台模拟验收 · 文本与多轮"
        if any(d.name == name for d in manager.list_datasets()):
            return
        dataset = manager.create_dataset(name, "本地模拟回答；使用最终输出规则评估器验收")
        manager.create_draft(dataset.id)
        for index, texts in enumerate((("你好",), ("查询余额",), ("第一轮", "第二轮")), 1):
            manager.save_case(
                dataset.id,
                Case(
                    name=f"模拟样本 {index}",
                    turns=tuple(
                        CaseTurn(
                            input={"txt": text},
                            expectations=(
                                {
                                    "kind": "output",
                                    "path": "output",
                                    "condition": {
                                        "kind": "matches_pattern",
                                        "pattern": ".*" + text + ".*",
                                    },
                                },
                            ),
                        )
                        for text in texts
                    ),
                ),
            )
        manager.publish_draft(dataset.id)
    finally:
        repository.close()


def main():
    if not shutil.which("redis-server"):
        raise RuntimeError("本地验收需要已安装的 redis-server")
    for port in (5199, 8099, 8119, 6399):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"端口 {port} 已占用；不会停止已有服务。")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    key = RUNTIME / "credential.key"
    if not key.exists():
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(base64.urlsafe_b64encode(os.urandom(32)).decode())
    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        AGENTGATE_DB_TYPE="sqlite",
        AGENTGATE_DB=str(RUNTIME / "agentgate.db"),
        AGENTGATE_AGENT_PLATFORM_MODE="mock",
        AGENTGATE_AGENT_PLATFORM_ORIGIN="http://127.0.0.1:8119",
        AGENTGATE_API_KEY_ENCRYPTION_KEY=key.read_text().strip(),
        AGENTGATE_REDIS_URL="redis://127.0.0.1:6399/0",
        AGENT_TASK_DISPATCHER_TYPE="celery",
        AGENTGATE_SCHEDULER_INTERVAL_SECONDS="2",
        FRONTEND_PORT="5199",
        API_PROXY_TARGET="http://127.0.0.1:8099",
        AGENT_PLATFORM_PROXY_TARGET="http://127.0.0.1:8119",
        VITE_AGENT_PLATFORM_ORIGIN="",
        VITE_ABCCLAW_PLATFORM_ORIGIN="",
        VITE_API_BASE_URL="/api",
    )
    python = str(ROOT / ".venv/bin/python")
    subprocess.run([python, str(Path(__file__).resolve()), "--seed"], env=env, cwd=ROOT, check=True)
    commands = {
        "peer": [python, str(ROOT / "scripts/agent-platform-mock/server.py")],
        "redis": [
            "redis-server",
            "--bind",
            "127.0.0.1",
            "--port",
            "6399",
            "--dir",
            str(RUNTIME),
            "--save",
            "",
            "--appendonly",
            "yes",
        ],
        "api": [
            python,
            "-m",
            "uvicorn",
            "agentgate.server.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8099",
            "--no-access-log",
        ],
        "worker": [
            python,
            "-m",
            "celery",
            "-A",
            "agentgate.integrations.job_dispatchers.celery:celery_app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--hostname=platform-mock@%h",
            "--loglevel=WARNING",
        ],
        "scheduler": [
            python,
            str(ROOT / "scripts/dispatch-scheduled-runs.py"),
            "--name",
            "platform-mock",
        ],
        "web": ["npm", "run", "dev"],
    }
    children, logs = [], []
    try:
        for name, command in commands.items():
            log = (RUNTIME / (name + ".log")).open("a")
            logs.append(log)
            children.append(
                subprocess.Popen(
                    command,
                    env=env,
                    cwd=ROOT / "frontend" if name == "web" else ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if any(c.poll() is not None for c in children):
                raise RuntimeError("服务启动失败，请检查 runtime/agent-platform/local 日志")
            try:
                for url in (
                    "http://127.0.0.1:8119/health",
                    "http://127.0.0.1:8099/health",
                    "http://127.0.0.1:5199/",
                ):
                    with urlopen(
                        Request(url, headers={"Accept": "text/html,application/json"}), timeout=1
                    ):
                        pass
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("本地服务启动超时")
        print(
            "本地验收已启动：http://127.0.0.1:5199/ ；Token 可填 local-demo，按 Ctrl+C 停止本次启动的服务。",
            flush=True,
        )
        while all(c.poll() is None for c in children):
            time.sleep(1)
        raise RuntimeError("服务退出，请检查本地日志")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        for log in logs:
            log.close()


if __name__ == "__main__":
    if "--seed" in sys.argv:
        seed()
    else:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            main()
        except KeyboardInterrupt:
            pass
