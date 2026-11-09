#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 专用检索模块。

合并产品规范（pd_spec_vector_library，LlamaIndex）和历史范式
（historical_paradigms，原始 LanceDB）检索结果为统一的 NodeWithScore 列表。

被 soc-single-responder-skill 调用（也可被 soc-json-responder-skill 复用）。
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore

import lancedb

try:
    from common.soc_vector_paths import (
        soc_pd_spec_lancedb_dir,
        soc_historical_lancedb_dir,
    )
    from common.soc_kb_registry.config import DEFAULT_KB_WEIGHTS
except ImportError:
    DEFAULT_KB_WEIGHTS = {"builtin": 1.0, "team": 1.05, "local": 1.1}

    def soc_pd_spec_lancedb_dir(agent_id: str = "soc") -> Path:
        return Path()
    def soc_historical_lancedb_dir(agent_id: str = "soc") -> Path:
        return Path()

try:
    from common.retrieval_pipeline import BGERerank
except ImportError:
    from retrieval_pipeline import BGERerank  # type: ignore

try:
    from watch_dog.file_watcher.embedding_model import (
        EmbeddingServiceError,
        OnlineBGEEmbedding,
    )
except ImportError:
    try:
        from common.embedding_model import EmbeddingServiceError, OnlineBGEEmbedding  # 兼容旧路径
    except ImportError:
        # 最后兜底：让 _get_query_embedding 报错
        class EmbeddingServiceError(RuntimeError):
            pass

        class OnlineBGEEmbedding:
            def _get_query_embedding(self, text):
                raise EmbeddingServiceError("OnlineBGEEmbedding not available")

logger = logging.getLogger(__name__)


def _ensure_online_bge_embed_model() -> None:
    """强制设置 OnlineBGEEmbedding，绕过 Settings getter 触发的 OpenAI 默认加载。"""
    if not getattr(Settings, "_embed_model", None):
        object.__setattr__(Settings, "_embed_model", OnlineBGEEmbedding())


def _get_query_embedding(query_text: str):
    """获取查询向量（用于历史范式表的原始 LanceDB 搜索）"""
    embed = OnlineBGEEmbedding()
    return embed._get_query_embedding(query_text)


def _build_path_prefix_where(path_prefix: Union[str, List[str]]) -> str:
    """
    把单个或多个路径前缀转换成 LanceDB where 子句。
    多个前缀用 OR 连接。
    """
    if isinstance(path_prefix, str):
        prefixes = [path_prefix]
    else:
        prefixes = list(path_prefix)

    prefixes = [p for p in prefixes if p]
    if not prefixes:
        return ""

    conditions = []
    for p in prefixes:
        safe = p.replace("'", "''")
        conditions.append(f"metadata.file_path LIKE '%{safe}%'")

    if len(conditions) == 1:
        return conditions[0]

    return "(" + " OR ".join(conditions) + ")"


