"""算子沙箱加固自测。

运行方式（在 RKB 容器内，因为要用到解析器依赖）：
    python3 /app/src/ingestion/tests/test_sandbox.py

覆盖的加固项：
  1) 危险算子被拒（AST 扫描接入真实执行路径）
  2) 死循环算子按超时终止
  3) 超大返回被拒（返回大小上限 10MB）
  4) 去 pickle：JSON 可序列化返回正常往返 / 自定义对象被拒
  5) 内存上限按「子进程基线 + 配额」计算
  6) 子进程跑在 forkserver 上、且**不重跑入口模块**（合并进 RKB 的关键性质，见下）
  7) 子进程环境变量收敛到白名单（知识库数据侧凭据不进算子进程）
  8) B 路（系统算子）有界等待——挂死算子必须返回而不是占死调用线程

第 6 项为什么关键：spawn/forkserver **默认都会执行入口模块** —— 注意
``spawn.prepare()`` 里的 ``_fixup_main_from_path → runpy.run_path(main.py)`` 对
**每个子进程**都会跑，把 ``'__main__'`` 从 forkserver 预载里摘掉**拦不住它**。
真正管用的是 ``main.py`` 里的 ``if __name__ == '__main__'``
守卫：若 ``from app import app`` 在顶层，每个算子子进程都会重新导入整个应用
（建连接池、装日志 handler…），并在日志轮转的竞态里崩掉（exitcode=1 → 文件任务报
``RetCode.operator.split.error``）。``test_entry_module_imports_are_guarded``
就是钉住这一点。

RKB 那 3 个常驻线程（语料队列消费者、每 5 分钟删 file_track 的清理任务…）若被复制进
子进程，会重复消费队列、删掉正在被读取的文件。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

# 保证可从任意目录运行：本文件在 <服务根>/src/ingestion/tests/ 下，
# 上溯三层得到 import 根 ``src/``。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ingestion.utility.self_operator import (  # noqa: E402
    execute_function_in_sandbox,
    SandboxTimeoutError,
)


def _write_script(dirpath: str, filename: str, source: str) -> str:
    path = os.path.join(dirpath, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return path


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _assert_raises_message(fn, substr, msg):
    try:
        fn()
    except Exception as e:
        if substr.lower() in str(e).lower():
            return str(e)
        raise AssertionError(f"{msg}；期望错误信息包含 {substr!r}，实际: {e!r}")
    raise AssertionError(f"{msg}；未抛出任何异常")


def test_dangerous_operator_rejected():
    """危险算子（os.system）在真实执行路径被 AST 扫描拒绝。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "evil.py", (
            "import os\n"
            "def file_parse(file_path):\n"
            "    os.system('echo pwned')\n"
            "    return 'x'\n"
        ))
        _assert_raises_message(
            lambda: execute_function_in_sandbox(script, "file_parse", file_path="f"),
            "security",
            "危险算子未被拒绝",
        )


def test_dangerous_bypasses_rejected():
    """补充绕过用例：常见黑名单绕过写法均被 AST 扫描拒绝。"""
    cases = {
        "from_import_system": (
            "from os import system\n"
            "def file_parse(file_path):\n"
            "    system('echo pwned')\n"
            "    return 'x'\n"
        ),
        "from_import_popen": (
            "from subprocess import Popen\n"
            "def file_parse(file_path):\n"
            "    Popen(['echo', 'pwned'])\n"
            "    return 'x'\n"
        ),
        "getattr_os_system": (
            "import os\n"
            "def file_parse(file_path):\n"
            "    getattr(os, 'system')('echo pwned')\n"
            "    return 'x'\n"
        ),
        "builtins_subscript_eval": (
            "def file_parse(file_path):\n"
            "    __builtins__['eval']('1+1')\n"
            "    return 'x'\n"
        ),
        "module_alias": (
            "import subprocess as sp\n"
            "def file_parse(file_path):\n"
            "    sp.Popen(['echo', 'pwned'])\n"
            "    return 'x'\n"
        ),
    }
    with tempfile.TemporaryDirectory() as d:
        for name, source in cases.items():
            script = _write_script(d, f"{name}.py", source)
            _assert_raises_message(
                lambda s=script: execute_function_in_sandbox(s, "file_parse", file_path="f"),
                "security",
                f"绕过用例 {name} 未被拒绝",
            )


