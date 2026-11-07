"""文档处理模块的调用面（文档清洗与切片）—— **进程内**，不再是 HTTP 客户端。

## 进程内适配器

直调 ``ingestion.runtime``，不再有 HTTP 边界。

**函数名与签名一律保持不变**，所以调用点是 ``task/handlers.py`` 与 ``graph/service/graph_extract_api.py``。

## 保留得最小心的是错误通道

异常把**文案键当作 ``message``**，本模块用 :data:`SPLIT_ERROR_MESSAGES` 映射成
``kb_directory.fail_reason``。

**映射的输入输出必须保持不变**（它决定落库的键、进而决定前端文案），
所以 :func:`_envelope_of` 保留下面的取值分支：

  1. ``SensitiveMsgException``  → ``(err.code, err.get_i18n_message(lang))``
  2. 同时具备 ``code``/``bo``/``message`` 的异常（如 ``ParseEmptyError``）
                               → ``(err.code, err.message)``
  3. 其余 ``Exception``         → ``('0001', str(err.args[0]))``

语言固定 ``zh_CN`` —— 客户端请求头就是写死的 ``X-Lang-Id: zh_CN``。

## 已移除

``DOC_PIPELINE_URL`` / ``API_PREFIX`` 等常量、``_base_url()``、``_post()``、
以及 ``requests`` 依赖 —— 进程内调用不再需要（这是本次合并对外契约的**有意变更**，
见合并方案的设计说明）。
"""

from __future__ import annotations

from parsing.exception import SensitiveMsgException

from shared.errors.api import KbApiError
from infrastructure.logging.logutil import log

# 语言写死（不从请求转发）——进程内调用沿用
LANG_ID = 'zh_CN'


def _runtime():
    """惰性取 ``ingestion.runtime``。

    **不要在模块顶层 import 它**：本模块属 ``operators``，而 ``tests/`` 刻意保持
    「不依赖 app.py、在任何装了 fastapi/pytest 的环境都能跑」。``ingestion.runtime``
    会连带拉进 pyaml_env / psycopg2 / pandas 等 RKB 运行期依赖，一旦顶层引入，
    宿主机上 24 个测试模块直接收集失败（实测）。

    惰性导入后：模块导入零额外依赖（测试可收集、可 monkeypatch 这四个函数），
    只有**真正发起调用**时才需要运行期依赖 —— 而那只会发生在容器里。
    """
    from ingestion import runtime as _rt
    return _rt

_SUCCESS_CODE = '0000'

# 切分业务码映射：文档处理模块返回这些 msg 时
# 转成对应的 fail_reason 键（会落到 kb_directory.fail_reason，前端据此提示）
#
# ⚠️ 约定：文档处理模块的**文案键本身就是异常 message**（``raise Exception("RetCode.x")``
# 形态），映射的键因此就是键名。
#
# 文档处理模块发出的**实际取值是文案键本身**（``RetCode.file.size.more`` 全键），
# 所以映射表里必须把全键也登记进来；只写 ``FILE_SIZE_MORE`` 这类短名会命中不了，
# 失败会落到兜底键 ``RetCode.operator.split.error``（"切分算子执行失败，请检查算子
# 是否存在问题"）—— 把「大文件排队/超时」说成「算子坏了」，用户会去查算子。
SPLIT_ERROR_MESSAGES = {
    'CHUNK_SIZE_MORE': 'RetCode.chunk.size.more',
    'RetCode.chunk.size.more': 'RetCode.chunk.size.more',
    'FILE_SIZE_MORE': 'RetCode.file.size.more',
    'RetCode.file.size.more': 'RetCode.file.size.more',
    'SENSITIVE_ERROR_CODE': 'RetCode.sensitive.check.failed',
    # 解析完成但正文为空（JS 渲染页空壳 / 扫描件 / 空白文件）：
    # 解析器的 ``ParseEmptyError.message`` 就是这个键。
    'RetCode.operator.split.empty': 'RetCode.operator.split.empty',
    # 没有解析器的格式（OFD 等）：``UnsupportedFormatError.message``。不映射的话会落到
    # ``RetCode.operator.split.error``（"切分算子执行失败"），把「格式不支持」说成
    # 「算子坏了」——用户会去查算子，徒劳。
    'RetCode.operator.split.unsupported': 'RetCode.operator.split.unsupported',
    # 文件损坏/不完整（截断的 docx/pptx/xlsx 等 ZIP 包）：``ParseCorruptError.message``。
    # 同样不能落到 split.error —— 33.1 MB 的截断 docx 报
    # "Package not found"，界面却提示「请检查算子是否存在问题」。
    'RetCode.operator.split.corrupt': 'RetCode.operator.split.corrupt',
}

