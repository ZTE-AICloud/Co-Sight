"""建库与删库（``POST /kbase`` 与 ``POST /kbase/delete/{id}``）。

建库与删库两条链路都有几处**反直觉但必须保持**的地方，见下。
"""

from __future__ import annotations

import re
from typing import Optional

from knowledge_base import name_lock
from shared.errors.api import KbApiError, KbStoreError, KbValidationError
from knowledge_base.service import kbase_service
from knowledge_base.service.embedding_dimension import (ensure_known_embedding_model,
                                                        resolve_embedding_dimension)
from infrastructure.db import ddl, identifiers
from infrastructure.storage import registry as storage_registry_store
from knowledge_base import graph_bridge as graph_lifecycle
from knowledge_base.repository import directory as directory_store, kbase as kbase_store
from retrieval.service import index as index_service
from retrieval.service import write as write_service
from infrastructure.logging.logutil import log

# 文档知识库的分类。这里**硬编码**用它，
# 请求体里带的 category 会被丢弃
CATEGORY_DOCUMENT = 1
# 文档库动态表前缀（向量表 ``doc_<id>_vector`` / 切片表 ``doc_<id>_chunk``）
TABLE_PREFIX_DOCUMENT = 'doc'
# 文档库 ES 索引前缀（``doc_<id>``，与物理表族同前缀）
ES_INDEX_PREFIX = 'doc_'
# 图谱库没有 ES 索引，列值只求与 ``table_name``（``graph_<id>``）一致
GRAPH_ES_INDEX_PREFIX = 'graph_'
# ``KbaseStatusEnum.CREATED``
STATUS_CREATED = 0
# 子类型默认值（当前不参与路由）
DEFAULT_KB_TYPE = 'document'
# ``${fileLimit.kbase}``
DEFAULT_FILE_COUNT_LIMIT = 5000

# ``KbaseReqDTO.description`` 的 @Size(max=1000) 与 ``headIcon`` 的 @Size(max=255)
DESCRIPTION_MAX = 1000
HEAD_ICON_MAX = 255
# ``${fileLimit.graph_kbase}`` —— 图谱库用（V2 建库路径）
GRAPH_FILE_COUNT_LIMIT = 50

CATEGORY_KNOWLEDGE_GRAPH = 10

# 名称正则的字符类必须显式写出（``[a-zA-Z_0-9]`` 不含中文），
# 别用 Python 的 ``\w``（它含全部 Unicode 词字符）。
_NAME_PATTERN = re.compile(r'[a-zA-Z_0-9一-龥.\-\s]{2,30}')


class _NullPropsNpe(RuntimeError):
    """``props == null`` 时的 NPE。

    用 ``RuntimeError`` 而不是 ``KbApiError``：这是**未捕获的 NPE**，
    落到全局处理器 → **0001**，不是业务异常那套 0005。router 的兜底分支正好给 0001。
    """


def _validate_name(name: Optional[str]) -> None:
    """``name`` 的两条约束（失败 → 0004）。

    ``name`` 为 null 时**两条都放行**（``@Pattern`` 对 null 不校验，``@AssertTrue`` 显式
    返回 true），随后会在 DB 的 ``NOT NULL`` 上炸掉 —— 不在这里补校验。
    """
    if name is None:
        return
    if not _NAME_PATTERN.fullmatch(name):
        raise KbValidationError('kbase.name.validation')
    if not name.strip():
        raise KbValidationError('kbase.name.not.all.whitespace')


def _validate_sizes(description: Optional[str], head_icon: Optional[str]) -> None:
    """``KbaseReqDTO`` 的两个 ``@Size`` —— **也是 0004，但跟请求语言走**。

    ``@Size`` 对 null 不校验；上界是**闭区间**（1000 与 255 都合法）。
    必须校验：缺了这两条时，1001 字的描述会直接建库成功 ——
    **多建一个本不该存在的库**（对外契约要求回 0004）。
    """
    if description is not None and len(description) > DESCRIPTION_MAX:
        raise KbValidationError('description.validation')
    if head_icon is not None and len(head_icon) > HEAD_ICON_MAX:
        raise KbValidationError('headIcon.validation')


