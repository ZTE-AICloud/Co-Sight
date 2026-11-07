"""文档处理的**进程内调用入口**。

## 错误通道

**异常对象携带的 message 是「文案键」**，RKB 侧 ``SPLIT_ERROR_MESSAGES`` 据此映射成
``kb_directory.fail_reason``。所以这里**必须保留异常上 ``code`` / ``bo`` / ``message``
三个属性**，``knowledge_base/task/operator_runtime.py`` 才映射得出同样的键。

三条分支：

  1. ``SensitiveMsgException``   → ``(err.code, err.get_i18n_message(lang))``
  2. 带 ``code``/``bo``/``message`` 的异常（如 ``ParseEmptyError``）
                                 → ``(err.code, err.message)``
  3. 其余 ``Exception``          → ``('0001', str(err.args[0]))``

## 大文件的错误通道

大文件（>50MB）路径下，**只有闸门等待超时**才归为
``Exception("RetCode.file.size.more")``；闸门内切分失败时原样上抛，
由 ``operator_runtime`` 按上面的三条分支映射成真实键
（``RetCode.operator.split.empty`` / ``corrupt`` …）。

旧实现把闸门内的任何异常也折成 ``RetCode.file.size.more``，会掩盖真实原因；
闸门改成排队等待后，「忙」只剩超时一种，折叠只会把「文件解析失败」误报成
「另一个大文件正在处理」，因此不再保留。
"""

import logging
import os
import threading

from ingestion.service.operator import file_parse_service as FileParseService, graph_extract_service as GraphExtractService, text_split_service as TextSplitService

#: 大文件阈值：超过它才参与串行化
LARGE_FILE_SIZE_LIMIT = 52428800  # 50MB

#: 大文件闸门的最长等待时间（秒）。
#:
#: 后到的文件**排队等**，不再一撞锁就失败 —— 批量导入多个大文件时，输家应当
#: 等赢家切完再处理，而不是被判「文件太大」。这个上限只兜底「持锁任务永久卡死」，
#: 与旧 HTTP handler 的 ``REQUEST_TIMEOUT``（36000 秒）同量级。
LARGE_FILE_LOCK_TIMEOUT_SECONDS = 36000

#: 大文件串行闸门。
#:
#: 用进程内 ``Lock``（同一时刻只允许一个大文件切分）。不要改回跨进程文件锁：
#: 算子在独立子进程里跑、触发点在 worker 线程上，跨进程锁没有意义，
#: 而且会往代码树写文件。
_large_file_lock = threading.Lock()


class OperatorBusyError(Exception):
    """大文件切分正在被别的任务占用 —— 对应 ``Exception("RetCode.file.size.more")``。

    ``message`` 是文案键（不是给人看的句子），见模块 docstring。
    """

    code = '0001'
    bo = None
    message = 'RetCode.file.size.more'

    def __str__(self):
        return f"OperatorBusyError(message={self.message})"


# ---------------------------------------------------------------------------
# file_parse（原 POST /kbase/operator/file_parse）
# ---------------------------------------------------------------------------
def file_parse(file_parse_info: dict):
    """文档清洗，返回清洗后文件的绝对路径。"""
    return FileParseService.file_parse_entry(file_parse_info)


# ---------------------------------------------------------------------------
# file_parse/preview（原 POST /kbase/operator/file_parse/preview）
# ---------------------------------------------------------------------------
def file_parse_preview(file_parse_info: dict):
    """同 file_parse，但返回清洗后的文本本身。"""
    return FileParseService.file_parse_entry_string(file_parse_info)


# ---------------------------------------------------------------------------
# text_split（原 POST /kbase/operator/text_split）
# ---------------------------------------------------------------------------
def text_split(text_split_info: dict):
    """切分。**大文件参与串行化**。

    ``fileSize`` 超过 ``LARGE_FILE_SIZE_LIMIT`` 时：
      * 闸门**排队等待**（最多 ``LARGE_FILE_LOCK_TIMEOUT_SECONDS``），
        等不到才 → ``OperatorBusyError``（键 ``RetCode.file.size.more``）
      * 闸门内的真实失败**原样上抛**，交由 ``operator_runtime`` 映射成具体键
    """
    file_size = text_split_info.get('fileSize') or 0
    if file_size <= LARGE_FILE_SIZE_LIMIT:
        return TextSplitService.text_split_entry(text_split_info)

    if not _large_file_lock.acquire(timeout=LARGE_FILE_LOCK_TIMEOUT_SECONDS):
        logging.error(
            "Timed out waiting for the large file lock. fileSize=%s, limit=%s, waited=%ss",
            file_size, LARGE_FILE_SIZE_LIMIT, LARGE_FILE_LOCK_TIMEOUT_SECONDS)
        raise OperatorBusyError()

    try:
        return TextSplitService.text_split_entry(text_split_info)
    except Exception as error:
        # 真实原因（正文为空 / 格式不支持 / 文件损坏）必须带出去：折叠成
        # 「大文件忙」会让用户按错误提示去重试，永远看不到真正的问题。
        logging.error("Large file text_split failed: %s", error)
        raise
    finally:
        _large_file_lock.release()


# ---------------------------------------------------------------------------
# graph_extract（原 POST /kbase/operator/graph_extract）
# ---------------------------------------------------------------------------
def graph_extract(graph_extract_info: dict, lang_id: str = 'zh_CN'):
    """抽图。保持原契约：调用方据 ``code == '0'`` 判成功。"""
    return GraphExtractService.graph_extract_entry(graph_extract_info, lang_id)


# ---------------------------------------------------------------------------
# code-check（原 POST /kbase/operator/{file_parse,text_split,graph_extract}/code-check）
# ---------------------------------------------------------------------------
def code_check_file_parse(script_path: str, parameters: dict):
    return FileParseService.code_check(script_path, parameters)


def code_check_text_split(script_path: str, parameters: dict):
    return TextSplitService.code_check(script_path, parameters)


# ---------------------------------------------------------------------------
# 系统算子清单（原 GET /kbase/operator/system/info）
# ---------------------------------------------------------------------------
#: 清单文件的位置：ingestion/split/operator_all.json（随包目录定位）
#:
#: **为什么是文件而不是数据库表**：全仓对该文件的引用清一色是只读
#: `open(..., 'r')`，内容是 2 个固定的内置算子，不会变。为一份只读静态数据
#: 建表 + 迁移 + 读路径 + 新故障面，买不到任何东西。
#:
#: 用户上传的算子是**另一条路**：走 RKB 的 `/api/co-knowledge/v1/operators`，
#: 落在 `rag_studio.operator` 表 + PVC（见 `src/operators/service/operator_import.py`），
#: 与本文件无关。两条路职责清晰，不要合并。
SYSTEM_OPERATOR_FILE = os.path.join(os.path.dirname(__file__), 'split', 'operator_all.json')
