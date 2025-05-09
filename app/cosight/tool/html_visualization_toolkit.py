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

import os
import json
import traceback
from typing import Dict, List, Optional, Union, Any, Tuple
import re
import uuid
import base64
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from llm import llm_for_tool
from work_space import WORKSPACE_PATH
import glob
import tempfile
import shutil
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import datetime
import markdown  
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import concurrent.futures 
import threading 
import io  

# 字体配置函数
def configure_matplotlib_fonts():
    """配置matplotlib字体，确保中文显示正确"""
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simhei.ttf')
    
    # 检查字体文件是否存在，如果不存在则下载
    if not os.path.exists(font_path):
        try:
            # 从网络下载开源中文字体
            font_url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
            print(f"正在下载中文字体...")
            response = requests.get(font_url, stream=True)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(font_path), exist_ok=True)
            
            # 保存字体文件
            with open(font_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            print(f"字体下载完成，保存到: {font_path}")
        except Exception as e:
            print(f"下载字体时出错: {str(e)}")
            # 使用系统默认字体作为后备
            font_path = None
    
    # 配置matplotlib字体
    if font_path and os.path.exists(font_path):
        # 添加自定义字体
        from matplotlib.font_manager import FontProperties, fontManager
        fontManager.addfont(font_path)
        custom_font = FontProperties(fname=font_path)
        
        plt.rcParams['font.family'] = custom_font.get_name()
    else:
        # 使用系统中可能存在的中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Arial Unicode MS', 'sans-serif']
    
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
    
# 调用字体配置函数
configure_matplotlib_fonts()

# 设置seaborn样式
sns.set_style("whitegrid")

try:
    DEEPSEEK_BASE_URL = llm_for_tool.base_url if hasattr(llm_for_tool, 'base_url') else None
    DEEPSEEK_API_KEY = llm_for_tool.api_key if hasattr(llm_for_tool, 'api_key') else None
    DEEPSEEK_MODEL = llm_for_tool.model if hasattr(llm_for_tool, 'model') else "deepseek-chat"
    
    # 如果无法从对象获取，则使用环境变量或默认值
    if not DEEPSEEK_BASE_URL:
        DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.ai.com/v1")
    if not DEEPSEEK_API_KEY:
        DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
except Exception as e:
    print(f"初始化LLM配置时出错: {str(e)}")
    DEEPSEEK_BASE_URL = "https://api.deepseek.ai.com/v1"
    DEEPSEEK_API_KEY = ""
    DEEPSEEK_MODEL = "deepseek-chat"

def get_workspace_path():
    """获取工作区路径"""
    return os.getenv("WORKSPACE_PATH") or os.getcwd()

def read_text_files_from_workspace():
    """读取工作区中的所有文本文件"""
    workspace_path = get_workspace_path()
    text_files = []
    
    print(f"正在扫描工作区: {workspace_path}")
    
    for ext in ['*.txt', '*.md', '*.json', '*.csv']:
        file_paths = glob.glob(os.path.join(workspace_path, ext))
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    text_files.append({
                        'path': file_path,
                        'filename': os.path.basename(file_path),
                        'content': content
                    })
                    print(f"已读取文件: {os.path.basename(file_path)}")
            except Exception as e:
                print(f"读取文件 {file_path} 时出错: {str(e)}")
    
    print(f"共找到 {len(text_files)} 个文本文件")
    return text_files

def ask_llm(prompt, temperature=0.3, max_tokens=4096):
    """通过LLM获取回答"""
    try:
        print("正在向LLM发送请求...", end='', flush=True)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }
        
        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        response = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            print(" 成功")
            content = response.json()["choices"][0]["message"]["content"]
            if content is not None:
                # 处理带有'</think>'标签的模型
                if '</think>' in content:
                    content = content.split('</think>')[-1].strip('\n')
                # 对于不带标签的模型，直接使用完整响应
                return content
            return content
        else:
            print(f" 失败: {response.status_code}")
            print(f"LLM调用失败: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f" 错误")
        print(f"调用LLM时出错: {str(e)}")
        return None

def generate_outline(text_files, user_query=""):
    """根据工作区中的文本文件生成报告大纲"""
    print("正在生成报告大纲...")
    all_content = ""
    for file in text_files:
        all_content += f"文件名: {file['filename']}\n内容预览: {file['content'][:500]}...\n\n"
    
    # 判断用户查询的语言
    is_chinese = bool(re.search(r'[\u4e00-\u9fff]', user_query)) if user_query else True
    
    if is_chinese:
        prompt = f"""作为一个专业的报告编辑器，请基于以下文本文件内容生成一个结构良好的报告大纲，大纲应包含：
1. 标题（主标题和副标题）
2. 3-6个主要章节（每个章节都应该有明确的标题）
3. 每个主要章节下的2-4个子章节

请使用中文生成大纲，确保大纲逻辑连贯，涵盖所有重要信息，并适合转化为专业报告。

文件内容：
{all_content}

请以JSON格式返回大纲，格式如下：
{{
    "title": "主标题",
    "subtitle": "副标题",
    "sections": [
        {{
            "title": "1 章节1标题",
            "subsections": [
                {{
                    "title": "1.1 子章节1.1标题",
                    "content_from": ["文件名1", "文件名2"]
                }},
                ...
            ]
        }},
        ...
    ]
}}

注意：content_from应该指示该子章节的内容应该从哪些文件中提取。请确保所有的JSON字段值都是字符串或数组，而不是嵌套的对象或复杂结构。
"""
    else:
        prompt = f"""As a professional report editor, please generate a well-structured report outline based on the following text file content. The outline should include:
1. Title (main title and subtitle)
2. 3-6 main sections (each section should have a clear title)
3. 2-4 subsections under each main section

Please generate the outline in English, ensuring that the outline is logically coherent, covers all important information, and is suitable for conversion into a professional report.

File content:
{all_content}

Please return the outline in JSON format as follows:
{{
    "title": "Main Title",
    "subtitle": "Subtitle",
    "sections": [
        {{
            "title": "1 Section 1 Title",
            "subsections": [
                {{
                    "title": "1.1 Subsection 1.1 Title",
                    "content_from": ["filename1", "filename2"]
                }},
                ...
            ]
        }},
        ...
    ]
}}

Note: content_from should indicate which files the content for that subsection should be extracted from. Please ensure that all JSON field values are strings or arrays, not nested objects or complex structures.
"""
    
    response = ask_llm(prompt)
    if response:
        try:
            # 提取JSON部分
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response
                
            # 清理可能导致JSON解析错误的字符
            json_str = json_str.strip()
            
            # 尝试解析JSON
            try:
                outline = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {str(e)}")
                print(f"JSON字符串: {json_str}")
                # 提供错误信息并返回空结构
                return None
            
            # 确保所有文件引用都是列表类型
            for section in outline.get('sections', []):
                for subsection in section.get('subsections', []):
                    if 'content_from' not in subsection:
                        subsection['content_from'] = []
                    elif not isinstance(subsection['content_from'], list):
                        subsection['content_from'] = [subsection['content_from']]
            
            return outline
        except Exception as e:
            print(f"解析大纲JSON时出错: {str(e)}")
            print(f"原始响应: {response}")
            traceback.print_exc()  # 打印完整堆栈
            return None
    else:
        print("从LLM获取大纲响应失败")
        return None

def convert_markdown_to_html(text):
    """将Markdown格式的文本转换为HTML格式"""
    try:
        # 首先检查文本是否包含在代码块中的Markdown内容
        # 这种情况下，内容可能是被包裹在 ```markdown ... ``` 中的
        code_block_pattern = r'```(?:markdown|md)?\s*([\s\S]*?)```'
        code_block_match = re.search(code_block_pattern, text)
        
        if code_block_match:
            # 如果发现代码块中包含Markdown内容，提取出来进行处理
            markdown_content = code_block_match.group(1)
            # 使用markdown库将文本转换为HTML
            html = markdown.markdown(markdown_content, extensions=['extra', 'nl2br', 'sane_lists', 'tables'])
            return html
        
        # 正常处理普通Markdown文本
        html = markdown.markdown(text, extensions=['extra', 'nl2br', 'sane_lists', 'tables'])
        return html
    except Exception as e:
        print(f"转换Markdown到HTML时出错: {str(e)}")
        # 如果转换失败，返回原始文本，但将基本的Markdown标题和格式转换为HTML
        try:
            # 转换标题
            text = re.sub(r'^(#{1,6})\s+(.+?)$', lambda m: f'<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>', text, flags=re.MULTILINE)
            
            # 转换粗体和斜体
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            
            # 转换列表
            text = re.sub(r'^\*\s+(.+?)$', r'<li>\1</li>', text, flags=re.MULTILINE)
            text = re.sub(r'^(\d+)\.\s+(.+?)$', r'<li>\2</li>', text, flags=re.MULTILINE)
            
            # 将连续的<li>包裹在<ul>或<ol>中
            text = re.sub(r'(<li>.*?</li>\n)+', r'<ul>\g<0></ul>', text, flags=re.DOTALL)
            
            # 转换段落
            text = re.sub(r'^([^<\n].+?)$', r'<p>\1</p>', text, flags=re.MULTILINE)
            
            # 转换换行
            text = text.replace('\n\n', '<br><br>')
            
            return text
        except:
            # 完全失败时，至少保证换行被转换
            return text.replace('\n', '<br>')

def reorganize_content(text_files, outline, user_query=""):
    """根据大纲重新组织内容，使用多线程并行处理LLM请求"""
    print("正在根据大纲重新组织内容...")
    filename_to_content = {file['filename']: file['content'] for file in text_files}
    reorganized_sections = []
    
    # 创建一个线程锁，用于安全添加内容到sections
    section_lock = threading.Lock()
    
    # 创建一个计数器，用于显示进度
    total_subsections = sum(len(section.get('subsections', [])) for section in outline.get('sections', []))
    processed_count = 0
    progress_lock = threading.Lock()
    
    print(f"总共需要处理 {total_subsections} 个子章节")
    
    # 判断用户查询的语言
    is_chinese = bool(re.search(r'[\u4e00-\u9fff]', user_query)) if user_query else True
    
    def process_subsection(section_idx, section, subsection_idx, subsection):
        """处理单个子章节的函数，将在独立线程中运行"""
        nonlocal processed_count
        
        try:
            content_files = subsection.get('content_from', [])
            
            # 如果没有指定文件，尝试查找相关内容
            if not content_files:
                relevant_content = ""
                for filename, content in filename_to_content.items():
                    if subsection['title'].lower() in content.lower():
                        relevant_content += content + "\n\n"
            else:
                relevant_content = ""
                for filename in content_files:
                    if filename in filename_to_content:
                        relevant_content += filename_to_content[filename] + "\n\n"
            
            # 根据用户查询语言选择合适的提示语
            if is_chinese:
                prompt = f"""请根据以下原始内容撰写一个关于"{subsection['title']}"的子章节内容。内容应该是连贯的，格式良好的段落，尽量提取和组织所有相关的信息，尽量保留数据相关的原始内容，请确保数据和内容完全与原始内容一致，不要篡改。

重要说明：请不要在内容中再次包含标题（如 "### {subsection['title']}"），因为标题会在最终报告中单独添加。

请使用Markdown格式，可以使用以下Markdown语法增强可读性：
- 使用 #### 及更小级别的标题标记小节（注意：不要使用 # 或 ## 或 ###，因为这些级别会与文档结构冲突）
- 使用 **文本** 标记重要内容
- 使用 1. 2. 3. 或 * - + 创建有序或无序列表
- 必要时可以使用表格、引用块等其他Markdown元素

注意：请直接输出Markdown内容，不要将Markdown内容包装在代码块中（例如不要使用```markdown之类的标记）。
同时请确保不要在内容开头重复子章节的标题，这会导致标题重复显示。

原始内容:
{relevant_content}

返回内容应该是结构良好的Markdown文本，每个段落都应该是完整的句子，且长度适当。
注意：直接从正文内容开始撰写，必须使用中文撰写内容。
"""
            else:
                prompt = f"""Based on the following original content, please write subsection content about "{subsection['title']}". The content should be coherent, well-formatted paragraphs that extract and organize all relevant information, preserving data-related original content. Ensure the data and content are completely consistent with the original content, without alteration.

Important note: Do not include the title (such as "### {subsection['title']}") in the content, as the title will be added separately in the final report.

Please use Markdown format, with the following Markdown syntax to enhance readability:
- Use #### and smaller heading levels to mark subsections (note: do not use #, ##, or ###, as these levels conflict with the document structure)
- Use **text** to mark important content
- Use 1. 2. 3. or * - + to create ordered or unordered lists
- Use tables, quote blocks, and other Markdown elements when necessary

Note: Output Markdown content directly, without wrapping it in code blocks (e.g., do not use ```markdown tags).
Also make sure not to repeat the subsection title at the beginning of the content, as this will cause the title to be displayed twice.

Original content:
{relevant_content}

The returned content should be well-structured Markdown text, with complete sentences in each paragraph and appropriate length.
Note: Start writing directly from the body content, and you must write the content in English.
"""
            
            with progress_lock:
                print(f"处理子章节 [{section_idx+1}.{subsection_idx+1}]: {subsection['title']} ({processed_count+1}/{total_subsections})")
            
            subsection_content = ask_llm(prompt)
            result = {
                'title': subsection['title'],
                'content': subsection_content,
                'section_idx': section_idx,
                'subsection_idx': subsection_idx
            }
            
            with progress_lock:
                processed_count += 1
                print(f"完成子章节 [{section_idx+1}.{subsection_idx+1}]: {subsection['title']} ({processed_count}/{total_subsections})")
            
            return result
        except Exception as e:
            print(f"处理子章节 {subsection['title']} 时出错: {str(e)}")
            return {
                'title': subsection['title'],
                'content': f"<p>内容生成失败: {str(e)}</p>",
                'section_idx': section_idx,
                'subsection_idx': subsection_idx
            }
    
    # 准备所有任务
    tasks = []
    for section_idx, section in enumerate(outline.get('sections', [])):
        print(f"准备章节 {section_idx+1}/{len(outline.get('sections', []))}: {section['title']}")
        section_data = {
            'title': section['title'],
            'subsections': [None] * len(section.get('subsections', []))  # 预分配空间
        }
        
        with section_lock:
            reorganized_sections.append(section_data)
        
        for subsection_idx, subsection in enumerate(section.get('subsections', [])):
            tasks.append((section_idx, section, subsection_idx, subsection))
    
    # 确定线程池大小，避免创建过多线程
    # 根据CPU数量和任务总数动态调整，但不超过10个线程
    max_workers = min(10, max(1, min(os.cpu_count() or 4, total_subsections)))
    print(f"将使用 {max_workers} 个线程并行处理LLM请求")
    
    # 使用线程池并行处理所有任务
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_task = {
            executor.submit(process_subsection, *task): task 
            for task in tasks
        }
        
        # 处理结果，按完成顺序
        for future in concurrent.futures.as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                if result:
                    section_idx = result['section_idx']
                    subsection_idx = result['subsection_idx']
                    
                    # 安全地添加结果到对应位置
                    with section_lock:
                        reorganized_sections[section_idx]['subsections'][subsection_idx] = {
                            'title': result['title'],
                            'content': result['content']
                        }
            except Exception as e:
                section_idx, section, subsection_idx, subsection = task
                print(f"获取子章节 {section['title']} - {subsection['title']} 的结果时出错: {str(e)}")
                with section_lock:
                    reorganized_sections[section_idx]['subsections'][subsection_idx] = {
                        'title': subsection['title'],
                        'content': f"<p>内容生成失败: {str(e)}</p>"
                    }
    
    print(f"所有 {total_subsections} 个子章节处理完成")
    return reorganized_sections

def analyze_content_for_visualization(section_content, user_query=""):
    """分析内容是否适合生成图表，返回可视化信息"""
    try:
        # 判断用户查询的语言
        is_chinese = bool(re.search(r'[\u4e00-\u9fff]', user_query)) if user_query else True
        
        if is_chinese:
            prompt = f"""请分析以下文本内容，判断其是否包含可以通过图表可视化的数据。如果内容中包含可视化的数据，请提取这些数据并推荐合适的图表类型。

内容：
{section_content}

请回答以下问题：

1. 这段内容是否包含可以进行可视化的数据？（回答是/否）
2. 如果是，这些数据的主题是什么？
3. 最适合展示这些数据的图表类型是什么？（如：折线图、柱状图、饼图、散点图、雷达图等）
4. 这些数据中的独立变量（x轴）和依赖变量（y轴）分别是什么？
5. 简要描述为什么选择这种图表类型以及它能展示哪些洞见？

请以JSON格式返回结果，并确保包含数据点信息：
{{
    "suitable_for_visualization": true,
    "theme": "数据主题",
    "chart_type": "推荐的图表类型",
    "variables": {{
        "x_axis": "独立变量",
        "y_axis": "依赖变量"
    }},
    "reason": "选择理由",
    "data_points": [
        {{
            "category": "类别1",
            "value": 100
        }},
        {{
            "category": "类别2",
            "value": 200
        }}
        // 请尽量提取所有可视化数据点
    ],
    "time_series": false  // 如果是时间序列数据，设为true
}}

如果内容不适合可视化，则返回：
{{
    "suitable_for_visualization": false,
    "reason": "不适合可视化的原因"
}}
"""
        else:
            prompt = f"""Please analyze the following text content and determine if it contains data that can be visualized through charts. If the content contains visualizable data, please extract this data and recommend an appropriate chart type.

Content:
{section_content}

Please answer the following questions:

1. Does this content contain data that can be visualized? (Answer yes/no)
2. If yes, what is the theme of this data?
3. What chart type is most suitable for displaying this data? (e.g.: line chart, bar chart, pie chart, scatter plot, radar chart, etc.)
4. What are the independent variables (x-axis) and dependent variables (y-axis) in this data?
5. Briefly describe why this chart type was chosen and what insights it can show?

Please return the results in JSON format, ensuring you include data points:
{{
    "suitable_for_visualization": true,
    "theme": "data theme",
    "chart_type": "recommended chart type",
    "variables": {{
        "x_axis": "independent variable",
        "y_axis": "dependent variable"
    }},
    "reason": "selection rationale",
    "data_points": [
        {{
            "category": "category1",
            "value": 100
        }},
        {{
            "category": "category2",
            "value": 200
        }}
        // Please try to extract all visualizable data points
    ],
    "time_series": false  // Set to true if it's time series data
}}

If the content is not suitable for visualization, then return:
{{
    "suitable_for_visualization": false,
    "reason": "reason why it's not suitable for visualization"
}}
"""

        response = ask_llm(prompt)
        
        # 处理JSON响应
        try:
            # 提取JSON部分
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response.strip()
                
            # 清理可能导致JSON解析错误的字符
            json_str = re.sub(r'```.*?```', '', json_str, flags=re.DOTALL)
            
            # 解析JSON
            visualization_info = json.loads(json_str)
            
            # 确保必需的字段存在
            if 'suitable_for_visualization' not in visualization_info:
                raise ValueError("JSON缺少'suitable_for_visualization'字段")
                
            if visualization_info['suitable_for_visualization']:
                # 处理数据点
                if 'data_points' not in visualization_info:
                    visualization_info['data_points'] = []
                
                # 确保提取的数据也存在
                extracted_data = []
                
                # 将data_points转换为适合处理的格式
                for point in visualization_info.get('data_points', []):
                    if isinstance(point, dict) and 'category' in point and 'value' in point:
                        extracted_item = {
                            'dimension': point['category'],
                            'metrics': {'value': point['value']}
                        }
                        extracted_data.append(extracted_item)
                
                # 设置提取的数据
                visualization_info['extracted_data'] = extracted_data
                
                # 设置数据指标和维度
                visualization_info['data_metrics'] = ['value']
                visualization_info['data_dimensions'] = [visualization_info.get('variables', {}).get('x_axis', '类别' if is_chinese else 'Category')]
                
                # 其他字段的处理
                if 'variables' not in visualization_info:
                    visualization_info['variables'] = {
                        'x_axis': 'Category',
                        'y_axis': 'Value'
                    }
                    
                if 'time_series' not in visualization_info:
                    visualization_info['time_series'] = False
                    
                # 提取数据主题
                if 'theme' not in visualization_info or not visualization_info['theme']:
                    visualization_info['theme'] = '数据可视化' if is_chinese else 'Data Visualization'
                
                # 添加标题和描述
                if 'title' not in visualization_info:
                    visualization_info['title'] = visualization_info.get('theme', '数据可视化' if is_chinese else 'Data Visualization')
                
                if 'description' not in visualization_info:
                    visualization_info['description'] = visualization_info.get('reason', '')
            
            return visualization_info
                
        except json.JSONDecodeError as e:
            # 返回一个默认的响应
            return {
                'suitable_for_visualization': False,
                'reason': f"JSON解析错误: {str(e)}"
            }
        except Exception as e:
            # 返回一个默认的响应
            return {
                'suitable_for_visualization': False,
                'reason': f"处理错误: {str(e)}"
            }
        
    except Exception as e:
        return {
            'suitable_for_visualization': False,
            'reason': f"分析错误: {str(e)}"
        }

def generate_sample_data(visualization_info):
    """从提取的真实数据生成可视化数据集"""
    print("处理可视化数据...", end='', flush=True)
    try:
        # 获取图表类型并确保它是字符串
        chart_type_value = visualization_info.get('chart_type', '')
        
        # 检查是否为列表，如果是，则取第一个元素
        if isinstance(chart_type_value, list):
            chart_type = chart_type_value[0].lower() if chart_type_value else ''
        else:
            chart_type = str(chart_type_value).lower()  # 确保转换为字符串
        
        # 获取从文本中提取的数据
        extracted_data = visualization_info.get('extracted_data', [])
        
        # 如果没有提取到数据，返回None
        if not extracted_data:
            return None
            
        # 获取指标和维度
        metrics = visualization_info.get('data_metrics', [])
        dimensions = visualization_info.get('data_dimensions', [])
        
        # 确保metrics和dimensions是列表
        if not isinstance(metrics, list):
            metrics = [metrics]
        if not isinstance(dimensions, list):
            dimensions = [dimensions]
            
        # 处理提取的数据
        data = {}
        dimension_values = []
        
        # 遍历提取的数据，构建数据框
        for item in extracted_data:
            dimension_value = item.get('dimension', '')
            if dimension_value:
                dimension_values.append(dimension_value)
                metrics_values = item.get('metrics', {})
                
                for metric_name, metric_value in metrics_values.items():
                    if metric_name not in data:
                        data[metric_name] = []
                    
                    # 尝试将值转换为浮点数
                    try:
                        data[metric_name].append(float(metric_value))
                    except (ValueError, TypeError):
                        # 如果无法转换为数字，使用0（并记录警告）
                        data[metric_name].append(0.0)
        
        # 如果数据为空或维度值为空，返回None
        if not data or not dimension_values:
            return None
            
        # 创建Pandas DataFrame
        df = pd.DataFrame(data, index=dimension_values)
        
        # 根据图表类型进行特定处理
        if chart_type in ['折线图', '线图', 'line chart', 'line graph', 'line plot']:
            # 检查维度是否可以转换为日期
            try:
                # 尝试将索引转换为日期时间
                date_index = pd.to_datetime(df.index)
                df.index = date_index
                df = df.sort_index()  # 按日期排序
            except:
                # 如果转换失败，保持原样并确保顺序
                pass
        
        # 确保数据框至少有一行一列
        if df.shape[0] == 0 or df.shape[1] == 0:
            return None
            
        print(" 成功")
        return df
    
    except Exception as e:
        traceback.print_exc()
        return None

def create_visualization(visualization_info, chart_types):
    """根据图表类型创建使用真实数据的可视化图表"""
    if not visualization_info['suitable_for_visualization']:
        reason = visualization_info.get('reason', '内容不适合生成图表')
        return None
    
    # 验证是否有提取到的数据
    if 'extracted_data' not in visualization_info or not visualization_info['extracted_data']:
        return None
    
    print(f"创建{visualization_info.get('chart_type', '')}类型的可视化图表...", end='', flush=True)
    
    # 获取图表类型并确保它是字符串
    chart_type_value = visualization_info.get('chart_type', '')
    
    # 检查是否为列表，如果是，则取第一个元素
    if isinstance(chart_type_value, list):
        chart_type = chart_type_value[0].lower() if chart_type_value else ''
    else:
        chart_type = str(chart_type_value).lower()  # 确保转换为字符串
    
    # 检查图表类型是否在用户指定的类型中
    if 'all' not in chart_types:
        chart_match = False
        if chart_type in ['折线图', '线图', 'line chart', 'line graph', 'line plot'] and 'line' in chart_types:
            chart_match = True
        elif chart_type in ['柱状图', '条形图', 'bar chart', 'bar graph', 'histogram'] and 'bar' in chart_types:
            chart_match = True
        elif chart_type in ['饼图', '圆饼图', 'pie chart'] and 'pie' in chart_types:
            chart_match = True
        elif chart_type in ['散点图', 'scatter plot', 'scatter graph'] and 'scatter' in chart_types:
            chart_match = True
        elif chart_type in ['雷达图', 'radar chart', 'radar plot', 'spider chart'] and 'radar' in chart_types:
            chart_match = True
        elif chart_type in ['热力图', 'heatmap', 'heat map'] and 'heatmap' in chart_types:
            chart_match = True
        elif chart_type in ['气泡图', 'bubble chart', 'bubble plot'] and 'bubble' in chart_types:
            chart_match = True
        elif chart_type in ['树状图', 'treemap', 'tree map'] and 'treemap' in chart_types:
            chart_match = True
        elif chart_type in ['桑基图', 'sankey diagram', 'sankey chart'] and 'sankey' in chart_types:
            chart_match = True
            
        if not chart_match:
            return None
    
    # 生成真实数据框
    sample_data = generate_sample_data(visualization_info)
    if sample_data is None:
        return None
    
    # 打印数据预览，以便验证
    print(f"\n数据预览 (前5行):\n{sample_data.head().to_string()}\n")
    
    # 创建可视化
    try:
        title = visualization_info.get('title', 'Data Visualization')
        description = visualization_info.get('description', 'Chart Description')
        
        # 使用用户提供的配色方案
        custom_palette = [
            '#4E5D6C',  # 深蓝灰色
            '#8FA1B3',  # 中蓝灰色 
            '#B3B3B3',  # 浅灰色
            '#D9A679',  # 浅棕色
            '#A6785E',  # 深棕色
            '#6B7C8C',  # 蓝灰色变种
            '#C8D3E0',  # 浅蓝灰色
            '#DECCB8',  # 浅棕米色
            '#896A53',  # 咖啡棕色
            '#5D7A96'   # 钴蓝色
        ]
        
        # 创建扩展调色板，在主色的基础上加入衍生色
        extended_palette = custom_palette.copy()
        # 添加衍生色 - 将每种颜色调亮一些
        for color in custom_palette:
            # 将16进制颜色转换为RGB，再调亮，再转回16进制
            r = min(255, int(color[1:3], 16) + 20)
            g = min(255, int(color[3:5], 16) + 20)
            b = min(255, int(color[5:7], 16) + 20)
            lighter_color = f'#{r:02x}{g:02x}{b:02x}'
            extended_palette.append(lighter_color)
            
            # 添加暗色变种
            r = max(0, int(color[1:3], 16) - 20)
            g = max(0, int(color[3:5], 16) - 20)
            b = max(0, int(color[5:7], 16) - 20)
            darker_color = f'#{r:02x}{g:02x}{b:02x}'
            extended_palette.append(darker_color)
        
        # 创建交互式plotly图表
        fig = None
        
        if chart_type in ['折线图', '线图', 'line chart', 'line graph', 'line plot']:
            # 折线图
            if isinstance(sample_data.index, pd.DatetimeIndex):
                # 时间序列数据
                fig = px.line(sample_data, x=sample_data.index, y=sample_data.columns,
                            title=title, labels={'value': 'Value', 'variable': 'Metric'},
                            color_discrete_sequence=custom_palette)
            else:
                # 非时间序列数据
                # 转置数据以便更好地展示
                df_melted = sample_data.reset_index().melt(id_vars='index')
                fig = px.line(df_melted, x='index', y='value', color='variable',
                            title=title, labels={'index': 'Category', 'value': 'Value', 'variable': 'Metric'},
                            color_discrete_sequence=custom_palette)
                
            fig.update_layout(
                hovermode='x unified',
                plot_bgcolor='rgba(245,245,242,0.2)',
                paper_bgcolor='white',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            fig.update_traces(line=dict(width=2.5))
        
        elif chart_type in ['柱状图', '条形图', 'bar chart', 'bar graph', 'histogram']:
            # 柱状图
            df_melted = sample_data.reset_index().melt(id_vars='index')
            
            if 'variable' in df_melted.columns:
                # 使用variable分组，为每个组分配不同颜色
                fig = px.bar(df_melted, x='index', y='value', color='variable',
                            title=title, labels={'index': 'Category', 'value': 'Value', 'variable': 'Metric'},
                            barmode='group', color_discrete_sequence=custom_palette)
            else:
                # 为每个柱子分配不同颜色
                fig = px.bar(df_melted, x='index', y='value',
                            title=title, labels={'index': 'Category', 'value': 'Value'},
                            color='index', color_discrete_sequence=custom_palette)
            
            fig.update_layout(
                plot_bgcolor='rgba(245,245,242,0.2)',
                paper_bgcolor='white',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            # 为柱状图添加轮廓，增强视觉效果
            fig.update_traces(marker_line_color='white', marker_line_width=1, opacity=0.85)
        
        elif chart_type in ['饼图', '圆饼图', 'pie chart']:
            # 饼图 - 只使用第一个指标列
            if sample_data.shape[1] >= 1:
                column = sample_data.columns[0]
                fig = px.pie(sample_data, values=column, names=sample_data.index,
                            title=title, color_discrete_sequence=extended_palette)
                
                fig.update_traces(
                    textposition='inside', 
                    textinfo='percent+label',
                    marker=dict(line=dict(color='white', width=1.5)),
                    pull=[0.03]*len(sample_data),  # 轻微拉出所有扇区
                    opacity=0.9
                )
                fig.update_layout(
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=-0.1,
                        xanchor="center",
                        x=0.5
                    )
                )
            else:
                return None
        
        elif chart_type in ['散点图', 'scatter plot', 'scatter graph']:
            # 散点图 - 需要至少两列数据
            if sample_data.shape[1] >= 2:
                x_col, y_col = sample_data.columns[0], sample_data.columns[1]
                
                # 使用额外的列作为分类变量以分配不同颜色
                color_col = None
                size_col = None
                
                if sample_data.shape[1] >= 3:
                    size_col = sample_data.columns[2]
                    
                    if sample_data.shape[1] >= 4:
                        color_col = sample_data.columns[3]
                        fig = px.scatter(sample_data, x=x_col, y=y_col, size=size_col, color=color_col,
                                        title=title, labels={x_col: x_col, y_col: y_col, size_col: size_col, color_col: color_col},
                                        color_discrete_sequence=custom_palette)
                    else:
                        # 创建一个颜色变量以便在没有分类变量的情况下为点分配不同颜色
                        sample_data_copy = sample_data.copy()
                        sample_data_copy['color_group'] = [f'Group {i+1}' for i in range(len(sample_data_copy))]
                        fig = px.scatter(sample_data_copy, x=x_col, y=y_col, size=size_col, color='color_group',
                                        title=title, labels={x_col: x_col, y_col: y_col, size_col: size_col},
                                        color_discrete_sequence=custom_palette)
                else:
                    # 创建一个颜色变量以便在没有分类变量的情况下为点分配不同颜色
                    sample_data_copy = sample_data.copy()
                    sample_data_copy['color_group'] = [f'Group {i+1}' for i in range(len(sample_data_copy))]
                    fig = px.scatter(sample_data_copy, x=x_col, y=y_col, color='color_group',
                                    title=title, labels={x_col: x_col, y_col: y_col},
                                    color_discrete_sequence=custom_palette)
                
                # 添加趋势线
                fig.update_traces(
                    marker=dict(
                        size=10 if size_col is None else None,
                        line=dict(width=1, color='white'),
                        opacity=0.75
                    )
                )
                
                # 添加平滑的趋势线
                fig.add_traces(go.Scatter(
                    x=sample_data[x_col], 
                    y=sample_data[x_col] * sample_data[y_col].mean() / sample_data[x_col].mean(),
                    mode='lines', 
                    name='Trend Line',
                    line=dict(color=custom_palette[1], width=2, dash='dash')
                ))
                
                fig.update_layout(
                    plot_bgcolor='rgba(245,245,242,0.2)',
                    paper_bgcolor='white'
                )
            else:
                return None
        
        elif chart_type in ['雷达图', 'radar chart', 'radar plot', 'spider chart']:
            # 雷达图 - 转换数据为适合雷达图的格式
            if sample_data.shape[1] >= 2:
                # 准备雷达图数据
                categories = sample_data.columns.tolist()
                
                fig = go.Figure()
                
                for i, idx in enumerate(sample_data.index):
                    values = sample_data.loc[idx].tolist()
                    # 确保数据闭合
                    if values[0] != values[-1]:
                        categories.append(categories[0])
                        values.append(values[0])
                        
                    fig.add_trace(go.Scatterpolar(
                        r=values,
                        theta=categories,
                        fill='toself',
                        name=str(idx),
                        line_color=custom_palette[i % len(custom_palette)],
                        fillcolor=custom_palette[i % len(custom_palette)],
                        opacity=0.6
                    ))
                
                fig.update_layout(
                    title=title,
                    polar=dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, sample_data.values.max() * 1.1]
                        )
                    ),
                    showlegend=True
                )
            else:
                return None
        
        elif chart_type in ['热力图', 'heatmap', 'heat map']:
            # 热力图
            # 为热力图创建渐变色配色方案
            colorscale = [
                [0, custom_palette[0]],      # 起始颜色
                [0.25, custom_palette[1]],   # 1/4处颜色
                [0.5, custom_palette[2]],    # 中间颜色
                [0.75, custom_palette[3]],   # 3/4处颜色
                [1, custom_palette[4]]       # 结束颜色
            ]
            
            fig = px.imshow(sample_data, 
                          title=title,
                          labels=dict(x='Category', y='Metrics', color='Value'),
                          color_continuous_scale=colorscale)
            
            fig.update_layout(
                plot_bgcolor='rgba(245,245,242,0.2)',
                paper_bgcolor='white'
            )
        
        elif chart_type in ['气泡图', 'bubble chart', 'bubble plot']:
            # 气泡图 - 需要至少三列数据
            if sample_data.shape[1] >= 3:
                cols = sample_data.columns.tolist()
                x_col, y_col, size_col = cols[0], cols[1], cols[2]
                
                # 第四列作为颜色 (如果有)
                color_col = None
                if sample_data.shape[1] >= 4:
                    color_col = cols[3]
                    fig = px.scatter(sample_data, x=x_col, y=y_col, size=size_col, color=color_col,
                                    title=title, 
                                    labels={x_col: x_col, y_col: y_col, size_col: 'Size', color_col: 'Group'},
                                    color_discrete_sequence=custom_palette)
                else:
                    fig = px.scatter(sample_data, x=x_col, y=y_col, size=size_col,
                                    title=title, 
                                    labels={x_col: x_col, y_col: y_col, size_col: 'Size'},
                                    color_discrete_sequence=custom_palette)
                
                fig.update_traces(
                    marker=dict(
                        line=dict(width=1, color='white'),
                        opacity=0.7,
                        sizemode='area',
                        sizeref=2.*max(sample_data[size_col])/(40.**2),
                        sizemin=4
                    )
                )
                
                fig.update_layout(
                    plot_bgcolor='rgba(245,245,242,0.2)',
                    paper_bgcolor='white'
                )
            else:
                return None
        
        elif chart_type in ['树状图', 'treemap', 'tree map']:
            # 树状图
            df_melted = sample_data.reset_index().melt(id_vars='index')
            fig = px.treemap(
                df_melted, 
                path=['variable', 'index'], 
                values='value',
                title=title,
                color_discrete_sequence=extended_palette
            )
            
            fig.update_traces(
                textinfo='label+value',
                marker=dict(line=dict(width=1, color='white'))
            )
            
            fig.update_layout(
                margin=dict(l=0, r=0, t=30, b=0)
            )
        
        elif chart_type in ['桑基图', 'sankey diagram', 'sankey chart']:
            # 桑基图 - 需要特殊处理数据
            if sample_data.shape[1] >= 2 and sample_data.shape[0] >= 3:
                # 准备节点和链接
                nodes = []
                links = []
                
                # 为简化起见，使用第一列和其他列的关系
                source_col = sample_data.columns[0]
                for i, target_col in enumerate(sample_data.columns[1:], 1):
                    for idx in sample_data.index:
                        source_val = f"{source_col}: {idx}"
                        target_val = f"{target_col}: {sample_data.loc[idx, target_col]}"
                        value = sample_data.loc[idx, source_col]
                        
                        if source_val not in nodes:
                            nodes.append(source_val)
                        if target_val not in nodes:
                            nodes.append(target_val)
                            
                        links.append({
                            'source': nodes.index(source_val),
                            'target': nodes.index(target_val),
                            'value': value
                        })
                
                # 为节点分配不同的颜色
                node_colors = []
                for i in range(len(nodes)):
                    node_colors.append(extended_palette[i % len(extended_palette)])
                
                # 创建桑基图
                fig = go.Figure(data=[go.Sankey(
                    node=dict(
                        pad=15,
                        thickness=20,
                        line=dict(color='black', width=0.5),
                        label=nodes,
                        color=node_colors
                    ),
                    link=dict(
                        source=[link['source'] for link in links],
                        target=[link['target'] for link in links],
                        value=[link['value'] for link in links],
                        color=[f'rgba({int(custom_palette[0][1:3], 16)},{int(custom_palette[0][3:5], 16)},{int(custom_palette[0][5:7], 16)},0.3)' for _ in links]
                    )
                )])
                
                fig.update_layout(
                    title=title,
                    font=dict(size=10),
                    paper_bgcolor='white'
                )
            else:
                return None
        
        # 如果没有创建图表，返回None
        if fig is None:
            print(" 失败：不支持的图表类型")
            return None
        
        # 设置通用布局属性
        fig.update_layout(
            title=dict(text=title, font=dict(size=20, family='Inter, sans-serif')),
            font=dict(family='Inter, sans-serif'),
            margin=dict(l=40, r=40, t=60, b=60),
            hoverlabel=dict(
                bgcolor='white',
                font_size=12,
                font_family='Inter, sans-serif'
            )
        )
        
        # 保存交互式HTML
        html_io = io.StringIO()
        fig.write_html(html_io, include_plotlyjs='cdn', full_html=False)
        chart_html = html_io.getvalue()
        
        # 保存为静态图像
        img_bytes = fig.to_image(format="png", width=800, height=500, scale=2)
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        print(" 成功")
        
        # 准备返回数据
        result = {
            'title': title,
            'description': description,
            'chart_type': chart_type,
            'image_base64': img_base64,
            'chart_html': chart_html,
            'is_interactive': True
        }
        
        return result
        
    except Exception as e:
        traceback.print_exc()
        return None

