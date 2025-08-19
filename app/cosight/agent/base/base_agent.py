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

import inspect
import json
import sys
from typing import List, Dict, Any

import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.agent_dispatcher.domain.plan.action.skill.mcp.engine import MCPEngine
from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.cosight.agent.base.skill_to_tool import convert_skill_to_tool,get_mcp_tools,convert_mcp_tools
from app.cosight.llm.chat_llm import ChatLLM
from app.cosight.task.time_record_util import time_record
from app.common.logger_util import logger


class BaseAgent:
    def __init__(self, agent_instance: AgentInstance, llm: ChatLLM, functions: {}, search_sources: list = None):
        self.agent_instance = agent_instance
        self.llm = llm
        self.tools = []
        self.mcp_tools = []
        self.mcp_tools = get_mcp_tools(self.agent_instance.template.skills)
        
        # 根据 search_sources 过滤技能
        filtered_skills = self._filter_skills_by_search_sources(self.agent_instance.template.skills, search_sources)
        
        for skill in filtered_skills:
            self.tools.extend(convert_skill_to_tool(skill.model_dump(), 'en'))
        self.tools.extend(convert_mcp_tools(self.mcp_tools))
        self.functions = functions
        self.history = []
        self.search_sources = search_sources

    def _filter_skills_by_search_sources(self, skills, search_sources):
        """根据 search_sources 过滤技能"""
        if not search_sources:
            return skills
        
        # 识别可用的搜索源类型
        available_types = set()
        try:
            for source in search_sources:
                source_type = source.get('type') if isinstance(source, dict) else None
                if source_type:
                    available_types.add(source_type)
        except Exception:
            pass
        
        enable_web = 'WebSearch' in available_types
        enable_rag = 'RAGKnowledgeLibrary' in available_types
        print(f"Filtering skills with search_sources: {search_sources}")
        print(f"Search tools - web: {enable_web}, rag: {enable_rag}")
        
        # 定义所有搜索类技能名称
        web_search_skills = {'search_baidu', 'search_google', 'tavily_search', 'image_search', 'search_wiki', 'search_duckgo', 'custom_search'}
        rag_search_skills = {'rag_search'}
        all_search_skills = web_search_skills | rag_search_skills
        
        filtered_skills = []
        for skill in skills:
            name = getattr(skill, 'skill_name', None)
            if name in all_search_skills:
                # 仅保留已启用源类型对应的技能
                if (name in web_search_skills and enable_web) or (name in rag_search_skills and enable_rag):
                    filtered_skills.append(skill)
                else:
                    print(f"Filtered out search skill: {name}")
            else:
                filtered_skills.append(skill)
        
        return filtered_skills

    def find_mcp_tool(self, tool_name):
        for tool in self.mcp_tools:
            for func in tool['mcp_tools']:
                if func.name == tool_name:
                    return tool, func.name
        return None

    def execute(self, messages: List[Dict[str, Any]], step_index=None, max_iteration=10):
        for i in range(max_iteration):
            logger.info(f'act agent call with tools message: {messages}')
            response = self.llm.create_with_tools(messages, self.tools)
            logger.info(f'act agent call with tools response: {response}')

            # Process initial response
            result = self._process_response(response, messages, step_index)
            logger.info(f'iter {i} for {self.agent_instance.instance_name} call tools result: {result}')
            if result:
                return result

        if max_iteration > 1:
            return self._handle_max_iteration(messages, step_index)
        return messages[-1].get("content")

    def _process_response(self, response, messages, step_index):
        logger.info(f"_process_response called with response: {response}")
        logger.info(f"Response type: {type(response)}")
        logger.info(f"Response is None: {response is None}")
        
        if response is not None:
            logger.info(f"Response has content: {hasattr(response, 'content')}")
            logger.info(f"Response has tool_calls: {hasattr(response, 'tool_calls')}")
            if hasattr(response, 'content'):
                logger.info(f"Response content: {response.content}")
            if hasattr(response, 'tool_calls'):
                logger.info(f"Response tool_calls: {response.tool_calls}")
        
        if not response.tool_calls:
            messages.append({"role": "assistant", "content": response.content})
            return response.content

        messages.append({
            "role": "assistant",
            "content": response.content,
            "tool_calls": response.tool_calls
        })

        results = self._execute_tool_calls(response.tool_calls, step_index)
        messages.extend(results)

        # Check for termination conditions
        for result in results:
            if result["name"] in ["terminate", "mark_step"]:
                return result["content"]
        return None

    def _execute_tool_calls(self, tool_calls, step_index):
        logger.info(f"_execute_tool_calls called with tool_calls: {tool_calls}")
        logger.info(f"Tool calls type: {type(tool_calls)}")
        logger.info(f"Tool calls is None: {tool_calls is None}")
        logger.info(f"Tool calls length: {len(tool_calls) if tool_calls else 0}")
        
        results = []
        with ThreadPoolExecutor() as executor:
            futures = []
            for i, tool_call in enumerate(tool_calls):
                logger.info(f"Processing tool call {i}: {tool_call}")
                logger.info(f"Tool call type: {type(tool_call)}")
                logger.info(f"Tool call has function: {hasattr(tool_call, 'function')}")
                
                if hasattr(tool_call, 'function'):
                    logger.info(f"Function has name: {hasattr(tool_call.function, 'name')}")
                    logger.info(f"Function has arguments: {hasattr(tool_call.function, 'arguments')}")
                    if hasattr(tool_call.function, 'name'):
                        logger.info(f"Function name: {tool_call.function.name}")
                    if hasattr(tool_call.function, 'arguments'):
                        logger.info(f"Function arguments: {tool_call.function.arguments}")
                
                function_name = tool_call.function.name
                function_args = tool_call.function.arguments

                if function_name in self.functions:
                    futures.append(executor.submit(
                        self._execute_tool_call,
                        function_name=function_name,
                        function_args=function_args,
                        tool_call_id=tool_call.id,
                        step_index=step_index
                    ))
                else:
                    futures.append(executor.submit(
                        self._execute_mcp_tool_call,
                        function_name=function_name,
                        function_args=function_args,
                        tool_call_id=tool_call.id
                    ))

            for future in futures:
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"Unhandled exception: {e}", exc_info=True)
                    results.append({
                        "role": "tool",
                        "name": function_name,
                        "tool_call_id": tool_call.id,
                        "content": f"Execution error: {str(e)}"
                    })
        return results

    def _handle_max_iteration(self, messages, step_index):
        messages.append({"role": "user", "content": "Summarize the above conversation, use mark_step to mark the step"})
        mark_step_tools = [tool for tool in self.tools if tool['function']['name'] == 'mark_step']
        response = self.llm.create_with_tools(messages, mark_step_tools)

        result = self._process_response(response, messages, step_index)
        if result:
            return result

        return messages[-1].get("content")

    @time_record
    def _execute_tool_call(self, function_name="", function_args="", tool_call_id="", step_index=None):
        try:
            # Clean and validate JSON
            cleaned_args = function_args.replace('\\\'', '\'')
            args_dict = json.loads(cleaned_args or "{}")

            if step_index is not None and 'step_index' not in args_dict and function_name in ['mark_step']:
                args_dict['step_index'] = step_index

            function_to_call = self.functions[function_name]

            # 检查是否是异步函数
            if inspect.iscoroutinefunction(function_to_call):
                # 创建新的事件循环来运行异步函数
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(function_to_call(**args_dict))
                finally:
                    loop.close()
            else:
                # 同步函数直接调用
                result = function_to_call(**args_dict)

            return {
                "role": "tool",
                "name": function_name,
                "content": str(result),
                "tool_call_id": tool_call_id
            }
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            return {
                "role": "tool",
                "name": function_name,
                "tool_call_id": tool_call_id,
                "content": f"Execution error: {str(e)}"
            }

    @time_record
    def _execute_mcp_tool_call(self, function_name="", function_args="", tool_call_id=""):
        loop = None
        try:
            mcp_tool, tool_name = self.find_mcp_tool(function_name)
            if mcp_tool and tool_name:
                cleaned_args = function_args.replace('\\\'', '\'')
                args_dict = json.loads(cleaned_args or "{}")
                # Windows系统需要特殊处理
                if sys.platform == "win32":
                    from asyncio import ProactorEventLoop
                    loop = ProactorEventLoop()
                else:
                    loop = asyncio.new_event_loop()

                asyncio.set_event_loop(loop)

                # 执行异步调用
                result = loop.run_until_complete(
                    MCPEngine.invoke_mcp_tool(
                        mcp_tool['mcp_name'],
                        mcp_tool['mcp_config'],
                        tool_name,
                        args_dict
                    )
                )
                return {
                    "role": "tool",
                    "name": function_name,
                    "content": str(result),
                    "tool_call_id": tool_call_id
                }
            else:
                return {
                    "role": "tool",
                    "name": function_name,
                    "tool_call_id": tool_call_id,
                    "content": f"Function {function_name} not found in available functions"
                }
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            return {
                "role": "tool",
                "name": function_name,
                "tool_call_id": tool_call_id,
                "content": f"Execution error: {str(e)}"
            }
        finally:
            # 清理事件循环
            if loop:
                loop.close()
                asyncio.set_event_loop(None)
