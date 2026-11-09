#!/usr/bin/env bash
# install.sh — install drive-compat into a dsh profile as a permanent plugin
# (bundle). Two modes:
#   * dev mode   (default)   : references the drive repo assets here — run from
#                              a drive repo clone.
#   * package mode (--pkg)   : installs a SELF-CONTAINED tarball produced by
#                              pack.sh (drive assets embedded; no drive repo
#                              needed by the end user). driveRoot set to AUTO.
# Idempotent — safe to re-run.
#
# What it does
#   1. adds the bundle to the profile:  dsh plugin --profile <p> add <target>
#   2. manages the drive-compat config block in the profile's cordis.patch.yml
#      (injects driveRoot/toggles; removes it on --uninstall)
#   3. verifies the composed tree and prints the restart hint
#
# Usage
#   bash drive-compat/install.sh                        # dev mode -> profile 'web'
#   bash drive-compat/install.sh --pkg dist/drive-dsh-plugin-*.tgz
#   bash drive-compat/install.sh [--profile web] [--drive-root <path>]
#                                [--dry-run] [--force] [--uninstall] [--verify]
#
# Env overrides: PROFILE, DRIVE_COMPAT_DRIVE_ROOT
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DRIVE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"   # drive-compat is a child of drive
PROFILE="${PROFILE:-web}"
DRIVE_ROOT="${DRIVE_COMPAT_DRIVE_ROOT:-$DEFAULT_DRIVE_ROOT}"
DRY_RUN=0
FORCE=0
UNINSTALL=0
VERIFY=0
PKG=""   # optional self-contained tarball (--pkg)

usage() { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; }

# ---- argument parsing ----------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --drive-root) DRIVE_ROOT="$2"; shift 2 ;;
    --pkg) PKG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --verify) VERIFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

# ---- environment checks --------------------------------------------
if ! command -v dsh >/dev/null 2>&1; then
  echo "ERROR: 'dsh' not on PATH" >&2; exit 1
fi
PKG_DIR="$DRIVE_ROOT/drive-compat"
if [ -n "$PKG" ]; then
  # self-contained published package mode: no external drive repo required
  [ -f "$PKG" ] || { echo "ERROR: --pkg tarball not found: $PKG" >&2; exit 1; }
  # use grep -c (reads the whole stream) — a `tar | grep -q` pipe would SIGPIPE
  # tar under `set -o pipefail` and wrongly fail an intact package.
  pkg_hit="$(tar tzf "$PKG" 2>/dev/null | grep -c 'drive-assets/hooks/planning_write_guard.py')"
  if [ "${pkg_hit:-0}" -lt 1 ]; then
    echo "ERROR: $PKG is not a drive-compat self-contained package (missing drive-assets/hooks)" >&2
    exit 1
  fi
  CFG_ROOT="AUTO"                                   # assets live inside the installed package
  ADD_TARGET="file:$PKG"
else
  [ -d "$DRIVE_ROOT/hooks" ] && [ -d "$DRIVE_ROOT/skills" ] && [ -d "$PKG_DIR" ] || {
    echo "ERROR: dev-mode drive payload not found. --drive-root must point at the drive repo root (has hooks/, skills/, drive-compat/), or pass --pkg <self-contained.tgz>." >&2
    exit 1
  }
  CFG_ROOT="$DRIVE_ROOT"                            # reference the repo assets
  ADD_TARGET="file:$PKG_DIR"
fi
PROFILE_DIR="${DSH_HOME:-$HOME/.dsh}/profiles/$PROFILE"
if [ ! -d "$PROFILE_DIR" ]; then
  echo "ERROR: profile dir not found: $PROFILE_DIR" >&2
  echo "  (run the profile once, e.g. 'dsh $PROFILE --dump-config', to initialize it)" >&2
  exit 1
fi
PATCH_FILE="$PROFILE_DIR/cordis.patch.yml"
[ -f "$PATCH_FILE" ] || PATCH_FILE="$PROFILE_DIR/cordis.yml"
MANIFEST="$PROFILE_DIR/package.json"

say()  { printf '%s\n' "$*"; }
info() { printf '[install] %s\n' "$*"; }
warn() { printf '[install][warn] %s\n' "$*" >&2; }
# run a command unless --dry-run
x()   { if [ "$DRY_RUN" = 1 ]; then say "(dry-run) $*"; else "$@"; fi }

# bundle already installed? (idempotence)
bundle_installed() {
  python3 - "$MANIFEST" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
bundles = (d.get("dsh", {}).get("profile", {}).get("bundles") or [])
sys.exit(0 if "drive-compat" in bundles else 1)
PY
}

