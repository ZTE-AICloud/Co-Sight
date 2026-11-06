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
            return f'current url is not valid: {website_url}'
        
        # 检查URL是否指向PDF文件
        if website_url.lower().endswith('.pdf') or _is_pdf_url(website_url):
            logger.info(f'Detected PDF URL: {website_url}, using PDF parser instead')
            return _fetch_pdf_content(website_url)
        
        # 对于普通网页，使用原有的抓取逻辑
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


from urllib.parse import urlparse, urljoin
import requests
import json
import tempfile


def _is_pdf_url(url: str) -> bool:
    """检查URL是否指向PDF文件
    
    检查方法：
    1. URL以.pdf结尾
    2. 发送HEAD请求检查Content-Type
    """
    try:
        # 方法1：检查URL扩展名
        if url.lower().endswith('.pdf'):
            return True
        
        # 方法2：检查Content-Type
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
        content_type = response.headers.get('Content-Type', '').lower()
        
        if 'application/pdf' in content_type:
            logger.info(f'URL {url} is PDF (Content-Type: {content_type})')
            return True
        
        return False
    except Exception as e:
        logger.debug(f'Error checking if URL is PDF: {e}')
        return False


def _is_valid_extracted_text(text: str) -> bool:
    """检测提取的文本是否有效（不是字形编码）"""
    if not text or len(text) < 10:
        return False
    
    # 检查是否包含大量字形编码（如/G21, /G22, /GFF）
    glyph_pattern = r'/G[0-9A-Fa-f]{2,4}'
    glyph_matches = re.findall(glyph_pattern, text)
    glyph_count = len(glyph_matches)
    
    # 计算总词数
    total_words = len(text.split())
    
    # 如果字形编码超过5%，认为提取失败
    if total_words > 0 and glyph_count > total_words * 0.05:
        logger.warning(f"Detected {glyph_count} glyph codes, text extraction failed")
        return False
    
    # 检查可读字符比例
    readable_chars = sum(1 for c in text if c.isalnum() or c in '，。！？,.!? \n\t')
    if len(text) > 0 and readable_chars < len(text) * 0.3:
        return False
    
    return True


def _fetch_pdf_content(pdf_url: str) -> str:
    """使用PDF解析器提取PDF内容
    
    Args:
        pdf_url: PDF文件的URL
        
    Returns:
        提取的文本内容
    """
    import io
    
    logger.info(f'Fetching PDF content from: {pdf_url}')
    
    # 下载PDF文件
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(pdf_url, headers=headers, timeout=30)
        response.raise_for_status()
        pdf_data = response.content
    except Exception as e:
        return f"PDF下载失败: {str(e)}。URL: {pdf_url}"
    
    # 方法1：pdfplumber（推荐，准确性最好）
    try:
        import pdfplumber
        logger.info("Using pdfplumber for PDF extraction")
        
        pdf_file = io.BytesIO(pdf_data)
        extracted_text = ""
        
        with pdfplumber.open(pdf_file) as pdf:
            total_pages = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    extracted_text += f"\n\n=== 第 {page_num}/{total_pages} 页 ===\n\n"
                    extracted_text += page_text
        
        if extracted_text.strip() and _is_valid_extracted_text(extracted_text):
            logger.info(f'pdfplumber成功提取 {len(extracted_text)} 字符')
            return f"PDF内容提取成功（pdfplumber，共{total_pages}页）：\n{extracted_text}"
    except ImportError:
        logger.debug("pdfplumber未安装，尝试下一个方法")
    except Exception as e:
        logger.warning(f"pdfplumber提取失败: {e}")
    
    # 方法2：PyMuPDF/fitz（最强大）
    try:
        import fitz
        logger.info("Using PyMuPDF for PDF extraction")
        
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        extracted_text = ""
        total_pages = len(doc)
        
        for page_num in range(total_pages):
            page_text = doc[page_num].get_text()
            if page_text.strip():
                extracted_text += f"\n\n=== 第 {page_num+1}/{total_pages} 页 ===\n\n"
                extracted_text += page_text
        
        doc.close()
        
        if extracted_text.strip() and _is_valid_extracted_text(extracted_text):
            logger.info(f'PyMuPDF成功提取 {len(extracted_text)} 字符')
            return f"PDF内容提取成功（PyMuPDF，共{total_pages}页）：\n{extracted_text}"
    except ImportError:
        logger.debug("PyMuPDF未安装，尝试下一个方法")
    except Exception as e:
        logger.warning(f"PyMuPDF提取失败: {e}")
    
    # 方法3：pypdf（基础，可能有编码问题）
    try:
        from pypdf import PdfReader
        logger.info("Using pypdf for PDF extraction")
        
        pdf_file = io.BytesIO(pdf_data)
        reader = PdfReader(pdf_file)
        extracted_text = ""
        total_pages = len(reader.pages)
        
        for page_num, page in enumerate(reader.pages, 1):
            page_text = page.extract_text()
            if page_text.strip():
                extracted_text += f"\n\n=== 第 {page_num}/{total_pages} 页 ===\n\n"
                extracted_text += page_text
        
        if extracted_text.strip():
            if _is_valid_extracted_text(extracted_text):
                logger.info(f'pypdf成功提取 {len(extracted_text)} 字符')
                return f"PDF内容提取成功（pypdf，共{total_pages}页）：\n{extracted_text}"
            else:
                logger.warning("pypdf提取的文本包含字形编码，质量较差")
                return f"PDF解析失败：此PDF使用了特殊字体编码（如/G21等字形ID），无法正确解析。\n建议：1. 安装更强大的库：uv pip install pdfplumber PyMuPDF\n2. 或使用其他PDF来源\nURL: {pdf_url}"
    except ImportError:
        return f"错误：未安装PDF解析库。请安装：uv pip install pdfplumber PyMuPDF。URL: {pdf_url}"
    except Exception as e:
        logger.error(f'pypdf提取失败: {e}', exc_info=True)
    
    # 所有方法都失败
    return f"PDF内容提取失败：尝试了多种解析方法都无法成功。此PDF可能是扫描版、加密或使用了特殊编码。URL: {pdf_url}"


