# Knowledge Studio E2E

Playwright 门禁轨 + chrome-devtools MCP 辅助轨。

## 快速开始（本机）

前置：Node 22.22+、Docker、**Docker Compose ≥ 2.24**（覆盖文件用了 `!override`）。

```bash
cd e2e
npm ci
npx playwright install --with-deps chromium   # 或使用系统 Chrome：E2E_BROWSER_CHANNEL=chrome

# 起一次性栈（需要本地已有 ragstudio/web 与 ragstudio/rag-knowledge-base 镜像）
E2E_RUN_ID=local-1 bash scripts/stack-up.sh

# 快速门禁（11 条 test，2 worker，约 25s）
E2E_BROWSER_CHANNEL=chrome npm run test:fast

# 冒烟 / P0 / 全量（148 条 / 20 个 spec，默认 1 worker，约 10 min）
npx playwright test --grep @smoke
npx playwright test --grep @p0
npm run test:full

# 韧性演练 / 截图基线 / gateway 鉴权（按需）
E2E_INFRA=1 npx playwright test tests/resilience/infra.spec.ts --workers=1
E2E_VISUAL=1 npx playwright test tests/ui/ui.spec.ts --grep UI-04
E2E_AUTH=1 E2E_AUTH_TOKEN=... npx playwright test --grep SEC-05

# 查看报告
npx playwright show-report

# 停栈并删卷
bash scripts/stack-down.sh
```

## 目录

```text
support/api/        API 造数/清理（纯 JSON + problem 错误解析）
support/pages/      Page Object（只放定位器与页面动作）
support/fixtures/   test fixture、console error 收集、共享造数
support/model-mock/ 确定性模型替身（无第三方依赖）
tests/              按域分目录；用例标题带 @smoke/@fast/@p0 标签
mcp/                MCP 辅助验收清单与证据目录
scripts/            起栈/停栈
```

## 环境契约

| 变量 | 默认 | 说明 |
|---|---|---|
| `E2E_BASE_URL` | `http://127.0.0.1:18080` | compose e2e 覆盖文件的 web 端口 |
| `E2E_MOCK_BASE_URL` | `http://127.0.0.1:18081` | fake gateway 的宿主调试端口 |
| `E2E_MODEL_MODE` | `mock` | `mock` / `live`；live 只跑 `@live` |
| `E2E_BROWSER_CHANNEL` | 空 | 本地填 `chrome` 用系统 Chrome；CI 留空 |
| `E2E_RUN_ID` | 自动生成 | 资源名前缀与 compose project |
| `E2E_WORKERS` | `1` | 并行度；快速门禁脚本显式传 2 |
| `E2E_ALL_BROWSERS` | `0` | `1` 时追加 Firefox/WebKit project（夜间用） |
| `E2E_KEEP` | `0` | `1` 时停栈脚本保留现场 |
| `E2E_INFRA` | `0` | `1` 时运行 RES-01~02（stop/restart 容器） |
| `E2E_VISUAL` | `0` | `1` 时运行 UI-04 截图基线 |
| `E2E_AUTH` | `0` | `1` 时运行 SEC-05（栈需 `AUTH_MODE=gateway`） |
| `E2E_AUTH_TOKEN` | 空 | SEC-05 使用的 `X-Auth-Value` |
| `E2E_AUTH_MODE` | `none` | 跑 `tests/auth/` 时设为 `local`；栈本身也要 `AUTH_MODE=local` |
| `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD` | `e2e-admin` / 内置测试口令 | `local` 栈首次启动播种的 admin（与 `RKB_ADMIN_*` 对应） |
| `E2E_RKB_CONTAINER` / `E2E_OPENSEARCH_CONTAINER` | e2e compose 默认名 | 韧性用例的容器名覆盖 |

## 快速门禁的 11 个用例 ID

`SMK-01~07`、`IMP-01`、`FLOW-07`、`CHAT-02`、`MODEL-01`。

`@fast` 为 **11 条 test**（5 个 spec），2 worker 约 25s。全量 **148 条 test / 20 个 spec**，
覆盖 12 个域；默认 1 worker（fake 模型的 config/requests 是进程级全局状态），
本地约 10 min。

### 用例清单

