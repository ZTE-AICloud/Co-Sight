"""``POST /kbase/retrieve``：向量路 / 关键词路。

三件事必须先说清楚，否则很容易「顺手改错」：

1. **异常一律收敛成空结果**。整条链用一个兜底捕获包住，
   吞掉后返回空列表 → 上层装成 ``HTTP 200 + code=0000 + bo=[]``。所以「检索失败」和
   「没命中」在响应上**长得一样**，这正是这里反复强调的静默失败。
2. **入参校验失败走另一条路**：校验在进入业务前抛错，
   转成 ``0004`` + ``bo=null``。两条路的响应形态不同，不能合并。
3. **优先级分组的循环语义**：按 priority 从高到低逐组查，**一旦累积结果里出现非空 docs
   就立刻返回并停止降级**；全都没命中时返回的是「每个 base 一条、docs 可能为空」的全量，
   不是空列表。

另有一处**刻意保留的缺陷**，见 :func:`_related_embeddings` 里 ``records[0]`` 那行。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from model import gateway as model_gateway
from infrastructure.db import identifiers
from infrastructure.http import binding
from shared.errors.api import KbValidationError
from retrieval.service.node_mapper import (
    enrich_metadata_with_chunk_text,
    process_vector_record,
    to_search_results,
)
from retrieval.repository import es_store as es_store, vector_store as vector_store
from infrastructure.logging.logutil import log

# 字段默认值
DEFAULT_TYPE = 0
# 请求没带 model 时用它。**必须与部署实际用的 embedding 模型一致** ——
# 用错模型会让 resolve_model 在注册表里查不到 → 回落到「默认模型+默认维度」，
# 而默认维度又与被查表的列宽不符 → 维度校验失败。与别处同源的 EMBEDDING_MODEL_NAME。
DEFAULT_MODEL = os.environ.get('EMBEDDING_MODEL_NAME', '').strip() or 'Qwen3-Embedding-0.6B'
DEFAULT_TOPK = 8
DEFAULT_SCORE_THRESHOLD = 0.0

#: 检索基名前缀：``doc_<id>``。
KBASE_NAME_PREFIX = 'doc_'
#: 物理表名后缀；``doc_`` 同时是基名前缀，传物理表名时要先剥掉它。
TABLE_NAME_SUFFIXES = ('_vector', '_chunk')
VECTOR_TABLE_PREFIX = 'data_'
SCOPE_SUFFIX_SEPARATOR = '|#|'


def retrieve(dto: dict) -> list[dict]:
    """入口：**永不抛异常**（失败返回 ``[]``）。"""
    # 绑定要在**校验之前、try 之外** —— 类型不对是 0004（绑定失败），
    # 不是「检索失败回空」。
    dto = binding.bind(dto, binding.RETRIEVE_FIELDS)
    dto['bases'] = binding.bind_objects(dto.get('bases'), binding.RETRIEVE_BASE_FIELDS)
    _validate(dto)
    try:
        if dto.get('type', DEFAULT_TYPE) == 0:
            raw_results = _query_embedding(dto)
        else:
            raw_results = _query_keyword(dto)
        return to_search_results(raw_results)
    except Exception:
        log.exception('retrieve failed, returning empty result')
        return []


def _validate(dto: dict) -> None:
    """参数校验的约束（失败 → 0004，不是空结果）。

    ``priority`` **没有** ``@NotNull`` —— 它缺失时不在这里报错，
    而是在分组时炸成空结果。这是真实行为，别顺手加上校验。
    """
    if not (dto.get('question') or '').strip():
        raise KbValidationError('retrieve.question.required')

    # ``type`` 的 DTO 字段初始值是 0，所以**缺席**取 0；显式传 null 才是 null。
    retrieve_type = dto['type'] if 'type' in dto else DEFAULT_TYPE
    if retrieve_type is None:
        raise KbValidationError('retrieve.type.null')     # @NotNull
    if not isinstance(retrieve_type, int) or isinstance(retrieve_type, bool) \
            or retrieve_type not in (0, 1):
        raise KbValidationError('retrieve.type.invalid')  # @Min/@Max

    bases = dto.get('bases')
    if bases is None:
        raise KbValidationError('retrieve.bases.null')
    if not isinstance(bases, list) or not bases:
        raise KbValidationError('retrieve.bases.empty')

    for base in bases:
        base_list = (base or {}).get('baseList')
        if base_list is None:
            raise KbValidationError('retrieve.baseList.null')
        if not isinstance(base_list, list) or not base_list:
            raise KbValidationError('retrieve.baseList.empty')
        priority = (base or {}).get('priority')
        if priority is not None and not (0 <= priority <= 10):
            raise KbValidationError('retrieve.priority.outOfRange')
        top_k = (base or {}).get('top_k', DEFAULT_TOPK)
        if not (1 <= top_k <= 80):
            raise KbValidationError('retrieve.topK.outOfRange')
        threshold = (base or {}).get('score_threshold', DEFAULT_SCORE_THRESHOLD)
        if not (0.0 <= threshold <= 1.0):
            raise KbValidationError('retrieve.scoreThreshold.outOfRange')


# ----------------------------------------------------------------------
# 顶层两条路
# ----------------------------------------------------------------------


def _query_embedding(dto: dict) -> list[dict]:
    asked_model = dto.get('model', DEFAULT_MODEL)
    embedding = model_gateway.embed_query(dto['question'], asked_model)
    return _loop_search(
        dto['bases'],
        lambda base: _related_embeddings(
            embedding, base.get('baseList') or [],
            base.get('score_threshold', DEFAULT_SCORE_THRESHOLD),
            base.get('top_k', DEFAULT_TOPK),
        ),
    )


def _query_keyword(dto: dict) -> list[dict]:
    question = dto['question']
    return _loop_search(
        dto['bases'],
        lambda base: _related_keywords(
            question, base.get('baseList') or [],
            base.get('score_threshold', DEFAULT_SCORE_THRESHOLD),
            base.get('top_k', DEFAULT_TOPK),
        ),
    )


def _loop_search(bases: list[dict], search: Callable[[dict], list[dict]]) -> list[dict]:
    """``loopSearchEmbedding`` / ``loopSearchKeyword``（两者同形）。"""
    accumulated: list[dict] = []
    for group in _group_by_priority(bases):
        for base in group:
            accumulated.extend(search(base))
        # 判定用**累积**结果：高优先级组全是空 docs 时不阻断向低优先级降级
        filtered = [
            item for item in accumulated
            if isinstance(item.get('docs'), list) and item['docs']
        ]
        if filtered:
            return filtered
    return accumulated


def _group_by_priority(bases: list[dict]) -> list[list[dict]]:
    """按 priority **降序**分组，组内保持原序。

    ``priority`` 缺失时抛异常，由 :func:`retrieve` 收敛成空结果。
    """
    groups: dict[int, list[dict]] = {}
    for base in bases:
        priority = (base or {}).get('priority')
        if priority is None:
            raise ValueError('priority is required for grouping')
        groups.setdefault(priority, []).append(base)
    return [groups[priority] for priority in sorted(groups, reverse=True)]


# ----------------------------------------------------------------------
# 向量路
# ----------------------------------------------------------------------


def _related_embeddings(embedding: list[float], base_list: list[str],
                        score_threshold: float, top_k: int) -> list[dict]:
    """``EmbeddingServiceImpl.getRelatedEmbeddings``。"""
    results: list[dict] = []
    embedding_literal = vector_store.to_vector_literal(embedding)

    for base_name in base_list:
        clean_base_name = _clean_base_name(base_name)
        kbase_id = _kbase_id_from_base_name(clean_base_name)
        table_name = _vector_table_name(kbase_id, clean_base_name)

        if not vector_store.table_exists(table_name):
            log.warning('vector table does not exist for baseName: %s (cleaned: %s)',
                        base_name, clean_base_name)
            continue        # 该 base **完全不产出条目**（不是空 docs 的条目）
        chunk_table_name = _chunk_table_name(kbase_id, clean_base_name)

        records = vector_store.query_by_embedding_with_chunk(
            table_name, chunk_table_name, embedding_literal, score_threshold, top_k)
        log.info('found %d results using joint query for baseName: %s',
                 len(records), clean_base_name)
        # ⚠️ **刻意保留这个缺陷**：这里之后无条件读 ``records[0]``（下方）。
        # 新知识库 + 0 命中 → IndexOutOfBounds → 冒到 retrieve() 的 catch →
        # **整个请求 bo=[]**（而不是「这个库空 docs」）。日志只打 id，不打整条记录
        # —— 整条记录会带 768 维向量字符串，把日志淹掉；日志内容不影响任何对外行为。
        log.info('first result id: %s', records[0].get('id'))

        docs = _build_docs(records)
        results.append({'base_name': clean_base_name, 'docs': docs})

    return results


def _build_docs(records: list[dict]) -> list[dict]:
    """``getRelatedEmbeddings`` 里的节点构造（``:110-132``）。"""
    if not records:
        return []
    docs = []
    for record in records:
        enrich_metadata_with_chunk_text(
            record, record.get('chunk_text'), record.get('chunk_id'))
        docs.append(process_vector_record(record))
    return docs


# ----------------------------------------------------------------------
# 关键词路
# ----------------------------------------------------------------------


def _related_keywords(question: str, base_list: list[str],
                      score_threshold: float, top_k: int) -> list[dict]:
    """关键词检索。

    ``score_threshold`` **收下但从不使用** —— 关键词路没有阈值过滤。
    """
    results: list[dict] = []
    for base_name in base_list:
        clean_base_name = _clean_base_name(base_name)
        kbase_id = _kbase_id_from_base_name(clean_base_name)
        hits = es_store.search(kbase_id, question, top_k)
        docs = [_keyword_node_with_score(hit) for hit in hits]
        results.append({'base_name': clean_base_name, 'docs': docs})
    return results


def _es_metadata(source: dict) -> dict:
    """从扁平文档中取出统一的响应 metadata。

    只保留非空的 ``chunk_index / source / chunk_id / type``，顺序与向量路
    （``EXPANDED_FIELDS`` 去掉 ``content_expand``）一致。
    """
    flat_keys = es_store.ES_RESPONSE_METADATA_FIELDS
    values = {key: source.get(key) for key in flat_keys}
    return {key: values[key] for key in flat_keys if values.get(key) is not None}


def _keyword_node_with_score(hit: dict) -> dict:
    """``KeywordServiceImpl.buildNodeWithScore``（与向量路的同名方法**不同**）。"""
    source = hit.get('_source') or {}
    text = source.get('text')
    metadata = _es_metadata(source)

    node = {
        'id': hit.get('_id'),
        'id_': source.get('node_id') or hit.get('_id') or _random_uuid(),
        'embedding': None,
        'metadata': metadata,
        'excluded_embed_metadata_keys': [
            'content_expand', 'context_expand_method', 'source',
        ],
        'excluded_llm_metadata_keys': [],
        'relationships': {},
        'text': text,
        'start_char_idx': 0,
        'end_char_idx': len(text) if text is not None else 0,
        'text_template': '{metadata_str}\n\n{content}',
        'metadata_template': '{key}: {value}',
        'metadata_seperator': '\n',
        'class_name': 'TextNode',
        'source': metadata.get('source'),
        'content_expand': None,
        'file_id': source.get('file_id'),
    }
    return {
        'node': node,
        'score': hit.get('_score') if hit.get('_score') is not None else 0.0,
        'class_name': 'NodeWithScore',
    }


def _random_uuid() -> str:
    import uuid

    return str(uuid.uuid4())


# ----------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------


def _clean_base_name(base_name: str) -> str:
    """剥掉 ``|#|dev`` 之类的 scope 后缀（只取第一段）。"""
    if base_name and SCOPE_SUFFIX_SEPARATOR in base_name:
        return base_name.split(SCOPE_SUFFIX_SEPARATOR)[0]
    return base_name