def _search_product_specs(
    agent_id: str,
    query_text: str,
    top_k: int = 10,
    path_prefix: Union[str, List[str]] = "",
) -> List[NodeWithScore]:
    """
    在 pd_spec_vector_library 中检索，返回 NodeWithScore 列表。
    如果传入 path_prefix（单个字符串或字符串列表），则只在 metadata.file_path
    包含这些前缀的节点中检索。
    使用 BGERerank 重排到 top_n=top_k。
    """
    lan_dir = soc_pd_spec_lancedb_dir(agent_id)
    if not (lan_dir / "nodes.lance").exists():
        logger.info(f"[SOC] pd_spec LanceDB 索引不存在: {lan_dir}")
        return []

    try:
        _ensure_online_bge_embed_model()

        # 有过滤前缀：使用 LanceDB 原生 "向量 + where" 检索
        if path_prefix:
            query_embedding = _get_query_embedding(query_text)
            db = lancedb.connect(str(lan_dir))
            table = db.open_table("nodes")

            where_clause = _build_path_prefix_where(path_prefix)

            # 在产品目录内直接做向量 ANN 搜索，多取一些给后续 BGE 重排
            rows = (
                table.search(query_embedding)
                .where(where_clause)
                .limit(max(top_k, 50))
                .to_list()
            )

            nodes = []
            for row in rows:
                meta = row.get("metadata", {})
                if isinstance(meta, str):
                    meta = json.loads(meta)
                # LanceDB 返回的距离值范围通常是 [0, 2]，转换为相似度
                distance = row.get("_distance", 2.0)
                similarity = max(0.0, 1.0 - distance / 2.0)
                node = TextNode(
                    text=row.get("text", ""),
                    id_=row.get("id", ""),
                    metadata=meta,
                )
                nodes.append(NodeWithScore(node=node, score=similarity))

            logger.info(
                f"[SOC] 产品规范过滤检索: path_prefix={path_prefix}, "
                f"命中 {len(nodes)} 个节点"
            )
            return nodes

        # 无过滤：保持原逻辑
        vector_store = LanceDBVectorStore(uri=str(lan_dir), table_name="nodes")
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
        retriever = index.as_retriever(similarity_top_k=50)
        nodes = retriever.retrieve(query_text)

        # 限制 top_k：直接截断（保留 BGERerank 行为可在调用方做）
        return nodes[:max(top_k, 1)]
    except EmbeddingServiceError:
        raise
    except Exception as e:
        logger.error(f"[SOC] 产品规范检索失败: {e}", exc_info=True)
        return []


def _search_paradigms(
    agent_id: str,
    query_text: str,
    top_k: int = 5,
) -> List[NodeWithScore]:
    """
    在 historical_paradigms.response_paradigm 表中检索，返回 NodeWithScore 列表。
    """
    hist_lan_dir = soc_historical_lancedb_dir(agent_id)
    if not hist_lan_dir.exists():
        logger.info(f"[SOC] 历史范式 LanceDB 目录不存在: {hist_lan_dir}")
        return []

    try:
        import lancedb
        db = lancedb.connect(str(hist_lan_dir))

        try:
            tables = db.list_tables()
            table_names = tables.tables if hasattr(tables, "tables") else tables
        except Exception:
            table_names = []
        if "response_paradigm" not in table_names:
            logger.info("[SOC] response_paradigm 表不存在")
            return []

        table = db.open_table("response_paradigm")
        query_vec = _get_query_embedding(query_text)

        items = table.search(query_vec).where("reviewed == true").limit(top_k).to_list()

        nodes = []
        for item in items:
            distance = item.get("_distance", 2.0)
            similarity = 1.0 - (distance / 2.0)
            if similarity <= 0.0:
                continue

            description = item.get("description", "")
            compliance = item.get("compliance", "")
            remarks = item.get("remarks", "")
            ref_doc = item.get("reference_document", "")
            source_file = item.get("source_file", "")
            created_at = item.get("created_at", "")
            source_path = item.get("source_path", "")

            content_parts = ["# 历史应答范式"]
            content_parts.append(f"**需求描述**: {description}")
            content_parts.append(f"**合规判定**: {compliance}")
            if remarks:
                content_parts.append(f"**备注**: {remarks}")
            if ref_doc:
                content_parts.append(f"**参考文档**: {ref_doc}")
            content_text = "\n\n".join(content_parts)

            metadata = {
                "source_type": "historical_paradigm",
                "compliance": compliance,
                "remarks": remarks,
                "reference_document": ref_doc,
                "source_file": source_file,
                "source_path": source_path,
                "created_at": created_at,
                "file_name": source_file,
                "chapter_title": f"历史范式: {source_file}",
                "header_path": f"/历史应答/{source_file}",
            }

            node = TextNode(
                text=content_text,
                id_=item.get("id", ""),
                metadata=metadata,
            )
            nodes.append(NodeWithScore(node=node, score=similarity))

        logger.info(f"[SOC] 历史范式检索: {len(nodes)} 条结果")
        return nodes
    except EmbeddingServiceError:
        raise
    except Exception as e:
        logger.warning(f"[SOC] 历史范式检索失败（非致命）: {e}")
        return []


