# Copyright 2025 ZTE Corporation. All Rights Reserved.
# Licensed under the Apache License, Version 2.0

"""
Skill Catalog — 系统级 Skill 目录。
维护所有可用的 actor 技能名称、显示名称和对应的 skill builder 映射。
Planner 技能集固定，不可自定义。
"""

import os
from typing import List, Dict, Callable, Optional
from app.common.logger_util import logger


# ======================= Skill 元数据注册表 =======================
# 每个条目: skill_name -> { display_name_zh, description_zh, builder_func_name, needs_workspace }
# builder_func_name 对应 actor_agent_skill.py 中的函数名

ACTOR_SKILL_CATALOG: Dict[str, dict] = {
    "execute_code": {
        "display_name_zh": "执行代码",
        "description_zh": "执行 Python 代码片段并返回结果",
        "needs_workspace": True,
    },
    "search_google": {
        "display_name_zh": "Google 搜索",
        "description_zh": "通过 Google 搜索引擎检索信息",
        "needs_workspace": False,
    },
    "tavily_search": {
        "display_name_zh": "Tavily 搜索",
        "description_zh": "通过 Tavily AI 搜索引擎检索信息",
        "needs_workspace": False,
    },
    "search_wiki": {
        "display_name_zh": "维基百科搜索",
        "description_zh": "搜索维基百科获取知识信息",
        "needs_workspace": False,
    },
    "mark_step": {
        "display_name_zh": "标记步骤",
        "description_zh": "标记任务步骤的完成状态和结果",
        "needs_workspace": False,
    },
    "file_saver": {
        "display_name_zh": "文件保存",
        "description_zh": "将内容保存到文件",
        "needs_workspace": False,
    },
    "file_read": {
        "display_name_zh": "文件读取",
        "description_zh": "读取文件内容",
        "needs_workspace": False,
    },
    "file_str_replace": {
        "display_name_zh": "文件内容替换",
        "description_zh": "在文件中查找并替换字符串",
        "needs_workspace": False,
    },
    "file_find_in_content": {
        "display_name_zh": "文件内容搜索",
        "description_zh": "在文件中搜索指定内容",
        "needs_workspace": False,
    },
    "ask_question_about_image": {
        "display_name_zh": "图片分析",
        "description_zh": "对图片内容进行智能识别和问答",
        "needs_workspace": False,
    },
    "ask_question_about_video": {
        "display_name_zh": "视频分析",
        "description_zh": "对视频内容进行智能分析和问答",
        "needs_workspace": False,
    },
    "audio_recognition": {
        "display_name_zh": "语音识别",
        "description_zh": "将音频转换为文字",
        "needs_workspace": False,
    },
    "extract_document_content": {
        "display_name_zh": "文档解析",
        "description_zh": "提取文档（PDF/Word/Excel 等）内容",
        "needs_workspace": False,
    },
    "create_html_report": {
        "display_name_zh": "HTML 报告生成",
        "description_zh": "生成包含图表的 HTML 可视化报告",
        "needs_workspace": False,
    },
    "fetch_website_content": {
        "display_name_zh": "网页内容抓取",
        "description_zh": "获取网页的文字内容",
        "needs_workspace": False,
    },
    "fetch_website_content_with_images": {
        "display_name_zh": "网页内容含图抓取",
        "description_zh": "获取网页的文字内容和图片",
        "needs_workspace": False,
    },
    "fetch_website_images_only": {
        "display_name_zh": "网页图片抓取",
        "description_zh": "仅获取网页中的图片",
        "needs_workspace": False,
    },
}

# Planner 固定技能集（v1 不可自定义）
PLANNER_FIXED_SKILLS = ["create_plan", "update_plan", "terminate"]


def get_available_actor_skills() -> List[dict]:
    """
    返回所有可供 actor 选择的 skill 元数据列表。
    用于前端展示和 API 返回。
    """
    result = []
    for name, info in ACTOR_SKILL_CATALOG.items():
        result.append({
            "name": name,
            "display_name_zh": info["display_name_zh"],
            "description_zh": info["description_zh"],
        })
    return result


def get_skill_display_name(skill_name: str) -> str:
    """获取 skill 的中文显示名"""
    info = ACTOR_SKILL_CATALOG.get(skill_name)
    return info["display_name_zh"] if info else skill_name


def validate_skill_names(skill_names: List[str]) -> List[str]:
    """
    校验 skill 名称列表，返回无效的 skill 名称。
    """
    return [s for s in skill_names if s not in ACTOR_SKILL_CATALOG]


def build_actor_skills(skill_names: List[str], work_space_path: str = None) -> list:
    """
    根据 skill 名称列表，调用 actor_agent_skill.py 中对应的 builder 生成 Skill 对象列表。
    仅返回请求的 skills，而非全量。
    """
    from app.cosight.agent.actor.instance.actor_agent_skill import (
        execute_code_skill, search_google_skill, tavily_search_skill,
        search_wiki_skill, mark_step_skill, file_saver_skill,
        file_read_skill, file_str_replace_skill, file_find_in_content_skill,
        ask_question_about_image_skill, ask_question_about_video_skill,
        audio_recognition_skill, extract_document_content_skill,
        create_html_report_skill, fetch_website_content_skill,
        fetch_website_content_with_images_skill, fetch_website_images_only_skill,
    )

    SKILL_BUILDERS = {
        "execute_code": lambda: execute_code_skill(work_space_path),
        "search_google": search_google_skill,
        "tavily_search": tavily_search_skill,
        "search_wiki": search_wiki_skill,
        "mark_step": mark_step_skill,
        "file_saver": file_saver_skill,
        "file_read": file_read_skill,
        "file_str_replace": file_str_replace_skill,
        "file_find_in_content": file_find_in_content_skill,
        "ask_question_about_image": ask_question_about_image_skill,
        "ask_question_about_video": ask_question_about_video_skill,
        "audio_recognition": audio_recognition_skill,
        "extract_document_content": extract_document_content_skill,
        "create_html_report": create_html_report_skill,
        "fetch_website_content": fetch_website_content_skill,
        "fetch_website_content_with_images": fetch_website_content_with_images_skill,
        "fetch_website_images_only": fetch_website_images_only_skill,
    }

    skills = []
    for name in skill_names:
        builder = SKILL_BUILDERS.get(name)
        if builder:
            try:
                skills.append(builder())
            except Exception as e:
                logger.warning(f"构建 skill '{name}' 失败: {e}")
        else:
            logger.warning(f"未找到 skill builder: '{name}'，跳过")
    return skills


def build_planner_skills() -> list:
    """构建 planner 固定技能集"""
    from app.cosight.agent.planner.instance.planner_agent_skill import create_plan_skill, update_plan_skill
    from app.cosight.agent.base.common_skill import terminate_skill
    return [create_plan_skill(), update_plan_skill(), terminate_skill()]