def test_dead_loop_timeout():
    """死循环算子按超时终止（默认已收敛到分钟级，这里显式传 2s 加速）。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "loop.py", (
            "def file_parse(file_path):\n"
            "    while True:\n"
            "        pass\n"
        ))
        try:
            execute_function_in_sandbox(script, "file_parse", timeout=2, file_path="f")
        except SandboxTimeoutError as e:
            _assert("timeout" in str(e).lower(), f"超时异常信息不含 timeout: {e!r}")
            return
        raise AssertionError("死循环算子未按超时终止")


def test_oversized_result_rejected():
    """超大返回（> 10MB）被拒绝。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "big.py", (
            "def file_split(file_path):\n"
            "    return [{'content': 'x' * (11 * 1024 * 1024), 'metadata': {}}]\n"
        ))
        _assert_raises_message(
            lambda: execute_function_in_sandbox(script, "file_split", file_path="f"),
            "exceeds limit",
            "超大返回未被拒绝",
        )


def test_json_roundtrip():
    """去 pickle 后，JSON 可序列化返回正常往返。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "ok.py", (
            "def file_split(file_path):\n"
            "    return [{'content': 'hello', 'metadata': {'source': 't'}}]\n"
        ))
        result = execute_function_in_sandbox(script, "file_split", file_path="f")
        _assert(result == [{"content": "hello", "metadata": {"source": "t"}}], f"JSON 往返结果不符: {result!r}")


def test_non_json_result_rejected():
    """去 pickle 后，自定义对象返回被明确拒绝（而非 pickle 悄悄吞掉）。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "obj.py", (
            "class Foo:\n"
            "    pass\n"
            "def file_split(file_path):\n"
            "    return Foo()\n"
        ))
        _assert_raises_message(
            lambda: execute_function_in_sandbox(script, "file_split", file_path="f"),
            "json serializable",
            "非 JSON 可序列化返回未被拒绝",
        )


def test_file_parse_str_return():
    """file_parse 返回 str（解析文本）经 JSON 往返保持 str 类型。"""
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "parse.py", (
            "def file_parse(file_path):\n"
            "    return '解析文本'\n"
        ))
        result = execute_function_in_sandbox(script, "file_parse", file_path="f")
        _assert(result == "解析文本", f"file_parse str 返回不符: {result!r}")
        _assert(isinstance(result, str), f"file_parse 返回类型不符: {type(result)!r}")


def test_memory_limit_relative_to_baseline():
    """内存上限 = 进程基线 VmSize + 配额，而非低于基线的绝对值。

    回归用例：沙箱子进程由 spawn 拉起，会重新导入应用入口
    （``__mp_main__`` 修正），基线 VmSize 已达数百 MB。若按绝对值设 500MB，
    上限低于基线 ⇒ 不允许任何新分配 ⇒ 算子连执行前的 AST 扫描都 MemoryError，
    并被误报成「代码安全检查失败」。
    在子进程里断言，避免给测试进程自身套上不可提升的硬限。
    """
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import resource\n"
        # ⚠️ 这是**字符串形式**的导入，机械改写脚本抓不到 —— 模块合并时改过一次
        #    （utility → ingestion.utility），将来再动包名要一并看这里。
        "from ingestion.utility.self_operator import set_resource_limits, _current_vmsize_bytes\n"
        "baseline = _current_vmsize_bytes()\n"
        "set_resource_limits(64)\n"
        "soft, hard = resource.getrlimit(resource.RLIMIT_AS)\n"
        "assert soft == hard, (soft, hard)\n"
        "lo = baseline + 64 * 1024 * 1024 - 1024 * 1024\n"
        "hi = baseline + 64 * 1024 * 1024 + 1024 * 1024\n"
        "assert lo <= soft <= hi, (soft, baseline)\n"
    ) % (_PROJECT_ROOT,)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    _assert(
        proc.returncode == 0,
        f"内存上限未按「基线 + 配额」设置: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else proc.stdout!r}",
    )