def _kbase_id_from_base_name(clean_base_name: str) -> Optional[str]:
    """``getKbaseIdByBaseName``：只认基名 ``doc_<id>``。

    ``doc_`` 同时是物理表名前缀（``doc_<id>_vector`` / ``doc_<id>_chunk``），
    传物理表名时先剥掉表后缀，避免把 ``<id>_vector`` 当成 kbaseId。
    """
    if not clean_base_name or not clean_base_name.startswith(KBASE_NAME_PREFIX):
        return None
    token = clean_base_name[len(KBASE_NAME_PREFIX):]
    for suffix in TABLE_NAME_SUFFIXES:
        if token.endswith(suffix):
            token = token[:-len(suffix)]
            break
    return token or None


def _vector_table_name(kbase_id: Optional[str], clean_base_name: str) -> str:
    """检索基名 → 物理向量表名。

    优先读 ``kb_kbase.table_name``（通常是 ``doc_<id>_vector``）；查不到时回落到
    旧拼法 ``data_ + <baseName>``，保证滚动升级期间老行仍可检索。
    """
    if kbase_id:
        try:
            name = vector_store.select_table_name_by_kbase_id(kbase_id)
            if (name or '').strip():
                return name
        except Exception:                                          # noqa: BLE001
            log.warning('failed to resolve table_name for %s', kbase_id, exc_info=True)
    # 新基名 ``doc_<id>`` 与物理表同族：补 ``_vector`` 即可；基名已经是物理表名
    # （``doc_<id>_vector``）时原样返回。
    if clean_base_name.endswith(TABLE_NAME_SUFFIXES):
        return clean_base_name
    if clean_base_name.startswith('doc_'):
        return clean_base_name + '_vector'
    return VECTOR_TABLE_PREFIX + clean_base_name


def _chunk_table_name(kbase_id: str, clean_base_name: str) -> str:
    """``VectorChunkDao.generateChunkTableName``：``doc_<id>_vector`` → ``doc_<id>_chunk``。

    最终表名**不带 schema**，查询时再拼 `kb_index.` 前缀。
    """
    table_name = vector_store.select_table_name_by_kbase_id(kbase_id)
    base = (table_name or '').strip() or _vector_table_name(kbase_id, clean_base_name)
    return identifiers.chunk_table_for(base)


# ---------------------------------------------------------------------------
# Public wrappers for the Agent domain (it deliberately bypasses retrieve()'s
# exception flattening but reuses the same record -> node mapping).
# ---------------------------------------------------------------------------
def build_docs(records: list[dict]) -> list[dict]:
    return _build_docs(records)


def keyword_node_with_score(hit: dict) -> dict:
    return _keyword_node_with_score(hit)
