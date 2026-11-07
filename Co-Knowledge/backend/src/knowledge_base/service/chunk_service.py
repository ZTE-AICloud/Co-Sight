"""``/chunk`` 那一族（切片的新增/修改/删除/列表/按文件搜/溯源）。

## 三条必须先搞懂的语义（写错了都是静默错数据）

1. **``chunkId`` 是 ``kb_node_relation`` 的主键**，不是向量表的 id，也不是
   chunk 表的 id。所以增删改查全是「先按 relation.id + kbaseId 找到 nodeId，
   再去动向量表」。
2. **``content_expand`` 存的是 chunkId、真实内容在 chunk 表的 ``text``**。
   读的时候要取 chunk 正文，否则 ``supplement`` 会返回一串 uuid。
3. **``metadata_`` 是平铺格式**：改切片只需重写 ``metadata/content_expand`` 一处
   （见 ``shared/chunk_schema/node_format.py``）。

## 校验：只有「文件不存在」这一类

``addChunk`` / ``searchChunkFromFile`` 会校验 ``fileId`` 属于该库，不存在就回
0005。**改/删都不校验**，``chunkId`` 查不到就是 0001。
"""

from __future__ import annotations

import uuid
from typing import Optional

from infrastructure.http.pagination import page as paginate
from shared.errors.api import KbApiError, KbLiteralError
from knowledge_base.repository import chunk as chunk_store, directory as directory_store, kbase as kbase_store, node_relation as node_relation_store
from retrieval.service import write as vector_store_write
from infrastructure.logging.logutil import log
from shared.prefixes import RKB_PREFIX

# ``ZaeConstant``
CONTENT_EXPAND = 'content_expand'

# ``FullTextClient`` 的两个字段名
NODE_ID_FIELD = 'node_id'

# 溯源接口返回的下载地址前缀（``KbFileController.BASE_URL`` + ``DOC_DOWNLOAD_FILE``）。
#
# ⚠️ 这是**响应体里的字段值**（`downloadUrl`），浏览器拿它直接发请求，所以它必须与
# nginx 实际反代的前缀一致 —— 留旧值就是「溯源列表出来了、点下载拿到一页 index.html」。
DOWNLOAD_URL = RKB_PREFIX + '/knowledge-bases'


def _kbase_or_raise(kbase_id: str) -> dict:
    """查不到 → 404 ``knowledge_base_not_found``。"""
    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise KbApiError('kbase.not.exist')
    return row


def _relation_or_raise(chunk_id: int, kbase_id: str) -> dict:
    """``selectByIdAndKbaseIdExist``：查不到**自己抛**「数据集不存在」（0005）。

    别照名字以为它返回 null —— 同一个 DAO 里还有个不带 ``Exist`` 的 ``selectByIdAndKbaseId``
    才是返回 null 的那个；改/删切片用的都是这个会抛的。
    """
    relation = chunk_store.select_relation_by_id(chunk_id, kbase_id)
    if relation is None:
        raise KbApiError('RetCode.dataSet.not.exist')
    return relation


def _file_or_raise(kbase_id: str, file_id: str) -> dict:
    """``kbFileDao.querySingleFile`` + 那句 0005。

    ``querySingleFile`` 带 ``type = 'file'`` 条件，传文件夹 id 会被判成「文件不存在」。
    """
    row = directory_store.get_directory(file_id, kbase_id, directory_store.TYPE_FILE)
    if row is None:
        log.error('File not found. kbase: %s, file: %s', kbase_id, file_id)
        raise KbApiError('RetCode.file.not.exist')
    return row


def _embedding(text: str, model: Optional[str]) -> list[float]:
    """``EmbeddingExecuteService.doEmbedding(List.of(text), model)`` 取第 0 条。

    ⚠️ 失败时抛的是 **0005 + 字面量 ``RetCode.embedding.fail``** —— key 字符串直接
    当消息，没走 i18n，不是「内容向量化失败！」那句译文。别「顺手」翻成中文。
    """
    from model import gateway as model_gateway

    try:
        return model_gateway.embed(text, model)
    except Exception as error:                                     # noqa: BLE001
        log.error('embedding failed: %s', error)
        raise KbLiteralError('RetCode.embedding.fail') from error


# ----------------------------------------------------------------------
# 新增
# ----------------------------------------------------------------------


