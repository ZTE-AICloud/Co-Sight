# Framework · the host shell

[简体中文](README.md) · [English](README.en.md)

The framework is not an app you can open on its own. It is the **host shell that ties the modules
into one entry point**: a left sidebar, workspace settings and a settings dialog. Sessions, experts,
agent development and observability are not implemented here — the framework only embeds each
module's pages (`<ModuleHost capability="…" />`, an iframe host). The experts page is served by
smart-factory's `/agents` (D44); the framework's own native page has been removed.

**There is one exception**: the floating "expand workspace files" button in the top-right corner of
the session area, and the panel it opens, are **drawn by the host**. Because there is no bridge
between host and module (D24), the host can neither read nor paint inside the iframe, while the
requirement put that icon exactly on the module's turf. The panel is **split left/right** (directory
tree on the left, file preview on the right); its left edge is draggable, with a width between 320px
and **one third of the page width**. Opening it **narrows the session area** (it does not cover it),
and it can also go **full screen** (filling the content area, sidebar kept).

The rationale, the cost (the colleague's iframe reflows frame by frame while the panel opens and
closes), and the warning that "anything your colleagues add in that corner will be covered", are in
[`docs/framework-decisions.md`](docs/framework-decisions.md) (D35, D38, D39) and
[`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md) §7.

This matches the repository's component conventions (root [`README.en.md`](../README.en.md#repository-layout), "Component conventions"):
**service-type components own their internal layout**, and a module root carries no `package.json`.
Therefore **every command under `framework/` runs at the repository root**, never in this directory.

## Layout

```
framework/
├── server/       Backend: Fastify 5 + TypeScript (HTTP API, SQLite + Drizzle)
├── shared/       Shared contract layer: zod schemas, API envelope, error codes, module manifests, iframe bridge protocol
├── web/          Frontend: React 18 + Vite + React Router + TanStack Query + Zustand
├── scripts/      Repository-level scripts: dev-all, start (artifact layout), package, smoke-package
│                 artifact/ holds the **source of truth for the five user-facing files shipped in the artifact** (install/start scripts + config template)
├── docs/         Framework docs: architecture, decisions, module integration, packaging, task list, module manifest registry
└── tsconfig.base.json   Compiler base that the three packages extend
```

**`shared/` produces no build output**: its `exports` point straight at `src/*.ts`, so a change is
visible to both sides immediately. Contracts are defined once, here — the server does not keep a
second copy (see `docs/architecture.md`).

## Installation

Two prerequisites: **Node.js `^22.19.0 || >=24.0.0`** (matching the server's `engines`; the root
`package.json` is the single place that declares it) and pnpm. The package manager version is pinned
in the root `package.json` (`packageManager`: `pnpm@11.28.5`); using corepack avoids lockfile churn
caused by a different local pnpm:

```bash
cd <repo-root>        # repo root = cosight-harness/, not framework/
corepack enable       # once
pnpm install          # installs shared / server / web in one go
```

There is **no** `package.json` inside `framework/`: each of the three packages has one, wired
together by the root `pnpm-workspace.yaml`. That is why every command runs at the repository root —
running them inside `framework/` finds no scripts.

Confirm the environment before starting anything:

```bash
pnpm typecheck        # tsc --noEmit in each of the three packages
pnpm run verify       # typecheck + oxlint + all tests (80% coverage threshold)
```

The data directory `$COSIGHT_HOME` (default `~/.cosight-harness`) is created and migrated on the
**first start**; there is nothing to set up by hand during installation.

If you have a **distribution package** rather than the source, do not follow the path above: unzip
it and run `./install.sh` (double-click `install.cmd` on Windows) — see
[`docs/user-guide.md`](docs/user-guide.md). The split is deliberate: the source repository runs via
`pnpm dev`, the artifact ships a prebuilt frontend plus `start.mjs`.

## Configuration

Server configuration has **exactly one entry point**: `loadConfig()` in
`server/src/config/env.ts`. In the first second of startup it parses and validates the environment
into `ServerConfig`; an invalid value throws `ConfigError` and exits — it never survives into a
request as `undefined`.

| Variable | Default | Meaning |
|---|---|---|
| `COSIGHT_PORT` | `4300` | Listen port; anything that is not an integer in 1..65535 fails at startup |
| `COSIGHT_HOST` | `0.0.0.0` | Listen address. All interfaces by default (D25: v1 is single-user and local, with no login — assess the exposure); use `127.0.0.1` for local-only |
| `COSIGHT_HOME` | `~/.cosight-harness` | Data root: database, `.credentials.yaml`, `.module-token`, module manifests and workspaces live under it |
| `COSIGHT_WORKSPACES_ROOT` | `$COSIGHT_HOME/workspaces` | Workspace root, so project files can live apart from framework-private data. Resolved exactly like `COSIGHT_HOME`: `path.resolve`, no `~` expansion |
| `COSIGHT_DATABASE_URL` | `file:$COSIGHT_HOME/sqlite.db` | libsql connection string |
| `COSIGHT_WEB_DIST` | empty in dev / set by `start.mjs` in production | Frontend static output directory; when empty the server runs API-only and Vite serves the frontend |
| `COSIGHT_CORS_ORIGINS` | `:4310` and `:4830` on both `localhost` and `127.0.0.1` | Allowed origins, comma-separated. Both spellings are listed because browsers treat them as different origins |
| `COSIGHT_HOST_ORIGIN` | `http://<host>:<port>` | Origin of the host **frontend**, used for module cross-origin validation; in dev this is `:4310`, not the API's `:4300` |
| `COSIGHT_LOG_LEVEL` | `info` | `fatal\|error\|warn\|info\|debug\|trace\|silent` |
| `COSIGHT_KNOWLEDGE_API_KEY` / `CO_KNOWLEDGE_API_KEY` | empty | Server-wide default for the knowledge-base Agent API Key; the former wins, first non-blank value is used. Never persisted; the browser face is only told whether one exists |
| `NODE_ENV` | unset | Decides static hosting and the default frontend output directory; under `production` the server serves the frontend |

Two sources of configuration, pick by how you run it:

- **Development**: `COSIGHT_PORT=4400 pnpm dev`, or export it in your shell profile. There is **no**
  config-file layer here — one less "I changed it but nothing happened, wrong file" trap.
- **Artifact**: `cosight.env` next to `start.mjs` (`KEY=VALUE`; the template is
  [`scripts/artifact/cosight.env.example`](scripts/artifact/cosight.env.example)). There is a single
  parser (`scripts/lib/env-file.mjs`) so `start.sh` and `start.cmd` cannot drift.
  Precedence: **CLI flags > real environment variables > `cosight.env` > built-in defaults**.

Module configuration is not in this table: a module declares its address and allowed origins in
`$COSIGHT_HOME/modules/<id>/module.json`, and its launch orchestration lives in
`docs/modules/<id>.launch.json` (development) or `<id>.artifact.json` (artifact).

## Quick start

```bash
cd <repo-root>        # the workspace root is the repo root, not framework/
pnpm install
pnpm dev              # backend 4300 + frontend 4310, in parallel
```

Open <http://localhost:4310>. In development the frontend proxies `/api` to 4300 through Vite, so
frontend code only ever uses relative paths. **Do not** point the frontend directly at
`http://127.0.0.1:4300`: the proxy also keeps both sides same-origin, which is what makes the
`SameSite=Lax` bridge cookie travel (`server/src/routes/bridge.ts`). A direct connection would make
cookie behaviour differ between development and production.

To bring the modules (smart-factory, cosight-viewer, …) up as well, use the orchestrator:

```bash
pnpm dev:all          # framework first, then modules by priority, waiting for readiness; Ctrl-C stops everything in reverse
```

### Running frontend and backend separately

Both run in watch mode, so restart only the side you changed:

```bash
pnpm dev:server       # backend only: tsx watch src/index.ts → 127.0.0.1:4300
pnpm dev:web          # frontend only: vite → 127.0.0.1:4310 (proxies /api to 4300)
```

When starting the frontend alone, the backend must already be up; otherwise every request fails to
proxy. You will see a string of `502` / `ECONNREFUSED` in the console rather than a blank page —
Vite itself is fine.

### Production shape (for local verification)

```bash
pnpm build            # builds the frontend dist; the server's build only type-checks and emits no JS
pnpm start            # node framework/scripts/start.mjs: serves web/dist + API, same-origin on :4300
```

In the repository layout `pnpm start` only **health-checks** registered modules, it does not launch
them (development orchestration belongs to `pnpm dev:all`, D27). In the artifact layout it starts
modules from `modules/<id>/artifact.json` first, then the framework.

Regression gate (typecheck + oxlint + tests, 80% coverage threshold):

```bash
pnpm run verify
```

## Scripts

`scripts/` belongs to the **whole repository**, not to any one package — it reaches across
`server/`, `web/` and `docs/`, which is why it sits at the module root.

| Command | What it does |
|---|---|
| `pnpm dev` | Development: backend (4300) and frontend (4310) in parallel |
| `pnpm dev:all` | Development **orchestrator**: framework plus each module's frontend/backend started in priority order, waiting for readiness at each step; Ctrl-C stops everything in reverse. See [`docs/dev-all.md`](docs/dev-all.md) |
| `pnpm start` | Start the server in the **artifact** or repository layout. In the artifact layout it first launches modules from `modules/<id>/artifact.json` and waits for each, then starts the framework; in the repository layout it only health-checks (development orchestration is `pnpm dev:all`'s job, D27). `--self-check` checks only (Node version / layout / data dir / config file / modules); `--init` also creates the data directory and generates the config from the template — this is what the artifact's `install.sh` / `install.cmd` call; `--no-modules` starts the framework alone. `--uninstall` is the reverse: it removes the five plugins and marketplaces from Claude Code (`--dry-run` previews, `--purge-data --yes` also deletes the data directory) — this is what `uninstall.sh` / `uninstall.cmd` call |
| `pnpm test:scripts` | Fast tests for packaging and startup scripts (pure functions plus encoding/EOL rules on the real script files; milliseconds) |
| `pnpm package` | Builds the delivery archive (`tar.gz` + `zip`; one package carries both linux-x64 and win32-x64 natives) with `install.*` + `start.*` + `server/` + `web/` + `modules/` + `start.mjs` at the top level. Which modules get packaged is decided by `docs/modules/*.artifact.json`; stale module frontend builds are rebuilt first |
| `pnpm smoke:package` | Unpacks independently with the system `tar`/`unzip`, simulates an install (`install.sh` → edit config → `start.sh`), starts the services and asserts over HTTP — **modules included**: 2xx on every service port, pages retrievable, `/api/modules` registered, smart-factory's static/SPA/API/WS/database-init paths, and every port released after shutdown |
| `pnpm package:plugin` | Packs a Claude Code plugin directory into an installer (`tar.gz` + `zip`), `agent-genesis` by default; the archive root carries `install.sh` / `install.cmd` / `INSTALL.md`, excluding `work/`, `output/`, `.agent-genesis/`, `.claude/` and `.env`. Use `--plugin <dir>` / `--out <dir>` to change the target; `--compat-manifest` fixes manifest fields **inside the package** according to the current CLI's discovery rules (source untouched; the change lands in the output and `INSTALL.md`) |

The layout constants used by `start` / `package` / `smoke-package` live in
`scripts/lib/project.mjs`: `REPO_ROOT` (repository root: `.package/` and the root `package.json`)
and `MODULE_ROOT` (`framework/`: `server/`, `web/`) are two different roots — do not mix them. What
the artifact should contain and which platform natives it needs are also defined only there
(`ARTIFACT_TARGETS`, `nativePackagesFor()`, `ENTRY_SCRIPT_SOURCES`), and pinned by tests.

## How a module gets mounted

The framework builds no business pages; it only provides mount points. For a module to appear under
a top-level navigation entry in the sidebar, two things are needed:

1. Its pages run on an origin **different from the host's** (D24: on the same origin the iframe
   `sandbox` would be meaningless);
2. A manifest registered in `docs/modules/<id>.module.json` (`id` / `entry` / `allowedOrigins` /
   `mounts`), copied into the runtime directory `$COSIGHT_HOME/modules/<id>/module.json`
   (`pnpm dev:all` does this for you).

To have `pnpm dev:all` actually **run** it locally, add a third thing: a `<id>.launch.json` in the
same directory (service list + ports + readiness paths + priority). That one is **development
orchestration**, not part of the runtime contract — `module.json` has no start-command field and
never will; see [`docs/dev-all.md`](docs/dev-all.md).

A module whose development entry is a **built artifact** (serving some `dist/`) needs one more block
in the same manifest: `build` (command + inputs + outputs). Build outputs are usually not versioned,
so `git pull` does not bring them — without a rebuild you keep running the old bundle, the page
lacks a feature a colleague just merged, and you conclude "it was never implemented". That block is
optional too; modules that run via `npm run dev` do not need it.

The capability slots behind each sidebar entry are defined in `MODULE_CAPABILITIES` in
`shared/src/contracts/module.ts`; the mount points are in `web/src/app/routes.tsx`. When one module
frontend has several pages, `mounts[].entryPath` declares which page of the module a capability
lands on (smart-factory's experts page is `experts → /agents`); without it, `entry` is used
directly. Manifests under `docs/modules/*.module.json` are regression-tested by
`server/tests/module-manifests-doc.test.ts` — a bad manifest degrades to "module not connected"
**silently**, indistinguishable from "never connected", which is why a test has to pin it.

### Shipping a module with the artifact

Beyond the three development-time pieces there is one that only concerns the **artifact**: another
file, `docs/modules/<id>.artifact.json` (assembly manifest: which files are packaged, how to build,
which command starts it on the user's machine). **Its presence means the module is packaged** —
there is no hard-coded list; a module with a `module.json` but without it is reported as "not
packaged" by the packaging output.

The split between the two manifests is deliberate: `launch.json` describes "how to run it on this
developer machine" (`npm run dev`, relative to the repository root), while `artifact.json` describes
"how to run it after packaging and installation" (`node server/index.js`, relative to the module
directory). The artifact has no repository and no npm toolchain, so the former description simply
does not hold there (D41).

Integration notes for connected modules, and what shipping requires:
[`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md),
[`docs/module-artifact-integration.md`](docs/module-artifact-integration.md).

Modules currently in the package are `cosight-viewer` (generic) and `smart-factory` (linux-x64
only). The latter is the multi-service example: the shipped `web-server.mjs` merges static pages,
`/api` reverse proxying and WebSocket upgrades onto a single port, and `db-init.mjs` copies the
database template into the data directory on first start. Both helper scripts come from the
framework side (`scripts/artifact/`) — `smart-factory/` sources are untouched (D42).

## Documentation

| Document | Contents |
|---|---|
| [`server/docs/architecture.md`](server/docs/architecture.md) | Backend architecture and trade-offs (layering, contracts, error model, module registry, iframe bridge) |
| [`docs/framework-decisions.md`](docs/framework-decisions.md) | Framework-level decision log (D1… one by one, with the trade-off and cost of each) |
| [`docs/module-integration-smart-factory.md`](docs/module-integration-smart-factory.md) | A worked integration example and hand-off notes |
| [`docs/module-artifact-integration.md`](docs/module-artifact-integration.md) | For module authors: what shipping requires, how to write the manifests, smart-factory's gaps item by item |
| [`docs/module-facing-api.md`](docs/module-facing-api.md) | Module-facing API: how local modules talk to the framework (models include plaintext keys; three subtrees: models/workspaces read-write, knowledge routes read-only; token required) |
| [`docs/rag-knowledge-api.md`](docs/rag-knowledge-api.md) | Knowledge-base routing API: **can be forwarded as-is to consumers** (two read-only endpoints + auth + fields + five usage rules); the sidebar "Knowledge" entry is its first consumer |
| [`docs/model-config-api.md`](docs/model-config-api.md) | Model configuration API: a self-contained note **you can forward to consumers** (three read + three write endpoints + auth + examples) |
| [`docs/workspace-design.md`](docs/workspace-design.md) | Workspace design: directory layout, slug rules and reserved names, which step touches disk, **read-only browsing (§7: include rules / four limits / loopback gate)**, deliberate divergence from dsh |
| [`docs/workspace-api.md`](docs/workspace-api.md) | Workspace API for consumers: **forwardable as-is** (base URL + auth + seven endpoints + real request/response + client code), plus disk boundaries and the difference between the two faces |
| [`docs/dev-all.md`](docs/dev-all.md) | The orchestrator: startup order, attributing and resolving port conflicts, adding a module |
| [`docs/packaging.md`](docs/packaging.md) | Packaging and cross-platform install: the one-universal-package trade-off, native mechanism, zero symlinks, **modules in the artifact (§6)**, packaging assertions, size comparison, **adding a platform**, manual Windows checklist (no Windows run has been done locally — stated honestly) |
| [`docs/user-guide.md`](docs/user-guide.md) | **Readable manual (start here)**: package → install → start in one line; an acceptance checklist for testers (happy paths / failures / exit codes 0/10/12/13), FAQ for end users, uninstall steps |
| [`docs/operations-manual.md`](docs/operations-manual.md) | **Operations manual**: from source to package (`pnpm build` → `pnpm package`) → unzip and install → start locally → configure → self-check → troubleshooting → uninstall; also `pnpm dev` / `pnpm dev:all` and a command cheat sheet |
| [`docs/uninstall-manual.md`](docs/uninstall-manual.md) | **Uninstall manual (standalone)**: why deleting the directory is not enough (plugins and payload copies live under `~/.claude`), the three-step uninstall, `--dry-run` / `--purge-data --yes`, what the script touches in which order, exit codes 0/12/13, shared marketplaces, ten manual fallback commands, post-uninstall self-check and FAQ |
| [`docs/task-list.md`](docs/task-list.md) | Task list and status |
| [`docs/modules/`](docs/modules/) | Module manifest registry (source of truth in version control) |
| [`web/docs/design-tokens.md`](web/docs/design-tokens.md) | Frontend design tokens |
