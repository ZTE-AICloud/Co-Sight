# 05 Web 服务与 API

## FastAPI 应用装配

- 应用入口：[main.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py)
- 关键动作
  - 加载 `.env`（如果安装了 `python-dotenv`）（见 [main.py:L25-L39](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L25-L39)）
  - 初始化 `custom_config`（路由前缀、端口、上传目录等）（见 [main.py:L102-L108](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L102-L108)）
  - 确保 `work_space/`、`upload_files/` 目录存在并以静态资源方式挂载（见 [main.py:L119-L156](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L119-L156)）
  - 挂载前端静态页面到 `/cosight`（见 [main.py:L158-L204](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L158-L204)）
  - 注册路由：`user/search/ws/common/chat/feedback`（见 [main.py:L205-L210](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/main.py#L205-L210)）

## 路由前缀与端口

- 默认端口：`7788`（见 [config.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/common/config.py#L16-L24)）
- 默认 API 前缀：`/api/nae-deep-research/v1`（见 [config.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/common/config.py#L16-L24)）
- WebSocket API 前缀：`/api/openans-support-chatbot/v1`（同上）

## 核心接口：深度研究（Streaming）

- 路由定义：`POST /deep-research/search`（会被 `base_api_url` 前缀包裹）（见 [search.py:L385-L392](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L385-L392)）
- 主要入参（来自 WebSocket 透传，结构见 `websocket_manager._send_resp`）
  - `content: [{type: "text", value: "..."}]`：任务文本
  - `sessionInfo.messageSerialNumber`：用于稳定复用的 `plan_id`（见 [search.py:L403-L408](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L403-L408)）
  - `uploadedFiles`：上传文件 ID 列表（会被复制到 workspace）（见 [search.py:L432-L449](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L432-L449)）
  - `replay/replayWorkspace/replayPlanId`：回放控制字段（由 WebSocket 层透传）
- 输出形态
  - 使用 `StreamingResponse` 将“计划进度 + 工具事件 + 可信分析 + 最终结果”以流式方式返回（search 路由内部 `generator_func()` 负责把事件写入队列并持续 yield）。
  - 工具事件会进行“本地路径 → 可访问 URL”的改写（见 [search.py:L517-L563](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/search.py#L517-L563)）。

## WebSocket：前端交互层

- 路由：`/robot/wss/messages`（见 [websocket_manager.py:L85-L140](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L85-L140)）
- 关键行为
  - 前端发送 `action=message` 后，WebSocket 层组装请求并转发到本地 HTTP `.../deep-research/search`（见 [websocket_manager.py:L150-L213](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L150-L213)）
  - 以流式方式读取 HTTP 响应并回推到 topic（见 [websocket_manager.py:L220-L260](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L220-L260)）
  - 支持 `action=subscribe`，用于断线重连后按 topic 重新绑定（见 [websocket_manager.py:L113-L117](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/websocket_manager.py#L113-L117)）

## 其它接口

- 登录：`GET /deep-research/login`（见 [user_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/user_manager.py#L27-L35)）
- 登出：`POST /deep-research/logout`（见 [user_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/user_manager.py#L38-L42)）
- 服务器启动时间：`GET /deep-research/server-timestamp`（见 [common.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/common.py#L29-L34)）
- 停止消息：`POST /deep-research/stop-message`（见 [common.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/common.py#L36-L43)）
- Chat：`/chat/list`、`/chat/create`、`/chat/edit`（见 [chat_manager.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/chat_manager.py)）
- Feedback：`/feedback/reasons`（见 [feedback.py](file:///d:/lingdong/Co-Sight/cosight_server/deep_research/routers/feedback.py)）

