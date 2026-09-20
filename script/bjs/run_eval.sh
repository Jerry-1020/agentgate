#!/bin/bash
# Synchronously execute a persisted evaluation Run by id.
# Usage: ./run_eval.sh <run_id>

set -euo pipefail
project_root="$(cd "$(dirname "$0")/../.." && pwd)"

if [ $# -ne 1 ]; then
    echo "Usage: $0 <run_id>"
    exit 1
fi

exec bash "$project_root/scripts/run.sh" execute-run "$1"
