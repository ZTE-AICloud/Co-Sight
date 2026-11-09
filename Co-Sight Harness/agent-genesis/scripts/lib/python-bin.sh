#!/usr/bin/env bash
# scripts/lib/python-bin.sh
# Resolve a Python interpreter >= 3.8 without assuming the binary name.
#
# Why: some hosts ship `python` = 3.11 and `python3` = 3.6 (or no `python3` at
# all). Hardcoding either name makes the pipeline host-dependent.
#
# Usage:
#   source "$(dirname "$0")/lib/python-bin.sh"
#   "$PYTHON_BIN" script.py
#
# Override: set AG_PYTHON to force a specific interpreter.

AG_PY_MIN_MAJOR=3
AG_PY_MIN_MINOR=8

_ag_python_ok() {
  local candidate="$1"
  [ -n "$candidate" ] || return 1
  command -v "$candidate" >/dev/null 2>&1 || return 1
  "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (${AG_PY_MIN_MAJOR}, ${AG_PY_MIN_MINOR}) else 1)" >/dev/null 2>&1
}

PYTHON_BIN=""
for _ag_candidate in "${AG_PYTHON:-}" python python3 py; do
  if _ag_python_ok "$_ag_candidate"; then
    PYTHON_BIN="$(command -v "$_ag_candidate")"
    break
  fi
done
unset _ag_candidate

# PYTHON_BIN is empty when no suitable interpreter exists; callers must检查并失败退出。
export PYTHON_BIN