def soc_retrieve_all(
    agent_id: str,
    query_text: str,
    *,
    product_spec_top_k: int = 10,
    paradigm_top_k: int = 5,
    product_spec_bonus: float = 0.15,
    use_bge_rerank_for_spec: bool = True,
    product_spec_path_prefix: Union[str, List[str]] = "",  # 新增：产品规范路径前缀过滤
) -> List[NodeWithScore]:
    """
    SOC 专用统一检索。

    Args:
        agent_id: 智能体 ID（默认 'soc-agent'）
        query_text: 检索问题
        product_spec_top_k: 产品规范 top_k
        paradigm_top_k: 历史范式 top_k
        product_spec_bonus: 产品规范在合并排序时的加分
        use_bge_rerank_for_spec: 是否对产品规范用 BGE 重排
        product_spec_path_prefix: 产品规范路径前缀过滤，为空表示不过滤；
            可传单个字符串或字符串列表（多个目录用 OR 连接）

    Returns:
        合并后的 NodeWithScore 列表，按 (similarity + product_spec_bonus if spec) 降序
    """
    # 1. 产品规范检索
    spec_matches = _search_product_specs(
        agent_id, query_text, product_spec_top_k,
        path_prefix=product_spec_path_prefix,
    )

    # 可选：BGE 重排
    if use_bge_rerank_for_spec and spec_matches:
        try:
            spec_matches = BGERerank(top_n=product_spec_top_k).rerank(query_text, spec_matches)
        except Exception as e:
            logger.warning(f"[SOC] BGE 重排失败，保持原顺序: {e}")

    # 给 spec 节点加 _source_kind 标记
    for n in spec_matches:
        meta = dict(n.node.metadata or {})
        meta["_source_kind"] = "product_spec"
        n.node.metadata = meta

    # 2. 历史范式检索
    paradigm_matches = _search_paradigms(agent_id, query_text, paradigm_top_k)
    for n in paradigm_matches:
        meta = dict(n.node.metadata or {})
        meta["_source_kind"] = "paradigm"
        n.node.metadata = meta

    # 3. 合并排序
    combined = sorted(
        spec_matches + paradigm_matches,
        key=lambda x: (
            float(getattr(x, "score", 0.0) or 0.0)
            + (product_spec_bonus if (x.node.metadata or {}).get("_source_kind") == "product_spec" else 0.0)
        ),
        reverse=True,
    )

    logger.info(
        f"[SOC] soc_retrieve_all: spec={len(spec_matches)}, "
        f"paradigm={len(paradigm_matches)}, combined={len(combined)}"
    )
    return combined


# ──────────────────────────────────────────────────────────
#  多 KB 检索融合（按注册表遍历所有启用 KB）
# ──────────────────────────────────────────────────────────

def _annotate_kb_source(nodes: List[NodeWithScore], kb) -> None:
    """给节点打上 kb_id / kb_name 标签，方便下游展示来源。"""
    for n in nodes:
        meta = dict(n.node.metadata or {})
        meta["kb_id"] = kb.kb_id
        meta["kb_name"] = kb.name
        n.node.metadata = meta


def _apply_kb_weight(nodes: List[NodeWithScore], kb_type: str) -> None:
    """按 KB 类型权重调整 final_score。"""
    weight = DEFAULT_KB_WEIGHTS.get(kb_type, 1.0)
    for n in nodes:
        meta = dict(n.node.metadata or {})
        meta["final_score"] = float(getattr(n, "score", 0.0) or 0.0) * weight
        n.node.metadata = meta