def add_chunk(kbase_id: str, file_id: str, payload: dict) -> dict:
    """``POST /chunk/add``：建向量行 + 建 chunk 行 + 建关系行 + 写 ES。"""
    kbase = _kbase_or_raise(kbase_id)
    file_row = _file_or_raise(kbase_id, file_id)

    node_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    content = payload.get('content')
    supplement = payload.get('supplement')
    floats = _embedding(content, kbase.get('embedding_model'))

    metadata = _build_chunk_metadata(chunk_id, file_row.get('title'))
    # 正文只留 chunk.text。
    chunk_store.insert_index(kbase, [{'text': None,
                                      'metadata': metadata,
                                      'node_id': node_id, 'embedding': floats}])

    try:
        # supplement 缺省时回落 content：否则 chunk.text 为 NULL，正文会凭空丢失。
        chunk_store.insert_chunk(kbase, chunk_id, kbase_id,
                                 file_row.get('title'),
                                 supplement if supplement is not None else content)
    except Exception:                                              # noqa: BLE001
        # 写入失败必须补偿删除刚写的向量行并失败：吞掉会让 content_expand 指向
        # 不存在的 chunk 行，supplement 回落成一串 uuid。
        log.exception('failed to create chunk row for chunkId %s', chunk_id)
        try:
            chunk_store.delete_by_node_ids(kbase, [node_id])
        except Exception:                                          # noqa: BLE001
            log.exception('failed to rollback vector row for node %s', node_id)
        raise

    node_relation_store.batch_insert_relations(kbase_id, file_id, [node_id])

    vector_store_write.save_es_documents(kbase_id, file_id, [
        {'node_id': node_id, 'text': content, 'metadata': dict(metadata)},
    ])
    return {'chunkId': chunk_id}


def _build_chunk_metadata(content_expand_value, file_title: str) -> dict:
    """``buildChunkMetadata``：平铺的 chunk metadata。

    ``content_expand`` 指向 chunk 表主键；``text``/``node_id`` 是表列，由
    ``chunk_store.insert_index`` 落列，不进 metadata。
    """
    return {
        CONTENT_EXPAND: content_expand_value,
        'source': file_title,
        'type': 1,
    }


# ----------------------------------------------------------------------
# 修改
# ----------------------------------------------------------------------


def update_chunk(chunk_id: int, kbase_id: str, payload: dict) -> None:
    """``POST /chunk/{chunkId}``：改内容 → 重算向量 → 写回 chunk / 向量 / ES。"""
    relation = _relation_or_raise(chunk_id, kbase_id)

    kbase = _kbase_or_raise(kbase_id)
    index_row = chunk_store.query_by_node_id(kbase, relation['node_id'])
    metadata = dict((index_row or {}).get('metadata') or {})

    vector_chunk_id = (metadata.get(CONTENT_EXPAND)
                       if metadata.get(CONTENT_EXPAND) is not None else None)
    vector_chunk_id = str(vector_chunk_id) if vector_chunk_id is not None else None

    content = payload.get('content')
    supplement = payload.get('supplement')
    floats = _embedding(content, kbase.get('embedding_model'))

    if vector_chunk_id is not None:
        try:
            chunk_store.update_chunk_text(kbase, vector_chunk_id,
                                          supplement if supplement is not None else content,
                                          {})
        except Exception:                                          # noqa: BLE001
            # 更新失败必须直接失败：吞掉会让 chunk 表正文停留在旧值，而向量/ES
            # 已更新，三份副本静默分叉。
            log.exception('failed to update chunk row %s', vector_chunk_id)
            raise

    metadata = dict(metadata or {})
    # 正文只留 chunk.text（上面已写入）。
    chunk_store.update_index(kbase, index_row['id'], None, metadata, floats)

    vector_store_write.update_es_document_by_node_id(
        kbase_id, relation['node_id'], content, dict(metadata))


# ----------------------------------------------------------------------
# 删除
# ----------------------------------------------------------------------


