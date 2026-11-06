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

import json
import uuid
from typing import List, Optional

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.config import custom_config
from app.common.logger_util import get_logger
from cosight_server.sdk.common.utils import get_timestamp

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
                message = json.loads(data.get("data"))
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
                    "initData": resp.get("content"),
                    "promptSentences": resp.get("promptSentences") or [],
                    "roleInfo": resp.get("roleInfo"),
                    "extra": resp.get("extra")
                }
            }, websocket)
