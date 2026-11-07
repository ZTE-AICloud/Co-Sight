"""worker 线程池。

* 起 ``workerThreadCount``（默认 5）个**非 daemon** 线程
* 每个线程 ``pollTask(5s)`` 阻塞等任务 → ``executeTask``
* 成功：``setKbaseStatusModified`` + 标记 COMPLETED（**这一句只在成功路径**）
* 失败：还有重试预算 → ``markAsRetry``（retryCount++）；否则标记 FAILED。
  重投默认**无延迟**，只有「大文件闸门被占用」这类需要等赢家跑完的错误才先等
  ``BUSY_RETRY_DELAY_SECONDS``（见 :func:`_retry_task`）。

重试条件是 ``retry_count < max_retry_count``，所以最多执行 **1 + 3** 次。
"""

from __future__ import annotations

import threading
import time

from shared.errors.api import KbApiError
from infrastructure.storage import kb_storage as storage
from knowledge_base.repository import kbase as kbase_store
from knowledge_base.task.chain import FileHandlerChain
from knowledge_base.task.handlers import (
    FileEmbeddingHandler,
    FileParseHandler,
    FileSplitHandler,
)
from knowledge_base.task.queue import POLL_TIMEOUT_SECONDS, FileTaskQueue
from knowledge_base.task.wrapper import FileTask
from infrastructure.logging.logutil import log

WORKER_THREAD_COUNT = 5

#: 大文件闸门被占用时的重试间隔（秒）。
#:
#: 普通失败仍然无延迟重投；``RetCode.file.size.more`` 值得等一等 ——
#: 无延迟重投会在几毫秒内烧光 3 次重试预算。
#: 刻意取小值：闸门本身已改成排队等待（见 ``ingestion/runtime.py``），这里只是兜底；
#: 而且重试发生在 worker 线程里，sleep 太久会拖住进程关停（compose 默认 10 秒宽限）。
BUSY_RETRY_DELAY_SECONDS = 5


def _is_large_file_busy(error: BaseException) -> bool:
    """``operator_runtime._invoke`` 把忙等错误包成 ``KbApiError(key=...)``。

    key 必须是 ``RetCode.file.size.more`` —— 映射表未登记时它会落到
    ``RetCode.operator.split.error`` 兜底键，与真实切分错误无法区分。
    """
    return isinstance(error, KbApiError) and error.key == 'RetCode.file.size.more'


def process_file(file_handle: dict) -> None:
    """跑处理链，成功后把状态推到「全链成功」。

    ⚠️ 链抛异常时 ``updateFileStatus(..., 1)`` **不会执行**（异常直接上抛给
    worker 去重试/判失败）—— 顺序不能反。
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


class FileTaskExecutor:
    """固定数量的 worker 线程。"""

    def __init__(self, worker_count: int = WORKER_THREAD_COUNT):
        self._worker_count = worker_count
        self._threads: list[threading.Thread] = []
        self._shutdown = False

    def start(self, queue_manager: FileTaskQueue) -> None:
        for index in range(1, self._worker_count + 1):
            thread = threading.Thread(target=self._worker_loop, args=(queue_manager, index),
                                      name=f'FileTask-Worker-{index}', daemon=False)
            thread.start()
            self._threads.append(thread)
        log.info('started %d file task workers', self._worker_count)

    def _worker_loop(self, queue_manager: FileTaskQueue, worker_id: int) -> None:
        while not self._shutdown:
            try:
                task = queue_manager.poll_task()
            except Exception:
                log.exception('worker %s poll failed', worker_id)
                continue
            if task is None:
                continue
            try:
                self._execute_task(queue_manager, task)
            except Exception:
                log.exception('worker %s execute task %s crashed', worker_id, task.task_id)

    def _execute_task(self, queue_manager: FileTaskQueue, task: FileTask) -> None:
        try:
            process_file(task.file_handle)
            # 成功路径才标「已修改」—— 失败不该动知识库状态
            kbase_store.set_kbase_status_modified((task.file_handle or {}).get('kbaseId'))
            task.mark_as_completed()
            queue_manager.update_task_status(task)
            log.info('task %s completed', task.task_id)
        except Exception as error:
            log.exception('task %s failed', task.task_id)
            if task.can_retry():
                self._retry_task(queue_manager, task, error)
            else:
                task.mark_as_failed(task.failure_message(error))
                queue_manager.update_task_status(task)

    def _retry_task(self, queue_manager: FileTaskQueue, task: FileTask, error) -> None:
        """``retryTask``：markAsRetry（retryCount++）→ 重投队尾。

        普通错误立即重投；大文件闸门被占用时先等 ``BUSY_RETRY_DELAY_SECONDS``，
        否则 3 次重试会在毫秒级烧完（实测：一次批量导入里 4 个大文件各试 4 次，
        总共只用了 0.5 秒）。
        """
        task.mark_as_retry()
        task.error_message = str(error)
        if _is_large_file_busy(error):
            log.info('task %s hit the large-file gate, retry in %ss',
                     task.task_id, BUSY_RETRY_DELAY_SECONDS)
            time.sleep(BUSY_RETRY_DELAY_SECONDS)
        try:
            resubmitted = queue_manager.resubmit_task(task)
        except Exception:
            log.exception('resubmit task %s failed', task.task_id)
            task.mark_as_failed(task.failure_message(error))
            queue_manager.update_task_status(task)
            return
        if not resubmitted:
            task.mark_as_failed('Failed to resubmit task: queue is full')
            queue_manager.update_task_status(task)

    def shutdown(self) -> None:
        """置标志并等 worker 退出。

        Python 的线程**不能被外部中断**，所以只能靠标志位 + 有上限的 join。
        代价：最坏情况下要等一个 ``pollTask`` 的超时（5 秒）才退出 —— 进程关停路径上
        这点延迟可接受（而且我们是 daemon 进程退出，不阻塞）。行为差异不影响任何对外语义。
        """
        self._shutdown = True
        for thread in self._threads:
            thread.join(timeout=POLL_TIMEOUT_SECONDS + 1)
        log.info('file task executor shut down')
