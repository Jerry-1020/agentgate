#!/bin/bash
# Start AgentGate frontend and backend services.
# Reads AGENT_TASK_DISPATCHER_TYPE from .env to decide
# whether Redis and Celery are needed.

set -e

PROJECT_DIR="/Users/eric/hw/xql/pythonwork/agentgate"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
ENV_FILE="$PROJECT_DIR/.env"

# ---- Read dispatcher type from .env ----
DISPATCHER_TYPE="celery"
if [ -f "$ENV_FILE" ]; then
    value=$(grep '^AGENT_TASK_DISPATCHER_TYPE=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
    if [ -n "$value" ]; then
        DISPATCHER_TYPE="$value"
    fi
fi

echo "Task dispatcher type: $DISPATCHER_TYPE"

# ---- Export shared env ----
export PYTHONPATH="$PROJECT_DIR/src"

# ---- Export all active variables from .env ----
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;
        esac
        key=$(echo "$line" | cut -d= -f1 | tr -d '[:space:]')
        val=$(echo "$line" | cut -d= -f2-)
        if [ -n "$key" ]; then
            export "$key=$val"
        fi
    done < "$ENV_FILE"
fi

# ---- 1. Redis (only for celery) ----
if [ "$DISPATCHER_TYPE" = "celery" ]; then
    if ! redis-cli -p 6379 ping > /dev/null 2>&1; then
        echo "Starting Redis..."
        redis-server --port 6379 --daemonize yes
        sleep 1
        redis-cli ping
    else
        echo "Redis already running."
    fi
else
    echo "BJS mode: skipping Redis."
fi

# ---- 2. Celery worker (only for celery) ----
if [ "$DISPATCHER_TYPE" = "celery" ]; then
    if ! pgrep -f "celery.*agentgate.*worker" > /dev/null 2>&1; then
        echo "Starting Celery worker..."
        nohup "$VENV_PYTHON" -m celery \
            -A agentgate.integrations.job_dispatchers.celery:celery_app worker \
            --loglevel=INFO --concurrency=1 > /tmp/agentgate-celery.log 2>&1 &
        disown
        echo "  Celery PID: $!"
    else
        echo "Celery worker already running."
    fi
else
    echo "BJS mode: skipping Celery worker."
fi

# ---- 3. FastAPI (uvicorn) ----
if ! pgrep -f "uvicorn.*agentgate" > /dev/null 2>&1; then
    echo "Starting FastAPI (uvicorn)..."
    nohup "$VENV_PYTHON" -m uvicorn agentgate.server.app:app \
        --host 127.0.0.1 --port 8000 > /tmp/agentgate-api.log 2>&1 &
    disown
    echo "  Uvicorn PID: $!"
else
    echo "FastAPI already running."
fi

# ---- 4. Vite frontend ----
if ! pgrep -f "vite" > /dev/null 2>&1; then
    echo "Starting Vite frontend..."
    cd "$PROJECT_DIR/web"
    AGENTGATE_API_TARGET="http://127.0.0.1:8000" \
        nohup npm run dev > /tmp/agentgate-web.log 2>&1 &
    disown
    echo "  Vite PID: $!"
else
    echo "Vite already running."
fi

# ---- Wait and check ----
sleep 5
echo ""
echo "=== Status ==="
echo -n "Redis:  "
if [ "$DISPATCHER_TYPE" = "celery" ]; then
    redis-cli ping 2>&1
else
    echo "(not started)"
fi
echo -n "API:    "
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/docs 2>&1
echo ""
echo -n "Celery: "
if [ "$DISPATCHER_TYPE" = "celery" ]; then
    tail -1 /tmp/agentgate-celery.log 2>&1
else
    echo "(not started)"
fi
echo "Vite:   "
tail -1 /tmp/agentgate-web.log 2>&1
