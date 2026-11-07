"""导入链的三个 handler：解析 → 切分 → 向量化。

链的语义（见 :mod:`knowledge_base.task.chain`）：正序执行，任一步失败**从它自己开始**
倒序回滚；每个 handler 成功时把 ``kb_directory.status`` 推进一步，失败时置 2 并写 fail_reason。

状态取值：``-2`` 解析完成 / ``-3`` 切分完成 /
``-4`` 向量化完成 / ``1`` 全链成功（由调用方在链跑完后写）/ ``2`` 失败。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.db import identifiers
from infrastructure.storage import kb_storage as storage
from knowledge_base.task import operator_runtime
from model import gateway as model_gateway
from knowledge_base.repository import chunk as chunk_store, directory as directory_store, node_relation as node_relation_store
from retrieval.service import write as write_service
from infrastructure.logging.logutil import log

STATUS_PARSE_DONE = -2
STATUS_SPLIT_DONE = -3
STATUS_EMBEDDING_DONE = -4
STATUS_FAILURE = 2

# 向量化批大小
EMBEDDING_BATCH_SIZE = 500

# 注入的默认参数（含 emp_no="test"）
DEFAULT_SPLIT_ARGS = (
    {'argName': 'emp_no', 'argType': 'str', 'defaultValue': 'test'},
)


def _update_status(file_id: str, status: int, fail_reason: Optional[str] = None) -> None:
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.update_file_status(cursor, file_id, status, fail_reason)


def _operator_python_path(operator_id) -> Optional[str]:
    """算子的脚本路径（实现在 store 里，预览链也用同一个）。"""
    return directory_store.operator_python_path(operator_id)


def _format_suffix(file_format) -> str:
    """物化临时文件的后缀。只影响文件名，解析/切片都会按 ``file_name`` 重命名。"""
    text = str(file_format or '').strip()
    return f'.{text}' if text else ''


class FileParseHandler:
    """清洗：``operatorParseDTO`` 为空时**直通**（不调文档处理模块，也不改状态）。

    ``diskPath`` 可能是本地绝对路径（local 后端），也可能是对象键（MinIO 后端）。
    后者先物化成 scratch 临时文件，再交给清洗算子 —— 算子只认真实文件路径。
    物化文件记录在 ``_materialized_files`` 上，任务链结束时统一清理。
    """

    def handle(self, file_handle: dict) -> None:
        parse_dto = file_handle.get('operatorParseDTO')
        try:
            disk_path, is_temp = storage.materialize_ref(
                file_handle.get('diskPath'), suffix=_format_suffix(file_handle.get('format')))
            if is_temp:
                file_handle.setdefault('_materialized_files', []).append(str(disk_path))

            if parse_dto is None:
                file_handle['cleanPath'] = str(disk_path)
                return

            request = dict(parse_dto)
            request['pythonPath'] = _operator_python_path(parse_dto.get('operatorId'))
            request['fileFormat'] = file_handle.get('format')
            request['regexList'] = file_handle.get('regexList')
            request['diskFileKey'] = str(disk_path)

            cleaned_path = operator_runtime.file_parse(
                request.get('operatorId'), request.get('args'), request.get('pythonPath'),
                request.get('fileFormat'), request.get('regexList'), request.get('diskFileKey'))
            file_handle['cleanPath'] = cleaned_path
            file_handle['format'] = 'md'
            _update_status(file_handle['fileId'], STATUS_PARSE_DONE)
        except Exception as error:
            _update_status(file_handle['fileId'], STATUS_FAILURE, _fail_reason(error))
            raise

    def rollback(self, file_handle: dict) -> None:
        """空实现。"""
        return None


def _normalized_operator_id(value):
    """把 ``operatorSplitDTO.operatorId`` 归一成整数或 null。

    空串/全空白串 → null、数字串 ``"3"`` → 3、``1.5`` → 1（截断）。metadata 是裸
    ``json.loads``，没有这层，字符串会原样走到本 handler；这里先归一，
    handler 只面对 int/null。

    ⚠️ 为什么必须有这一步（F3 的真身）：前端 ``fileOperatorDefaultData()`` 的默认值
    是 ``''``（``frontend/src/views/kBase/useSplitInfo.ts``），它进了后台任务后撞上
    ``'' > 0`` 就是 ``TypeError: '>' not supported between instances of 'str' and 'int'``
    —— 任务重试 3 次后 FAILED、文件 status=2。这类输入在**上传期**会被必填校验拦掉
    （上传链见 ``file_service.validate_operator_args``）；这里按同一规则归一，
    保证 handler 只面对 int/null。

    为什么不直接用 ``binding.as_integer``：它把 ``''`` 当非数字串抛错，而这里对
    **空串**的语义是折成 null，所以先在这里折掉。
    非数字串/布尔/对象仍让它抛 ``ValueError`` —— 与任何 handler 异常同路
    （status=2 + rethrow；这类输入在上传期绑定失败时回 0001）。
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    from infrastructure.http import binding

    return binding.as_integer('operatorSplitDTO.operatorId', value)