def test_child_context_is_forkserver():
    """沙箱上下文必须是 forkserver（原为 spawn）。

    换成 forkserver 的两个收益：① 子进程从预载过的 server fork 出来，不再重新导入
    应用入口 —— 这正是第 5 项「基線 + 配额」重新成立的前提；② 起始模块状态确定。
    """
    from ingestion.utility.sandbox_runtime import PRELOAD_MODULES, sandbox_context

    ctx = sandbox_context()
    _assert(ctx.get_start_method() == "forkserver",
            f"沙箱上下文应为 forkserver，实际 {ctx.get_start_method()!r}")
    _assert("__main__" not in PRELOAD_MODULES,
            f"预载列表**不得**包含 '__main__'（会让子进程重跑 RKB 入口、各起一份后台线程）: {PRELOAD_MODULES}")


def test_child_does_not_reexecute_entry_module():
    """子进程不得重跑入口模块、不得复制常驻后台线程。

    判据取自**子进程自身的可观测事实**（``__main__`` 的 ``__file__`` 与线程清单），
    而不是父进程的配置 —— 配置写对了不代表运行时真的没重跑。
    """
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "probe.py", (
            "import sys, threading\n"
            "def file_split(file_path):\n"
            "    main_mod = sys.modules.get('__main__')\n"
            "    return {\n"
            "        'main_file': str(getattr(main_mod, '__file__', '') or ''),\n"
            "        'threads': [t.name for t in threading.enumerate()],\n"
            "    }\n"
        ))
        result = execute_function_in_sandbox(script, "file_split", file_path="f")

        # 入口脚本是 RKB 的 main.py —— 若它被重跑，这里会看到它的路径
        _assert("main.py" not in result["main_file"],
                f"沙箱子进程重跑了入口模块: {result['main_file']!r}")

        extra = [name for name in result["threads"] if name != "MainThread"]
        _assert(not extra,
                f"沙箱子进程里出现了额外线程（后台任务被复制进来了）: {extra}")


def test_entry_module_imports_are_guarded():
    """``main.py`` 的**顶层**不得 import ``app`` / ``uvicorn``。

    子进程经 ``spawn.prepare()`` 重跑入口模块时（runpy），顶层 import 会真的执行 ——
    于是每个算子子进程都会重新导入整个 FastAPI 应用，并在日志 handler 的
    ``_backup_remains`` 竞态里崩掉。静态扫描便宜且能覆盖真实运行形态（``__main__``
    就是 main.py），而上面那条运行时探针在 pytest 下 ``__main__`` 是 pytest 本身，
    永远看不到这个问题。
    """
    import ast

    main_py = os.path.join(_PROJECT_ROOT, "main.py")
    with open(main_py, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=main_py)

    guarded_imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            guarded_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            guarded_imports.add(node.module or "")

    for forbidden in ("app", "uvicorn"):
        _assert(forbidden not in guarded_imports,
                f"main.py 顶层 import 了 {forbidden!r} —— 必须在 if __name__ == "
                f"'__main__' 守卫内，否则每个算子子进程都会重导入整个应用")
    return sorted(guarded_imports)


def test_child_environment_is_whitelisted():
    """子进程环境变量收敛：数据侧凭据被剔除，算子出站配置保留。

    顺序很关键 —— ``operator_api.llm`` 在**导入时**读 ``MODEL_GATEWAY_*``，
    所以收敛必须在导入算子模块之前做（实现里是子进程入口第一件事）。
    """
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "env.py", (
            "import os\n"
            "def file_split(file_path):\n"
            "    return {'keys': sorted(os.environ)}\n"
        ))
        saved = {k: os.environ.get(k) for k in
                 ("RKB_DB_PASSWORD", "MODEL_GATEWAY_URL")}
        os.environ["RKB_DB_PASSWORD"] = "should-not-reach-operator"
        os.environ["MODEL_GATEWAY_URL"] = "http://gateway.invalid"
        try:
            keys = set(execute_function_in_sandbox(script, "file_split", file_path="f")["keys"])
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        _assert("RKB_DB_PASSWORD" not in keys,
                "知识库数据侧凭据泄漏进了算子进程")
        _assert("MODEL_GATEWAY_URL" in keys,
                "算子出站配置（MODEL_GATEWAY_URL）被误剔除 —— 抽图算子会退回默认端点")


