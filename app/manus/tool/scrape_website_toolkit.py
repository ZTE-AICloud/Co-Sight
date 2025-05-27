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

# -*- coding: utf-8 -*-
import asyncio
import os
import re
from typing import Any, Optional, Type
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from app.manus.gate.format_gate import format_check


class ScrapeWebsiteTool:
    name: str = "Read website content"
    description: str = "A tool that can be used to read a website content."
    website_url: Optional[str] = None
    cookies: Optional[dict] = None
    headers: Optional[dict] = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(
            self,
            website_url: str,
            cookies: Optional[dict] = None
    ):
        if website_url is not None:
            self.website_url = website_url
            self.description = (
                f"A tool that can be used to read {website_url}'s content."
            )
            if cookies is not None:
                self.cookies = {cookies["name"]: os.getenv(cookies["value"])}
        else:
            raise RuntimeError("website_url can not be null")

    async def _run(
            self,
            website_url: str,
    ) -> Any:
        page = requests.get(
            website_url,
            timeout=15,
            headers=self.headers,
            cookies=self.cookies if self.cookies else {},
        )

        page.encoding = page.apparent_encoding
        parsed = BeautifulSoup(page.text, "html.parser")

        text = parsed.get_text(" ")
        text = re.sub("[ \t]+", " ", text)
        text = re.sub("\\s+\n\\s+", "\n", text)
        return text


def is_document_url(url):
    path = urlparse(url).path.lower()
    return path.endswith('.pdf') or path.endswith('.doc') or path.endswith('.docx')

@format_check()
def fetch_website_content(website_url):
    if is_document_url(website_url):
        print(f'Please use the file download tool to get the contents of the file {website_url}')
        return "Please use the file download tool to get the contents of the file"
    scrapeWebsiteTool = ScrapeWebsiteTool(website_url)
    print(f'starting fetch {website_url} Content')
    return asyncio.run(scrapeWebsiteTool._run(website_url))


if __name__ == '__main__':
    fetch_website_content('http://13213/1231/12312/213.pdf')