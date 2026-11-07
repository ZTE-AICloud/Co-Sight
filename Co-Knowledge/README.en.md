<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="frontend/public/brand/zte-logo-white.svg">
    <img src="frontend/public/brand/zte-logo.svg" width="160" height="95" alt="ZTE">
  </picture>
  <h1>Knowledge Studio</h1>
  <p><b>Open-source Knowledge Engineering Platform</b><br>Turn private knowledge into AI assets that are searchable, orchestrated and traceable.</p>
</div>

<p align="center">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

<p align="center">
  <code>Apache-2.0</code> · <code>4 containers by default</code> · <code>single API prefix</code> · <code>pluggable model endpoints</code> · <code>Chinese / English UI</code>
</p>

> Knowledge Studio is the product / interface name; the component name is Co-Knowledge. The repository is named Co-Knowledge, while Docker images and package names retain the `ragstudio` prefix.

Knowledge Studio is a self-hostable **knowledge engineering platform**. Documents go in, get parsed and chunked, and are indexed both as vectors and as full text—ready to retrieve. An LLM extracts relational knowledge into entities and relations—either against a schema or in a general schema-free mode—and stores it in a knowledge graph, which can be combined with document retrieval into **GraphRAG** pipelines. Retrieval flows are composed visually on a canvas and executed as a DAG once published. Answers stream over SSE and cite the exact knowledge-base fragments they were built from.

One Compose command brings up the whole stack: **one frontend + one backend + two stores**, with **a single API prefix** exposed to the outside. Embedding, generation and reranking all point at your own OpenAI-compatible endpoints, so data, models and compute stay inside your environment.

---

## What it solves

| Real enterprise problem | What Knowledge Studio does |
|---|---|
| **Answers cannot be traced** — models confidently make things up | Every answer lists the fragments actually supplied to the model, their source files, scores and the rewritten retrieval query. Agent answers carry `[S1]`-style citations that can be checked one by one. |
| **Relational questions defeat keyword and vector search** | Graph knowledge bases: define a schema or use the schema-free general mode → LLM-extract entities and relations → query and retrieve over the graph. Graph retrieval can run side by side with document retrieval in the same pipeline. |
| **Building it yourself is expensive** — parsing, chunking, vectors, full text, graph store, orchestration and model access are all required | One Compose stack with 4 containers; only two general-purpose stores (PostgreSQL and OpenSearch). |

---

## Core capabilities

| Capability | What it gives you |
|---|---|
| **Knowledge base management** | Document and graph knowledge bases; directory tree, bulk import, document status and statistics, chunk inspection and manual chunk creation; a dedicated vector table and full-text index per knowledge base |
| **Document parsing and chunking** | md / docx / xlsx / pdf / pptx / html / txt / csv; 512-character chunks with 128-character overlap by default; every chunk is written to both the vector and the full-text index |
| **Custom operators** | Upload a zip → register → select it during import. Supports `file_parse` / `text_split` / `graph_extract` entry points (ABI v2), with template download, publish/visibility and export. Executed in an isolated subprocess (500MB memory, 10MB result, best-effort network isolation) after an AST safety check; operator import is administrator-only and operators are treated as trusted code |
| **Dual retrieval** | Vector search (`type=0`) and keyword search (`type=1`, OpenSearch + analysis-ik); multi-knowledge-base grouping with priority—the first high-priority hit wins |
| **Knowledge graph** | Schema (ontology) definition and template designer, LLM extraction, PostgreSQL JSONB storage (`graph_<kbId>_vertex/_edge`), entity/edge editing, graph query / export / visualization and graph vector retrieval; ships two built-in operators — **general** (`-6` v1.2.0, schema-free, supports `extractionProfile` with `general` / `general_attributes`) and **specialized** (`-5` v1.0.0, schema-driven) |
| **Retrieval orchestration** | @antv/x6 canvas; built-in sequential, blended and conditional templates (including graph variants); drafts are separate from published snapshots, and the runtime only reads published ones; graph retrieval nodes expose `depth` / `top_k` / `include_edge_facts` |
| **Chat playground** | SSE streaming, multi-turn sessions, knowledge-base evidence and per-stage timings; query metrics can be persisted to `chat_query_trace` with list and P50/P95/P99 statistics |
| **Model management** | Register, test connectivity and enable/disable LLMs, embedding models and rerankers; changes take effect immediately; thinking configuration ships with 17 presets plus custom JSON |
| **Agent access** | 6 Agent REST endpoints and 5 MCP tools; API-key scopes, knowledge-base allowlists, per-key rate limiting and usage statistics |
| **Accounts and auth** | `local` accounts (scrypt + HttpOnly session) / `gateway` token trust / `none` (auth disabled) |