def test_system_operator_timeout_returns_instead_of_hanging():
    """B 路（系统算子）必须有界等待。

    ``process.join()`` 与 ``queue.get()`` **都必须带超时参数** —— 否则算子挂死会永久占死
    调用线程；调用方是 5 个文件任务 worker，占满即整条导入链停摆。
    """
    from ingestion.utility.operator_zip_action import execute_operator_module

    with tempfile.TemporaryDirectory() as d:
        module = _write_script(d, "hang.py", (
            "def file_split(file_path):\n"
            "    while True:\n"
            "        pass\n"
        ))
        saved = os.environ.get("OPERATOR_TIMEOUT_SECONDS")
        os.environ["OPERATOR_TIMEOUT_SECONDS"] = "5"   # 本用例只验「有界」，不验默认值
        try:
            start = time.monotonic()
            caught = None
            try:
                execute_operator_module(module, "file_split", file_path="f")
            except SandboxTimeoutError as e:
                caught = e
            elapsed = time.monotonic() - start
        finally:
            if saved is None:
                os.environ.pop("OPERATOR_TIMEOUT_SECONDS", None)
            else:
                os.environ["OPERATOR_TIMEOUT_SECONDS"] = saved

        _assert(caught is not None, "挂死的系统算子应抛 SandboxTimeoutError，实际未抛")
        _assert(elapsed < 60, f"未在有界时间内返回（耗时 {elapsed:.1f}s）")


def test_operator_can_import_operator_api():
    """Custom operators import the public interface via ``operator_api.*``.

    The sandbox exposes only the standard library and ``operator_api``; the
    old top-level packages (``client.*`` / ``utility.*``) are intentionally
    gone and are rejected by the import validator.
    """
    with tempfile.TemporaryDirectory() as d:
        script = _write_script(d, "abi_import.py", (
            "from operator_api.logging import TxPrefixedLogger\n"
            "from operator_api.storage import read_text\n"
            "from operator_api.types import Chunk\n"
            "def file_split(file_path):\n"
            "    return {'ok': all([TxPrefixedLogger, read_text, Chunk])}\n"
        ))
        result = execute_function_in_sandbox(script, "file_split", file_path="f")
        _assert(result == {"ok": True},
                f"operator_api 导入失败或返回异常: {result!r}")


def test_deliver_raises_when_queue_put_fails():
    """结果交付失败必须抛出去，不能被静默吞掉。

    场景：沙箱子进程 RLIMIT_AS 用满 → 首次 ``queue.put()``
    启动 feeder 线程失败（``can't start new thread``）→ ``except`` 分支里第二次
    ``put`` 发现线程对象已存在、只把路径塞进缓冲区就正常返回 → 子进程
    **exitcode=0** 却什么也没交付，父进程只能报 ``subprocess crashed (exitcode=0)``，
    对外落成 ``RetCode.operator.split.error``（「切分算子执行失败」）。
    """
    from ingestion.utility.operator_zip_action import _deliver

    class _BrokenQueue:
        def put(self, payload):
            raise RuntimeError("can't start new thread")

    try:
        _deliver(_BrokenQueue(), "/tmp/x.json", None)
    except RuntimeError as e:
        _assert("can't start new thread" in str(e), f"异常应原样抛出: {e!r}")
    else:
        raise AssertionError("交付失败被静默吞掉了（子进程会以 exitcode=0 空手退出）")

    delivered = []

    class _OkQueue:
        def put(self, payload):
            delivered.append(payload)

    _deliver(_OkQueue(), "/tmp/ok.json", None)
    _assert(delivered == ["/tmp/ok.json"], f"正常交付路径被改坏: {delivered!r}")


