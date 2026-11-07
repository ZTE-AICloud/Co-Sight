"""失败文档的手工重试。

把一条 ``status = 2``（解析失败）的文档重新入队，走与上传完全相同的
parse → split → embedding 链。

**处理配置从哪来**：上传时把 ``operatorParseDTO`` / ``operatorSplitDTO`` /
``regexList`` 存进 ``kb_directory_property.task_config``（见
``file_service._persist_task_config``），重试按原样还原。本次改动之前上传的旧行
没有这份配置，回落到「与上传界面同一口径」的系统算子默认参数
（``operators.service.operator_service.support``，优先 ``id = -1``）。

**为什么只允许 ``status = 2``**：其余状态要么正在跑（0 / -2 / -3 / -4），要么是
图谱库文件的落盘态（-1）。重试会把同一个文件二次入队，或启动一条不该跑的链。
认领用一条 ``UPDATE ... WHERE status = 2`` 完成 —— 连点两次只有第一次成功。

**失败产物**：处理链自己会在失败时回滚（``task/chain.py``），这里不再重复清理。
按文件名删 chunk 会误伤其它目录的同名文件；崩溃残留不在 ``status = 2`` 里，
本来也不可重试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from infrastructure.logging.logutil import log
from infrastructure.storage import kb_storage as storage
from knowledge_base.repository import directory as directory_store
from knowledge_base.repository import kbase as kbase_store
from knowledge_base.service.file_service import FILE_SIZE_PROP, TASK_CONFIG_PROP
from knowledge_base.task import runtime
from shared.errors.api import KbApiError

STATUS_FAILED = 2
STATUS_PENDING = 0
SPLIT_MODULE = 'text_split'
#: 与上传界面一致：优先默认切分算子（``-1``），没有时取该格式下的第一个。
DEFAULT_OPERATOR_ID = -1
RETRY_NOT_ALLOWED_KEY = 'file.retry.not.allowed'
RETRY_CONFLICT_PROBLEM = 'task_conflict'


def retry_file(kbase_id: str, file_id: str, emp_no: str,
               org_id: Optional[str] = None) -> dict:
    """重新解析一篇失败文档。返回 ``{fileId, taskId}``（接口转 202）。"""
    row = directory_store.get_directory(file_id, kbase_id, directory_store.TYPE_FILE)
    if row is None:
        raise KbApiError('file.not.exist', status=404,
                         problem_code='document_not_found')
    if _status_of(row) != STATUS_FAILED:
        raise _not_retryable()
    if not storage.core_file_exists(file_id):
        # 正文文件被清掉时重试必然失败，提前给出「文件不存在」而不是等算子报错。
        raise KbApiError('file.not.exist', status=404,
                         problem_code='document_not_found')

    handle = _build_handle(row, emp_no, org_id)
    previous_reason = row.get('fail_reason')
    if not _claim(file_id):
        # 查与改之间被别人重试/删除抢了先。
        raise _not_retryable()

    try:
        task_id = runtime.get_queue().submit_task(handle)
    except Exception:
        _restore_failed(file_id, previous_reason)
        raise

    log.info('document %s of kbase %s re-enqueued, task=%s', file_id, kbase_id, task_id)
    return {'fileId': file_id, 'taskId': task_id}


def _status_of(row: dict) -> int:
    try:
        return int(row.get('status') or 0)
    except (TypeError, ValueError):
        return 0


def _not_retryable() -> KbApiError:
    return KbApiError(RETRY_NOT_ALLOWED_KEY, status=409,
                      problem_code=RETRY_CONFLICT_PROBLEM)


def _claim(file_id: str) -> bool:
    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            return directory_store.claim_file_for_retry(
                cursor, file_id, STATUS_FAILED, STATUS_PENDING)


def _restore_failed(file_id: str, fail_reason: Optional[str]) -> None:
    """入队失败时把文件退回失败态，避免停在「待处理」永远等不到任务。"""
    try:
        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                directory_store.update_file_status(
                    cursor, file_id, STATUS_FAILED,
                    fail_reason or 'RetCode.operator.split.error')
    except Exception:
        log.warning('restore document %s to failed state failed', file_id, exc_info=True)


def _build_handle(row: dict, emp_no: str, org_id: Optional[str]) -> dict:
    """按上传时的形状重建任务 handle。"""
    kbase_id = row['kbase_id']
    file_id = row['id']
    file_name = row.get('title') or ''
    file_format = Path(file_name).suffix.lstrip('.').lower()
    config = _stored_config(file_id)

    handle = {
        'fileId': file_id,
        'kbaseId': kbase_id,
        # 与 ``_save_to_disk`` 的落点同源：core/<前4位>/<fileId>，materialize_ref 两种后端都认。
        'diskPath': storage.core_key(file_id),
        'format': file_format,
        'fileName': file_name,
        'fileSize': _file_size(file_id),
        'modelName': _embedding_model(kbase_id),
        'regexList': config.get('regexList'),
    }
    if config.get('operatorParseDTO'):
        handle['operatorParseDTO'] = config['operatorParseDTO']

    split_dto = config.get('operatorSplitDTO')
    if not split_dto:
        split_dto = _default_split_operator(file_format, emp_no, org_id)
    if not split_dto:
        raise KbApiError('RetCode.operator.notfound')
    handle['operatorSplitDTO'] = split_dto
    return handle


def _stored_config(file_id: str) -> dict:
    props = directory_store.get_all_properties([file_id]).get(file_id) or {}
    raw = props.get(TASK_CONFIG_PROP)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        log.warning('invalid task config for document %s, using defaults', file_id)
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_split_operator(file_format: str, emp_no: str,
                            org_id: Optional[str]) -> Optional[dict]:
    """回落到系统算子默认参数（与上传界面同一口径）。

    旧行没有 ``task_config`` 时走这里。取不到算子就返回 None —— 调用方报错，
    而不是入队一个必然炸（``operator_id < 0`` 时缺 ``maxWordCount``/``overlap``）
    的任务。
    """
    if not file_format:
        return None
    # 延迟 import：operators 域只在重试回落这条路上用到，别拖进模块加载期。
    from operators.service import operator_service

    supported = operator_service.support(
        {'module': SPLIT_MODULE, 'formats': [file_format]}, emp_no, org_id) or {}
    candidates = [item for item in supported.get(file_format) or []
                  if isinstance(item, dict)]
    operator = next((item for item in candidates
                     if item.get('id') == DEFAULT_OPERATOR_ID),
                    candidates[0] if candidates else None)
    if operator is None:
        return None
    return {'operatorId': operator.get('id'), 'args': list(operator.get('args') or [])}


def _file_size(file_id: str) -> int:
    raw = directory_store.get_properties([file_id], FILE_SIZE_PROP).get(file_id)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _embedding_model(kbase_id: str) -> Optional[str]:
    row = kbase_store.select_kbase_by_id(kbase_id) or {}
    return row.get('embedding_model')