### Design decisions worth knowing

- **Two indexes, one source of truth**: every chunk lands in both pgvector and OpenSearch; consistency can be checked with "vector count == chunk count == full-text document count".
- **Draft / publish separation**: canvas edits only take effect after **Publish**; the runtime executes only published snapshots.
- **Retrieval is observable**: hits, source files, relevance scores, rewritten queries and stage timings are all returned in the same request.
- **Extension points stay outside the core**: a custom format or chunking strategy becomes an operator package; a model swap happens on the model management page; a retrieval change happens on the canvas.

---

## Architecture

```text
        Browser / business systems / Agents (REST · MCP)
                             │  HTTP · SSE
                     ┌───────▼────────┐
                     │  web (nginx)   │  sole public entry :80
                     └───────┬────────┘
                             │  /api/co-knowledge/v1
        ┌────────────────────▼───────────────────┐
        │  rag-knowledge-base                    │  sole backend (FastAPI :8091)
        │  knowledge base · graph · operators    │
        │  retrieval · engine · chat · models    │
        │  agent · auth                          │
        └──────────┬─────────────────────┬───────┘
                   │                     │
     ┌─────────────▼────────┐  ┌─────────▼──────────────┐
     │  PostgreSQL 16       │  │  OpenSearch 2.19.6     │
     │  + pgvector 0.8.7    │  │  + analysis-ik         │
     │  vectors / metadata  │  │  full-text / keyword   │
     │  graph JSONB         │  └────────────────────────┘
     └──────────────────────┘
     Outside the stack: OpenAI-compatible endpoints (embedding / chat / rerank)
```

The left store holds vectors, business metadata and the graph; the right store holds the full-text and keyword index.

**4 containers by default:**

| Container | Role | Host port |
|---|---|---|
| `web` | nginx static assets + reverse proxy (sole public entry) | **80** |
| `rag-knowledge-base` | Sole backend: knowledge base / graph / operators / retrieval / orchestration / chat / models / agent | container network only |
| `postgresql` | Business tables, vector tables (pgvector 0.8.7) and graph tables (JSONB) | `127.0.0.1:5432` |
| `opensearch` | Full-text and keyword index (OpenSearch 2.19.6 + analysis-ik) | `127.0.0.1:9200` |

Two optional profiles are available on demand:

- `local-embedding`: a local Infinity 0.0.77 container providing 768-dimensional embeddings (`bge-base-zh-v1.5`);
- `minio`: stores persistent files in MinIO (RELEASE.2024-10-13) object storage instead of the local named volume.

### Component stack

| Layer | Components and versions |
|---|---|
| Frontend runtime | Vue 3.5.26 · Element Plus 2.14.7 · Vue Router 4.6.4 · Vuex 4.1.0 |
| Canvas and visualization | @antv/x6 2.19.2 · vis-network 9.1.13 |
| Frontend build / test | Node 22.23.3 · @vue/cli-service 5.0.9 · Vitest 5.0.4 |
| Backend runtime | Python 3.11.18 · FastAPI 0.111.0 · Uvicorn 0.27.0 · Pydantic 2.9.2 · psycopg2-binary 2.9.9 · MCP SDK 1.12.4 |
| Document parsing | pdfplumber 0.11.7 · pypdfium2 5.14.0 · python-docx 1.1.2 · python-pptx 1.0.2 · openpyxl 3.1.5 |
| Storage | PostgreSQL 16 + pgvector 0.8.7 · OpenSearch 2.19.6 + analysis-ik |
| Entry and deployment | nginx 1.27.5 · Docker Compose v2 |