def test_parser_imports_are_lazy():
    """导入解析器入口不得连带导入 numpy / openpyxl。

    这是**沙箱内存配额**的判据，不只是启动速度：``openpyxl`` 在导入时会
    ``import numpy``，而 numpy 的 OpenBLAS 按 CPU 核数预分配缓冲区 —— 8 核实测
    子进程 VmSize 从 27MB 顶到 434MB（其中 numpy 占 361MB），RLIMIT_AS（基线+500MB）
    里留给文档的只剩几十 MB，稍大的 PDF 就会在结果交付处失败。
    实测换成按需导入后：导入后 434MB → 27MB，同一份 PDF 解析完 514MB → 143MB。
    """
    code = (
        "import sys\n"
        "import parsing.parsers.strategies as m\n"
        "assert 'numpy' not in sys.modules, 'numpy 在导入解析器入口时就被拉起来了'\n"
        "assert 'openpyxl' not in sys.modules, 'openpyxl 在导入解析器入口时就被拉起来了'\n"
        "assert 'pdf' in m.FILE_PARSE_STRATEGIES, '策略表被改坏'\n"
        "assert 'docx' in m.FILE_PARSE_STRATEGIES, '策略表被改坏'\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = _PROJECT_ROOT
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    _assert(r.returncode == 0,
            f"解析器导入不再是惰性的: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}")


def _write_synthetic_pdf(path: str, pages: int = 10, lines_per_page: int = 60,
                         line_len: int = 88) -> None:
    """写一份只含 ASCII 文本的多页 PDF（Helvetica），不依赖 reportlab（镜像里没有）。

    **每行带唯一编号**：切分前的 ``_reconstruct_text`` 会按 ``content_expand``
    去重，重复行会被折叠成一个切片 —— 那样测到的就不是真实内存占用了。
    """
    filler = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    objs, kids = {}, []
    for i in range(pages):
        page_num, content_num = 4 + i * 2, 5 + i * 2
        kids.append(page_num)
        body = []
        for n in range(lines_per_page):
            head = f"SIGNAL TRACE GUIDE p{i + 1:05d} l{n + 1:03d} "
            line = (head + filler * 10)[:line_len]
            body.append(f"1 0 0 1 40 {800 - n * 13} Tm ({line}) Tj")
        stream = "BT /F1 9 Tf\n" + "\n".join(body) + "\nET"
        objs[content_num] = (
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode())
        objs[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_num} 0 R >>").encode()
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = ("<< /Type /Pages /Kids [" + " ".join(f"{k} 0 R" for k in kids) +
               f"] /Count {len(kids)} >>").encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref_at = len(out)
    total = max(objs) + 1
    out += f"xref\n0 {total}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, total):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    with open(path, "wb") as f:
        f.write(out)


def test_system_operator_split_realistic_pdf_fits_quota():
    """真实沙箱路径 + 接近真实大小的 PDF，在**收紧的配额**下必须切分成功。

    这是「2MB PDF 解析失败」的端到端护栏。失败原因不是文档太大：
    解析器入口在模块顶层 import 全部 8 种格式，``openpyxl`` 连带 ``import numpy``，
    OpenBLAS 按 8 核预分配 —— **光导入就吃掉 434MB**，519MB 上限里只剩 85MB。
    文档稍大就会在 ``queue.put()`` 处 ``can't start new thread``，而且被 except
    吞成 exitcode=0，对外只剩一句「切分算子执行失败」。

    为什么要单独一条：``test_split.py`` 直接调 ``load_corpus_file``（同进程、无沙箱、
    无 RLIMIT），本文件其余用例只喂 dummy 算子 —— 「真实路径 + 真实尺寸文档」
    这个组合没有其他覆盖，所以这类问题会一路漏到线上。

    判据用收紧的配额而不是线上配额：取 384MB，峰值约 210MB（留 40% 余量）。
    注意这条守的是**组合**：只退回「懒加载」而保留 OPENBLAS_NUM_THREADS=1 时，
    导入约 154MB，本用例仍会通过；只有两半都退回去（顶层导入 + 线程数不设限，
    导入 434MB）才会失败。
    两半各自还有独立的秒级守卫：``test_parser_imports_are_lazy`` 守懒加载，
    ``test_thread_env_survives_sanitize`` 守线程数白名单。

    必须在**独立子进程**里跑：forkserver 进程在第一次起沙箱时就把父进程的环境变量
    拷贝走了，之后在父进程里改 ``OPERATOR_MEMORY_LIMIT_MB`` 不会传给子进程。
    """
    from parsing.common.pathutil import get_workdir

    operator_main = os.path.join(_PROJECT_ROOT, "operators", "text_split", "main.py")
    env = dict(os.environ)
    env["PYTHONPATH"] = _PROJECT_ROOT
    env["OPERATOR_MEMORY_LIMIT_MB"] = "384"

    with tempfile.TemporaryDirectory() as d:
        pdf_path = os.path.join(d, "quota_probe.pdf")
        _write_synthetic_pdf(pdf_path, pages=10)
        code = (
            "from ingestion.utility.operator_zip_action import execute_operator_module\n"
            f"docs = execute_operator_module({operator_main!r}, 'file_split_with_chunk',\n"
            f"                               file_path={pdf_path!r},\n"
            "                               maxWordCount=512, overlap=128)\n"
            "print('CHUNKS', len(docs))\n"
            "print('EMPTY', sum(1 for doc in docs if not doc.page_content))\n"
        )
        try:
            r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                               text=True, env=env, timeout=300)
        finally:
            # 解析产物落在服务根的 temp 下，测完清掉，别留垃圾
            for leftover in ("pdf/quota_probe_md", "corpus_split/quota_probe"):
                path = os.path.join(get_workdir(), "temp", *leftover.split("/"))
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)

    detail = (r.stderr.strip().splitlines() or [""])[-1]
    _assert(r.returncode == 0,
            f"真实尺寸 PDF 在 384MB 配额下切分失败（exit={r.returncode}）: {detail}")
    chunks = int(r.stdout.split("CHUNKS")[1].split()[0])
    empty = int(r.stdout.split("EMPTY")[1].split()[0])
    _assert(chunks >= 80, f"切分结果异常少: {chunks}")
    _assert(empty == 0, f"存在 {empty} 个空切片")


