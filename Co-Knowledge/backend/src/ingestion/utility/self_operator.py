"""自定义算子隔离执行器。

**边界说明**：下面这些是资源与运行时约束，不是安全边界。算子按可信代码对待，
导入接口只允许管理员；真正的隔离（独立容器/namespace、非 root、无业务卷）
由部署层负责。

运行时约束：
- 资源限制：子进程启用 `RLIMIT_AS`，上限 = 子进程基线 VmSize + 配额（默认 500MB，
  可用 `OPERATOR_MEMORY_LIMIT_MB` 配置）。改用 forkserver 之后基线**小且确定**
  （详见 `set_resource_limits` 与 `sandbox_runtime` 的说明）。
- 子进程上下文：**forkserver**（原为 spawn），且预载列表显式排除 `'__main__'`
  —— 见 `ingestion/utility/sandbox_runtime.py` 的模块 docstring。
- 环境变量：子进程入口先收敛到白名单（`sandbox_runtime.sanitize_environment`），
  知识库数据侧的凭据（RKB_DB_*/RKB_ES_*/POSTGRES_* 等）不进算子进程。
- 超时：可配置，默认按函数收敛到分钟级——切分 `file_split` /
  `file_split_with_chunk` 300s、解析 `file_parse`
  600s、图抽取 `graph_extract` 1800s（可用 `OPERATOR_TIMEOUT_SECONDS` 统一覆盖）。
- 结果序列化：**禁用 pickle**，算子返回值必须是 JSON 可序列化结构，父子进程通过
  JSON 文件交换结果（`json.dumps` / `json.loads`）。
- 返回大小上限：结果 JSON 序列化后默认 ≤ 10MB（`OPERATOR_RESULT_MAX_BYTES`），超限报错。
- 危险代码：每次真实执行前都会做 AST 扫描（`DangerousFunctionVisitor`），防御纵深，
  不依赖上传时的 `code_check` 单独调用。
- 网络访问：尽力禁网（尝试 Linux network namespace `unshare`）；无特权/无 namespace
  时退化为文档级禁止（本文件顶部注释 + 平台能力）。

系统算子（`operators/text_split`）走的是
`utility/operator_zip_action.py::execute_operator_module` 这一独立路径（不在本文件范围），
其返回值是 `LCDocument` 对象（非 JSON 可序列化），因此去 pickle 只影响自定义算子沙箱，
不影响系统算子。
"""
import importlib.util
import inspect
import json
import logging
import multiprocessing
import os
import resource
import sys
import tempfile

from ingestion.service.operator.dangerous_function_visitor import validate_code_security
from ingestion.utility import sandbox_runtime


class ParameterValidationError(Exception):
    pass


class SandboxTimeoutError(RuntimeError):
    """算子沙箱执行超时。"""


class OperatorResultTooLargeError(Exception):
    """算子返回结果超过大小上限。"""


class OperatorResultSerializationError(Exception):
    """算子返回值不是 JSON 可序列化结构。"""


# ---------------------------------------------------------------------------
# 可配置项（通过环境变量覆盖，默认值见契约 §4.8）
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _memory_limit_bytes() -> int:
    """算子子进程内存上限（字节）。默认 500MB。"""
    return _env_int("OPERATOR_MEMORY_LIMIT_MB", 500) * 1024 * 1024


def _result_max_bytes() -> int:
    """算子返回结果 JSON 大小上限（字节）。默认 10MB。"""
    return _env_int("OPERATOR_RESULT_MAX_BYTES", 10 * 1024 * 1024)


# 契约 §4.8：切分 300s / 解析 600s。graph_extract 是**逐 chunk 调大模型**的算子
# （算子自身对单次 HTTP 调用给到 1800s），600s 连小文档都跑不完（单 chunk 关闭
# 思考后 ~10s、开启思考后 >600s），故按算子自身的预算取 1800s。
_DEFAULT_TIMEOUTS = {
    "file_split": 300,
    # 系统算子 -1 的入口函数名（-1/-2 合并到 operators/text_split）。
    # 不登记会落到 600s 兜底，等于把默认切分的超时翻倍。
    "file_split_with_chunk": 300,
    "file_parse": 600,
    "graph_extract": 1800,
}
_DEFAULT_TIMEOUT_FALLBACK = 600


