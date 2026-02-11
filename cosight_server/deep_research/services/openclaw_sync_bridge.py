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
同步调用桥：在子线程中通过主线程 event loop 调用 OpenClaw 异步客户端，
返回 send_message_and_get_history 的同步封装，供 CoSight/OpenclawAgent 使用。
"""

import asyncio
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, Optional

from cosight_server.deep_research.services.openclaw_client import openclaw_client_manager
from cosight_server.sdk.common.config import custom_config


def make_sync_openclaw_sender(
    loop: asyncio.AbstractEventLoop,
) -> Callable[[str, Optional[str]], Dict[str, Any]]:
    """
    返回一个同步可调用 sender(message, session_key=None) -> dict，在子线程中阻塞等待
    OpenClaw Gateway 的 send_message_and_get_history 结果。

    Args:
        loop: 主线程的 asyncio event loop（在 search 的 async 上下文中
              asyncio.get_running_loop() 获取）。

    Returns:
        同步函数 sender(message, session_key="main") -> dict：
        - session_key 未传或为 None 时使用 "main"；
        - 传入 plan_id 或 "cosight:{plan_id}" 可实现每个 plan 独立 session。
        - 成功时返回 chat.history 的完整响应（含 payload.messages）；
        - 未连接或失败时返回 {"ok": False, "error": {"message": "..."}}。
    """
    final_timeout = float(custom_config.get("openclaw_final_timeout", 120.0))
    history_delay = float(custom_config.get("openclaw_history_delay", 0.5))
    limit = int(custom_config.get("openclaw_history_limit", 10))
    # 子线程等待总超时略大于 final_timeout，避免过早超时
    result_timeout = final_timeout + 30.0

    async def _ensure_and_send(message: str, session_key: str = "main") -> Dict[str, Any]:
        await openclaw_client_manager.ensure_connected()
        if not openclaw_client_manager.is_connected():
            return {
                "ok": False,
                "error": {"message": "OpenClaw未连接"},
            }
        client = openclaw_client_manager.get_client()
        if not client:
            return {
                "ok": False,
                "error": {"message": "OpenClaw客户端不可用"},
            }
        return await client.send_message_and_get_history(
            message,
            session_key=session_key,
            limit=limit,
            final_timeout=final_timeout,
            history_delay=history_delay,
        )

    def sender(message: str, session_key: Optional[str] = None) -> Dict[str, Any]:
        key = session_key if session_key else "main"
        try:
            future = asyncio.run_coroutine_threadsafe(
                _ensure_and_send(message, key),
                loop,
            )
            return future.result(timeout=result_timeout)
        except (asyncio.TimeoutError, FuturesTimeoutError):
            return {
                "ok": False,
                "error": {"message": "OpenClaw 请求超时"},
            }
        except Exception as e:
            return {
                "ok": False,
                "error": {"message": str(e)},
            }

    return sender
