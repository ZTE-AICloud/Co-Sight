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
import os
import threading
from typing import Any, Coroutine, Optional, TypeVar
from urllib.parse import quote, urlparse, urlunparse

from browser_use import Agent
from browser_use.browser import BrowserSession, BrowserProfile, ProxySettings
from browser_use.llm import ChatOpenAI

from app.common.logger_util import logger
from config.config import get_browser_model_config

_browser_loop: Optional[asyncio.AbstractEventLoop] = None
_browser_loop_thread: Optional[threading.Thread] = None
_browser_loop_ready = threading.Event()
_browser_loop_lock = threading.Lock()
_T = TypeVar("_T")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(
            "Invalid float value for %s=%s, falling back to %s",
            name,
            value,
            default,
        )
        return default


def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(
            "Invalid int value for %s=%s, falling back to %s",
            name,
            value,
            default,
        )
        return default


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    _browser_loop_ready.set()
    loop.run_forever()


def _ensure_browser_loop() -> asyncio.AbstractEventLoop:
    global _browser_loop, _browser_loop_thread
    if _browser_loop and _browser_loop.is_running():
        return _browser_loop

    with _browser_loop_lock:
        if _browser_loop and _browser_loop.is_running():
            return _browser_loop

        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_loop,
            name="WebToolkitBrowserLoop",
            args=(loop,),
            daemon=True,
        )
        thread.start()

        _browser_loop_ready.wait()
        _browser_loop_ready.clear()

        _browser_loop = loop
        _browser_loop_thread = thread

    return _browser_loop


def _run_in_browser_loop(coro: Coroutine[Any, Any, _T]) -> _T:
    loop = _ensure_browser_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