def _parse_scoped_prefixes(
    path_prefix: Union[str, List[str], None],
) -> "tuple[dict[str, List[str]], bool]":
    """把路径前缀列表解析成 per-KB 路由表。

    条目格式：
      - "<kb_id>::<path>" → 只路由到该 KB（进入 LIKE 前剥掉 kb 前缀，
        因为 LanceDB metadata.file_path 不含 kb 前缀，不剥会导致 0 命中）
      - 裸 "<path>" → 应用到所有 KB（归入 "" 键）

    返回 (per_kb, has_scoped)：
      per_kb:     {kb_id 或 "": [path, ...]}
      has_scoped: 是否存在带 kb 前缀的条目。True 时，没有匹配条目的 KB
                  不做 spec 检索（避免对无关 KB 做全库过滤检索）。
    """
    per_kb: dict[str, List[str]] = {}
    has_scoped = False
    if not path_prefix:
        return per_kb, has_scoped
    items = [path_prefix] if isinstance(path_prefix, str) else list(path_prefix)
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if "::" in text:
            kb_part, path_part = text.split("::", 1)
            kb_part = kb_part.strip()
            path_part = path_part.strip()
            if kb_part and path_part:
                per_kb.setdefault(kb_part, []).append(path_part)
                has_scoped = True
        else:
            per_kb.setdefault("", []).append(text)
    return per_kb, has_scoped


def _retrieve_specs_scoped(
    lancedb_dir: Path,
    query_text: str,
    top: int,
    kb_prefixes: List[str],
    query_vec: Optional[List[float]] = None,
) -> List[NodeWithScore]:
    """带范围前缀的 spec 检索：每个前缀独立检索，保证每个产品范围都有候选。

    2026-08-29 真实事故：5 个产品范围合并成一条 OR 检索时，team G7/G8 文档
    （标题精准命中"硬件参数"）的高分 chunk 挤占 top 名额，support G5/G6
    一条不剩。逐前缀检索 + `_scope_prefix` 标记，配合下游
    `_select_with_scope_diversity` 的范围保底，根治该问题。
    """
    if len(kb_prefixes) == 1:
        nodes = _search_product_specs_in_dir(
            lancedb_dir, query_text, top, path_prefix=kb_prefixes, query_vec=query_vec,
        )
        for n in nodes:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["_scope_prefix"] = kb_prefixes[0]
        return nodes

    per_prefix_top = max(2, math.ceil(top / len(kb_prefixes)))
    merged: List[NodeWithScore] = []
    for prefix in kb_prefixes:
        hits = _search_product_specs_in_dir(
            lancedb_dir, query_text, per_prefix_top,
            path_prefix=[prefix], query_vec=query_vec,
        )
        for n in hits:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["_scope_prefix"] = prefix
        merged.extend(hits)

    # KB 内去重（同一 chunk 可能被多个前缀命中）
    seen: set[str] = set()
    deduped: List[NodeWithScore] = []
    for n in merged:
        nid = n.node.node_id or n.node.id_
        if nid in seen:
            continue
        seen.add(nid)
        deduped.append(n)
    return deduped


def _select_with_scope_diversity(
    deduped: List[NodeWithScore],
    limit: int,
    paradigm_reserve: int = 5,
) -> List[NodeWithScore]:
    """多产品范围检索的最终名额分配：每个范围保底代表，剩余名额按分数补。

    输入必须已按 final_score 降序。spec 节点按 `_scope_prefix` 分桶做轮询
    保底（每桶每轮取 1 条）；paradigm 等非范围节点预留 paradigm_reserve
    个名额；桶取完或名额有余时，全部剩余节点按分数补位。
    范围桶 ≤1 时退化为纯分数截断（与旧行为一致）。
    """
    buckets: Dict[str, List[NodeWithScore]] = {}
    paradigm_pool: List[NodeWithScore] = []
    other_rest: List[NodeWithScore] = []
    for n in deduped:
        meta = n.node.metadata or {}
        scope = meta.get("_scope_prefix") if meta.get("_source_kind") != "paradigm" else None
        if scope:
            buckets.setdefault(scope, []).append(n)
        elif meta.get("_source_kind") == "paradigm":
            paradigm_pool.append(n)
        else:
            other_rest.append(n)

    if len(buckets) <= 1:
        return deduped[:limit]

    spec_slots = max(limit - min(len(paradigm_pool), paradigm_reserve), len(buckets))
    picked: List[NodeWithScore] = []
    # 轮询保底：每轮从每个非空桶取 1 条（桶内已按分数有序）
    while len(picked) < spec_slots:
        progressed = False
        for bucket in buckets.values():
            if bucket and len(picked) < spec_slots:
                picked.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break

    # paradigm 预留名额直接入列（历史范式是应答链路的核心证据源，
    # 不能被 spec 高分 chunk 在补位阶段挤光）
    picked.extend(paradigm_pool[:paradigm_reserve])

    # 剩余名额：预留之外的 paradigm + 桶里没取完的 + 其他未归属节点，按分数补
    remainder = (
        paradigm_pool[paradigm_reserve:]
        + other_rest
        + [n for bucket in buckets.values() for n in bucket]
    )
    remainder.sort(
        key=lambda x: x.node.metadata.get("final_score", 0.0), reverse=True,
    )
    picked.extend(remainder[: max(limit - len(picked), 0)])
    return picked[:limit]