def delete_chunk(chunk_id: int, kbase_id: str) -> None:
    """``POST /chunk/delete/{chunkId}``：删 ES + 向量行 + chunk 行 + 关系行。

    ⚠️ 删除顺序是硬约束：

    * **先删 ES**（按 node_id 幂等）：ES 失败时 PG 一行未动，可直接重试；
      反过来先删 PG 向量/relation，ES 失败后 relation 已没了，重试会直接 0005，
      ES 文档永久残留。
    * chunk 表行也要一起删，避免「点了删除、正文还在库里」。
    * ``relation`` 必须**最后**删：它是 chunkId 的唯一寻址锚点，早删会让任何
      前序失败都无法重试。
    """
    relation = _relation_or_raise(chunk_id, kbase_id)
    kbase = _kbase_or_raise(kbase_id)
    node_ids = [relation['node_id']]

    index_row = chunk_store.query_by_node_id(kbase, relation['node_id'])
    metadata = (index_row or {}).get('metadata') or {}
    vector_chunk_id = metadata.get(CONTENT_EXPAND)

    # 1. ES 先删（幂等）。失败则 PG 一行未动，可直接重试。
    vector_store_write.delete_es_documents_by_query(kbase_id, NODE_ID_FIELD, node_ids)

    # 2. chunk 行
    if vector_chunk_id is not None:
        chunk_store.delete_chunk_by_id(kbase, str(vector_chunk_id))

    # 3. 向量行
    chunk_store.delete_by_node_ids(kbase, node_ids)

    # 4. relation 最后删
    chunk_store.delete_relation(chunk_id)


# ----------------------------------------------------------------------
# 列表 / 按文件搜
# ----------------------------------------------------------------------


def get_chunk_list(kbase_id: str, file_id: Optional[str], keyword: Optional[str],
                   current_page: int, page_size: int) -> dict:
    """``GET /chunk``：**忽略 ``fileId``**（参数存在但不参与查询）。

    按 id 倒序分页；``supplement`` 取 chunk 表正文；``source`` 取关系行指向的文件名。
    """
    kbase = _kbase_or_raise(kbase_id)
    records, total = chunk_store.query_page_by_keyword(kbase, keyword,
                                                       current_page, page_size)
    if not records:
        return paginate([], 0, current_page, page_size)

    chunk_map: dict[str, dict] = {}
    chunk_ids = [value for value in
                 (_chunk_id_of(record) for record in records) if value]
    if chunk_ids:
        try:
            chunk_map = {row['id']: row
                         for row in chunk_store.query_by_chunk_ids(kbase,
                                                                  list(set(chunk_ids)))}
        except Exception:                                          # noqa: BLE001
            log.warning('failed to query chunk table for kbaseId: %s', kbase_id,
                        exc_info=True)

    relations = chunk_store.select_relations_by_node_ids(
        [record['node_id'] for record in records], kbase_id)
    node_rel_map = {}
    for relation in relations:
        node_rel_map.setdefault(relation['node_id'], relation)
    directory_ids = list({relation['directory_id'] for relation in relations})
    titles = {row['id']: row.get('title')
              for row in directory_store.get_files_by_ids(directory_ids)}

    result = []
    for record in records:
        relation = node_rel_map.get(record['node_id'], {})
        result.append(_dataset_vo(
            chunk_id=relation.get('id'),
            kbase_id=kbase_id,
            file_id=relation.get('directory_id'),
            content=record.get('text'),
            supplement=_supplement_of(record.get('metadata'),
                                      chunk_map.get(_chunk_id_of(record) or '')),
            source=titles.get(relation.get('directory_id')),
        ))
    return paginate(result, total, current_page, page_size)


def _chunk_id_of(record: Optional[dict]) -> Optional[str]:
    """``extractChunkIdFromMetadata``：``metadata_.content_expand`` 转字符串。"""
    metadata = (record or {}).get('metadata') or {}
    if CONTENT_EXPAND in metadata and metadata[CONTENT_EXPAND] is not None:
        return str(metadata[CONTENT_EXPAND])
    return None


def _supplement_of(metadata: Optional[dict], chunk_row: Optional[dict]) -> str:
    """``supplement``：chunk 行有正文时用 ``chunk.text``，否则回落 ``content_expand``。"""
    if not metadata:
        return ''
    if CONTENT_EXPAND not in metadata or metadata[CONTENT_EXPAND] is None:
        return ''
    content_expand = str(metadata[CONTENT_EXPAND])
    if chunk_row is not None:
        text = chunk_row.get('text')
        if text and str(text).strip() and content_expand == _chunk_id_of({'metadata': metadata}):
            return text
    return content_expand


