"""Supervise a complete loopback-only local stack without touching other services."""

from __future__ import annotations

import argparse
import base64
import secrets
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def local_environment(root: Path, offset: int = 0) -> tuple[dict[str, str], dict[str, int]]:
    env = dict(os.environ)
    dispatcher = env.get("AGENT_TASK_DISPATCHER_TYPE", "celery").strip().lower()
    if dispatcher not in ("celery", "bjs"):
        raise ValueError("AGENT_TASK_DISPATCHER_TYPE must be celery or bjs")
    ports = {
        k: n + offset
        for k, n in {
            "web": 5197,
            "api": 8097,
            "redis": 6397,
            "directory": 8119,
            "bank": 8107,
            "trace": 8210,
        }.items()
    }
    if any(not 1024 <= p <= 65535 for p in ports.values()):
        raise ValueError("端口偏移超出范围")
    runtime = root / "runtime"
    db = Path(env.get("AGENTGATE_DB", str(runtime / "agentgate.db")))
    if not db.is_absolute():
        db = root / db
    key_path = runtime / "credential.key"
    runtime.mkdir(parents=True, exist_ok=True)
    if not env.get("AGENTGATE_API_KEY_ENCRYPTION_KEY"):
        if not key_path.exists():
            with open(key_path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as f:
                f.write(base64.urlsafe_b64encode(os.urandom(32)).decode())
        env["AGENTGATE_API_KEY_ENCRYPTION_KEY"] = key_path.read_text().strip()
    external = env.get("AGENTGATE_AGENT_PLATFORM_MODE", "mock") == "mock"
    env.update(
        PYTHONPATH=str(root / "src"),
        AGENTGATE_DB=str(db.resolve()),
        AGENTGATE_DB_TYPE=env.get("AGENTGATE_DB_TYPE", "sqlite"),
        AGENTGATE_LOG_PATH=str(runtime / "logs"),
        AGENT_TASK_DISPATCHER_TYPE=dispatcher,
        AGENTGATE_REDIS_MODE="single" if external else env.get("AGENTGATE_REDIS_MODE", "single"),
        AGENTGATE_REDIS_URL=(
            f"redis://127.0.0.1:{ports['redis']}/0"
            if external
            else env.get("AGENTGATE_REDIS_URL", "redis://localhost:6379/0")
        ),
        AGENTGATE_BANK_BASE_URL=env.get(
            "AGENTGATE_BANK_BASE_URL", f"http://127.0.0.1:{ports['bank']}"
        ),
        AGENTGATE_TRACE_SERVER_URL=env.get(
            "AGENTGATE_TRACE_SERVER_URL", f"http://127.0.0.1:{ports['trace']}"
        ),
        AGENTGATE_AGENT_PLATFORM_MODE=env.get("AGENTGATE_AGENT_PLATFORM_MODE", "mock"),
        AGENTGATE_AGENT_PLATFORM_ORIGIN=(
            env.get("AGENTGATE_AGENT_PLATFORM_ORIGIN", "")
            if env.get("AGENTGATE_AGENT_PLATFORM_MODE", "mock") != "mock"
            else f"http://127.0.0.1:{ports['directory']}"
        ),
        VITE_LOCAL_PLATFORM_ORIGIN=f"http://127.0.0.1:{ports['directory']}",
        FRONTEND_PORT=str(ports["web"]),
        API_PROXY_TARGET=f"http://127.0.0.1:{ports['api']}",
        BANK_RUNTIME_DIR=str(runtime / "bank-agents"),
    )
    return env, ports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-bank-agents", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--port-offset", type=int, default=0, help="shift every local port for an isolated checkout"
    )
    args = parser.parse_args()
    load_dotenv(os.environ.get("AGENTGATE_MODEL_ENV_FILE", str(ROOT / ".env")), override=False)
    env, ports = local_environment(ROOT, args.port_offset)
    reporting_key = ROOT / "runtime/trace-report.key"
    if not reporting_key.exists():
        with open(reporting_key, "x", opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            handle.write(secrets.token_urlsafe(32))
    env.setdefault("TRACE_REPORT_TOKEN", reporting_key.read_text().strip())
    env.setdefault("TRACE_REPORT_URL", f"http://127.0.0.1:{ports['trace']}")
    if env["AGENTGATE_AGENT_PLATFORM_MODE"] == "mock":
        env["AGENTGATE_TRACE_SERVER_URL"] = env["TRACE_REPORT_URL"]
        env["AGENTGATE_TRACE_SERVER_TOKEN"] = env["TRACE_REPORT_TOKEN"]
        env["AGENTGATE_REQUIRE_REPORTED_TRACE"] = "1"
    celery = env["AGENT_TASK_DISPATCHER_TYPE"] == "celery"
    local_redis = celery and env["AGENTGATE_AGENT_PLATFORM_MODE"] == "mock"
    for command in ("redis-server", "npm") if local_redis else ("npm",):
        if not shutil.which(command):
            raise RuntimeError(f"缺少依赖：{command}")
    python = str(ROOT / ".venv/bin/python")
    if args.with_bank_agents:
        env["AGENTGATE_BANK_BASE_URL"] = f"http://127.0.0.1:{ports['bank']}"
        if env["AGENTGATE_AGENT_PLATFORM_MODE"] == "mock":
            env["AGENTGATE_TRACE_SERVER_URL"] = env["TRACE_REPORT_URL"]
        for target, source in [
            ("BANK_MODEL_BASE_URL", "AGENTGATE_JUDGE_BASE_URL"),
            ("BANK_MODEL_NAME", "AGENTGATE_JUDGE_MODEL_ID"),
            ("BANK_MODEL_API_KEY", "AGENTGATE_JUDGE_API_KEY"),
        ]:
            if not env.get(target):
                env[target] = env.get(source, "")
        if not all(
            env.get(k) for k in ("BANK_MODEL_BASE_URL", "BANK_MODEL_NAME", "BANK_MODEL_API_KEY")
        ):
            raise RuntimeError(
                "真实贷款服务需要BANK_MODEL三项或完整AGENTGATE_JUDGE模型配置；不会回退为模拟回答。"
            )
    active = (
        (["redis"] if local_redis else [])
        + ["directory", "api", "web", "trace"]
        + (["bank"] if args.with_bank_agents else [])
    )
    for name in active:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", ports[name])) == 0:
                raise RuntimeError(
                    f"{name}端口{ports[name]}已占用；不停止已有服务。可使用--port-offset。"
                )
    if env["AGENTGATE_DB_TYPE"] == "sqlite" and env["AGENTGATE_AGENT_PLATFORM_MODE"] == "mock":
        subprocess.run(
            [python, str(ROOT / "scripts/seed-loan-evaluators.py")], cwd=ROOT, env=env, check=True
        )
    commands = {
        "redis": (
            [
                shutil.which("redis-server"),
                "--bind",
                "127.0.0.1",
                "--port",
                str(ports["redis"]),
                "--dir",
                str(ROOT / "runtime"),
                "--save",
                "",
                "--appendonly",
                "yes",
            ],
            ROOT,
            env,
        ),
        "directory": (
            [
                python,
                str(ROOT / "scripts/agent-platform-mock/server.py"),
                "--port",
                str(ports["directory"]),
            ],
            ROOT,
            {
                **env,
                "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tested-agents/src")]),
            },
        ),
        "api": (
            [
                python,
                "-m",
                "uvicorn",
                "agentgate.server.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(ports["api"]),
            ],
            ROOT,
            env,
        ),
        "worker": (
            [
                python,
                "-m",
                "celery",
                "-A",
                "agentgate.integrations.job_dispatchers.celery:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                f"--hostname=local-{ports['api']}@%h",
                "--loglevel=INFO",
            ],
            ROOT,
            env,
        ),
        "scheduler": (
            [
                python,
                "-m",
                "celery",
                "-A",
                "agentgate.integrations.job_dispatchers.celery:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--queues=agentgate.scheduler",
                "--beat",
                f"--schedule={ROOT / 'runtime/scheduler-state'}",
                f"--hostname=local-scheduler-{ports['api']}@%h",
                "--loglevel=INFO",
            ],
            ROOT,
            env,
        ),
        "web": ([shutil.which("npm"), "run", "dev"], ROOT / "frontend", env),
    }
    if not local_redis:
        del commands["redis"]
    if not celery:
        del commands["worker"]
        commands["scheduler"] = (
            [python, str(ROOT / "scripts/dispatch-scheduled-runs.py")],
            ROOT,
            env,
        )
    if args.with_bank_agents:
        commands["bank"] = (
            [
                str(ROOT / "tested-agents/.venv/bin/python"),
                str(ROOT / "tested-agents/run.py"),
                "--port",
                str(ports["bank"]),
            ],
            ROOT,
            {**env, "PYTHONPATH": str(ROOT / "tested-agents/src")},
        )
    commands["trace"] = (
        [python, str(ROOT / "scripts/trace-server.py"), "--port", str(ports["trace"])],
        ROOT,
        {
            **env,
            "PYTHONPATH": os.pathsep.join(
                [str(ROOT / "src"), str(ROOT / "vendor/trace-server/backend")]
            ),
            "STORAGE_BACKEND": "file",
            "DATA_FILE": str(ROOT / "runtime/trace-server/received"),
        },
    )
    children, logs = [], []
    opener = build_opener(ProxyHandler({}))
    try:
        for name, (command, cwd, child_env) in commands.items():
            log = (ROOT / "runtime" / f"{name}.log").open("ab")
            logs.append(log)
            children.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        urls = [
            f"http://127.0.0.1:{ports['api']}/health",
            f"http://127.0.0.1:{ports['web']}/",
            f"http://127.0.0.1:{ports['directory']}/health",
            f"http://127.0.0.1:{ports['trace']}/health",
        ]
        if args.with_bank_agents:
            urls += [f"http://127.0.0.1:{ports[n]}/health" for n in ("bank",)]
        for _ in range(90):
            if any(c.poll() is not None for c in children):
                raise RuntimeError("服务退出，请查看runtime/*.log。")
            try:
                for url in urls:
                    with opener.open(
                        Request(url, headers={"Accept": "text/html, application/json"}), timeout=1
                    ):
                        pass
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("服务健康检查超时，请查看runtime/*.log。")
        print(
            f"已启动：http://127.0.0.1:{ports['web']}/ （行外Login）；Ctrl+C停止本次服务。",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{ports['web']}/")
        while True:
            if any(c.poll() is not None for c in children):
                exited = [
                    name
                    for name, child in zip(commands, children, strict=True)
                    if child.poll() is not None
                ]
                raise RuntimeError(f"服务意外退出：{exited}，请查看runtime/*.log。")
            time.sleep(1)
    finally:
        for c in reversed(children):
            if c.poll() is None:
                try:
                    os.killpg(c.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for c in children:
            try:
                c.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(c.pid, signal.SIGKILL)
                c.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
