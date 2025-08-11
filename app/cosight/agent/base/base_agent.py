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
        
        # 检查是否包含 type: 'WebSearch'
        enable_search = any(source.get('type') == 'WebSearch' for source in search_sources)
        print(f"Filtering skills with search_sources: {search_sources}")
        print(f"Search tools enabled: {enable_search}")
        
        if enable_search:
            return skills  # 启用搜索，返回所有技能
        else:
            # 禁用搜索，过滤掉搜索相关技能
            filtered_skills = []
            search_skill_names = ['search_baidu', 'search_google', 'tavily_search', 'image_search', 'search_wiki', 'search_duckgo']
            
            for skill in skills:
                if skill.skill_name not in search_skill_names:
                    filtered_skills.append(skill)
                    print(f"Kept skill: {skill.skill_name}")
                else:
                    print(f"Filtered out search skill: {skill.skill_name}")
            
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
        results = []
        with ThreadPoolExecutor() as executor:
            futures = []
            for tool_call in tool_calls:
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
