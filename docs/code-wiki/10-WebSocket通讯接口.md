# WebSocket 通讯接口（前后端）

本项目的 WebSocket 通讯仅有 1 套：前端原生 WebSocket 客户端与后端 FastAPI WebSocket 服务端。

## 1. 连接与路由

### 1.1 后端路由

- WebSocket 路由定义：[/robot/wss/messages](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L85-L90)
- Router 挂载前缀：`base_chatbot_api_url = "/api/openans-support-chatbot/v1"`：[config.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/common/config.py#L16-L24)
- Router 挂载位置：[main.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L205-L210)

最终服务端 WS 路径：

`/api/openans-support-chatbot/v1/robot/wss/messages`

### 1.2 前端连接 URL 生成方式

- 路径常量：[_webSocketPath](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L8-L13)
- URL 组装与连接创建：[_createWebsocket](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L195-L210)

最终连接 URL（浏览器内实际值）：

`ws(s)://{window.location.host}/api/openans-support-chatbot/v1/robot/wss/messages?lang={lang}&websocket-client-key={clientKey}`

### 1.3 Query 参数（握手参数）

- `lang`：必填；后端以 Query 方式接收：[websocket_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L85-L90)
  - 前端默认语言取浏览器语言：[_getBrowserLanguage](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L23-L36)
  - 可通过 `WebSocketService.setLang(lang)` 修改（影响 WS URL 与发送消息体中的 `lang` 字段）：[setLang](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L314-L329)
- `websocket-client-key`：可选；后端以 Query 方式接收：[websocket_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L85-L93)
  - 前端持久化在 `localStorage: cosight:wsClientKey`（用于跨刷新保持）：[_createWebsocket](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L195-L210)
- Cookie：后端会读取 WS 握手时带来的 cookies，并在内部转发 HTTP 请求时带上：[websocket_handler/_send_resp](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L91-L207)

## 2. 协议总览（Topic 路由）

该 WS 通道以 `topic` 作为“会话/任务”路由键：

- 客户端先对 `topic` 发 `subscribe`，让服务端绑定 `topic -> 当前 websocket`
- 之后服务端对该 `topic` 的所有推送，都会发到绑定的 websocket 上

服务端 topic 绑定实现：[bind_topic/topic_to_ws](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L31-L75)

## 3. 客户端 -> 服务端（入站消息）

服务端只处理两类 `action`：[websocket_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L109-L139)

### 3.1 subscribe

用途：声明当前连接关注某个 `topic`，允许刷新/断线重连后继续接收该 topic 的推送。

消息格式：

```json
{
  "action": "subscribe",
  "topic": "topic-uuid"
}
```

前端触发器：

- `WebSocketService.subscribe(topic, callback)` 会立即发送 subscribe：[subscribe/_sendSubscribe](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L66-L122)
- 断线重连成功（onopen）会对已订阅 topic 补发 subscribe：[_onopen](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L223-L230)

后端处理：

- 收到 `action=subscribe` 后将 `topic` 绑定到当前 websocket：[websocket_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L112-L117)

### 3.2 message

用途：在某个 `topic` 上发起一次任务/对话/回放。

外层消息格式（注意 `data` 是 JSON 字符串）：

```json
{
  "action": "message",
  "topic": "topic-uuid",
  "data": "{...JSON字符串...}",
  "lang": "zh"
}
```

前端触发器：

- 新任务：`messageService.sendMessage(content)`：[MessageService.sendMessage](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L628-L676)
- 回放：`messageService.sendReplay(workspacePath, replayPlanId)`：[sendReplay](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L683-L814)
- 刷新恢复 pending：连接成功后对 `cosight:pendingRequests` 重新订阅/必要时重发：[init.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/init.js#L8-L40)

后端处理：

- 服务端会 `json.loads(data)` 解析业务消息体，并绑定 `topic -> websocket`：[websocket_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L118-L123)
- 随后转发到 HTTP 流式接口 `/deep-research/search`，并把流式结果回推到 WS：[_send_resp/_stream_handler](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L150-L317)

## 4. message 的业务消息体（data 内部 JSON）

### 4.1 新任务（常规请求）

由前端组装（示例字段）：[MessageService.sendMessage](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L647-L675)

- `initData`：数组（多模态内容），典型为 `[{type:"text", value:"..."}]`
- `extra.fromBackEnd.actualPrompt`：服务端透传为 `contentProperties`（字符串）
- `sessionInfo.messageSerialNumber`：前端生成并复用的 planId（用于后端持久化文件命名/任务标识）
  - 生成与缓存逻辑：`ensurePlanIdForTopic(topic)`：[ensurePlanIdForTopic](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L121-L137)

### 4.2 上传文件（可选）

前端若在 `extra.fromBackEnd.uploadedFiles` 放置文件 ID 列表，后端会提取到 `params["uploadedFiles"]` 并在搜索侧复制文件到工作区：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L166-L175) 与 [search.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L432-L449)

### 4.3 回放（Replay）

前端会把 `replay/replayWorkspace/replayPlanId` 放在 `extra` 与 `extra.fromBackEnd` 两处（兼容服务端提取逻辑）：[sendReplay](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L774-L799)

后端会识别并透传以下字段到搜索侧（并复用 planId）：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L176-L201)

