"""编排 → rag-knowledge-base 的**进程内传输**（取代 HTTP）。

## 为什么是「按逻辑名直调」而不是「按 URL 分派」

并入之前，四个客户端自己拼 URL：

    url = Config.get('kb_service_url').rstrip('/') + Config.get('kb_retrieve_path')
    response = requests.post(url, json=body, headers=headers, timeout=60)

那些键（`kb_service_url` / `flow_config_path` / …）指向的是**已经不存在或即将不存在的地址**。
合并后没有「地址」可言，
所以这里按**逻辑名**直调，那六个键与对应的环境变量一并删除。

## 保住的是什么

客户端里这一段**保持不变**：

    if response.status_code < 200 or response.status_code >= 300: raise ...
    payload = response.json()
    if payload['code']['code'] != '0000': raise ...

因为那是线上报文形状的契约。本模块的四个函数返回的 `InProcessResponse`
只保证 `.status_code` 与 `.json()` —— 于是差异面从「一整套信封语义」缩到「一次 I/O」。

## 惰性导入

`chat.adapters.rkb_inprocess` 会拉起 RKB 的 compat 层（`store` 会 import psycopg2）。
编排独立跑单测的环境只有编排层依赖与 fastapi/requests，**没有 psycopg2** ——
模块级 import 会让整个测试收集失败。所以全部放在函数内。
"""

from __future__ import annotations

from typing import Any


def post_retrieve(body: dict, headers: Any = None):
    """检索：`invoke_knowledge_base_client` 的目标。"""
    from chat.adapters import rkb_inprocess

    return rkb_inprocess.post_retrieve(body)


def post_graph_retrieve(body: dict, headers: Any = None):
    """图谱检索：`invoke_knowledge_graph_client` 的目标。

    入参不符合契约时抛 `pydantic.ValidationError`（HTTP 时代是 422），由调用方
    的兜底分支折成 `request-knowledge-graph-failed` —— 与合并前同一个键。
    """
    from chat.adapters import rkb_inprocess

    return rkb_inprocess.post_graph_retrieve(body, headers)


def get_kbase_list():
    """知识库列表：`invoke_list_vector_knowledge_bases` 的目标。"""
    from chat.adapters import rkb_inprocess

    return rkb_inprocess.get_kbase_list()


def get_flow_config(app_id: str, scope: str = ''):
    """画布配置：`flow_config_provider.get_workflow_config` 的目标。

    `scope` 原样传递（`'dev'` 读草稿，其余读最新发布快照）。
    """
    from chat.adapters import rkb_inprocess

    return rkb_inprocess.get_flow_config(app_id, scope)