class FileSplitHandler:
    """切分：``operatorId > 0`` 取库里的 pythonPath；``< 0`` 注入默认参数。"""

    def handle(self, file_handle: dict) -> None:
        split_dto = file_handle.get('operatorSplitDTO')
        try:
            clean_path, is_temp = storage.materialize_ref(
                file_handle.get('cleanPath'), suffix=_format_suffix(file_handle.get('format')))
            if is_temp:
                file_handle.setdefault('_materialized_files', []).append(str(clean_path))

            request = dict(split_dto or {})
            # ``None``（V2 建图那条链的默认态）与 ``''`` 走同一支：注入默认参数。
            # ``< 0`` 与 ``> 0`` 是两个独立分支，0 两边都不进 —— 这一处保持
            # 现状（等 0 的语义真被用到再处理），本次只做类型归一。
            operator_id = _normalized_operator_id(request.get('operatorId'))
            if operator_id is not None and operator_id > 0:
                request['pythonPath'] = _operator_python_path(operator_id)
            else:
                request['args'] = _with_default_split_args(
                    request.get('args'), file_handle.get('kbaseId'))

            split_result = operator_runtime.text_split(
                operator_id, request.get('args'), request.get('pythonPath'),
                file_handle.get('format'), str(clean_path),
                file_handle.get('fileName'), file_handle.get('fileSize'),
                file_handle.get('kbaseId'))
            file_handle['splitResult'] = split_result
            _update_status(file_handle['fileId'], STATUS_SPLIT_DONE)
        except Exception as error:
            _update_status(file_handle['fileId'], STATUS_FAILURE, _fail_reason(error))
            raise

    def rollback(self, file_handle: dict) -> None:
        """空实现。"""
        return None


def _with_default_split_args(args, kbase_id) -> list:
    """args 为空则建空表，再**追加**注入的两个默认参数。

    ``emp_no`` 固定为 ``'test'``（实际行为就是注入它）。
    """
    merged = list(args or [])
    merged.extend(dict(arg) for arg in DEFAULT_SPLIT_ARGS)
    merged.append({'argName': 'kbase_id', 'argType': 'str', 'defaultValue': kbase_id})
    return merged