def generate_chart_code_template(visualization_info):
    """生成图表代码模板"""
    chart_type = visualization_info.get('chart_type', '').lower()
    title = visualization_info.get('title', '数据可视化')
    
    if chart_type in ['折线图', '线图', 'line chart', 'line graph', 'line plot']:
        code = f"""
def create_line_chart(data):
    \"\"\"创建折线图
    参数:
        data: 包含时间序列数据的DataFrame，行索引为日期，列为不同指标
    返回:
        base64编码的图像字符串
    \"\"\"
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO
    
    plt.figure(figsize=(10, 6))
    ax = data.plot(kind='line', marker='o')
    plt.title("{title}")
    plt.xlabel('日期')
    plt.ylabel('数值')
    plt.grid(True)
    plt.legend(title='指标')
    plt.tight_layout()
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=300)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    
    return image_base64
"""
        
    elif chart_type in ['柱状图', '条形图', 'bar chart', 'bar graph', 'histogram']:
        code = f"""
def create_bar_chart(data):
    \"\"\"创建柱状图
    参数:
        data: 包含分类数据的DataFrame，行索引为类别，列为不同指标
    返回:
        base64编码的图像字符串
    \"\"\"
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO
    
    plt.figure(figsize=(10, 6))
    ax = data.plot(kind='bar')
    plt.title("{title}")
    plt.xlabel('类别')
    plt.ylabel('数值')
    plt.legend(title='指标')
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=300)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    
    return image_base64
"""
        
    elif chart_type in ['饼图', '圆饼图', 'pie chart']:
        code = f"""
def create_pie_chart(data):
    \"\"\"创建饼图
    参数:
        data: 包含比例数据的DataFrame，行索引为类别，只使用第一列数据
    返回:
        base64编码的图像字符串
    \"\"\"
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO
    
    plt.figure(figsize=(10, 6))
    column = data.columns[0]
    ax = data[column].plot(kind='pie', autopct='%1.1f%%')
    plt.title("{title}")
    plt.ylabel('')
    plt.tight_layout()
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=300)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    
    return image_base64
"""
        
    elif chart_type in ['散点图', 'scatter plot', 'scatter graph']:
        code = f"""
def create_scatter_plot(data):
    \"\"\"创建散点图
    参数:
        data: 包含二维数据的DataFrame，至少包含两列数据
    返回:
        base64编码的图像字符串
    \"\"\"
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO
    
    plt.figure(figsize=(10, 6))
    if len(data.columns) >= 2:
        x_col, y_col = data.columns[0], data.columns[1]
        plt.scatter(data[x_col], data[y_col])
        plt.title("{title}")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        plt.grid(True)
    else:
        raise ValueError("数据至少需要包含两列")
    
    plt.tight_layout()
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=300)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    
    return image_base64
"""
        
    else:  # 默认为通用图表
        code = f"""
def create_chart(data, chart_type='bar'):
    \"\"\"创建通用图表
    参数:
        data: 包含数据的DataFrame
        chart_type: 图表类型，可选值: 'bar', 'line', 'pie', 'scatter'
    返回:
        base64编码的图像字符串
    \"\"\"
    import matplotlib.pyplot as plt
    import base64
    from io import BytesIO
    
    plt.figure(figsize=(10, 6))
    
    if chart_type == 'line':
        ax = data.plot(kind='line', marker='o')
        plt.xlabel('X轴')
        plt.ylabel('Y轴')
        plt.grid(True)
        plt.legend(title='指标')
    elif chart_type == 'bar':
        ax = data.plot(kind='bar')
        plt.xlabel('类别')
        plt.ylabel('数值')
        plt.legend(title='指标')
        plt.xticks(rotation=45)
    elif chart_type == 'pie':
        column = data.columns[0]
        ax = data[column].plot(kind='pie', autopct='%1.1f%%')
        plt.ylabel('')
    elif chart_type == 'scatter':
        if len(data.columns) >= 2:
            x_col, y_col = data.columns[0], data.columns[1]
            plt.scatter(data[x_col], data[y_col])
            plt.xlabel(x_col)
            plt.ylabel(y_col)
            plt.grid(True)
        else:
            raise ValueError("散点图数据至少需要包含两列")
    
    plt.title("{title}")
    plt.tight_layout()
    
    buffer = BytesIO()
    plt.savefig(buffer, format='png', dpi=300)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    plt.close()
    
    return image_base64
"""
    
    return code