def _keyword_analyzer(props: dict, language: str) -> str:
    """关键词 analyzer：``props.keywordAnalyzer`` 优先，否则按请求语言推。

    英文库固定 ``ik_smart`` 会让 BM25 掉约 6–7 pp nDCG@10（SciFact 离线实测
    59.82 → 66.84）；中文库必须保留 ``ik_smart``。
    """
    explicit = str((props or {}).get('keywordAnalyzer') or '').strip()
    if explicit:
        return explicit
    return 'ik_smart' if (language or '').lower().startswith('zh') else 'english'


def create_kbase(payload: dict, emp_no: str, org_id: Optional[str],
                 language: str = '') -> dict:
    """建库。返回 ``KbaseVO``。

    三步顺序固定：**加锁 → 判重（可复用）→ 三写（表/表/索引）**。

    重名复用是这里最容易看错的一处：同名且**该库下没有文件**时不报错，而是**直接复用**
    那个库（连同它的向量表与索引），且不再建 access。只有「同名**且有文件**」才报
    ``RetCode.kbase.exist``。
    """
    name = payload.get('name')
    _validate_name(name)
    _validate_sizes(payload.get('description'), payload.get('headIcon'))

    # ⚠️ ``props`` **缺席就是 NPE**，不是「回落到空」。
    # props 为 null → NPE → **0001**（"Cannot invoke PropsDTO.getEmbeddingModel()
    # because the return value of KbaseReqDTO.getProps() is null"）。
    # 不能写成 ``payload.get('props') or {}``：那会**静默建库成功**，与应有行为相反。
    # V2 的同名方法有同样的 NPE。
    props = payload.get('props')
    if props is None:
        raise _NullPropsNpe(
            'Cannot invoke "PropsDTO.getEmbeddingModel()" because "KbaseReqDTO.getProps()" is null')
    embedding_model = props.get('embeddingModel')
    description = payload.get('description') or ''      # defaultString：null → ''
    kb_type = payload.get('kbtype') or DEFAULT_KB_TYPE

    try:
        with name_lock.acquire(org_id, name):
            existing = kbase_store.find_kbases_by_name(name, org_id)
            if existing:
                candidate = existing[0]
                if kbase_store.count_files(candidate['kbase_id']) > 0:
                    raise KbApiError('kbase.exist')
                log.info('reusing empty kbase %s named %s', candidate['kbase_id'], name)
                return kbase_service.get_kbase_detail(candidate['kbase_id'])

            # 名字解析不到时写路径会**静默换成** .env 默认模型 → 记录与向量分家，
            # 所以在建表/入库之前就拒（0004）。放在取 ID 之前，坏输入不产生任何副作用。
            ensure_known_embedding_model(embedding_model)
            kbase_id = kbase_store.generate_kbase_id()
            table_name = identifiers.doc_vector_table(kbase_id)
            try:
                pk_id = kbase_store.insert_kbase(
                    kbase_id=kbase_id,
                    name=name,
                    description=description,
                    kbase_type=kb_type,
                    embedding_model=embedding_model,
                    table_name=table_name,
                    es_index_name=ES_INDEX_PREFIX + kbase_id,
                    category=CATEGORY_DOCUMENT,
                    status=STATUS_CREATED,
                    file_count_limit=DEFAULT_FILE_COUNT_LIMIT,
                    org_id=org_id,
                    created_by=emp_no,
                )
            except KbStoreError as error:
                if error.kind == KbStoreError.DUPLICATE:
                    raise KbApiError('kbase.exist') from error
                raise

            # 三写：向量表、chunk 表、ES 索引（都先判存，幂等）
            # 向量列必须带维度，否则 pgvector 无法建 HNSW 索引。
            dimension = resolve_embedding_dimension(embedding_model)
            storage_registry_store.begin_create(
                kbase_id, name, CATEGORY_DOCUMENT, table_name, embedding_model, dimension)
            try:
                ddl.create_vector_table(table_name, dimension)
                ddl.create_chunk_table(identifiers.chunk_table_for(table_name))
                index_service.create_index(
                    kbase_id, keyword_analyzer=_keyword_analyzer(props, language))

                # 默认目录：title 取 language-option 头，**严格等于 zh-CN** 才算中文
                _create_default_directory(
                    kbase_id, '默认文件夹' if language == 'zh-CN' else 'Default')
            except Exception as error:                             # noqa: BLE001
                storage_registry_store.mark_failed(kbase_id, str(error))
                raise
            storage_registry_store.mark_ready(kbase_id)

            log.info('created kbase %s (pk=%s) named %s', kbase_id, pk_id, name)
            # ⚠️ 建库的响应是**窄 VO**：只设 ``pkId/type/id/name`` 四个字段，
            # 其余全为 null —— 这时 ES 索引与动态表刚建、文件数为 0，
            # 所以前端建完还会再拉一次详情。
            # 别「顺手」改成 get_kbase_detail：**重名复用那条路返回的才是全量 VO**，
            # 两条路形状不同是真实的。
            return {
                'id': kbase_id,
                'pkId': pk_id,
                'name': name,
                'headIcon': None,
                'type': kb_type,
                'description': None,
                'props': None,
                'esIndexName': None,
                'embeddingModel': None,
                'currentFileCount': None,
                'fileCountLimit': None,
                'createdBy': None,
                'createdDate': None,
                'lastUpdatedBy': None,
                'lastUpdatedDate': None,
                'fullName': None,
                'fullNameEn': None,
                'tableName': None,
                'action': None,
                'operatorId': None,
                'failReason': None,
                'status': None,
                'schemaName': None,
                'schemaObj': None,
                'process': None,
                'processDetailInfo': None,
            }
    except name_lock.NameLockAcquireException:
        raise KbApiError('kbase.name.lock.timeout')


