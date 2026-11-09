#!/usr/bin/env bash
# install-dsh.sh — install ALL FIVE cosight plugins into a DeepSeek Harness
# (dsh) profile in one idempotent step:
#
#   drive              -> via drive-compat         (bundle: drive-compat)
#   agent-genesis   \
#   agent-evaluator  \
#   skill-optimizer   > via cosight-plugin-compat  (bundle: cosight-plugin-compat)
#   cosight-bot      /
#
# Claude plugin sources are never modified; the two compat packages mount
# their skills / commands / agents / hooks through the dsh composition API.
#
# Usage
#   bash install-dsh.sh                          # profile 'web', dev repo mode
#   bash install-dsh.sh --profile mylab          # another profile
#   bash install-dsh.sh --dsh-source <dsh-repo>  # dsh run from a source checkout
#   bash install-dsh.sh --verify                 # also dump the composed tree
#   bash install-dsh.sh --uninstall              # remove both bundles + blocks
#   bash install-dsh.sh --dry-run                # show every action, write nothing
#
# Options
#   --profile <name>        dsh profile to install into        (default: web)
#   --dsh <command>         explicit dsh command, e.g. "pnpm dsh"
#   --dsh-source <dir>      source checkout; runs
#                           `node --import tsx/esm apps/cli/src/bin.ts`
#   --plugins-root <dir>    repo holding the four plugin dirs   (default: this dir)
#   --drive-root <dir>      drive repo root                     (default: this/drive)
#   --no-drive              skip drive-compat
#   --no-plugins            skip cosight-plugin-compat
#   --pkg <tgz>             install cosight-plugin-compat from a self-contained
#                           tarball (dsh-compat/pack.sh) instead of the repo
#   --drive-pkg <tgz>       same, for drive-compat (drive/drive-compat/pack.sh)
#   --dev-patch             do not install bundles; print the --patch launch line
#   --port <n>              port used only in the restart hint  (default: 3080)
#   --dry-run | --force | --uninstall | --verify | -h|--help
#
# Env: PROFILE, DSH_SOURCE_DIR, DSH_HOME, COSIGHT_COMPAT_PLUGINS_ROOT
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${PROFILE:-web}"
PLUGINS_ROOT="${COSIGHT_COMPAT_PLUGINS_ROOT:-$SCRIPT_DIR}"
DRIVE_ROOT="$SCRIPT_DIR/drive"
PORT="3080"
DSH_CMD_OPT=""
DSH_SOURCE="${DSH_SOURCE_DIR:-}"
COMPAT_PKG=""
DRIVE_PKG=""
DO_DRIVE=1
DO_PLUGINS=1
DEV_PATCH=0
DRY_RUN=0
FORCE=0
UNINSTALL=0
VERIFY=0

DRIVE_PKG_DIR="$DRIVE_ROOT/drive-compat"
COMPAT_PKG_DIR="$PLUGINS_ROOT/dsh-compat"
DRIVE_BUNDLE="drive-compat"
COMPAT_BUNDLE="cosight-plugin-compat"

usage() { sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; }
info() { printf '[dsh-install] %s\n' "$*"; }
warn() { printf '[dsh-install][warn] %s\n' "$*" >&2; }
die()  { printf '[dsh-install][error] %s\n' "$*" >&2; exit 1; }
say()  { printf '%s\n' "$*"; }
# Echo a command instead of running it under --dry-run.
x() {
  if [ "$DRY_RUN" = 1 ]; then say "(dry-run) $*"; else "$@"; fi
}

# ---- arguments ------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --dsh) DSH_CMD_OPT="$2"; shift 2 ;;
    --dsh-source) DSH_SOURCE="$2"; shift 2 ;;
    --plugins-root) PLUGINS_ROOT="$2"; shift 2 ;;
    --drive-root) DRIVE_ROOT="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --pkg) COMPAT_PKG="$2"; shift 2 ;;
    --drive-pkg) DRIVE_PKG="$2"; shift 2 ;;
    --no-drive) DO_DRIVE=0; shift ;;
    --no-plugins) DO_PLUGINS=0; shift ;;
    --dev-patch) DEV_PATCH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --verify) VERIFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

