#!/usr/bin/env bash
set -euo pipefail
revision_root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$revision_root/runtime"
export AGENTGATE_DB="$revision_root/runtime/agentgate.db"
export AGENTGATE_REDIS_URL="redis://127.0.0.1:6397/0"
export PYTHONPATH="$revision_root/src"
# Private per-user model configuration is deliberately outside the project/package.
case "${1:-}" in
  api|worker|scheduler)
    model_env_file="${AGENTGATE_MODEL_ENV_FILE:-$revision_root/.env}"
    if [[ -f "$model_env_file" ]]; then
      set -a
      source "$model_env_file"
      set +a
    fi
    ;;
esac
case "${1:-}" in
  redis) exec redis-server --bind 127.0.0.1 --port 6397 --dir "$revision_root/runtime" --save '' --appendonly no ;;
  api) cd "$revision_root"; exec .venv/bin/python -m uvicorn agentgate.server.app:app --host 127.0.0.1 --port 8097 ;;
  worker) cd "$revision_root"; exec .venv/bin/python -m celery -A agentgate.integrations.job_dispatchers.celery:celery_app worker --pool=solo --concurrency=1 --hostname=unified-tasks-20260915@%h --loglevel=INFO ;;
  scheduler) cd "$revision_root"; exec .venv/bin/python -m celery -A agentgate.integrations.job_dispatchers.celery:celery_app worker --pool=solo --concurrency=1 --queues=agentgate.scheduler --beat --schedule="$revision_root/runtime/scheduler-state" --hostname=unified-tasks-scheduler-20260915@%h --loglevel=INFO ;;
  web) cd "$revision_root/frontend"; export FRONTEND_PORT=5197 API_PROXY_TARGET=http://127.0.0.1:8097; exec npm run dev ;;
  bank-agents) cd "$revision_root/tested-agents"; exec .venv/bin/python run.py --model-env "${AGENTGATE_MODEL_ENV_FILE:-$revision_root/.env}" --use-agentgate-model ;;
  *) printf 'Usage: bash scripts/run.sh {redis|api|worker|scheduler|web|bank-agents}\n'; exit 2 ;;
esac