def multi_kb_retrieve(
    agent_id: str,
    query_text: str,
    *,
    top_spec: int = 10,
    top_paradigm: int = 5,
    scopes: Optional[List[str]] = None,
    spec_path_prefix: Union[str, List[str], None] = None,
) -> List[NodeWithScore]:
    """遍历所有启用 KB，全量检索 spec + paradigm。

    替换 soc_retrieve_all 的多 KB 版本。

    spec_path_prefix：可选路径前缀过滤，支持 "<kb_id>::<path>" 路由语法
    （剥掉 kb 前缀后下推到该 KB 的 LanceDB WHERE 子句）；裸 path 应用到所有
    KB。空 / None = 不过滤。
    """
    from common.soc_kb_registry import load_registry

    registry = load_registry(agent_id=agent_id)
    all_results: List[NodeWithScore] = []
    scoped_prefixes, has_scoped = _parse_scoped_prefixes(spec_path_prefix)

    # 多前缀逐条检索前预算一次查询向量，避免每个前缀重复调 embedding 服务
    query_vec: Optional[List[float]] = None

    def _ensure_query_vec() -> List[float]:
        nonlocal query_vec
        if query_vec is None:
            query_vec = _get_query_embedding(query_text)
        return query_vec

    for kb in registry.enabled_kbs():
        if scopes and kb.kb_id not in scopes:
            continue
        if kb.type.value not in {"builtin", "team", "local"}:
            continue

        # spec 检索：按 KB 路由 path_prefix（剥掉 "<kb>::" 后下推 LanceDB）
        spec_lancedb = _kb_lancedb_dir(kb.kb_id, "pd_spec_vector_library", agent_id)
        if has_scoped:
            kb_prefixes = scoped_prefixes.get(kb.kb_id, []) + scoped_prefixes.get("", [])
            if not kb_prefixes:
                spec_nodes: List[NodeWithScore] = []  # 该 KB 无匹配范围，跳过
            else:
                spec_nodes = _retrieve_specs_scoped(
                    spec_lancedb, query_text, top_spec, kb_prefixes,
                    query_vec=_ensure_query_vec(),
                )
        else:
            bare = scoped_prefixes.get("", [])
            spec_nodes = _search_product_specs_in_dir(
                spec_lancedb, query_text, top_spec, path_prefix=bare or None,
            )

        # paradigm 检索
        paradigm_lancedb = _kb_lancedb_dir(kb.kb_id, "historical_paradigms", agent_id)
        paradigm_nodes = _search_paradigms_in_dir(
            paradigm_lancedb, query_text, top_paradigm,
            query_vec=query_vec,
        )

        # 标记来源 + 应用权重
        for n in spec_nodes:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["_source_kind"] = "product_spec"
            n.node.metadata["kb_id"] = kb.kb_id
            n.node.metadata["kb_name"] = kb.name
        for n in paradigm_nodes:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["_source_kind"] = "paradigm"
            n.node.metadata["kb_id"] = kb.kb_id
            n.node.metadata["kb_name"] = kb.name

        # KB 类型权重
        kb_weight = DEFAULT_KB_WEIGHTS.get(kb.type.value, 1.0)
        for n in spec_nodes + paradigm_nodes:
            n.node.metadata["final_score"] = (
                float(getattr(n, "score", 0.0) or 0.0) * kb_weight
            )

        # 按 final_score 排序
        combined = sorted(
            spec_nodes + paradigm_nodes,
            key=lambda x: x.node.metadata.get("final_score", 0.0),
            reverse=True,
        )
        all_results.extend(combined)

    # 全局去重：按 node.id_ 去重
    seen: set[str] = set()
    deduped: List[NodeWithScore] = []
    for n in all_results:
        nid = n.node.node_id or n.node.id_
        if nid in seen:
            continue
        seen.add(nid)
        deduped.append(n)

    # 按 final_score 全局排序
    deduped.sort(
        key=lambda x: x.node.metadata.get("final_score", 0.0),
        reverse=True,
    )
    if has_scoped:
        # 多产品范围：每个范围保底代表，避免高分范围挤占全部名额
        return _select_with_scope_diversity(deduped, 15)
    return deduped[:15]