class FileEmbeddingHandler:
    """向量化 + 三写（chunk 表 / 向量表 / ES）。"""

    def handle(self, file_handle: dict) -> None:
        split_result = file_handle.get('splitResult')
        if split_result is None:
            return

        file_id = file_handle['fileId']
        kbase_id = file_handle['kbaseId']
        try:
            kbase_row = _kbase_row(kbase_id)
            pk_id = kbase_row['id']
            table_name = kbase_row.get('table_name')
            chunk_table = identifiers.chunk_table_for(table_name)

            write_service.save_chunks(chunk_table, split_result.get('chunks'))

            results = list(split_result.get('results') or [])
            for start in range(0, len(results), EMBEDDING_BATCH_SIZE):
                batch = results[start:start + EMBEDDING_BATCH_SIZE]
                texts = [node.get('text') for node in batch]
                vectors = _embed(texts, file_handle.get('modelName'))
                for node, vector in zip(batch, vectors):
                    node['embedding'] = vector
                _persist_index_nodes(kbase_id, file_id, pk_id, table_name, batch,
                                     split_result.get('chunks'))

            _update_status(file_id, STATUS_EMBEDDING_DONE)
        except Exception as error:
            _update_status(file_id, STATUS_FAILURE, _fail_reason(error))
            raise

    def rollback(self, file_handle: dict) -> None:
        """``FileEmbeddingHandler.rollback``：删 relation / chunk 行 / ES 文档。"""
        file_id = file_handle['fileId']
        kbase_id = file_handle['kbaseId']
        try:
            node_relation_store.delete_by_directory_ids(
                _kbase_row(kbase_id)['id'], [file_id])
        except Exception:
            log.warning('rollback relation failed for %s', file_id, exc_info=True)
        try:
            # 失败重试会重新切分并生成新的 chunk uuid；不删旧行会按重试次数累积孤儿。
            split_result = file_handle.get('splitResult') or {}
            chunk_ids = [chunk.get('id') for chunk in split_result.get('chunks') or []
                         if chunk.get('id')]
            if chunk_ids:
                kbase = _kbase_row(kbase_id)
                for chunk_id in chunk_ids:
                    chunk_store.delete_chunk_by_id(kbase, str(chunk_id))
        except Exception:
            log.warning('rollback chunk rows failed for %s', file_id, exc_info=True)
        try:
            write_service.delete_es_documents_by_query(kbase_id, 'file_id', [file_id])
        except Exception:
            log.warning('rollback es documents failed for %s', file_id, exc_info=True)


def _persist_index_nodes(kbase_id: str, file_id: str, pk_id: int, table_name: str,
                         nodes: list[dict], chunks) -> None:
    """保存索引：relation 批量插 + 向量表批量插 + ES bulk。"""
    chunk_map = {chunk.get('id'): chunk for chunk in (chunks or [])}

    rows = []
    doc_nodes = []
    node_ids = []
    for node in nodes:
        node_id = node.get('nodeId')
        chunk_id = node.get('chunk_id')
        metadata = write_service.build_metadata(node.get('metadata') or {}, chunk_id)
        chunk = chunk_map.get(chunk_id) or {}
        metadata.setdefault('source', chunk.get('source'))
        # 只写平铺格式，不要补嵌套副本（``_node_content`` / ``_node_type`` /
        # doc-id 别名）—— 那份副本与外层按字段重复，见
        # ``shared/chunk_schema/node_format.py`` 的模块注释。

        rows.append({'node_id': node_id, 'text': node.get('text'), 'metadata': metadata,
                     'embedding': node.get('embedding')})
        doc_nodes.append({'node_id': node_id, 'text': node.get('text'), 'metadata': metadata})
        node_ids.append(node_id)

    node_relation_store.batch_insert_relations(kbase_id, file_id, node_ids)
    # 正文只留 chunk.text；向量表的 text 列不写普通行。
    write_service.save_vectors(table_name, rows)
    write_service.save_es_documents(kbase_id, file_id, doc_nodes)


def _embed(texts: list[str], model_name: Optional[str]) -> list[list[float]]:
    """批量向量化：**一次请求发整批**。

    ⚠️ 别改回逐条循环：一个文件会变成几十上百次 HTTP，上游每次抖动都被放大成
    一次「整条文件链回滚」（``FileEmbeddingHandler`` 失败即 rollback）。
    维度不符**显式抛错**，不截断。
    """
    return model_gateway.embed_many(list(texts), model_name)


def _kbase_row(kbase_id: str) -> dict:
    from knowledge_base.repository import kbase as kbase_store

    row = kbase_store.select_kbase_by_id(kbase_id)
    if row is None:
        raise LookupError('kbase not found: %s' % kbase_id)
    return row


def _table_exists(table_name: str) -> bool:
    from infrastructure.db import ddl

    return ddl.table_exists(table_name)


def _fail_reason(error: Exception) -> str:
    """失败原因写入 ``kb_directory.fail_reason``。

    业务错误用它的文案键（前端会去 i18n 表里查），其余用同一个兜底键。
    """
    from shared.errors.api import KbApiError

    if isinstance(error, KbApiError):
        return error.key
    return 'RetCode.database.updateOrInsertException'

