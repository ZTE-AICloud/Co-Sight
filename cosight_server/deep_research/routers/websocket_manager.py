# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import List, Optional

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.config import custom_config
from app.common.logger_util import get_logger
from cosight_server.sdk.common.utils import get_timestamp
from cosight_server.deep_research.services.openclaw_client import openclaw_client_manager

logger = get_logger("websocket")
wsRouter = APIRouter()

class WebsocketManager:
    def __init__(self):
        # 存放激活的ws连接对象
        self.active_clients: List[WebSocket] = []
        # 维护 topic 到最新 WebSocket 的映射（用于断线重连后路由消息）
        self.topic_to_ws: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket):
        # 等待连接
        await ws.accept()
        # 存储ws连接对象
        self.active_clients.append(ws)
        logger.info(f"ws connect >>>>>>>>>>>>>> ")

    def disconnect(self, ws: WebSocket):
        # 关闭时 移除ws对象
        self.active_clients.remove(ws)
        # 清理与该 ws 相关的 topic 绑定
        topics_to_remove = [topic for topic, mapped_ws in self.topic_to_ws.items() if mapped_ws is ws]
        for topic in topics_to_remove:
            self.topic_to_ws.pop(topic, None)

    @staticmethod
    async def send_message(message: str, ws: WebSocket):
        # 发送个人消息
        await ws.send_text(message)

    @staticmethod
    async def send_json(data: dict, ws: WebSocket):
        # 发送个人消息
        await ws.send_json(data)

    def bind_topic(self, topic: str, ws: WebSocket):
        if topic:
            self.topic_to_ws[topic] = ws

    def get_ws_for_topic(self, topic: str) -> Optional[WebSocket]:
        return self.topic_to_ws.get(topic)

    async def send_json_to_topic(self, topic: str, data: dict, default_ws: Optional[WebSocket] = None):
        ws = self.get_ws_for_topic(topic) or default_ws
        if ws is not None:
            logger.info(f"send_json_to_topic >>>>>>>>>>>>>> topic: {topic}, data: {data}")
            await ws.send_json(data)

    async def broadcast(self, message: str):
        # 广播消息
        for client in self.active_clients:
            await client.send_text(message)


manager = WebsocketManager()


def _get_replay_workspace_path(message: dict, topic: str) -> Optional[str]:
    """获取当前会话用于回放的 workspace 目录（replay.json 所在目录）。
    优先从 message.extra.replayWorkspace / fromBackEnd.replayWorkspace 读取；
    否则按时间戳新建一个 OpenClaw 专用 workspace，与 search 的 work_space 同基目录，便于回放列表展示。
    """
    try:
        extra = message.get("extra") or {}
        if isinstance(extra, dict):
            from_back_end = extra.get("fromBackEnd") or {}
            replay_workspace = extra.get("replayWorkspace") or from_back_end.get("replayWorkspace")
            if isinstance(replay_workspace, str) and replay_workspace.strip():
                path = replay_workspace.strip()
                if not os.path.isabs(path):
                    path = os.path.join(os.getcwd(), path)
                return path
    except Exception:
        pass
    try:
        # OpenClaw 始终创建新 workspace，与 search 的 work_space_path 同基目录
        curr = os.environ.get("WORKSPACE_PATH")
        if isinstance(curr, str) and curr.strip():
            curr = os.path.abspath(curr) if not os.path.isabs(curr) else curr
            bname = os.path.basename(curr)
            if "work_space_" in bname:
                # curr 是具体 workspace 路径（如 work_space/work_space_20250202_xxx）
                base = os.path.dirname(curr)
            elif bname == "work_space":
                # curr 已是 work_space 基目录
                base = curr
            else:
                base = os.path.join(curr, "work_space")
        else:
            base = os.path.join(os.getcwd(), "work_space")
        if not os.path.isabs(base):
            base = os.path.abspath(os.path.join(os.getcwd(), base))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(base, f"work_space_{timestamp}")
        os.makedirs(path, exist_ok=True)
        logger.info(f"创建 OpenClaw replay workspace: {path}")
        return path
    except Exception as e:
        logger.warning(f"无法解析或创建 replay workspace: {e}")
    return None


