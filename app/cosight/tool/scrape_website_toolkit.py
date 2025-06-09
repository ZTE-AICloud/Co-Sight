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
import re
from typing import Any, Optional, Type
import requests
from bs4 import BeautifulSoup

from app.common.logger_util import logger


class ScrapeWebsiteTool:
    name: str = "Read website content"
    description: str = "A tool that can be used to read a website content."
    website_url: Optional[str] = None
    cookies: Optional[dict] = None

    def __init__(
            self,
            website_url: str,
            cookies: Optional[dict] = None
    ):
        proxy = os.environ.get("PROXY")
        self.proxies = {"http": proxy, "https": proxy} if proxy else None

        if website_url is not None:
            self.website_url = website_url
            self.description = (
                f"A tool that can be used to read {website_url}'s content."
            )
            if cookies is not None:
                self.cookies = {cookies["name"]: os.getenv(cookies["value"])}
        else:
            raise RuntimeError("website_url can not be null")
        self.headers: Optional[dict] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    async def _run(
            self,
            website_url: str,
    ) -> Any:
        page = requests.get(
            website_url,
            timeout=15,
            verify=False,
            headers=self.headers,
            cookies=self.cookies if self.cookies else {},
            proxies=self.proxies
        )

        page.encoding = page.apparent_encoding
        parsed = BeautifulSoup(page.text, "html.parser")

        text = parsed.get_text(" ")
        text = re.sub("[ \t]+", " ", text)
        text = re.sub("\\s+\n\\s+", "\n", text)
        return text


def fetch_website_content(website_url):
    try:
        if not is_valid_url(website_url):
            return f'current url is valid {website_url}'
        scrapeWebsiteTool = ScrapeWebsiteTool(website_url)
        logger.info(f'starting fetch {website_url} Content')
        # 检查是否在事件循环中
        try:
            loop = asyncio.get_running_loop()
            # 如果已经在事件循环中，创建新任务
            task = loop.create_task(scrapeWebsiteTool._run(website_url))
            return loop.run_until_complete(task)
        except RuntimeError:
            # 如果没有事件循环，创建新的
            loop = asyncio.new_event_loop()
            return loop.run_until_complete(scrapeWebsiteTool._run(website_url))
    except Exception as e:
        logger.error(f"fetch_website_content error {str(e)}", exc_info=True)
        # 确保返回的是字符串而不是协程
        return f"fetch_website_content error: {str(e)}"


from urllib.parse import urlparse
import requests


def is_valid_url(url: str) -> bool:
    return is_valid_pattern_url(url)


def is_valid_pattern_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False