def is_valid_url(url: str) -> bool:
    return is_valid_pattern_url(url)


def is_valid_pattern_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def fetch_website_content_with_images(website_url):
    """
    获取网页内容并提取图片信息
    
    Args:
        website_url (str): 要抓取的网站URL
        
    Returns:
        dict: 包含文本内容和图片信息的字典
        {
            "text_content": "网页文本内容",
            "images": [
                {
                    "src": "图片URL",
                    "alt": "图片描述",
                    "title": "图片标题",
                    "width": "宽度",
                    "height": "高度"
                }
            ],
            "background_images": ["背景图片URL列表"],
            "total_images": "图片总数"
        }
    """
    try:
        if not is_valid_url(website_url):
            return {
                "error": f"Invalid URL: {website_url}",
                "text_content": "",
                "images": [],
                "background_images": [],
                "total_images": 0
            }
        
        scrapeWebsiteTool = ScrapeWebsiteTool(website_url)
        logger.info(f'Starting fetch {website_url} content with images')
        
        # 获取网页HTML内容
        page = requests.get(
            website_url,
            timeout=15,
            verify=False,
            headers=scrapeWebsiteTool.headers,
            cookies=scrapeWebsiteTool.cookies if scrapeWebsiteTool.cookies else {},
            proxies=scrapeWebsiteTool.proxies
        )
        
        page.encoding = page.apparent_encoding
        parsed = BeautifulSoup(page.text, "html.parser")
        
        # 获取文本内容（保持原有功能）
        text = parsed.get_text(" ")
        text = re.sub("[ \t]+", " ", text)
        text = re.sub("\\s+\n\\s+", "\n", text)
        
        # 提取图片信息
        images = []
        img_tags = parsed.find_all('img')
        
        for img in img_tags:
            img_info = {
                "src": img.get('src', ''),
                "alt": img.get('alt', ''),
                "title": img.get('title', ''),
                "width": img.get('width', ''),
                "height": img.get('height', ''),
                "class": img.get('class', []),
                "id": img.get('id', '')
            }
            
            # 处理相对URL
            if img_info["src"] and not img_info["src"].startswith(('http://', 'https://', 'data:')):
                img_info["src"] = urljoin(website_url, img_info["src"])
            
            images.append(img_info)
        
        # 提取CSS背景图片
        background_images = []
        style_tags = parsed.find_all('style')
        
        for style in style_tags:
            if style.string:
                # 查找background-image属性
                bg_matches = re.findall(r'background-image:\s*url\(["\']?([^"\']+)["\']?\)', style.string)
                for bg_url in bg_matches:
                    if not bg_url.startswith(('http://', 'https://', 'data:')):
                        bg_url = urljoin(website_url, bg_url)
                    background_images.append(bg_url)
        
        # 查找内联样式的背景图片
        elements_with_bg = parsed.find_all(attrs={"style": re.compile(r"background-image")})
        for element in elements_with_bg:
            style_attr = element.get('style', '')
            bg_matches = re.findall(r'background-image:\s*url\(["\']?([^"\']+)["\']?\)', style_attr)
            for bg_url in bg_matches:
                if not bg_url.startswith(('http://', 'https://', 'data:')):
                    bg_url = urljoin(website_url, bg_url)
                background_images.append(bg_url)
        
        result = {
            "text_content": text,
            "images": images,
            "background_images": list(set(background_images)),  # 去重
            "total_images": len(images) + len(set(background_images)),
            "url": website_url,
            "status": "success"
        }
        
        logger.info(f'Successfully fetched {website_url} with {len(images)} img tags and {len(set(background_images))} background images')
        return result
        
    except Exception as e:
        logger.error(f"fetch_website_content_with_images error {str(e)}", exc_info=True)
        return {
            "error": f"fetch_website_content_with_images error: {str(e)}",
            "text_content": "",
            "images": [],
            "background_images": [],
            "total_images": 0,
            "url": website_url,
            "status": "error"
        }


def fetch_website_images_only(website_url):
    """
    仅获取网页中的图片信息，不返回文本内容
    
    Args:
        website_url (str): 要抓取的网站URL
        
    Returns:
        dict: 仅包含图片信息的字典
    """
    try:
        result = fetch_website_content_with_images(website_url)
        
        # 只返回图片相关信息
        return {
            "images": result.get("images", []),
            "background_images": result.get("background_images", []),
            "total_images": result.get("total_images", 0),
            "url": result.get("url", website_url),
            "status": result.get("status", "error")
        }
        
    except Exception as e:
        logger.error(f"fetch_website_images_only error {str(e)}", exc_info=True)
        return {
            "error": f"fetch_website_images_only error: {str(e)}",
            "images": [],
            "background_images": [],
            "total_images": 0,
            "url": website_url,
            "status": "error"
        }
