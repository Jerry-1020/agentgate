"""Run the isolated upstream integration stack; never stop pre-existing services."""
import os
import argparse
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

root = Path(__file__).resolve().parents[1]
children = []
logs = []


def _probe(url):
    # vite 4 的 html 中间件要求带 Accept 头，否则根路径返回 404。
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/json,*/*"})
    urllib.request.urlopen(request, timeout=1).close()

def shutdown(*_):
    for child in reversed(children):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
    for log in logs:
        log.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-bank-agents', action='store_true', help='also supervise the independent tested-Agent service on 8107')
    options = parser.parse_args()
    for port in ((5197, 8097, 6397, 8107) if options.with_bank_agents else (5197, 8097, 6397)):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"端口 {port} 已被占用。不会停止已有服务；如本副本已启动，请访问 http://127.0.0.1:5197/")
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    services = ("bank-agents", "redis", "api", "worker", "scheduler", "web") if options.with_bank_agents else ("redis", "api", "worker", "scheduler", "web")
    for name in services:
        log = (runtime / (name + ".log")).open("a")
        logs.append(log)
        children.append(subprocess.Popen(["bash", str(root / "scripts/run.sh"), name],
                                         cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True))
        time.sleep(0.5)
    for _ in range(60):
        if any(child.poll() is not None for child in children):
            raise RuntimeError("有服务启动失败，请检查 runtime 中的日志。")
        try:
            _probe("http://127.0.0.1:8097/health")
            _probe("http://127.0.0.1:5197/")
            if options.with_bank_agents:
                _probe("http://127.0.0.1:8107/health")
            break
        except (OSError, ValueError):
            time.sleep(1)
    else:
        raise RuntimeError("服务启动超时，请检查 runtime 日志。")
    if options.with_bank_agents:
        subprocess.run([str(root / ".venv/bin/python"),
                        str(root / "scripts/seed-bank-agents.py")], cwd=root, check=True)
    print("已启动：http://127.0.0.1:5197/ ；按 Ctrl+C 停止本次启动的服务。", flush=True)
    webbrowser.open("http://127.0.0.1:5197/")
    while True:
        if any(child.poll() is not None for child in children):
            raise RuntimeError("服务已退出，请检查 runtime 日志。")
        time.sleep(1)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    finally:
        shutdown()
