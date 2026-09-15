#!/bin/bash
set -euo pipefail
integration_root="$(cd "$(dirname "$0")" && pwd)"
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"
cd "$integration_root"
if ! command -v redis-server >/dev/null || ! command -v npm >/dev/null || ! command -v uv >/dev/null; then
  echo "需先安装 Node.js/npm、Redis 和 uv。本脚本不会自动安装系统软件。"
  exit 1
fi
if [ ! -x backend/.venv/bin/python ]; then
  (cd backend && uv sync --extra test)
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi
exec backend/.venv/bin/python scripts/start-integration.py
