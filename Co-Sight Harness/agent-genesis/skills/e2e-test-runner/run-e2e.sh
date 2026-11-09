#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_FILE="${SCRIPT_DIR}/task/suite.yaml"

if [ ! -f "$TASK_FILE" ]; then
  echo "ERROR: task/suite.yaml not found at $TASK_FILE"
  exit 1
fi

exec python3 "${SCRIPT_DIR}/scripts/run_e2e.py" --task-file "$TASK_FILE"