# manage the drive-compat config block in cordis.patch.yml
#   block_start/block_end guards; an older un-marked `- id: drive-compat`
#   block is also replaced (idempotent migration).
write_patch_block() {
  # 1. backup
  local bak="$PATCH_FILE.bak.$(date +%Y%m%d%H%M%S)"
  x cp "$PATCH_FILE" "$bak"

  # 2. drop any existing drive-compat block (marked or legacy) via python
  x env DRIVE_PATCH_FILE="$PATCH_FILE" DRIVE_PROFILE="$PROFILE" \
      DRIVE_ROOT_ARG="$CFG_ROOT" DRIVE_FORCE="$FORCE" python3 - <<'PY'
import os
from pathlib import Path
import re

file = os.environ["DRIVE_PATCH_FILE"]
profile = os.environ["DRIVE_PROFILE"]
drive_root = os.environ["DRIVE_ROOT_ARG"]
force = os.environ.get("DRIVE_FORCE") == "1"

START = "# >>> drive-compat (managed by drive-compat/install.sh) >>>"
END   = "# <<< drive-compat <<<"
NEW = f"""{START}
# driveRoot: deployment parameter (bundle is installed as a copy into the
# profile's node_modules and cannot infer it) — managed by install.sh.
# Remove this whole block and run 'dsh plugin --profile {profile} remove drive-compat'
# to uninstall.
- id: drive-compat
  config:
    driveRoot: {drive_root}
    hooks: true
    hitl: true
    skills: true
    shims: true
{END}
"""

p = Path(file)
text = p.read_text(encoding="utf-8")

# A freshly initialized profile's patch is `# comments... \n[]` (empty list).
# Appending a row after `[]` yields two documents without a separator, which
# YAML rejects — strip a trailing lone empty-list line before appending.
def strip_trailing_empty_list(t):
    lines = t.splitlines()
    while lines and lines[-1].strip() == "[]":
        lines.pop()
    return "\n".join(lines)

# legacy marker: un-marked top-level `- id: drive-compat` block
legacy = re.compile(r"(?m)^- id: drive-compat\s*\n(?:\s.*\n)*?(?=^- id: |\Z)")

if START in text:
    # replace our managed block wholesale
    head, _sep, tail = text.partition(START)
    after = tail.split(END, 1)[1] if END in tail else ""
    new_text = head + NEW + after
elif legacy.search(text):
    if not force:
        print("note: found a legacy (un-marked) drive-compat block; removing and re-writing")
    new_text = legacy.sub(NEW, text, count=1)
else:
    base = strip_trailing_empty_list(text).rstrip("\n")
    new_text = f"{base}\n{NEW}" if base else NEW

p.write_text(new_text, encoding="utf-8")
print(f"patch updated: {file}")
PY
}

uninstall_patch_block() {
  x env DRIVE_PATCH_FILE="$PATCH_FILE" python3 - <<'PY'
import os
from pathlib import Path
import re
file = os.environ["DRIVE_PATCH_FILE"]
START = "# >>> drive-compat (managed by drive-compat/install.sh) >>>"
END   = "# <<< drive-compat <<<"
legacy = re.compile(r"(?m)^- id: drive-compat\s*\n(?:\s.*\n)*?(?=^- id: |\Z)")
p = Path(file)
text = p.read_text(encoding="utf-8")
if START in text:
    head, _s, tail = text.partition(START)
    after = tail.split(END, 1)[1] if END in tail else ""
    new_text = head + after
else:
    new_text = legacy.sub("", text, count=1)
new_text = new_text.strip("\n")
# dsh requires the patch to be a top-level YAML ARRAY; a comments-only file
# parses as null and is rejected. Restore the canonical empty array marker.
if not re.search(r"(?m)^- ", new_text):
    new_text = f"{new_text}\n[]" if new_text else "[]"
p.write_text(new_text + "\n", encoding="utf-8")
print("patch block removed")
PY
}

# ---- main -----------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  info "uninstalling drive-compat from profile '$PROFILE'"
  uninstall_patch_block
  if bundle_installed; then
    x dsh plugin --profile "$PROFILE" remove drive-compat
  else
    info "bundle not present; nothing to remove"
  fi
  info "done. restart dsh to drop the plugin."
  exit 0
fi

info "installing drive-compat into dsh profile '$PROFILE'"
if [ -n "$PKG" ]; then
  info "  mode: self-contained package ($PKG); driveRoot=AUTO (assets ship inside the package)"
else
  info "  mode: dev repo (assets referenced at $DRIVE_ROOT)"
fi
info "  profile dir: $PROFILE_DIR"

# 1) add the bundle (skip if already there)
if bundle_installed; then
  info "bundle 'drive-compat' already in profile bundles — skipping add"
else
  info "adding bundle via: dsh plugin --profile $PROFILE add $ADD_TARGET"
  x dsh plugin --profile "$PROFILE" add "$ADD_TARGET"
fi

# 2) manage the profile patch block
write_patch_block

# 3) verify
if [ "$VERIFY" = 1 ]; then
  info "verifying composed tree..."
  x dsh "$PROFILE" --dump-config
fi
info "file-level check:"
if bundle_installed; then say "  + bundle present in profiles/$PROFILE/package.json"
else say "  - bundle NOT present (check add output)"; fi
if grep -q "driveRoot: ${CFG_ROOT}" "$PATCH_FILE"; then say "  + driveRoot=${CFG_ROOT} configured in $PATCH_FILE"
else say "  - driveRoot not found in patch"; fi

info "DONE. Restart dsh to apply:"
say "    kill \$(pgrep -f 'bin/dsh $PROFILE') ; dsh $PROFILE --no-open --port 3080   # adjust flags"
say "  (a fresh 'dsh $PROFILE' picks up the new bundles at boot; HMR covers config edits after that)"
exit 0