def ask_model_for_parameters(user_query=""):
    """与大模型交互获取报告生成参数"""
    try:
        # 判断用户查询的语言
        is_chinese = bool(re.search(r'[\u4e00-\u9fff]', user_query)) if user_query else True
        
        # 根据用户查询语言选择提示语言
        if is_chinese:
            prompt = """
我需要为您生成HTML报告，请提供以下参数（如果您不指定某个参数，我将使用默认值）：

1. 报告标题：您希望的报告标题是什么？
2. 是否包含数据可视化图表：yes/no（默认yes）
3. 需要生成的图表类型：可选值包括:
   - all（所有类型）
   - line（折线图）
   - bar（柱状图）
   - pie（饼图）
   - scatter（散点图）
   - radar（雷达图）
   - heatmap（热力图）
   - bubble（气泡图）
   - treemap（树状图）
   - sankey（桑基图）
   或它们的组合
4. 输出文件名前缀：您希望的HTML文件名前缀是什么？（不含扩展名）

请按上述顺序提供您的选择，或直接表示使用全部默认值。
"""
        else:
            prompt = """
I need to generate an HTML report for you. Please provide the following parameters (if you don't specify a parameter, I will use the default value):

1. Report Title: What title would you like for the report?
2. Include Data Visualization Charts: yes/no (default yes)
3. Chart Types to Generate: Options include:
   - all (all types)
   - line (line charts)
   - bar (bar charts)
   - pie (pie charts)
   - scatter (scatter plots)
   - radar (radar charts)
   - heatmap (heat maps)
   - bubble (bubble charts)
   - treemap (tree maps)
   - sankey (sankey diagrams)
   or a combination of these
4. Output Filename Prefix: What prefix would you like for the HTML file name? (without extension)

Please provide your choices in the order above, or simply indicate to use all default values.
"""
        
        response = ask_llm(prompt)
        if not response:
            return {}
        
        # 解析模型回复
        params = {}
        
        # 尝试提取报告标题
        title_match = re.search(r'报告标题[：:]\s*(.+?)(?=\n|$)', response)
        if title_match and title_match.group(1).strip() and '默认' not in title_match.group(1):
            params['report_title'] = title_match.group(1).strip()
        
        # 尝试提取是否包含图表
        charts_match = re.search(r'包含[数据可视化]*图表[：:]\s*(yes|no|是|否)', response, re.IGNORECASE)
        if charts_match:
            include_value = charts_match.group(1).strip().lower()
            params['include_charts'] = include_value in ['yes', '是']
        
        # 尝试提取图表类型
        chart_types_match = re.search(r'图表类型[：:]\s*(.+?)(?=\n|$)', response)
        if chart_types_match:
            chart_types_str = chart_types_match.group(1).strip().lower()
            chart_types = []
            if 'all' in chart_types_str or '所有' in chart_types_str:
                chart_types = ['all']
            else:
                if 'line' in chart_types_str or '折线' in chart_types_str:
                    chart_types.append('line')
                if 'bar' in chart_types_str or '柱状' in chart_types_str:
                    chart_types.append('bar')
                if 'pie' in chart_types_str or '饼图' in chart_types_str:
                    chart_types.append('pie')
                if 'scatter' in chart_types_str or '散点' in chart_types_str:
                    chart_types.append('scatter')
                if 'radar' in chart_types_str or '雷达' in chart_types_str:
                    chart_types.append('radar')
                if 'heatmap' in chart_types_str or '热力' in chart_types_str:
                    chart_types.append('heatmap')
                if 'bubble' in chart_types_str or '气泡' in chart_types_str:
                    chart_types.append('bubble')
                if 'treemap' in chart_types_str or '树状' in chart_types_str:
                    chart_types.append('treemap')
                if 'sankey' in chart_types_str or '桑基' in chart_types_str:
                    chart_types.append('sankey')
            
            if chart_types:
                params['chart_types'] = chart_types
        
        # 尝试提取输出文件名
        filename_match = re.search(r'文件名[前缀]*[：:]\s*(.+?)(?=\n|$)', response)
        if filename_match and filename_match.group(1).strip() and '默认' not in filename_match.group(1):
            params['output_filename'] = filename_match.group(1).strip()
        
        return params
    
    except Exception as e:
        return {}

