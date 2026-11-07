"""关键词路的 ES 访问。

* 索引名：``<前缀>_<tableName 为空 ? 自增 id : kbaseId>``。
  前缀为 ``doc``（与物理表族 ``doc_<id>_vector`` / ``doc_<id>_chunk`` 一致）。
* 搜索：索引字段是 ``text``。有 IK 用 ``ik_smart``，
  没有则 ``minimum_should_match: 100%``（否则 standard 分词把中文切成单字，
  matchQuery 的 OR 语义会对不存在的词误报）。
* IK 探测：``GET _cat/plugins``，结果**只在启动时探一次**并缓存。

ES 连接复用 ``ESClientSingleton``（与其他模块共用同一实例）。
"""

from __future__ import annotations

import os
import struct
import time

from infrastructure.logging.logutil import log
from retrieval.repository.kbase_lookup import get_kbase_row

#: 文档库 ES 索引名前缀：索引 = 检索基名 = ``doc_<kbaseId>``，与物理表族
#: ``doc_<id>_vector`` / ``doc_<id>_chunk`` 同前缀。
INDEX_PREFIX = 'doc'

#: 当前 ES 文档 schema 版本（扁平文档）。
SCHEMA_VERSION = 2
#: mapping 元数据（analyzer）的缓存 TTL。
MAPPING_CACHE_TTL_SECONDS = 30

#: v2 扁平文档的全部顶层字段（``_id`` 不在此列表，它等于 ``node_id``）。
ES_DOCUMENT_FIELDS = (
    'node_id', 'file_id', 'text', 'source', 'chunk_index', 'chunk_id', 'type',
)

#: 两条检索路统一对外透出的 metadata 键（按向量表 ``EXPANDED_FIELDS`` 的顺序）。
ES_RESPONSE_METADATA_FIELDS = ('chunk_index', 'source', 'chunk_id', 'type')

# 只探一次并缓存（首次用到时探）。
_ik_status: bool | None = None

#: ``index -> (monotonic_ts, keyword_analyzer)``；查询侧必须与索引侧用同一个
#: analyzer，否则英文 ``english`` 索引被 ``ik_smart`` 查询会大面积 0 命中。
_analyzer_cache: dict[str, tuple[float, str]] = {}


def _client():
    from infrastructure.search.elasticsearch import ESClientSingleton

    return ESClientSingleton().get_client()


def ik_analyzer_enabled() -> bool:
    """ES 集群是否装了 ``analysis-ik``（``_cat/plugins`` 探测）。"""
    global _ik_status
    if _ik_status is None:
        try:
            plugins = _client().cat.plugins(format='json')
            _ik_status = any(p.get('component') == 'analysis-ik' for p in (plugins or []))
        except Exception:
            log.exception('probe es ik analyzer failed')
            _ik_status = False
        log.info('es analysis-ik enabled: %s', _ik_status)
    return _ik_status


def _index_middle(table_name: str | None, kbase_pk_id: int, kbase_id: str) -> str:
    """⚠️ 三元分支容易看错：``table_name`` **为空**时用自增主键 ``id``，非空时用
    **入参的 ``kbaseId``**（而不是表名）。本栈的 ``table_name`` 恒为新物理名
    （文档库 ``doc_<uuid>_vector``），所以实际索引名是 ``doc_<kbaseId>``。
    """
    return str(kbase_pk_id if not (table_name or '').strip() else kbase_id)


def index_name(table_name: str | None, kbase_pk_id: int, kbase_id: str) -> str:
    """``getIndexName`` 的命名规则（``doc_<kbaseId>``）。"""
    return f'{INDEX_PREFIX}_{_index_middle(table_name, kbase_pk_id, kbase_id)}'


