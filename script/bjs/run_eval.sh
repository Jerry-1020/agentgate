#!/bin/bash
# Synchronously execute a persisted evaluation Run by id.
# Usage: ./run_eval.sh <run_id>

set -e

PROJECT_DIR="/Users/eric/hw/xql/pythonwork/agentgate"
PYTHON="$PROJECT_DIR/.venv/bin/python"
DB_PATH="$PROJECT_DIR/agentgate-demo.db"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <run_id>"
    exit 1
fi

RUN_ID="$1"

AGENTGATE_DB="$DB_PATH" "$PYTHON" "$PROJECT_DIR/script/bjs/run_evaluation.py" "$RUN_ID"
