# Smart Factory 文档索引

本目录是 smart-factory 的全部设计文档。**本文件是唯一入口**：新增文档必须在此登记。

## 1. 目录约定

按文档在生命周期中的位置编号归档：

| 目录 | 放什么 | 状态 |
|---|---|---|
| `03-architecture/` | 架构、工程约定与详细设计 | 已启用 |
| `04-api/` | 接口契约（REST / WebSocket / 错误码） | 已启用 |
| `05-openapi/` | OpenAPI 契约（当前覆盖 agents、产物状态与 files 域；未覆盖的端点仍看 `04-api/`） | 已启用 |
| `99-adr/` | 架构决策记录（ADR），一决策一文件 | 已启用 |

其余生命周期目录（概览、需求、测试、部署、指南）**有内容时再建，不建空壳**。

## 2. 命名规则

```
<两位序号>-<功能名>.md      # 正文文档；序号决定目录内的阅读顺序
NNNN-<decision-slug>.md    # ADR；四位序号，如 0001-no-ddd-four-layers.md
```

- `03-architecture/` 与 `99-adr/` 的功能名用**英文小写连字符**（`01-architecture.md`、`0001-no-ddd-four-layers.md`）；`04-api/` 用 `<章>.<节>-<中文功能名>.md`（`4.01-接口总览.md`）；`05-openapi/` 用 `<章>.<节>-<英文小写连字符>.yaml`（`5.01-agent-openapi.yaml`）。
- 文件名体现**功能**，不带版本与日期；文档内也**不写修订记录** - 过程记录归 `WORKLOG.md`。
- 插入文档导致顺序变化时直接重排序号，不预留空位。

## 3. 文档状态标记

每篇正文文档首部必须有一行状态，取值四种：

| 标记 | 含义 |
|---|---|
| 草案 | 作者自用，未提评审 |
| 待评审 | 已提交评审，等待结论 |
| 已定稿 | 评审通过，实现以此为准 |
| 已废弃 | 被新文档取代（首部写明取代者路径） |

ADR 用「已提议 / 已接受 / 已取代」。

## 4. 索引

