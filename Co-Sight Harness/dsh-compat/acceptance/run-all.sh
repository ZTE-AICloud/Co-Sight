#!/usr/bin/env bash
# run-all.sh — acceptance gate for cosight-plugin-compat.
#
#   bash dsh-compat/acceptance/run-all.sh
#
# 1. syntax-checks every source module (node --check, no execution)
# 2. verifies the four plugin payloads are present next to the package
# 3. runs the offline probe, which exercises the mount, shim, hook and
#    decision paths against stub dsh contexts and the real guard script
#
# Exit 0 means the package is safe to install; anything else is a hard stop.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$ROOT/.." && pwd)"
FAILED=0

step() { printf '\n== %s\n' "$1"; }
ok() { printf '   OK   %s\n' "$1"; }
bad() { printf '   FAIL %s\n' "$1"; FAILED=1; }

step "source syntax"
for file in "$ROOT"/src/*.mjs "$ROOT"/acceptance/*.mjs; do
  name="$(basename "$file")"
  if node --check "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
done

step "plugin payloads (repo root: $REPO)"
for plugin in agent-genesis agent-evaluator skill-optimizer cosight-bot; do
  if [ -d "$REPO/$plugin" ]; then ok "$plugin/"; else bad "$plugin/ missing"; fi
done

step "offline probe"
if node "$ROOT/acceptance/probe.mjs"; then ok "probe"; else bad "probe"; fi

step "result"
if [ "$FAILED" -eq 0 ]; then
  echo "PASS — cosight-plugin-compat is ready to install"
  exit 0
fi
echo "FAIL — fix the items above before installing"
exit 1