def multi_kb_retrieve_paradigms(
    agent_id: str,
    query_text: str,
    *,
    top: int = 5,
    scopes: Optional[List[str]] = None,
    query_vec: Optional[List[float]] = None,
) -> List[NodeWithScore]:
    """遍历所有启用 KB 的 historical_paradigms。

    query_vec：可选的预算查询向量（批量 embedding 场景避免逐条重复计算）。
    """
    from common.soc_kb_registry import load_registry

    registry = load_registry(agent_id=agent_id)
    all_results: List[NodeWithScore] = []

    for kb in registry.enabled_kbs():
        if scopes and kb.kb_id not in scopes:
            continue
        paradigm_lancedb = _kb_lancedb_dir(kb.kb_id, "historical_paradigms", agent_id)
        nodes = _search_paradigms_in_dir(
            paradigm_lancedb, query_text, top, query_vec=query_vec,
        )
        kb_weight = DEFAULT_KB_WEIGHTS.get(kb.type.value, 1.0)
        for n in nodes:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["kb_id"] = kb.kb_id
            n.node.metadata["kb_name"] = kb.name
            n.node.metadata["final_score"] = (
                float(getattr(n, "score", 0.0) or 0.0) * kb_weight
            )
        all_results.extend(nodes)

    # 去重 + 排序
    seen: set[str] = set()
    deduped: List[NodeWithScore] = []
    for n in all_results:
        nid = n.node.node_id or n.node.id_
        if nid in seen:
            continue
        seen.add(nid)
        deduped.append(n)
    deduped.sort(
        key=lambda x: x.node.metadata.get("final_score", 0.0),
        reverse=True,
    )
    return deduped[:15]