def get_apple_theme():
    """返回Apple风格的主题"""
    return {
        'primary_color': '#000000',      # 黑色
        'secondary_color': '#0066CC',    # 蓝色
        'accent_color': '#FF3B30',       # 红色点缀
        'text_color': '#1D1D1F',         # 近黑色文本
        'text_secondary': '#86868B',     # 灰色次要文本
        'background_color': '#FFFFFF',   # 白色背景
        'nav_bg': '#FFFFFF',             # 导航背景白色
        'nav_text': '#1D1D1F',           # 导航文字近黑色
        'chart_bg': '#F5F5F7'            # 图表背景浅灰色
    }

def extract_key_metrics(content, user_query=""):
    """从内容中提取关键指标"""
    try:
        # 判断用户查询的语言
        is_chinese = bool(re.search(r'[\u4e00-\u9fff]', user_query)) if user_query else True
        
        if is_chinese:
            prompt = f"""请从以下内容中提取3-5个关键指标或数据点，这些指标应该是报告中最重要的量化数据。

内容：
{content}

对于每个指标，请提供：
1. 指标名称（简短描述，如"年增长率"、"客户满意度"等）
2. 指标值（具体数值，包括单位）
3. 变化趋势（如"上升"、"下降"、"稳定"等，如果适用）
4. 指标的简短描述或解释

请以JSON格式返回结果：
{{
    "metrics": [
        {{
            "name": "指标名称",
            "value": "指标值",
            "trend": "变化趋势",
            "description": "简短描述"
        }},
        ...
    ]
}}

如果内容中没有合适的量化指标，请返回：
{{
    "metrics": []
}}
"""
        else:
            prompt = f"""Please extract 3-5 key metrics or data points from the following content. These metrics should be the most important quantitative data in the report.

Content:
{content}

For each metric, please provide:
1. Metric name (brief description, such as "Annual Growth Rate", "Customer Satisfaction", etc.)
2. Metric value (specific value, including units)
3. Change trend (such as "increasing", "decreasing", "stable", etc., if applicable)
4. Brief description or explanation of the metric

Please return the results in JSON format:
{{
    "metrics": [
        {{
            "name": "Metric Name",
            "value": "Metric Value",
            "trend": "Change Trend",
            "description": "Brief Description"
        }},
        ...
    ]
}}

If there are no suitable quantitative metrics in the content, please return:
{{
    "metrics": []
}}
"""
        
        response = ask_llm(prompt)
        
        try:
            # 提取JSON部分
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response
                
            # 清理可能导致JSON解析错误的字符
            json_str = json_str.strip()
            json_str = re.sub(r'```.*?```', '', json_str, flags=re.DOTALL)
            
            # 尝试解析JSON
            metrics_data = json.loads(json_str)
            
            # 确保metrics字段存在
            if 'metrics' not in metrics_data:
                metrics_data = {'metrics': []}
                
            return metrics_data['metrics']
        except json.JSONDecodeError as e:
            print(f"解析指标JSON时出错: {str(e)}")
            return []
        except Exception as e:
            print(f"处理指标时出错: {str(e)}")
            return []
    except Exception as e:
        print(f"提取关键指标时出错: {str(e)}")
        return []

