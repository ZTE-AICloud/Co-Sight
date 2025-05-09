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
from typing import List

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.config import custom_config
from cosight_server.sdk.common.logger_util import logger
from cosight_server.sdk.common.utils import get_timestamp

wsRouter = APIRouter()


class WebsocketManager:
    def __init__(self):
        # 存放激活的ws连接对象
        self.active_clients: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        # 等待连接
        await ws.accept()
        # 存储ws连接对象
        self.active_clients.append(ws)
        logger.info(f"ws connect >>>>>>>>>>>>>> ")

    def disconnect(self, ws: WebSocket):
        # 关闭时 移除ws对象
        self.active_clients.remove(ws)

    @staticmethod
    async def send_message(message: str, ws: WebSocket):
        # 发送个人消息
        await ws.send_text(message)

    @staticmethod
    async def send_json(data: dict, ws: WebSocket):
        # 发送个人消息
        await ws.send_json(data)

    async def broadcast(self, message: str):
        # 广播消息
        for client in self.active_clients:
            await client.send_text(message)


manager = WebsocketManager()


@wsRouter.websocket("/robot/wss/messages")
async def websocket_handler(
        websocket: WebSocket,
        websocket_client_key: str = Query(..., alias="websocket-client-key"),
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
            if data.get("action") == "message":
                message = json.loads(data.get("data"))
                logger.info(f"message >>>>>>>>>>>>>> {message}")

                # 推送时间更新的消息给前端
                await manager.send_json({
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
                
                # 发送结束的控制消息
                await manager.send_json({
                    "topic": data.get("topic"),
                    "data": {
                        "type": "control-status-message",
                        "initData": {
                            "status": "finished_successfully"
                        }
                    }
                }, websocket)

                
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
    timeout = aiohttp.ClientTimeout(sock_read=300)
    sessionInfo =params.get('sessionInfo', {})
    sessionInfo['messageSerialNumber'] = msg_uuid
    params['sessionInfo'] = sessionInfo
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url=url, json=params, headers=headers) as response:
            async for line in response.content:
                decoded_line = line.decode('utf-8')
                # print(f"====websocket_manager _stream_handler: {decoded_line}")
                try:
                    line_json = json.loads(decoded_line)
                except json.JSONDecodeError:
                    # logger.error(f"loads json for [{decoded_line}] error: {e}")
                    continue
                msg_type = line_json.get("contentType") if line_json.get("contentType") is not None else "multi-modal"
                init_data = line_json.get("content") if line_json.get("content") is not None else [
                    {"type": "text", "value": i18n.t('unknown_message')}]
                change_type = line_json.get("changeType") if line_json.get("changeType") is not None else "append"
                await manager.send_json({
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

