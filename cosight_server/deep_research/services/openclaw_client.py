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

"""
OpenClaw WebSocket客户端
实现与OpenClaw Gateway的WebSocket通信，支持JSON-RPC协议
"""

import asyncio
import json
import uuid
from typing import Optional, Dict, Callable, Any
from enum import Enum

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import WebSocketException

from app.common.logger_util import get_logger
from cosight_server.sdk.common.config import custom_config

logger = get_logger("openclaw_client")

# OpenClaw Gateway 协议版本（与 openclaw 仓库 PROTOCOL_VERSION 一致）
PROTOCOL_VERSION = 3
# WebChat 客户端 ID / mode（与 openclaw GATEWAY_CLIENT_IDS.WEBCHAT 一致）
GATEWAY_CLIENT_ID_WEBCHAT = "webchat"
GATEWAY_CLIENT_MODE_WEBCHAT = "webchat"


class ConnectionState(Enum):
    """连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class OpenClawClient:
    """
    OpenClaw WebSocket客户端
    负责与OpenClaw Gateway建立和维护WebSocket连接
    """

    def __init__(self, gateway_url: str, timeout: int = 30):
        """
        初始化OpenClaw客户端

        Args:
            gateway_url: OpenClaw Gateway的WebSocket地址
            timeout: 连接超时时间（秒）
        """
        self.gateway_url = gateway_url
        self.timeout = timeout
        self.ws: Optional[WebSocketClientProtocol] = None
        self.state = ConnectionState.DISCONNECTED
        
        # 请求管理
        self.pending_requests: Dict[str, asyncio.Future] = {}
        
        # 事件回调
        self.event_handlers: Dict[str, Callable] = {}
        
        # 后台任务
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        
        # 重连配置
        self.reconnect_interval = custom_config.get("openclaw_reconnect_interval", 5)
        self.max_retries = custom_config.get("openclaw_max_retries", 3)
        self.retry_count = 0
        
        # 连接锁
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> bool:
        """
        连接到OpenClaw Gateway

        Returns:
            bool: 连接是否成功
        """
        async with self._connect_lock:
            if self.state == ConnectionState.CONNECTED:
                logger.info("已经连接到OpenClaw Gateway")
                return True

            self.state = ConnectionState.CONNECTING
            logger.info(f"正在连接到OpenClaw Gateway: {self.gateway_url}")

            try:
                self.ws = await asyncio.wait_for(
                    websockets.connect(
                        self.gateway_url,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5
                    ),
                    timeout=self.timeout
                )
                # Gateway 建立连接后会先发 connect.challenge，再等客户端发 connect 请求
                first = await asyncio.wait_for(self.ws.recv(), timeout=self.timeout)
                first_data = json.loads(first)
                if (
                    first_data.get("type") == "event"
                    and first_data.get("event") == "connect.challenge"
                ):
                    logger.info("已收到 connect.challenge，发送完整 connect 请求")
                else:
                    logger.warning("未先收到 connect.challenge，继续发送 connect: %s", first_data)
                # 发送符合 Gateway ConnectParams 的完整 connect 请求（webchat 模式）
                # 获取认证token（从配置或环境变量）
                auth_token = custom_config.get("openclaw_auth_token")
                if not auth_token:
                    logger.warning("未配置 openclaw_auth_token，尝试使用匿名连接")
                
                connect_msg = {
                    "type": "req",
                    "id": str(uuid.uuid4()),
                    "method": "connect",
                    "params": {
                        "minProtocol": PROTOCOL_VERSION,
                        "maxProtocol": PROTOCOL_VERSION,
                        "client": {
                            "id": GATEWAY_CLIENT_ID_WEBCHAT,
                            "displayName": "Co-Sight",
                            "version": "1.0.0",
                            "platform": "linux",
                            "mode": GATEWAY_CLIENT_MODE_WEBCHAT,
                        },
                        "caps": [],
                    },
                }
                
                # 如果有token，添加到connect参数中
                if auth_token:
                    connect_msg["params"]["auth"] = {"token": auth_token}
                    logger.info("使用token进行认证连接")
                await self.ws.send(json.dumps(connect_msg))
                logger.info("已发送 connect 请求 (webchat)")
                # 等待 connect 响应（type=res, ok=true 表示成功，payload 为 hello-ok）
                response = await asyncio.wait_for(
                    self.ws.recv(),
                    timeout=self.timeout
                )
                resp_data = json.loads(response)
                if resp_data.get("type") == "res" and resp_data.get("ok"):
                    self.state = ConnectionState.CONNECTED
                    self.retry_count = 0
                    logger.info("成功连接到OpenClaw Gateway")
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    return True
                logger.error("连接OpenClaw Gateway失败: %s", resp_data)
                self.state = ConnectionState.DISCONNECTED
                return False
                    
            except asyncio.TimeoutError:
                logger.error(f"连接OpenClaw Gateway超时: {self.gateway_url}")
                self.state = ConnectionState.DISCONNECTED
                return False
            except Exception as e:
                logger.error(f"连接OpenClaw Gateway异常: {e}", exc_info=True)
                self.state = ConnectionState.DISCONNECTED
                return False

    async def disconnect(self):
        """断开连接"""
        logger.info("正在断开OpenClaw Gateway连接")
        self.state = ConnectionState.DISCONNECTED
        
        # 取消后台任务
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # 关闭WebSocket连接
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.error(f"关闭WebSocket连接异常: {e}")
            finally:
                self.ws = None
        
        # 清理待处理的请求
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(Exception("连接已关闭"))
        self.pending_requests.clear()
        
        logger.info("已断开OpenClaw Gateway连接")

    async def send_message(self, message: str, session_key: str = "main") -> Dict[str, Any]:
        """
        发送消息到OpenClaw (使用OpenClaw内部格式)

        Args:
            message: 用户消息内容
            session_key: 会话键（默认"main"）

        Returns:
            Dict: OpenClaw的响应
        """
        if self.state != ConnectionState.CONNECTED:
            raise Exception("未连接到OpenClaw Gateway")

        request_id = str(uuid.uuid4())
        # 使用OpenClaw内部格式（非JSON-RPC）
        request = {
            "type": "req",
            "id": request_id,
            "method": "chat.send",
            "params": {
                "sessionKey": session_key,
                "message": message,
                "idempotencyKey": str(uuid.uuid4()),  # 幂等性键，防止重复
                "deliver": False,  # 不自动发送到外部渠道
            }
        }
        
        # 创建Future等待响应
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            # 发送请求
            await self.ws.send(json.dumps(request))
            logger.info(f"已发送消息到OpenClaw: request_id={request_id}, message={message[:50]}...")
            
            # 等待响应（带超时）
            response = await asyncio.wait_for(future, timeout=self.timeout)
            return response
            
        except asyncio.TimeoutError:
            logger.error(f"发送消息超时: request_id={request_id}")
            raise
        finally:
            # 清理
            self.pending_requests.pop(request_id, None)

    async def get_history(self, session_key: str = "main", limit: int = 2) -> Dict[str, Any]:
        """
        获取会话历史

        Args:
            session_key: 会话键
            limit: 获取的消息数量限制

        Returns:
            Dict: 包含messages数组的响应
        """
        if self.state != ConnectionState.CONNECTED:
            raise Exception("未连接到OpenClaw Gateway")

        request_id = str(uuid.uuid4())
        request = {
            "type": "req",
            "id": request_id,
            "method": "chat.history",
            "params": {
                "sessionKey": session_key,
                "limit": limit
            }
        }
        
        # 创建Future等待响应
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            # 发送请求
            await self.ws.send(json.dumps(request))
            logger.info(f"已请求会话历史: session_key={session_key}, limit={limit}")
            
            # 等待响应（带超时）
            response = await asyncio.wait_for(future, timeout=self.timeout)
            return response
            
        except asyncio.TimeoutError:
            logger.error(f"获取历史超时: request_id={request_id}")
            raise
        finally:
            # 清理
            self.pending_requests.pop(request_id, None)

    def register_event_handler(self, event_type: str, handler: Callable):
        """
        注册事件处理器

        Args:
            event_type: 事件类型
            handler: 事件处理函数
        """
        self.event_handlers[event_type] = handler
        logger.info(f"已注册事件处理器: {event_type}")

    async def _receive_loop(self):
        """接收消息循环"""
        logger.info("启动OpenClaw消息接收循环")
        try:
            while self.state == ConnectionState.CONNECTED and self.ws:
                try:
                    message = await self.ws.recv()
                    await self._handle_message(message)
                except WebSocketException as e:
                    logger.error(f"WebSocket接收异常: {e}")
                    break
                except Exception as e:
                    logger.error(f"处理消息异常: {e}", exc_info=True)
        finally:
            logger.info("OpenClaw消息接收循环结束")
            # 触发重连
            if self.state == ConnectionState.CONNECTED:
                asyncio.create_task(self._reconnect())

    async def _handle_message(self, message: str):
        """
        处理接收到的消息（支持JSON-RPC 2.0和旧格式）

        Args:
            message: JSON格式的消息
        """
        try:
            data = json.loads(message)
            
            # JSON-RPC 2.0格式（优先检查）
            if "jsonrpc" in data:
                request_id = data.get("id")
                if request_id and request_id in self.pending_requests:
                    future = self.pending_requests[request_id]
                    if not future.done():
                        if "result" in data:
                            # 成功响应
                            future.set_result(data["result"])
                            logger.info(f"收到JSON-RPC响应: request_id={request_id}")
                        elif "error" in data:
                            # 错误响应
                            error_info = data["error"]
                            error_msg = error_info.get("message", "Unknown error")
                            future.set_exception(Exception(f"OpenClaw error: {error_msg}"))
                            logger.error(f"OpenClaw返回错误: {error_info}")
            
            # OpenClaw内部格式
            else:
                msg_type = data.get("type")
                
                if msg_type == "res":
                    # 响应消息
                    request_id = data.get("id")
                    if request_id in self.pending_requests:
                        future = self.pending_requests[request_id]
                        if not future.done():
                            if data.get("ok"):
                                # 返回整个响应对象（包含payload）
                                future.set_result(data)
                                logger.info(f"收到OpenClaw响应: request_id={request_id}, ok=true")
                            else:
                                error = data.get("error", {})
                                error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                                future.set_exception(Exception(error))
                                logger.error(f"OpenClaw返回错误: request_id={request_id}, error={error_msg}")
                                
                elif msg_type == "event":
                    # 事件消息
                    event_type = data.get("event")
                    payload = data.get("payload", {})
                    logger.info(f"收到OpenClaw事件: type={event_type}, payload_keys={list(payload.keys())}")
                    if event_type in self.event_handlers:
                        handler = self.event_handlers[event_type]
                        await handler(data)
                    else:
                        logger.debug(f"未处理的事件: {event_type}")
                    
        except json.JSONDecodeError as e:
            logger.error(f"解析消息失败: {e}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}", exc_info=True)

    async def _heartbeat_loop(self):
        """心跳循环"""
        logger.info("启动OpenClaw心跳循环")
        try:
            while self.state == ConnectionState.CONNECTED and self.ws:
                await asyncio.sleep(30)  # 每30秒发送一次心跳
                try:
                    # WebSocket的ping/pong由websockets库自动处理
                    # 这里只是确保连接活跃
                    if self.ws and not getattr(self.ws, 'closed', True):
                        await self.ws.ping()
                except Exception as e:
                    logger.error(f"心跳发送失败: {e}")
                    break
        finally:
            logger.info("OpenClaw心跳循环结束")

    async def _reconnect(self):
        """自动重连"""
        if self.state == ConnectionState.RECONNECTING:
            return
        
        self.state = ConnectionState.RECONNECTING
        
        while self.retry_count < self.max_retries:
            self.retry_count += 1
            wait_time = self.reconnect_interval * self.retry_count
            logger.info(f"尝试重连OpenClaw Gateway (第{self.retry_count}次，{wait_time}秒后)")
            
            await asyncio.sleep(wait_time)
            
            if await self.connect():
                logger.info("重连OpenClaw Gateway成功")
                return
        
        logger.error(f"重连OpenClaw Gateway失败，已达到最大重试次数: {self.max_retries}")
        self.state = ConnectionState.DISCONNECTED


class OpenClawClientManager:
    """
    OpenClaw客户端管理器
    管理OpenClawClient的生命周期
    """

    def __init__(self):
        self.client: Optional[OpenClawClient] = None
        self._started = False

    async def start(self):
        """启动OpenClaw客户端"""
        if self._started and self.client is not None and self.client.state == ConnectionState.CONNECTED:
            logger.warning("OpenClaw客户端已经启动且已连接")
            return

        # 若曾启动但已断开，先清理再重连
        if self._started and self.client is not None:
            await self.client.disconnect()
            self.client = None
        self._started = False

        gateway_url = custom_config.get("openclaw_gateway_url")
        timeout = custom_config.get("openclaw_timeout", 30)
        
        logger.info(f"启动OpenClaw客户端: {gateway_url}")
        
        self.client = OpenClawClient(gateway_url, timeout)
        success = await self.client.connect()
        
        if success:
            self._started = True
            logger.info("OpenClaw客户端启动成功")
        else:
            logger.error("OpenClaw客户端启动失败")
            self.client = None

    async def stop(self):
        """停止OpenClaw客户端"""
        if not self._started:
            return

        logger.info("停止OpenClaw客户端")
        
        if self.client:
            await self.client.disconnect()
            self.client = None
        
        self._started = False
        logger.info("OpenClaw客户端已停止")

    def get_client(self) -> Optional[OpenClawClient]:
        """获取OpenClaw客户端实例"""
        return self.client

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return (
            self._started
            and self.client is not None
            and self.client.state == ConnectionState.CONNECTED
        )

    async def ensure_connected(self) -> bool:
        """
        若已启用 OpenClaw 但未连接，则尝试连接（用于 Gateway 晚于 Co-Sight 启动的场景）。
        返回当前是否已连接。
        """
        if not custom_config.get("openclaw_enabled"):
            return False
        if self.is_connected():
            return True
        await self.start()
        return self.is_connected()


# 全局OpenClaw客户端管理器实例
openclaw_client_manager = OpenClawClientManager()