def search_chunk_from_file(kbase_id: str, file_id: str, keyword: Optional[str],
                           current_page: int, page_size: int,
                           chunk_id_asc: bool = False) -> dict:
    """``GET /chunk/file/{fileId}``：按文件搜切片，带 ``nameChain``（父目录名 + 文件名）。

    ``chunk_id_asc``：文档预览要按原文顺序拼正文，传 ``True`` 取升序；
    切片管理页保持默认倒序。
    """
    kbase = _kbase_or_raise(kbase_id)
    file_row = _file_or_raise(kbase_id, file_id)

    total = chunk_store.count_by_file(kbase, file_id, keyword)
    data: list[dict] = []
    if total > 0:
        joined = chunk_store.list_by_file(kbase, file_id, keyword,
                                          current_page, page_size, chunk_id_asc)
        chunk_map: dict[str, dict] = {}
        chunk_ids = list({value for value in
                          (_chunk_id_of({'metadata': item.get('metadata')})
                           for item in joined) if value})
        if chunk_ids:
            try:
                chunk_map = {row['id']: row
                             for row in chunk_store.query_by_chunk_ids(kbase,
                                                                      chunk_ids)}
            except Exception:                                      # noqa: BLE001
                log.warning('failed to query chunk table for kbaseId: %s', kbase_id,
                            exc_info=True)
        for item in joined:
            data.append(_dataset_vo(
                chunk_id=item.get('chunk_id'),
                kbase_id=kbase_id,
                file_id=item.get('directory_id'),
                content=item.get('text'),
                supplement=_supplement_of(item.get('metadata'),
                                          chunk_map.get(_chunk_id_of(
                                              {'metadata': item.get('metadata')}) or '')),
                source=file_row.get('title'),
            ))

    id_list = [file_row.get('parent_id'), file_row.get('id')]
    name_map = {row['id']: (row.get('title') or '')
                for row in directory_store.get_files_by_ids(
                    [item for item in id_list if item], kbase_id)}
    return paginate(
        data, total, current_page, page_size,
        nameChain=[name_map.get(item, '') for item in id_list])


def _dataset_vo(chunk_id, kbase_id: str, file_id, content, supplement,
                source) -> dict:
    """``DataSetVO`` 的字段**全集与顺序**（前端按字段存在解析）。

    ⚠️ 一共 **13** 个键 —— ``score`` 后面还有 ``rankScore`` 与 ``fullScore``
    （打分链路上才赋值，这条链恒为 null）。漏掉它们会让「字段存在性」判断的前端
    少两个键。
    """
    return {
        'chunkId': chunk_id,
        'kbaseId': kbase_id,
        'fileId': file_id,
        'content': content,
        'supplement': supplement,
        'createdBy': None,
        'createdDate': None,
        'lastUpdatedBy': None,
        'lastUpdatedDate': None,
        'source': source,
        'score': None,
        'rankScore': None,
        'fullScore': None,
    }


# ----------------------------------------------------------------------
# 溯源
# ----------------------------------------------------------------------


def trace_source_file(node_ids: list[str], org_id: Optional[str] = None) -> dict:
    """``POST /chunk/trace-source-file``：把 nodeId 分类成 可溯源/无权/不可溯源。

    ⚠️ 「无权」这一层靠 ``kbaseService.getKbaseList()`` 比对。那个方法内部
    ``getKbaseList(null)``（empNo 传的是 **null**）→ ``isNotEmpty(null)`` 为假 →
    **不会**按 ``created_by`` 过滤，实际就是「该 org 下的全部有效库」。
    别照名字以为它在做用户过滤；不加鉴权的约束下，语义正好一致。
    """
    relations = chunk_store.select_relations_by_node_ids(node_ids)
    existed = {relation['node_id'] for relation in relations}
    untraceable = [node_id for node_id in node_ids if node_id not in existed]

    available_kbase_ids = {row.get('kbase_id')
                           for row in kbase_store.select_all_kbases(org_id)}
    available, no_permission = [], []
    for relation in relations:
        if relation['kbase_id'] in available_kbase_ids:
            available.append(relation)
        else:
            no_permission.append(relation['node_id'])

    directory_ids = list({relation['directory_id'] for relation in available})
    directories = directory_store.get_files_by_ids(directory_ids)

    node_ids_by_dir: dict[str, list[str]] = {}
    for relation in available:
        node_ids_by_dir.setdefault(relation['directory_id'], []).append(relation['node_id'])

    result = []
    for directory in directories:
        node_id_list = node_ids_by_dir.get(directory['id'], [])
        if not node_id_list:
            continue
        result.append({
            'id': directory['id'],
            'kbaseId': directory.get('kbase_id'),
            'downloadUrl': (f'{DOWNLOAD_URL}/{directory.get("kbase_id")}'
                            f'/documents/{directory["id"]}/content'),
            'nodeId': node_id_list,
        })
    return {'noPermission': no_permission, 'untraceable': untraceable, 'result': result}