async def create_browser_session():
    # 获取共享的browser session
    logger.info("Creating new shared browser session for multi-agent use")
    user_data_dir = os.path.expanduser("~/.cosight/browser_profiles/shared")
    os.makedirs(user_data_dir, exist_ok=True)

    # 创建browser profile配置
    proxy_url = os.environ.get("BROWSER_PROXY_URL") or os.environ.get("PROXY_URL", "")
    proxy_user = os.environ.get("BROWSER_PROXY_USER")
    proxy_password = os.environ.get("BROWSER_PROXY_PASSWORD")
    proxy_settings: Optional[ProxySettings] = None
    if proxy_url:
        proxy_settings = ProxySettings(
            server=proxy_url,
            username=proxy_user,
            password=proxy_password,
            bypass=os.environ.get("BROWSER_PROXY_BYPASS", "localhost,127.0.0.1,*.internal"),
        )

    profile = BrowserProfile(
        # 核心配置：保持browser alive，支持多agent复用
        keep_alive=_env_bool("FORCE_KEEP_BROWSER_ALIVE", True),
        # 用户数据目录，保存cookies和认证信息
        user_data_dir=user_data_dir,
        # 代理配置
        proxy=proxy_settings,
        # 基本配置
        headless=_env_bool("HEADLESS", False),
        disable_security=_env_bool("DISABLE_SECURITY", False),
        # 等待时间配置
        minimum_wait_page_load_time=_env_float("MINIMUM_WAIT_PAGE_LOAD_TIME", 5.0),
        wait_for_network_idle_page_load_time=_env_float(
            "WAIT_FOR_NETWORK_IDLE_PAGE_LOAD_TIME", 5.0
        ),
        wait_between_actions=_env_float("WAIT_BETWEEN_ACTIONS", 3.0),
        # User Agent
        user_agent=os.environ.get(
            "USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        ),
        # AI Intergration
        highlight_elements=True,
        paint_order_filtering=True,
    )

    # 创建共享的browser session
    browser_session = BrowserSession(browser_profile=profile)

    # 启动browser session
    await browser_session.start()

    logger.info("Shared browser session created and started successfully")

    return browser_session


class WebToolkit:
    # 类级别的共享browser session，支持多agent复用
    _shared_browser_session: Optional[BrowserSession] = None
    _session_lock: Optional[asyncio.Lock] = None

    def __init__(self, llm_config=None):
        """
        初始化WebToolkit
        
        Args:
            llm_config: 可选的LLM配置，如果不提供则使用专门的浏览器自动化模型配置
        """
        if llm_config is None:
            # 使用专门的浏览器自动化模型配置
            self.llm_config: dict = get_browser_model_config()
            logger.info("使用专门的浏览器自动化模型配置")
        else:
            # 使用提供的配置
            self.llm_config: dict = llm_config
            logger.info("使用提供的LLM配置")
        
        self._llm: Optional[ChatOpenAI] = None

    @classmethod
    async def _get_shared_browser_session(cls) -> BrowserSession:
        if cls._shared_browser_session:
            return cls._shared_browser_session

        if cls._session_lock is None:
            cls._session_lock = asyncio.Lock()

        async with cls._session_lock:
            if cls._shared_browser_session:
                return cls._shared_browser_session

            cls._shared_browser_session = await create_browser_session()

        return cls._shared_browser_session

    @classmethod
    async def _reset_browser_session(cls) -> None:
        if cls._shared_browser_session:
            try:
                await cls._shared_browser_session.kill()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to close shared browser session during reset")
            finally:
                cls._shared_browser_session = None

    def browser_use(self, task_prompt: str):
        r"""A powerful toolkit which can simulate the browser interaction to solve the task which needs multi-step actions.

        This method now supports multi-agent browser session sharing, which means:
        - Multiple agents can share the same browser instance
        - User credentials (cookies, localStorage, sessionStorage) are preserved across agents
        - Browser remains alive between agent runs for better performance
        - Each agent gets its own tab/focus but shares the underlying browser process

        Args:
            task_prompt (str): The task prompt to solve.

        Returns:
            str: The simulation result to the task.
        """
        logger.info(f"start browser_use, task_prompt is {task_prompt}")
        try:
            return _run_in_browser_loop(self.inner_browser_use(task_prompt))
        except Exception as e:
            logger.error(f"browser_use error {str(e)}", exc_info=True)
            # 确保返回的是字符串而不是协程
            return f"browser_use error: {str(e)}"

    async def inner_browser_use(self, task_prompt):
        browser_session: Optional[BrowserSession] = None
        try:
            browser_session = await self._get_shared_browser_session()
            if self._llm is None:
                llm_kwargs = {**self.llm_config}
                llm_kwargs.setdefault("temperature", 0.0)
                llm_kwargs["add_schema_to_system_prompt"] = _env_bool(
                    "ADD_SCHEMA_TO_SYSTEM_PROMPT",
                    llm_kwargs.get("add_schema_to_system_prompt", True),
                )
                self._llm = ChatOpenAI(**llm_kwargs)
            # 创建agent，复用共享的browser session
            agent_kwargs: dict[str, Any] = dict(
                task=task_prompt,
                browser_session=browser_session,  # 使用共享的browser session
                llm=self._llm,
                use_vision=False,
                max_actions_per_step=1,
                directly_open_url=False,
                flash_mode=_env_bool("FLASH_MODE", True),
                extend_system_message="""
ADDITIONAL INSTRUCTIONS:
- Your answers **MUST NOT** contain any of the markdown code blocks such as ``` or ```json.
- **Directly** return the final answer as a plain text **without any additional formatting**.
""",
            )

            max_tokens_per_step = _env_int("MAX_TOKENS_PER_STEP")
            if max_tokens_per_step is not None:
                agent_kwargs["max_tokens_per_step"] = max_tokens_per_step

            agent = Agent(**agent_kwargs)

            # 运行agent
            result = await agent.run()
            final_result = result.final_result()
            logger.info("Task completed successfully with shared browser session")
            return final_result

        except Exception as e:
            logger.error(f"failed to use browser: {str(e)}", exc_info=True)
            if browser_session:
                await self._reset_browser_session()
            return f"fail, because: {str(e)}"
        # 注意：不要在这里关闭browser_session，因为它是共享的
        # browser session会通过keep_alive=True保持活跃，供后续agent复用