[ "$DO_DRIVE" = 1 ] || [ "$DO_PLUGINS" = 1 ] || die "both --no-drive and --no-plugins given; nothing to do"
if [ "$DEV_PATCH" = 1 ] && { [ -n "$COMPAT_PKG" ] || [ -n "$DRIVE_PKG" ]; }; then
  die "--dev-patch loads overlays from this checkout and cannot be combined with --pkg/--drive-pkg"
fi
if [ -n "$COMPAT_PKG" ] && [ "$DO_PLUGINS" = 0 ]; then
  warn "--pkg ignored because --no-plugins was given"
fi
if [ -n "$DRIVE_PKG" ] && [ "$DO_DRIVE" = 0 ]; then
  warn "--drive-pkg ignored because --no-drive was given"
fi

COMPAT_PKG_DIR="$PLUGINS_ROOT/dsh-compat"
DRIVE_PKG_DIR="$DRIVE_ROOT/drive-compat"

# Optional self-contained tarballs replace the repo directories. Their assets
# ship inside the package, so the patch must say AUTO instead of a repo path
# (the bundle is copied into the profile and cannot see this checkout).
COMPAT_TARGET="file:$COMPAT_PKG_DIR"
DRIVE_TARGET="file:$DRIVE_PKG_DIR"
COMPAT_CFG_ROOT="$PLUGINS_ROOT"
DRIVE_CFG_ROOT="$DRIVE_ROOT"
if [ -n "$COMPAT_PKG" ]; then
  COMPAT_TARGET="file:$COMPAT_PKG"
  COMPAT_CFG_ROOT="AUTO"
fi
if [ -n "$DRIVE_PKG" ]; then
  DRIVE_TARGET="file:$DRIVE_PKG"
  DRIVE_CFG_ROOT="AUTO"
fi

# ---- where does dsh come from? --------------------------------------
# 1) --dsh "<command>"   2) global `dsh` on PATH
# 3) --dsh-source / DSH_SOURCE_DIR source checkout (tsx runner)
# 4) this machine's checkout, if present
DSH_MODE=""
if [ -n "$DSH_CMD_OPT" ]; then
  DSH_MODE="custom"
  read -r -a DSH_ARGV <<< "$DSH_CMD_OPT"
elif command -v dsh >/dev/null 2>&1; then
  DSH_MODE="path"
  DSH_ARGV=(dsh)
elif [ -n "$DSH_SOURCE" ]; then
  [ -f "$DSH_SOURCE/apps/cli/src/bin.ts" ] \
    || die "--dsh-source is not a dsh checkout: $DSH_SOURCE (missing apps/cli/src/bin.ts)"
  DSH_MODE="source"
elif [ -f "$HOME/文档/Co-sight Harness/apps/cli/src/bin.ts" ]; then
  DSH_MODE="source"
  DSH_SOURCE="$HOME/文档/Co-sight Harness"
else
  die "no dsh runner found. Put 'dsh' on PATH, or pass --dsh-source <dsh-repo> (a checkout with apps/cli/src/bin.ts)."
fi

dsh_run() {
  if [ "$DSH_MODE" = "source" ]; then
    ( cd "$DSH_SOURCE" && node --import tsx/esm apps/cli/src/bin.ts "$@" )
  else
    "${DSH_ARGV[@]}" "$@"
  fi
}
dsh_label() {
  if [ "$DSH_MODE" = "source" ]; then
    printf 'node --import tsx/esm apps/cli/src/bin.ts %s   # cwd %s' "$*" "$DSH_SOURCE"
  else
    printf '%s %s' "${DSH_ARGV[*]}" "$*"
  fi
}
x_dsh() {
  if [ "$DRY_RUN" = 1 ]; then say "(dry-run) $(dsh_label "$@")"; else dsh_run "$@"; fi
}