> Versions follow [`backend/requirements.txt`](backend/requirements.txt), [`frontend/package.json`](frontend/package.json) and [`deploy/docker-compose.yml`](deploy/docker-compose.yml); this table lists only components that directly affect deployment and integration.

### Backend modules

```text
backend/src/
├── knowledge_base/  knowledge bases, directories, documents, chunks, task queue
├── ingestion/       parse / chunk / graph-extraction pipelines
├── parsing/         pure format-parsing library
├── operators/       operator registry, templates, sandbox, system operators
├── operator_api/    public import surface of operator ABI v2
├── graph/           schema, extraction, import, query, export, graph retrieval
├── retrieval/       vector and keyword reads, node mapping
├── workflow/        canvas, validation, publishing, templates
├── engine/          RAG runtime (rewrite → retrieve → rerank → compose)
├── chat/            /query, SSE, multi-turn sessions, evidence, query traces
├── model/           model registry, gateway client, thinking configuration
├── agent/           REST / MCP / API keys
├── auth/            local accounts, sessions and CLI
├── infrastructure/  config, database, HTTP, logging, storage, search
├── shared/          prefixes, problems, errors, chunk model, i18n
└── system/          health checks and system information
```

The frontend is layered as `app / pages / features / shared`, with feature directories named after backend domains. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full structure and dependency rules.

---

## Quick start

### Prerequisites

- Docker ≥ 24 + `docker compose` v2 (local image builds require buildx ≥ 0.17; on older versions, build with `docker build` and start with `up -d --no-build`)
- ≥ 20GB disk, ≥ 6GiB RAM recommended
- A reachable **OpenAI-compatible embedding endpoint**; generation endpoint also required for Q&A (reranking optional)
- Port 80 free; OpenSearch requires a host kernel parameter:

```bash
sudo sysctl -w vm.max_map_count=262144
# persist: echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf
```

### Four steps

**1. Configure**

```bash
cp deploy/.env.example deploy/.env
# At minimum, change the database passwords:
#   POSTGRES_PASSWORD / RKB_DB_PASSWORD
# Model endpoints can also be registered in Model Management after startup;
# values here act as the first seed:
#   MODEL_GATEWAY_URL / MODEL_GATEWAY_API_KEY / EMBEDDING_MODEL / EMBEDDING_DIMENSION
# To use Agent REST / MCP, also set:
#   RKB_AGENT_KEY_PEPPER (openssl rand -hex 32)
```

`.env` must live in `deploy/` (next to the compose file) for Compose to pick it up.