def _create_default_directory(kbase_id: str, title: str) -> None:
    """``DirectoryService.createDefaultDirectoryIfAbsent``：已有同名就不建（父为 null）。"""
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            if directory_store.find_folder_by_title(cursor, kbase_id, None, title):
                return
            directory_store.insert_directory(
                cursor, kbase_id, None, directory_store.ROOT_DIRECTORY_SYMBOL,
                title, directory_store.TYPE_FOLDER, status=None)


def delete_kbase(kbase_id: str, emp_no: str = '') -> None:
    """删库：判空 → 逐目录删 → drop 两张动态表 → 删 kb_kbase 行 → 删 ES 索引。

    注意 ``dropTable`` 与 ``deleteIndex`` 都是幂等的（先判存在），但**整体不幂等**：
    第二次删同一个库时会失败。这里给一个明确的业务错误，行为上同样是「失败」。

    ⚠️ v1 路由必须按 ``category`` 区分：删图谱库时还要清 ``_vector`` / 任务表 /
    registry / 图存储。图谱库（category=10）直接委托 v2 的完整删除链。
    """
    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise KbApiError('kbase.not.exist')

    if str(row.get('category')) == str(CATEGORY_KNOWLEDGE_GRAPH):
        # 延迟 import：kbase_v2_service 在模块顶层 import 本模块，顶层反向 import
        # 会形成循环。
        from knowledge_base.service import kbase_v2_service

        kbase_v2_service.delete_kbase(kbase_id, emp_no)
        return

    if kbase_store.count_files(kbase_id) > 0:
        raise KbApiError('kbase.can.not.delete.include.knowledge')

    storage_registry_store.begin_delete(kbase_id)
    table_name = row.get('table_name')
    delete_directories_of_kbase(kbase_id)

    if table_name:
        ddl.drop_table(table_name)
        ddl.drop_table(identifiers.chunk_table_for(table_name))

    index_service.delete_index(kbase_id)     # 必须先于删行取名字 —— 这里内部还会查一次
    kbase_store.delete_kbase_row(kbase_id)
    storage_registry_store.remove(kbase_id)
    log.info('deleted kbase %s', kbase_id)


