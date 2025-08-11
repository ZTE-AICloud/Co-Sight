#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试不同请求的工具是否不同
"""

import json
import sys
import os
from unittest.mock import Mock

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.cosight.agent.actor.instance.actor_agent_instance import create_actor_instance
from app.cosight.agent.base.base_agent import BaseAgent
from app.cosight.llm.chat_llm import ChatLLM
from openai import OpenAI

def test_dynamic_tools():
    """测试不同请求的工具是否不同"""
    
    print("=== 测试不同请求的工具是否不同 ===\n")
    
    # 创建模拟的 OpenAI client
    mock_client = Mock(spec=OpenAI)
    
    # 模拟 LLM 实例
    mock_llm = ChatLLM("http://localhost:8000", "test_key", "test_model", mock_client)
    
    # 测试用例1：包含 WebSearch
    print("测试用例1：包含 WebSearch")
    search_sources_1 = [
        {
            "id": 44,
            "type": "WebSearch",
            "name": "互联网",
            "sub_name": "全网",
            "description": "系统默认的互联网搜索",
            "source_from": "system_preset",
            "config": {
                "url": "",
                "spaces": None,
                "workflow_id": ""
            }
        },
        {
            "id": 46,
            "type": "RAGKnowledgeLibrary",
            "name": "知识库",
            "sub_name": "demo",
            "description": "用户上传文件创建 demo 知识库",
            "source_from": "user_defined",
            "config": {
                "url": "http://172.20.0.76:8093/query",
                "workflow_id": "RAG_Workflow_nae_product_manual"
            }
        }
    ]
    
    agent_instance_1 = create_actor_instance("test_actor_1", "/tmp/test")
    base_agent_1 = BaseAgent(agent_instance_1, mock_llm, {}, search_sources_1)
    
    search_tools_1 = [tool for tool in base_agent_1.tools if 'search' in tool['function']['name'].lower()]
    print(f"搜索工具数量: {len(search_tools_1)}")
    for tool in search_tools_1:
        print(f"  - {tool['function']['name']}")
    print()
    
    # 测试用例2：不包含 WebSearch
    print("测试用例2：不包含 WebSearch")
    search_sources_2 = [
        {
            "id": 46,
            "type": "RAGKnowledgeLibrary",
            "name": "知识库",
            "sub_name": "demo",
            "description": "用户上传文件创建 demo 知识库",
            "source_from": "user_defined",
            "config": {
                "url": "http://172.20.0.76:8093/query",
                "workflow_id": "RAG_Workflow_nae_product_manual"
            }
        },
        {
            "id": 48,
            "type": "custom",
            "name": "自定义",
            "sub_name": "微信搜索",
            "description": "微信搜索",
            "source_from": "user_defined",
            "config": {
                "url": "xxxx",
                "method": "POST"
            }
        }
    ]
    
    agent_instance_2 = create_actor_instance("test_actor_2", "/tmp/test")
    base_agent_2 = BaseAgent(agent_instance_2, mock_llm, {}, search_sources_2)
    
    search_tools_2 = [tool for tool in base_agent_2.tools if 'search' in tool['function']['name'].lower()]
    print(f"搜索工具数量: {len(search_tools_2)}")
    for tool in search_tools_2:
        print(f"  - {tool['function']['name']}")
    print()
    
    # 测试用例3：无 search_sources
    print("测试用例3：无 search_sources")
    agent_instance_3 = create_actor_instance("test_actor_3", "/tmp/test")
    base_agent_3 = BaseAgent(agent_instance_3, mock_llm, {}, None)
    
    search_tools_3 = [tool for tool in base_agent_3.tools if 'search' in tool['function']['name'].lower()]
    print(f"搜索工具数量: {len(search_tools_3)}")
    for tool in search_tools_3:
        print(f"  - {tool['function']['name']}")
    print()
    
    # 验证工具列表是否不同
    print("=== 验证结果 ===")
    print(f"用例1搜索工具数量: {len(search_tools_1)}")
    print(f"用例2搜索工具数量: {len(search_tools_2)}")
    print(f"用例3搜索工具数量: {len(search_tools_3)}")
    
    if len(search_tools_1) > 0:
        print("✅ 成功：包含 WebSearch 的请求有搜索工具")
    else:
        print("❌ 失败：包含 WebSearch 的请求没有搜索工具")
    
    if len(search_tools_2) == 0:
        print("✅ 成功：不包含 WebSearch 的请求没有搜索工具")
    else:
        print("❌ 失败：不包含 WebSearch 的请求仍有搜索工具")

    if len(search_tools_3) > 0:
        print("✅ 成功：无 search_sources 的请求有搜索工具")
    else:
        print("❌ 失败：无 search_sources 的请求没有搜索工具")

if __name__ == "__main__":
    test_dynamic_tools() 