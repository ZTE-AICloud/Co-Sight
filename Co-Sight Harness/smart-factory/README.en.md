<div align="center">

# Smart Factory

**Build, preview, and evaluate AI agents through conversation — turning agent creation from a command-line capability into a product with a UI.**

[简体中文](README.md) · [English](README.en.md)

<br/>

![Version](https://img.shields.io/badge/version-0.1.0-46d4e8?style=flat-square)
![Node](https://img.shields.io/badge/Node-%3E%3D20-4ade80?style=flat-square&logo=nodedotjs&logoColor=4ade80)
![React](https://img.shields.io/badge/React-19-46d4e8?style=flat-square&logo=react&logoColor=46d4e8)
![Express](https://img.shields.io/badge/Express-5-1f2937?style=flat-square)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20windows-f0a63a?style=flat-square)
![Local-first](https://img.shields.io/badge/local--first-%E2%9C%94-4ade80?style=flat-square)

</div>

---

## Contents

- [What it is](#what-it-is)
- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Models and secrets](#models-and-secrets)
- [Data and directories](#data-and-directories)
- [UI tour](#ui-tour)
- [HTTP and WebSocket API](#http-and-websocket-api)
- [Project layout](#project-layout)
- [Development and testing](#development-and-testing)
- [Documentation](#documentation)
- [Ecosystem](#ecosystem)
- [Contributing](#contributing)
- [License](#license)

## What it is

Smart Factory is the on-device module of [Co-Sight Harness](../README.md). It runs an API server and a web UI on your machine and provides an end-to-end loop for agents: create, build, preview, and evaluate.

It does not write agents in place of the model. It gives the model a controllable execution structure: requirements are clarified in a conversation, artifacts land in the workspace directory, and every step has gates, records, and a replayable history.

Three core objects:

| Object | Meaning |
|---|---|
| **session** | A persistent conversation bound to one agent (or one directory) and one stage |
| **run** | One execution inside a session; subagent delegations create child runs in the same table and state machine |
| **message** | Every output, every pending request, and every settlement in a run |

Design principles:

- **Local-first**: UI, server, and Claude Code run on the same machine. Files are referenced by local path, and artifacts are written directly to disk — no upload/download round trip.
- **Real engine**: `claude-cli` drives the local Claude Code CLI by default; the `fake` adapter exists only for tests and e2e.
- **Thin UI**: business rules live in server-side services; the front end only reads parameters, renders, and handles interaction.
- **Deliberate non-goals**: no model management, version management, skill marketplace, publishing/installation, or authentication. The agent run page belongs to the framework's session page; this module only provides the "Use" jump.

## Features

| Capability | Description |
|---|---|
| **Agent management** | Metadata CRUD, tags, search, source and production-status filters; status is derived from the artifact directory and never stored |
| **Conversational creation** | Pick a capability on the home page, describe the need in one sentence, and get a complete agent project in a development session; supports first-turn attachments and a knowledge-retrieval workflow |
| **Three-stage workflow** | Build / Preview / Evaluate each have their own session and directory; preview and evaluation run in isolated sandboxes |
| **Live sessions** | WebSocket streaming for text, thinking, and tool events; abort a run; page through history with a message cursor |
| **Approvals and questions** | Tool approvals and interactive questions become pending messages with no timeout; allow once, allow all for the session, or reject |
| **Skill development** | Scan the skill library and attach skills into an agent's artifacts; `/workshop` hosts skill creation and optimization as directory sessions |
| **Evaluation reports** | Read `agent-eval` output and normalize it into report/case DTOs; result quality and trace compliance are kept as two separate scores |
| **Knowledge retrieval** | Read-only proxy for published RAG Studio workflows, selectable when creating an agent |
| **Built-in experts** | Shipped with the product and read-only; registered idempotently from definition directories at startup, with capabilities provided by the corresponding plugins |
| **Bilingual and embeddable** | Chinese and English UI; can be embedded in the framework via iframe, which hides this module's sidebar automatically |
| **Local files** | Agent cover upload, artifact browsing/download, and whole-machine file tree browsing with text preview |

### Three stages, four directories

The backend has four stage directories; the creation flow uses three of them (`runtime` has no creation panel — runs are started from the framework's session page):

| Stage | stage / directory | cwd | How the directory is produced |
|---|---|---|---|
| Build | `development` | `<agentRoot>/development/` | Created with the agent; the development session builds the agent project here |
| Preview | `preview` | `<agentRoot>/preview/` | Materialized from the latest `vN` under development before every run; skipped when the source is unchanged |
| Evaluate | `evaluation` | `<agentRoot>/evaluation/` | Ensures preview first, then materializes from the preview sandbox; skipped when the source is unchanged |
| Runtime | `runtime` | `<agentRoot>/development/output/agents/{name}/{latest vN}/` | Runs the development artifact in place, without copying |

- **Preview and evaluation are isolated copies**: edits, deletions, or a runaway run inside the sandbox do not touch the development artifacts.
- **Preview and evaluation are gated**: entering requires `ready` from `GET /agents/{id}/production`. The gate checks delivery files and quality-gate results; missing artifacts, missing versions, or an unfinished pipeline fail loudly.
- **Evaluation results belong to a source version**: when development changes and the sandbox is recopied, old evaluation reports are cleared with it.

## Architecture

```text
Browser  React 19 + Vite (:4110)
├── /                     Home: create from one sentence · 5 capabilities
├── /agents               Experts / skill library
├── /agents/:id/design    Design page: Build · Preview · Evaluate
└── /workshop             Skill development
        │
        │  REST + WebSocket   /api/smart-factory/v1
        ▼
Smart Factory Server  Express 5 + TypeScript (:4100)
├── Domains  agent · session · run · artifact · evaluation · skill ·
│           knowledge · files · fs · model · workspace · health
├── Data     $COSIGHT_HOME/smart-factory.db (SQLite)
└── Engine   claude-cli | fake
        │                                    │
        │ read-only module API (module token) │ run / stream / approvals
        ▼                                    ▼
Cosight Framework                     Claude Code CLI (installed by the user)
workspaces · models · knowledge        cwd = stage sandbox or artifact
```

The server is split by capability domain. Each domain has a fixed four-file shape, and dependencies only flow one way: `routes → controller → service → store`.

| Layer | Location | Responsibility |
|---|---|---|
| Routes | `modules/<domain>/<domain>.routes.ts` | Maps paths and HTTP methods to controllers |
| Controller | `modules/<domain>/<domain>.controller.ts` | Reads parameters, calls the service, assembles the response |
| Service | `modules/<domain>/<domain>.service.ts` | The only place for business logic: orchestration, transactions, validation, state machines |
| Repository | `shared/store/*.repo.ts` | ORM calls and row-to-domain mapping |
| Realtime | `shared/live/` | Connections, envelope encoding, fan-out, heartbeat, backpressure |
| Engine | `shared/engine/` | Normalizes the CLI protocol; depends on no Anthropic package and only spawns the user-installed `claude` |
| Workspace | `shared/workspace/` | Path derivation, sandbox materialization, production gates |

## Quick start

### Prerequisites

- **Node.js >= 20** (npm included).
- **A running [Co-Sight Harness framework](../framework/)** (default `http://127.0.0.1:4300`): workspaces, models, and knowledge routing are preferably read from it.
- **Claude Code CLI installed and configured with a usable model**: the real engine spawns the local `claude` and talks to it over the stream-json / control protocol.
- **Windows**: install Git for Windows first — the engine's Bash tool needs Git Bash. If auto-detection fails, point `CLAUDE_CODE_GIT_BASH_PATH` at `bash.exe`.
- **The distribution ships no Claude Code / Agent SDK**: the CLI is a user-side prerequisite, installed and licensed by the user; this service only invokes it.

### Start

```bash
cd smart-factory

node scripts/dev.mjs setup   # first run: install deps, create server/.env, prisma generate, create the DB
node scripts/dev.mjs start   # start server and web in the background
```

Open <http://localhost:4110>.

`setup` installs dependencies for `server/` and `web/`, copies `server/.env.example` to `server/.env` if missing, generates the Prisma Client, creates the data directory, and builds the database (`prisma db push` + `bootstrap.sql`). The database is created with `db push`, not migration files.

### Verify

```bash
curl -s http://127.0.0.1:4100/api/smart-factory/v1/health
# {"status":"ok","service":"smart-factory-server","version":"0.1.0","time":"..."}
```

If the framework is not running, the health check still succeeds, but workspace-, model-, and artifact-related calls return an explicit `502` — no guessed paths, no silent fallback.

Run the full session flow end to end (temporary server, isolated data directory, framework stub; `fake` engine by default):

```bash
node scripts/dev.mjs e2e
```

Run the same flow with the real engine:

```bash
ENGINE=claude-cli SF_PROMPT="Create a.txt with the Write tool" node scripts/dev.mjs e2e
```

On Windows, set environment variables with `set ENGINE=...` (cmd) or `$env:ENGINE="..."` (PowerShell).

### Stop, status, and logs

```bash
node scripts/dev.mjs status
node scripts/dev.mjs stop
node scripts/dev.mjs restart
```

Logs are written to `.run/logs/` (`server.log` / `web.log`); tail those files to follow a run.

## Configuration

Backend configuration is read in one place, `server/src/config/index.ts`. `setup` generates `server/.env` from `server/.env.example`. The commonly used settings:

| Variable | Default | Description |
|---|---|---|
| `COSIGHT_HOME` | `~/.cosight-harness` | Data root, shared with the framework (`path.resolve`; `~` is not expanded). Both processes must point at the same directory |
| `FRAMEWORK_BASE_URL` | `http://127.0.0.1:4300` | Framework module API. Read-only GET; the token is read from `{COSIGHT_HOME}/.module-token` on every request |
| `HOST` / `PORT` | `0.0.0.0` / `4100` | Server listen address. All interfaces by default (reachable from the local network); the service has no authentication and `/fs/*` can browse the whole machine, so keep it on trusted networks or set `127.0.0.1` for local-only access |
| `CORS_ORIGIN` | `*` | Allowed cross-origin front-end origins |
| `ENGINE` | `claude-cli` | Engine adapter: `claude-cli` or `fake`. Unknown values refuse to start |
| `CLAUDE_CODE_PATH` | empty | Explicit path to the `claude` executable; empty means resolve from `PATH` |
| `SKILLS_ROOT` | `{COSIGHT_HOME}/smart-factory/skill-workshop` | cwd for skill-development sessions; the skill library is its `output/skills/` |
| `CHAT_ROOT` | `{COSIGHT_HOME}/smart-factory/chat` | Fallback cwd for free chat when no workspace is active |
| `WS_HEARTBEAT_MS` | `30000` | WebSocket heartbeat interval; timeout is twice the interval |
| `WS_MAX_BUFFERED_BYTES` | `4194304` | Per-connection send buffer limit; exceeding it marks a slow consumer and disconnects |
| `ARTIFACT_MAX_FILE_BYTES` | `2097152` | Text artifact read limit; `413` above it. Downloads are not limited |
| `FILES_MAX_FILE_BYTES` | `10485760` | Single upload size limit; `413` above it |
| `EVALUATION_MAX_JSON_BYTES` | `5242880` | Read limit for evaluation JSON / JSONL files |
| `AUTO_META` | enabled | Auto-generate name, description, and tags after creation; set `0` to disable |
| `CO_KNOWLEDGE_BASE_URL` | empty | **Fallback** RAG Studio root URL (e.g. `http://rag-studio.example.com`); an active framework route takes precedence |
| `CO_KNOWLEDGE_API_KEY` | empty | **Fallback** Agent API key (`ragk_...`), sent as `X-API-Key`; the active value from the framework takes precedence |
| `CO_KNOWLEDGE_LIST_TIMEOUT_MS` | `8000` | Timeout for knowledge workflow list requests |
| `SMART_FACTORY_SERVER_PORT` / `SMART_FACTORY_WEB_PORT` | `4100` / `4110` | Used only by `scripts/dev.mjs` and Vite |

The front end normally needs no configuration: in development Vite proxies `/api` to the backend, and front-end code only uses relative paths. To bypass the proxy, copy `web/.env.example` to `web/.env.local` and follow the comments for `VITE_API_BASE_URL`, `VITE_WS_BASE_URL`, `VITE_FRAMEWORK_HOME_URL`, and related variables.

## Models and secrets

- Models are managed by the framework. This service has **no model table, no model CRUD, and no credential settings**.
- `sessions.modelId` stores a framework model UUID and is **always non-empty**: required by `sessions/create` and `send { agentId }`; switching can only replace it with another non-empty model, and clearing is not supported. The server has no fallback to a workspace default, the framework's active model, or the local Claude Code configuration.
- Before creating the first preview/evaluation session, the web UI resolves a default model itself (workspace `defaultModelId` → framework `activeId` → first item), then passes it explicitly.
- When a run starts, the server reads `modelName` / `baseUrl` / `apiKey` from the framework and injects them into the engine subprocess. **Secrets are never persisted, never sent to the browser, and never written to logs or error messages.**

## Data and directories

The module database and agent artifacts live in two places:

```text
{COSIGHT_HOME}/
├── smart-factory.db            # module DB (SQLite: agents / instances / sessions / runs / messages)
├── .module-token               # framework module API token, read per request
└── smart-factory/
    ├── builtin-agents/         # built-in expert definitions, read-only
    ├── skill-workshop/         # cwd for skill-development sessions
    │   └── output/skills/      # skill library: <name>/vN/{SKILL.md,references/,scripts/,templates/}
    └── chat/                   # fallback cwd for free chat without an active workspace

{workspace.directory}/.smart-factory/
└── agents/{agentId}/
    ├── development/            # Build cwd; the agent project itself
    │   └── output/agents/{agentName}/{latest vN}/
    ├── preview/                # preview sandbox (materialized from the latest development vN)
    ├── evaluation/             # evaluation sandbox (materialized from preview) and reports
    └── .state/                 # materialization markers (not a stage dir; hidden from artifact browsing)
```

- **An agent is one metadata row plus one artifact directory.** `id` is the only link between them, and the directory name is the `id`.
- **Agents belong to a framework workspace.** `workspaceId` is required at creation and immutable; built-in agents belong to no workspace.
- **`status` is derived**, computed from the development directory's process state, delivery gates, and artifacts. Values: `not_started` / `building` / `blocked` / `failed` / `completed`. Never stored.
- **Disk first, then DB**: at startup the server adopts agent directories that exist on disk but not in the table, and registers built-in experts idempotently.

## UI tour

| Path | Page | Description |
|---|---|---|
| `/` | Home | Describe the need in one sentence; five capabilities: create agent, create skill, optimize agent, optimize skill, evaluate agent |
| `/agents` | Experts · Skills | Two tabs: agent list (search, tags, source and production-status filters) and skill library |
| `/agents/:agentId/design` | Design page | Build / Preview / Evaluate; `?stage=preview\|evaluation` opens a stage directly |
| `/workshop` | Skill development | Directory sessions for creating and optimizing skills; the right pane is the skill file tree |

- **"Use" does not stay in this module**: it navigates the whole page to the framework's session page.
- **Built-in experts are read-only**: no design or evaluation; only "Use" is offered.
- **When embedded in the framework** (`window.self !== window.top`), the sidebar is hidden automatically; `?embed=1/0` forces either state for debugging.

## HTTP and WebSocket API

- Base path: `/api/smart-factory/v1`; REST and WebSocket share the same port and prefix.
- In development Vite proxies `/api`, so front-end code only uses relative paths.
- Successful responses always use `200`. The error envelope and general conventions are in [4.02 Common conventions](server/docs/04-api/4.02-通用规范.md).

### REST

| Group | Endpoints | Purpose |
|---|---|---|
| Health | `GET /health` | 200 while the process is alive |
| Agents | `GET/POST /agents`, `GET /agents/{id}`, `POST /agents/{id}/update`, `POST /agents/{id}/delete`, `GET /agents/tags`, `GET /agents/{id}/production`, `GET/POST /agents/{id}/skills`, `POST /agents/{id}/skills/remove` | Metadata, tags, production status, product skills |
| Workspaces | `GET /workspaces/list`, `GET /workspaces/directories/list` | Read-only framework workspace proxy (plus the observer directory list) |
| Sessions | `GET /sessions/list`, `POST /sessions/create`, `GET /sessions/detail`, `POST /sessions/{id}/update`, `POST /sessions/delete`, `POST /sessions/abort` | Session lifecycle |
| Messages | `GET /messages/list`, `POST /messages/send`, `POST /messages/respond` | Message stream, send-and-run, settle approvals/questions |
| Runs | `GET /runs/list`, `GET /runs/detail`, `GET /runs/children`, `POST /runs/abort` | Top-level and child runs |
| Artifacts | `GET /artifacts/list`, `GET /artifacts/file`, `GET /artifacts/download` | Read-only browsing of the four stage directories |
| Evaluations | `GET /evaluations/list`, `GET /evaluations/detail`, `GET /evaluations/cases/list`, `GET /evaluations/cases/detail` | Normalized evaluation reports |
| Skills | `GET /skills` | Skill library plus skills produced by agents in the current workspace |
| Models | `GET /models/list` | Read-only framework model proxy; never includes secrets |
| Knowledge | `GET /knowledge/workflows/list` | Read-only proxy for published RAG Studio workflows |
| Files | `POST /files`, `GET /files/{fileId}` | Upload and read (agent covers, etc.) |
| Local files | `GET /fs/roots`, `GET /fs/list`, `GET /fs/read`, `GET /fs/raw/*` | Whole-machine file tree browsing and preview |

The full endpoint table is in [4.01 API overview](server/docs/04-api/4.01-接口总览.md). The agent and file domains are specified by OpenAPI contracts ([5.01](server/docs/05-openapi/5.01-agent-openapi.yaml), [5.02](server/docs/05-openapi/5.02-file-openapi.yaml), [5.03](server/docs/05-openapi/5.03-agent-production-openapi.yaml)).

### WebSocket

Endpoint: `ws://localhost:4100/api/smart-factory/v1/ws`.

| Direction | Methods |
|---|---|
| Client → server | `send`, `subscribe` / `unsubscribe`, `message.respond`, `run.abort`, `ping`, plus compatibility methods `history`, `approval.respond`, `tool.respond`, `model.switch`, `mode.switch`, `effort.switch` |
| Server → client | `connection.ready`, `session.status`, `run.started` / `run.status`, `task.started` / `task.notified`, `message`, `chat.delta` / `chat.thinking` / `chat.final` / `chat.error` / `chat.aborted`, `approval.request`, `tool.interactive` / `tool.executing` / `tool.executed`, `error` |

- Live events are **not replayed**: after a reconnect or page refresh, use REST to fill in history.
- `chat.delta` and `chat.thinking` are transient increments, not persisted — they exist only for incremental rendering.
- Approvals and questions have no timeout; the server never emits `interactive.timeout`.

Envelopes, payloads, heartbeat, and backpressure are documented in [4.06 Realtime channel](server/docs/04-api/4.06-实时通道.md).

## Project layout

```text
smart-factory/
├── server/                       Backend service
│   ├── src/
│   │   ├── index.ts              Process entry: startup order, graceful shutdown, WS gateway
│   │   ├── app.ts                Application wiring: middleware + routes
│   │   ├── config/               Centralized environment configuration
│   │   ├── modules/              Capability domains: agent / session / run / artifact / evaluation /
│   │   │                         skill / knowledge / files / fs / model / workspace / health
│   │   └── shared/               Engine, realtime, repositories, workspace, skills, types, errors
│   ├── prisma/                   Schema and bootstrap.sql
│   ├── builtin-agents/           Built-in expert definitions
│   ├── tests/                    Unit, API-contract, and e2e tests
│   └── docs/                     Design docs and OpenAPI contracts
├── web/                          Front end
│   ├── src/
│   │   ├── features/             Domain pages: home / agent-list / agent-create /
│   │   │                         skill-library / skill-workshop
│   │   ├── shared/               API clients, live client, shared components, command builders
│   │   ├── i18n/                 zh-CN / en-US messages
│   │   └── styles/
│   └── docs/                     Front-end handoff and contract notes
├── scripts/                      dev.mjs single entry: setup / start / stop / restart / status / e2e
└── .run/                         Runtime artifacts: PID and logs (gitignored)
```

Convention: **one front-end `features/<domain>` maps to one backend `modules/<domain>`**. Only cross-domain code moves up into `web/src/shared/` or `server/src/shared/`.

## Development and testing

```bash
# Backend
cd server
npm run typecheck          # tsc --noEmit
npm test                   # node --test (integration tests do not listen on a port)

# Front end
cd web
npm run typecheck
npm run build              # tsc -b && vite build
npm run check:i18n         # message completeness check

# End to end (fake engine + framework stub + isolated data directory)
node scripts/dev.mjs e2e
```

Working agreements:

- **Contract first**: change `server/docs/04-api/` or `05-openapi/` before the implementation. The same fact is allowed in exactly one place.
- **Layering discipline**: routes contain no logic, controllers never touch stores, and services contain no HTTP concepts.
- **Front-end messages**: `zh-CN.ts` is the single source of truth for message shape; `en-US.ts` is type-constrained, so a missing translation is a compile error.
- **Artifacts are the ground truth**: when debugging, inspect the actual files under `development/`, `preview/`, `evaluation/`, and `.agent-genesis/` before comparing database rows.

## Documentation

The design docs are currently written in Chinese:

| Document | Contents |
|---|---|
| [Documentation index](server/docs/README.md) | The single entry point for all design docs and naming rules |
| [Architecture](server/docs/03-architecture/01-architecture.md) | Scope and boundaries, layering, API style, configuration, runtime requirements |
| [Data model](server/docs/03-architecture/02-data-model.md) | Five tables, state machines, seq allocation, cascades, invariants |
| [Sessions and runs](server/docs/03-architecture/03-session-run.md) | Four stage directories, sandbox materialization, lifecycle orchestration |
| [Engine seam](server/docs/03-architecture/04-engine.md) | Engine port, registry, adapters |
| [Realtime channel](server/docs/03-architecture/05-realtime.md) | WS envelopes, fan-out, heartbeat, backpressure |
| [Approvals and questions](server/docs/03-architecture/06-approval.md) | Approval-as-message, settlement protocol, session-level `approved_all` |
| [Artifact browsing](server/docs/03-architecture/07-artifact.md) | Read-only browsing of stage directories and path safety |
| [Agents](server/docs/03-architecture/08-agent.md) | Metadata rows and artifact directories, status, startup adoption, tags |
| [Skill library and directory sessions](server/docs/03-architecture/10-skill-library.md) | Directory instances, skill scanning, workshop cwd |
| [API overview](server/docs/04-api/4.01-接口总览.md) | Base path, document map, REST / WS endpoint tables |
| [Front-end handoff](web/docs/) | Capability routing, contracts, environment variables, known deviations |

## Ecosystem

Smart Factory reuses skills provided by plugins in the same repository:

| Plugin | Skills used | Scenario |
|---|---|---|
| [agent-genesis](../agent-genesis/) | `harness-create`, `skill-foundry` | Create/optimize agents, create skills |
| [goldeval](../agent-evaluator/) | `agent-eval`, `goldeval`, `traceaudit` | Generate test sets, execute, score, audit traces |
| [skill-optimizer](../skill-optimizer/) | `skill_optimize` | Score-driven skill iteration |
| [drive](../drive/) | `drive` | Multi-stage delivery flow for the built-in "Software R&D Team" expert |
| [cosight-bot](../cosight-bot/) | `pkm`, `soc` | Knowledge management and bid response for the built-in "Enterprise Knowledge Assistant" expert |

Plugins must be installed in the local Claude Code for sessions to call their skills. When a plugin is missing, built-in experts declare a fallback in their `CLAUDE.md` or state plainly that the capability is unavailable.

## Contributing

- Prefix commit messages with `feat / fix / refactor / docs / test / chore / perf / ci`.
- Change the contract docs before the API, and run the acceptance tests mapped to the affected document.
- Before merging, at minimum run `typecheck` + `test` for `server`, and `typecheck` + `build` for `web`. API shape changes also require `node scripts/dev.mjs e2e`.
- Record design trade-offs in `99-adr/` (one decision per file). Process history does not belong in the reference docs.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

This distribution **does not include or redistribute** Anthropic's Claude Agent SDK or Claude Code CLI. The real execution engine is an optional integration: users install the Claude Code CLI on their own machine and accept Anthropic's terms. Without it, agent creation, management, and browsing still work; the run entry point shows installation guidance.