| 文档 | 状态 | 说明 |
|---|---|---|
| [架构](03-architecture/01-architecture.md) | 已定稿 | 定位与边界、分层与目录、接口风格、配置、运行环境、脚本 |
| [数据模型](03-architecture/02-data-model.md) | 已定稿 | 五张表、schema、状态机、seq 分配、级联与不变量 |
| [会话与运行](03-architecture/03-session-run.md) | 已定稿 | 目录与四阶段、生命周期编排、启动关闭与重启收口 |
| [引擎接缝](03-architecture/04-engine.md) | 已定稿 | 端口、注册表、适配器要点：换 SDK 只动这层 |
| [实时通道](03-architecture/05-realtime.md) | 已定稿 | 信封、订阅扇出、无回放边界、心跳与背压 |
| [审批与交互](03-architecture/06-approval.md) | 已定稿 | 审批即消息、结算协议、会话级 approved_all、语义后果 |
| [产物浏览](03-architecture/07-artifact.md) | 已定稿 | 四 stage 目录只读 list / file / download、路径安全、大小上限 |
| [智能体](03-architecture/08-agent.md) | 待评审 | 元数据行与产物目录、status、先盘后库、启动收养、标签 |
| [通用文件](03-architecture/09-file.md) | 草案 | 上传与读取的机制、安全边界、与 artifacts 的分工 |
| [技能库与目录会话](03-architecture/10-skill-library.md) | 待评审 | 目录实例（无 agentId、cwd 落库、stage 按用途取值）、`GET /skills` 两路扫描 |
| [接口总览](04-api/4.01-接口总览.md) | 已定稿 | 基址、文档地图、REST 与 WS 端点总表、刻意不存在的接口、改动前的验收 |
| [通用规范](04-api/4.02-通用规范.md) | 已定稿 | 前缀、HTTP 方法、动作词、id 传法、分页与游标、参数校验口径、错误码、鉴权 |
| [会话](04-api/4.03-会话.md) | 已定稿 | `sessions/*` 六个端点、`Session` 与 `Instance` 字段表、按 `agentId` 首帧新建会话、模型 / 模式 / 强度切换与 resume |
| [消息](04-api/4.04-消息.md) | 已定稿 | `messages/*` 三个端点、`Message` 全字段表、`content` 按 type 的形状 |
| [运行](04-api/4.05-运行.md) | 已定稿 | `runs/*` 三个端点、状态机、派生字段 `waiting` 与活跃顶层 run 的并发不变量 |
| [实时通道](04-api/4.06-实时通道.md) | 已定稿 | WS 信封、上行方法（原生 + 兼容）、下行事件（原生 + 兼容）、订阅与补发、心跳与背压、断线恢复 |
| [待前端对齐](04-api/4.07-待前端对齐.md) | 已定稿 | 跨端待对齐：后端现状（含已实现项）与前端待改清单 |
| [任务中心查询交接](04-api/4.08-任务中心查询交接.md) | 已定稿 | 智能体 / 会话查询与 agent-runtime 的差异、字段映射与任务中心改造清单 |
| [评估报告](04-api/4.09-评估报告.md) | 已定稿 | `evaluations/*` 四个查询端点、报告与用例 DTO、筛选与分页口径 |
| [智能体产物状态](04-api/4.10-智能体产物状态.md) | 已定稿 | `GET /agents/{agentId}/production`：完成判定、状态推导、预览 / 评估门禁 |
| [Web 交接](04-api/4.11-web交接.md) | 已定稿 | 近期协议与字段变更对 smart-factory web 的影响、必改项与验收清单 |
| [cosight-viewer WS 能力对比](cosight-viewer-ws-能力对比.md) | 已定稿 | 商用客户端契约与 smart-factory 的完整能力矩阵 |
| [cosight-viewer 对接清单](cosight-viewer-对接清单.md) | 已定稿 | 面向客户端的动作清单：连接、send、history、switch、事件、数据源 |
| [功能接口文档](04-api/4.09-功能接口文档.md) | 草案 | 单份整合视图：全部功能域的端点、DTO、错误码与 WS 通道行为一篇读全；冲突以 4.02~4.06 与 OpenAPI 为准 |
| [公共形状（OpenAPI）](05-openapi/5.00-common-openapi.yaml) | 草案 | 错误体、分页、时间戳等跨资源共用 schema，不含端点 |
| [智能体契约（OpenAPI）](05-openapi/5.01-agent-openapi.yaml) | 草案 | agents 六个端点，含 `workspaceId` 与标签清单；未覆盖的端点仍以 `04-api/` 为准 |
| [文件契约（OpenAPI）](05-openapi/5.02-file-openapi.yaml) | 草案 | `POST /files` 上传、`GET /files/{fileId}` 读取 |
| [产物状态契约（OpenAPI）](05-openapi/5.03-agent-production-openapi.yaml) | 草案 | `GET /agents/{agentId}/production`：完成状态与 `ready` |
| [ADR-0001 不采用 DDD 四层分层](99-adr/0001-no-ddd-four-layers.md) | 已接受 | 分层决策与重新评估的触发条件 |
| [ADR-0002 智能体管理收进本仓后端](99-adr/0002-agents-table-in-server.md) | 已提议 | 新增 agents 表与 `/agents/*` 端点；取代 `01-architecture.md` 减法清单里的「智能体管理不做」 |

## 5. 写作约束

- **同一事实只出现在一处**：数据模型进 `03-architecture/02-data-model.md`，机制进对应设计篇，接口形状进 `04-api/`，工程约定进 `01-architecture.md`；其余文档只引用，不复制。
- **每篇标注代码落点与验收**：正文首部除状态行外，标注「代码落点」（对应 `server/src` 路径）与「验收测试」（对应 `server/tests` 文件），与代码模块一一对应。
- **不留过程痕迹**：不写修订记录、决策过程、调研过程、批次与方案编号；这些属于 `WORKLOG.md` 与 ADR。
- **改动顺序**：先改对应文档再写代码（数据模型 → `02-data-model.md`；接口 → `04-api/`），完成后 review 一致。
- 跨文档引用一律写**相对本文件的相对路径**（如 `./02-data-model.md`、`../04-api/4.02-通用规范.md`），不写裸文件名。

## 6. 变更验收

改完代码合入前逐项过：

- `cd server && npm run typecheck`：0 报错。
- `npm test`：全绿；改哪篇先跑该篇「验收测试」映射的文件，合入前跑全量。
- 端到端（在 `smart-factory/` 下执行）：`node scripts/dev.mjs e2e`（fake）；引擎相关改动加跑一次真实引擎（`ENGINE=claude-cli SF_PROMPT="用 Write 工具创建文件…" node scripts/dev.mjs e2e`），且挂起期间 `runs/abort` 能立刻打断。
- 启动冒烟（在 `smart-factory/` 下执行）：`node scripts/dev.mjs setup` → `node scripts/dev.mjs start`。