def create_metric_cards_html(metrics):
    """将指标转换为HTML指标卡片"""
    if not metrics:
        return ""
    
    # 根据指标数量确定每行卡片数
    metrics_count = len(metrics)
    if metrics_count <= 3:
        cards_per_row = metrics_count
    else:
        cards_per_row = min(4, metrics_count)  # 最多4个卡片一行
    
    cards_html = []
    for metric in metrics:
        # 检查必需的字段是否存在
        if 'name' not in metric or 'value' not in metric:
            continue
            
        trend_icon = ""
        trend_color = ""
        if metric.get('trend') == 'up' or metric.get('trend', '').lower() == 'increasing':
            trend_icon = "↑"
            trend_color = "var(--accent-color)"
        elif metric.get('trend') == 'down' or metric.get('trend', '').lower() == 'decreasing':
            trend_icon = "↓"
            trend_color = "#FF9500"
        
        # 判断value是数值还是文本
        try:
            float(str(metric['value']).replace('%', '').replace(',', ''))
            is_number = True
        except ValueError:
            is_number = False
            
        # 为数值和文本创建不同的样式
        if is_number:
            value_html = f"""
            <div class="metric-value">{metric['value']} 
                <span class="trend-icon" style="color: {trend_color}">{trend_icon}</span>
            </div>
            """
        else:
            value_html = f"""
            <div class="metric-text-value">{metric['value']}</div>
            """
            
        card = f"""
        <div class="metric-card">
            <div class="metric-header">
                <div class="metric-label">{metric['name']}</div>
            </div>
            {value_html}
            <div class="metric-desc">{metric.get('description', '')}</div>
        </div>
        """
        cards_html.append(card)
    
    # 创建响应式布局
    metrics_html = f"""
    <div class="metrics-container">
        <div class="metrics-grid" style="grid-template-columns: repeat({cards_per_row}, 1fr);">
            {''.join(cards_html)}
        </div>
    </div>
    """
    
    return metrics_html

