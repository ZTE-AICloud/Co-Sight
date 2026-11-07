"""图谱库走过的 kbase 端点。

## 与 v1 的四条实质差别（别把两套合并）

1. **建库用的是 ``createKbaseForGraph``**：``category`` 由请求决定（默认 1 文档库），
   图谱库（10）的 ``table_name`` 是 ``graph_<uuid>`` 而不是 ``data_kb_index_<uuid>``，
   而且**不建 ES 索引**。
2. **``fileCountLimit`` 恒取 ``fileLimit.graph_kbase`` = 50**，文档图谱一个值 ——
   注入的是同名字段，源码没有按 category 分流。v1 那条路才是 5000。
3. **建库不建默认目录**。v1 的控制器会 ``createDefaultDirectoryIfAbsent``，V2 不建。
4. **删库走 ``deletePrecheck`` 而不是「空库才许删」**：查**画布绑定**，被知识检索
   引用了就不许删（fail-open：绑定查询本身坏掉时按「没绑定」放行）。

## 图谱库不建裸 ``graph_<id>`` 表

建库时不创建裸 ``graph_<id>``（检索向量在导入时懒建为 ``_vector``），
``deleteGraph`` 只 drop ``graph_<id>_chunk`` / ``graph_<id>_vector``，**从不删它**，
所以绝不能创建它，否则会积累孤儿表。图谱向量走 ``graph_<id>_vector``
（导入时由 ``graph_index_store.build_index`` 懒建）。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.db import identifiers
from infrastructure.http import binding
from knowledge_base import name_lock
from knowledge_base import graph_bridge as graph_lifecycle
from shared.errors.api import KbApiError, KbStoreError
from knowledge_base.service import directory_service, kbase_service
from knowledge_base.service.embedding_dimension import (ensure_known_embedding_model,
                                                        resolve_embedding_dimension)
from knowledge_base.repository import directory as directory_store, kbase as kbase_store
from retrieval.service import index as index_service
from infrastructure.storage import registry as storage_registry_store
from knowledge_base.service.kbase_write_service import (
    ES_INDEX_PREFIX,
    GRAPH_ES_INDEX_PREFIX,
    _NullPropsNpe,
    _keyword_analyzer,
    _validate_name,
    _validate_sizes,
    delete_directories_of_kbase,
)
from infrastructure.logging.logutil import log

# ``KbCategoryEnum``
CATEGORY_DOCUMENT = 1
CATEGORY_KNOWLEDGE_GRAPH = 10

# 文档库动态表前缀（``doc_<id>_vector`` / ``doc_<id>_chunk``）与图谱库基名前缀
TABLE_PREFIX_DOCUMENT = 'doc'
TABLE_PREFIX_GRAPH = 'graph'

DEFAULT_KB_TYPE = 'document'
STATUS_CREATED = 0

# ``@Value("${fileLimit.graph_kbase}")`` —— **两个 category 共用这一个值**
V2_FILE_COUNT_LIMIT = 50

# ``EffectiveScopeEnum`` 的后缀
SCOPE_SUFFIXES = ('|#|dev', '|#|publish')

# 字段（camelCase，没有别名）
KBASE_REQ_FIELDS = {
    'name': binding.STRING,
    'description': binding.STRING,
    'headIcon': binding.STRING,
    'kbtype': binding.STRING,
    'props': binding.MAP,
    'category': binding.INTEGER,
    'kbaseId': binding.STRING,
}
PROPS_FIELDS = {'embeddingModel': binding.STRING}


def create_kbase(payload: dict, emp_no: str, org_id: Optional[str],
                 language: str = '') -> dict:
    """``POST /kbase/graph``。返回**窄 VO**（只有 pkId/type/id/name/headIcon 有值）。"""
    payload = binding.bind(payload, KBASE_REQ_FIELDS)
    # 只在确实是对象时才往里绑：``props`` 缺席/为 null 要保持 None ——
    # 那是 **NPE 路径**（0001），不是绑定失败（0004）。
    if isinstance(payload.get('props'), dict):
        payload['props'] = binding.bind(payload['props'], PROPS_FIELDS)

    name = payload.get('name')
    _validate_name(name)
    _validate_sizes(payload.get('description'), payload.get('headIcon'))

    # ``createKbaseForGraph(... getProps().getEmbeddingModel() ...)`` —— 与 v1 同款 NPE
    props = payload.get('props')
    if props is None:
        raise _NullPropsNpe(
            'Cannot invoke "PropsDTO.getEmbeddingModel()" because "KbaseReqDTO.getProps()" is null')

    # ``category.equals(...)``：DTO 默认值是 1，但**显式传 null** 会 NPE
    category = payload['category'] if 'category' in payload else CATEGORY_DOCUMENT
    if category is None:
        raise RuntimeError('Cannot invoke "java.lang.Integer.equals(Object)" '
                           'because "category" is null')

    try:
        with name_lock.acquire(org_id, name):
            existing = _find_name_conflict(name, org_id, exclude_id=None)
            if existing is not None:
                # 同名且有文件 → 抛；同名但空 → **复用**（连它的表与索引一起）
                return _reuse_or_raise(existing, name, category)

            embedding_model = props.get('embeddingModel')
            # 名字解析不到时写路径会**静默换成** .env 默认模型 → 记录与向量分家，
            # 所以在建表/入库之前就拒（0004）。放在取 ID 之前，坏输入不产生任何副作用。
            ensure_known_embedding_model(embedding_model)

            kbase_id = payload.get('kbaseId') or kbase_store.generate_kbase_id()
            kb_type = payload.get('kbtype') or DEFAULT_KB_TYPE
            table_name = _table_name(category, kbase_id)

            try:
                pk_id = kbase_store.insert_kbase(
                    kbase_id=kbase_id,
                    name=name,
                    description=payload.get('description') or '',
                    kbase_type=kb_type,
                    embedding_model=embedding_model,
                    table_name=table_name,
                    es_index_name=(GRAPH_ES_INDEX_PREFIX
                                   if category == CATEGORY_KNOWLEDGE_GRAPH
                                   else ES_INDEX_PREFIX) + kbase_id,
                    category=category,
                    status=STATUS_CREATED,
                    file_count_limit=V2_FILE_COUNT_LIMIT,
                    org_id=org_id,
                    created_by=emp_no,
                    head_icon=payload.get('headIcon'),
                )
            except KbStoreError as error:
                if error.kind == KbStoreError.DUPLICATE:
                    raise KbApiError('kbase.exist') from error
                raise

            dimension = resolve_embedding_dimension(embedding_model)
            storage_registry_store.begin_create(
                kbase_id, name, category, table_name, embedding_model, dimension)
            try:
                _create_tables(table_name, dimension, category=category)
                # 图谱库**不建 ES 索引**（``category == 10`` 那条 if）
                if category != CATEGORY_KNOWLEDGE_GRAPH:
                    index_service.create_index(
                        kbase_id, keyword_analyzer=_keyword_analyzer(props, language))
            except Exception as error:                             # noqa: BLE001
                storage_registry_store.mark_failed(kbase_id, str(error))
                raise
            storage_registry_store.mark_ready(kbase_id)

            # ⚠️ V2 **不建默认目录**（v1 的控制器才建）。别「顺手」补上。
            log.info('v2 created kbase %s (pk=%s, category=%s)', kbase_id, pk_id, category)
            # ``createKbaseForGraph`` 只 builder 了五个字段，其余全 null —— 但
            # 没有「非 null 才输出」的策略，所以**26 个键都要出现**。
            # 只回那五个键会少 21 个键，前端按「键存在」解析。
            return _narrow_vo(kbase_id, pk_id, name, payload.get('headIcon'), kb_type)
    except name_lock.NameLockAcquireException:
        raise KbApiError('kbase.name.lock.timeout')


def _narrow_vo(kbase_id: str, pk_id: int, name: str, head_icon, kb_type: str) -> dict:
    """``createKbaseForGraph`` 的返回：全字段在场、只有这五个有值。"""
    # 复用 kbase_service 的字段全集，顺序也一致
    vo = dict(kbase_service._base_vo({}))
    vo.update({'id': kbase_id, 'pkId': pk_id, 'name': name,
               'headIcon': head_icon, 'type': kb_type})
    return vo


def _table_name(category: int, kbase_id: str) -> str:
    if category == CATEGORY_KNOWLEDGE_GRAPH:
        return f'{TABLE_PREFIX_GRAPH}_{kbase_id}'
    return identifiers.doc_vector_table(kbase_id)


def _create_tables(table_name: str, dimension: int | None = None, *,
                   category: int) -> None:
    """建库时的动态表，都先判存在（幂等）。

    * 文档库（``doc_<id>_vector``）：向量表 + 切片表 ``doc_<id>_chunk``；
    * 图谱库（``graph_<id>``）：**只建**切片表 ``graph_<id>_chunk`` 与图库本体
      （``_vertex`` / ``_edge``）。图谱向量走导入时懒建的 ``_vector``。
    """
    from infrastructure.db import ddl

    if category != CATEGORY_KNOWLEDGE_GRAPH:
        ddl.create_vector_table(table_name, dimension)
        ddl.create_chunk_table(identifiers.chunk_table_for(table_name))
    else:
        # 图谱 chunk 保留导入/导出契约字段，不能用文档库的最小模板
        ddl.create_graph_chunk_table(identifiers.chunk_table_for(table_name))
    graph_lifecycle.ensure_database(table_name)


def _find_name_conflict(name: str, org_id: Optional[str],
                        exclude_id: Optional[str]) -> Optional[dict]:
    rows = kbase_store.find_kbases_by_name(name, org_id, exclude_id)
    return rows[0] if rows else None


def _reuse_or_raise(existing: dict, name: str, category: int) -> dict:
    """同名库：**有文件就抛，没文件就复用**。

    ⚠️ 这是刻意行为：复用前校验 ``category`` 与 ``table_name`` 前缀，
    避免把文档库复用到图谱导入、或反过来 —— 否则一个 KB 会同时拥有
    ``doc_<id>_vector`` / ``graph_<id>`` 两套基名。
    """
    kbase_id = existing['kbase_id']
    existing_category = existing.get('category')
    if existing_category is not None and str(existing_category) != str(category):
        log.warning('refuse reuse: kbase %s category %s != requested %s',
                    kbase_id, existing_category, category)
        raise KbApiError('kbase.exist')
    table_name = str(existing.get('table_name') or '')
    expected_prefix = (TABLE_PREFIX_GRAPH if category == CATEGORY_KNOWLEDGE_GRAPH
                       else TABLE_PREFIX_DOCUMENT)
    if table_name and not table_name.startswith(expected_prefix + '_'):
        log.warning('refuse reuse: kbase %s table %s does not match category %s',
                    kbase_id, table_name, category)
        raise KbApiError('kbase.exist')
    if kbase_store.count_files(kbase_id) > 0:
        raise KbApiError('kbase.exist')
    log.info('v2 reusing empty kbase %s named %s', kbase_id, name)
    # 复用那条路走的是 ``kbaseDao.getKbase``（全量 VO），**不是** getKbaseDetail：
    # 没有 currentFileCount，也没有 props 覆写。
    return kbase_service._base_vo(existing)


def update_kbase(kbase_id: str, payload: dict, org_id: Optional[str],
                 emp_no: str = '') -> None:
    """``POST /kbase/{id}``：改名/改描述/改图标。返回 ``bo=null``。"""
    payload = binding.bind(payload, KBASE_REQ_FIELDS)
    # 改库走的是**同一套**请求体校验，
    # 所以 name / description / headIcon 的约束与建库一模一样。
    _validate_name(payload.get('name'))
    _validate_sizes(payload.get('description'), payload.get('headIcon'))

    try:
        with name_lock.acquire(org_id, payload.get('name')):
            # 与建库不同：**只要同名就抛**，不看那个库有没有文件
            # （checkKbaseNameExist 返回空库的 VO → 这里判非空 → 照样抛）
            if _find_name_conflict(payload.get('name'), org_id, exclude_id=kbase_id) is not None:
                raise KbApiError('kbase.exist')
            _update_row(kbase_id, payload, emp_no)
    except name_lock.NameLockAcquireException:
        raise KbApiError('kbase.name.lock.timeout')


def _update_row(kbase_id: str, payload: dict, emp_no: str) -> None:
    """``KbaseDao.updateKbase`` 的三条**条件**赋值（空值跳过，描述允许置空）。"""
    sets = []
    params: list = []
    name = payload.get('name')
    if name is not None and str(name).strip():
        sets.append('"name" = %s')
        params.append(name)
    if payload.get('description') is not None:
        sets.append('description = %s')
        params.append(payload['description'])
    if payload.get('headIcon') is not None:
        sets.append('head_icon = %s')
        params.append(payload['headIcon'])
    if not sets:
        return
    sets.extend(['updated_by = %s', 'updated_at = NOW()'])
    params.extend([emp_no, kbase_id])
    with kbase_store.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE kb_kbase SET {", ".join(sets)} WHERE kbase_id = %s', params)


def get_kbase_detail(kbase_id: str) -> dict:
    """``GET /kbase/{id}/graph``：``{schemaInfo, data, fileInfo}`` 复合体。

    两处容易看漏：

    * ``data`` 里的 ``schemaObj`` 被**置成空 map**（``Maps.newHashMap()``），
      真值挪到 ``schemaInfo``；
    * ``fileInfo`` 是 ``kbFileService.searchFileByKbId``（另一条查询，见下面注释）。
    """
    kbase_vo = kbase_service.get_kbase_detail(kbase_id)
    schema_obj = kbase_vo.pop('schemaObj', None)
    kbase_vo['schemaObj'] = {}
    # 空对象序列化成 ``{}``；这里用 dict() 保持同一形状
    return {
        'schemaInfo': schema_obj,
        'data': kbase_vo,
        'fileInfo': _search_file_by_kb_id(kbase_id),
        # 图谱全量实体/关系数（与查询条件无关）；文档库或尚未建图时为 None。
        'stats': _graph_stats(kbase_id),
    }


def _graph_stats(kbase_id: str) -> Optional[dict[str, int]]:
    """图谱库的真实实体/关系总数，供详情页「基本信息」概览使用。

    不能复用 ``graph/query`` 的 ``entity_num``/``edge_num``：那两个是**本次查询
    结果的长度**，会被类型筛选、关键词和 ``limit`` 截断。这里直接数
    ``graph_<id>_vertex`` / ``graph_<id>_edge`` 的物理行。
    """
    row = kbase_service.get_kbase_row(kbase_id)
    if row is None or str(row.get('category')) != str(CATEGORY_KNOWLEDGE_GRAPH):
        return None
    try:
        return graph_lifecycle.count_graph_entities_and_edges(kbase_id)
    except Exception:                                              # noqa: BLE001
        log.warning('graph stats unavailable for kbase %s', kbase_id, exc_info=True)
        return None


def _search_file_by_kb_id(kbase_id: str) -> list:
    """``KbFileServiceV2.searchFileByKbId``：库内**全部文件**（不含文件夹）。

    图谱库通常没有文件，返回空列表 —— 但走的是同一条查询，所以照实现。
    """
    try:
        rows = directory_store.get_all_files(kbase_id)
    except Exception:
        log.warning('searchFileByKbId failed for %s', kbase_id, exc_info=True)
        return []
    vos = [directory_service._base_vo(row) for row in rows]
    # ``KbFileServiceV2.searchFileByKbId`` 里只有 ``setFileSize`` 这一步后处理
    # （不像列表端点还要塞 props / kType / failReason）
    directory_service._set_file_size(vos, [row['id'] for row in rows])
    return vos


def delete_kbase(kbase_id: str, emp_no: str = '') -> None:
    """``POST /kbase/delete/{id}``：图谱库与文档库**分两条路**。"""
    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        # ⚠️ 这里**轮不到** ``checkIsExist``（那句用的是图谱抽取的 key）——
        # 这个端点也挂了业务级权限校验（``scope = INNER_KBASE_MANAGE``，
        # 同样没写 ``checkBusinessPermission=false``），所以找不到库时先被它拦下，
        # 分支规则与 ``GET /kbase/{id}`` 完全一样：纯数字 id → PermissionDenied，
        # 非数字 → 「知识库不存在」。两种 id 各踩一边。
        raise KbApiError('permission.denied' if kbase_service._looks_numeric(kbase_id)
                         else 'kbase.not.exist')

    pk_id = row.get('id')
    storage_registry_store.begin_delete(kbase_id)
    try:
        if str(row.get('category')) == str(CATEGORY_KNOWLEDGE_GRAPH):
            _delete_graph(row, pk_id, emp_no)
        else:
            _delete_document(row, pk_id, emp_no)
    except KbApiError:
        raise
    except Exception:
        log.exception('failed to delete kbase %s', kbase_id)
        raise KbApiError('kbase.delete.fail', kbase_id)
    storage_registry_store.remove(kbase_id)


def _delete_graph(row: dict, pk_id: int, emp_no: str) -> None:
    """``deleteGraph``：目录 → ES → 任务表 → 图存储 → 两张动态表 → 删除行。

    ⚠️ 删除必须放在**最后**：先删除再清理时，任何一步失败后 API 重试只会得到
    「知识库不存在」，孤儿表/孤儿图谱库再也清不掉。图存储删除失败时保留 registry、
    KB 保持 enabled，使删除变成可重试的幂等操作。
    """
    kbase_id = row['kbase_id']
    _check_bound_by_workflow(kbase_id, pk_id, emp_no)
    delete_directories_of_kbase(kbase_id)

    index_service.delete_index(kbase_id)

    graph_lifecycle.delete_import_and_extract_tasks(kbase_id)

    # 图存储先删；失败会抛出，registry 与 kb_kbase 都保留，可重试。
    graph_lifecycle.delete_graph_database(kbase_id)

    # ⚠️ 只 drop 这两张；``graph_<uuid>`` 主表**不删**（见模块注释）
    graph_lifecycle.drop_chunk_and_vector_tables(kbase_id)

    # 最后删除：前面任何一步失败时，库仍然可见、可再次调用删除。
    kbase_store.delete_kbase_row(kbase_id)


def _delete_document(row: dict, pk_id: int, emp_no: str) -> None:
    """``deleteDocument``：目录 → relation → 两张动态表 → ES → 删除行。"""
    kbase_id = row['kbase_id']
    _check_bound_by_workflow(kbase_id, pk_id, emp_no)
    table_name = row.get('table_name')
    delete_directories_of_kbase(kbase_id)

    # ⚠️ **不要**在这里按库清 relation：那会删掉需要保留的行，
    # 而 relation 是「文件→向量行」的桥，多删会让后续对不上。
    # 文件级的清理在 delete_directories_of_kbase → _purge_files 里已经做过。

    if table_name:
        from infrastructure.db import ddl

        ddl.drop_table(table_name)
        ddl.drop_table(identifiers.chunk_table_for(table_name))

    index_service.delete_index(kbase_id)
    kbase_store.delete_kbase_row(kbase_id)


# ----------------------------------------------------------------------
# 画布绑定前置检查（``deletePrecheck``）
# ----------------------------------------------------------------------


_workflow_binding_provider = None


def set_workflow_binding_provider(provider) -> None:
    """Install the workflow binding query (called by the HTTP assembly)."""
    global _workflow_binding_provider
    _workflow_binding_provider = provider


def _check_bound_by_workflow(kbase_id: str, pk_id: int, emp_no: str) -> None:
    """``deletePrecheck``：被知识检索引用了就不许删。

    **fail-open** —— 绑定查询本身坏掉时按「没绑定」放行
    （前置检查不该把删除整体拦死）。

    绑定关系来自本地画布（``flow_api`` 的 ``flow_*`` 三表）。这里直接用它的
    store 取数，**不**构造 ``FlowService`` —— 那个构造会按环境变量建能力快照、
    还可能起一个模型探测，为了读一次绑定不值得。
    """
    if _workflow_binding_provider is None:
        return
    try:
        hit = _workflow_binding_provider(kbase_id, pk_id, emp_no)
    except Exception as error:
        log.warning('workflow binding precheck unavailable, treating %s as unbound: %s',
                    kbase_id, error)
        return
    if hit:
        raise KbApiError('kbase.bound.by.workflow', ','.join(hit))