def _append_to_replay(workspace_path: Optional[str], payload: dict) -> None:
    """将发给前端的单条消息追加到该 workspace 下的 replay.json（JSONL 一行）。"""
    if not workspace_path:
        return
    try:
        replay_file = os.path.join(workspace_path, "replay.json")
        os.makedirs(workspace_path, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        if not line.endswith("\n"):
            line += "\n"
        with open(replay_file, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.warning(f"写入 replay.json 失败: {e}")


@wsRouter.websocket("/robot/wss/messages")
async def websocket_handler(
        websocket: WebSocket,
        websocket_client_key: Optional[str] = Query(None, alias="websocket-client-key"),
        lang: str = Query(..., alias="lang")):
    await manager.connect(websocket)
    cookie = websocket.cookies
    logger.info(f"websocket_handler >>>>>>>>>>>>>> websocket_client_key: {websocket_client_key}, lang: {lang}, "
                f"cookie: {cookie}")

    try:
        welcome_message = {
            "data": {
                "type": "welcome",
                "initData": {
                    "title": i18n.t('welcome_title'),
                    "desc": i18n.t('welcome_desc'),
                    "abilities": [],
                    "maxHeight": "468px"
                }
            }
        }
        await manager.send_json(welcome_message, websocket)
        # Started by AICoder, pid:cd2a2pa21827c9b148ae08eff0221b0be93612b0
        while True:
            data = await websocket.receive_json()
            logger.info(f"receive >>>>>>>>>>>>>> {data}")
            # 处理订阅动作，允许前端仅通过 topic 绑定路由（刷新后无需立即发起新任务即可接收后续消息）
            if data.get("action") == "subscribe":
                topic = data.get("topic")
                manager.bind_topic(topic, websocket)
                logger.info(f"bind topic >>> {topic} to current websocket")
                continue
            if data.get("action") == "message":
                raw_data = data.get("data")
                if isinstance(raw_data, dict):
                    message = raw_data
                else:
                    message = json.loads(raw_data or "{}")
                logger.info(f"message >>>>>>>>>>>>>> {message}")
                # 绑定当前 topic 到该 websocket
                manager.bind_topic(data.get("topic"), websocket)

                # 推送时间更新的消息给前端
                await manager.send_json_to_topic(data.get("topic"), {
                    "topic": data.get("topic"),
                    "data": {
                        "type": message.get("type"),
                        "uuid": message.get("uuid"),
                        "timestamp": get_timestamp(),
                        "from": "human",
                        "changeType": "replace",
                        "initData": message.get("initData"),
                        "roleInfo": message.get("roleInfo"),
                        "status": "in_progress"
                    }
                }, websocket)

                # 路由逻辑：根据target字段决定转发到Co-Sight还是OpenClaw
                target = data.get("target", "cosight")  # 默认使用cosight
                logger.info(f"消息路由 target={target}, topic={data.get('topic')}")
                
                # 新增：后端二次检测OpenClaw命令（作为后备检测）
                init_data = message.get("initData", [])
                if isinstance(init_data, list) and len(init_data) > 0:
                    first_item = init_data[0]
                    if isinstance(first_item, dict) and first_item.get("type") == "text":
                        text_value = first_item.get("value", "").strip()
                        if text_value.startswith("/openclaw"):
                            target = "openclaw"
                            # 去掉 /openclaw 前缀
                            actual_command = text_value[len("/openclaw"):].strip()
                            if actual_command:
                                # 更新消息内容
                                init_data[0]["value"] = actual_command
                                message["initData"] = init_data
                                logger.info(f"后端检测到OpenClaw命令，实际内容: {actual_command}")
                            else:
                                # 命令为空，使用默认问候
                                init_data[0]["value"] = "你好"
                                message["initData"] = init_data
                                logger.warning("OpenClaw命令为空，使用默认问候")
                
                if target == "openclaw":
                    # 转发给OpenClaw
                    await _send_to_openclaw(websocket, data.get("topic"), message, lang)
                else:
                    # 原有Co-Sight逻辑
                    await _send_resp(websocket, cookie, data.get("topic"), message, lang)


        # Ended by AICoder, pid:cd2a2pa21827c9b148ae08eff0221b0be93612b0

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.error(f"disconnect >>>>>>>>>>>>>> ")


# Started by AICoder, pid:wb967gf743u19051414d0be1f088122a49b62acf
async def _send_resp(websocket, cookie, topic, message, lang):
    cookie_str = "; ".join([f"{key}={value}" for key, value in cookie.items()])
    assistants = [mention['name'] for mention in message['mentions']]
    params = {
        "content": message.get("initData"),
        "history": [],
        "sessionInfo": {
            "locale": lang,
            "sessionId": topic,
            "username": message.get("roleInfo").get("name"),
            "assistantNames": assistants
        },
        "stream": True,
        "contentProperties": message.get("extra", {}).get("fromBackEnd", {}).get("actualPrompt")
    }
    
    # 提取上传的文件ID列表
    try:
        extra = message.get("extra", {}) or {}
        from_back_end = (extra.get("fromBackEnd") or {}) if isinstance(extra, dict) else {}
        uploaded_files = from_back_end.get("uploadedFiles")
        if uploaded_files and isinstance(uploaded_files, list) and len(uploaded_files) > 0:
            params["uploadedFiles"] = uploaded_files
            logger.info(f"Found uploaded files in message: {uploaded_files}")
    except Exception as e:
        logger.warning(f"Error extracting uploaded files from message: {e}")
    # 支持回放控制字段：replay、replayWorkspace、replayPlanId
    try:
        extra = message.get("extra", {}) or {}
        from_back_end = (extra.get("fromBackEnd") or {}) if isinstance(extra, dict) else {}
        # 允许两处读取：extra.replay / extra.fromBackEnd.replay
        replay_flag = extra.get("replay")
        if replay_flag is None:
            replay_flag = from_back_end.get("replay")
        if isinstance(replay_flag, bool) and replay_flag:
            params["replay"] = True

        # 显式传入要回放的 workspace 目录（包含 replay.json）
        replay_workspace = extra.get("replayWorkspace")
        if replay_workspace is None:
            replay_workspace = from_back_end.get("replayWorkspace")
        if isinstance(replay_workspace, str) and replay_workspace:
            params["replayWorkspace"] = replay_workspace

        # 使用既有的 planId（对应 messageSerialNumber）避免新建 topic / 计划
        replay_plan_id = extra.get("replayPlanId")
        if replay_plan_id is None:
            replay_plan_id = from_back_end.get("replayPlanId")
        if isinstance(replay_plan_id, str) and replay_plan_id:
            # 不覆盖现有 sessionId；仅设置 messageSerialNumber 以复用历史文件名
            params.setdefault("sessionInfo", {})["messageSerialNumber"] = replay_plan_id
    except Exception:
        pass
    url = f'http://127.0.0.1:{custom_config.get("search_port")}{custom_config.get("base_api_url")}/deep-research/search'
    headers = {
        "content-type": "application/json;charset=utf-8",
        "Cookie": cookie_str,
    }
    try:
        if params.get("stream", False):
            await _stream_handler(params, url, headers, topic, websocket)
        else:
            await _no_stream_handler(params, url, headers, topic, websocket)
    except Exception as e:
        logger.error(f"response websocket error: {e}", exc_info=True)


# Ended by AICoder, pid:wb967gf743u19051414d0be1f088122a49b62acf


async def _stream_handler(params, url, headers, topic, websocket):
    msg_uuid = str(uuid.uuid4())
    
    # 设置更大的读取限制，避免大消息块被截断
    # 通过修改 aiohttp 的内部限制
    import aiohttp
    import aiohttp.streams
    
    # 设置读取超时为无限，避免长时间无数据导致 TimeoutError
    timeout = aiohttp.ClientTimeout(sock_read=None, total=None)
    sessionInfo = params.get('sessionInfo', {})
    # 若未显式指定回放的 planId，则为本次新流生成 messageSerialNumber
    if not sessionInfo.get('messageSerialNumber'):
        sessionInfo['messageSerialNumber'] = msg_uuid
    params['sessionInfo'] = sessionInfo
    # 设置连接器，提高连接池限制
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
    
    # 保存原始限制并将默认限制调大，避免单行/单块过大错误
    original_limit = getattr(aiohttp.streams, '_DEFAULT_LIMIT', 2**16)  # 64KB
    aiohttp.streams._DEFAULT_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB
    
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(url=url, json=params, headers=headers) as response:
                # 尝试将实例级读取限制也放大，避免readline触发Chunk too big
                try:
                    reader = getattr(response, 'content', None)
                    big_limit = 2 * 1024 * 1024 * 1024  # 2GB
                    if reader is not None and hasattr(reader, '_limit'):
                        reader._limit = big_limit
                        logger.info(f"aiohttp StreamReader instance limit set to {big_limit}")
                except Exception:
                    pass
                control_sent = False
                # 为规避 aiohttp 对单行的内置限制，这里改为按块读取并按换行还原行，不会拆分业务消息
                buffer = b''
                try:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        if not chunk:
                            continue
                        buffer += chunk
                        while True:
                            nl_pos = buffer.find(b'\n')
                            if nl_pos == -1:
                                break
                            line = buffer[:nl_pos + 1]
                            buffer = buffer[nl_pos + 1:]
                            decoded_line = line.decode('utf-8', errors='ignore')
                            try:
                                line_json = json.loads(decoded_line)
                            except json.JSONDecodeError:
                                # 非完整JSON行，跳过
                                continue

                            # 回放中来自 OpenClaw 的已格式化的 WS 消息：用当前请求的 topic 透传，否则前端用录制时的 topic 取不到当前会话的展示
                            if isinstance(line_json.get("data"), dict) and "topic" in line_json:
                                payload = {"topic": topic, "data": line_json["data"]}
                                await manager.send_json_to_topic(topic, payload, websocket)
                                continue

                            msg_type = line_json.get("contentType") if line_json.get("contentType") is not None else "multi-modal"
                            init_data = line_json.get("content") if line_json.get("content") is not None else [
                                {"type": "text", "value": i18n.t('unknown_message')}]
                            change_type = line_json.get("changeType") if line_json.get("changeType") is not None else "append"

                            await manager.send_json_to_topic(topic, {
                                "topic": topic,
                                "data": {
                                    "type": msg_type,
                                    "uuid": msg_uuid,
                                    "timestamp": get_timestamp(),
                                    "from": "ai",
                                    "source": "cosight",  # 标识来源
                                    "changeType": change_type,
                                    "initData": init_data,
                                    "headFoldConfig": line_json.get("headFoldConfig"),
                                    "roleInfo": line_json.get("roleInfo"),
                                    "status": line_json.get("status"),
                                    "extra": line_json.get("extra"),
                                    "styles": {"width": "100%"}
                                }
                            }, websocket)

                            # 如果这是plan更新数据，且progress显示已全部完成，则发送结束控制
                            try:
                                if (not control_sent) and msg_type == "lui-message-manus-step" and isinstance(init_data, dict):
                                    progress = init_data.get("progress") or {}
                                    total = int(progress.get("total") or 0)
                                    completed = int(progress.get("completed") or 0)
                                    if total > 0 and completed >= total:
                                        # 先让出事件循环，确保上面的最终PLAN更新已被前端渲染
                                        import asyncio as _asyncio
                                        await _asyncio.sleep(0)
                                        await manager.send_json_to_topic(topic, {
                                            "topic": topic,
                                            "data": {
                                                "type": "control-status-message",
                                                "initData": {
                                                    "status": "finished_successfully"
                                                }
                                            }
                                        }, websocket)
                                        control_sent = True
                                        # 计划已完成，后续如仍有流数据，继续透传；不强制关闭连接
                            except Exception:
                                # 解析或字段缺失不阻断主流程
                                pass
                except Exception:
                    # 发生读取异常（包含超时），尝试把缓冲区中已到达的完整行消费掉
                    while True:
                        nl_pos = buffer.find(b'\n')
                        if nl_pos == -1:
                            break
                        line = buffer[:nl_pos + 1]
                        buffer = buffer[nl_pos + 1:]
                        decoded_line = line.decode('utf-8', errors='ignore')
                        try:
                            line_json = json.loads(decoded_line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(line_json.get("data"), dict) and "topic" in line_json:
                            payload = {"topic": topic, "data": line_json["data"]}
                            await manager.send_json_to_topic(topic, payload, websocket)
                            continue
                        msg_type = line_json.get("contentType") if line_json.get("contentType") is not None else "multi-modal"
                        init_data = line_json.get("content") if line_json.get("content") is not None else [
                            {"type": "text", "value": i18n.t('unknown_message')}]
                        change_type = line_json.get("changeType") if line_json.get("changeType") is not None else "append"
                        await manager.send_json_to_topic(topic, {
                            "topic": topic,
                            "data": {
                                "type": msg_type,
                                "uuid": msg_uuid,
                                "timestamp": get_timestamp(),
                                "from": "ai",
                                "source": "cosight",  # 标识来源
                                "changeType": change_type,
                                "initData": init_data,
                                "headFoldConfig": line_json.get("headFoldConfig"),
                                "roleInfo": line_json.get("roleInfo"),
                                "status": line_json.get("status"),
                                "extra": line_json.get("extra"),
                                "styles": {"width": "100%"}
                            }
                        }, websocket)
                    return
    finally:
        # 恢复原始限制
        aiohttp.streams._DEFAULT_LIMIT = original_limit


async def _no_stream_handler(params, url, headers, topic, websocket):
    async with aiohttp.ClientSession() as session:
        async with session.post(url=url, json=params, headers=headers) as response:
            resp = await response.json()
            logger.info(f"/deep-research/search >>>>>>>>>>> resp: {resp}")
            await manager.send_json({
                "topic": topic,
                "data": {
                    "type": resp.get("contentType") or "multi-modal",
                    "uuid": str(uuid.uuid4()),
                    "timestamp": get_timestamp(),
                    "from": "ai",
                    "source": "cosight",  # 标识来源
                    "initData": resp.get("content"),
                    "promptSentences": resp.get("promptSentences") or [],
                    "roleInfo": resp.get("roleInfo"),
                    "extra": resp.get("extra")
                }
            }, websocket)


async def _send_to_openclaw(websocket: WebSocket, topic: str, message: dict, lang: str):
    """
    将消息转发给OpenClaw并处理响应

    Args:
        websocket: WebSocket连接
        topic: 会话topic
        message: 消息内容
        lang: 语言
    """
    msg_uuid = str(uuid.uuid4())
    replay_workspace = _get_replay_workspace_path(message, topic)

    async def send_openclaw_and_replay(payload: dict) -> None:
        """发往前端并同时追加到当前会话的 replay.json（payload 为 {topic, data}）"""
        await manager.send_json_to_topic(topic, payload, websocket)
        _append_to_replay(replay_workspace, payload)

    try:
        # 若未连接则尝试按需连接（支持先起 Co-Sight 后起 Gateway 的场景）
        await openclaw_client_manager.ensure_connected()
        if not openclaw_client_manager.is_connected():
            error_message = "OpenClaw未连接" if lang == "zh" else "OpenClaw not connected"
            await send_openclaw_and_replay({
                "topic": topic,
                "data": {
                    "type": "multi-modal",
                    "uuid": msg_uuid,
                    "timestamp": get_timestamp(),
                    "from": "ai",
                    "source": "openclaw",  # 标识来源
                    "changeType": "replace",
                    "initData": [{"type": "text", "value": error_message}],
                    "status": "error"
                }
            })
            return

        client = openclaw_client_manager.get_client()
        if not client:
            error_message = "OpenClaw客户端不可用" if lang == "zh" else "OpenClaw client unavailable"
            await send_openclaw_and_replay({
                "topic": topic,
                "data": {
                    "type": "multi-modal",
                    "uuid": msg_uuid,
                    "timestamp": get_timestamp(),
                    "from": "ai",
                    "source": "openclaw",
                    "changeType": "replace",
                    "initData": [{"type": "text", "value": error_message}],
                    "status": "error"
                }
            })
            return
        
        # 用于累积不同来源的文本和同步final事件
        accumulated_text = {
            "text": "",        # 来自 chat delta 事件
            "agent_text": "", # 来自 agent 事件
            "need_history": False,
            "runId": None
        }
        final_event = asyncio.Event()  # 用于等待chat final事件
        
        # 注册事件处理器来接收OpenClaw的响应
        async def handle_openclaw_event(event_data: dict):
            """处理OpenClaw事件"""
            event_type = event_data.get("event")
            payload = event_data.get("payload", {})
            
            # 处理 agent 事件（包含实际的消息数据）
            if event_type == "agent":
                run_session_key = payload.get("sessionKey")
                if run_session_key == openclaw_session_key:
                    stream_type = payload.get("stream")
                    data = payload.get("data")
                    seq = payload.get("seq", 0)
                    
                    logger.info(f"收到OpenClaw agent事件: sessionKey={run_session_key}, stream={stream_type}, seq={seq}, data类型={type(data)}")
                    
                    # 尝试从 agent 事件的 data 中提取文本
                    if data:
                        logger.info(f"agent事件data内容(前500字符): {str(data)[:500]}...")
                        
                        # data 可能是 JSON 字符串，尝试解析
                        if isinstance(data, str):
                            try:
                                import json
                                data_obj = json.loads(data)
                                logger.info(f"解析后的data类型: {type(data_obj)}, keys: {data_obj.keys() if isinstance(data_obj, dict) else 'N/A'}")
                                
                                # 如果是消息对象，提取文本
                                if isinstance(data_obj, dict):
                                    # 可能的格式1: {"type": "text", "text": "..."}
                                    if data_obj.get("type") == "text" and "text" in data_obj:
                                        text = data_obj.get("text", "").strip()
                                        if text and not accumulated_text.get("agent_text"):
                                            accumulated_text["agent_text"] = text
                                            logger.info(f"✅ 从agent事件提取到文本(格式1)，长度: {len(text)}")
                                    
                                    # 可能的格式2: {"role": "assistant", "content": [...]}
                                    elif data_obj.get("role") == "assistant":
                                        content_items = data_obj.get("content", [])
                                        text_parts = []
                                        for item in content_items:
                                            if isinstance(item, dict) and item.get("type") == "text":
                                                text = item.get("text", "").strip()
                                                if text:
                                                    text_parts.append(text)
                                        if text_parts:
                                            accumulated_text["agent_text"] = "\n".join(text_parts)
                                            logger.info(f"✅ 从agent事件提取到文本(格式2)，长度: {len(accumulated_text['agent_text'])}")
                                
                            except json.JSONDecodeError:
                                logger.debug(f"agent事件data不是JSON格式")
                        elif isinstance(data, dict):
                            # data 已经是字典对象
                            logger.info(f"agent事件data是字典，keys: {data.keys()}")
                    
                    # 不要return，让后续的 chat 事件也能处理
            
            if event_type == "chat":
                # OpenClaw的chat事件
                state = payload.get("state")
                run_session_key = payload.get("sessionKey")
                
                # 记录所有 chat 事件（用于调试）
                logger.info(f"收到OpenClaw chat事件: state={state}, sessionKey={run_session_key}, payload_keys={list(payload.keys())}")
                
                # 只处理当前会话的事件
                if run_session_key != openclaw_session_key:
                    logger.debug(f"跳过其他会话的事件: {run_session_key} != {openclaw_session_key}")
                    return
                
                if state == "delta":
                    # 增量更新：累积文本
                    message_obj = payload.get("message")
                    logger.info(f"delta事件中的message对象类型: {type(message_obj)}, keys: {message_obj.keys() if isinstance(message_obj, dict) else 'N/A'}")
                    
                    if message_obj:
                        content_items = message_obj.get("content", []) if isinstance(message_obj, dict) else []
                        for item in content_items:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                if text.strip():
                                    accumulated_text["text"] = text  # delta 事件发送的是完整文本，不是增量
                                    logger.info(f"✅ 收到delta事件文本，长度: {len(text)}, 前100字符: {text[:100]}")
                    
                    if not accumulated_text["text"]:
                        logger.warning(f"delta事件未提取到文本: message_obj={message_obj}")
                
                elif state == "final":
                    # Chat完成，需要主动调用chat.history获取完整对话
                    # 原因：OpenClaw Gateway的webchat硬编码了disableBlockStreaming=true
                    # 导致chat final事件中没有message字段
                    try:
                        logger.info(f"Chat完成，准备获取历史消息: sessionKey={openclaw_session_key}")
                        
                        # 设置标志并触发event
                        accumulated_text["need_history"] = True
                        accumulated_text["runId"] = payload.get("runId")
                        final_event.set()  # 触发等待
                    
                    except Exception as e:
                        logger.error(f"处理chat final事件异常: {e}", exc_info=True)
                
                elif state == "error":
                    # 错误状态
                    error_msg = payload.get("errorMessage", "Unknown error")
                    await send_openclaw_and_replay({
                        "topic": topic,
                        "data": {
                            "type": "multi-modal",
                            "uuid": msg_uuid,
                            "timestamp": get_timestamp(),
                            "from": "ai",
                            "source": "openclaw",
                            "changeType": "replace",
                            "initData": [{"type": "text", "value": f"Error: {error_msg}"}],
                            "status": "error"
                        }
                    })
        
        # 注册事件处理器（监听"chat"和"agent"事件）
        client.register_event_handler("chat", handle_openclaw_event)
        client.register_event_handler("agent", handle_openclaw_event)
        
        # 提取用户消息
        user_message = message.get("initData", "")
        if isinstance(user_message, list):
            # 如果是多模态消息，提取文本内容
            text_parts = [item.get("value", "") for item in user_message if item.get("type") == "text"]
            user_message = " ".join(text_parts)
        user_input_title = (user_message or "").strip() or ("OpenClaw" if lang == "en" else "OpenClaw 对话")

        # 先发一条单节点 manus step 到前端（状态：进行中），节点名称即用户输入
        step_name = user_input_title[:200] if len(user_input_title) > 200 else user_input_title
        manus_init = {
            "title": step_name,
            "steps": [step_name],
            "step_files": {},
            "step_statuses": {step_name: "in_progress"},
            "step_notes": {step_name: ""},
            "step_details": {step_name: ""},
            "step_tool_calls": {step_name: []},
            "dependencies": {},
            "progress": {"total": 1, "completed": 0, "in_progress": 1, "blocked": 0, "not_started": 0},
            "result": "",
            "statusText": "正在执行..." if lang == "zh" else "Executing...",
        }
        await send_openclaw_and_replay({
            "topic": topic,
            "data": {
                "type": "lui-message-manus-step",
                "uuid": msg_uuid,
                "timestamp": get_timestamp(),
                "from": "ai",
                "source": "openclaw",
                "changeType": "replace",
                "initData": manus_init,
                "styles": {"width": "100%"},
            },
        })

        async def send_manus_completed(success: bool = True):
            """OpenClaw 消息发完后，将 DAG 节点状态更新为已完成"""
            completed_init = {
                "title": step_name,
                "steps": [step_name],
                "step_files": {},
                "step_statuses": {step_name: "completed"},
                "step_notes": {step_name: ""},
                "step_details": {step_name: ""},
                "step_tool_calls": {step_name: []},
                "dependencies": {},
                "progress": {"total": 1, "completed": 1, "in_progress": 0, "blocked": 0, "not_started": 0},
                "result": "",
                "statusText": "已完成" if (success and lang == "zh") else ("执行失败" if (not success and lang == "zh") else ("Completed" if success else "Failed")),
            }
            await send_openclaw_and_replay({
                "topic": topic,
                "data": {
                    "type": "lui-message-manus-step",
                    "uuid": msg_uuid,
                    "timestamp": get_timestamp(),
                    "from": "ai",
                    "source": "openclaw",
                    "changeType": "replace",
                    "initData": completed_init,
                    "styles": {"width": "100%"},
                },
            })

        # 生成OpenClaw会话键（格式：agent:main:<topic>）
        openclaw_session_key = f"agent:main:{topic}"
        
        # 发送消息到OpenClaw
        logger.info(f"转发消息到OpenClaw: sessionKey={openclaw_session_key}, message={user_message[:100]}...")
        
        try:
            response = await client.send_message(user_message, openclaw_session_key)
            logger.info(f"OpenClaw响应: {response}")
            
            # 如果有立即响应，也发送给前端
            if response.get("ok") and response.get("payload"):
                payload = response["payload"]

                # 兼容旧格式：payload 直接带 content 字段
                if "content" in payload:
                    await send_openclaw_and_replay({
                        "topic": topic,
                        "data": {
                            "type": "multi-modal",
                            "uuid": msg_uuid,
                            "timestamp": get_timestamp(),
                            "from": "ai",
                            "source": "openclaw",
                            "changeType": "replace",
                            "initData": [{"type": "text", "value": payload["content"]}],
                            "status": "finished"
                        }
                    })
                # 新格式：payload.messages 中包含完整对话历史
                elif isinstance(payload.get("messages"), list):
                    messages = payload.get("messages", [])
                    logger.info(f"从OpenClaw响应中提取AI回复，messages数量: {len(messages)}")
                    ai_reply = ""

                    # 查找最后一条 assistant 消息，并拼接其中的文本片段
                    for msg in reversed(messages):
                        if msg.get("role") != "assistant":
                            continue
                        content_items = msg.get("content", [])
                        text_parts = []
                        for item in content_items:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                # 清理 <final> 标签
                                import re
                                text = re.sub(r'<final>(.*?)</final>', r'\1', text, flags=re.DOTALL)
                                if text.strip():
                                    text_parts.append(text)
                        if text_parts:
                            ai_reply = "\n".join(text_parts).strip()
                            logger.info(f"从assistant消息中提取到AI回复，长度: {len(ai_reply)}, 前100字符: {ai_reply[:100]}")
                            break
                    
                    if not ai_reply:
                        logger.warning(f"未从messages中提取到AI回复，messages: {messages}")

                    if ai_reply:
                        await send_openclaw_and_replay({
                            "topic": topic,
                            "data": {
                                "type": "multi-modal",
                                "uuid": msg_uuid,
                                "timestamp": get_timestamp(),
                                "from": "ai",
                                "source": "openclaw",
                                "changeType": "replace",
                                "initData": [{"type": "text", "value": ai_reply}],
                                "status": "finished_successfully"
                            }
                        })
            
            # 等待chat final事件到达（最多120秒）
            try:
                await asyncio.wait_for(final_event.wait(), timeout=120.0)
                logger.info(f"✓ 收到chat final事件信号")
            except asyncio.TimeoutError:
                logger.warning(f"等待chat final事件超时（120秒）")
            
            # 在chat final事件后，等待片刻再调用chat.history
            if accumulated_text.get("need_history"):
                try:
                    logger.info(f"准备调用chat.history获取完整对话")
                    accumulated_text["need_history"] = False  # 清除标志
                    
                    # 等待一小段时间，确保OpenClaw Gateway完成消息存储
                    await asyncio.sleep(0.5)
                    
                    # 调用chat.history获取完整消息历史
                    history_response = await client.get_history(openclaw_session_key, limit=10)
                    logger.info(f"chat.history响应: ok={history_response.get('ok')}, payload_keys={list(history_response.get('payload', {}).keys())}")
                    
                    if history_response.get("ok") and history_response.get("payload"):
                        messages = history_response["payload"].get("messages", [])
                        logger.info(f"从历史中获取到 {len(messages)} 条消息，准备分段推送")
                        
                        # 分段推送完整对话历史（结构化模式）
                        import re
                        is_first_segment = True
                        segment_count = 0
                        
                        for idx, msg in enumerate(messages, 1):
                            role = msg.get("role", "unknown")
                            content_items = msg.get("content", [])
                            
                            # 处理每个 content item，每个单独发送
                            for item in content_items:
                                if not isinstance(item, dict):
                                    continue
                                    
                                item_type = item.get("type", "")
                                message_data = None
                                
                                if item_type == "text":
                                    text = item.get("text", "")
                                    # 清理 <final> 标签
                                    text = re.sub(r'<final>(.*?)</final>', r'\1', text, flags=re.DOTALL)
                                    if text.strip():
                                        message_data = {
                                            "messageType": "text",
                                            "role": role,
                                            "content": text.strip()
                                        }
                                
                                elif item_type == "thinking":
                                    thinking = item.get("thinking", "")
                                    if thinking.strip():
                                        message_data = {
                                            "messageType": "thinking",
                                            "role": role,
                                            "content": thinking.strip()
                                        }
                                
                                elif item_type == "toolCall":
                                    tool_name = item.get("name", "unknown")
                                    tool_args = item.get("arguments", {})
                                    message_data = {
                                        "messageType": "toolCall",
                                        "role": role,
                                        "toolName": tool_name,
                                        "arguments": tool_args
                                    }
                                
                                # 发送当前片段
                                if message_data:
                                    segment_count += 1
                                    change_type = "replace" if is_first_segment else "append"
                                    status = "streaming"  # 所有中间片段都是 streaming

                                    await send_openclaw_and_replay({
                                        "topic": topic,
                                        "data": {
                                            "type": "multi-modal",
                                            "uuid": msg_uuid,
                                            "timestamp": get_timestamp(),
                                            "from": "ai",
                                            "source": "openclaw",
                                            "changeType": change_type,
                                            "initData": [{"type": "text", "value": json.dumps(message_data, ensure_ascii=False)}],
                                            "status": status,
                                            "metadata": message_data  # 添加结构化元数据
                                        }
                                    })

                                    logger.info(f"已推送片段 #{segment_count}: messageType={message_data.get('messageType')}, role={role}")
                                    is_first_segment = False

                                    # 短暂延迟，模拟流式效果
                                    await asyncio.sleep(0.05)
                            
                            # 如果是 toolResult，单独发送
                            if role == "toolResult":
                                tool_name = msg.get("toolName", "unknown")
                                is_error = msg.get("isError", False)
                                tool_content_items = msg.get("content", [])
                                
                                # 提取 toolResult 的文本内容
                                result_text = ""
                                for item in tool_content_items:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        result_text = item.get("text", "")
                                        break
                                
                                message_data = {
                                    "messageType": "toolResult",
                                    "role": role,
                                    "toolName": tool_name,
                                    "isError": is_error,
                                    "content": result_text
                                }
                                
                                segment_count += 1
                                change_type = "replace" if is_first_segment else "append"
                                
                                await send_openclaw_and_replay({
                                    "topic": topic,
                                    "data": {
                                        "type": "multi-modal",
                                        "uuid": msg_uuid,
                                        "timestamp": get_timestamp(),
                                        "from": "ai",
                                        "source": "openclaw",
                                        "changeType": change_type,
                                        "initData": [{"type": "text", "value": json.dumps(message_data, ensure_ascii=False)}],
                                        "status": "streaming",
                                        "metadata": message_data
                                    }
                                })

                                logger.info(f"已推送片段 #{segment_count}: messageType=toolResult, toolName={tool_name}")
                                is_first_segment = False
                                await asyncio.sleep(0.05)
                        
                        # 发送最后一条完成消息
                        if segment_count > 0:
                            await send_openclaw_and_replay({
                                "topic": topic,
                                "data": {
                                    "type": "multi-modal",
                                    "uuid": msg_uuid,
                                    "timestamp": get_timestamp(),
                                    "from": "ai",
                                    "source": "openclaw",
                                    "changeType": "append",
                                    "initData": [{"type": "text", "value": ""}],
                                    "status": "finished_successfully",
                                    "metadata": {"messageType": "completion", "totalSegments": segment_count}
                                }
                            })

                        logger.info(f"✅ 完成分段推送，共 {segment_count} 个片段")
                except Exception as e:
                    logger.error(f"获取历史消息失败: {e}", exc_info=True)
            await send_manus_completed(True)

        except Exception as e:
            logger.error(f"发送消息到OpenClaw失败: {e}", exc_info=True)
            error_message = f"发送失败: {str(e)}" if lang == "zh" else f"Send failed: {str(e)}"

            await send_openclaw_and_replay({
                "topic": topic,
                "data": {
                    "type": "multi-modal",
                    "uuid": msg_uuid,
                    "timestamp": get_timestamp(),
                    "from": "ai",
                    "source": "openclaw",
                    "changeType": "replace",
                    "initData": [{"type": "text", "value": error_message}],
                    "status": "error"
                }
            })
            await send_manus_completed(False)

    except Exception as e:
        logger.error(f"处理OpenClaw消息异常: {e}", exc_info=True)
        error_message = f"处理异常: {str(e)}" if lang == "zh" else f"Processing error: {str(e)}"

        await send_openclaw_and_replay({
            "topic": topic,
            "data": {
                "type": "multi-modal",
                "uuid": msg_uuid,
                "timestamp": get_timestamp(),
                "from": "ai",
                "source": "openclaw",
                "changeType": "replace",
                "initData": [{"type": "text", "value": error_message}],
                "status": "error"
            }
        })
        await send_manus_completed(False)