def test_thread_env_survives_sanitize():
    """BLAS/MKL 的线程数变量必须能在沙箱子进程里活下来。

    这几项是**内存配额**的一部分，不只是性能旋钮：numpy 的 OpenBLAS 按线程数
    预分配缓冲区，8 核实测 VmSize +280MB（361MB → 81MB）。而
    ``sanitize_environment()`` 会把不在白名单里的变量全部剥掉 —— 一旦被剥，
    ``deploy/.env`` 里配的 OPENBLAS_NUM_THREADS=1 就静默失效、退回按核数分配。
    """
    from ingestion.utility import sandbox_runtime

    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        _assert(sandbox_runtime._is_allowed(name),
                f"{name} 会被 sanitize_environment 剥掉，线程数上限静默失效")
    # 放行这几项不能顺手把数据侧凭据也放进来
    _assert(not sandbox_runtime._is_allowed("RKB_DB_PASSWORD"),
            "RKB_DB_* 不应被放行")


def main():
    tests = [
        test_dangerous_operator_rejected,
        test_dangerous_bypasses_rejected,
        test_dead_loop_timeout,
        test_oversized_result_rejected,
        test_json_roundtrip,
        test_non_json_result_rejected,
        test_file_parse_str_return,
        test_memory_limit_relative_to_baseline,
        test_child_context_is_forkserver,
        test_child_does_not_reexecute_entry_module,
        test_entry_module_imports_are_guarded,
        test_child_environment_is_whitelisted,
        test_system_operator_timeout_returns_instead_of_hanging,
        test_operator_can_import_operator_api,
        test_deliver_raises_when_queue_put_fails,
        test_parser_imports_are_lazy,
        test_thread_env_survives_sanitize,
        test_system_operator_split_realistic_pdf_fits_quota,
    ]
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"PASS {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
