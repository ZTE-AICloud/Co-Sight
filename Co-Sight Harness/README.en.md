<div align="center">

# Co-Sight Harness

**A runtime control structure for agents, built around the model**

[简体中文](README.md) · [English](README.en.md)

[Quick start](QUICKSTART.en.md) · [Architecture](#architecture) · [Components](#components) · [Docs](#documentation)

<br/>

![Version](https://img.shields.io/badge/version-0.1.0-46d4e8?style=flat-square)
![Node](https://img.shields.io/badge/Node-%5E22.19_%7C%7C_%3E%3D24-4ade80?style=flat-square&logo=nodedotjs&logoColor=4ade80)
![Platform](https://img.shields.io/badge/platform-linux_x64_%7C_win_x64-f0a63a?style=flat-square)
![Runtime](https://img.shields.io/badge/runtime-Claude_Code_%7C_Codex_%7C_DSH-46d4e8?style=flat-square)
![Local-first](https://img.shields.io/badge/Local--first-%E2%9C%94-4ade80?style=flat-square)
![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square)

</div>

---

Co-Sight Harness is a **local-first agent host**. It ties agent runtimes such as Claude Code, Codex
and DSH into one front-end / back-end shell, and holds long-running, knowledge-intensive business
tasks in place with versioned and auditable control data — goals, state, context, tools, permissions,
verification and evidence — so they stay stable well beyond the demo.

It does not train models and does not think for them. It builds **the control structure around the
model**.

```bash
# From source: two commands to bring the framework up (see QUICKSTART.en.md)
pnpm install && pnpm dev

# From the distributed artifact: unzip, then two commands
./install.sh && ./start.sh
```

---

## Table of contents

- [What it is](#what-it-is)
- [Why it exists](#why-it-exists)
- [Core capabilities](#core-capabilities)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Components](#components)
- [Requirements](#requirements)
- [Source development](#source-development)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## What it is

Coding agents are reliable because compilers, tests and CI are ready-made referees with a
minute-level feedback loop. Real business agents — requirements analysis, solution design, impact
assessment — run for hours or days across knowledge-intensive work with fuzzy feedback and no
referee. However good a single step is, errors compound along the chain and the goal drifts.

Co-Sight Harness puts the answer **outside the model**: state, constraints and acceptance criteria
are not left to the LLM's self-discipline, but guaranteed by the harness structure. Around the
probabilistic core it establishes four control planes:

| # | Question | Control plane | Capability |
|:---:|:---|:---|:---|
| `01` | What must be done? | **Business** | Goal · Constraint · Acceptance · Risk: break monolithic skills apart — a coordinator drives the flow, executors work from a checklist, verifiers strip out deterministic logic; generation and evaluation stay separate |
| `02` | What happens next? | **Execution** | Orchestrator · Loop · Graph · State · Checkpoint: a control layer drives the pipeline, state lives outside the model, work resumes from checkpoints, failed evaluations return with evidence |
| `03` | What experience is available? | **Assets** | Knowledge · Memory · Tool · Skill · Policy: retrieval at runtime so the agent can find it, authoring at build time so the knowledge is complete |
| `04` | How do we prove it was done right? | **Evidence** | Trace · Eval · Review · Version · Rollback: a three-level metric system, an evaluation loop that decides what to change, and merge only after regression passes |

> **One principle: control data lives outside the model.**

---

## Why it exists

A step that is 95% correct leaves only 60% after ten steps in series:

```text
  0.95 × 0.95 × … × 0.95  ≈  0.60

  STEP 1  ██████████████████▋░  95%
  STEP 5  ███████████████▎░░░░  77%
  STEP 10 ████████████▋░░░░░░░  60%   ← measured end-to-end completion without human help: ~50%
```

Uncertainty comes from three directions and grows along the chain:

| Source | Symptom |
|:---|:---|
| `LLM` probabilistic output | The same input does not guarantee the same path; drift accumulates and errors propagate |
| `USER` constraints kept in someone's head | Acceptance criteria and boundaries are never stated, so the model guesses; wherever they are missing, quality depends on a human watching |
| `ENV` unstable supply | Knowledge is scattered, tools and permissions are limited, calls are slow; the answer sits in the knowledge base but cannot be reached |

The harness answer is to **stop errors from compounding**: every step gets a gate — pass and the
flow moves on, fail and it comes back with evidence. Ten steps in series become ten independent
passes.

```text
CONTROLLED EXECUTION LOOP

 ┌──────────┐    ┌────────┐    ┌─────────┐    ┌────────────┐
 │ ANALYSIS │ ─▶ │  PLAN  │ ─▶ │ EXECUTE │ ─▶ │ EVALUATION │
 │ clarify  │    │ plan   │    │ run     │    │ test·grade │
 └──────────┘    └────────┘    └─────────┘    └────────────┘
      ▲                                            │
      └──────────  failed evaluation, back with evidence  ◀──┘
```

---

## Core capabilities

| Capability | What it means |
|:---|:---|
| **The executor does not grade itself** | Generation and evaluation are separated: a verifier independent of the executor, deterministic logic moved out of prompts into hooks and scripts, progress only after DOD review |
| **Multi-day chains, no re-explaining** | State and checkpoints all live outside the model; a task stopped today resumes tomorrow with context, decision records and artifacts intact |
| **Humans exit by confidence** | Low confidence → human fallback; medium → LLM review plus spot checks; high → scripts / grep / schema with no human. High-risk and unknown task types always keep a human in the loop |
| **Describe the need, get control data** | A colloquial request is turned into a task definition, executable checks (DOD) and domain skills; no need to learn the internal conventions first |
| **Change config, not code** | Policies and rules are versioned independently; every change is evaluable and reversible, with impact analysis and regression eval |
| **Faster every time** | Every run deposits assets: building a new test case drops from 2–4 hours to 5–10 minutes |

Measured on real business acceptance work:

| Dimension | Metric | Before → after | Change |
|:---:|:---|:---:|:---:|
| Efficiency | Requirements analysis | `169 min` → **56.4 min** | `-67%` |
| Efficiency | Subsystem design | `114 min` → **26.5 min** | `-77%` |
| Quality | Scenario sub-task F1 | `68%` → **91.25%** | `+34%` |
| Reliability | Task completion rate | `50%` → **100%** | `+100%` |

---

## Architecture

Harness assets drive execution; the enablement centre closes the *produce · evaluate · optimise*
loop; the knowledge engine and model supply sit underneath as external dependencies:

```text
INTERACTION · session UI
│  Session UI — dispatch tasks · review results
│  Observability — run status / logs
   │
   ▼  dispatch · asset loading
HARNESS · cosight-harness
│  Harness assets (built-in · custom)
│    ▸ software development expert · domain experts 1…N · expert teams 1…N
│  Agent execution support
│    ▸ asset loading · session management · agent run management · agent loop integration · runtime data · trace
   │
   ▼  generate → evaluate → optimise loop
ENABLEMENT
│  ① AgentGenesis (produce harness assets) → ② Drive (task-driven execution)
│       → ③ agent-evaluator (result · process evaluation) → ④ skill-optimizer (skill self-optimisation)
│  ↺ optimised assets flow back · produce → execute → evaluate → optimise
   │
   ▼  agent loop integration
AGENTCORE
│  Cosight Pro · Claude Code · DSH · … — a model-agnostic execution loop
   │
   ▼  context fetch · model inference
EXTERNAL
│  Knowledge engine — knowledge management / context / retrieval / graph services
│  LLMs — embedding / rerank / LLM / … · behind one proxy, models are swappable
```

> Assets are produced in enablement, executed on AgentCore, informed by external knowledge.

---

## Repository layout

```text
cosight-harness/
├── framework/        # Host shell: server/ (Fastify API) + web/ (unified shell) + shared/ (contracts)
├── drive/            # Declarative multi-agent orchestration engine (Claude Code / DSH plugin)
├── agent-genesis/    # Requirement → Agent / Skill asset generation plugin
├── agent-evaluator/  # Agent evaluation plugin (install ID: goldeval)
├── skill-optimizer/  # Skill evaluation-optimisation loop plugin
├── cosight-bot/      # CoSightBot: knowledge management / bid response plugin
├── cosight-viewer/   # Task centre: session observability + task management (local service)
├── smart-factory/    # Smart Factory: build / preview / evaluate agents in a UI (local service)
├── dsh-compat/       # Compatibility layer that mounts the five plugins onto DeepSeek Harness
├── install-dsh.sh    # One command to install all five plugins into dsh
├── package.json      # Workspace root: pnpm workspace + repository-level scripts
└── pnpm-workspace.yaml
```

**Component conventions** (please follow these when adding one):

- Top-level directories are **kebab-case** and match the component's English name.
- **Plugin components** follow Drive's layout: `.claude-plugin/` + `agents/` + `skills/` + `hooks/` + `tests/`.
- **Service components** usually carry `server/`, `web/`, `docker-compose.yml` and `docs/`.
- A module root carries no `package.json`: service components own their internal layout, and
  **every pnpm command runs at the repository root**.
- Component metadata is registered in `.claude-plugin/plugin.json` (plugins) or in the module manifest (services).

---

## Quick start

Two paths — pick by who you are. Full steps, failure handling and an acceptance checklist live in
**[QUICKSTART.en.md](QUICKSTART.en.md)**.

**Path A · distributed artifact** (no pnpm, no build, no network needed):

```bash
tar -xzf cosight-harness-*.tar.gz      # Windows: right-click → Extract All
cd cosight-harness-*/
./install.sh                           # preflight + data dir + config + five plugins
./start.sh                             # start framework and modules, health-check each
# open http://127.0.0.1:4300
```

On Windows, double-click `install.cmd`, then `start.cmd`.

**Path B · from source** (development / customisation):

```bash
git clone https://github.com/ZTE-AICloud/Co-Sight.git
cd "Co-Sight/Co-Sight Harness"
corepack enable && pnpm install        # Node ^22.19.0 || >=24.0.0, pnpm 11.28.5
pnpm dev                               # framework: API 4300 + web dev server 4310
# open http://localhost:4310
```

To bring the modules (cosight-viewer, smart-factory) up as well, use the aggregate launcher.
Install each module's dependencies first, following its README:

```bash
pnpm dev:all
```

---

## Components

| Component | Form | Description | Version |
|:---|:---:|:---|:---:|
| [`framework/`](framework/) | Service | Unified entry: sidebar + workspace + module iframe host + module-facing API | `0.1.0` |
| [`cosight-viewer/`](cosight-viewer/) | Service | Task centre: Claude Code session observability and task management (single machine) | `1.2.1` |
| [`smart-factory/`](smart-factory/) | Service | Smart Factory: build, preview and evaluate agents conversationally | `0.1.0` |
| [`drive/`](drive/) | Plugin | Declarative multi-agent orchestration, `phase` / `dag` modes | `2.3.4` |
| [`agent-genesis/`](agent-genesis/) | Plugin | Natural-language requirement → runnable Agent / Skill (Claude Code and DSH) | `0.23.0` |
| [`agent-evaluator/`](agent-evaluator/) | Plugin | Golden-set evaluation, E2E case generation / execution / scoring, trace audit (install ID `goldeval`) | `1.0.0` |
| [`skill-optimizer/`](skill-optimizer/) | Plugin | Skill evaluation-optimisation loop: evaluate → gap analysis → optimise → re-evaluate | `1.0.0` |
| [`cosight-bot/`](cosight-bot/) | Plugin | CoSightBot: personal knowledge management + bid response (install ID `cosightbot`) | `0.1.0` |
| [`dsh-compat/`](dsh-compat/) | Compat layer | Mounts the five plugins onto DeepSeek Harness native surfaces | — |

A Claude Code plugin is installed by `<plugin name>@<marketplace name>`, **not** by its directory
name: `drive@zte-ai-lab`, `agent-genesis@agent-genesis`, `goldeval@goldeval`,
`skill-optimizer@skillx`, `cosightbot@cosightbot`.

---

## Requirements

| Item | Requirement | Notes |
|:---|:---|:---|
| `Node.js` | `^22.19.0` or `>=24.0.0` | Matches the server's `engines`; on a mismatch the installer prints a download link |
| `pnpm` | `11.28.5` | Source development only; pinned in the root `package.json` `packageManager` field — run `corepack enable` |
| `Claude Code` | CLI `>= 2.1.287` | Used by the artifact installer for the five plugins; skip with `--skip-plugins` |
| `Python 3` | `python3` on PATH | Needed by plugin hooks and cosight-bot scripts |
| Platform | Linux x64 / Windows x64 | One archive carries native dependencies for both platforms |

---

## Source development

Run every command at the **repository root** (`framework/` has no `package.json`).

| Command | Purpose |
|:---|:---|
| `pnpm dev` | Framework in dev mode: API 4300 + web 4310 (`/api` proxied by Vite to 4300) |
| `pnpm dev:server` / `pnpm dev:web` | Back end only / front end only (watch mode) |
| `pnpm dev:all` | Aggregate launcher: framework + registered modules (cosight-viewer 4830, smart-factory 4100/4110), each step waits for readiness, Ctrl-C stops in reverse order |
| `pnpm build` | Build the web bundle (the server build only type-checks) |
| `pnpm start` | Run in artifact form: serves `web/dist` + API on the same origin at 4300 |
| `pnpm typecheck` / `pnpm lint` | `tsc --noEmit` / `oxlint` |
| `pnpm test` | Script tests + every package's tests |
| `pnpm test:coverage` | Coverage (80% threshold) |
| `pnpm verify` | **Pre-commit gate**: typecheck + lint + all tests |
| `pnpm package` | Produce delivery archives (`tar.gz` + `zip` under `.package/`) |
| `pnpm smoke:package` | Independently unzip, simulate install and start, assert every port answers over HTTP |

The data directory defaults to `~/.cosight-harness` (`COSIGHT_HOME`) and is created, with
migrations, on first start.

---

## Documentation

| Document | Contents |
|:---|:---|
| [QUICKSTART.en.md](QUICKSTART.en.md) | **Start here**: the artifact and source paths, ports, configuration, troubleshooting, uninstall |
| [`framework/docs/user-guide.md`](framework/docs/user-guide.md) | Package → install → start in one line; acceptance checklist and FAQ (Chinese) |
| [`framework/docs/operations-manual.md`](framework/docs/operations-manual.md) | Operations manual: packaging, install, start, configuration, self-check, uninstall (Chinese) |
| [`framework/docs/packaging.md`](framework/docs/packaging.md) | Packaging and cross-platform install: native packages, assertions, Windows checklist (Chinese) |
| [`framework/docs/uninstall-manual.md`](framework/docs/uninstall-manual.md) | Uninstall: plugin payload copies, three steps, exit codes, manual fallback (Chinese) |
| [`framework/docs/dev-all.md`](framework/docs/dev-all.md) | Aggregate launcher: start order, port conflicts, adding a module (Chinese) |
| [`framework/docs/module-facing-api.md`](framework/docs/module-facing-api.md) | Module-facing API: models, workspaces, knowledge routing (Chinese) |
| [`framework/docs/module-artifact-integration.md`](framework/docs/module-artifact-integration.md) | What a module needs to ship inside the artifact (Chinese) |
| [`framework/docs/plugin-install.md`](framework/docs/plugin-install.md) | What the five plugins install, where, and how to debug (Chinese) |
| [`dsh-compat/README.en.md`](dsh-compat/README.en.md) | Installing the five plugins into DeepSeek Harness (dsh) |

Each component's architecture, configuration and API docs live in its own `README.md` and `docs/`.

---

## Contributing

Issues and pull requests are welcome.

| Item | Convention |
|:---|:---|
| Commit message | `<type>: <description>`, type ∈ `feat / fix / refactor / docs / test / chore / perf / ci` |
| Pre-commit gate | `pnpm verify` (typecheck + lint + tests, 80% coverage threshold) must pass |
| New component | Follow the [component conventions](#repository-layout): kebab-case directory, plugin or service layout, metadata in `plugin.json` |
| New module integration | Register a manifest under `framework/docs/modules/`, then decide about shipping it via [`module-artifact-integration.md`](framework/docs/module-artifact-integration.md) |
| Security | Never commit plaintext secrets; credentials come from environment variables or `.credentials.yaml` in the data directory |
| Pull request | State the motivation, the scope of change and how it was tested; update the relevant docs when behaviour changes |

---

## License

This project is licensed under the [Apache License 2.0](LICENSE),
Copyright 2026 ZTE Corporation. Every component directory carries the same license;
third-party notices are listed in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).

---

## Acknowledgements

The [`cosight-viewer/`](cosight-viewer/) component was designed and implemented with reference to,
and reuse of, parts of the open-source project
[**Claude-Code-Agent-Monitor**](https://github.com/hoangsonww/Claude-Code-Agent-Monitor)
(MIT License, Copyright (c) 2026 - Now, Son Nguyen). Our thanks to that project, its author and its
community.

As required by the MIT License, the upstream copyright and permission notices are preserved in full
in [`cosight-viewer/NOTICE`](cosight-viewer/NOTICE).

---

<div align="center">

### Give your agents a control structure.

`start cheap` · `run under control` · `get smarter every run`

<sub>`Co-Sight Harness` · Built with control, not luck.</sub>

</div>