def _match_clause(field: str, question: str, use_ik: bool,
                  analyzer: str | None = None) -> dict:
    """构造单字段 match clause；无 analyzer 时保留 ``minimum_should_match: 100%``。

    ``analyzer`` 必须与索引 mapping 的 ``text.analyzer`` 一致；中文用
    ``ik_smart``，英文用 ``english``（standard + stemming），其余用 ``standard``。
    """
    match_body: dict = {'query': question}
    selected = analyzer if analyzer is not None else ('ik_smart' if use_ik else None)
    if selected:
        match_body['analyzer'] = selected
    else:
        match_body['minimum_should_match'] = '100%'
    return {'match': {field: match_body}}


def index_exists_by_name(name: str) -> bool:
    """索引是否存在（``name`` 是 ``index_name(...)`` 的产物，不是 kbaseId）。

    Agent 接口需要把「索引不存在 = 空结果」与「ES 不可用 = 502」分开，
    所以单独暴露这条判断；``search`` 仍是「不存在就返回空」语义。
    """
    # RKB 的 ES 是自研 REST 包装器（ESRestfulClientWrapper），接口是
    # `client.indices.exists(...)` / `client.cat.plugins(...)` 两个命名空间 ——
    # 不是 elasticsearch-py 的 `client.indices.exists`（同名不同物）也不是
    # 内层 ESRestfulClient 的 `indices_exists`。
    return bool(_client().indices.exists(name))


def search_index(name: str, question: str, top_k: int,
                 analyzer: str | None = None) -> list[dict]:
    """在**已确认存在**的索引上执行全文检索，返回原始 hits。"""
    client = _client()
    use_ik = ik_analyzer_enabled()
    selected = analyzer if analyzer is not None else index_keyword_analyzer(name)
    query = _match_clause('text', question, use_ik, selected)

    body = {'query': query, 'track_scores': True, 'size': top_k}
    result = client.search(index=name, body=body) or {}
    hits = ((result.get('hits') or {}).get('hits')) or []
    return [
        {'_id': hit.get('_id'), '_score': _widen_es_score(hit.get('_score')),
         '_source': hit.get('_source')}
        for hit in hits
    ]


def search(kbase_id: str, question: str, top_k: int) -> list[dict]:
    """``FullTextClient.search``：返回 ``[{_id, _score, _source}, ...]``。

    索引不存在时返回空列表（不报错）。
    """
    
    row = get_kbase_row(kbase_id)
    if row is None:
        # 库不存在时直接抛出去，由上层收敛成 bo=[]。
        raise LookupError(f'kbase not found for es index: {kbase_id}')

    name = index_name(row.get('table_name'), row.get('id'), kbase_id)
    if not index_exists_by_name(name):
        log.info('kbase_id:%s indexName: %s not support es', kbase_id, name)
        return []
    return search_index(name, question, top_k)


def _widen_es_score(score):
    """把 ES 的分数按 **float32 → double** 还原，否则会差一串尾数。

    ES 的 ``_score`` 是 32 位浮点，按 ``float`` 读入再当 ``double`` 用，
    序列化出来是**float32 的 double 展开**：

    * 期望值：``3.0150585174560547``
    * 直接取 JSON 字面量：``3.0150585``

    两个数数值相等，但 ``repr`` 不同 → 对比时每次都报差异，前端如果拿它做
    字符串比较也会不一致。``struct`` 往返一次即可拿到同一个 double。
    """
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return score
    try:
        return struct.unpack('f', struct.pack('f', float(score)))[0]
    except (struct.error, OverflowError):
        return score


# ----------------------------------------------------------------------
# 索引的建与删（建库/删库用）
#
# v2 文档是**扁平**的：字段与 PG 向量表的展开列一一对应，不再有嵌套
# ``metadata``。``dynamic: strict`` 让写侧漏字段/多字段在 bulk 时显式报错，
# 而不是被动态 mapping 悄悄吞掉。
# ----------------------------------------------------------------------


