# Smart Factory 实时通道

> 状态：**已定稿**。本文定义 WebSocket 信封、订阅扇出、无回放边界、心跳与背压。
> 代码落点：`server/src/shared/live/*`、`server/src/index.ts`（网关挂载）。验收测试：`server/tests/ws.test.ts`、`server/tests/live-hub.test.ts`。
> 相关篇：协议形状见 [`../04-api/4.06-实时通道.md`](../04-api/4.06-实时通道.md)；挂起恢复流程见 [`06-approval.md`](./06-approval.md)。

## 1. 职责划分

- **WS 只做实时**：下行推事件、上行收动作。
- **REST 做一切 CRUD 与查询**，包括历史消息与挂起状态；历史**不放** WS（订阅时补发的仅是当前挂起帧，不回放历史事件），避免信道与查询混在一处。
- 信封、上行方法与下行事件清单见 [`../04-api/4.06-实时通道.md`](../04-api/4.06-实时通道.md)。
- **选 WS 而非 SSE**：一条连接复用多会话（SSE 在 HTTP/1.1 下同域限 6 条长连接），且聊天类产品惯例、留高频上行扩展位；代价是多一个 `ws` 依赖与三个测试点（半开连接、慢消费者、断线零补发）。

## 2. 实现要点

- 传输用 `ws`：`new WebSocketServer({ server, path })`。网关由 `index.ts` 在 `http.createServer` 之后 `attachWsGateway(server)` 挂载，`createApp()` 保持纯 Express、可被测试直接调用。
- **扇出**：`broadcast(sessionId, envelope)` 逐订阅者发送（进程内 `Map<sessionId, Set<Subscriber>>`，无跨进程广播）。
- **网关不认识业务**：动作（`send` / `run.abort` / `message.respond`）与订阅握手（`subscribeInfo`）以 handlers 注入，由 `index.ts` 装配，`shared/` 不反向依赖 `modules/`。
- **订阅语义**：`subscribe` 时会话不存在回 `NOT_FOUND`，不静默成功；成功回 `{subscribed:true, sessionId, status}`，`status` 是订阅时刻的会话状态快照。**先订阅、后取快照**，快照窗口内新落的挂起要么进入补发列表、要么作为实时事件到达，不会漏。
  **响应之后**再向该连接逐条补发该会话当前挂起（`status='pending'`）的 `approval.request` / `tool.interactive` 兼容事件帧，与实时兼容事件由同一构造函数产出、形状完全一致，不补发 `message` 帧。
  补发幂等：前端按 `approvalId` / `toolCallId` upsert，重复订阅重复补发是允许的。`send` 处理前先隐式订阅该会话，前端不必「先 subscribe 再 send」。
- **心跳（客户端驱动）**：服务端**不发**协议层 ping，只按 `wsHeartbeatMs`（默认 30s）扫描；上行帧（`{method:'ping'}` 回 `method:'pong'`、payload `{serverTime}` 的响应帧，或任何其它动作帧）到达即刷新活跃时间，**超过 2 倍间隔没收到任何帧**即以关闭码 `1000` + reason「心跳超时」断开并清理订阅（防半开连接与内存泄漏）。浏览器 WebSocket API 不能主动发协议层 ping，故保活一律走应用层信封，行为见 [`../04-api/4.06-实时通道.md`](../04-api/4.06-实时通道.md) §2。
- **背压**：`send()` 前检查 `bufferedAmount`，超阈值（4MB）发 `error{code:'SLOW_CONSUMER'}` 并断开。断开不丢数据：事件几乎都有对应的落库消息。
- **断线清理**：`close` 时从所有会话的订阅集合移除该 socket。

## 3. 「不回放」的精确边界：状态可查、事件不回放

| 允许 | 不允许 |
|---|---|
| `GET /messages/list?sessionId=` 拉到历史，其中 `status='pending'` 的行由前端渲染成可操作弹窗 | WS 服务端缓冲事件、按游标补发历史 |
| `?status=pending` 过滤，解决「挂起那条比加载的最后一页更老」 | 重连时重新下发一条已经推送过的 `chat.delta` |
| 任何新开的客户端、另一个标签页、另一台设备都能查到同一条挂起 | 把瞬态的 `chat.delta` 当可靠信道（断线即丢，终稿由落库消息补齐） |
| 订阅成功时补发该会话**当前挂起**的 `approval.request` / `tool.interactive` 兼容帧（只补 `status='pending'` 的行，幂等，前端按 `approvalId` / `toolCallId` upsert） | 订阅补发已结算的历史行：补发读的是库里的挂起状态，不是事件缓冲；也不补发 `message` 帧 |

由此产生一条客户端必须遵守的规则（见 [`../04-api/4.04-消息.md`](../04-api/4.04-消息.md) §4.3）：`messages` 不是 append-only（`status` 会变），所以**不能只按 `afterSeq` 增量续拉**。

## 4. 性能与背压

- 扇出为进程内 Map，`broadcast` 逐订阅者发送；慢消费者按 `bufferedAmount` 阈值断流。
- SQLite 单写者串行化，写入量级为会话事件，非瓶颈；`seq` 分配依赖该串行化（见 [`02-data-model.md`](./02-data-model.md)）。
- 无回放 ⇒ 服务端不缓冲历史事件，内存占用与会话数线性、与事件总量无关；订阅补发的挂起帧现查库，不占事件缓冲。