def _resolve_timeout(function_name: str, timeout) -> int:
    """解析超时值：显式传入 > 函数级环境变量 > 统一环境变量 > 函数默认值。

    大图谱抽图（数百 chunk）在慢网关上可能超过 1800s；用
    `OPERATOR_GRAPH_EXTRACT_TIMEOUT_SECONDS` 单独放宽，不影响切分/解析。
    """
    if timeout is not None:
        return int(timeout)
    specific = _env_int(
        f"OPERATOR_{function_name.upper()}_TIMEOUT_SECONDS", 0)
    if specific > 0:
        return specific
    env_timeout = _env_int("OPERATOR_TIMEOUT_SECONDS", 0)
    if env_timeout > 0:
        return env_timeout
    return _DEFAULT_TIMEOUTS.get(function_name, _DEFAULT_TIMEOUT_FALLBACK)


def _current_vmsize_bytes() -> int:
    """本进程当前虚拟地址空间大小（``/proc/self/status`` 的 VmSize）。读不到返回 0。"""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


def set_resource_limits(memory_limit_mb=None):
    """在子进程内启用内存上限（RLIMIT_AS，软硬限相同，设后不可提升）。

    上限 = **当前进程基线 VmSize + ``OPERATOR_MEMORY_LIMIT_MB``（默认 500）**，
    即配额是「算子自身可用的内存」，不含沙箱子进程自身的基线。

    不能直接设成 500MB 绝对值：上限低于基线等于「不允许任何新分配」—— 算子会在执行前的
    AST 安全扫描就 MemoryError，并被误报成 ``file_read_error`` 式的「代码安全检查失败」。

    **上下文改用 forkserver 后基线变得又小又确定**：子进程从只预载了两个模块的
    server fork 出来，不再重新导入应用入口（spawn 下子进程基线曾达 551MB、
    父进程 735MB）。因此
    「子进程入口自测基线 + 配额」这一相对算术重新成立，无需父进程注入绝对上限。
    """
    if memory_limit_mb is None:
        memory_limit_mb = _env_int("OPERATOR_MEMORY_LIMIT_MB", 500)
    memory_limit = _current_vmsize_bytes() + memory_limit_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))


def _try_disable_network():
    """尽力禁网。

    尝试 Linux network namespace（`unshare(CLONE_NEWNET)`）。普通容器/无
    CAP_SYS_ADMIN 时通常返回 EPERM，此时退化为「文档级禁止 + 依赖平台能力」
    （契约 §4.8 允许的兜底）。
    """
    try:
        import ctypes

        CLONE_NEWNET = 0x40000000
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.unshare(CLONE_NEWNET) == 0:
            return True
    except Exception as e:  # noqa: BLE001 - 尽力而为，失败不阻断执行
        logging.debug("Sandbox network namespace isolation unavailable: %s", e)
    return False


def _json_default(obj):
    """让 json.dumps 在遇到不可序列化对象时抛出清晰错误。"""
    raise TypeError(
        f"Object of type {type(obj).__name__!r} is not JSON serializable. "
        "Operator must return a JSON-serializable structure (e.g. str / list[dict])."
    )


def _serialize_result(result):
    """将算子返回值序列化为 JSON 字节串，并校验大小上限。"""
    try:
        raw = json.dumps(result, ensure_ascii=False, default=_json_default)
    except TypeError as e:
        raise OperatorResultSerializationError(str(e)) from e
    data = raw.encode("utf-8")
    max_bytes = _result_max_bytes()
    if len(data) > max_bytes:
        raise OperatorResultTooLargeError(
            f"Operator result size {len(data)} bytes exceeds limit {max_bytes} bytes"
        )
    return data


