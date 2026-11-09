"""系统算子执行路径（`split/system_split_manager.py::segment_file` 调用）。

安全契约（见 `docs/operator-interface.md`）：
- 结果序列化：**禁 pickle，改 JSON**。系统算子 `file_split` 返回 `List[LCDocument]`
  （自定义类，非 JSON 可序列化），因此在子进程内先把每个 `LCDocument` 转成
  `{"page_content", "metadata", "id"}` 字典，再经 JSON 文件在父子进程间交换，
  父进程反序列化时还原为等价的 `_LCDocument` 对象（`page_content`/`metadata`/`id`
  三字段与原 `LCDocument` 对齐），保证 `system_split_manager.py` 后续
  `rewrite_source_metadata` / `parse_md_to_nodes` 逻辑不受影响。

## 安全加固

系统算子执行与 A 路（`self_operator.execute_function_in_sandbox`）保持同一套约束：

| 项 | 要求 |
|---|---|
| 上下文 | forkserver（`sandbox_runtime.sandbox_context`），**不要**用裸 `Process(...)`（Linux 上默认 fork） |
| 超时 | 有界等待 + 终止 + 硬杀；`process.join()` / `queue.get()` **必须带超时**，否则子进程挂死会永久占死调用线程 |
| 资源限制 | `RLIMIT_AS`（与 A 路同口径） |
| 危险代码 | 父进程先扫（与 A 路一致），子进程内复扫 |

**为什么「fork 从带线程的进程」是危险组合**：调用方进程里跑着 3 个常驻线程
（语料队列消费者、清理任务…）。从多线程进程 fork，子进程会继承可能处于不一致
状态的锁。fork 还会继承父进程的整个内存镜像，而这里根本不需要继承
（参数经 `Queue` + 临时文件传递）。

**超时值**：复用 A 路的 `_resolve_timeout`（`file_split` / `file_split_with_chunk`
300s / `file_parse` 600s / `graph_extract` 1800s，可用 `OPERATOR_TIMEOUT_SECONDS`
统一覆盖）。系统算子切分大文档
可能超过 300s —— 遇到时用该环境变量放宽。

**超时的对外表现**：抛 `SandboxTimeoutError`，其 message 不含已知文案键，
经 `SPLIT_ERROR_MESSAGES` 未命中而落兜底键 `RetCode.operator.split.error`。
这是**保守选择**：不新增文案键（新增会变更对外可见的落库值，属独立变更）。
"""
import json
import logging
import queue as queue_module
import time
import shutil
import tempfile
from typing import Any
import importlib.util
import sys

from parsing.exception import SensitiveMsgException

from ingestion.service.operator.dangerous_function_visitor import validate_code_security
from ingestion.utility import sandbox_runtime
from ingestion.utility.self_operator import (
    SandboxTimeoutError,
    _resolve_timeout,
    set_resource_limits,
)


class _LCDocument:
    """LCDocument 反序列化载体（对齐各系统算子返回的 page_content/metadata/id）。"""

    def __init__(self, page_content, metadata, doc_id=None):
        self.page_content = page_content
        self.metadata = metadata
        self.id = doc_id


