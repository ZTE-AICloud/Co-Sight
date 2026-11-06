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

from baidusearch.baidusearch import search
from requests.exceptions import RequestException
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import random
import asyncio
import aiohttp
import os
import ssl
import urllib3
import requests
from app.common.logger_util import logger
from .scrape_website_toolkit import is_valid_url

# 禁用 requests 中的 InsecureRequestWarning（仅在显式关闭 verify 时才会触发）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _build_ssl_context_for_fetch() -> ssl.SSLContext | None:
    """
    为异步抓取构建 SSL 上下文。

    设计原则（开源安全注意事项）：
    - 默认行为：严格校验证书（相比修改系统 CA，更推荐用户在系统层正确安装证书）
    - 可选配置：
        - FETCH_CA_FILE: 指定自定义 CA 证书文件路径，用于公司代理 / 私有 CA 场景
        - FETCH_SSL_VERIFY=false: 仅在本地/内网调试时临时关闭 SSL 校验（不推荐生产环境使用）
    - 返回值：
        - None：交给 aiohttp 使用默认 SSL 行为（等价于严格校验）
        - SSLContext：按 env 配置生成的上下文
    """
    # 是否显式关闭 SSL 校验（默认不关闭）
    verify_flag = os.environ.get("FETCH_SSL_VERIFY", "").strip().lower()
    if verify_flag in ("0", "false", "no", "off"):
        # 仅用于调试环境：完全关闭证书校验
        logger.warning(
            "FETCH_SSL_VERIFY is set to false: SSL certificate verification is DISABLED for fetch_url_content. "
            "This is unsafe and NOT recommended for production environments."
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    # 如需信任自定义 CA（常见于公司代理或自签名证书场景）
    ca_file = os.environ.get("FETCH_CA_FILE", "").strip()
    if ca_file:
        try:
            ctx = ssl.create_default_context(cafile=ca_file)
            logger.info(f"Using custom CA file for fetch_url_content: {ca_file}")
            return ctx
        except Exception as e:
            logger.error(f"Failed to load custom CA file '{ca_file}', fallback to default SSL context: {e}")
            # 失败则退回默认行为

    # 返回 None，交由 aiohttp 使用默认 SSL 行为（严格校验）
    return None


def _resolve_baidu_redirect(session: requests.Session, url: str, timeout: int = 8) -> str:
    """
    将百度的跳转链接(http[s]://www.baidu.com/link?url=...)解析为真实目标URL。
    若解析失败，则返回原始URL。
    """
    try:
        if not url or 'baidu.com/link?url=' not in url:
            return url

        # 使用GET以兼容部分站点对HEAD的限制；仅获取重定向最终地址
        resp = session.get(url, allow_redirects=True, timeout=timeout, verify=False)
        final_url = resp.url or url

        # 避免仍然是百度的中转链接
        if 'baidu.com/link?url=' in final_url:
            return url
        return final_url
    except Exception:
        return url

def search_baidu_with_ssl_fix(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """
    修复SSL问题的百度搜索函数
    由于百度反爬虫机制，返回模拟搜索结果
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        # 创建不验证SSL的session
        session = requests.Session()
        session.verify = False
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        session.headers.update(headers)
        
        # 构建搜索URL
        search_url = f"https://www.baidu.com/s?ie=utf-8&tn=baidu&wd={query}"
        
        logger.info(f"Searching Baidu with URL: {search_url}")
        response = session.get(search_url, timeout=10)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            logger.error(f"Baidu search failed with status code: {response.status_code}")
            return []
        
        
        # 解析搜索结果
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # 直接查找搜索结果链接 (h3 a 是百度搜索结果的标准结构)
        result_links = soup.select('h3 a')
        logger.info(f"Found {len(result_links)} result links")
        
        for i, link in enumerate(result_links[:num_results], 1):
            try:
                title = link.get_text(strip=True)
                url = link.get('href', '')
                
                # 跳过无效的链接
                if not title or not url or len(title) < 2:
                    continue
                
                # 处理百度重定向链接为真实目标URL
                if url.startswith('http://www.baidu.com/link?url=') or url.startswith('https://www.baidu.com/link?url='):
                    url = _resolve_baidu_redirect(session, url)
                elif not url.startswith('http'):
                    # 相对链接，跳过
                    continue
                
                # 查找描述信息 - 在链接的父容器中查找
                parent = link.parent
                description = ""
                if parent:
                    # 查找描述文本
                    desc_selectors = [
                        'span[class*="content"]',
                        'div[class*="abstract"]', 
                        'div[class*="desc"]',
                        'span[class*="desc"]'
                    ]
                    for selector in desc_selectors:
                        desc_elem = parent.find(selector)
                        if desc_elem:
                            description = desc_elem.get_text(strip=True)
                            break
                    
                    # 如果没有找到专门的描述元素，尝试获取父容器的文本
                    if not description:
                        parent_text = parent.get_text(strip=True)
                        # 移除标题，获取剩余文本作为描述
                        if parent_text.startswith(title):
                            description = parent_text[len(title):].strip()
                        else:
                            description = parent_text
                
                # 清理描述文本
                if description:
                    description = description.replace('\n', ' ').replace('\t', ' ')
                    # 限制描述长度
                    if len(description) > 200:
                        description = description[:200] + "..."
                
                results.append({
                    'title': title,
                    'url': url,
                    'abstract': description
                })
                
                logger.info(f"Parsed result {i}: {title[:50]}... -> {url[:120]}...")
                    
            except Exception as e:
                logger.warning(f"Error parsing result item {i}: {e}")
                continue
        

        
        logger.info(f"Successfully parsed {len(results)} results from Baidu")
        return results
    except Exception as e:
        logger.error(f"Baidu search parse error: {e}", exc_info=True)
        return []


async def fetch_url_content(url: str) -> str:
    """Fetch and parse content from a given URL"""
    try:
        headers = {
            'User-Agent': random.choice([
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0'
            ]),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive'
        }
        proxy = os.environ.get("PROXY")
        if not is_valid_url(url):
            return f'current url is valid {url}'
        timeout = aiohttp.ClientTimeout(total=180)

        # 根据开源安全规范构建 SSL 上下文：
        # - 默认严格校验证书
        # - 支持通过环境变量配置自定义 CA 或在开发环境下关闭校验
        ssl_ctx = _build_ssl_context_for_fetch()
        connector = aiohttp.TCPConnector(ssl=ssl_ctx) if ssl_ctx is not None else None

        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url, headers=headers, proxy=proxy) as response:
                if response.status == 200:
                    # Check content type
                    content_type = response.headers.get('Content-Type', '')
                    if 'text/html' not in content_type:
                        return f"Non-HTML content: {content_type}"

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Remove unwanted elements
                    for element in soup(["script", "style", "nav", "footer", "iframe", "noscript"]):
                        element.decompose()

                    # Get clean text
                    text = soup.get_text(separator='\n')
                    # Clean up extra whitespace
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text = '\n'.join(chunk for chunk in chunks if chunk)

                    return text
                else:
                    return f"HTTP Error: {response.status}"
    except asyncio.TimeoutError as e:
        logger.error(f"Request timed out: {str(e)}", exc_info=True)
        return "Request timed out"
    except Exception as e:
        logger.error(f"Error fetching content: {str(e)}", exc_info=True)
        return f"Error fetching content: {str(e)}"


def search_baidu(
        query: str, max_results: int = 5
) -> List[Dict[str, Any]]:
    logger.info(f'starting search content {query} use baidu')
    """Use Baidu search engine to search information for the given query.

    This function queries the Baidu API for related topics to the given search term.
    The results are formatted into a list of dictionaries, each representing a search result.

    Args:
        query (str): The query to be searched.
        max_results (int): Max number of results, defaults to `5`.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries where each dictionary
            represents a search result.
    """
    logger.info(f"search baidu for {query}")
    responses: List[Dict[str, Any]] = []
    max_retries = 3

    for attempt in range(max_retries):
        try:
            # 使用SSL修复版本的搜索函数
            results = search_baidu_with_ssl_fix(query, max_results)
            # Limit results to max_results
            results = results

            # Create a new event loop for the current thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def process_results():
                tasks = []
                for i, result in enumerate(results, start=1):
                    url = result.get("url", "")
                    tasks.append((i, result, fetch_url_content(url)))
                # Run all fetch operations concurrently
                fetch_results = await asyncio.gather(*[task[2] for task in tasks])
                for idx, (i, result, _) in enumerate(tasks):
                    response = {
                        "result_id": i,
                        "title": result.get("title", ""),
                        "description": result.get("abstract", ""),
                        "url": result.get("url", ""),
                        "content": fetch_results[idx]  # Add scraped content
                    }
                    responses.append(response)

            loop.run_until_complete(process_results())
            loop.close()
            break  # Success, exit retry loop
        except Exception as e:
            logger.error(f'raise error: {str(e)}', exc_info=True)
            if attempt == max_retries - 1:  # Last attempt failed
                responses.append({"error": f"Baidu search failed after {max_retries} attempts: {e}"})
            continue
    logger.info(f"search baidu for response: {responses}")
    return responses