def index_body(use_ik: bool, keyword_analyzer: str | None = None) -> dict:
    """建索引体；``keyword_analyzer`` 按知识库语言选（zh→ik_smart，en→english）。

    不传时保持旧行为：有 IK 用 ``ik_smart``，否则不指定（standard）。
    """
    if keyword_analyzer is None and use_ik:
        keyword_analyzer = 'ik_smart'
    if keyword_analyzer == 'ik_smart' and not use_ik:
        # 集群没装 IK，硬写 ik_smart 会建索引失败；退回 standard。
        keyword_analyzer = None
    text_prop: dict = {'type': 'text'}
    # 单节点开发/私有化默认 0 副本，避免集群长期 yellow；多节点部署用
    # ES_NUMBER_OF_REPLICAS=1 覆盖。已有索引需要 PUT _settings 另外改。
    try:
        replicas = int(os.environ.get('ES_NUMBER_OF_REPLICAS', '0') or 0)
    except ValueError:
        replicas = 0
    settings: dict = {'number_of_replicas': max(0, replicas), 'number_of_shards': 1}
    if keyword_analyzer:
        text_prop['analyzer'] = keyword_analyzer
        if keyword_analyzer == 'ik_smart':
            settings['analysis'] = {'analyzer': {'ik': {'tokenizer': 'ik_smart'}}}
    return {
        'settings': settings,
        'mappings': {
            'dynamic': 'strict',
            '_meta': {'schema': 'kb_index_document', 'schema_version': SCHEMA_VERSION,
                      'keyword_analyzer': keyword_analyzer or 'standard'},
            'properties': {
                'node_id': {'type': 'keyword'},
                'file_id': {'type': 'keyword'},
                'text': text_prop,
                'source': {'type': 'keyword'},
                'chunk_index': {'type': 'keyword'},
                'chunk_id': {'type': 'integer'},
                'type': {'type': 'short'},
            },
        },
    }


def index_keyword_analyzer(index: str) -> str:
    """读索引的关键词 analyzer（``_meta.keyword_analyzer``，缺失时回退 mapping）。

    查询侧必须与写入侧一致：英文库建索引用 ``english``，查询若仍用
    ``ik_smart`` 会大面积 0 命中（离线实测 nDCG@10 66.84 → 40.52）。
    """
    cached = _analyzer_cache.get(index)
    now = time.monotonic()
    if cached is not None and now - cached[0] < MAPPING_CACHE_TTL_SECONDS:
        return cached[1]
    analyzer = 'standard'
    try:
        mapping = _client().indices.get_mapping(index) or {}
        payload = mapping.get(index)
        if payload is None and mapping:
            payload = next(iter(mapping.values()))
        body = (payload or {}).get('mappings') or {}
        meta = body.get('_meta') or {}
        analyzer = (meta.get('keyword_analyzer')
                    or ((body.get('properties') or {}).get('text') or {}).get('analyzer')
                    or 'standard')
    except Exception:
        log.warning('read es keyword analyzer failed for %s, use standard',
                    index, exc_info=True)
    _analyzer_cache[index] = (now, analyzer)
    return analyzer


def create_index(kbase_id: str, keyword_analyzer: str | None = None) -> None:
    """按 kbaseId 建索引（``doc_<kbaseId>``）。

    已存在则跳过。
    """

    row = get_kbase_row(kbase_id)
    name = index_name(row.get('table_name') if row else None,
                      row.get('id') if row else 0, kbase_id)
    client = _client()
    if client.indices.exists(name):
        log.info('index %s already exists, skip', name)
        return
    body = index_body(ik_analyzer_enabled(), keyword_analyzer)
    client.indices.create(name, body=body)
    _analyzer_cache[name] = (
        time.monotonic(),
        body['mappings']['_meta'].get('keyword_analyzer') or 'standard')
    log.info('created es index %s analyzer=%s', name, keyword_analyzer or 'auto')


def delete_index(kbase_id: str) -> None:
    """``FullTextClient.deleteIndex``：先判存再删，不存在静默跳过（幂等）。"""

    row = get_kbase_row(kbase_id)
    name = index_name(row.get('table_name') if row else None,
                      row.get('id') if row else 0, kbase_id)
    client = _client()
    if not client.indices.exists(name):
        log.info('index %s not exists, skip delete', name)
        return
    client.indices.delete(name)
    _analyzer_cache.pop(name, None)
    log.info('deleted es index %s', name)
