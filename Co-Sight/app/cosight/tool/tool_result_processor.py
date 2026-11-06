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

import re
import json
import time
import os
import requests
from typing import Any, Dict, Optional, List
from app.common.logger_util import logger




class ToolResultProcessor:
    """工具结果处理器，针对不同工具类型处理结果"""
    
    # 可配置的域名过滤列表（通过环境变量 IFRAME_BLOCKED_DOMAINS 设置，逗号分隔）
    # 例如: export IFRAME_BLOCKED_DOMAINS="ainvest.com,example.com"
    _cached_blocked_domains = None
    
    @staticmethod
    def _get_blocked_domains() -> list:
        """
        获取配置的不可嵌入域名列表
        支持通过环境变量 IFRAME_BLOCKED_DOMAINS 配置（逗号分隔）
        
        Returns:
            list: 域名列表
        """
        if ToolResultProcessor._cached_blocked_domains is not None:
            return ToolResultProcessor._cached_blocked_domains
            
        # 从环境变量读取
        blocked_domains_str = os.environ.get('IFRAME_BLOCKED_DOMAINS', '')
        if blocked_domains_str:
            domains = [d.strip().lower() for d in blocked_domains_str.split(',') if d.strip()]
            ToolResultProcessor._cached_blocked_domains = domains
            logger.info(f"从环境变量加载iframe黑名单域名: {domains}")
        else:
            ToolResultProcessor._cached_blocked_domains = []
            
        return ToolResultProcessor._cached_blocked_domains
    
    @staticmethod
    def _is_domain_blocked(url: str) -> bool:
        """
        检查URL的域名是否在配置的黑名单中
        
        Args:
            url: 要检查的URL
            
        Returns:
            bool: 如果在黑名单中返回True
        """
        blocked_domains = ToolResultProcessor._get_blocked_domains()
        if not blocked_domains:
            return False
            
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            # 移除 www. 前缀进行匹配
            domain_without_www = domain.replace('www.', '')
            
            for blocked_domain in blocked_domains:
                if domain_without_www == blocked_domain or domain_without_www.endswith('.' + blocked_domain):
                    logger.info(f"URL {url} 的域名 {domain} 在配置的iframe黑名单中")
                    return True
            return False
        except Exception as e:
            logger.warning(f"检查域名黑名单时出错: {e}")
            return False
    
    @staticmethod
    def _detect_language_from_content(content: str) -> str:
        """
        根据内容检测语言类型
        
        Args:
            content: 要检测的内容
            
        Returns:
            str: 'zh' 表示中文，'en' 表示英文
        """
        if not content or not isinstance(content, str):
            return 'zh'  # 默认中文
        
        # 统计中文字符数量（包括中文标点）
        chinese_chars = len([c for c in content if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f'])
        
        # 统计英文字符数量（只统计纯英文单词，排除中文中的英文字母）
        import re
        # 使用正则表达式匹配英文单词
        english_words = re.findall(r'\b[a-zA-Z]+\b', content)
        english_chars = sum(len(word) for word in english_words)
        
        # 调试信息
        logger.debug(f"Language detection - Content: '{content}', Chinese chars: {chinese_chars}, English chars: {english_chars}")
        
        # 如果中文字符数量大于英文字符数量，判断为中文
        if chinese_chars > english_chars:
            return 'zh'
        elif english_chars > 0:
            return 'en'
        else:
            return 'zh'  # 默认中文
    
    @staticmethod
    def _get_localized_summary(chinese_summary: str, english_summary: str, task_content: str = "") -> str:
        """
        根据任务内容判断语言并返回对应的summary内容
        
        Args:
            chinese_summary: 中文摘要
            english_summary: 英文摘要
            task_content: 任务内容，用于判断语言
            
        Returns:
            str: 根据任务内容语言返回对应的摘要
        """
        try:
            # 根据任务内容检测语言
            detected_language = ToolResultProcessor._detect_language_from_content(task_content)
            
            if detected_language == 'en':
                return english_summary
            else:
                return chinese_summary
        except Exception:
            # 如果检测失败，默认返回中文
            return chinese_summary
    
    @staticmethod
    def batch_check_embeddable(urls: List[str], max_check: int = 10) -> Dict[str, bool]:
        """
        批量检查多个URL的iframe可嵌入性
        
        Args:
            urls: 要检查的URL列表
            max_check: 最大检查数量，避免过多请求
            
        Returns:
            Dict[str, bool]: URL到可嵌入性的映射
        """
        results = {}
        urls_to_check = urls[:max_check]
        
        for url in urls_to_check:
            results[url] = ToolResultProcessor.check_embeddable(url)
        
        # 对于未检查的URL，默认认为可以嵌入
        for url in urls[max_check:]:
            results[url] = True
            
        return results
    
    @staticmethod
    def check_embeddable(url: str) -> bool:
        """
        检查给定URL是否可以在电脑区正常打开和嵌入
        通过实际HTTP请求检测URL的可访问性和iframe嵌入能力
        
        检测策略：
        1. 检查域名是否在配置的黑名单中（可选，通过环境变量配置）
        2. 发送HTTP请求检查可访问性
        3. 分析HTTP响应头（X-Frame-Options, CSP等）
        4. 检测内容类型和大小
        5. 对于HTML页面，尝试检测JavaScript反iframe模式
        
        Args:
            url: 要检查的URL
            
        Returns:
            bool: 如果可以正常打开并嵌入返回True，否则返回False
        """
        # 1. 检查域名是否在配置的黑名单中（可通过环境变量 IFRAME_BLOCKED_DOMAINS 配置）
        if ToolResultProcessor._is_domain_blocked(url):
            return False
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # 获取代理配置
            proxies = None
            proxy_url = os.environ.get("BROWSER_PROXY_URL") or os.environ.get("PROXY_URL")
            if proxy_url:
                proxies = {
                    "http": proxy_url,
                    "https": proxy_url
                }
            
            response = None
            # 先尝试HEAD请求，如果失败再尝试GET请求（只获取少量数据）
            try:
                # 发送HEAD请求检查URL的可访问性和HTTP头，缩短超时时间到8秒
                response = requests.head(url, headers=headers, timeout=8, allow_redirects=True, 
                                       verify=False, proxies=proxies)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                logger.info(f"URL {url} HEAD请求失败 ({type(e).__name__})，尝试GET请求")
                # HEAD请求失败，尝试GET请求（只获取前1KB数据）
                try:
                    response = requests.get(url, headers=headers, timeout=8, allow_redirects=True, 
                                          verify=False, proxies=proxies, stream=True)
                    # 只读取少量数据
                    response.raw.read(1024, decode_content=True)
                except Exception as get_error:
                    logger.warning(f"URL {url} GET请求也失败: {get_error}")
                    return False
            
            if response is None:
                logger.warning(f"URL {url} 无法获取响应")
                return False
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                logger.info(f"URL {url} 返回错误状态码 {response.status_code}，无法访问")
                return False
            
            # 头信息不区分大小写，所以将键转换为小写
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            
            # 1. 检查Content-Type - 非HTML内容不适合iframe嵌入
            content_type = response_headers.get('content-type', '').lower()
            if content_type:
                if 'application/pdf' in content_type:
                    logger.info(f"URL {url} 是PDF文件，不适合iframe嵌入")
                    return False
                if 'application/' in content_type and 'text/html' not in content_type:
                    logger.info(f"URL {url} 的Content-Type不是HTML: {content_type}，不适合iframe嵌入")
                    return False
                if 'image/' in content_type:
                    logger.info(f"URL {url} 是图片文件，不适合iframe嵌入")
                    return False
            
            # 2. 检查 X-Frame-Options 头 - 明确禁止嵌入
            x_frame_options = response_headers.get('x-frame-options', '').lower()
            if x_frame_options in ('deny', 'sameorigin'):
                logger.info(f"URL {url} 设置了 X-Frame-Options: {x_frame_options}，禁止iframe嵌入")
                return False
            
            # 3. 检查 Content-Security-Policy 头中的 frame-ancestors
            csp = response_headers.get('content-security-policy', '').lower()
            if 'frame-ancestors' in csp:
                if "'none'" in csp:
                    logger.info(f"URL {url} 设置了 CSP frame-ancestors: none，禁止iframe嵌入")
                    return False
                if "'self'" in csp:
                    logger.info(f"URL {url} 设置了 CSP frame-ancestors: self，禁止iframe嵌入")
                    return False
                # 如果没有通配符，也认为不允许跨域嵌入
                if '*' not in csp:
                    logger.info(f"URL {url} 的 CSP frame-ancestors 不包含通配符，禁止iframe嵌入")
                    return False
            
            # 4. 检查响应大小 - 过大的内容不适合iframe
            content_length = response_headers.get('content-length')
            if content_length:
                try:
                    size_mb = int(content_length) / (1024 * 1024)
                    if size_mb > 50:  # 超过50MB认为过大
                        logger.info(f"URL {url} 内容过大 ({size_mb:.1f}MB)，不适合iframe嵌入")
                        return False
                except (ValueError, TypeError):
                    pass
            
            # 5. 检查是否是可访问的HTML页面
            if 'text/html' in content_type or not content_type:
                # 对于HTML页面，尝试获取部分内容检测JavaScript反iframe代码
                html_content = None
                try:
                    # 如果之前是HEAD请求，需要重新发送GET请求获取内容
                    if response.request.method == 'HEAD':
                        get_response = requests.get(url, headers=headers, timeout=8, allow_redirects=True,
                                                   verify=False, proxies=proxies, stream=True)
                        # 只读取前5KB内容用于检测
                        html_content = get_response.raw.read(5120, decode_content=True).decode('utf-8', errors='ignore')
                        get_response.close()
                    else:
                        # 如果之前是GET请求，尝试读取已有内容
                        try:
                            html_content = response.content[:5120].decode('utf-8', errors='ignore')
                        except Exception:
                            pass
                    
                    # 检测常见的JavaScript反iframe模式
                    if html_content:
                        # 常见的反iframe JavaScript模式
                        anti_iframe_patterns = [
                            'top.location != self.location',
                            'top.location !== self.location', 
                            'top != self',
                            'top !== self',
                            'top.location.href != self.location.href',
                            'top.location.href !== self.location.href',
                            'window.top !== window.self',
                            'window.top != window.self',
                            'parent.frames.length > 0',
                            'parent.frames.length',
                            'frameElement',
                            'if (window.top != window.self)',
                            'if (window.top !== window.self)',
                            'if(top!=self)',
                            'if(top!==self)',
                        ]
                        
                        # 检查是否包含反iframe代码
                        anti_iframe_detected = False
                        for pattern in anti_iframe_patterns:
                            if pattern.lower() in html_content.lower():
                                logger.info(f"URL {url} 检测到JavaScript反iframe代码: {pattern}")
                                anti_iframe_detected = True
                                break
                        
                        if anti_iframe_detected:
                            return False
                            
                except Exception as e:
                    # 内容检测失败不影响结果，使用保守策略
                    logger.debug(f"URL {url} 内容检测失败: {e}")
                    pass
                
                logger.info(f"URL {url} 是可访问的HTML页面，允许iframe嵌入")
                return True
            else:
                logger.info(f"URL {url} 不是HTML页面 (Content-Type: {content_type})，不适合iframe嵌入")
                return False
                
        except requests.exceptions.Timeout:
            logger.warning(f"URL {url} 请求超时，无法访问")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"URL {url} 连接失败，无法访问: {e}")
            return False
        except requests.exceptions.TooManyRedirects:
            logger.warning(f"URL {url} 重定向次数过多，无法访问")
            return False
        except requests.exceptions.SSLError as e:
            logger.warning(f"URL {url} SSL错误，无法访问: {e}")
            return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"URL {url} 请求失败: {e}")
            return False
        except Exception as e:
            logger.error(f"检查URL '{url}' 嵌入状态时发生意外错误: {e}")
            return False
    
    @staticmethod
    def _generate_search_results_page_url(tool_name: str, tool_args: str, search_results: list = None) -> str:
        """
        生成可嵌入的搜索结果展示页面URL
        
        Args:
            tool_name: 搜索工具名称
            tool_args: 工具参数，包含查询内容
            search_results: 搜索结果列表
            
        Returns:
            str: 可嵌入的搜索结果展示页面URL
        """
        try:
            # 从tool_args中提取查询内容
            query = ""
            if tool_args:
                try:
                    # 尝试解析JSON格式的tool_args
                    parsed_args = json.loads(tool_args)
                    if isinstance(parsed_args, dict):
                        # 尝试多种可能的查询参数key
                        for key in ['query', 'q', 'search', 'keyword', 'text', 'entity']:
                            if key in parsed_args:
                                query = str(parsed_args[key])
                                break
                except json.JSONDecodeError:
                    # 如果不是JSON格式，直接使用tool_args作为查询内容
                    query = tool_args
            
            # 如果仍然没有查询内容，使用默认值
            if not query:
                query = "搜索结果"
            
            # URL编码查询内容
            import urllib.parse
            encoded_query = urllib.parse.quote(query)
            
            # 生成搜索结果展示页面的URL
            # 使用我们自己的API端点来展示搜索结果
            base_url = "/api/nae-deep-research/v1/search-results"
            params = {
                'query': encoded_query,
                'tool': tool_name,
                'timestamp': str(int(time.time() * 1000))  # 添加时间戳避免缓存
            }
            
            # 构建查询参数
            param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
            return f"{base_url}?{param_str}"
                
        except Exception as e:
            logger.error(f"生成搜索结果页面URL时出错: {e}")
            # 出错时返回一个默认的搜索结果页面
            return "/api/nae-deep-research/v1/search-results?query=搜索结果&tool=default"
    
    @staticmethod
    def _to_frontend_url(path_value: str) -> str:
        """将包含 work_space 的本地绝对路径改写为前端可访问的 URL。

        规则：
        - 仅当路径中包含 "work_space" 时改写（兼容 work_space/ 和 work_space_ 格式）
        - 如果文件名没有前缀文件夹，自动补上当前工作空间路径
        - 使用配置项 base_api_url，缺省为 "/api/nae-deep-research/v1"
        - 仅对文件名进行 URL 编码，目录保持原样
        """
        try:
            if not isinstance(path_value, str) or len(path_value) == 0:
                return path_value

            normalized = path_value.replace("\\", "/")
            
            # 查找 work_space 标记，支持 work_space/ 和 work_space_ 两种格式
            marker = "work_space"
            idx = normalized.find(marker)
            
            # 如果没有找到work_space标记，检查是否是纯文件名
            if idx == -1:
                # 检查是否是纯文件名（不包含路径分隔符）
                if "/" not in normalized and "\\" not in normalized:
                    # 获取当前工作空间路径
                    try:
                        current_workspace = os.environ.get('WORKSPACE_PATH')
                        if current_workspace:
                            # 构建完整路径
                            full_path = os.path.join(current_workspace, normalized).replace("\\", "/")
                            # 重新查找work_space标记
                            idx = full_path.find(marker)
                            if idx != -1:
                                normalized = full_path
                            else:
                                return path_value
                        else:
                            return path_value
                    except Exception:
                        return path_value
                else:
                    return path_value

            relative = normalized[idx:]

            # 读取配置前缀
            try:
                from cosight_server.sdk.common.config import custom_config
                base_url = str(custom_config.get("base_api_url"))
            except Exception:
                base_url = ""

            if not base_url:
                base_url = "/api/nae-deep-research/v1"
            base_url = base_url.rstrip("/")

            # 仅对文件名编码
            parts = relative.split("/")
            if len(parts) >= 2 and parts[-1]:
                parts[-1] = parts[-1]
                relative = "/".join(parts)

            return f"{base_url}/{relative}"
        except Exception:
            return path_value

    @staticmethod
    def process_tool_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """
        根据工具类型处理结果
        
        Args:
            tool_name: 工具名称
            tool_args: 工具参数
            tool_result: 工具原始结果
            task_title: 任务标题，用于语言检测
            
        Returns:
            处理后的结果字典
        """
        try:
            # 根据工具名称精确匹配选择处理方式
            if tool_name in ['search_baidu', 'search_google', 'search_wiki', 'tavily_search', 'image_search']:
                return ToolResultProcessor._process_search_result(tool_name, tool_args, tool_result, task_title)
            elif tool_name == 'execute_code':
                return ToolResultProcessor._process_code_result(tool_name, tool_args, tool_result, task_title)
            elif tool_name in ['file_saver', 'file_read', 'file_str_replace', 'file_find_in_content','create_html_report']:
                return ToolResultProcessor._process_file_result(tool_name, tool_args, tool_result, task_title)
            elif tool_name == 'browser_use':
                return ToolResultProcessor._process_web_result(tool_name, tool_args, tool_result, task_title)
            elif tool_name == 'fetch_website_content':
                return ToolResultProcessor._process_website_content_result(tool_name, tool_args, tool_result, task_title)
            elif tool_name in ['ask_question_about_image', 'ask_question_about_video']:
                return ToolResultProcessor._process_image_result(tool_name, tool_args, tool_result, task_title)
            else:
                return ToolResultProcessor._process_default_result(tool_name, tool_args, tool_result, task_title)
        except Exception as e:
            logger.error(f"Error processing tool result for {tool_name}: {e}")
            return ToolResultProcessor._process_default_result(tool_name, tool_args, tool_result)
    
    @staticmethod
    def _process_search_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理搜索结果"""
        try:
            # 首先尝试解析为JSON（适用于tavily等结构化结果）
            parsed_result = None
            try:
                if isinstance(tool_result, str):
                    parsed_result = json.loads(tool_result)
                else:
                    parsed_result = tool_result
            except (json.JSONDecodeError, TypeError):
                parsed_result = None
            
            urls = []
            result_count = 0
            
            if parsed_result and isinstance(parsed_result, dict):
                # 处理结构化搜索结果（如tavily）
                if 'results' in parsed_result and isinstance(parsed_result['results'], list):
                    results = parsed_result['results']
                    result_count = len(results)
                    for result in results:
                        if isinstance(result, dict) and 'url' in result:
                            urls.append(result['url'])
                elif 'result_id' in parsed_result:
                    # 兼容其他格式
                    result_count = 1
                    if 'url' in parsed_result:
                        urls.append(parsed_result['url'])
            else:
                # 处理字符串格式的搜索结果（兼容旧格式）
                # 方法1: 从 'url': 'xxx' 格式中提取
                url_pattern1 = r"'url':\s*'([^']+)'"
                matches1 = re.findall(url_pattern1, tool_result)
                urls.extend(matches1)
                
                # 方法2: 从 "url": "xxx" 格式中提取
                url_pattern2 = r'"url":\s*"([^"]+)"'
                matches2 = re.findall(url_pattern2, tool_result)
                urls.extend(matches2)
                
                # 方法3: 从 href 属性中提取
                href_pattern = r'href=["\']([^"\']+)["\']'
                href_matches = re.findall(href_pattern, tool_result)
                urls.extend([url for url in href_matches if url.startswith('http')])
                
                # 方法4: 直接匹配HTTP/HTTPS链接
                http_pattern = r'https?://[^\s\'"<>]+'
                http_matches = re.findall(http_pattern, tool_result)
                urls.extend(http_matches)
                
                # 方法5: 专门处理维基搜索的URL格式 "Wikipedia URL: https://..."
                if tool_name == 'search_wiki':
                    wiki_url_pattern = r'Wikipedia URL:\s*(https?://[^\s\n]+)'
                    wiki_matches = re.findall(wiki_url_pattern, tool_result)
                    urls.extend(wiki_matches)
                
                # 尝试提取结果数量
                result_count = len(re.findall(r"'result_id':\s*\d+", tool_result))
            
            # 去重并保持顺序
            seen = set()
            unique_urls = []
            for url in urls:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            # 限制URL数量，避免过多
            unique_urls = unique_urls[:20]
            
            # 批量检查URL的iframe可嵌入性（限制检查数量以提高性能）
            try:
                embeddable_results = ToolResultProcessor.batch_check_embeddable(unique_urls, max_check=10)
                
                embeddable_urls = []
                non_embeddable_urls = []
                
                for url, is_embeddable in embeddable_results.items():
                    if is_embeddable:
                        embeddable_urls.append(url)
                    else:
                        non_embeddable_urls.append(url)
                        
            except Exception as e:
                logger.error(f"批量检查URL iframe可嵌入性时出错: {e}")
                # 如果批量检查失败，所有URL默认认为可以嵌入
                embeddable_urls = unique_urls.copy()
                non_embeddable_urls = []
            
            # 如果之前没有找到result_id，使用去重后的URL数量
            if result_count == 0:
                result_count = len(unique_urls)
            
            # 确定first_url
            first_url = None
            if embeddable_urls:
                first_url = embeddable_urls[0]
            else:
                # 如果embeddable_urls为空，生成可嵌入的搜索结果展示页面URL
                first_url = ToolResultProcessor._generate_search_results_page_url(tool_name, tool_args, unique_urls)
            
            return {
                "tool_type": "search",
                "summary": ToolResultProcessor._get_localized_summary(
                    f"搜索完成，找到 {result_count} 个结果，其中 {len(embeddable_urls)} 个可在电脑区浏览",
                    f"Search completed, found {result_count} results, {len(embeddable_urls)} can be browsed in desktop area",
                    task_title
                ),
                "first_url": first_url,
                "urls": unique_urls,  # 所有URL列表
                "embeddable_urls": embeddable_urls,  # 可嵌入iframe的URL列表
                "non_embeddable_urls": non_embeddable_urls,  # 不可嵌入iframe的URL列表
                "result_count": result_count,
                "embeddable_count": len(embeddable_urls),
                "non_embeddable_count": len(non_embeddable_urls),
                "has_content": "Error fetching content" not in str(tool_result)
            }
        except Exception as e:
            logger.error(f"Error processing search result: {e}")
            return {
                "tool_type": "search",
                "summary": ToolResultProcessor._get_localized_summary(
                    "搜索完成",
                    "Search completed",
                    task_title
                ),
                "error": str(e)
            }
    
    @staticmethod
    def _process_code_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理代码执行结果"""
        try:
            # 提取代码内容
            code_content = tool_args if tool_args else "无代码内容"
            
            # 判断执行是否成功
            is_success = "error" not in tool_result.lower() and "exception" not in tool_result.lower()
            
            # 提取输出长度
            output_length = len(tool_result)
            
            return {
                "tool_type": "code_execution",
                "summary": ToolResultProcessor._get_localized_summary(
                    f"代码执行{'成功' if is_success else '失败'}",
                    f"Code execution {'successful' if is_success else 'failed'}",
                    task_title
                ),
                "code_content": code_content[:200] + "..." if len(code_content) > 200 else code_content,
                "output_length": output_length,
                "is_success": is_success
            }
        except Exception as e:
            logger.error(f"Error processing code result: {e}")
            return {
                "tool_type": "code_execution",
                "summary": ToolResultProcessor._get_localized_summary(
                    "代码执行完成",
                    "Code execution completed",
                    task_title
                ),
                "error": str(e)
            }
    
    @staticmethod
    def _process_file_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理文件操作结果"""
        try:
            # 解析tool_args中的JSON数据
            file_path = "未知文件"
            parsed_args = {}
            
            if tool_args:
                try:
                    # 尝试解析JSON格式的tool_args
                    parsed_args = json.loads(tool_args)
                    if isinstance(parsed_args, dict):
                        # 尝试多种可能的文件名key
                        for key in ['file_path', 'file', 'filename', 'file_name']:
                            if key in parsed_args:
                                file_path = parsed_args[key]
                                break
                except json.JSONDecodeError:
                    # 如果不是JSON格式，直接使用tool_args作为文件路径
                    file_path = tool_args

            # 将本地路径改写为前端URL
            file_path = ToolResultProcessor._to_frontend_url(file_path)
            
            # 判断操作类型并生成摘要
            if 'read' in tool_name.lower():
                operation = "读取"
                content_length = len(tool_result)
                summary = ToolResultProcessor._get_localized_summary(
                    f"文件读取完成，内容长度: {content_length} 字符",
                    f"File read completed, content length: {len(tool_result)} characters",
                    task_title
                )
            elif 'save' in tool_name.lower() or 'write' in tool_name.lower():
                operation = "保存"
                summary = ToolResultProcessor._get_localized_summary(
                    "文件保存完成",
                    "File save completed",
                    task_title
                )
            else:
                operation = "文件操作"
                summary = ToolResultProcessor._get_localized_summary(
                    "文件操作完成",
                    "File operation completed",
                    task_title
                )
            
            return {
                "tool_type": "file_operation",
                "summary": summary,
                "operation": operation,
                "file_path": file_path,
                "content_length": len(tool_result) if 'read' in tool_name.lower() else None
            }
        except Exception as e:
            logger.error(f"Error processing file result: {e}")
            return {
                "tool_type": "file_operation",
                "summary": ToolResultProcessor._get_localized_summary(
                    "文件操作完成",
                    "File operation completed",
                    task_title
                ),
                "error": str(e)
            }
    
    @staticmethod
    def _process_web_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理网页操作结果"""
        try:
            # 提取URL
            url_pattern = r"https?://[^\s]+"
            url_match = re.search(url_pattern, tool_args)
            url = url_match.group(0) if url_match else "未知URL"
            
            # 判断操作类型并生成摘要
            if 'fetch' in tool_name.lower():
                operation = "网页抓取"
                content_length = len(tool_result)
                summary = ToolResultProcessor._get_localized_summary(
                    f"网页抓取完成，内容长度: {content_length} 字符",
                    f"Web scraping completed, content length: {len(tool_result)} characters",
                    task_title
                )
            else:
                operation = "网页操作"
                summary = ToolResultProcessor._get_localized_summary(
                    "网页操作完成",
                    "Web operation completed",
                    task_title
                )
            
            return {
                "tool_type": "web_operation",
                "summary": summary,
                "operation": operation,
                "url": url,
                "content_length": len(tool_result)
            }
        except Exception as e:
            logger.error(f"Error processing web result: {e}")
            return {
                "tool_type": "web_operation",
                "summary": ToolResultProcessor._get_localized_summary(
                    "网页操作完成",
                    "Web operation completed",
                    task_title
                ),
                "error": str(e)
            }
    
    @staticmethod
    def _process_website_content_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理网站内容抓取结果"""
        try:
            # 提取URL
            url = "未知URL"
            if tool_args:
                try:
                    # 尝试解析JSON格式的tool_args
                    parsed_args = json.loads(tool_args)
                    if isinstance(parsed_args, dict) and 'website_url' in parsed_args:
                        url = parsed_args['website_url']
                except json.JSONDecodeError:
                    # 如果不是JSON格式，直接使用tool_args作为URL
                    url = tool_args
            
            # # 检查是否有错误
            is_error =  "fetch_website_content error" in tool_result
            
            # 计算内容长度
            content_length = len(tool_result)
            
            # 提取内容摘要（前200个字符）
            content_preview = tool_result[:200] + "..." if len(tool_result) > 200 else tool_result
            
            # 统计行数和段落数
            lines = tool_result.split('\n')
            line_count = len([line for line in lines if line.strip()])
            paragraph_count = len([p for p in tool_result.split('\n\n') if p.strip()])
            
            # 提取可能的标题（以大写字母开头且长度适中的行）
            potential_titles = []
            for line in lines[:10]:  # 只检查前10行
                line = line.strip()
                if (len(line) > 10 and len(line) < 100 and 
                    line[0].isupper() and not line.endswith('.') and 
                    not line.startswith('http')):
                    potential_titles.append(line)
            
            # 生成摘要
            chinese_summary = f"网站内容抓取{'成功' if not is_error else '失败'}，内容长度: {content_length} 字符"
            english_summary = f"Website content scraping {'successful' if not is_error else 'failed'}, content length: {content_length} characters"
            
            if is_error:
                chinese_summary += f"，错误信息: {tool_result}"
                english_summary += f", error: {tool_result}"
            
            summary = ToolResultProcessor._get_localized_summary(chinese_summary, english_summary, task_title)
            
            return {
                "tool_type": "website_content",
                "summary": summary,
                "operation": "网站内容抓取",
                "url": url,
                "content_length": content_length,
                "line_count": line_count,
                "paragraph_count": paragraph_count,
                "content_preview": content_preview,
                "potential_titles": potential_titles[:3],  # 最多返回3个可能的标题
                "is_success": not is_error,
                "has_content": content_length > 0 and not is_error
            }
        except Exception as e:
            logger.error(f"Error processing website content result: {e}")
            return {
                "tool_type": "website_content",
                "summary": ToolResultProcessor._get_localized_summary(
                    "网站内容抓取完成",
                    "Website content scraping completed",
                    task_title
                ),
                "operation": "网站内容抓取",
                "error": str(e),
                "is_success": False
            }

    @staticmethod
    def _process_image_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理图像分析结果"""
        try:
            # 判断操作类型并生成摘要
            if 'question' in tool_name.lower():
                operation = "图像问答"
                summary = ToolResultProcessor._get_localized_summary(
                    "图像分析完成",
                    "Image analysis completed",
                    task_title
                )
            else:
                operation = "图像处理"
                summary = ToolResultProcessor._get_localized_summary(
                    "图像处理完成",
                    "Image processing completed",
                    task_title
                )
            
            return {
                "tool_type": "image_analysis",
                "summary": summary,
                "operation": operation,
                "result_length": len(tool_result)
            }
        except Exception as e:
            logger.error(f"Error processing image result: {e}")
            return {
                "tool_type": "image_analysis",
                "summary": ToolResultProcessor._get_localized_summary(
                    "图像处理完成",
                    "Image processing completed",
                    task_title
                ),
                "error": str(e)
            }
    
    @staticmethod
    def _process_default_result(tool_name: str, tool_args: str, tool_result: str, task_title: str = "") -> Dict[str, Any]:
        """处理默认结果"""
        return {
            "tool_type": "other",
            "summary": ToolResultProcessor._get_localized_summary(
                f"{tool_name} 执行完成",
                f"{tool_name} execution completed",
                task_title
            ),
            "result_length": len(tool_result),
            "has_result": bool(tool_result.strip())
        }