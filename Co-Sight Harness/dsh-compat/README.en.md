# Installing the five plugins into DeepSeek Harness (dsh)

[简体中文](README.md) · [English](README.en.md)

One command installs `drive`, `agent-genesis`, `agent-evaluator` (goldeval), `skill-optimizer` and
`cosight-bot` (CoSightBot). Not a single line of the four Claude plugins is changed: the
compatibility layer `cosight-plugin-compat` mounts them onto dsh's native surface, and `drive` is
mounted by its own `drive-compat`.

| bundle | Plugins it carries |
|---|---|
| `drive-compat` | drive |
| `cosight-plugin-compat` | agent-genesis, agent-evaluator, skill-optimizer, cosight-bot |

Measured scale: 25 skills, 10 commands, 28 agent roles, 1 hook rule; after installation the dsh
runtime reports 52 skills in total (35 from this package + 17 from drive) and starts without errors.
Both source installs and `--pkg` release-package installs have been verified.

---

## 1. Prerequisites and installation

**Prerequisites**

- A dsh that **already runs**: a published CLI, or a source checkout (in source mode the script
  launches it with `node --import tsx/esm apps/cli/src/bin.ts`, so that checkout needs its
  dependencies installed).
- **bash**: `install-dsh.sh` is a bash script (Linux / macOS directly; Windows via WSL or Git Bash).
- The `drive` directory (by default the `drive/` next to the script), unless you pass `--no-drive`.
- The installer calls `dsh plugin add`, so the `dsh` command (or `--dsh "pnpm dsh"`) must be on PATH.

**Installation.** All commands below run at the **repository root** (the parent of `dsh-compat/`).
`DSH_SOURCE_DIR` is your dsh source checkout; set it to your actual path — the script auto-detects
one when it is unset.

```bash
export DSH_SOURCE_DIR="$HOME/Co-sight Harness"   # point this at your dsh checkout

# 1) install + self-check (idempotent, safe to re-run)
bash install-dsh.sh --verify

# 2) restart dsh (bundle members are read only at boot)
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

The installer touches exactly two places: it writes a marked block (with a timestamped backup) into
the profile's `cordis.patch.yml`, and registers the two bundles via `dsh plugin add`. Existing
entries are skipped, so re-running is safe. To see what it would do without writing anything, use
`bash install-dsh.sh --dry-run`.

The startup log should show:

```text
cosight-plugin-compat: mounted 35 skills/commands (25 skills, 10 commands, 0 failed, 0 skipped)
cosight-plugin-compat: agent roles=28, shims registered=[Task], skipped=[]
cosight-plugin-compat: 1 PreToolUse hook rule(s) active: agent-genesis[Write|Edit]
```

## 2. Starting it (frontend and backend)

dsh is a **single-process application**: one port serves both the backend API and the frontend pages
(`3080` by default). The compatibility layer is **not** a separate service and has no frontend or
backend process of its own — it is loaded into that dsh process at boot and registers skills,
commands, roles and hooks onto the dsh runtime. So there is no "start the frontend and backend
separately" step here, only "which way do you start dsh".

**Source checkout** (development or local debugging):

```bash
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

**Published dsh CLI**:

```bash
dsh web --no-open --port 3080
# another profile: dsh --profile mylab web --no-open --port 3080
```

**Layered on top without installing** (to try a change to the compat layer immediately):

```bash
bash install-dsh.sh --dev-patch      # prints a launch command with --patch; run it
```

Then open <http://127.0.0.1:3080/>. Stop with **Ctrl-C**.

**Restarting dsh after installation is mandatory**: bundle membership and config blocks are read
only at boot, so nothing changes in the UI until you restart.

## 3. Configuration

**Compat-layer configuration** (`config` of `cosight-plugin-compat` in the profile's patch; you
normally do not touch it):

| Key | Default | Meaning |
|---|---|---|
| `pluginsRoot` | auto-detected | Parent directory holding the four plugins; `AUTO` = use the packaged `plugin-assets/` |
| `plugins` | all | Mount only a subset (array of directory names) |
| `skills` / `shims` / `hooks` | `true` | Toggle the skill, agent-tool and hook layers independently |
| `extraShims` | `false` | Also register `Agent`/`TodoWrite`/`AskUserQuestion` (**do not** enable when coexisting with drive — duplicate tool names) |
| `hookTimeoutMs` | `60000` | Hook timeout ceiling, in milliseconds |

`pluginsRoot` resolution order: `config.pluginsRoot` → env `COSIGHT_COMPAT_PLUGINS_ROOT` → packaged
`plugin-assets/` → development layout (repository root).

**Environment variables read by the installer**:

| Variable | Purpose |
|---|---|
| `PROFILE` | Which dsh profile to install into; same as `--profile` (default `web`) |
| `DSH_SOURCE_DIR` | dsh source directory; when set, source mode is used for the restart hint |
| `DSH_HOME` | dsh configuration root (profiles live under it); rarely set |
| `COSIGHT_COMPAT_PLUGINS_ROOT` | Parent directory of the four plugins; same as `--plugins-root` |

