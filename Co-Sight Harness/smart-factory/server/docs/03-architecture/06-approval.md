# Smart Factory 审批与交互

> 状态：**已定稿**。本文定义「审批就是一条消息」的结算协议与 approved_all 的会话级语义。
> 代码落点：`server/src/modules/session/session.service.ts`（`requestInput` / `respondMessage` / `abortRun` 路径）、`server/src/shared/live/live-hub.ts`（`waitFor` / `settle`）。验收测试：`server/tests/approval.test.ts`、`server/tests/live-hub.test.ts`、`server/tests/e2e/session-flow.mjs`。
> 相关篇：消息与审批的表结构见 [`02-data-model.md`](./02-data-model.md)；通道与无回放见 [`05-realtime.md`](./05-realtime.md)。

## 1. 审批就是一条消息

不做独立的审批表、不做 `approvalId`、不做独立的 `approval.*` 事件。一次挂起 = `messages` 里一行：

| 环节 | 动作 |
|---|---|
| 引擎请求 | 适配器调 `ctx.requestInput(req)` |
| 挂起 | session 层插一条 `type` 为 `approval` / `tool_interactive`、`status='pending'` 的行（`seq` 照常递增，天然排在对话里）→ **先** `liveHub.waitFor(messageId)` 注册等待 → **再**广播 `message` 事件 → `await` 该 Promise。两步顺序不可反（理由见下） |
| 应答 | 客户端调 `message.respond`，条件更新抢仲裁：`UPDATE messages SET status=?, content=? WHERE id=? AND status='pending'` |
| 结算 | 命中（受影响 1 行）→ `liveHub.settle(messageId, decision)` 放行引擎 → 广播更新后的 `message` 事件 |
| 中止 | 该 run 所有 `status='pending'` 的行批量置 `aborted`，对应 `waitFor` 全部以 `aborted` 放行 |
| 重启 | 启动扫一遍残留 pending 行置 `aborted`，与 `failAllActiveRuns()` 同一处收口（见 [`03-session-run.md`](./03-session-run.md)） |

`content` 的形状见 [`../04-api/4.04-消息.md`](../04-api/4.04-消息.md) §3。**仲裁只有一处**：数据库的条件更新，受影响 1 行者胜、0 行者已处理；内存里的 Map 只存 resolve 句柄与「结算先到」的短暂暂存，不参与仲裁：真相在库里，崩溃安全。

因此 `live-hub` 上只需两个方法：`waitFor(messageId)` 与 `settle(messageId, decision)`，**不存在独立的审批模块**。

两个方法的契约必须写死，否则上面的「先注册后广播」仍会漏：

- `waitFor(id)` 注册一个等待者并返回 Promise；进入时先取暂存值，有则立即 resolve 并消费暂存，无则挂起等 `settle`。
- `settle(id, value)` 有等待者即放行并消费句柄；无等待者则**把 value 暂存**在 `Map<id, value>`，任一等者随后 `waitFor(id)` 进入时取走即删。暂存只保证不丢，结算仲裁已由 SQL 条件更新完成。

两条缺一不可：先注册后广播消除「广播先到、等待者后到」的窗口；暂存兜住「应答已落库、但等待者注册前进程被调度走」的重入。
任缺一条，在「审批不超时」下都会变成 run **永久挂起**，并占住活跃顶层 run 名额，卡死同会话（非 `runtime` 阶段还卡死整个实例）的后续运行（见 [`02-data-model.md`](./02-data-model.md) §6）。

## 2. 不超时

不设定时器，没有 `expiresAt`，没有 `rejected_timeout`。引擎一直 `await` 在那个 Promise 上，子进程一直等，与 Claude 的行为一致：你不答，它就一直等。出口只有四个：**用户应答、用户中止、服务重启、进程被杀**。

## 3. approved_all

`approved_all` 是**会话级**开关，落在 `sessions.approved_all`（DTO 字段 `approvedAll`），与 Claude 的权限语义一致：「全部允许」对这段对话一直有效，直到把审批模式降级。

触发只有一条路径：`messages/respond {decision:'approved_all'}`（含 `approval.respond` 兼容入口）。

- 服务端先赢下消息结算仲裁（`WHERE id=? AND status='pending'`），再更新会话：`approvalMode='full_access'`、`approvedAll=true`，最后 `liveHub.settle` 放行引擎。
- 会话更新在放行之前，因此同一 run 的下一条审批立即能看到新值；并发结算失败的一方只拿 409，不写会话。
- 会话更新落库失败只记日志，不让本次响应失败（与 agent-runtime 一致）。

策略在 session 层而不是 live-hub 内：`requestInput` 进来时先看当前会话的 `approvedAll`，为真则**不挂起**，直接返回 `approved_all`，但仍落一条 `type='approval'`、`status='approved_all'`、`decisionSource='approved_all_auto'` 的消息保留审计轨迹。
子 run 与顶层 run 读同一个会话开关，没有各自的副本。
权限规则只按会话级 `approvedAll` 生效，服务端不通过 `updatedPermissions` 把 SDK 的规则建议写进共享 cwd 的 `.claude/settings.local.json`；runtime 多会话共用 cwd 时，既不发生跨会话权限泄漏，也不会因并发读改写丢规则。

生命周期：

- 新 run 继承会话的 `approvalMode` 与 `approvedAll`，不会因为上一轮 run 结束而回到逐条审批。
- 把 `approvalMode` 经 WS `mode.switch` 切到任何非 `full_access` 的值（`read_only` / `workspace_write`）会同时把 `approvedAll` 复位为 `false`。
- 切到 `full_access` 不会自动置真；`approvedAll` 只由用户的 `approved_all` 决策置真。
- 没有单独的「重置 approvedAll」端点；复位入口就是审批模式降级。

三个决策与三种状态的关系：`approved`（允许一次）与 `rejected`（不允许）作用于单条挂起；`approved_all`（允许所有）把会话切到全权模式，作用于本 run 与后续 run 的所有挂起。授权范围是会话，跨 run 有效。

## 4. 语义后果

- 客户端在挂起期间断线 → 服务端继续持有，引擎继续阻塞；重连后靠**查历史**重新看到，靠 WS 看不到（「不回放」的精确边界见 [`05-realtime.md`](./05-realtime.md)）。
- 审批不超时 + 活跃顶层 run 名额（见 [`02-data-model.md`](./02-data-model.md) §6）⇒ 无人应答的 run 一直占着名额，直到 abort 或重启；被卡住的范围由 §6 的名额粒度决定。
  前端应把 `runs/detail` 派生的 `waiting` 渲染成醒目的「等待审批中，已等 X 秒」，并提供中止按钮。
- 服务重启后挂起的 run 不能续命（挂起是进程内的 Promise，跨不过重启），一律 `failed` + 审批 `aborted`（重启收口见 [`03-session-run.md`](./03-session-run.md)）。
