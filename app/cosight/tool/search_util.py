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
from app.common.logger_util import logger
from .scrape_website_toolkit import is_valid_url

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
        async with aiohttp.ClientSession(timeout=timeout) as session:
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
        query: str
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
            results = search(query)
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
