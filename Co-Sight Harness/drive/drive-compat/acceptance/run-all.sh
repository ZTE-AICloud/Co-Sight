#!/usr/bin/env bash
# run-all.sh — drive-compat acceptance suite.
#   1) probe-core.mjs   : pre-execute wire contracts (deny / audit / ask)
#   2) verify-apply.mjs : full apply() wiring (skills / shims / listener)
# Exit 0 = all pass.
set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1   # drive repo root
DRIVE_ROOT="$PWD"

# Drive guards read cwd to locate .drive; run from a throwaway workspace
# (neutral — does not depend on any pre-existing repo directory).
WS="${DRIVE_COMPAT_WS:-$(mktemp -d -t drive-compat-probe.XXXXXX)}"
mkdir -p "$WS/.drive"
trap 'rm -rf "$WS"' EXIT

export DRIVE_COMPAT_DRIVE_ROOT="$DRIVE_ROOT"
RC=0

pushd "$WS" >/dev/null || exit 1
node "$DRIVE_ROOT/drive-compat/acceptance/probe-core.mjs" --drive-root "$DRIVE_ROOT" || RC=1
popd >/dev/null || true

node "$DRIVE_ROOT/drive-compat/acceptance/verify-apply.mjs" || RC=1

exit "$RC"