def multi_kb_retrieve_specs(
    agent_id: str,
    query_text: str,
    *,
    top: int = 10,
    scopes: Optional[List[str]] = None,
    path_prefix: Union[str, List[str], None] = None,
) -> List[NodeWithScore]:
    """遍历所有启用 KB 的 pd_spec_vector_library。

    path_prefix：可选路径前缀过滤，支持 "<kb_id>::<path>" 路由语法（剥掉 kb
    前缀后下推到该 KB 的 LanceDB where 子句）；裸 path 应用到所有 KB；
    None / 空 = 不过滤。
    """
    from common.soc_kb_registry import load_registry

    registry = load_registry(agent_id=agent_id)
    all_results: List[NodeWithScore] = []
    scoped_prefixes, has_scoped = _parse_scoped_prefixes(path_prefix)

    # 多前缀逐条检索前预算一次查询向量，避免每个前缀重复调 embedding 服务
    query_vec: Optional[List[float]] = None

    def _ensure_query_vec() -> List[float]:
        nonlocal query_vec
        if query_vec is None:
            query_vec = _get_query_embedding(query_text)
        return query_vec

    for kb in registry.enabled_kbs():
        if scopes and kb.kb_id not in scopes:
            continue
        spec_lancedb = _kb_lancedb_dir(kb.kb_id, "pd_spec_vector_library", agent_id)
        if has_scoped:
            kb_prefixes = scoped_prefixes.get(kb.kb_id, []) + scoped_prefixes.get("", [])
            if not kb_prefixes:
                nodes: List[NodeWithScore] = []  # 该 KB 无匹配范围，跳过
            else:
                nodes = _retrieve_specs_scoped(
                    spec_lancedb, query_text, top, kb_prefixes,
                    query_vec=_ensure_query_vec(),
                )
        else:
            bare = scoped_prefixes.get("", [])
            nodes = _search_product_specs_in_dir(
                spec_lancedb, query_text, top, path_prefix=bare or None,
            )
        kb_weight = DEFAULT_KB_WEIGHTS.get(kb.type.value, 1.0)
        for n in nodes:
            n.node.metadata = dict(n.node.metadata or {})
            n.node.metadata["kb_id"] = kb.kb_id
            n.node.metadata["kb_name"] = kb.name
            n.node.metadata["final_score"] = (
                float(getattr(n, "score", 0.0) or 0.0) * kb_weight
            )
        all_results.extend(nodes)

    # 去重 + 排序
    seen: set[str] = set()
    deduped: List[NodeWithScore] = []
    for n in all_results:
        nid = n.node.node_id or n.node.id_
        if nid in seen:
            continue
        seen.add(nid)
        deduped.append(n)
    deduped.sort(
        key=lambda x: x.node.metadata.get("final_score", 0.0),
        reverse=True,
    )
    if has_scoped:
        # 多产品范围：每个范围保底代表，避免高分范围挤占全部名额
        return _select_with_scope_diversity(deduped, 15)
    return deduped[:15]


def _kb_lancedb_dir(kb_id: str, table_name: str, agent_id: str) -> Path:
    """获取指定 KB 的 LanceDB 目录。

    路径：<state_root>/workspace-<agent_id>/kbs/<kb_id>/<table_name>/
    """
    from common.soc_kb_registry.paths import state_root as _state_root_path

    base = _state_root_path() / f"workspace-{agent_id}" / "kbs" / kb_id
    return base / table_name


def _search_product_specs_in_dir(
    lancedb_dir: Path,
    query_text: str,
    top_k: int,
    path_prefix: Union[str, List[str], None] = None,
    query_vec: Optional[List[float]] = None,
) -> List[NodeWithScore]:
    """在指定 LanceDB 目录里检索 pd_spec，支持 path_prefix 下推到数据库。

    path_prefix 行为：
      - None 或空 → 不过滤
      - 字符串 / 列表 → 拼成 `metadata.file_path LIKE '%prefix%' OR ...` 下推到 LanceDB

    query_vec：可选的预算查询向量（调用方批量 embedding 后逐条传入，
    避免多前缀逐个检索时重复调用 embedding 服务）；None 时按 query_text 现算。
    """
    if not lancedb_dir.exists():
        return []
    try:
        _ensure_online_bge_embed_model()

        # 取更多候选以配合 BGE 重排
        limit_n = max(top_k, 50) if path_prefix else top_k

        if path_prefix:
            # 有过滤前缀：直连 lancedb，下推 where 子句
            import lancedb as _lancedb
            query_embedding = query_vec if query_vec is not None else _get_query_embedding(query_text)
            db = _lancedb.connect(str(lancedb_dir))
            table = db.open_table("nodes")
            where_clause = _build_path_prefix_where(path_prefix)
            rows = table.search(query_embedding).where(where_clause).limit(limit_n).to_list()
        else:
            # 无过滤：用 LlamaIndex 默认检索
            vector_store = LanceDBVectorStore(uri=str(lancedb_dir), table_name="nodes")
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex.from_vector_store(
                vector_store, storage_context=storage_context
            )
            retriever = index.as_retriever(similarity_top_k=max(limit_n, 1))
            rows = []
            for n in retriever.retrieve(query_text):
                # LlamaIndex NodeWithScore → row dict 兼容
                meta = dict(n.node.metadata or {})
                if isinstance(meta.get("metadata"), str):
                    try:
                        meta = {**meta, **json.loads(meta["metadata"])}
                    except Exception:
                        pass
                rows.append({
                    "id": n.node.node_id or n.node.id_,
                    "text": n.node.get_content(),
                    "metadata": meta,
                    "_distance": 2.0 * (1.0 - float(getattr(n, "score", 0.0) or 0.0)),
                })
            rows = rows[:limit_n]

        nodes: List[NodeWithScore] = []
        for row in rows:
            meta = row.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            distance = row.get("_distance", 2.0)
            similarity = max(0.0, 1.0 - distance / 2.0)
            node = TextNode(
                text=row.get("text", ""),
                id_=row.get("id", ""),
                metadata=meta,
            )
            nodes.append(NodeWithScore(node=node, score=similarity))
        return nodes[:top_k]
    except EmbeddingServiceError:
        # 与本文件其他检索函数同约定：Embedding 失败必须传播，
        # 由调用方按业务失败（exit 2 / RAG_SYNC_FAILED）处理，
        # 不能吞成"0 命中"假正常（违反零兜底硬规则）。
        raise
    except Exception as exc:
        logger.warning("[SOC] KB spec 检索失败 (%s): %s", lancedb_dir, exc)
        return []


