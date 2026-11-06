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

import json
import os
from typing import List, Dict, Any, Optional
from app.common.logger_util import logger
from app.cosight.llm.chat_llm import ChatLLM
from config.config import get_credibility_model_config
from llm import set_model
from .i18n_service import i18n


class CredibilityAnalyzer:
    """可信信息分析器，用于分析步骤结果并生成可信信息总结"""
    
    def __init__(self):
        """初始化可信信息分析器"""
        self.llm = None  # 延迟初始化
        self.credibility_types_zh = {
            "truth": "常识或者真理",
            "verified_facts": "给定或者已验证的事实", 
            "searchable_facts": "需要查找的事实",
            "derived_facts": "需要推导的事实",
            "educated_guess": "有根据的猜测"
        }
        self.credibility_types_en = {
            "truth": "Common Sense or Truth",
            "verified_facts": "Given or Verified Facts", 
            "searchable_facts": "Searchable Facts",
            "derived_facts": "Derived Facts",
            "educated_guess": "Educated Guess"
        }
    
    def _detect_language(self, text: str) -> str:
        """检测文本语言，返回'zh'或'en'"""
        if not text:
            return 'zh'  # 默认中文
        
        # 检查是否包含中文字符（包括中文标点）
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff' or '\u3000' <= char <= '\u303f')
        
        # 如果包含中文字符，优先判断为中文
        if chinese_chars > 0:
            return 'zh'
        
        # 如果没有中文字符，检查是否主要是英文
        english_chars = sum(1 for char in text if char.isalpha() and ord(char) < 128)
        if english_chars > 0:
            return 'en'
        
        # 默认中文
        return 'zh'
    
    def _get_credibility_types(self, language: str) -> Dict[str, str]:
        """根据语言获取可信度类型定义"""
        if language == 'en':
            return self.credibility_types_en
        else:
            return self.credibility_types_zh
    
    def _init_llm(self) -> Optional[ChatLLM]:
        """初始化LLM客户端"""
        try:
            if self.llm is not None:
                return self.llm
                
            # 获取可信信息分析专用配置
            model_config = get_credibility_model_config()
            logger.info(f"可信信息分析LLM配置: {model_config}")
            
            # 创建ChatLLM实例
            self.llm = set_model(model_config)
            logger.info("可信信息分析LLM初始化成功")
            return self.llm
            
        except Exception as e:
            logger.error(f"初始化可信信息分析LLM失败: {str(e)}", exc_info=True)
            return None
    
    def _get_credibility_prompt(self, step_content: str, all_steps_content: str, tool_events_summary: str, tool_events_json: str, language: str = 'zh') -> str:
        """生成可信信息分析的prompt，关注工具结果内容而非调用过程。"""
        if language == 'en':
            return self._get_credibility_prompt_en(step_content, all_steps_content, tool_events_summary, tool_events_json)
        else:
            return self._get_credibility_prompt_zh(step_content, all_steps_content, tool_events_summary, tool_events_json)
    
    def _get_credibility_prompt_zh(self, step_content: str, all_steps_content: str, tool_events_summary: str, tool_events_json: str) -> str:
        """生成中文可信信息分析的prompt"""
        return f"""你是一个专业的信息可信度分析师。请基于以下工具执行结果中获取的具体信息内容，按照5种可信度类型进行总结。

**任务背景：**
当前步骤：{step_content}
已完成步骤：{all_steps_content}

**工具执行结果内容：**
{tool_events_summary}

**详细结果数据：**
```json
{tool_events_json}
```

**分析要求：**
请从上述工具结果中提取出与任务相关的具体信息内容，按照以下可信度类型进行分类总结。重点关注工具返回的实际数据、事实、观点等有价值的信息，而不是工具调用过程本身。

**可信度分类定义：**

1. **常识或者真理 (Truth/Common Sense)**
   - 定义：被广泛接受的基础事实和逻辑真理
   - 特征：无需验证、普遍认可、逻辑自洽

2. **给定或者已验证的事实 (Given/Verified Facts)**
   - 定义：来自权威来源或已通过不同信息源反复验证的明确事实
   - 特征：官方文档、权威数据、PDF文件、学术论文

3. **查找的事实 (Searchable Facts)**
   - 定义：通过网络搜索或数据库查询获取的事实信息
   - 特征：搜索结果、网页内容、实时数据、最新信息

4. **推导的事实 (Derived Facts)**
   - 定义：基于获取的信息通过逻辑推理得出的结论
   - 特征：基于数据的分析、趋势推断、因果关系

5. **有根据的猜测 (Educated Guess)**
   - 定义：基于有限信息做出的合理推测和观点
   - 特征：专家观点、市场预测、可能性分析

**输出要求：**
1) 每类至少1条、至多2条，单句不超过100字
2) 重点描述从工具结果中提取的具体信息内容，而非工具调用过程
3) 在句末注明信息来源（如：来自"搜索结果/官方数据/专家分析"）
4) 确保信息对用户任务有直接价值和指导意义，避免重复、冗余、无关信息

**输出格式（严格按此JSON格式）：**
```json
{{
    "truth": ["常识或真理1", "常识或真理2"],
    "verified_facts": ["已验证事实1", "已验证事实2"],
    "searchable_facts": ["需查找事实1", "需查找事实2"],
    "derived_facts": ["需推导事实1", "需推导事实2"],
    "educated_guess": ["有根据猜测1", "有根据猜测2"]
}}
```

请开始分析："""
    
    def _get_credibility_prompt_en(self, step_content: str, all_steps_content: str, tool_events_summary: str, tool_events_json: str) -> str:
        """生成英文可信信息分析的prompt"""
        return f"""You are a professional information credibility analyst. Please analyze the specific information content obtained from the following tool execution results and summarize according to 5 credibility types.

**Task Background:**
Current Step: {step_content}
Completed Steps: {all_steps_content}

**Tool Execution Results:**
{tool_events_summary}

**Detailed Result Data:**
```json
{tool_events_json}
```

**Analysis Requirements:**
Please extract specific information content related to the task from the above tool results and classify and summarize according to the following credibility types. Focus on the actual data, facts, opinions and other valuable information returned by the tools, rather than the tool invocation process itself.

**Credibility Classification Definitions:**

1. **Common Sense or Truth**
   - Definition: Widely accepted basic facts and logical truths
   - Characteristics: No verification needed, universally recognized, logically consistent

2. **Given or Verified Facts**
   - Definition: Clear facts from authoritative sources or verified through multiple information sources
   - Characteristics: Official documents, authoritative data, PDF files, academic papers

3. **Searchable Facts**
   - Definition: Factual information obtained through web search or database queries
   - Characteristics: Search results, web content, real-time data, latest information

4. **Derived Facts**
   - Definition: Conclusions drawn through logical reasoning based on acquired information
   - Characteristics: Data-based analysis, trend inference, causal relationships

5. **Educated Guess**
   - Definition: Reasonable speculation and opinions based on limited information
   - Characteristics: Expert opinions, market predictions, possibility analysis

**Output Requirements:**
1) At least 1, at most 2 items per category, single sentence not exceeding 50 words
2) Focus on describing specific information content extracted from tool results, not tool invocation process
3) Note information source at the end of sentence (e.g., from "search results/official data/expert analysis")
4) Ensure information has direct value and guidance significance for user tasks, avoid repetition, redundancy, irrelevant information

**Output Format (strictly follow this JSON format):**
```json
{{
    "truth": ["common sense or truth 1", "common sense or truth 2"],
    "verified_facts": ["verified fact 1", "verified fact 2"],
    "searchable_facts": ["searchable fact 1", "searchable fact 2"],
    "derived_facts": ["derived fact 1", "derived fact 2"],
    "educated_guess": ["educated guess 1", "educated guess 2"]
}}
```

Please start analysis:"""

    async def analyze_step_credibility(self, current_step: Dict[str, Any], all_completed_steps: List[Dict[str, Any]], tool_events: List[Dict[str, Any]] | None = None) -> Optional[Dict[str, List[str]]]:
        """分析步骤的可信信息
        
        Args:
            current_step: 当前完成的步骤信息
            all_completed_steps: 所有已完成的步骤信息
            tool_events: 工具事件列表
            
        Returns:
            可信信息分析结果，格式为 {类型: [总结句子列表]}
        """
        logger.info(f"可信信息分析器开始工作")
        
        # 初始化LLM
        llm = self._init_llm()
        if not llm:
            logger.warning("LLM初始化失败，跳过可信信息分析")
            return None
            
        try:
            # 检测语言
            step_title = current_step.get('title', '')
            language = self._detect_language(step_title)
            logger.info(f"检测到语言: {language}, 步骤标题: {step_title}")
            
            # 构建当前步骤内容
            current_content = self._format_step_content(current_step)
            
            # 仅构建当前步骤内容，取消拼接所有已完成步骤内容以降低长度
            all_content = ""
            
            # 工具事件摘要与原始结果（精简JSON）
            tool_events = tool_events or []
            tool_events_summary = self._format_tool_events_summary(tool_events)
            tool_events_json = self._format_tool_events_json(tool_events)

            # 生成prompt（根据语言选择对应的提示词）
            prompt = self._get_credibility_prompt(current_content, all_content, tool_events_summary, tool_events_json, language)
            
            # 调用LLM分析
            messages = [{"role": "user", "content": prompt}]
            logger.info(f"开始调用LLM进行可信信息分析，语言: {language}, prompt长度: {len(prompt)}")
            
            # 使用 asyncio.to_thread 在线程池中执行同步的 LLM 调用，避免阻塞事件循环
            # 这样可信分析就不会阻塞 manus 主流程
            import asyncio
            response = await asyncio.to_thread(llm.chat_to_llm, messages)
            logger.info(f"LLM响应长度: {len(response) if response else 0}")
            
            # 解析响应并补全五类
            credibility_result = self._parse_llm_response(response)
            credibility_result = self._ensure_complete_result(
                credibility_result,
                current_step,
                all_completed_steps,
                tool_events,
                language
            )
            logger.info(f"解析结果: {credibility_result}")
            
            logger.info(f"可信信息分析完成，当前步骤: {current_step.get('title', 'Unknown')}, 语言: {language}")
            return credibility_result
            
        except Exception as e:
            logger.error(f"可信信息分析失败: {str(e)}", exc_info=True)
            return None

    def _format_tool_events_summary(self, tool_events: List[Dict[str, Any]]) -> str:
        if not tool_events:
            return "(无工具调用记录)"
        lines: List[str] = []
        max_items = 20
        for idx, evt in enumerate(tool_events[-max_items:]):
            summary = evt.get("summary") or ""
            # 补齐常见字段
            tool_name = evt.get("tool_name") or evt.get("name") or "tool"
            args = evt.get("tool_args") or evt.get("args")
            result = evt.get("tool_result") or evt.get("result") or evt.get("output")
            if isinstance(result, (dict, list)):
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except Exception:
                    result = str(result)
            if not summary:
                # 从原始结构回退提取
                if isinstance(evt.get("raw"), dict):
                    try:
                        raw = evt["raw"]
                        content = raw.get("content") or {}
                        tool_name = content.get("toolName") or content.get("name") or tool_name
                        status = content.get("status") or content.get("resultStatus") or "ok"
                        result = content.get("output") or content.get("result") or result
                        if isinstance(result, (dict, list)):
                            result = json.dumps(result, ensure_ascii=False)
                        summary = f"[{tool_name}] {status} {str(result)[:300] if result else ''}"
                    except Exception:
                        summary = f"[{tool_name}] {str(result)[:300] if result else ''}"
                else:
                    summary = f"[{tool_name}] {str(result)[:300] if result else ''}"
            lines.append(f"- {summary}")
        if len(tool_events) > max_items:
            lines.append(f"(其余 {len(tool_events)-max_items} 条已省略)")
        return "\n".join(lines)

    def _format_tool_events_json(self, tool_events: List[Dict[str, Any]]) -> str:
        """将工具事件精简为适合放入 Prompt 的 JSON 字符串。

        仅保留关键信息，并限制每条输出的长度，避免提示词过长。
        """
        slim_events: List[Dict[str, Any]] = []
        max_items = 10
        for evt in tool_events[-max_items:]:
            tool_name = evt.get("tool_name") or evt.get("name") or "tool"
            args = evt.get("tool_args") or evt.get("args")
            result = evt.get("tool_result") or evt.get("result") or evt.get("output")
            if isinstance(result, (dict, list)):
                try:
                    result = json.dumps(result, ensure_ascii=False)
                except Exception:
                    result = str(result)
            if isinstance(args, (dict, list)):
                try:
                    args = json.dumps(args, ensure_ascii=False)
                except Exception:
                    args = str(args)
            slim_events.append({
                "tool": tool_name,
                "args": (str(args)[:300] if args else None),
                "result": (str(result)[:600] if result else None),
                "timestamp": evt.get("timestamp")
            })
        try:
            return json.dumps(slim_events, ensure_ascii=False, indent=2)
        except Exception:
            return "[]"
    
    def _format_step_content(self, step: Dict[str, Any]) -> str:
        """格式化步骤内容为可读文本"""
        title = step.get('title', '未知步骤')
        description = step.get('description', '')
        notes = step.get('notes', '')
        status = step.get('status', '')
        
        content_parts = [f"步骤标题: {title}"]
        if description:
            content_parts.append(f"步骤描述: {description}")
        if notes:
            content_parts.append(f"执行结果: {notes}")
        if status:
            content_parts.append(f"状态: {status}")
            
        return "\n".join(content_parts)
    
    def _parse_llm_response(self, response: str) -> Dict[str, List[str]]:
        """解析LLM响应，提取可信信息分析结果"""
        try:
            # 尝试提取JSON部分
            if "```json" in response:
                json_start = response.find("```json") + 7
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            elif "```" in response:
                json_start = response.find("```") + 3
                json_end = response.find("```", json_start)
                json_str = response[json_start:json_end].strip()
            else:
                # 尝试直接解析整个响应
                json_str = response.strip()
            
            result = json.loads(json_str)
            
            # 验证和清理结果
            cleaned_result = {}
            for key, value in result.items():
                if isinstance(value, list):
                    # 过滤掉"无"和空字符串
                    cleaned_value = [item for item in value if item and item.strip() != "无"]
                    cleaned_result[key] = cleaned_value
                else:
                    cleaned_result[key] = []
            
            return cleaned_result
            
        except json.JSONDecodeError as e:
            logger.error(f"解析LLM响应JSON失败: {str(e)}")
            logger.error(f"原始响应: {response}")
            return {}
        except Exception as e:
            logger.error(f"解析LLM响应失败: {str(e)}", exc_info=True)
            return {}
    
    def format_credibility_message(self, credibility_result: Dict[str, List[str]], step_title: str, step_index: int | None = None) -> Dict[str, Any]:
        """格式化可信信息为前端消息格式"""
        if not credibility_result:
            return None
        
        # 检测语言
        language = self._detect_language(step_title)
        credibility_types = self._get_credibility_types(language)
            
        # 构建可信信息内容
        credibility_content = []
        
        for cred_type, items in credibility_result.items():
            if items:  # 只添加有内容的类型
                type_name = credibility_types.get(cred_type, cred_type)
                credibility_content.append({
                    "title": type_name,
                    "items": items
                })
        
        if not credibility_content:
            return None
        
        # 根据语言设置标题
        if language == 'en':
            title = f"Step Credibility Analysis: {step_title}"
        else:
            title = f"步骤可信信息分析: {step_title}"
            
        message: Dict[str, Any] = {
            "type": "lui-message-credibility-analysis",
            "title": title,
            "content": credibility_content,
            "stepTitle": step_title,
            "timestamp": self._get_timestamp()
        }
        if step_index is not None:
            message["stepIndex"] = step_index
        return message

    def _ensure_complete_result(self,
                                result: Dict[str, List[str]] | None,
                                current_step: Dict[str, Any],
                                all_completed_steps: List[Dict[str, Any]],
                                tool_events: List[Dict[str, Any]] | None,
                                language: str = 'zh') -> Dict[str, List[str]]:
        categories = [
            ("truth", "常识或真理"),
            ("verified_facts", "已验证事实"),
            ("searchable_facts", "需查找事实"),
            ("derived_facts", "需推导事实"),
            ("educated_guess", "有根据猜测"),
        ]
        safe_result: Dict[str, List[str]] = {k: (result.get(k) if result else []) or [] for k, _ in categories}

        step_title = current_step.get("title") or ("Current Step" if language == 'en' else "当前步骤")
        step_notes = (current_step.get("notes") or "").strip()
        tools_lines = []
        for evt in (tool_events or [])[-10:]:
            s = evt.get("summary") or ""
            if s:
                tools_lines.append(s)
        tools_hint = ("；".join(tools_lines))[:200]

        def ensure_line(lst: List[str], fallback: str):
            if not lst:
                lst.append(fallback[:50])

        if language == 'en':
            # 英文回退内容
            ensure_line(safe_result["truth"], f"Common sense related to '{step_title}': satisfy dependencies before execution (logic)")
            ensure_line(safe_result["verified_facts"], f"Confirmed: {(step_notes or 'No given or verified facts based on current step')}")
            ensure_line(safe_result["searchable_facts"], f"Still need to search: supplement authoritative data and latest trends for '{step_title}' (search)")
            ensure_line(safe_result["derived_facts"], f"Deduction: completing '{step_title}' reduces subsequent uncertainty (reasoning)")
            ensure_line(safe_result["educated_guess"], f"Estimate: {('tools show ' + tools_hint) if tools_hint else 'conservative judgment based on context'} (guess)")
        else:
            # 中文回退内容
            ensure_line(safe_result["truth"], f"与'{step_title}'相关常识：先满足依赖再执行（逻辑）")
            ensure_line(safe_result["verified_facts"], f"已确认：{(step_notes or '根据当前步骤，暂无给定或者已验证的事实')}")
            ensure_line(safe_result["searchable_facts"], f"仍需检索：补充'{step_title}'的权威数据与最新动态（搜索）")
            ensure_line(safe_result["derived_facts"], f"推导：完成'{step_title}'降低后续不确定性（推理）")
            ensure_line(safe_result["educated_guess"], f"估计：{('工具显示' + tools_hint) if tools_hint else '依据上下文保守判断'}（猜测）")

        # 清理和去重结果，但保持LLM生成的完整内容
        for k in safe_result:
            compact = []
            for item in safe_result[k][:2]:
                s = (item or "").strip()
                # 根据语言设置合理的最大长度限制
                # 中文：150字符（约等于prompt要求的100字加上标点和来源标注）
                # 英文：200字符（约等于prompt要求的50单词）
                max_length = 200 if language == 'en' else 150
                if len(s) > max_length:
                    # 只有超过合理长度时才截断，并添加省略号
                    s = s[:max_length] + "..."
                if s and s not in compact:
                    compact.append(s)
            safe_result[k] = compact

        return safe_result
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from cosight_server.sdk.common.utils import get_timestamp
        return get_timestamp()


# 全局实例
credibility_analyzer = CredibilityAnalyzer()