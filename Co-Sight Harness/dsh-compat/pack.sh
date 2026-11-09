#!/usr/bin/env bash
# pack.sh — build a SELF-CONTAINED dsh plugin tarball for the four cosight
# Claude plugins (agent-genesis, agent-evaluator/goldeval, skill-optimizer,
# cosight-bot).
#
# The artifact embeds every plugin's resources VERBATIM (copied, never
# modified) into plugin-assets/ together with this bridge, so anyone with dsh
# installed can:
#
#   dsh plugin --profile <name> add file:dist/cosight-dsh-plugins-<ver>.tgz
#
# and get skills + commands + agent roles + hooks WITHOUT cloning this repo.
#
# Output:  dsh-compat/dist/cosight-dsh-plugins-<version>.tgz  (+ staging dir)
#
# Usage:   bash dsh-compat/pack.sh [--out DIR] [--skip-verify]
# Env:     OUT, SKIP_VERIFY
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGINS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="${OUT:-$SCRIPT_DIR/dist}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"
for arg in "$@"; do
  case "$arg" in
    --skip-verify) SKIP_VERIFY=1 ;;
    --out=*) OUT="${arg#--out=}" ;;
    --help|-h) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

PLUGIN_LIST=(agent-genesis agent-evaluator skill-optimizer cosight-bot)

echo "[pack] plugins root   = $PLUGINS_ROOT"
echo "[pack] output         = $OUT"

# ---- sanity: every plugin payload is present -------------------------------
for plugin in "${PLUGIN_LIST[@]}"; do
  [ -d "$PLUGINS_ROOT/$plugin" ] || { echo "ERROR: $PLUGINS_ROOT/$plugin missing" >&2; exit 1; }
  [ -d "$PLUGINS_ROOT/$plugin/skills" ] || { echo "ERROR: $plugin/skills missing" >&2; exit 1; }
done

# ---- versions --------------------------------------------------------------
read -r BASE_VER GENESIS_VER EVAL_VER SKILLX_VER BOT_VER < <(python3 - "$SCRIPT_DIR/package.json" "$PLUGINS_ROOT" <<'PY'
import json, os, sys
base = json.load(open(sys.argv[1], encoding="utf-8"))
root = sys.argv[2]
def ver(plugin):
    try:
        manifest = json.load(open(os.path.join(root, plugin, ".claude-plugin", "plugin.json"), encoding="utf-8"))
        return manifest.get("version", "0.0.0")
    except Exception:
        return "0.0.0"
print(base.get("version", "0.0.0"), ver("agent-genesis"), ver("agent-evaluator"), ver("skill-optimizer"), ver("cosight-bot"))
PY
)
FULL_VER="${BASE_VER}-dsh.0"
PKG_NAME="cosight-plugin-compat"
STAGE="$OUT/$PKG_NAME-$FULL_VER"
TGZ="$OUT/cosight-dsh-plugins-$FULL_VER.tgz"

echo "[pack] bridge version = $FULL_VER"
echo "[pack] embedded: agent-genesis $GENESIS_VER | agent-evaluator $EVAL_VER | skill-optimizer $SKILLX_VER | cosight-bot $BOT_VER"

# ---- gate: run the acceptance suite before packaging -----------------------
if [ "$SKIP_VERIFY" = 0 ]; then
  echo "[pack] acceptance gate (dsh-compat/acceptance/run-all.sh)"
  bash "$SCRIPT_DIR/acceptance/run-all.sh" >/dev/null || { echo "ERROR: acceptance failed; run it directly to see why" >&2; exit 1; }
  echo "[pack] acceptance: PASS"
fi

# ---- staging ---------------------------------------------------------------
# Start from a clean stage so removed or renamed files never linger in the artifact.
rm -rf "${STAGE:?}"
mkdir -p "$STAGE/src" "$STAGE/acceptance" "$STAGE/plugin-assets"

