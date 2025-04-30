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

from typing import List, Dict, Any

from googlesearch import search
from bs4 import BeautifulSoup
import random
import asyncio
import aiohttp

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
        

        timeout = aiohttp.ClientTimeout(total=10)
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
                    
    except asyncio.TimeoutError:
        return "Request timed out"
    except Exception as e:
        return f"Error fetching content: {str(e)}"

def search_google(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Use Google search engine to search information for the given query.

    Args:
        query (str): The query to be searched.
        max_results (int): Max number of results, defaults to `5`.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries where each dictionary
            represents a search result.
    """
    print(f"search google for {query}")
    responses: List[Dict[str, Any]] = []
    
    max_retries = 3
    for attempt in range(max_retries):
        try:

            links = list(search(query, num_results=max_results, proxy=proxy, advanced=True))
            
            # Create a new event loop for the current thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Format results and fetch content
            async def process_links():
                tasks = []
                for i, link in enumerate(links, start=1):
                    tasks.append((i, link, fetch_url_content(link.url)))
                # Run all fetch operations concurrently
                fetch_results = await asyncio.gather(*[task[2] for task in tasks])
                for idx, (i, link, _) in enumerate(tasks):
                    response = {
                        "result_id": i,
                        "title": link.title,
                        "description": link.description,
                        "url": link.url,
                        "content": fetch_results[idx]  # Add scraped content
                    }
                    responses.append(response)
            
            loop.run_until_complete(process_links())
            loop.close()
            break  # Success, exit retry loop
        except Exception as e:
            if attempt == max_retries - 1:  # Last attempt failed
                responses.append({"error": f"Google search failed after {max_retries} attempts: {e}"})
    # print(f"search google for {responses}")
    return responses


def main():
    # Test search query
    query = "中兴通讯"
    results = search_google(query)
    
    # Print results
    print("\nSearch Results:")
    for result in results:
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"{result}")

if __name__ == "__main__":
    main()
    # googleTrendsUrl = 'https://www.google.com/search'
    # response = requests.get(googleTrendsUrl)
    # if response.status_code == 200:
    #     g_cookies = response.cookies.get_dict()
    #     print(g_cookies)

