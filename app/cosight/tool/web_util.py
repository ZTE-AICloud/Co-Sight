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
import traceback
import os
from browser_use import Agent
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from langchain_openai import ChatOpenAI
from browser_use.browser.context import BrowserContextConfig
from browser_use import BrowserConfig
from app.common.logger_util import logger


class WebToolkit:
    def __init__(self, llm_config):
        self.llm_config = llm_config

    def browser_use(self, task_prompt: str):
        r"""A powerful toolkit which can simulate the browser interaction to solve the task which needs multi-step actions.

        Args:
            task_prompt (str): The task prompt to solve.

        Returns:
            str: The simulation result to the task.
        """
        logger.info(f"start browser_use, task_prompt is {task_prompt}")
        try:
            # 检查是否在事件循环中
            try:
                loop = asyncio.get_running_loop()
                # 如果已经在事件循环中，创建新任务
                task = loop.create_task(self.inner_browser_use(task_prompt))
                return loop.run_until_complete(task)
            except RuntimeError:
                # 如果没有事件循环，创建新的
                loop = asyncio.new_event_loop()
                return loop.run_until_complete(self.inner_browser_use(task_prompt))
        except Exception as e:
            logger.error(f"browser_use error {str(e)}", exc_info=True)
            # 确保返回的是字符串而不是协程
            return f"browser_use error: {str(e)}"

    async def inner_browser_use(self, task_prompt):
        browser = None
        try:
            browser = Browser(
                config=BrowserConfig(
                    headless=os.environ.get('HEADLESS', False),
                    disable_security=os.environ.get('DISABLE_SECURITY', False),
                    _force_keep_browser_alive=os.environ.get('FORCE_KEEP_BROWSER_ALIVE', False),
                    new_context_config=BrowserContextConfig(
                        minimum_wait_page_load_time=os.environ.get('MINIMUM_WAIT_PAGE_LOAD_TIME', 5.0),
                        wait_for_network_idle_page_load_time=os.environ.get('WAIT_FOR_NETWORK_IDLE_PAGE_LOAD_TIME',
                                                                            5.0),
                        wait_between_actions=os.environ.get('WAIT_BETWEEN_ACTIONS', 3.0),
                        user_agent=os.environ.get('USER_AGENT',
                                                  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36')
                    ),
                ))
            agent = Agent(
                task=task_prompt,
                browser=browser,
                llm=ChatOpenAI(**self.llm_config),
                use_vision=False,
            )
            results = await agent.run()
            return results.final_result()

        except Exception as e:
            logger.error(f"failed to use browser: {str(e)}", exc_info=True)
            return "fail, because:{}".format(e)
        finally:
            await browser.close()