> **Air-gapped / internal mirrors**: builds use the official PyPI and npm registry by
> default. Set `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` / `NPM_REGISTRY` to your mirror
> (empty = official sources); they are passed to the backend and frontend images as
> build args. The OpenSearch IK plugin is **installed offline**: the package
> ships with the repository (`deploy/opensearch/analysis-ik.zip`, from the
> [analysis-ik releases](https://github.com/medcl/elasticsearch-analysis-ik/releases),
> version matching `OPENSEARCH_VERSION`). For fully offline hosts, build the images
> elsewhere and start with `--no-build` as described under "Deployment notes".

**2. Start the stack**

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps    # all 4 containers should be healthy
```

**3. Check health**

```bash
curl -fs http://localhost/api/co-knowledge/v1/health   # → ok
```

**4. Sign in and register models**

Open `http://localhost`. The default is `AUTH_MODE=local`; on first start an `admin` account is created and a random password is written inside the container:

```bash
docker compose -f deploy/docker-compose.yml exec rag-knowledge-base \
  cat /data/rkb/initial-admin-password
```

The first sign-in forces a password change. Then go to **Model Management** and register your embedding / generation / reranking endpoints—**saved changes take effect immediately**. The model registry is the authoritative list; `deploy/.env` only seeds it on first boot and serves as a fallback.

From there: **create a knowledge base → import documents → retrieve / orchestrate / extract a graph**.

> Offline environments: once the images are available, add `--no-build`. For development, overlay `deploy/docker-compose.dev.yml` (source mounts + hot reload, reusing existing services).

---

## Using it

### UI

| Entry | Route | Purpose |
|---|---|---|
| Knowledge bases → Document KBs | `/#/knowledge`; detail `/#/knowledge/detail/:id`; documents `/#/knowledge/detail/:id/documents` | List, dataset/basic info, directory and document management |
| Knowledge bases → Graph KBs | `/#/graph`; detail `/#/graph/detail/:id`, edit `/#/graph/edit/:id`, create `/#/graph/create`, template `/#/graph/createTemplate/:templateId` | List, detail, edit, creation and template designer |
| Retrieval orchestration | `/#/flow`; canvas `/#/flow/detail/:id` | Workflow list, canvas editing, save and publish |
| Chat playground | `/#/chat` | Streaming Q&A, multi-turn sessions, evidence and stage timings |
| Custom operators | `/#/operators` | Upload, template download, publish/visibility and export |
| Model management | `/#/models` | LLM / embedding / reranker registry, connection tests and thinking configuration |
| Remote access → Access methods | `/#/access` | Agent REST + MCP integration guide |
| Remote access → API keys | `/#/keys` | Agent API keys, scopes, allowlists and rate limits |
| Login / password change | `/#/login`, `/#/change-password` | Local account sign-in and forced password change |

> The frontend uses **hash routing**: page URLs look like `/#/knowledge`. `/` redirects to `/#/login`, and unknown paths fall back to `/#/knowledge`.

### HTTP API + SSE

- **One prefix only**: `/api/co-knowledge/v1`.
- Main REST contract **OpenAPI 2.3.0**: **65 paths / 93 operations** (including `/health`), at [`contracts/openapi/rkb-api.yaml`](contracts/openapi/rkb-api.yaml).
- Agent REST contract **OpenAPI 1.4.0**: **6 paths / 6 operations**, at [`contracts/openapi/agent-api.yaml`](contracts/openapi/agent-api.yaml).
- Success responses return the resource itself; pagination is `{items,total,page,pageSize}`; errors use RFC 9457 `application/problem+json`.
- Q&A via `POST /query` uses standard named SSE events with buffering disabled for that nginx location.

```bash
BASE=http://localhost/api/co-knowledge/v1
curl -fs $BASE/health
```

See [`docs/api-reference.md`](docs/api-reference.md) for the full reference and [`docs/external-api/`](docs/external-api/) for the integrator-facing package.

### Agent REST + MCP

A knowledge access, retrieval Q&A and published-workflow execution surface for agent platforms and IDEs:

| Type | Endpoints / tools |
|---|---|
| REST | `GET /agent/knowledge-bases`, `GET /agent/knowledge-bases/{id}`, `POST /agent/search`, `POST /agent/answer`, `GET /agent/workflows`, `POST /agent/query` (run a published workflow) |
| MCP | `list_knowledge_bases`, `search_knowledge`, `ask_knowledge_base`, `list_workflows`, `run_workflow` (run a published workflow) |

```bash
curl -s http://localhost/api/co-knowledge/v1/agent/search \
  -H "Authorization: Bearer <API_KEY>" \
  -H 'Content-Type: application/json' \
  -d '{"query":"inspection interval","mode":"hybrid","top_k":5}'
```

API keys are created under **API Keys**; each key can be restricted by scope (`kb:list` / `kb:search` / `kb:answer` / `workflow:read` / `workflow:run`), knowledge-base allowlist, per-key rate limit and usage statistics. Workflow execution uses `POST /agent/query` and requires `workflow:run`. The MCP endpoint is `/api/co-knowledge/v1/mcp`. See [`docs/agent-integration.md`](docs/agent-integration.md).

---

## Quality and baselines

| Item | Current value (measured 2026-11-04) |
|---|---|
| Backend tests | **2,417 passed** / 7 deselected (~58s) |
| Frontend tests | **936 passed** / 91 files (~35s) |
| API contract | OpenAPI **2.3.0**: 65 paths / 93 operations (including `/health`), locked by a snapshot test |
| E2E | Playwright: 11 fast-gate tests in ~25s; full suite 148 tests / 20 specs (~10 min) |
| Architecture check | `python3 tools/check-architecture.py --strict`: **0 violations** |
| Retrieval baseline (2,000 queries, 2026-10-29) | Vector NDCG@10 **81.57%**, Recall@80 **95.02%**; keyword NDCG@10 59.96% |
| Reranking gain (2026-10-20 ablation) | `Qwen3-Reranker-4B`, top-50 → top-10: NDCG@10 **81.57% → 88.10% (+6.53 pp)** |
| Public benchmarks (2026-11-01) | SciFact vector NDCG@10 **68.45%** (model public value 69.72%); CRUD-RAG keyword **83.83%** / vector 72.51%; RGB noise 3 levels 88.67 / 86.67 / 85.67% |
| Graph end-to-end (2WikiMultiHopQA, 100 questions, 2026-11-02) | Attribute extraction + edge facts + normalization prompt: EM **82.0%**, normalized EM **90.0%** (same-day v1: 75.0% / 81.0%) |

> Retrieval and benchmark numbers are single full or sampled runs on public datasets and will move with corpus, model and hardware. Methodology and reproduction for the public benchmarks: [`docs/rag-benchmark-20261101.md`](docs/rag-benchmark-20261101.md).

---

## Configuration

Key environment variables (full list in [`deploy/.env.example`](deploy/.env.example); per-variable reference in [`docs/TECHNICAL-GUIDE.md`](docs/TECHNICAL-GUIDE.md) §6):

| Variable | Description |
|---|---|
| `POSTGRES_PASSWORD` / `RKB_DB_PASSWORD` | Database passwords; change before first start |
| `MODEL_GATEWAY_URL` / `MODEL_GATEWAY_EMBEDDINGS_PATH` | Embedding endpoint and path (remote `/v1/embeddings`, local Infinity `/embeddings`) |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | Model name and dimension; 1024 / 768 dimensions can coexist per knowledge base, and each query uses the model bound to its knowledge base |
| `GENERATION_GATEWAY_URL` / `GENERATION_MODEL` / `GENERATION_API_KEY` | Generation endpoint |
| `GENERATION_MAX_TOKENS` | Default 16384; keep it below the 32768 context window |
| `RERANK_URL` / `RERANK_MODEL` | Optional cross-encoder rerank endpoint/model; a rerank model in the registry takes precedence |
| `AUTH_MODE` | `local` (default) / `gateway` / `none` |
| `RKB_ADMIN_USERNAME` / `RKB_ADMIN_PASSWORD_FILE` | Bootstrap administrator and initial password file |
| `RKB_AGENT_KEY_PEPPER` | Set this to use Agent REST / MCP (`openssl rand -hex 32`) |
| `RKB_SECRET_KEY` / `RKB_SECRET_KEY_FILE` | Static encryption key for model-registry credentials (`model_registry.api_key`); keep it safe |
| `RKB_STORAGE_BACKEND` | `local` (default) / `minio` |
| `NO_PROXY` / `no_proxy` | Must include every model endpoint host when the host uses a proxy |

### Authentication modes

| `AUTH_MODE` | Behavior |
|---|---|
| `local` | Local accounts + scrypt passwords + HttpOnly session cookie; unauthenticated UI/API requests return `401` |
| `gateway` | Trusts an upstream gateway; only checks for `X-Auth-Value` / `X-Auth-Token` / `Authorization` |
| `none` | Auth disabled; requests without an identity are attributed to `AUTH_DEFAULT_USER` |

An unknown value fails startup, so misconfiguration is caught early. Account management uses the in-container CLI: `python3 -m auth.cli create|list|reset-password|enable|disable|delete`. See [`docs/auth-login.md`](docs/auth-login.md).

---

## Deployment notes

- **Single replica**: query rewriting keeps multi-turn context in an in-process cache, so deploy `rag-knowledge-base` as a single replica.
- **Old kernels (< 5.3)**: the compose file sets `security_opt: [seccomp:unconfined]` for `clone3` compatibility; remove it on modern kernels.
- **HTTP proxy**: containers inherit the host `http_proxy`. Model endpoint hosts must be in `NO_PROXY`, otherwise requests go through the proxy and look like embedding-service failures.
- **Offline deployment**: with the 3 locally built images ready (`ragstudio/rag-knowledge-base`, `ragstudio/web`, `ragstudio/opensearch`), run `docker compose ... up -d --no-build`.
- **Sub-path deployment**: set `WEB_BASE_URL=/co-knowledge/` (leading and trailing slash required) in `deploy/.env` and rebuild the web image (`up -d --build web`). The site is then served at `/co-knowledge/`, with `/` redirecting to it; the API prefix `/api/co-knowledge/v1` is unchanged.
- **Data**: one business database, `rag_studio`; knowledge-base files live in the `kb-storage` named volume by default, runtime data (keys, logs, temporary files) in `rkb-storage`. `down` keeps data, `down -v` deletes it.

---

## Repository layout

```text
.
├── backend/      Python 3.11 + FastAPI: the sole backend
├── frontend/     Vue 3.5 + Element Plus + @antv/x6: the sole frontend
├── contracts/    OpenAPI + JSON Schema: single source of API contracts
├── deploy/       Docker Compose, init scripts, OpenSearch image
├── docs/         Technical guides, architecture, database schema, benchmark reports, verification records
├── e2e/          Playwright end-to-end tests
└── tools/        Verification / benchmark scripts, architecture checks
```

---

## Documentation

| Document | Content |
|---|---|
| [`docs/TECHNICAL-GUIDE.md`](docs/TECHNICAL-GUIDE.md) | Complete technical guide: architecture and data flow, components, deployment, feature guide, configuration, API, troubleshooting and operations |
| [`docs/api-reference.md`](docs/api-reference.md) | API reference: conventions, resources, status codes, SSE |
| [`docs/agent-integration.md`](docs/agent-integration.md) | Agent integration: REST + MCP, API keys, scopes, Claude Code setup, troubleshooting |
| [`docs/external-api/`](docs/external-api/) | Integrator-facing API package (single-file HTML + Markdown + Agent OpenAPI) |
| [`docs/database-schema.md`](docs/database-schema.md) | Database schema: one database, two schemas, per-table definitions, dynamic vector/graph table templates |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code structure, dependency rules and change conventions |
| [`docs/operator-abi.md`](docs/operator-abi.md) | Custom operator ABI v2: package format, entry points, public modules |
| [`deploy/operators/general-graph-extract/README.md`](deploy/operators/general-graph-extract/README.md) | General graph extraction operator v1.2.0: `extractionProfile`, installation and upgrades |
| [`docs/rag-benchmark-20261101.md`](docs/rag-benchmark-20261101.md) | Evaluation report across 11 public benchmarks |
| [`docs/opensearch.md`](docs/opensearch.md) | Why OpenSearch (licensing and Chinese analysis) |
| [`e2e/README.md`](e2e/README.md) | E2E runbook |
| [`docs/acceptance-handbook.md`](docs/acceptance-handbook.md) | Acceptance handbook: test layers, error-branch criteria, edge fixtures, defect taxonomy and regression loop |

---

## Roadmap

Directional planning:

| Horizon | Direction |
|---|---|
| Near term | Full support for ontology constraints (extends / disjoint / constraints); transitive, symmetric and inverse relations; entity aliasing and normalization; agentic retrieval (vector/keyword seeds + graph traversal for context) |
| Mid term | Multi-hop subgraphs returned in BFS layer order and coupled to `depth` / `seed_k`; graph scale from millions to tens of millions; automatic ontology induction from documents; quality governance (staleness, conflicts, lineage) |
| Long term | Multi-domain knowledge federation and an open ontology ecosystem; an operator and connector marketplace; structured knowledge consumed directly by AI applications |

---

## Development and contributing

Frontend builds and unit tests require **Node ≥ 22.22**.

```bash
bash tools/run-tests.sh                 # frontend vitest + backend pytest
python3 tools/check-architecture.py --strict   # architecture dependency check
python3 tools/verify/generate-rkb-openapi.py --check   # contract snapshot check
```

- API contracts in [`contracts/`](contracts/) are the single source of truth—change the contract first.
- Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (structure and change conventions) before changing code.

---

## License

[Apache License 2.0](LICENSE). Free for commercial use and further development.

Third-party components and licenses are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