PROFILE_DIR="${DSH_HOME:-$HOME/.dsh}/profiles/$PROFILE"
MANIFEST="$PROFILE_DIR/package.json"

bundle_installed() { # $1 = bundle name
  [ -f "$MANIFEST" ] || return 1
  python3 - "$MANIFEST" "$1" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
bundles = (data.get("dsh", {}).get("profile", {}).get("bundles") or [])
sys.exit(0 if sys.argv[2] in bundles else 1)
PY
}

patch_file() {
  local candidate
  for candidate in "$PROFILE_DIR/cordis.patch.yml" "$PROFILE_DIR/cordis.yml"; do
    if [ -f "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  printf '%s\n' "$PROFILE_DIR/cordis.patch.yml"
}

# ---- preflight ------------------------------------------------------
info "profile: $PROFILE   dsh runner: $DSH_MODE"
if [ "$DSH_MODE" = "source" ]; then say "  source: $DSH_SOURCE"; fi

if [ "$DO_DRIVE" = 1 ]; then
  if [ -n "$DRIVE_PKG" ]; then
    [ -f "$DRIVE_PKG" ] || die "--drive-pkg tarball not found: $DRIVE_PKG"
    # grep -c reads the whole stream; `tar | grep -q` would SIGPIPE tar under pipefail.
    hits="$(tar tzf "$DRIVE_PKG" 2>/dev/null | grep -c 'drive-assets/hooks/planning_write_guard.py')"
    [ "${hits:-0}" -ge 1 ] || die "$DRIVE_PKG is not a drive-compat self-contained package"
  elif [ ! -d "$DRIVE_ROOT/hooks" ] || [ ! -d "$DRIVE_ROOT/skills" ] || [ ! -f "$DRIVE_PKG_DIR/package.json" ]; then
    die "drive payload not found under $DRIVE_ROOT (need hooks/, skills/, drive-compat/package.json). Pass --drive-root, or --no-drive."
  fi
fi
if [ "$DO_PLUGINS" = 1 ]; then
  if [ -n "$COMPAT_PKG" ]; then
    [ -f "$COMPAT_PKG" ] || die "--pkg tarball not found: $COMPAT_PKG"
    hits="$(tar tzf "$COMPAT_PKG" 2>/dev/null | grep -c 'plugin-assets/agent-genesis/skills/')"
    [ "${hits:-0}" -ge 1 ] || die "$COMPAT_PKG is not a cosight-plugin-compat self-contained package"
  else
    [ -f "$COMPAT_PKG_DIR/package.json" ] \
      || die "cosight-plugin-compat not found at $COMPAT_PKG_DIR. Pass --plugins-root, or --no-plugins."
    for plugin in agent-genesis agent-evaluator skill-optimizer cosight-bot; do
      if [ ! -d "$PLUGINS_ROOT/$plugin" ]; then
        warn "$PLUGINS_ROOT/$plugin is missing; that plugin will be skipped at mount time"
      fi
    done
  fi
fi

# ---- patch block management ----------------------------------------
# Both blocks are marker-guarded. drive-compat keeps the exact markers its own
# install.sh uses, so running either installer never duplicates the block.
# The compat block carries pluginsRoot because `dsh plugin add` COPIES the
# package into the profile (no repo-relative inference possible).
write_patch_blocks() {
  local file
  file="$(patch_file)"
  say "  patch:  $file"
  if [ "$DRY_RUN" != 1 ] && [ -f "$file" ]; then
    cp "$file" "$file.bak.$(date +%Y%m%d%H%M%S)"
  fi
  COSIGHT_PATCH_FILE="$file" \
  COSIGHT_PROFILE="$PROFILE" \
  COSIGHT_DRY="$DRY_RUN" \
  COSIGHT_WANT_DRIVE="$DO_DRIVE" \
  COSIGHT_WANT_PLUGINS="$DO_PLUGINS" \
  COSIGHT_DRIVE_ROOT="$DRIVE_CFG_ROOT" \
  COSIGHT_PLUGINS_ROOT="$COMPAT_CFG_ROOT" \
  python3 - <<'PY'
import os
from pathlib import Path
import re

path = Path(os.environ["COSIGHT_PATCH_FILE"])
dry = os.environ.get("COSIGHT_DRY") == "1"

DRIVE_START = "# >>> drive-compat (managed by drive-compat/install.sh) >>>"
DRIVE_END = "# <<< drive-compat <<<"
COMPAT_START = "# >>> cosight-plugin-compat (managed by install-dsh.sh) >>>"
COMPAT_END = "# <<< cosight-plugin-compat <<<"

DRIVE_BLOCK = f"""{DRIVE_START}
# Managed by install-dsh.sh (same markers as drive-compat/install.sh, so either
# installer can rewrite this block). driveRoot is explicit because the bundle is
# COPIED into this profile's node_modules and cannot infer the repo.
- id: drive-compat
  config:
    driveRoot: {os.environ['COSIGHT_DRIVE_ROOT']}
    hooks: true
    hitl: true
    skills: true
    shims: true
{DRIVE_END}"""

EXTRA_SHIMS = (
    "    # drive-compat is not installed here, so this package also claims the\n"
    "    # remaining Claude tool names (Agent/TodoWrite/AskUserQuestion).\n"
    "    extraShims: true\n"
    if os.environ.get("COSIGHT_WANT_DRIVE") != "1"
    else ""
)

COMPAT_BLOCK = f"""{COMPAT_START}
# Mounts agent-genesis, agent-evaluator (goldeval), skill-optimizer and
# cosight-bot (CoSightBot) from pluginsRoot: their skills -> dsh skills,
# commands -> user-invocable skills, agents/*.md -> the Task shim,
# hooks/hooks.json -> tools/pre-execute.
# pluginsRoot is explicit for the same reason as driveRoot above.
- id: cosight-plugin-compat
  config:
    pluginsRoot: {os.environ['COSIGHT_PLUGINS_ROOT']}
    hooks: true
    skills: true
    shims: true
{EXTRA_SHIMS}{COMPAT_END}"""

text = path.read_text(encoding="utf-8") if path.exists() else ""


def replace_marked(value, start, end, new):
    idx = value.find(start)
    if idx < 0:
        return None
    tail = value[idx:]
    close = tail.find(end)
    if close < 0:
        return value[:idx] + new
    return value[:idx] + new + tail[close + len(end):]


def legacy_pattern(block_id):
    return re.compile(
        r"(?m)^- id: " + re.escape(block_id) + r"\s*\n(?:\s.*\n)*?(?=^- id: |\Z)"
    )


def strip_trailing_empty_list(value):
    lines = value.splitlines()
    while lines and lines[-1].strip() == "[]":
        lines.pop()
    return "\n".join(lines)


def upsert(value, start, end, new, block_id):
    replaced = replace_marked(value, start, end, new)
    if replaced is not None:
        return replaced, "replaced"
    legacy = legacy_pattern(block_id)
    if legacy.search(value):
        return legacy.sub(new, value, count=1), "migrated"
    base = strip_trailing_empty_list(value).rstrip("\n")
    return (f"{base}\n\n{new}" if base else new), "appended"


if os.environ.get("COSIGHT_WANT_DRIVE") == "1":
    text, action = upsert(text, DRIVE_START, DRIVE_END, DRIVE_BLOCK, "drive-compat")
    print(f"drive-compat block: {action}")
if os.environ.get("COSIGHT_WANT_PLUGINS") == "1":
    text, action = upsert(text, COMPAT_START, COMPAT_END, COMPAT_BLOCK, "cosight-plugin-compat")
    print(f"cosight-plugin-compat block: {action}")

if dry:
    print("--- resulting patch (dry-run, not written) ---")
    print(text)
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
PY
}

remove_patch_blocks() {
  local file
  file="$(patch_file)"
  if [ ! -f "$file" ]; then info "no patch file; nothing to clean"; return 0; fi
  COSIGHT_PATCH_FILE="$file" COSIGHT_DRY="$DRY_RUN" python3 - <<'PY'
import os
from pathlib import Path
import re

path = Path(os.environ["COSIGHT_PATCH_FILE"])
dry = os.environ.get("COSIGHT_DRY") == "1"
text = path.read_text(encoding="utf-8")

for start, end, block_id in (
    ("# >>> cosight-plugin-compat (managed by install-dsh.sh) >>>",
     "# <<< cosight-plugin-compat <<<", "cosight-plugin-compat"),
    ("# >>> drive-compat (managed by drive-compat/install.sh) >>>",
     "# <<< drive-compat <<<", "drive-compat"),
):
    idx = text.find(start)
    if idx >= 0:
        tail = text[idx:]
        close = tail.find(end)
        text = text[:idx] + (tail[close + len(end):] if close >= 0 else "")
    else:
        text = re.sub(
            r"(?m)^- id: " + re.escape(block_id) + r"\s*\n(?:\s.*\n)*?(?=^- id: |\Z)",
            "", text, count=1,
        )

text = text.strip("\n")
# A comments-only file parses as YAML null and dsh rejects it; keep the array.
if not re.search(r"(?m)^- ", text):
    text = f"{text}\n[]" if text else "[]"

if dry:
    print("--- resulting patch (dry-run, not written) ---")
    print(text)
else:
    path.write_text(text + "\n", encoding="utf-8")
    print(f"blocks removed from {path}")
PY
}

# ---- uninstall ------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  info "uninstalling from profile '$PROFILE'"
  remove_patch_blocks
  if [ "$DEV_PATCH" = 0 ]; then
    for bundle in "$DRIVE_BUNDLE" "$COMPAT_BUNDLE"; do
      if bundle_installed "$bundle"; then
        x_dsh plugin --profile "$PROFILE" remove "$bundle"
      else
        info "bundle '$bundle' not present; nothing to remove"
      fi
    done
  fi
  info "done. restart dsh to drop both plugins."
  exit 0
fi

# ---- dev-patch mode -------------------------------------------------
if [ "$DEV_PATCH" = 1 ]; then
  [ -d "$PROFILE_DIR" ] || die "profile '$PROFILE' not initialized ($PROFILE_DIR). Run it once, or drop --dev-patch."
  cmd="$(dsh_label "--profile $PROFILE")"
  if [ "$DO_DRIVE" = 1 ]; then cmd="$cmd --patch $DRIVE_PKG_DIR/cordis.patch.yml"; fi
  if [ "$DO_PLUGINS" = 1 ]; then cmd="$cmd --patch $COMPAT_PKG_DIR/cordis.patch.yml"; fi
  info "nothing installed; launch dsh with the overlays instead:"
  say ""
  say "  $cmd"
  say ""
  info "run without --dev-patch to make this permanent (bundles + patch blocks)."
  exit 0
fi

# ---- install --------------------------------------------------------
if [ ! -d "$PROFILE_DIR" ]; then
  info "profile '$PROFILE' not initialized yet; the first 'plugin add' will create it"
fi

if [ "$DO_DRIVE" = 1 ]; then
  if bundle_installed "$DRIVE_BUNDLE"; then
    info "bundle '$DRIVE_BUNDLE' already present — skipping add"
  else
    x_dsh plugin --profile "$PROFILE" add "$DRIVE_TARGET"
  fi
fi

if [ "$DO_PLUGINS" = 1 ]; then
  if bundle_installed "$COMPAT_BUNDLE"; then
    info "bundle '$COMPAT_BUNDLE' already present — skipping add"
  else
    x_dsh plugin --profile "$PROFILE" add "$COMPAT_TARGET"
  fi
fi

# Bundle membership only takes effect at boot, so the profile dir (and its
# patch file) exists by now — except under --dry-run.
if [ "$DRY_RUN" = 1 ] || [ -d "$PROFILE_DIR" ]; then
  write_patch_blocks
else
  warn "profile dir still absent ($PROFILE_DIR); patch blocks not written. Re-run after starting dsh once."
fi

# ---- verification ---------------------------------------------------
if [ "$DRY_RUN" = 1 ]; then
  info "dry-run complete — nothing was written."
  exit 0
fi

info "file-level checks:"
rc=0
if [ "$DEV_PATCH" = 0 ]; then
  if [ "$DO_DRIVE" = 1 ]; then
    if bundle_installed "$DRIVE_BUNDLE"; then say "  + bundle '$DRIVE_BUNDLE' in $MANIFEST"; else say "  - bundle '$DRIVE_BUNDLE' MISSING"; rc=1; fi
  fi
  if [ "$DO_PLUGINS" = 1 ]; then
    if bundle_installed "$COMPAT_BUNDLE"; then say "  + bundle '$COMPAT_BUNDLE' in $MANIFEST"; else say "  - bundle '$COMPAT_BUNDLE' MISSING"; rc=1; fi
  fi
fi
patch="$(patch_file)"
if [ -f "$patch" ]; then
  if [ "$DO_DRIVE" = 1 ]; then
    if grep -q "driveRoot: ${DRIVE_CFG_ROOT}" "$patch"; then say "  + driveRoot=${DRIVE_CFG_ROOT}"; else say "  - driveRoot not found in patch"; rc=1; fi
  fi
  if [ "$DO_PLUGINS" = 1 ]; then
    if grep -q "pluginsRoot: ${COMPAT_CFG_ROOT}" "$patch"; then say "  + pluginsRoot=${COMPAT_CFG_ROOT}"; else say "  - pluginsRoot not found in patch"; rc=1; fi
  fi
fi

if [ -n "$COMPAT_PKG" ]; then
  PROBE_PATH="$PROFILE_DIR/node_modules/cosight-plugin-compat/acceptance/probe.mjs"
else
  PROBE_PATH="$COMPAT_PKG_DIR/acceptance/probe.mjs"
fi

if [ "$DO_PLUGINS" = 1 ] && [ -f "$PROBE_PATH" ]; then
  info "offline acceptance probe (no dsh needed):"
  if node "$PROBE_PATH" >/dev/null 2>&1; then
    say "  + probe passed"
  else
    say "  - probe FAILED (run: node $PROBE_PATH)"; rc=1
  fi
fi

if [ "$VERIFY" = 1 ]; then
  info "composed tree:"
  tmp_cfg="$(mktemp)"
  if dsh_run "$PROFILE" --dump-config >"$tmp_cfg" 2>&1; then
    for id in "$DRIVE_BUNDLE" "$COMPAT_BUNDLE"; do
      if grep -q "$id" "$tmp_cfg"; then say "  + $id present in composed config"; else say "  - $id missing from composed config"; rc=1; fi
    done
  else
    warn "dump-config failed; first lines:"
    sed -n '1,20p' "$tmp_cfg" >&2
    rc=1
  fi
  rm -f "$tmp_cfg"
fi

# ---- restart hint ---------------------------------------------------
say ""
info "bundles are read at boot — restart the dsh web app to load them:"
if [ "$DSH_MODE" = "source" ]; then
  say "    (cd \"$DSH_SOURCE\" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port $PORT)"
else
  say "    dsh $PROFILE --no-open --port $PORT    # adjust flags to taste"
fi
say "  Bundle membership is read at boot; config blocks take effect at the next launch."
if pgrep -af "bin\.ts web" >/dev/null 2>&1; then
  say ""
  info "a dsh web process is running:"
  pgrep -af "bin\.ts web" | sed 's/^/    /' || true
  say "  stop it before relaunching."
fi

if [ "$rc" -ne 0 ]; then
  warn "one or more checks failed — review the '-' lines above."
  exit 1
fi
info "DONE — all five plugins are installed in profile '$PROFILE'."
