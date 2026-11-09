# Smart Factory 产物浏览

> 状态：**已定稿**。本文定义产物管理模块：对四个 stage 根目录的文件浏览能力。
> 代码落点：`server/src/modules/artifact/*`、`server/src/shared/workspace/dir-resolver.ts`（`assertRelativePath`）。验收测试：`server/tests/artifact-api.test.ts`。
> 相关篇：目录与物化见 [`03-session-run.md`](./03-session-run.md) §1；工作区解析与智能体根目录见 [`08-agent.md`](./08-agent.md) §1；接口索引见 [`../04-api/4.01-接口总览.md`](../04-api/4.01-接口总览.md) §4.1。

## 1. 定位

产物 = 四个 stage 的 cwd 里的文件本身：`development/`（开发）、`preview/`（预览）、嵌套在 development 树内的 runtime 产物目录（运行）、`evaluation/`（评估）。**不进数据库** - 没有 artifacts 表、没有登记、没有元数据管理；目录就是真相，浏览接口只是它的只读视图。

浏览能力三件事：列目录、读文本文件、下载文件。不做写操作（上传 / 改名 / 删除都不做） - 目录的写方只有会话里的引擎。

## 2. 目录映射

先由 `agents` 表取 `workspaceId`，再经框架模块面 `GET /api/framework/v1/workspaces/{id}` 取 `directory`，得到：

```text
agentRoot = <workspace.directory>/.smart-factory/agents/{agentId}/
```

四个 stage 根都在 `agentRoot` 之下：

| stage | 根目录 | 说明 |
|---|---|---|
| `development` | `agentRoot/development/` | 开发目录：创建与开发会话的 cwd，runtime 产物也在这里产出 |
| `preview` | `agentRoot/preview/` | 预览目录：每次 run 前 ensure，源未变则跳过，变了才整体重拷 |
| `runtime` | `agentRoot/development/output/agents/{agentName}/{latest vN}/` | 运行目录：**原地使用，不拷贝**，根是嵌套产物目录 |
| `evaluation` | `agentRoot/evaluation/` | 评估沙箱根：同预览，源未变则跳过。被测副本在 `agent/`（评估会话 cwd），`e2e-test-*` 报告与它同级 |

`workspace.directory` 为 `null` 或框架不可达时不猜路径，接口明确报错（见 §4）。`agentRoot` 下另有 `.state/`（物化 mtime 标记），不属于任何 stage 根，浏览接口不可见。

## 3. 能力域

`modules/artifact/` 四件套，与其他域同构：`artifact.routes.ts` / `artifact.controller.ts` / `artifact.service.ts` / `index.ts`。服务层唯一业务是路径安全与形状组装，直接读文件系统，不经过 store。

三个端点（索引见 [`4.01 接口总览`](../04-api/4.01-接口总览.md) §4.1 端点总表，形状见下表）：

| 端点 | 作用 |
|---|---|
| `GET /artifacts/list` | 列目录：`stage` + `agentId` + `path`（缺省根），返回项 `{name, type, size, mtime}` |
| `GET /artifacts/file` | 读文本文件：返回 `{name, size, mtime, content}`，仅 utf-8，超限 413 |
| `GET /artifacts/download` | 下载原始流：`Content-Disposition: attachment` |

`runtime` 的根在每次请求时现算：先要求产物完成（`development/.agent-genesis/work/{agentName}/orchestrator-state.yaml` 流程收尾，且交付门禁 verdict ∈ `PASS` / `CONCERNS`；full 认 `pipeline_status: COMPLETED`，fast 认收尾步 `current_step: step-f1-fast-build` / `step-f2-fast-optimize`）；再在 `development/output/agents/` 下取**唯一**子目录名作为 `agentName`，取最新的 `v*` 版本目录。生产状态缺失或未完成、交付门禁未过、产物缺失、同一层出现多个子目录、或没有 `v*` 版本目录，都明确报错 - 与物化时的判定同一口径（见 [`03-session-run.md`](./03-session-run.md) §1.4）。可读状态见 [`../04-api/4.10-智能体产物状态.md`](../04-api/4.10-智能体产物状态.md)。

## 4. 路径安全

`assertRelativePath(path)` 是本模块唯一的安全边界，与 `assertAgentId` 同级、同风格：

- 拒绝绝对路径、空段、`.`、`..`、反斜杠与 NUL - 目录项逐段校验，拼出的路径 `.resolve` 后必须仍落在对应 stage 根内（双保险）；
- `stage` 经枚举校验（`development | preview | runtime | evaluation`），`agentId` 经既有 `assertAgentId`；
- 违规一律 400 `BAD_REQUEST`，不区分「非法」与「逃逸」 - 对调用方是同一种错误。
- 工作区目录解析失败：`workspace.directory` 为 `null`、工作区不存在或框架不可达，一律返回 502 `BAD_GATEWAY`，不回退到本地猜测路径。

符号链接按 `file` 展示（`lstat` 取链接自身信息，不跟随），读取时对解析后的真实路径再校验一次：真实路径必须仍在 stage 根内，逃出根外一律 400；不存在路径返回 404。

## 5. 边界

- 四个 stage 根共用一套实现，stage 只决定根目录，行为无差别；
- `development` 根包含 `output/agents/`，因此在 development 视图里也能看到运行产物；`runtime` 视图只暴露最新版本目录；
- 沙箱目录可能不存在（该 agent 从未开过对应沙箱会话或尚未物化）→ 404，与路径不存在同响应；
- `runtime` 根随最新版本变化：新版本出现后，同一个 `path` 在不同请求间可能指向不同版本；
- 文件大小上限走 config（`ARTIFACT_MAX_FILE_BYTES`，默认 2 MiB），只约束 `/artifacts/file`，下载不受限；
- 无缓存、无订阅：文件变化靠前端重新拉取，不进 WS。
