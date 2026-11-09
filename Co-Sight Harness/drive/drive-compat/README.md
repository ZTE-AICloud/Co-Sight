# drive-compat — 让 drive 在 dsh 原生运行（drive 代码零改动）

> **第三方冷启动？** 看 [QUICKSTART.md](QUICKSTART.md) —— 拿一份 drive 副本，
> 一条命令装进你自己的 dsh，30 秒验证生效。不需要任何来自作者机器的配置。

There are two ways to attach it — **development (ad-hoc patch)** and
**installation (permanent bundle)**. Pick based on whether you want it to
survive restarts automatically.

## Mode 1 — Development / try-out (no install, auto-inferred paths)

```bash
# from inside the drive repo:
dsh web --patch ./drive-compat/cordis.patch.yml
```

> Proxy note: if your dsh routes model traffic through a proxy and your model
> endpoint is on an internal network, set your normal `no_proxy` (this is a
> deployment concern of your own machine, unrelated to this plugin).

- `cordis.patch.yml` names the plugin as `./src/index.mjs`; dsh resolves it
  relative to the patch file's own directory (verified → `file://` URL there).
- `driveRoot` is **inferred** from the plugin's own location:
  `<anything>/drive/drive-compat/src/` → `<anything>/drive`. Override with
  `config.driveRoot` or env `DRIVE_COMPAT_DRIVE_ROOT` for unusual layouts.
- **Fail loud**: if `driveRoot` does not hold the drive payload (hooks/ +
  skills/), the plugin logs a clear error and disables the layers that need it —
  it never silently runs with guards off.
- Ad-hoc: does not survive restart; add the `--patch` again next launch.

## Mode 2 — Installation (permanent; survives restart, no --patch at launch)

**Use the artifact installer** (idempotent; handles bundle add + driveRoot config
+ verification + restart hint):

```bash
bash drive-compat/install.sh                 # install into profile 'web'
bash drive-compat/install.sh --dry-run       # preview only
bash drive-compat/install.sh --profile p2    # different profile
bash drive-compat/install.sh --uninstall     # remove again
bash drive-compat/install.sh --verify        # also print the composed tree
```

What it does:
1. `dsh plugin --profile <p> add file:<drive>/drive-compat` → permanent bundle
   in the profile's `dsh.profile.bundles` (skipped if already installed).
2. Manages the `drive-compat` config block in the profile's `cordis.patch.yml`
   between `# >>> drive-compat ... >>>` markers, injecting `driveRoot` + toggles
   (also migrates any older un-marked block; backs up before editing).
3. Verifies bundle/patch, and with `--verify` dumps the composed tree.
4. Prints the restart step (first install needs a restart; HMR covers config
   edits afterwards).

Under the hood, mode 2 boils down to the two steps below (what `install.sh`
automates):

```bash
dsh plugin --profile web add file:/path/to/drive/drive-compat
# + a drive-compat config block (driveRoot) appended to ~/.dsh/profiles/web/cordis.patch.yml
dsh web   # <-- no --patch; drive-compat is a permanent profile layer
```

Deployment note: installing COPIES the package into the profile's
`node_modules`, so `driveRoot` must be set (install.sh does this). If it stays
unset the plugin fails loud and turns off the guards/skills layers.

## Mode 3 — Release package (self-contained; end users need NO drive repo)

For distribution to third parties who only have dsh installed, build a
**self-contained plugin tarball** that embeds drive's hooks/skills/agents
verbatim (drive source is only copied, never modified):

```bash
bash drive-compat/pack.sh
# → drive-compat/dist/drive-dsh-plugin-<drivever>-dsh.0.tgz   (+ .sha256)
```

End users install it with the same installer, no drive repo anywhere:

```bash
bash drive-compat/install.sh --pkg drive-dsh-plugin-2.3.4-dsh.0.tgz
# (or directly: dsh plugin --profile web add file:/path/to/that.tgz)
dsh web   # restart once
```

- The package sets `driveRoot: AUTO` — the plugin prefers its in-package
  `drive-assets/` (hooks + skills + agents) automatically, so no repo, no
  `--drive-root`, no env needed on the consumer machine.
- `pack.sh` runs the acceptance probes against the staged copy before producing
  the tarball, so a broken artifact is refused at build time.
- Upgrade: rebuild with `pack.sh`, re-run `install.sh --pkg <new.tgz>`, restart.
- Uninstall / keep bundle identical to Mode 2 (`install.sh --uninstall`).

### Hot-reload reality (be honest with yourself about this)

| Change | Mode 2 behaviour |
|---|---|
| First `dsh plugin add` | takes effect on the **next** `dsh web` start (compositions resolve at boot) |
| Bundle `config` edits (bundle.patch.yml) | web profile runs **config-only HMR** → hot-reloaded without restart |
| Plugin `.mjs` code edits | need a restart (HMR is config-only, not code) |
| `--patch` overlay edits (Mode 1) | next launch (patch is read at boot) |

## What it does (drive code is never modified)

| Layer | Job |
|---|---|
| `hooks` | listens on `tools/pre-execute`; maps lowercase dsh tool names back to Claude PascalCase (`write`→`Write`, `bash`→`Bash`, `subagent`→`Task`, `skill`→`Skill`), back-fills `subagent_type` from `description`/`prompt`, then shells out to the drive Python guards (`planning_write_guard.py` / `state_transition_guard.py` / `audit_events.py`). `exit 2` → `{kind:'deny'}`. |
| `hitl` | any bash whose command mentions `confirm_stage.py`, `confirm-node`, or `state_cli ... transition` returns `{kind:'ask'}` → human approval. **Reminder:** approval policy `never` rejects `ask` — run under `ask` for HITL. |
| `skills` | mounts `drive/skills/*/SKILL.md` via `ctx.skills.register`, replacing `\${CLAUDE_SKILL_DIR}` with the skill dir and `\${CLAUDE_PLUGIN_ROOT}` with `driveRoot`. |
| `shims` | registers Claude-named model tools: `Agent` (spawns a subagent and awaits its result, emulating `run_in_background=False`), `TodoWrite` (no-op unless the todo service is present), `AskUserQuestion` (steers to the native `ask_user_question`). |

## Accepted losses / notes

- `allowed-tools` per-skill tool allowlists have no declarative equivalent in dsh;
  that capability is enforced dynamically here (deny/ask), or not at all.
- `agent_type` on subagent start/stop is always `general-purpose` in dsh; role
  attribution is recovered via `description`/`prompt` heuristics.
- Approval policy `never` ⇒ `ask` is auto-rejected (headless = no HITL).

## Acceptance probes

```bash
bash drive-compat/acceptance/run-all.sh
```

Each probe exits non-zero on failure: write-guard deny, audit append, HITL refusal.
