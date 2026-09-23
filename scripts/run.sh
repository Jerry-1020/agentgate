#!/usr/bin/env bash
set -euo pipefail
revision_root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$revision_root/runtime"
export AGENTGATE_REDIS_MODE="${AGENTGATE_REDIS_MODE:-single}"
export AGENTGATE_REDIS_URL="${AGENTGATE_REDIS_URL:-redis://127.0.0.1:6397/0}"
export PYTHONPATH="$revision_root/src"

_stop_service() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping existing process matching '$pattern' (pid: $(echo "$pids" | tr '\n' ' '))"
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
      sleep 1
    fi
  fi
}

# Private per-user model configuration is deliberately outside the project/package.
case "${1:-}" in
  api|worker|scheduler|web|seed|verify-traces|execute-run|dispatch-due|dispatcher-type)
    model_env_file="${AGENTGATE_MODEL_ENV_FILE:-$revision_root/.env}"
    if [[ -f "$model_env_file" ]]; then
      set -a
      source "$model_env_file"
      set +a
    fi
    ;;
esac
export AGENTGATE_DB="${AGENTGATE_DB-$revision_root/runtime/agentgate.db}"

# 行外（本地虚拟）模式的平台执行后端；行内部署时由环境变量覆盖。
export AGENTGATE_AGENT_PLATFORM_MODE="${AGENTGATE_AGENT_PLATFORM_MODE-mock}"
export AGENTGATE_AGENT_PLATFORM_ORIGIN="${AGENTGATE_AGENT_PLATFORM_ORIGIN-http://127.0.0.1:8119}"
# 平台 token 凭据加密主密钥：api 提交与 worker 执行必须共享同一密钥。
if [[ -z "${AGENTGATE_API_KEY_ENCRYPTION_KEY:-}" ]]; then
  key_file="$revision_root/runtime/credential.key"
  if [[ ! -f "$key_file" ]]; then
    umask 077
    printf '%s' "$("$revision_root/.venv/bin/python" -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" > "$key_file"
  fi
  export AGENTGATE_API_KEY_ENCRYPTION_KEY="$(cat "$key_file")"
fi


_log_dir="${AGENTGATE_LOG_PATH:-$revision_root/runtime/logs}"
mkdir -p "$_log_dir"

case "${1:-}" in
  dispatcher-type) cd "$revision_root"; exec .venv/bin/python -c 'from agentgate.integrations.job_dispatchers.configuration import load_dispatcher_type; print(load_dispatcher_type())' ;;
  execute-run) cd "$revision_root"; shift; exec .venv/bin/python scripts/bjs/run_evaluation.py "$@" ;;
  dispatch-due) cd "$revision_root"; shift; exec .venv/bin/python scripts/dispatch-scheduled-runs.py --once "$@" ;;
  seed) cd "$revision_root"; exec .venv/bin/python scripts/seed-bank-agents.py ;;
  verify-traces) cd "$revision_root"; shift; exec .venv/bin/python scripts/verify-bank-traces.py "$@" ;;
  redis) exec redis-server --bind 127.0.0.1 --port 6397 --dir "$revision_root/runtime" --save '' --appendonly no >> "$_log_dir/redis.log" 2>&1 ;;
  api) _stop_service "uvicorn agentgate.server.app"; cd "$revision_root"; exec .venv/bin/python -m uvicorn agentgate.server.app:app --host 127.0.0.1 --port 8097 >> "$_log_dir/api.log" 2>&1 ;;
  worker) _stop_service "celery.*agentgate.*--hostname=unified-tasks-20260915"; cd "$revision_root"; exec .venv/bin/python -m celery -A agentgate.integrations.job_dispatchers.celery:celery_app worker --pool=solo --concurrency=1 --hostname=unified-tasks-20260915@%h --loglevel=INFO >> "$_log_dir/worker.log" 2>&1 ;;
  web) cd "$revision_root/frontend"; export FRONTEND_PORT=5197 API_PROXY_TARGET=http://127.0.0.1:8097; exec npm run dev >> "$_log_dir/web.log" 2>&1 ;;
  scheduler)
    cd "$revision_root"
    _stop_service "celery.*agentgate.*--beat"
    _stop_service "dispatch-scheduled-runs"
    dispatcher_type="$(.venv/bin/python -c 'from agentgate.integrations.job_dispatchers.configuration import load_dispatcher_type; print(load_dispatcher_type())')"
    if [[ "$dispatcher_type" == bjs ]]; then
      exec .venv/bin/python scripts/dispatch-scheduled-runs.py >> "$_log_dir/scheduler.log" 2>&1
    fi
    exec .venv/bin/python -m celery -A agentgate.integrations.job_dispatchers.celery:celery_app worker --pool=solo --concurrency=1 --queues=agentgate.scheduler --beat --schedule="$revision_root/runtime/scheduler-state" --hostname=unified-tasks-scheduler-20260915@%h --loglevel=INFO >> "$_log_dir/scheduler.log" 2>&1
    ;;
  stop)
    shift
    targets=("${@:-api worker scheduler redis web}")
    for t in "${targets[@]}"; do
      case "$t" in
        api) _stop_service "uvicorn agentgate.server.app" ;;
        worker) _stop_service "celery.*agentgate.*--hostname=unified-tasks-20260915" ;;
        scheduler)
          _stop_service "dispatch-scheduled-runs"
          _stop_service "celery.*agentgate.*--beat"
          ;;
        redis) _stop_service "redis-server.*6397" ;;
        web) _stop_service "vite.*5197|npm run dev" ;;
        all)
          _stop_service "uvicorn agentgate.server.app"
          _stop_service "celery.*agentgate"
          _stop_service "dispatch-scheduled-runs"
          _stop_service "redis-server.*6397"
          _stop_service "vite.*5197|npm run dev"
          ;;
        *) echo "unknown service: $t"; exit 2 ;;
      esac
    done
    exit 0
    ;;
  bank-agents) cd "$revision_root/tested-agents"; exec .venv/bin/python run.py --model-env "${AGENTGATE_MODEL_ENV_FILE:-$revision_root/.env}" --use-agentgate-model ;;
  *) printf 'Usage: bash scripts/run.sh {stop|api|worker|scheduler|web|redis|bank-agents|seed|verify-traces|execute-run|dispatch-due|dispatcher-type}\n'; exit 2 ;;
esac
