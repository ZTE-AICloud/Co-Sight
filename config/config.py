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
from dotenv import load_dotenv
from typing import Optional

# 加载.env文件到环境变量
load_dotenv()


# ========== 大模型配置 ==========
def get_model_config() -> dict[str, Optional[str | int | float]]:
    """获取API配置"""
    max_tokens = os.environ.get("MAX_TOKENS")
    temperature = os.environ.get("TEMPERATURE")

    return {
        "api_key": os.environ.get("API_KEY"),
        "base_url": os.environ.get("API_BASE_URL"),
        "model": os.environ.get("MODEL_NAME"),
        "max_tokens": int(max_tokens) if max_tokens and max_tokens.strip() else None,
        "temperature": float(temperature) if temperature and temperature.strip() else None,
        "proxy": os.environ.get("PROXY")
    }


# ========== 规划大模型配置 ==========
def get_plan_model_config() -> dict[str, Optional[str | int | float]]:
    """获取Plan专用API配置，如果缺少配置则退回默认"""
    plan_api_key = os.environ.get("PLAN_API_KEY")
    plan_base_url = os.environ.get("PLAN_API_BASE_URL")
    model_name = os.environ.get("PLAN_MODEL_NAME")

    # 检查三个字段是否都存在且非空
    if not (plan_api_key and plan_base_url and model_name):
        return get_model_config()

    max_tokens = os.environ.get("PLAN_MAX_TOKENS")
    temperature = os.environ.get("PLAN_TEMPERATURE")

    return {
        "api_key": plan_api_key,
        "base_url": plan_base_url,
        "model": model_name,
        "max_tokens": int(max_tokens) if max_tokens and max_tokens.strip() else None,
        "temperature": float(temperature) if temperature and temperature.strip() else None,
        "proxy": os.environ.get("PLAN_PROXY")
    }


# ========== 执行大模型配置 ==========
def get_act_model_config() -> dict[str, Optional[str | int | float]]:
    """获取Act专用API配置，如果缺少配置则退回默认"""
    act_api_key = os.environ.get("ACT_API_KEY")
    act_base_url = os.environ.get("ACT_API_BASE_URL")
    model_name = os.environ.get("ACT_MODEL_NAME")

    # 检查三个字段是否都存在且非空
    if not (act_api_key and act_base_url and model_name):
        return get_model_config()

    max_tokens = os.environ.get("ACT_MAX_TOKENS")
    temperature = os.environ.get("ACT_TEMPERATURE")

    return {
        "api_key": act_api_key,
        "base_url": act_base_url,
        "model": model_name,
        "max_tokens": int(max_tokens) if max_tokens and max_tokens.strip() else None,
        "temperature": float(temperature) if temperature and temperature.strip() else None,
        "proxy": os.environ.get("ACT_PROXY")
    }


# ========== 工具大模型配置 ==========
def get_tool_model_config() -> dict[str, Optional[str | int | float]]:
    """获取Tool专用API配置，如果缺少配置则退回默认"""
    tool_api_key = os.environ.get("TOOL_API_KEY")
    tool_base_url = os.environ.get("TOOL_API_BASE_URL")
    model_name = os.environ.get("TOOL_MODEL_NAME")

    # 检查三个字段是否都存在且非空
    if not (tool_api_key and tool_base_url and model_name):
        return get_model_config()

    max_tokens = os.environ.get("TOOL_MAX_TOKENS")
    temperature = os.environ.get("TOOL_TEMPERATURE")

    return {
        "api_key": tool_api_key,
        "base_url": tool_base_url,
        "model": model_name,
        "max_tokens": int(max_tokens) if max_tokens and max_tokens.strip() else None,
        "temperature": float(temperature) if temperature and temperature.strip() else None,
        "proxy": os.environ.get("TOOL_PROXY")
    }


# ========== 多模态大模型配置 ==========
def get_vision_model_config() -> dict[str, Optional[str | int | float]]:
    """获取Vision专用API配置，如果缺少配置则退回默认"""
    vision_api_key = os.environ.get("VISION_API_KEY")
    vision_base_url = os.environ.get("VISION_API_BASE_URL")
    model_name = os.environ.get("VISION_MODEL_NAME")

    # 检查三个字段是否都存在且非空
    if not (vision_api_key and vision_base_url and model_name):
        return get_model_config()

    max_tokens = os.environ.get("VISION_MAX_TOKENS")
    temperature = os.environ.get("VISION_TEMPERATURE")

    return {
        "api_key": vision_api_key,
        "base_url": vision_base_url,
        "model": model_name,
        "max_tokens": int(max_tokens) if max_tokens and max_tokens.strip() else None,
        "temperature": float(temperature) if temperature and temperature.strip() else None,
        "proxy": os.environ.get("VISION_PROXY")
    }


# ========== 工具配置 ==========
def get_tavily_config() -> Optional[str]:
    """获取tavily兼容API配置"""
    return os.environ.get("TAVILY_API_KEY")


def validate_config(config: dict) -> bool:
    """验证必要配置是否存在"""
    if not config.get("api_key"):
        raise ValueError("OPENAI_COMPATIBILITY_API_KEY 未配置")
    return True