**Common command-line options** are in section 6; the full list is
`bash install-dsh.sh --help`.

## 4. Verifying the installation

```bash
# bundle registration (expect drive-compat and cosight-plugin-compat)
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.dsh/profiles/web/package.json')))['dsh']['profile']['bundles'])"

# composed config (authoritative check, no restart needed; expect one entry line per id)
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --dump-config) | grep -E "drive-compat|cosight-plugin-compat"

# offline acceptance (no dsh required; expect 23/23 checks passed)
node dsh-compat/acceptance/probe.mjs | tail -1
```

Then three clicks in the UI (<http://127.0.0.1:3080/>):

- typing `/selftest` gets you in → commands are mounted;
- searching the skill list for `goldeval-e2e-test-runner` → skills are mounted (including the
  rename-on-collision case);
- asking the model to "take a look with debug-pro" → the role entry point (`Task`) works.

## 5. Uninstalling

```bash
bash install-dsh.sh --uninstall      # also from the repository root
```

Then restart dsh. Confirm it is clean:

```bash
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.dsh/profiles/web/package.json')))['dsh']['profile']['bundles'])"
# expect only ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app']
```

## 6. Common variants

| Scenario | Command |
|---|---|
| Preview what it would do, write nothing | `bash install-dsh.sh --dry-run` |
| Only the four Claude plugins (no drive) | `bash install-dsh.sh --no-drive` |
| Target machine has no checkout — use the release package | `bash install-dsh.sh --pkg dsh-compat/dist/cosight-dsh-plugins-0.1.0-dsh.0.tgz` |
| Install into another profile | `bash install-dsh.sh --profile mylab` |
| No install, temporary overlay | `bash install-dsh.sh --dev-patch` (prints a `--patch` launch command) |
| dsh is not on PATH | `bash install-dsh.sh --dsh "pnpm dsh"` |

## 7. Troubleshooting

| Symptom | What to do |
|---|---|
| Nothing changed in the UI after installing | You did not restart; bundles are read only at boot |
| Startup reports duplicate tools (`duplicateError`) | Keep the default when coexisting with drive (only `Task` is registered); do not enable `extraShims` |
| Log says `no plugin payload found` | `pluginsRoot` is wrong; source installs point at the repository root, release packages use `AUTO` |
| Full rollback | `bash install-dsh.sh --uninstall`, then restart |

## 8. Capability boundaries (an honest list)

The mapping is not byte-for-byte equivalent. The differences below are deliberate trade-offs, not
silently papered over:

- **`allowed-tools` is advisory only**: dsh has no mechanism to narrow tool permissions per command;
  permissions follow dsh's own policy.
- **`run_in_background` always waits**: dsh sub-agent calls are synchronous.
- **`${CLAUDE_PROJECT_DIR}` in skill bodies is not expanded** (there is no session directory at mount
  time); it is expanded in hook commands. `${CLAUDE_PLUGIN_ROOT}`, `${PLUGIN_ROOT}` and
  `${CLAUDE_SKILL_DIR}` are replaced with absolute paths at mount time.
- **Steps in agent-evaluator that call `claude -p`** require a local `claude` CLI; if it is missing
  they fail rather than being substituted.
- **skill-optimizer's assumptions about local paths such as `/media/vdb`** are not rewritten; on a
  different machine, configure the real paths.
- **`/name` must be typed by the user**; the model will not pick command-type skills automatically
  (a faithful mapping of Claude command semantics).
- **The role entry point is `Task`** (when coexisting with drive): the model picks a role by name,
  not through Claude's `subagent_type` dispatch.

## 9. How the mounting works

| Claude Code resource | Landing spot in dsh | How it is triggered |
|---|---|---|
| `skills/*/SKILL.md` | `ctx.skills.register`, callable by model and user | Model auto-selects, or `/name` |
| `commands/*.md` | Same registry, user-callable only | Typing `/name` only |
| `agents/*.md` | `Task` tool; the role Markdown is prepended to the spawn prompt | Name the role in the task |
| `PreToolUse` in `hooks/hooks.json` | `ctx.on('tools/pre-execute')` | Before dsh tool calls |

Naming rules: underscores become hyphens (`skill_create` → `/skill-create`); Chinese names go
through an alias table (`编码原则` → `coding-principles`); on collision the first one wins and later
ones get a prefix (agent-evaluator's `e2e-test-runner` → `goldeval-e2e-test-runner`).

## 10. For developers: acceptance and packaging

```bash
bash dsh-compat/acceptance/run-all.sh     # syntax checks + 23 offline probes
bash dsh-compat/pack.sh                   # build a self-contained release package into dsh-compat/dist/
```

The probes do not need dsh: they drive every module with a stub `ctx` and **actually execute**
agent-genesis's guard scripts, verifying that writes inside the plugin directory are denied while
writes outside are allowed, and that hook exit codes map to deny/ask/allow.