def _to_jsonable(obj):
    """递归把算子返回值转换为 JSON 可序列化结构（LCDocument → dict）。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {key: _to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    if hasattr(obj, "page_content") and hasattr(obj, "metadata"):
        return {
            "page_content": _to_jsonable(getattr(obj, "page_content", None)),
            "metadata": _to_jsonable(getattr(obj, "metadata", None)),
            "id": _to_jsonable(getattr(obj, "id", None)),
        }
    raise TypeError(
        f"Object of type {type(obj).__name__!r} is not JSON serializable. "
        "Operator must return a JSON-serializable structure."
    )


def _from_jsonable(obj):
    """递归把 JSON 反序列化结构还原为等价的 LCDocument 对象。"""
    if isinstance(obj, dict):
        if "page_content" in obj and "metadata" in obj:
            return _LCDocument(obj.get("page_content"), obj.get("metadata"), obj.get("id"))
        return {key: _from_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_from_jsonable(item) for item in obj]
    return obj


def _deliver(queue, payload: str, original_error) -> None:
    """把结果/错误文件路径交给父进程。**交付失败必须抛，不能悄悄退出。**

    ``multiprocessing.Queue.put()`` 首次调用会启动 feeder 线程；沙箱子进程有
    ``RLIMIT_AS``，额度用满时 ``pthread_create``（线程栈 8MB）会失败并抛
    ``RuntimeError: can't start new thread``。此时 ``self._thread`` 已被赋成一个
    **未启动**的 Thread 对象，于是后续 ``put`` 会跳过 ``_start_thread``、只把对象
    追加进缓冲区就正常返回 —— 子进程随即 "正常退出"（**exitcode=0**），父进程却
    一个字节都没收到，只能报 ``System operator subprocess crashed (exitcode=0)``；
    原始错误写在本进程的 ``.err`` 文件里，又被父进程的 ``finally`` 一并 rmtree 掉。
    这样会把「内存配额不足」伪装成「切分算子执行失败」（
    2MB PDF + 159 切片即触发）。

    重新抛出后，multiprocessing 会把 exitcode 置为非 0 并打印 traceback ——
    至少容器日志里能看见真实原因。
    """
    try:
        queue.put(payload)
    except BaseException:  # noqa: BLE001 - 交付失败即进程级故障，必须暴露
        logging.exception(
            "sandbox worker failed to deliver %r to parent (original error: %s)",
            payload, original_error)
        raise


def sandbox_worker(queue, module_path: str, function_name: str, temp_dir: str, **kwargs):
    """
    沙箱进程执行算子逻辑，结果写入临时文件
    """
    try:
        # 0) 环境变量收敛到白名单 —— **必须最先做**：算子模块经
        #    operator_api.llm 在**导入时**读 MODEL_GATEWAY_*，
        #    顺序错了会静默丢配置（算子退回默认端点）。
        sandbox_runtime.sanitize_environment()
        # 0.5) 把 src/ 放进 import 路径（公开接口 operator_api 从这里导入）
        sandbox_runtime.ensure_import_root()
        # 1) 资源限制（与 A 路同口径）
        set_resource_limits()
        # 2) 危险代码扫描（防御纵深：父进程已扫过一遍，真实执行路径再复检）
        validate_code_security(module_path)

        # 动态加载模块
        spec = importlib.util.spec_from_file_location("operator_module", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["operator_module"] = module
        spec.loader.exec_module(module)

        # 获取函数
        if not hasattr(module, function_name):
            raise AttributeError(f"Function '{function_name}' not found in module '{module_path}'")
        func = getattr(module, function_name)

        # 执行算子函数
        result = func(**kwargs)

        # 结果序列化：去 pickle，改 JSON（契约 §4.8）。
        # 系统算子返回 List[LCDocument]，先转 dict 再 json.dump。
        temp_file = tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=".json")
        with open(temp_file.name, 'w', encoding='utf-8') as f:
            json.dump(_to_jsonable(result), f, ensure_ascii=False)

        # 返回临时文件路径
        _deliver(queue, temp_file.name, None)
    except SensitiveMsgException as e:
        error_file = tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=".sen_err")
        with open(error_file.name, 'w') as f:
            exception_json = {
                'code': e.code,
                'bo': e.bo,
                'message_dict': e.message_dict
            }
            json.dump(exception_json, f, ensure_ascii=False, indent=2)
        _deliver(queue, error_file.name, e)


    except Exception as e:
        error_file = tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=".err")
        with open(error_file.name, 'w') as f:
            # ⚠️ 文本**只能**是异常自己的 ``str(e)``，别加前缀、别吞字：
            # 这一段会原样经 ``pretty_error_response`` 落到信封 ``code.msg``，是下游
            # （``SPLIT_ERROR_MESSAGES`` 的 msg 比对）的比对面。
            # 带 ``.message`` 的异常（ParseEmptyError / SensitiveMsgException 这类
            # 「message 即文案键」的）**只写键**——它们的 ``str()`` 里带诊断细节，
            # 混进信封就会让键匹配失败、退回泛化文案。细节本来就有 logging。
            f.write(getattr(e, 'message', None) or str(e))
        # 异常详情也要进容器日志：只写文件的话，父进程一 rmtree 就什么都不剩，
        # 排障时只能看到父进程那句泛化的 "subprocess crashed"。
        logging.exception("system operator %s failed", function_name)
        _deliver(queue, error_file.name, e)


def _terminate(process) -> None:
    """终止子进程：terminate → join(5) → kill → join(2)，与 A 路同一套三级收尾。"""
    if process is None:
        return
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive() and hasattr(process, 'kill'):
        process.kill()
        process.join(timeout=2)


def execute_operator_module(module_path: str, function_name: str, **kwargs) -> Any:
    """
    在隔离的进程中运行算子模块，并通过临时文件读取结果。

    与 A 路的差异只在结果形态：系统算子的返回值是 ``List[LCDocument]``，
    经 ``_to_jsonable`` 转成 JSON 再回传（故不走 A 路那套「返回值必须 JSON 可序列化」的
    强校验 —— 这里由本模块自己负责转换）。
    """
    # 父进程先扫一遍危险代码：快速失败，且免得白起一个子进程
    validate_code_security(module_path)

    timeout = _resolve_timeout(function_name, None)

    # 临时目录：每次调用独占一个子目录，finally 里清掉；不要直接用 gettempdir()
    # 根目录（超时路径下结果/错误文件会永久留在 /tmp）。
    temp_dir = tempfile.mkdtemp(prefix='op_')
    ctx = sandbox_runtime.sandbox_context()
    queue = ctx.Queue()
    process = ctx.Process(
        target=sandbox_worker,
        args=(queue, module_path, function_name, temp_dir),
        kwargs=kwargs,
    )

    try:
        process.start()

        # 有界等待：`process.join()` + `queue.get()` **必须带超时**。子进程挂死
        # （死循环 / 卡在出站请求）会永久占死调用线程，而上层是 5 个文件任务 worker，
        # 占满即整条导入链停止推进。
        #
        # 轮询而非一次性等满 timeout：子进程**崩了且没送结果**时应当立刻发现，
        # 而不是白等到 timeout（默认 file_split 300s）。
        result_file_path = None
        deadline = time.monotonic() + timeout
        while result_file_path is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate(process)
                raise SandboxTimeoutError(
                    f"System operator {function_name} timed out after {timeout}s")
            try:
                result_file_path = queue.get(timeout=min(1.0, remaining))
            except queue_module.Empty:
                if not process.is_alive():
                    # 已死且没送结果 —— 真崩溃（退出码才是此时的有效判据）
                    _terminate(process)
                    raise RuntimeError(
                        f"System operator subprocess crashed (exitcode={process.exitcode})")

        # ⚠️ **拿到结果后不要立刻 terminate**：子进程 `queue.put()` 之后还要走完自身
        #    收尾，`queue.get()` 往往先返回 —— 立刻发 SIGTERM 会得到 exitcode=-15，
        #    再被退出码检查误判成「子进程崩溃」。文件任务会报
        #    `RetCode.operator.split.error`，日志里是 `subprocess crashed (exitcode=-15)`。
        #    正确做法是**先给宽限期让它自然退出**；退不出来（真挂死）才强杀，
        #    且那属于「已交付结果后的收尾问题」，只告警，不推翻已经拿到的结果。
        process.join(timeout=5)
        if process.is_alive():
            logging.warning(
                "System operator subprocess still alive after delivering result; terminating")
            _terminate(process)

        if result_file_path.endswith(".err"):
            with open(result_file_path, 'r', encoding='utf-8') as error_file:
                error_message = error_file.read()
            raise RuntimeError(error_message)

        if result_file_path.endswith(".sen_err"):
            with open(result_file_path, 'r', encoding='utf-8') as sen_error_file:
                exception_data = json.load(sen_error_file)
            raise SensitiveMsgException(
                code=exception_data.get('code'),
                bo=exception_data.get('bo'),
                message_dict=exception_data.get('message_dict')
            )

        # 读取结果（JSON，替代 pickle）
        with open(result_file_path, 'r', encoding='utf-8') as result_file:
            jsonable_result = json.load(result_file)

        return _from_jsonable(jsonable_result)
    finally:
        # 无论成功、失败还是超时，子进程与临时目录都要收干净
        _terminate(process)
        try:
            queue.close()
        except Exception:  # noqa: BLE001 - 收尾尽力而为
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)
