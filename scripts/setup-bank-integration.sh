#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
for command_name in uv node npm redis-server; do
  if ! command -v "$command_name" >/dev/null; then
    echo "缺少依赖：$command_name。请先安装 Python 3.11、uv、Node.js 22/npm、Redis。"
    exit 1
  fi
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("需要 Node.js 22 或更高版本"); process.exit(1) }'
uv sync --locked --python 3.11 --extra test
(cd tested-agents && uv sync --locked --python 3.11 --extra test)
(cd frontend && npm ci)
echo "依赖已安装。浏览器验收还需：(cd frontend && npx playwright install chromium)"
echo "配置模型后运行 bash scripts/start-bank-integration.sh"