def generate_html_report_with_apple_theme(outline, sections, visualizations, user_query=""):
    """使用类Apple设计风格生成HTML报告"""
    print("生成HTML报告...")
    
    # 获取主题样式
    apple_theme = get_apple_theme()
    
    # 准备标题和副标题
    title = outline.get('title', '自动生成的报告')
    subtitle = outline.get('subtitle', '')
    
    # 提取所有内容，用于生成关键指标
    all_content = ""
    for section in sections:
        for subsection in section.get('subsections', []):
            all_content += str(subsection.get('content') or '') + "\n\n"
    
    # 提取关键指标
    metrics = extract_key_metrics(all_content, user_query)
    metrics_html = create_metric_cards_html(metrics)
    
    # 构建导航目录
    nav_items = []
    for i, section in enumerate(sections):
        section_id = f"section-{i+1}"
        nav_item = f'<li><a href="#{section_id}" class="nav-section-link">{section["title"]}</a><ul class="subsection-nav">'
        
        for j, subsection in enumerate(section['subsections']):
            subsection_id = f"subsection-{i+1}-{j+1}"
            nav_item += f'<li><a href="#{subsection_id}">{subsection["title"]}</a></li>'
        
        nav_item += '</ul></li>'
        nav_items.append(nav_item)
    
    nav_html = '\n'.join(nav_items)
    
    # 构建内容部分
    content_sections = []
    for i, section in enumerate(sections):
        section_id = f"section-{i+1}"
        section_html = f'<section id="{section_id}" class="main-section"><h2 class="section-title">{section["title"]}</h2>'
        
        for j, subsection in enumerate(section['subsections']):
            subsection_id = f"subsection-{i+1}-{j+1}"
            section_html += f'<div id="{subsection_id}" class="subsection"><h3 class="subsection-title">{subsection["title"]}</h3>'
            
            # 将Markdown格式的内容转换为HTML格式
            html_content = convert_markdown_to_html(subsection["content"])
            
            # 添加子章节内容
            section_html += f'<div class="content">{html_content}</div>'
            
            # 添加可视化图表（如果有）
            viz_id = f"{i+1}-{j+1}"
            if viz_id in visualizations and visualizations[viz_id]:
                viz = visualizations[viz_id]
                
                # 检查是否是交互式图表
                if viz.get('is_interactive', False) and 'chart_html' in viz:
                    # 使用交互式图表
                    section_html += f'''
                    <div class="chart-container">
                        <h4 class="chart-title">{viz['title']}</h4>
                        <div class="interactive-chart">{viz['chart_html']}</div>
                        <p class="chart-description">{viz['description']}</p>
                        <div class="chart-toggle">
                            <button class="toggle-button toggle-static" onclick="toggleChart('{viz_id}', 'static')">静态图表</button>
                            <button class="toggle-button toggle-interactive" onclick="toggleChart('{viz_id}', 'interactive')" style="display:none;">交互图表</button>
                        </div>
                        <div class="static-chart" style="display:none;">
                            <img src="data:image/png;base64,{viz['image_base64']}" alt="{viz['title']}" class="chart-image">
                        </div>
                    </div>
                    '''
                else:
                    # 使用静态图表
                    section_html += f'''
                    <div class="chart-container">
                        <h4 class="chart-title">{viz['title']}</h4>
                        <img src="data:image/png;base64,{viz['image_base64']}" alt="{viz['title']}" class="chart-image">
                        <p class="chart-description">{viz['description']}</p>
                    </div>
                    '''
            
            section_html += '</div>'
        
        section_html += '</section>'
        content_sections.append(section_html)
    
    content_html = '\n'.join(content_sections)
    
    # 获取当前日期
    now = datetime.datetime.now().strftime("%Y年%m月%d日")
    
    # HTML模板 - 使用Apple风格主题
    html_template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
    <style>
        :root {{
            --primary-color: {apple_theme['primary_color']};
            --secondary-color: {apple_theme['secondary_color']};
            --accent-color: {apple_theme['accent_color']};
            --text-color: {apple_theme['text_color']};
            --text-secondary: {apple_theme['text_secondary']};
            --background-color: {apple_theme['background_color']};
            --nav-bg: {apple_theme['nav_bg']};
            --nav-text: {apple_theme['nav_text']};
            --chart-bg: {apple_theme['chart_bg']};
            --nav-width: 280px;
            --transition-speed: 0.5s;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        @keyframes slideInLeft {{
            from {{ transform: translateX(-30px); opacity: 0; }}
            to {{ transform: translateX(0); opacity: 1; }}
        }}
        
        @keyframes scaleUp {{
            from {{ transform: scale(0.95); opacity: 0; }}
            to {{ transform: scale(1); opacity: 1; }}
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
            color: var(--text-color);
            background-color: var(--background-color);
            line-height: 1.5;
            display: flex;
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        
        #toc {{
            width: var(--nav-width);
            background-color: var(--nav-bg);
            color: var(--nav-text);
            padding: 2rem 1.5rem;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
            box-shadow: 0 0 20px rgba(0,0,0,0.03);
            z-index: 100;
            transition: transform 0.5s ease;
        }}
        
        #toc h1 {{
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            letter-spacing: -0.02em;
        }}
        
        #toc p {{
            margin-bottom: 2rem;
            font-size: 0.95rem;
            color: var(--text-secondary);
            font-weight: 300;
        }}
        
        #toc ul {{
            list-style: none;
        }}
        
        #toc ul li {{
            margin-bottom: 0.7rem;
        }}
        
        #toc ul li a {{
            color: var(--nav-text);
            text-decoration: none;
            transition: all 0.2s ease;
            display: block;
            padding: 0.4rem 0;
            font-weight: 400;
            border-radius: 5px;
        }}
        
        #toc ul li a:hover {{
            color: var(--secondary-color);
            transform: translateX(5px);
        }}
        
        #toc ul li a.active {{
            color: var(--secondary-color);
            font-weight: 500;
        }}
        
        .nav-section-link {{
            font-weight: 500 !important;
        }}
        
        .subsection-nav {{
            margin-left: 1rem !important;
            margin-top: 0.3rem !important;
            margin-bottom: 0.5rem !important;
            opacity: 0.9;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }}
        
        #toc ul li:hover .subsection-nav {{
            max-height: 500px;
        }}
        
        .nav-subsection-link {{
            font-size: 0.9rem !important;
            opacity: 0.9;
            padding: 0.3rem 0 0.3rem 0 !important;
        }}
        
        #menu-toggle {{
            display: none;
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 200;
            background: var(--secondary-color);
            border: none;
            color: white;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            font-size: 24px;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        #content {{
            flex: 1;
            margin-left: var(--nav-width);
            padding: 3rem 5rem;
            max-width: calc(100% - var(--nav-width));
            animation: fadeIn 0.8s ease-out;
        }}
        
        header {{
            margin-bottom: 2.5rem;
            animation: slideInLeft 0.8s ease-out;
        }}
        
        header h1 {{
            font-size: 3.5rem;
            color: var(--primary-color);
            margin-bottom: 1rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            line-height: 1.1;
        }}
        
        header p.subtitle {{
            font-size: 1.5rem;
            color: var(--text-secondary);
            margin-bottom: 1.5rem;
            font-weight: 300;
            max-width: 36rem;
        }}
        
        header .meta {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-weight: 300;
        }}

        .report-metrics {{
            margin: 2.5rem 0 4rem 0;
            padding: 1.5rem;
            background-color: rgba(245, 247, 250, 0.7);
            border-radius: 16px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.03);
            animation: scaleUp 0.6s ease-out;
        }}
        
        .main-section {{
            margin-bottom: 6rem;
            opacity: 0;
            transform: translateY(20px);
            transition: opacity 0.8s, transform 0.8s;
        }}
        
        .main-section.visible {{
            opacity: 1;
            transform: translateY(0);
        }}
        
        .section-title {{
            font-size: 2.5rem;
            color: var(--primary-color);
            margin-bottom: 2.5rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            opacity: 0;
            transform: translateY(20px);
            transition: opacity 0.5s, transform 0.5s;
        }}
        
        .section-title.visible {{
            opacity: 1;
            transform: translateY(0);
        }}
        
        .subsection {{
            margin-bottom: 3.5rem;
            background-color: white;
            padding: 2.5rem;
            border-radius: 16px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.04);
            transition: transform 0.4s, box-shadow 0.4s;
            opacity: 0;
            transform: translateY(20px);
            transition-delay: 0.1s;
        }}
        
        .subsection.visible {{
            opacity: 1;
            transform: translateY(0);
        }}
        
        .subsection:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 60px rgba(0,0,0,0.07);
        }}
        
        .subsection-title {{
            font-size: 1.8rem;
            color: var(--text-color);
            margin-bottom: 1.5rem;
            font-weight: 600;
            letter-spacing: -0.01em;
        }}
        
        .content {{
            margin-bottom: 2rem;
            line-height: 1.7;
        }}
        
        .content p {{
            margin-bottom: 1.2rem;
            font-size: 1.05rem;
        }}
        
        /* 指标卡片样式 */
        .metrics-container {{
            margin: 1.5rem 0 2.5rem 0;
            animation: scaleUp 0.5s ease-out;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
        }}
        
        .metric-card {{
            background: linear-gradient(145deg, rgba(255,255,255,0.5), rgba(240,240,245,0.5));
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 5px 15px rgba(0,0,0,0.03);
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(230,230,230,0.7);
            display: flex;
            flex-direction: column;
            position: relative;
        }}
        
        .metric-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.05);
        }}
        
        .metric-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.8rem;
        }}
        
        .metric-label {{
            color: var(--text-secondary);
            font-size: 0.95rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        
        .metric-value {{
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--primary-color);
            margin-bottom: 0.5rem;
            letter-spacing: -0.03em;
            line-height: 1.1;
        }}
        
        .metric-text-value {{
            font-size: 1.6rem;
            font-weight: 600;
            color: var(--secondary-color);
            margin-bottom: 0.5rem;
            letter-spacing: -0.01em;
            line-height: 1.3;
        }}
        
        .trend-icon {{
            font-size: 1rem;
            margin-left: 0.3rem;
            vertical-align: middle;
        }}
        
        .metric-desc {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            line-height: 1.5;
            flex-grow: 1;
        }}
        
        /* Markdown 内容样式 */
        .content h1, .content h2, .content h3, .content h4, .content h5, .content h6 {{
            color: var(--text-color);
            margin: 2rem 0 1rem 0;
            font-weight: 600;
            letter-spacing: -0.01em;
        }}
        
        .content h4 {{
            font-size: 1.4rem;
        }}
        
        .content h5 {{
            font-size: 1.2rem;
        }}
        
        .content h6 {{
            font-size: 1.1rem;
        }}
        
        .content ul, .content ol {{
            margin-left: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .content li {{
            margin-bottom: 0.7rem;
        }}
        
        .content strong {{
            color: var(--primary-color);
            font-weight: 600;
        }}
        
        .content blockquote {{
            border-left: 3px solid var(--secondary-color);
            padding: 1rem 0 1rem 1.5rem;
            margin: 1.5rem 0;
            font-style: italic;
            color: var(--text-secondary);
            background-color: rgba(0,0,0,0.02);
            border-radius: 0 8px 8px 0;
        }}
        
        .content code {{
            background-color: rgba(0,0,0,0.05);
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            font-family: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.9em;
        }}
        
        .content pre {{
            background-color: #f8f8f8;
            padding: 1.2rem;
            border-radius: 8px;
            overflow-x: auto;
            margin: 1.5rem 0;
        }}
        
        .content pre code {{
            background-color: transparent;
            padding: 0;
        }}
        
        .content table {{
            border-collapse: collapse;
            width: 100%;
            margin: 2rem 0;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 0 20px rgba(0,0,0,0.05);
        }}
        
        .content th, .content td {{
            border: none;
            padding: 1rem;
            text-align: left;
        }}
        
        .content th {{
            background-color: rgba(0,0,0,0.03);
            font-weight: 600;
        }}
        
        .content tr:nth-child(even) {{
            background-color: rgba(0,0,0,0.01);
        }}
        
        .content tr {{
            transition: background-color 0.3s;
        }}
        
        .content tr:hover {{
            background-color: rgba(0,0,0,0.03);
        }}
        
        .chart-container {{
            margin-top: 3rem;
            padding: 2rem;
            background-color: var(--chart-bg);
            border-radius: 16px;
            box-shadow: 0 8px 30px rgba(0,0,0,0.04);
            text-align: center;
            transition: transform 0.4s, box-shadow 0.4s;
            overflow: hidden;
            opacity: 0;
            transform: scale(0.95);
        }}
        
        .chart-container.visible {{
            opacity: 1;
            transform: scale(1);
        }}
        
        .chart-container:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 50px rgba(0,0,0,0.08);
        }}
        
        .chart-title {{
            color: var(--text-color);
            margin-bottom: 1.5rem;
            font-size: 1.5rem;
            font-weight: 600;
            letter-spacing: -0.01em;
        }}
        
        .chart-image {{
            max-width: 85%;
            height: auto;
            margin: 0 auto 2rem auto;
            border-radius: 8px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.08);
            transition: transform 0.4s;
        }}
        
        .chart-image:hover {{
            transform: scale(1.02);
        }}
        
        .interactive-chart {{
            width: 100%;
            height: 500px;
            margin: 0 auto 2rem auto;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 5px 20px rgba(0,0,0,0.08);
            transition: transform 0.3s;
        }}
        
        .interactive-chart:hover {{
            transform: scale(1.01);
        }}
        
        .chart-description {{
            color: var(--text-secondary);
            max-width: 85%;
            margin: 0 auto 1.5rem;
            font-size: 0.95rem;
            line-height: 1.6;
            font-weight: 300;
        }}
        
        .chart-toggle {{
            margin-top: 1.5rem;
        }}
        
        .toggle-button {{
            background-color: var(--secondary-color);
            color: white;
            border: none;
            padding: 0.7rem 1.5rem;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
            margin: 0 5px;
            font-weight: 500;
            transition: all 0.3s;
            box-shadow: 0 4px 10px rgba(0, 102, 204, 0.2);
        }}
        
        .toggle-button:hover {{
            background-color: #0052a5;
            transform: translateY(-2px);
            box-shadow: 0 6px 15px rgba(0, 102, 204, 0.3);
        }}
        
        .toggle-button:active {{
            transform: translateY(0);
            box-shadow: 0 2px 5px rgba(0, 102, 204, 0.2);
        }}
        
        @media (max-width: 1200px) {{
            #content {{
                padding: 3rem;
            }}
            
            header h1 {{
                font-size: 3rem;
            }}
            
            .section-title {{
                font-size: 2.2rem;
            }}
            
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
        
        @media (max-width: 1024px) {{
            :root {{
                --nav-width: 250px;
            }}
            
            #content {{
                padding: 2.5rem;
            }}
            
            header h1 {{
                font-size: 2.8rem;
            }}
            
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
        
        @media (max-width: 768px) {{
            #menu-toggle {{
                display: block;
            }}
            
            #toc {{
                transform: translateX(-100%);
                box-shadow: 0 0 20px rgba(0,0,0,0.1);
            }}
            
            #toc.active {{
                transform: translateX(0);
            }}
            
            #content {{
                margin-left: 0;
                max-width: 100%;
                padding: 2rem;
            }}
            
            header h1 {{
                font-size: 2.5rem;
            }}
            
            .section-title {{
                font-size: 2rem;
            }}
            
            .subsection {{
                padding: 1.8rem;
            }}
            
            .metrics-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        
        @media (max-width: 480px) {{
            #content {{
                padding: 1.5rem;
            }}
            
            header h1 {{
                font-size: 2.2rem;
            }}
            
            .section-title {{
                font-size: 1.8rem;
            }}
            
            .subsection-title {{
                font-size: 1.5rem;
            }}
            
            .subsection {{
                padding: 1.5rem;
            }}
            
            .metric-value {{
                font-size: 1.8rem;
            }}
        }}
    </style>
