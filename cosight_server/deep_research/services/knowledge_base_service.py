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

"""
知识库检索服务 — 在任务执行前查询知识库上下文
"""

import os
import asyncio
from typing import List, Optional

import httpx
from app.common.logger_util import logger


async def query_knowledge_bases(
    question: str,
    kb_ids: List[str],
    mode: Optional[str] = None,
) -> str:
    """
    并行查询多个知识库，合并返回检索到的上下文文本。
    用于注入到 Planner 的 system prompt 中。

    Args:
        question: 用户查询
        kb_ids: 知识库 ID 列表
        mode: 查询模式（默认从环境变量读取）

    Returns:
        合并后的上下文文本，如无内容则返回空字符串
    """
    if not kb_ids:
        return ""

    base_url = os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621").rstrip("/")
    api_key = os.getenv("LIGHTRAG_API_KEY")
    query_mode = mode or os.getenv("LIGHTRAG_DEFAULT_QUERY_MODE", "hybrid")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def _query_single(kb_id: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{base_url}/query",
                    headers=headers,
                    json={
                        "query": question,
                        "mode": query_mode,
                        "workspace": kb_id,
                        "only_need_context": True,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                if isinstance(result, str):
                    return result
                return result.get("response", str(result))
        except Exception as e:
            logger.warning(f"Query knowledge base {kb_id} failed: {e}")
            return None

    results = await asyncio.gather(*[_query_single(kb_id) for kb_id in kb_ids])

    # 加载知识库名称
    from cosight_server.deep_research.routers.knowledge_base import _load_kb_meta
    meta = _load_kb_meta()
    name_map = {kb["id"]: kb["name"] for kb in meta}

    contexts = []
    for kb_id, result in zip(kb_ids, results):
        if result and result.strip():
            kb_name = name_map.get(kb_id, kb_id)
            contexts.append(f"【来源: {kb_name}】\n{result.strip()}")

    if not contexts:
        return ""

    header = "=== 以下是从本地知识库检索到的相关参考信息 ===\n\n"
    return header + "\n\n---\n\n".join(contexts) + "\n\n=== 知识库参考信息结束 ==="