- `replay: true`
- `replayWorkspace: "work_space_xxx"`
- `sessionInfo.messageSerialNumber = replayPlanId`（复用历史）

搜索侧会按是否 replay 决定是否创建新的 workspace 目录：[search.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L395-L431)

## 5. 服务端 -> 客户端（出站推送）

### 5.1 welcome（连接后立即推送）

触发器：新连接 accept 后立即推送 welcome：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L95-L108)

消息格式：

```json
{
  "data": {
    "type": "welcome",
    "initData": {
      "title": "...",
      "desc": "...",
      "abilities": [],
      "maxHeight": "468px"
    }
  }
}
```

### 5.2 human 回显（in_progress）

触发器：收到 `action=message` 后立即推送（用于更新时间戳与状态）：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L124-L139)

消息格式：

```json
{
  "topic": "topic-uuid",
  "data": {
    "type": "multi-modal",
    "uuid": "来自客户端的uuid",
    "timestamp": 1710000000000,
    "from": "human",
    "changeType": "replace",
    "initData": [],
    "roleInfo": {},
    "status": "in_progress"
  }
}
```

### 5.3 ai 流式消息（append/replace）

触发器：后端 `_stream_handler` 把 `/deep-research/search` 的流式响应逐条转发：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L275-L295)

消息格式（关键字段）：

- `data.type`：来自下游流的 `contentType`，缺省为 `multi-modal`
- `data.changeType`：来自下游流的 `changeType`，缺省为 `append`
- `data.initData`：来自下游流的 `content`
- `data.extra/status/roleInfo/headFoldConfig`：来自下游流的同名字段（若存在）

### 5.4 control-status-message（结束控制信号）

触发器：当某条 AI 流消息 `type == "lui-message-manus-step"` 且 `progress.completed >= progress.total` 时，额外发送一次结束信号：[websocket_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L297-L317)

消息格式：

```json
{
  "topic": "topic-uuid",
  "data": {
    "type": "control-status-message",
    "initData": {
      "status": "finished_successfully"
    }
  }
}
```

前端触发器：收到该类型后会清理该 topic 的 pending（认为已完成）：[MessageService.receiveMessage](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L34-L47)

## 6. 前端消息消费（data.type/contentType -> 功能）

前端统一接收入口：`messageService.receiveMessage(messageData)`：[message.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L12-L77)

- `lui-message-manus-step`：创建/更新 DAG（步骤、依赖、进度）
  - 分发：`stepMessageHandler -> createDag(messageData)`：[stepMessageHandler](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L79-L116)，[createDag](file:///d:/lingdong/Co-Sight/cosight_server/web/js/dag.js#L531-L589)
- `lui-message-tool-event`：工具事件面板（tool_start/tool_complete/tool_error），并持久化 step tool events
  - 分发：`handleToolEvent(messageData)`：[handleToolEvent](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L143-L270)
- `lui-message-credibility-analysis`：可信分析展示
  - 分发：`credibilityService.credibilityMessageHandler(messageData)`：[MessageService.receiveMessage](file:///d:/lingdong/Co-Sight/cosight_server/web/js/message.js#L59-L64)
  - 相关实现：[credibility.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/credibility.js)

## 7. 断线重连与刷新恢复

### 7.1 断线重连

- 触发器：WS `onclose`，10 秒后重连：[websocket.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L235-L242)
- 重连成功后：补发所有 topic 的 subscribe：[_onopen](file:///d:/lingdong/Co-Sight/cosight_server/web/js/websocket.js#L223-L230)

### 7.2 刷新恢复（pendingRequests）

- 触发器：页面启动后，WS connected 事件触发 `setupMessageHandling()`：[init.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/init.js#L32-L40)
- 行为：
  - 重新订阅每个 pending topic
  - 仅当 `stillPending===true` 才重发，避免刷新重复执行：[init.js](file:///d:/lingdong/Co-Sight/cosight_server/web/js/init.js#L8-L26)

