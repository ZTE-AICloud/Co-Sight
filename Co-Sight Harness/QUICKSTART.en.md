# Quick start

[简体中文](QUICKSTART.md) · [English](QUICKSTART.en.md) · [← Back to README](README.en.md)

This document covers **how to get it running**: what to type, what success looks like, and where to
look first when it does not. For the reasoning behind the design see [`framework/docs/`](framework/docs/)
and each component's README; for the full acceptance checklist of the distributed artifact see
[`framework/docs/user-guide.md`](framework/docs/user-guide.md) (Chinese).

```text
Artifact  : unzip → install (preflight + plugins) → start (framework + modules) → open 127.0.0.1:4300
From source: clone → pnpm install → pnpm dev (framework) / pnpm dev:all (+ modules) → open localhost:4310
```

---

## 0. Pick a path

| Your situation | Start at | You need |
|:---|:---|:---|
| You have `cosight-harness-*.tar.gz` / `.zip` and just want it running | [Path A](#2-path-a-the-distributed-artifact) | Node.js (Claude Code and Python 3 optional) |
| You want to develop or customise | [Path B](#3-path-b-from-source) | Node.js + pnpm + each module's dependencies |
| You need to produce the artifact for someone else | [8. Packaging](#8-packaging) | Same as Path B |
| You only want the five plugins inside DeepSeek Harness | [7. Optional](#7-optional-claude-code-plugins-and-dsh) | A working dsh |

---

## 1. Prerequisites

| Item | Requirement | Check with | If missing |
|:---|:---|:---|:---|
| **Node.js** | `^22.19.0` or `>=24.0.0` | `node -v` | Install/start preflight fails, exit code **10** |
| **pnpm** | `11.28.5` (source development only) | `corepack enable && pnpm -v` | Cannot install workspace dependencies |
| **Claude Code** | CLI `>= 2.1.287` (for plugins) | `claude --version` | Exit code **10**; skip with `--skip-plugins` |
| **Python 3** | `python3` on PATH | `python3 --version` | Exit code **10**; plugin hooks and cosight-bot need it |
| **Platform** | Linux x64 / Windows x64 | — | Preflight fails |
| **Disk** | ≥ 512 MB on the data-directory volume | `df -h` | Warning only, does not block |

> The artifact needs **no pnpm, no network and no administrator rights**. Only the machine that
> produces the artifact needs pnpm.

---

## 2. Path A: the distributed artifact

### 2.1 Unzip

```bash
tar -xzf cosight-harness-*.tar.gz
cd cosight-harness-*/
```

Windows: right-click the archive → *Extract All* (or use 7-Zip). `tar.gz` and `zip` are equivalent;
the extracted tree contains no symlinks, so the built-in Windows extractor works too.

### 2.2 Self-check (recommended, read-only)

```bash
node start.mjs --self-check
```

It prints `[OK]` / `[WARN]` / `[FAIL]` per item and a verdict. **Fix any `[FAIL]` before installing** —
this step writes nothing and can be run repeatedly.

### 2.3 Install

```bash
./install.sh
```

Windows: double-click `install.cmd`.

The installer does four things in order, and **is safe to re-run (idempotent)**:

1. **Preflight** (read-only): platform, Node, Claude Code version, writable config directory,
   Python 3, payload integrity. Any blocking failure prints *check / reason / action / impact* and
   exits with code **10** without writing a single file.
2. **Create the data directory**: defaults to `~/.cosight-harness`; override with `--home <dir>`.
3. **Generate configuration**: `cosight.env` is created from a template; existing files are kept.
4. **Install five Claude Code plugins** (`user` scope): `drive`, `agent-genesis`, `goldeval`,
   `skill-optimizer`, `cosightbot`. Failures exit with code **12** and print the failing plugin plus
   the raw CLI error.

Common flags:

```bash
./install.sh --home /srv/cosight-harness   # custom data directory
./install.sh --skip-plugins                # skip plugins (plugin-backed features become unavailable)
```

### 2.4 Start

```bash
./start.sh
```

Windows: double-click `start.cmd`.

The launcher brings up the framework and every module, **health-checking each one**; if any fails to
come up, already-started processes are stopped in reverse order so you never end up with half a
stack. Startup failures such as a busy port or an unready module exit with code **13**.

```bash
./start.sh --port 8080 --home /var/lib/cosight   # different port / data directory
./start.sh --no-modules                          # framework only
./start.sh --help                                # all flags
```

### 2.5 Open and verify

Open <http://127.0.0.1:4300>. From the command line:

```bash
curl -s http://127.0.0.1:4300/api/health     # {"status":"ok", ...}
curl -s http://127.0.0.1:4300/api/modules    # registered modules and reachability
```

| Address | Contents |
|:---|:---|
| `127.0.0.1:4300` | Framework home (listens on `0.0.0.0` by default; use loopback locally) |
| `/api/health` | Health check |
| `/api/docs` | API documentation |
| `/api/modules` | Module registry and reachability |

### 2.6 Stop

Press **Ctrl-C** in the foreground: every process is stopped in reverse order and all ports are
released (`ss -ltn | grep -E ':(4300|4830|4100|4110)'` should print nothing).

---

## 3. Path B: from source

### 3.1 Clone and install dependencies

```bash
git clone https://github.com/ZTE-AICloud/Co-Sight.git
cd "Co-Sight/Co-Sight Harness"
corepack enable      # once: aligns pnpm with the packageManager field
pnpm install         # installs shared / server / web for the framework
```

### 3.2 Start the framework

```bash
pnpm dev             # API 4300 + web dev server 4310
# open http://localhost:4310
```

In development Vite proxies `/api` to 4300, so application code only ever uses relative paths.
**Do not** point the front end straight at `http://127.0.0.1:4300`: that makes cookie behaviour
diverge between development and production.

One side only:

```bash
pnpm dev:server      # back end only: 127.0.0.1:4300
pnpm dev:web         # front end only: 127.0.0.1:4310 (the back end must be up, or every /api call is 502)
```

### 3.3 Start the modules too

Install each module's dependencies first — **the aggregate launcher never installs them for you**;
it only reports what is missing and points at the module's README:

```bash
# smart-factory: dependencies + .env + Prisma Client + database
cd smart-factory && node scripts/dev.mjs setup && cd ..

# cosight-viewer: install dependencies as described in its README
cd cosight-viewer && npm install && cd ..
```

Then, at the repository root:

```bash
pnpm dev:all         # framework + cosight-viewer + smart-factory, each step waits for readiness; Ctrl-C stops all
```

| Order | Service | Port | Readiness probe |
|:---:|:---|:---:|:---|
| 1 | `framework:server` | 4300 | `/api/health` |
| 2 | `framework:web` | 4310 | `/` |
| 3 | `cosight-viewer` | 4830 | `/health` |
| 4 | `smart-factory:server` | 4100 | `/api/smart-factory/v1/health` |
| 5 | `smart-factory:web` | 4110 | `/` |

Useful flags: `--home <dir>` (framework data directory), `--reuse` (reuse an instance already
listening on the port — it is not owned by the launcher and will not be stopped by Ctrl-C),
`--live` (do not isolate module data directories; use the real `~/.claude`).
See [`framework/docs/dev-all.md`](framework/docs/dev-all.md) (Chinese).

### 3.4 Production mode (local verification)

```bash
pnpm build           # builds the web bundle; the server build only type-checks
pnpm start           # serves web/dist + API on the same origin at 4300
```

In the repository layout `pnpm start` only **probes** registered modules; it does not launch them
(that is what `pnpm dev:all` is for).

### 3.5 Pre-commit gate

```bash
pnpm verify          # typecheck + oxlint + all tests (80% coverage threshold)
```

---

## 4. Ports

| Port | Service | Notes |
|:---:|:---|:---|
| `4300` | Framework API / artifact-mode front end | Also the home page of the artifact |
| `4310` | Framework front end (development) | Vite, proxies `/api` to 4300 |
| `4830` | cosight-viewer | Session observability and task centre |
| `4100` | smart-factory back end | `/api/smart-factory/v1/health` |
| `4110` | smart-factory front end | Development Vite server |

---

## 5. Configuration

### 5.1 Two sources, by how you run it

- **Artifact**: `cosight.env` next to `start.mjs` (`KEY=VALUE`; the template is
  `cosight.env.example` in the archive). Restart to apply changes.
- **Source**: environment variables, e.g. `COSIGHT_PORT=4400 pnpm dev`.

Precedence: **command-line flags > real environment variables > `cosight.env` > built-in defaults**.

### 5.2 Common variables

| Variable | Default | Meaning |
|:---|:---|:---|
| `COSIGHT_PORT` | `4300` | Listening port |
| `COSIGHT_HOST` | `0.0.0.0` | Bind address (all interfaces by default; no login; use `127.0.0.1` for local-only) |
| `COSIGHT_HOME` | `~/.cosight-harness` | Data root: database, credentials, module manifests, workspaces |
| `COSIGHT_DATABASE_URL` | `file:$COSIGHT_HOME/sqlite.db` | libsql connection string |
| `COSIGHT_LOG_LEVEL` | `info` | `fatal\|error\|warn\|info\|debug\|trace\|silent` |

The full list (CORS, static bundle directory, knowledge-base API key, …) is in
[`framework/README.en.md`](framework/README.en.md).

---

## 6. Acceptance checklist

Whichever path you took, tick these off:

- [ ] `node start.mjs --self-check` reports `[OK]` everywhere (artifact path)
- [ ] Install exits `0` and all five plugins report "installed"
- [ ] The start log says ready; `curl -s 127.0.0.1:4300/api/health` returns `status=ok`
- [ ] `curl -s 127.0.0.1:4300/api/modules` lists `cosight-viewer` and `smart-factory`
- [ ] The home page opens and the sidebar switches pages
- [ ] After Ctrl-C, `ss -ltn | grep -E ':(4300|4830|4100|4110)'` prints nothing

---

## 7. Optional: Claude Code plugins and dsh

### 7.1 Installing plugins by hand

The artifact's `install.sh` does this for you; from source you can install manually:

```bash
# run at the repository root; <dir> is the component directory, <id> the install ID
claude plugin marketplace add <dir>
claude plugin install <id> --scope user
```

| Component directory | Install ID |
|:---|:---|
| `drive` | `drive@zte-ai-lab` |
| `agent-genesis` | `agent-genesis@agent-genesis` |
| `agent-evaluator` | `goldeval@goldeval` |
| `skill-optimizer` | `skill-optimizer@skillx` |
| `cosight-bot` | `cosightbot@cosightbot` |

> The install ID is `<plugin name>@<marketplace name>`, **not** the directory name. `cosight-bot`
> additionally needs `python cosight-bot/scripts/install.py` to set up its runtime — see its README.

### 7.2 Installing into DeepSeek Harness (dsh)

```bash
bash install-dsh.sh --verify              # default profile: web
bash install-dsh.sh --profile mylab       # another profile
bash install-dsh.sh --dry-run             # show every action, write nothing
bash install-dsh.sh --uninstall           # reverse it
```

Restart dsh afterwards (it is a single process: port `3080` serves both the UI and the API).
For a source checkout, point `DSH_SOURCE_DIR` at it:

```bash
export DSH_SOURCE_DIR="$HOME/dsh"
bash install-dsh.sh --verify
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

See [`dsh-compat/README.en.md`](dsh-compat/README.en.md).

---

## 8. Packaging

At the repository root:

```bash
pnpm install
pnpm build          # build the framework web bundle
pnpm package        # → tar.gz and zip under .package/
pnpm smoke:package  # optional: unzip independently, simulate install + start, assert HTTP on every port
```

The archive top level is `install.*` + `start.*` + `server/` + `web/` + `modules/` + `start.mjs`, and
one archive carries native packages for both linux-x64 and win32-x64. **The packaging script builds
but never installs dependencies**: if a module lacks `node_modules` it tells you to install them in
that module's directory.

Which modules ship is decided by `framework/docs/modules/<id>.artifact.json`.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|:---|:---|:---|
| Installer complains about the Node version | Not in `^22.19.0 \|\| >=24.0.0` | Upgrade Node using the link it prints (exit code **10**) |
| Installer cannot find `claude` | Claude Code missing or not on PATH | `npm i -g @anthropic-ai/claude-code`, or `./install.sh --skip-plugins` |
| Missing `python3` | Plugin hooks need it | Install Python 3 and put it on PATH |
| Start exits with **13**, port busy | Leftover process on 4300 / 4830 / 4100 / 4110 | Find it with `ss -ltn` and stop it, or `./start.sh --port <new port>` |
| A `pnpm dev:all` service keeps reporting "not ready" | The module's dependencies are not installed (the launcher does not install them) | Install them in that module's directory, then retry |
| The page loads but every request is 502 | Front end started without the back end | Start `pnpm dev:server` before `pnpm dev:web` |
| cosight-viewer UI unchanged after `git pull` | It serves `client/dist` in production mode, and `dist` is not tracked | Run `npm run build` in that module, or let `pnpm dev:all` rebuild it |
| Start log shows `[WARN]` | Non-blocking item (e.g. disk warning) | Safe to continue; only `[FAIL]` needs action |
| Scripts close instantly when double-clicked on Windows | Missing prerequisite, or not run from the extracted directory | Open a terminal in that directory and run `install.cmd` to see the output |

Exit codes: `0` success · `10` preflight failed · `12` plugin install/uninstall failed ·
`13` startup failed / port busy.

---

## 10. Stopping and uninstalling

**Stop**: `Ctrl-C` in the foreground; `start.sh` tears everything down in reverse order.

**Uninstall** (artifact):

```bash
./uninstall.sh --dry-run           # read-only: print the commands it would run
./uninstall.sh                     # remove the five plugins and marketplace registrations
./uninstall.sh --purge-data --yes  # also delete the data directory (irreversible)
```

Windows: `uninstall.cmd`.

**Deleting the directory is not enough**: plugin payload copies and state live under `~/.claude`,
so use `uninstall.sh` or clean them by hand. Full details in
[`framework/docs/uninstall-manual.md`](framework/docs/uninstall-manual.md) (Chinese).

---

## Next steps

- What problem it solves and how it is designed: [README.en.md](README.en.md)
- Full acceptance checklist for the artifact: [`framework/docs/user-guide.md`](framework/docs/user-guide.md)
- Integrating your own module: [`framework/docs/module-artifact-integration.md`](framework/docs/module-artifact-integration.md)
- Building custom experts and skills: start with [`agent-genesis/README.md`](agent-genesis/README.md)