</head>
<body>
    <button id="menu-toggle" onclick="toggleMenu()">
        <span>≡</span>
    </button>
    
    <nav id="toc">
        <h1>{title}</h1>
        <p>{subtitle}</p>
        <ul>
            {nav_html}
        </ul>
    </nav>
    
    <main id="content">
        <header>
            <h1>{title}</h1>
            <p class="subtitle">{subtitle}</p>
            <div class="meta">生成日期: {now}</div>
        </header>
        
        <!-- 全局指标卡片 -->
        <div class="report-metrics">
            {metrics_html}
        </div>
        
        {content_html}
    </main>
    
    <script>
        // 菜单切换功能
        function toggleMenu() {{
            document.getElementById('toc').classList.toggle('active');
        }}
        
        // 设置平滑滚动
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {{
            anchor.addEventListener('click', function(e) {{
                e.preventDefault();
                
                // 在移动设备上点击菜单链接后关闭菜单
                if (window.innerWidth <= 768) {{
                    document.getElementById('toc').classList.remove('active');
                }}
                
                const targetId = this.getAttribute('href').substring(1);
                const targetElement = document.getElementById(targetId);
                
                if (targetElement) {{
                    const offsetTop = targetElement.getBoundingClientRect().top + window.pageYOffset - 50;
                    
                    window.scrollTo({{
                        top: offsetTop,
                        behavior: 'smooth'
                    }});
                }}
            }});
        }});
        
        // 处理滚动，高亮当前章节并触发动画
        const animateOnScroll = () => {{
            // 动画元素
            const sections = document.querySelectorAll('.main-section');
            const sectionTitles = document.querySelectorAll('.section-title');
            const subsections = document.querySelectorAll('.subsection');
            const charts = document.querySelectorAll('.chart-container');
            
            // 视口高度
            const viewportHeight = window.innerHeight;
            
            // 为每个元素检查是否在视口中并添加动画类
            const addVisibleClass = (elements) => {{
                elements.forEach(element => {{
                    const bounding = element.getBoundingClientRect();
                    const isInViewport = bounding.top < viewportHeight * 0.85;
                    
                    if (isInViewport) {{
                        element.classList.add('visible');
                    }}
                }});
            }};
            
            // 高亮当前章节
            let currentSectionId = '';
            sections.forEach(section => {{
                const sectionTop = section.offsetTop;
                const sectionHeight = section.clientHeight;
                if (window.pageYOffset >= sectionTop - 300) {{
                    currentSectionId = section.getAttribute('id');
                }}
            }});
            
            if (currentSectionId) {{
                document.querySelectorAll('#toc a').forEach(a => {{
                    a.classList.remove('active');
                }});
                
                const activeLink = document.querySelector(`#toc a[href="#${{currentSectionId}}"]`);
                if (activeLink) {{
                    activeLink.classList.add('active');
                }}
            }}
            
            // 触发各元素的动画
            addVisibleClass(sections);
            addVisibleClass(sectionTitles);
            addVisibleClass(subsections);
            addVisibleClass(charts);
        }};
        
        // 页面加载时和滚动时执行动画
        window.addEventListener('load', animateOnScroll);
        window.addEventListener('scroll', animateOnScroll);
        
        // 图表切换功能
        function toggleChart(chartId, mode) {{
            const container = document.querySelector(`#subsection-${{chartId}} .chart-container`);
            if (!container) return;
            
            const interactiveChart = container.querySelector('.interactive-chart');
            const staticChart = container.querySelector('.static-chart');
            const toggleStatic = container.querySelector('.toggle-static');
            const toggleInteractive = container.querySelector('.toggle-interactive');
            
            if (mode === 'static') {{
                if (interactiveChart) interactiveChart.style.display = 'none';
                if (staticChart) staticChart.style.display = 'block';
                if (toggleStatic) toggleStatic.style.display = 'none';
                if (toggleInteractive) toggleInteractive.style.display = 'inline-block';
            }} else {{
                if (interactiveChart) interactiveChart.style.display = 'block';
                if (staticChart) staticChart.style.display = 'none';
                if (toggleStatic) toggleStatic.style.display = 'inline-block';
                if (toggleInteractive) toggleInteractive.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>'''
    
    return html_template

def save_html_report(html_content, report_name="report"):
    """保存HTML报告到工作区"""
    workspace_path = get_workspace_path()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 清理文件名，移除Windows不允许的字符 (: * ? " < > | \ / )
    safe_report_name = re.sub(r'[\\/:*?"<>|]', '_', report_name)
    
    filename = f"{safe_report_name}_{timestamp}.html"
    filepath = os.path.join(workspace_path, filename)
    
    print(f"正在保存HTML报告到: {filepath}")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML报告保存成功")
        return filepath
    except Exception as e:
        print(f"保存HTML报告时出错: {str(e)}")
        return None

def create_html_report(title=None, include_charts=True, chart_types=['all'], output_filename=None, user_query=""):
    """创建HTML报告的主函数"""
    try:
        print("=" * 50)
        print("开始创建HTML报告")
        print("=" * 50)
        print(user_query)
        # 步骤1: 读取工作区文件
        print("\n[步骤1/6] 读取工作区文件")
        text_files = read_text_files_from_workspace()
        if not text_files:
            return {
                "status": "error",
                "message": "工作区中没有找到文本文件，请先保存一些文本文件"
            }
        
        # 步骤2: 生成报告大纲
        print("\n[步骤2/6] 生成报告大纲")
        outline = generate_outline(text_files, user_query)
        if outline is None:
            return {
                "status": "error",
                "message": "生成报告大纲时出错，无法解析LLM返回的内容"
            }
        
        # 如果提供了标题，覆盖大纲中的标题
        if title:
            outline['title'] = title
            print(f"使用自定义标题: {title}")
        else:
            print(f"使用生成的标题: {outline['title']}")
        
        # 步骤3: 根据大纲重新组织内容
        print("\n[步骤3/6] 根据大纲重新组织内容")
        sections = reorganize_content(text_files, outline, user_query)
        if not sections:
            return {
                "status": "error",
                "message": "重新组织内容时出错"
            }
        
        # 步骤4: 分析每个子章节，判断是否适合生成图表
        print("\n[步骤4/6] 分析内容并生成可视化")
        visualizations = {}
        chart_templates = {}
        
        if include_charts:
            # 如果指定了"all"，包含所有图表类型
            if 'all' in chart_types:
                chart_types = ['line', 'bar', 'pie', 'scatter', 'radar', 'heatmap', 'bubble', 'treemap', 'sankey']
                
            print(f"包含图表类型: {', '.join(chart_types)}")
            
            # 创建线程安全的字典用于存储可视化结果
            viz_lock = threading.Lock()
            template_lock = threading.Lock()
            
            # 创建一个计数器，用于显示进度
            total_subsections = sum(len(section['subsections']) for section in sections)
            processed_count = 0
            progress_lock = threading.Lock()
            
            print(f"总共需要处理 {total_subsections} 个子章节")
            
            def process_visualization(i, section, j, subsection):
                """处理单个子章节的可视化，将在独立线程中运行"""
                nonlocal processed_count
                
                try:
                    viz_id = f"{i+1}-{j+1}"
                    
                    with progress_lock:
                        processed_count += 1
                        print(f"\n处理小节 ({processed_count}/{total_subsections}): {subsection['title']}")
                    
                    # 分析内容是否适合生成图表
                    viz_info = analyze_content_for_visualization(subsection['content'], user_query)
                    
                    if not viz_info.get('suitable_for_visualization', False):
                        return None
                    
                    # 使用图表类型过滤
                    chart_type = viz_info.get('chart_type', '').lower()
                    chart_match = False
                    
                    if 'all' in chart_types:
                        chart_match = True
                    elif chart_type in ['折线图', '线图', 'line chart', 'line graph', 'line plot'] and 'line' in chart_types:
                        chart_match = True
                    elif chart_type in ['柱状图', '条形图', 'bar chart', 'bar graph', 'histogram'] and 'bar' in chart_types:
                        chart_match = True
                    elif chart_type in ['饼图', '圆饼图', 'pie chart'] and 'pie' in chart_types:
                        chart_match = True
                    elif chart_type in ['散点图', 'scatter plot', 'scatter graph'] and 'scatter' in chart_types:
                        chart_match = True
                    elif chart_type in ['雷达图', 'radar chart', 'radar plot', 'spider chart'] and 'radar' in chart_types:
                        chart_match = True
                    elif chart_type in ['热力图', 'heatmap', 'heat map'] and 'heatmap' in chart_types:
                        chart_match = True
                    elif chart_type in ['气泡图', 'bubble chart', 'bubble plot'] and 'bubble' in chart_types:
                        chart_match = True
                    elif chart_type in ['树状图', 'treemap', 'tree map'] and 'treemap' in chart_types:
                        chart_match = True
                    elif chart_type in ['桑基图', 'sankey diagram', 'sankey chart'] and 'sankey' in chart_types:
                        chart_match = True
                    
                    if not chart_match:
                        return None
                    
                    # 创建可视化
                    viz = create_visualization(viz_info, chart_types)
                    if not viz:
                        return None
                    
                    # 生成图表代码模板
                    template = {
                        'title': subsection['title'],
                        'chart_type': viz_info.get('chart_type', ''),
                        'template': generate_chart_code_template(viz_info)
                    }
                    
                    with progress_lock:
                        print(f"已为小节 '{subsection['title']}' 生成图表")
                    
                    # 安全地将结果添加到共享字典中
                    with viz_lock:
                        visualizations[viz_id] = viz
                    
                    with template_lock:
                        chart_templates[viz_id] = template
                    
                    return viz_id
                    
                except Exception as e:
                    return None
            
            # 准备所有可视化任务
            tasks = []
            for i, section in enumerate(sections):
                for j, subsection in enumerate(section['subsections']):
                    tasks.append((i, section, j, subsection))
            
            # 确定线程池大小，避免创建过多线程
            max_workers = min(10, max(1, min(os.cpu_count() or 4, total_subsections)))
            print(f"将使用 {max_workers} 个线程并行处理可视化")
            
            # 使用线程池并行处理所有可视化任务
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(process_visualization, *task) for task in tasks]
                
                # 等待所有任务完成
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as e:
                        print(f"获取可视化结果时出错: {str(e)}")
            
            print(f"所有 {total_subsections} 个子章节的可视化处理完成")
            print(f"共生成了 {len(visualizations)} 个图表")
            
        else:
            print("生成内容不包含可视化数据，跳过图表生成")
        
        # 步骤5: 使用商务风格主题生成HTML报告
        print(f"\n[步骤5/6] 生成HTML报告")
        html_content = generate_html_report_with_apple_theme(outline, sections, visualizations, user_query)
        
        # 步骤6: 保存HTML报告
        print(f"\n[步骤6/6] 保存HTML报告")
        if output_filename:
            filename_prefix = output_filename
        else:
            # 使用标题但确保不含无效字符
            filename_prefix = outline['title'].replace(' ', '_')
            
        report_path = save_html_report(html_content, report_name=filename_prefix)
        
        if report_path:
            # 将图表模板也保存到工作区
            if chart_templates:
                # 确保模板文件名也不含无效字符
                safe_filename_prefix = re.sub(r'[\\/:*?"<>|]', '_', filename_prefix)
                templates_path = os.path.join(get_workspace_path(), f"{safe_filename_prefix}_chart_templates.py")
                print(f"保存图表模板到: {templates_path}")
                with open(templates_path, 'w', encoding='utf-8') as f:
                    f.write("# 图表生成模板\n\n")
                    for viz_id, template_info in chart_templates.items():
                        f.write(f"# {template_info['title']} - {template_info['chart_type']}\n")
                        f.write(template_info['template'])
                        f.write("\n\n")
                print(f"图表模板保存成功")
            
            print("\n" + "=" * 50)
            print(f"HTML报告生成完成: {report_path}")
            if chart_templates:
                print(f"图表模板已保存: {templates_path}")
            print("=" * 50)
            
            return {
                "status": "success",
                "message": f"报告已成功生成并保存到: {report_path}",
                "report_path": report_path,
                "templates_path": templates_path if chart_templates else None
            }
        else:
            return {
                "status": "error",
                "message": "保存报告时出错"
            }
            
    except Exception as e:
        print(f"\n报告生成失败: {str(e)}")
        print(f"详细错误: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"创建HTML报告时发生错误: {str(e)}"
        }

# 主函数入口
def main(params=None):
    """主函数入口点
    这个函数会被Agent框架调用，不需要传入参数
    会在运行过程中与大模型交互获取所需参数
    """
    try:
        print("\n" + "=" * 60)
        print("HTML可视化报告生成工具")
        print("=" * 60)
        
        # 从参数中获取用户查询（如果有的话）
        user_query = ""
        if params and isinstance(params, dict) and 'user_query' in params:
            user_query = params['user_query']
        
        print("\n正在与模型交互获取报告参数...")
        
        # 与大模型交互获取参数
        user_params = ask_model_for_parameters(user_query)
        
        print("\n获取到的参数:")
        if user_params.get('report_title'):
            print(f"- 报告标题: {user_params.get('report_title')}")
        if 'include_charts' in user_params:
            print(f"- 包含图表: {'是' if user_params.get('include_charts', True) else '否'}")
        if user_params.get('chart_types'):
            print(f"- 图表类型: {', '.join(user_params.get('chart_types', ['all']))}")
        if user_params.get('output_filename'):
            print(f"- 输出文件名: {user_params.get('output_filename')}")
            
        print("\n开始生成HTML报告...")
        
        # 使用获取到的参数创建报告
        result = create_html_report(
            title=user_params.get('report_title'),
            include_charts=user_params.get('include_charts', True),
            chart_types=user_params.get('chart_types', ['all']),
            output_filename=user_params.get('output_filename'),
            user_query=user_query
        )
        
        if result["status"] == "success":
            print(f"报告生成成功: {result['report_path']}")
        else:
            print(f"报告生成失败: {result['message']}")
            
        return result
    except Exception as e:
        print(f"执行HTML报告生成工具时出错: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"执行出错: {str(e)}"
        }

if __name__ == "__main__":
    result = main()
    print(json.dumps(result, ensure_ascii=False, indent=2))