| 目录 | 域 | 用例 |
|---|---|---|
| `tests/smoke/` | 平台导航 | SMK-01~10 |
| `tests/kb/` | 文档知识库 | KB-01~14（KB-03/04 随旧整页建库页退役） |
| `tests/import/` | 导入/切片/索引 | IMP-01~18（IMP-05/08/10/13/17 随旧文件列表退役；IMP-02b 为 `fixme`） |
| `tests/operator/` | 自定义算子 | OP-01~10 |
| `tests/flow/` | 知识检索 | FLOW-01~20 |
| `tests/chat/` | 对话 | CHAT-01~13（CHAT-13 为 `fixme`） |
| `tests/graph/` | 知识图谱 | GRAPH-01~12 |
| `tests/model/` | 模型管理 | MODEL-01~10 |
| `tests/ui/` | i18n/响应式/a11y | UI-01~10（UI-04 需 `E2E_VISUAL=1`） |
| `tests/resilience/` | 韧性 | RES-01~10（RES-01~02 需 `E2E_INFRA=1`） |
| `tests/security/` | 安全 | SEC-01~07（SEC-05 需 `E2E_AUTH=1`） |
| `tests/auth/` | 本地账号 | 登录/错误口令/深链回跳/刷新保持/退出（需 `AUTH_MODE=local E2E_AUTH_MODE=local`） |

### 预期失败与已知缺口

当前没有 `test.fail`。

仍是 `fixme`/条件跳过的：`IMP-02b`（PDF 样本解析为空）、`KB-12-UI`（原型列表已无表头
排序按钮）、`CHAT-13`（无独立环境移除生成模型），以及需按需环境变量的
`UI-04`、`SEC-05`、`RES-01~02`。完整缺陷清单与取舍见各 spec 头部注释。

## 已落地的基础设施

- `playwright.config.ts` + fixture（`api` / `consoleErrors` / `runId`）
- `deploy/docker-compose.e2e.yml`：web@18080、fake gateway@18081、基础设施仅在 compose 网络内
- `deploy/init/pg/00-schema.sql`：**核心表 schema 快照**（22 张业务表 + `kb_index`）。
  默认 compose 已挂到 `/docker-entrypoint-initdb.d/`，E2E 与生产用同一份；
  动态 `data_*` 表仍由应用按需创建。
- `support/model-mock/`：确定性 embedding（词法哈希）、编排所需的 rewrite/rerank/select
  响应、graph_extract 响应、SSE 流、故障注入（one-shot `failNext` / 持续 `failChat`）
- `scripts/stack-up.sh` / `stack-down.sh`
- `mcp/acceptance-checklist.md`：辅助轨清单与证据目录
- 按需门禁：`E2E_INFRA`（容器故障演练）、`E2E_VISUAL`（截图）、`E2E_AUTH`（鉴权模式）

## 与已有验收脚本的关系

- `tools/verify/*.py` 保留为接口层验收，不在本目录重写。
- 验收分层、错误分支判据、边界夹具与回归闭环见
  [`docs/acceptance-handbook.md`](../docs/acceptance-handbook.md)（**跟进外部测试报告前先读**）。

## 已知坑

1. **浏览器缓存旧 chunk**：本地长期开着的 Chrome 可能缓存了旧 `index.html` 与旧
   `module.*.js`，表现为 `ChunkLoadError`。Playwright 每次新 context 不会遇到；
   手工用 chrome-devtools MCP 时先 `reload` 并勾选 ignore cache。
2. **单副本后端**：RKB 按单副本部署；CI worker 固定 2，破坏性用例串行。
3. **自动刷新**：列表页会轮询，不要等 `networkidle`；等具体元素或 API 状态。
4. **导入等待**：用 `api.waitForFile()` 轮询状态（0=进行中/1=成功/2=失败），不要固定 sleep。
5. **mock 替身不可达**：确认 compose 覆盖文件的 `fake-model-gateway` 已启动，且 RKB 的
   `NO_PROXY` 包含它；否则 `/query` 会卡住或返回空。
6. **本地已有栈**：若不想起第二套栈，可 `E2E_BASE_URL=http://127.0.0.1` 指向现有栈；
   此时 `E2E_MODEL_MODE` 应设为 `live`，且 RET/CHAT 用例依赖真实 embedding/LLM。
7. **mock 配置是全局状态**：`/__mock__/config`、`/__mock__/requests` 被所有测试共享。
   全量必须 `--workers=1`（`npm run test:full`）；只有 `@fast` 显式开 2 worker。
8. **图谱导入不更新库状态**：`/graph/import` 完成后 `kb_kbase.status` 仍是 0；
   断言数据要用 `api.graph.waitForGraphData()`，不要等 status。
9. **发布校验会探测生成端点**：`flow/publish` 拿画布里的 `llm` 名去 `/models` 清单核对，
   结果缓存 60s。新增自定义模型名要同步进 fake 的 `E2E_MOCK_MODELS`（compose 已含
   `e2e-path-llm`）或 `extraModels`，否则发布报 `model.unavailable`。

## MCP 辅助轨

见 [`mcp/acceptance-checklist.md`](mcp/acceptance-checklist.md)。它不阻断合并，产出证据与
问题链接；稳定步骤再固化成 Playwright 用例。