#: 兜底码：原 ``pretty_error_response`` 的属性取值失败分支用 ``HttpCodeEnum.system_failed``
_FALLBACK_CODE = '0001'


def _envelope_of(error) -> tuple:
    """把异常折成原信封的 ``(code, msg)``。分支顺序与语义见模块 docstring。"""
    if isinstance(error, SensitiveMsgException):
        return error.code, error.get_i18n_message(LANG_ID)

    if all(hasattr(error, attr) for attr in ('code', 'bo', 'message')):
        return error.code, error.message

    detail = error.args[0] if error.args else ''
    return _FALLBACK_CODE, str(detail)


def _invoke(call, fallback_key: str):
    """执行进程内调用；异常按原信封语义折成 :class:`KbApiError`。"""
    try:
        return call()
    except KbApiError:
        raise
    except Exception as error:
        code, message = _envelope_of(error)
        log.exception('in-process parse/split call failed')
        mapped = SPLIT_ERROR_MESSAGES.get(message)
        raise KbApiError(mapped or fallback_key, code=code or '0005') from error


def file_parse(operator_id, args, python_path, file_format, regex_list, disk_file_key) -> str:
    """``fileParse``：调清洗算子，返回**清洗后文件的绝对路径**。

    字段名与进程内入参一致（保持调用点不变）。
    """
    return _invoke(lambda: _runtime().file_parse({
        'operatorId': operator_id,
        'args': args,
        'pythonPath': python_path,
        'fileFormat': file_format,
        'regexList': regex_list,
        'diskFileKey': disk_file_key,
    }), fallback_key='RetCode.file.parse.error')


def file_parse_preview(operator_id, args, python_path, file_format, regex_list,
                       disk_file_key) -> str:
    """``fileParsePreview``：与 :func:`file_parse` 同形，但返回清洗后的**文本本身**。

    下载清洗文件那条链用的就是它（``KbFileService.downloadCleanPreview``）。
    """
    return _invoke(lambda: _runtime().file_parse_preview({
        'operatorId': operator_id,
        'args': args,
        'pythonPath': python_path,
        'fileFormat': file_format,
        'regexList': regex_list,
        'diskFileKey': disk_file_key,
    }), fallback_key='RetCode.file.preview.error')


def text_split(operator_id, args, python_path, file_format, clean_path,
               file_name, file_size, kbase_id, split_preview=None) -> dict:
    """``textSplit``：调切分算子，返回 切分结果（``results`` + ``chunks``）。

    ``splitPreview`` 上传链**不设**（保持 null），只有预览链才置 true。
    """
    return _invoke(lambda: _runtime().text_split({
        'operatorId': operator_id,
        'args': args,
        'pythonPath': python_path,
        'fileFormat': file_format,
        'cleanPath': clean_path,
        'splitPreview': split_preview,
        'fileName': file_name,
        'fileSize': file_size,
        'kbaseId': kbase_id,
    }), fallback_key='RetCode.operator.split.error')


def graph_extract(operator_id, args, python_path, file_format, kb_id,
                  disk_file_key, regex_list, kwargs) -> dict:
    """``graphExtract``：调抽图算子，返回 ``bo``（``{code, message}``，``code=='0'`` 才算成功）。

    ⚠️ **``args`` 与 ``kwargs`` 分工不同**（实测，见
    ``memory/graph-extract-operator-contract.md``）：

    * ``args`` → 经 ``extract_params`` 变成**算子函数的 kwargs**；
      ``llm`` 必须藏在其中一个 argName 叫 ``kwargs`` 的条目里。
    * 这个顶层 ``kwargs`` → **只**用于切分参数（``chunkSize``/``overlap`` 等）。

    把 ``chunkSize`` 放进 ``args`` 会让算子报
    ``graph_extract() got an unexpected keyword argument 'chunkSize'``。
    """
    return _invoke(lambda: _runtime().graph_extract({
        'operatorId': operator_id,
        'args': args,
        'pythonPath': python_path,
        'fileFormat': file_format,
        'kbId': kb_id,
        'diskFileKey': disk_file_key,
        'regexList': regex_list,
        'kwargs': kwargs,
    }, LANG_ID), fallback_key='Retcode.graph.import.fail')