def _search_paradigms_in_dir(
    lancedb_dir: Path,
    query_text: str,
    top_k: int,
    query_vec: Optional[List[float]] = None,
) -> List[NodeWithScore]:
    """在指定 LanceDB 目录里检索 historical_paradigms.response_paradigm 表。

    query_vec：可选的预算查询向量（调用方批量 embedding 后逐条传入，
    避免每条需求重复调用 embedding 服务）；None 时按 query_text 现算。
    """
    if not lancedb_dir.exists():
        return []
    try:
        db = lancedb.connect(str(lancedb_dir))
        try:
            tables = db.list_tables()
            table_names = tables.tables if hasattr(tables, "tables") else tables
        except Exception:
            table_names = []
        if "response_paradigm" not in table_names:
            return []
        table = db.open_table("response_paradigm")
        if query_vec is None:
            query_vec = _get_query_embedding(query_text)
        items = (
            table.search(query_vec)
            .where("reviewed == true")
            .limit(top_k)
            .to_list()
        )
        nodes: List[NodeWithScore] = []
        for item in items:
            distance = item.get("_distance", 2.0)
            similarity = 1.0 - (distance / 2.0)
            if similarity <= 0.0:
                continue
            description = item.get("description", "")
            compliance = item.get("compliance", "")
            remarks = item.get("remarks", "")
            ref_doc = item.get("reference_document", "")
            source_file = item.get("source_file", "")
            created_at = item.get("created_at", "")
            source_path = item.get("source_path", "")

            content_parts = ["# 历史应答范式"]
            content_parts.append(f"**需求描述**: {description}")
            content_parts.append(f"**合规判定**: {compliance}")
            if remarks:
                content_parts.append(f"**备注**: {remarks}")
            if ref_doc:
                content_parts.append(f"**参考文档**: {ref_doc}")
            content_text = "\n\n".join(content_parts)

            # 与旧 _search_paradigms 保持一致的完整 metadata：
            # 应答技能靠 source_file / created_at / header_path 展示文件名与入库时间，
            # 缺了会在「📚 参考文档」里显示「未命名 / 未知」；
            # json-responder 靠 description 回填 matched_req（匹配到的历史需求描述）。
            metadata = {
                "source_type": "historical_paradigm",
                "description": description,
                "compliance": compliance,
                "remarks": remarks,
                "reference_document": ref_doc,
                "source_file": source_file,
                "source_path": source_path,
                "created_at": created_at,
                "file_name": source_file,
                "chapter_title": f"历史范式: {source_file}",
                "header_path": f"/历史应答/{source_file}",
            }
            node = TextNode(
                text=content_text,
                id_=item.get("id", ""),
                metadata=metadata,
            )
            nodes.append(NodeWithScore(node=node, score=similarity))
        return nodes
    except EmbeddingServiceError:
        raise
    except Exception as exc:
        logger.warning("[SOC] KB paradigm 检索失败 (%s): %s", lancedb_dir, exc)
        return []