def target_function(conn, script_path, function_name, operator_params):
    """子进程入口：环境收敛 + 资源限制 + 禁网 + 危险代码扫描 + 执行 + JSON 序列化回传。"""
    temp_file_path = None
    try:
        # 0) 环境变量收敛到白名单 —— **必须最先做**：算子模块（经
        #    operator_api.llm）是在**导入时**读 MODEL_GATEWAY_* 的，
        #    顺序错了会静默丢配置，算子退回默认端点。
        sandbox_runtime.sanitize_environment()
        # 0.5) 保证 ``src/`` 在导入路径上，插件可以 import ``operator_api.*``。
        sandbox_runtime.ensure_import_root()

        # 安全检查：确保脚本路径存在
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")

        # 1) 资源限制（契约 §4.8）
        set_resource_limits()
        # 2) 尽力禁网
        _try_disable_network()
        # 3) 危险代码扫描（防御纵深：真实执行路径也复检）
        validate_code_security(script_path)

        # 动态加载模块
        spec = importlib.util.spec_from_file_location("sandbox_module", script_path)
        if spec is None:
            raise RuntimeError(f"Cannot load spec from {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, function_name):
            raise AttributeError(f"Function '{function_name}' not found in {script_path}")

        func = getattr(module, function_name)
        if not callable(func):
            raise TypeError(f"'{function_name}' is not callable")

        # 执行函数
        result = func(**operator_params)

        # JSON 序列化到临时文件（去 pickle，见文件顶部契约说明）
        data = _serialize_result(result)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            tmp_file.write(data)
            temp_file_path = tmp_file.name

        # 发送成功消息
        conn.send(("success", temp_file_path))

    except Exception as e:
        # 构造错误信息（避免发送不可序列化对象）
        error_msg = f"{type(e).__name__}: {str(e)}"
        try:
            conn.send(("error", error_msg))
        except Exception:
            logging.exception(e)
    finally:
        try:
            conn.close()
        except Exception:
            logging.exception('failed to close sandbox connection')


def _unwrap_sandbox_error(payload: str) -> str:
    """把子进程回传的 ``"<Type>: <message>"`` 还原成抛出时的 message。

    子进程不能再抛异常对象，只能回传字符串；这里按**构造时的固定形状**
    （``target_function`` 的 ``f"{type(e).__name__}: {str(e)}"``）反解。

    ⚠️ 特殊情况是「message 即文案键」的异常（ParseEmptyError 等，message 形如
    ``RetCode.*``）：它们的 ``str()`` 带诊断细节，直接被上层当文案键匹配就会失败、
    退回泛化文案。这里认出**内层 message 已是键**的情形就只返回键本身，
    与 ``operator_zip_action.sandbox_worker`` 对系统算子的处理保持一致。
    """
    _error_type, separator, inner = payload.partition(': ')
    if separator and (inner.startswith('RetCode.') or inner.startswith('Recode.')):
        # 内层 message 本身就是文案键 —— 丢弃类型前缀与 str() 里的诊断细节
        return inner
    return payload


def execute_function_in_sandbox(script_path, function_name, timeout=None, **kwargs):
    """在隔离子进程中执行用户算子，返回 JSON 反序列化后的结果。"""
    # 危险代码扫描：接入真实执行路径（每次执行前复检，而非仅上传时 code_check）
    validate_code_security(script_path)

    timeout = _resolve_timeout(function_name, timeout)

    process = None
    temp_file_path = None
    parent_conn, child_conn = multiprocessing.Pipe()

    try:
        # 过滤参数（保留键见契约 §4.7：受控上下文不作为算子 kwargs 传入）
        valid_args = ["emp_no", "kbase_id", "format"]
        operator_params = {k: v for k, v in kwargs.items() if k not in valid_args}

        ctx = sandbox_runtime.sandbox_context()
        process = ctx.Process(
            target=target_function,
            args=(child_conn, script_path, function_name, operator_params)
        )
        process.start()
        child_conn.close()

        if parent_conn.poll(timeout=timeout):
            status, data = parent_conn.recv()
        else:
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            raise SandboxTimeoutError(f"Sandbox timeout ({timeout}s) for {function_name}")

        # 等待子进程自然退出
        we_terminated = False
        process.join(timeout=5)
        if process.is_alive():
            # ⚠️ 走到这里说明子进程**已经交付了结果**、但 5 秒内没退干净。
            #    此时强杀它属于「结果已拿到之后的收尾问题」，**不能因此推翻结果** ——
            #    杀出来的 exitcode 会是 -15，若拿去跑下面的「崩溃」判定就会误报成
            #    `Subprocess crashed`。（B 路 operator_zip_action 正是缺这层区分，
            #    导致系统算子切分必然间歇失败，见 d733856。）
            logging.warning("Sandbox process did not exit cleanly after delivering result; terminating.")
            process.terminate()
            we_terminated = True
            process.join(timeout=2)
            if process.is_alive():
                if hasattr(process, 'kill'):
                    process.kill()
                    process.join(timeout=2)

        # 只有在**不是我们杀的**情况下，退出码才反映子进程自己的结局
        if not we_terminated and process.exitcode not in (0, None):
            raise RuntimeError(f"Subprocess crashed (exitcode={process.exitcode})")

        if status == "error":
            raise RuntimeError(f"Sandbox function failed: {_unwrap_sandbox_error(data)}")

        temp_file_path = data
        with open(temp_file_path, 'rb') as f:
            result = json.loads(f.read().decode('utf-8'))
        return result

    except SandboxTimeoutError:
        raise
    except Exception as e:
        raise RuntimeError(f"Sandbox execution failed: {str(e)}") from e

    finally:
        parent_conn.close()
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as e:
                logging.exception(e)
        if process and process.is_alive():
            process.terminate()


def load_module_from_file(script_path):
    module_name = script_path.split("/")[-1].split(".")[0]
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def validate_parameters(func, param_name_to_check, expected_param_type):
    sig = inspect.signature(func)
    parameters = sig.parameters
    if param_name_to_check not in parameters:
        raise ParameterValidationError(f"Parameter '{param_name_to_check}' not found in function '{func.__name__}'.")
    param = parameters[param_name_to_check]
    if param.annotation != expected_param_type:
        actual_type = param.annotation.__name__ if param.annotation != inspect.Parameter.empty else 'None'
        raise ParameterValidationError(
            f"Parameter '{param_name_to_check}' should be of type '{expected_param_type.__name__}', "
            f"but got '{actual_type}' in function '{func.__name__}'."
        )


def validate_return_type(func, expected_return_type):
    sig = inspect.signature(func)
    return_annotation = sig.return_annotation

    if return_annotation != expected_return_type:
        actual_type = return_annotation.__name__ if return_annotation != inspect.Signature.empty else 'None'
        raise ParameterValidationError(
            f"Function '{func.__name__}' should return '{expected_return_type.__name__}', "
            f"but got '{actual_type}'."
        )


# 参数类型仅允许这三种（契约 §4.5），用白名单映射替代 eval（去 eval 注入面）
_ALLOWED_PARAM_TYPES = {"str": str, "int": int, "bool": bool}


def check_operator_code(script_path: str, function_name: str, parameters: dict):
    module = load_module_from_file(script_path)
    try:
        if hasattr(module, function_name):
            function_to_call = getattr(module, function_name)
            for key, value in parameters.items():
                if value not in _ALLOWED_PARAM_TYPES:
                    raise Exception(f"Function {key} param type {value} not support.")
                class_type = _ALLOWED_PARAM_TYPES[value]
                validate_parameters(function_to_call, key, class_type)
            if function_name == 'file_parse':
                validate_return_type(function_to_call, str)
        else:
            raise Exception(f"Function {function_name} not found.")
    except ParameterValidationError as e:
        raise Exception(f"Parameter validation error: {e}")


def extract_params(operator_param_list):
    params = {}
    if operator_param_list is None:
        return params
    for param in operator_param_list:
        params[param.get('argName')] = param.get('defaultValue')
    return params


def extract_params_type(operator_param_list):
    param_types = {}
    if (operator_param_list is None):
        return param_types
    for param in operator_param_list:
        param_types[param.get('argName')] = param.get('argType')
    return param_types


if __name__ == "__main__":
    params = {
        "file_path": "/tmp/test.py",
        "custom_args": "1"
    }
    types = {

    }
    # check_operator_code("utility/test.py","file_parse", types)
    result = execute_function_in_sandbox("utility/test.py", "file_parse", **params)
    print(result)