def delete_directories_of_kbase(kbase_id: str) -> None:
    """逐个删掉库内所有文件夹（含级联的文件与索引残留）。

    与 ``KbaseService.deleteDirectory`` 私有方法同序：先查子孙 → 删除目录与文件 →
    清 ``kb_node_relation`` 与属性 → 删磁盘文件。
    """
    from knowledge_base.repository import node_relation as node_relation_store
    from infrastructure.storage import kb_storage as storage

    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        return
    pk_id = row.get('id')

    for folder in directory_store.get_all_folders(kbase_id):
        _delete_one_directory(kbase_id, pk_id, folder['id'], storage)

    # 没有父文件夹的游离文件（例如建库时落下的）也一并清掉
    _purge_files(kbase_id, pk_id, [d['id'] for d in directory_store.get_children(
        kbase_id, None, directory_store.TYPE_FILE)], node_relation_store, storage)


def _delete_one_directory(kbase_id: str, pk_id: int, directory_id: str, storage) -> None:
    from knowledge_base.repository import node_relation as node_relation_store

    descendants = directory_store.get_descendants(kbase_id, directory_id)
    file_ids = [d['id'] for d in descendants if d.get('type') == directory_store.TYPE_FILE]
    folder_ids = [d['id'] for d in descendants if d.get('type') != directory_store.TYPE_FILE]
    _purge_files(kbase_id, pk_id, file_ids, node_relation_store, storage)
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.delete_folders(cursor, folder_ids + [directory_id])


def _purge_files(kbase_id: str, pk_id: int, file_ids: list, node_relation_store, storage) -> None:
    """清这些文件/目录的索引与磁盘文件（删库 / 删目录 / 删文件共用）。

    ⚠️ **顺序有讲究**：

    1. **先取文件名** —— 切片表的 ``source`` 存的就是文件名，删除之后仍能读，
       但要在删除记录之前取；
    2. 删 relation / 向量（``node_relation_store``）；
    3. **按文件名删切片行** —— 漏了这一步，删完文件后 ``_chunk`` 表会残留孤儿行；
    4. 删除 ``kb_directory`` 行；
    5. 删磁盘文件。
    """
    if not file_ids:
        return

    # 1. 名字要在删除之前取（行删掉后就读不到了）
    file_names = directory_store.titles_by_ids(kbase_id, file_ids)

    # 2. relation / 向量
    node_relation_store.delete_by_directory_ids(pk_id, file_ids)

    row = kbase_store.select_kbase_by_id(kbase_id)
    table_name = (row or {}).get('table_name')

    # 2.5 关键词索引按 file_id 清掉；否则删文件后关键词路仍能搜到残留文档。
    #     table_name 为空说明不是正常的文档库（不能拿 pkId 回退去猜索引名）。
    if table_name:
        write_service.delete_es_documents_by_query(kbase_id, 'file_id', file_ids)

    # 2.8 图谱库：先取该 source 的 chunk id，再同步删图存储实体/边与向量。
    #     必须在步骤 3 删 chunk 行之前取；图存储删除失败会抛出，整个文件删除可重试。
    is_graph = (str((row or {}).get('category')) == '10'
                or (table_name or '').startswith('graph_'))
    if is_graph and table_name and file_names:
        chunk_ids = graph_lifecycle.chunk_ids_for_sources(table_name, file_names)
        if chunk_ids:
            graph_lifecycle.delete_source_graph_data(table_name, kbase_id, chunk_ids)

    # 3. 切片表按 source（= 文件名）清
    if table_name and file_names:
        # 图谱库还要顺带清 ``_vector`` 里对应的 chunk 向量（helper 内部判表存在）
        graph_lifecycle.delete_chunks_by_sources(table_name, file_names)

    # 3.5 属性行：漏了这一步，删文件后属性永久残留。
    directory_store.delete_properties_by_file_ids(kbase_id, file_ids)

    # 4. 删除文件行
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.delete_files(cursor, kbase_id, file_ids)

    # 5. 磁盘
    for file_id in file_ids:
        storage.delete_core_file(file_id)


def chunk_table_name(table_name: Optional[str], pk_id: int) -> str:
    """供其它模块复用：``doc_<id>_chunk`` / ``graph_<id>_chunk``。"""
    base = (table_name or '').strip() or identifiers.doc_vector_table(str(pk_id))
    return identifiers.chunk_table_for(base)
