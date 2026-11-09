#!/usr/bin/env bash
# pack.sh — build a self-contained dsh plugin tarball for drive.
#
# The artifact embeds drive's runtime assets (hooks/, skills/, agents/) VERBATIM
# (copied, never modified) together with the drive-compat bridge, so anyone with
# dsh installed can `dsh plugin add file:<tgz>` (or use install.sh --pkg) and get
# the full drive workflow WITHOUT needing the drive repo itself.
#
# Output:  dist/drive-dsh-plugin-<version>.tgz   (+ staging dir)
#
# Usage:  bash drive-compat/pack.sh [--out DIR] [--skip-verify]
# Env:    OUT, SKIP_VERIFY
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"           # drive repo root (drive drive-compat is a child)
OUT="${OUT:-$SCRIPT_DIR/dist}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"
for a in "$@"; do
  case "$a" in
    --skip-verify) SKIP_VERIFY=1 ;;
    --out=*) OUT="${a#--out=}" ;;
    --help|-h) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  esac
done

# ---- version ---------------------------------------------------------------
VER="$(python3 - "$DRIVE_ROOT/.claude-plugin/plugin.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get("version", "0.0.0"))
except Exception:
    print("0.0.0")
PY
)"
FULL_VER="${VER}-dsh.0"
PKG_NAME="drive-compat"
STAGE="$OUT/$PKG_NAME-$FULL_VER"
TGZ="$OUT/drive-dsh-plugin-$FULL_VER.tgz"

echo "[pack] drive version      = $VER"
echo "[pack] package version    = $FULL_VER"
echo "[pack] source drive root  = $DRIVE_ROOT"
echo "[pack] output             = $OUT"

# ---- sanity: drive payload present ----------------------------------------
for d in hooks skills agents; do
  [ -d "$DRIVE_ROOT/$d" ] || { echo "ERROR: drive/$d missing" >&2; exit 1; }
done
[ -f "$DRIVE_ROOT/hooks/planning_write_guard.py" ] || { echo "ERROR: hooks look incomplete" >&2; exit 1; }

# ---- staging ---------------------------------------------------------------
mkdir -p "$STAGE/src" "$STAGE/acceptance" "$STAGE/drive-assets"
rm -rf "$STAGE/src"/* "$STAGE/acceptance"/* "$STAGE/drive-assets"/* 2>/dev/null || true

cp "$SCRIPT_DIR"/src/*.mjs "$STAGE/src/"
cp "$SCRIPT_DIR"/acceptance/*.mjs "$STAGE/acceptance/"
cp "$SCRIPT_DIR"/acceptance/run-all.sh "$STAGE/acceptance/"
# bundle patch keeps name: ./src/index.mjs (relative to package root at install time)
cp "$SCRIPT_DIR/bundle.patch.yml" "$STAGE/bundle.patch.yml"
# docs
cp "$SCRIPT_DIR/README.md" "$SCRIPT_DIR/QUICKSTART.md" "$STAGE/" 2>/dev/null || true
[ -f "$DRIVE_ROOT/LICENSE" ] && cp "$DRIVE_ROOT/LICENSE" "$STAGE/LICENSE"

# generate package.json (name stays drive-compat; version carries the dsh suffix)
python3 - "$SCRIPT_DIR/package.json" "$STAGE/package.json" "$FULL_VER" "$VER" <<'PY'
import json, sys
base = json.load(open(sys.argv[1]))
out  = json.load(open(sys.argv[1]))
out["version"] = sys.argv[3]
out["description"] = (out.get("description") or "") + f" Self-contained dsh plugin for drive v{sys.argv[4]} (drive hooks/skills/agents embedded, drive source untouched)."
with open(sys.argv[2], "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

# embed drive runtime assets verbatim (copies only; drive repo is never modified)
# -- use `find` white-listing (not tar --exclude) so nested __pycache__/pyc
#    caches can never leak into the artifact.
echo "[pack] copying drive assets -> drive-assets/"
( cd "$DRIVE_ROOT" && \
    find hooks skills agents -type f \
      ! -path '*/__pycache__/*' \
      ! -name '*.pyc' ! -name '*.pyo' \
      ! -path '*/.git/*' ! -path '*/.drive*' \
    | tar -C "$DRIVE_ROOT" -T - -cf - ) \
  | tar -C "$STAGE/drive-assets" -xf -

# ---- structural self-check -------------------------------------------------
n_skills=$(find "$STAGE/drive-assets/skills" -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l)
n_agents=$(ls "$STAGE/drive-assets/agents"/*.md 2>/dev/null | wc -l)
n_hooks=$(ls "$STAGE/drive-assets/hooks"/*.py 2>/dev/null | wc -l)
echo "[pack] self-check: skills=$n_skills agents=$n_agents hook_py=$n_hooks"
[ "$n_skills" -ge 1 ] || { echo "ERROR: no skills embedded" >&2; exit 1; }
[ "$n_agents" -ge 1 ] || { echo "ERROR: no agents embedded" >&2; exit 1; }
[ "$n_hooks" -ge 5 ]  || { echo "ERROR: hooks incomplete" >&2; exit 1; }

# ---- verify guards against the STAGED assets (drive-assets = new driveRoot) -
# Remember: running the python guards here would leave __pycache__ behind, so
# disable bytecode + cache writes for the whole verify phase.
if [ "$SKIP_VERIFY" = 0 ]; then
  export PYTHONDONTWRITEBYTECODE=1
  echo "[pack] verifying staged guards (probe-core --drive-root <stage>/drive-assets) ..."
  WS="$(mktemp -d -t drive-pack-verify.XXXXXX)"
  node "$STAGE/acceptance/probe-core.mjs" --drive-root "$STAGE/drive-assets" \
      >"$WS/probe.log" 2>&1 || { echo "probe failed:"; cat "$WS/probe.log"; rm -rf "$WS"; exit 1; }
  grep -q "ALL PROBES PASSED" "$WS/probe.log" || { echo "probes not all passed:"; cat "$WS/probe.log"; rm -rf "$WS"; exit 1; }
  echo "[pack] staged guards: ALL PROBES PASSED"
  rm -rf "$WS"
fi
# belt-and-braces: drop any bytecode cache that sneaked into staging
find "$STAGE" \( -name '__pycache__' -type d \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true

# update the bundle patch to advertise self-contained mode (driveRoot: AUTO)
python3 - "$STAGE/bundle.patch.yml" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
if "driveRoot: AUTO" not in s:
    s = s.replace(
        "        # driveRoot: /absolute/path/to/drive   # <-- managed by install.sh in deployment mode",
        "        driveRoot: AUTO   # self-contained: assets live in this package's drive-assets/",
    )
open(p, "w").write(s)
PY

# ---- tarball ----------------------------------------------------------------
echo "[pack] tarball: $TGZ"
tar -C "$OUT" -czf "$TGZ" "$(basename "$STAGE")"
shasum -a 256 "$TGZ" | tee "$TGZ.sha256"
du -h "$TGZ"
echo
echo "[pack] DONE. Install anywhere with dsh:"
echo "    dsh plugin --profile <name> add file:$TGZ"
echo "    # or: bash <unstaged>/drive-compat/install.sh --pkg $TGZ"
echo "    # then restart dsh."