cp "$SCRIPT_DIR"/src/*.mjs "$STAGE/src/"
cp "$SCRIPT_DIR"/acceptance/*.mjs "$STAGE/acceptance/"
cp "$SCRIPT_DIR"/acceptance/*.sh "$STAGE/acceptance/"
cp "$SCRIPT_DIR/bundle.patch.yml" "$SCRIPT_DIR/cordis.patch.yml" "$STAGE/"
for doc in README.md; do
  [ -f "$SCRIPT_DIR/$doc" ] && cp "$SCRIPT_DIR/$doc" "$STAGE/"
done
[ -f "$PLUGINS_ROOT/LICENSE" ] && cp "$PLUGINS_ROOT/LICENSE" "$STAGE/LICENSE"

python3 - "$SCRIPT_DIR/package.json" "$STAGE/package.json" "$FULL_VER" "$GENESIS_VER" "$EVAL_VER" "$SKILLX_VER" "$BOT_VER" <<'PY'
import json, sys
src, dst, full, genesis, evaluator, skillx, bot = sys.argv[1:8]
pkg = json.load(open(src, encoding="utf-8"))
pkg["version"] = full
pkg["description"] = (
    (pkg.get("description") or "")
    + f" Self-contained dsh package embedding agent-genesis {genesis}, "
      f"agent-evaluator {evaluator}, skill-optimizer {skillx} and cosight-bot {bot} "
      f"(plugin sources untouched)."
)
with open(dst, "w", encoding="utf-8") as handle:
    json.dump(pkg, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY

# ---- embed plugin resources verbatim --------------------------------------
# Copy every top-level entry except caches/tests: commands reference scripts/,
# references/, framework_configs/ and config/ by relative path, so a narrow
# allow-list would break them at run time.
echo "[pack] copying plugin resources -> plugin-assets/"
for plugin in "${PLUGIN_LIST[@]}"; do
  mkdir -p "$STAGE/plugin-assets/$plugin"
  ( cd "$PLUGINS_ROOT/$plugin" && \
      find . -mindepth 1 -maxdepth 1 \
        ! -name 'tests' ! -name '.git' ! -name 'node_modules' \
        ! -name '__pycache__' ! -name '.pytest_cache' ! -name '.mypy_cache' \
        ! -name 'dist' ! -name '.venv' ! -name '*.pyc' -print0 | \
      tar --null -cf - -T - ) | \
    tar -C "$STAGE/plugin-assets/$plugin" -xf -
done
# belt-and-braces: no bytecode caches anywhere in the artifact
find "$STAGE" \( -name '__pycache__' -type d \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true

# ---- structural self-check -------------------------------------------------
n_skills=$(find "$STAGE/plugin-assets" -mindepth 4 -maxdepth 4 -name SKILL.md | wc -l)
n_agents=$(find "$STAGE/plugin-assets" -mindepth 3 -maxdepth 3 -path '*/agents/*.md' | wc -l)
n_commands=$(find "$STAGE/plugin-assets" -mindepth 3 -maxdepth 3 -path '*/commands/*.md' | wc -l)
n_hooks=$(find "$STAGE/plugin-assets" -name hooks.json | wc -l)
echo "[pack] self-check: skills=$n_skills agents=$n_agents commands=$n_commands hooks=$n_hooks"
[ "$n_skills" -ge 10 ] || { echo "ERROR: expected >=10 skills embedded" >&2; exit 1; }
[ "$n_agents" -ge 20 ] || { echo "ERROR: expected >=20 agent roles embedded" >&2; exit 1; }
[ "$n_commands" -ge 6 ] || { echo "ERROR: expected >=6 commands embedded" >&2; exit 1; }
[ "$n_hooks" -ge 1 ] || { echo "ERROR: no hooks.json embedded" >&2; exit 1; }

# ---- advertise self-contained mode in the staged bundle patch --------------
python3 - "$STAGE/bundle.patch.yml" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
if "pluginsRoot: AUTO" not in text:
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("# pluginsRoot:"):
            lines.append("        pluginsRoot: AUTO   # self-contained: assets live in plugin-assets/")
        else:
            lines.append(line)
    text = "\n".join(lines) + "\n"
open(path, "w", encoding="utf-8").write(text)
PY

# ---- verify: the probe must pass against the STAGED layout ----------------
echo "[pack] verifying staged package (plugin-assets layout)"
if ! node "$STAGE/acceptance/probe.mjs" >"$OUT/.probe-$FULL_VER.log" 2>&1; then
  echo "ERROR: staged probe failed:" >&2
  tail -30 "$OUT/.probe-$FULL_VER.log" >&2
  exit 1
fi
tail -3 "$OUT/.probe-$FULL_VER.log"
rm -f "$OUT/.probe-$FULL_VER.log"

# ---- tarball ---------------------------------------------------------------
echo "[pack] tarball: $TGZ"
tar -C "$OUT" -czf "$TGZ" "$(basename "$STAGE")"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$TGZ" | tee "$TGZ.sha256"
else
  shasum -a 256 "$TGZ" | tee "$TGZ.sha256"
fi
du -h "$TGZ"
echo
echo "[pack] DONE. Install anywhere with dsh:"
echo "    dsh plugin --profile <name> add file:$TGZ"
echo "    # then add the config block (see $STAGE/bundle.patch.yml comments) or run"
echo "    #   bash install-dsh.sh --pkg $TGZ"
echo "    # and restart dsh."
