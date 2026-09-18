#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
for python_path in .venv/bin/python tested-agents/.venv/bin/python; do
  if [ ! -x "$python_path" ]; then
    echo "先运行 bash scripts/setup-bank-integration.sh"
    exit 1
  fi
done
if [ ! -d frontend/node_modules ]; then
  echo "先运行 bash scripts/setup-bank-integration.sh"
  exit 1
fi
export AGENTGATE_MODEL_ENV_FILE="${AGENTGATE_MODEL_ENV_FILE:-$project_root/.env}"
if [ ! -f "$AGENTGATE_MODEL_ENV_FILE" ]; then
  echo "缺少模型配置：复制 .env.example 为 .env 后填写有效模型配置，或设置 AGENTGATE_MODEL_ENV_FILE。"
  exit 1
fi
exec .venv/bin/python scripts/start-integration.py --with-bank-agents
