"""画布「知识库下拉」的数据源。

**这是本地数据源**：flow_api 直接查库组装，不再 HTTP 透传
``POST /workflow/allStatusKbase``。

**为什么不复用 ``GET /kbase`` 或 ``/kbase/search``**（这里踩过同样的坑）：
下拉要的 ``tableName`` 是**检索侧基名** ``doc_<uuid>``
（与 ES 索引名、物理表族同前缀），不是 ``kb_kbase.table_name`` 那一列的物理表名
（``doc_<uuid>_vector``）。前端把基名存进算子的
``knowledge_info_list[].knowledge_base_name``，运行时按 ``kb_kbase.table_name``
解析物理表；两种名字混用会**静默返回空结果**。

分组：``running`` = 已发布 ``7`` / 发布后又改 ``8``，其余一律 ``dev``。
"""

from __future__ import annotations

from typing import Optional

from knowledge_base.repository import kbase as kbase_store
from infrastructure.logging.logutil import log

GROUP_RUNNING = 'running'
GROUP_DEV = 'dev'

# ``KbaseStatusEnum``：7 已发布 / 8 发布后已修改 —— 都算「线上有一版能跑」
PUBLISHED_STATUSES = {'7', '8'}

# ``KbCategoryEnum.KNOWLEDGE_GRAPH.getCode()``
CATEGORY_KNOWLEDGE_GRAPH = 10

# 文档库检索基名：``doc_<uuid>``，与 ES 索引名（``es_store.INDEX_PREFIX``）和
# 物理表族（``doc_<uuid>_vector`` / ``doc_<uuid>_chunk``）同前缀。
RETRIEVAL_NAME_PREFIX = 'doc_'


class KbaseTableOptionProvider:
    """从 ``rag_studio.kb_kbase`` 直接取画布下拉项（结构上满足 flow_api 的 Protocol）。"""

    def list_options(self, embedding_model: Optional[str] = None) -> dict[str, list[dict]]:
        wanted_model = (embedding_model or '').strip()
        rows = kbase_store.select_all_kbases()
        # getAuthorityKbases 会按名称排序，下拉顺序沿用（大小写不敏感，见 kbase_service 的说明）
        rows.sort(key=lambda row: ((row.get('name') or '').lower(), row.get('name') or ''))

        grouped: dict[str, list[dict]] = {GROUP_RUNNING: [], GROUP_DEV: []}
        for row in rows:
            table_name = row.get('table_name')
            if not table_name:
                # 没有 tableName 的库画布绑不了（算子里存的就是它）—— 跳过并留日志，
                # 不要返回「看起来能选、选了检索不到」的选项
                log.warning('skip kbase %s in canvas dropdown: tableName is missing',
                            row.get('name'))
                continue
            if wanted_model and row.get('embedding_model') != wanted_model:
                continue

            option = {
                'kbasePkId': row.get('id'),
                'name': row.get('name'),
                'tableName': _retrieval_base_name(row),
                'dbTableName': table_name,
                'type': row.get('type'),
                # 没有资产中心，没有 assetId 可取；用知识库自身 uuid 顶替，
                # 只要在本次返回里唯一即可（用途是前端下拉项的 key）
                'assetId': row.get('kbase_id'),
                'status': row.get('status'),
                # 向量模型：画布的检索器算子要把它写进 kwargs.embedding，
                # 不带的话后端会用旧默认模型，与库里写入的向量对不上 → 检索命中为空
                'embeddingModel': row.get('embedding_model'),
            }
            group = GROUP_RUNNING if str(row.get('status')) in PUBLISHED_STATUSES else GROUP_DEV
            grouped[group].append(option)

        log.info('allStatusKbase: %d running, %d dev (total %d kbase(s))',
                 len(grouped[GROUP_RUNNING]), len(grouped[GROUP_DEV]), len(rows))
        return grouped


def _retrieval_base_name(row: dict) -> str:
    """传给检索的库名：图谱库用物化表名，文档库用 ``doc_<uuid>``。"""
    if row.get('category') == CATEGORY_KNOWLEDGE_GRAPH:
        return row.get('table_name')
    return RETRIEVAL_NAME_PREFIX + str(row.get('kbase_id'))
