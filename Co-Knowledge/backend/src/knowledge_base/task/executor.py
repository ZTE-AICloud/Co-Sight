"""文件导入任务的 runner 与重试策略。

执行已经交给 ``infrastructure.tasks`` 的统一引擎；本模块只保留三件事：

* ``process_file``：parse → split → embedding 链（原有语义不变）；
* ``retry_delay``：大文件闸门被占用时延迟 5 秒再重投，其它错误立即重投；
* ``run_file_task``：引擎 runner，成功后把知识库标成「已修改」。

**重试不再在 worker 里 sleep**：引擎的调度线程负责延迟重投，避免一条 5 秒的等待
占住一个 worker（批量导入时会把整条车道拖住）。
"""

from __future__ import annotations

from shared.errors.api import KbApiError
from infrastructure.storage import kb_storage as storage
from knowledge_base.repository import kbase as kbase_store
from knowledge_base.task.chain import FileHandlerChain
from knowledge_base.task.handlers import (
    FileEmbeddingHandler,
    FileParseHandler,
    FileSplitHandler,
)

#: 文件导入车道的 worker 数
WORKER_THREAD_COUNT = 5

#: 大文件闸门被占用时的重试间隔（秒）。
#:
#: 普通失败仍然无延迟重投；``RetCode.file.size.more`` 值得等一等 ——
#: 无延迟重投会在几毫秒内烧光 3 次重试预算。
BUSY_RETRY_DELAY_SECONDS = 5


def _is_large_file_busy(error: BaseException) -> bool:
    """``operator_runtime._invoke`` 把忙等错误包成 ``KbApiError(key=...)``。

    key 必须是 ``RetCode.file.size.more`` —— 映射表未登记时它会落到
    ``RetCode.operator.split.error`` 兜底键，与真实切分错误无法区分。
    """
    return isinstance(error, KbApiError) and error.key == 'RetCode.file.size.more'


def retry_delay(error: BaseException) -> float:
    """引擎的 ``TaskKind.retry_delay``：只有大文件闸门忙时才等。"""
    return BUSY_RETRY_DELAY_SECONDS if _is_large_file_busy(error) else 0.0


def process_file(file_handle: dict) -> None:
    """跑处理链，成功后把状态推到「全链成功」。

    ⚠️ 链抛异常时 ``updateFileStatus(..., 1)`` **不会执行**（异常直接上抛给
    引擎去重试/判失败）—— 顺序不能反。
    """
    if not file_handle:
        return
    chain = FileHandlerChain()
    chain.add_handler(FileParseHandler())
    chain.add_handler(FileSplitHandler())
    chain.add_handler(FileEmbeddingHandler())
    try:
        chain.execute(file_handle)

        from knowledge_base.repository import directory as directory_store

        with directory_store.connection() as conn:
            with conn.cursor() as cursor:
                directory_store.update_file_status(cursor, file_handle['fileId'], 1, None)
    finally:
        # MinIO 后端在解析/切片前会把对象物化成临时文件，无论成功失败都要清掉。
        storage.cleanup_task_files(file_handle)


def run_file_task(record, ctx) -> None:
    """统一引擎的 runner：执行文件链 + 成功后的库状态副作用。

    内存模式从 ``payload['task']`` 取 FileTask；DB 模式从
    ``payload['fileHandle']`` 重建（进程重启后仍然可恢复）。
    """
    task = record.payload.get('task')
    handle = task.file_handle if task is not None else record.payload.get('fileHandle')
    if not handle:
        raise RuntimeError('file task has no handle')
    process_file(handle)
    # 成功路径才标「已修改」—— 失败不该动知识库状态
    kbase_store.set_kbase_status_modified(handle.get('kbaseId'))
