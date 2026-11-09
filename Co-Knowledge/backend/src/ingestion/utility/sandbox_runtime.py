"""沙箱运行时的公共装配：multiprocessing 上下文、预载、环境白名单。

## 为什么单独成模块

两条执行路径（自定义算子 / 系统算子）需要统一的进程管理：

* **A 路**（自定义算子）``self_operator.execute_function_in_sandbox`` —— spawn + RLIMIT
  + 超时 + AST + 去 pickle，比较完整；
* **B 路**（系统算子）``operator_zip_action.execute_operator_module`` —— 默认 **fork**、
  无 RLIMIT、无超时、无 AST。

两条路都在**同一进程**里发起，公共部分收在这里，避免分叉。

## 关键一：forkserver 必须显式排除 ``'__main__'``

``spawn`` 与 ``forkserver`` **默认都会执行入口模块**：

* ``multiprocessing/spawn.py``：``runpy.run_path(main_path, run_name="__mp_main__")``
* ``multiprocessing/forkserver.py``：``ForkServer.__init__`` 的
  ``self._preload_modules = ['__main__']``，server 侧
  ``if '__main__' in preload and main_path is not None: spawn.import_main_path(...)``

RKB 的 ``main.py`` **不能顶层** ``from app import app`` —— 那会让 3 个常驻线程
（语料队列消费者、每日清理与每 5 分钟删 ``file_track`` 过期文件的调度器）在**每个沙箱
子进程里各起一份**：重复消费语料队列、删掉正在被读取的文件。

⚠️ **摘掉预载拦不住子进程**。``spawn.prepare()`` 里还有一条
``_fixup_main_from_path → runpy.run_path(main.py)``，它对每个子进程都会跑，
与 ``_preload_modules`` 无关 —— 真实现场就是子进程里重新执行了 ``main.py``、
连带建起日志 handler 并在 ``_backup_remains`` 的竞态里崩掉（exitcode=1）。
所以真正管用的是 **``main.py`` 里的 ``if __name__ == '__main__'`` 守卫**
（``uvicorn`` / ``app`` 的 import 都放在守卫内）。这里的预载排除仍然保留：
它省掉 forkserver 侧的 ``import_main_path``，属于另一层。

## 关键二：forkserver 让「基线 + 配额」重新成立

原 A 路用 spawn，子进程要重新导入应用入口，基线 VmSize 高达数百 MB（注释实测 551MB），
于是 ``上限 = 子进程自测基线 + 配额`` 里的「基线」变得又大又不可预测。
改成 forkserver 后，子进程从**只预载了两个模块**的 server fork 出来，基线小且确定 ——
子进程在入口处自测基线重新变得有意义（这也是为什么不再需要「父进程注入绝对上限」）。
"""

import multiprocessing
import os
import sys

#: forkserver 进程预载的模块（**刻意不含 '__main__'**，见模块 docstring）。
#: 预载它们是为了让子进程 fork 出来时就已具备执行算子所需的导入，省掉每子进程的重导入。
PRELOAD_MODULES = (
    'ingestion.utility.self_operator',
    'ingestion.service.operator.dangerous_function_visitor',
)

_configured = False


def configure_multiprocessing():
    """配置 forkserver 预载。幂等；进程生命周期内只需生效一次。"""
    global _configured
    if _configured:
        return
    multiprocessing.set_forkserver_preload(list(PRELOAD_MODULES))
    _configured = True


def sandbox_context():
    """沙箱子进程用的 multiprocessing 上下文（forkserver）。"""
    configure_multiprocessing()
    return multiprocessing.get_context('forkserver')


# ---------------------------------------------------------------------------
# 算子导入根
# ---------------------------------------------------------------------------
#: 沙箱只把 ``src/`` 放进 ``sys.path``，算子插件只能 import 标准库与 ``operator_api.*``。
_import_root_ready = False


def ensure_import_root():
    """Ensure ``src/`` is importable inside the sandbox process.

    Custom plugins import the public interface via ``operator_api.*``.  The old
    top-level packages (``client`` / ``utility`` / ``service`` / ``split``) are
    not added to ``sys.path``; plugins using them are rejected at import time
    with ``operator_plugin_incompatible``.
    """
    global _import_root_ready
    if _import_root_ready:
        return
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import_root = os.path.dirname(package_root)
    if import_root not in sys.path:
        sys.path.append(import_root)
    _import_root_ready = True


# ---------------------------------------------------------------------------
# 子进程环境变量白名单
# ---------------------------------------------------------------------------
#: 原样保留的变量（不保留会把 Python 自身跑坏）
#:
#: ``*_NUM_THREADS`` 这几项是**内存配额**的一部分，不只是性能旋钮：numpy 的
#: OpenBLAS/MKL 按线程数预分配缓冲区，8 核下 VmSize **+280MB**（361MB → 81MB）。
#: 沙箱子进程有 ``RLIMIT_AS``，这笔账会直接吃掉算子的可用额度 ——
#: 「PDF 切分失败」就是这么触发的。放在白名单里，``deploy/.env`` 配的值才不会
#: 被 ``sanitize_environment()`` 剥掉（剥掉会静默退回按核数分配）。
_KEEP_ENV = frozenset({
    'PATH', 'PYTHONPATH', 'PYTHONHASHSEED', 'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE',
    'HOME', 'TMPDIR', 'TMP', 'TEMP', 'TZ', 'LANG', 'LC_ALL', 'LC_CTYPE',
    'LD_LIBRARY_PATH', 'OPERATOR_ENV_ALLOWLIST',
    'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
})

#: 算子**出站**需要的配置前缀，整前缀放行。
#:
#: 注意这里**包含其中的 API key**：抽图算子要拿它去调模型网关，属算子正常工作所需。
#: 与之相对，下面 _DENY_PREFIXES 里的是**知识库数据侧**的凭据 —— 算子从不合法地需要它们，
#: 而这正是合并后要守的那条线（合并前 A 路只握 PG、B 路连 PG 都不碰；合并后与 RKB 同进程，
#: 必须靠白名单把数据凭据挡在子进程之外）。
_KEEP_ENV_PREFIXES = (
    'MODEL_GATEWAY_',       # 地址/路径/推理开关/网关 key
    'EMBEDDING_',           # 模型名与维度
    'GENERATION_',          # 生成端点与 key
    'RKB_RERANK_',
    'OPERATOR_',            # 沙箱自身的旋钮
)

#: 显式拒绝的变量名前缀 —— 知识库数据侧的凭据与库连信息。
_DENY_PREFIXES = (
    'RKB_DB_',              # 业务库连接与口令
    'RKB_ES_',              # OpenSearch 连接与口令（变量名沿用 RKB_ES_*）
    'RKB_SECRET',           # 静态加密密钥
    'RKB_ADMIN_',           # 管理员账号
    'RKB_AGENT_KEY_PEPPER',  # Agent Key 摘要 pepper
    'POSTGRES_',
    'DB_',
    'AUTH_',
)


def _env_allowlist() -> set:
    """``OPERATOR_ENV_ALLOWLIST``（逗号分隔）—— 运维逃生口。"""
    raw = os.environ.get('OPERATOR_ENV_ALLOWLIST', '')
    return {item.strip() for item in raw.split(',') if item.strip()}


def _is_allowed(name: str) -> bool:
    """判定单个变量是否保留。顺序即优先级，见各分支注释。"""
    if name in _env_allowlist():
        return True                      # 运维显式放行，最高优先级
    if any(name.startswith(bad) for bad in _DENY_PREFIXES):
        return False                     # 数据侧凭据：无论如何不放
    if name.startswith(_KEEP_ENV_PREFIXES):
        return True                      # 算子出站配置
    return name in _KEEP_ENV             # Python 自身的基础环境


def sanitize_environment():
    """把当前（子）进程的环境变量收敛到白名单。**在子进程入口第一件事调用**。

    为什么必须在导入算子模块**之前**：``operator_api.llm``（底层
    ``model/operator_client.py``）是在**模块导入时**读 ``MODEL_GATEWAY_*``
    的 —— 顺序错了会静默丢配置（算子退到默认端点）。

    返回被剔除的名字列表，便于测试断言与排查。
    """
    removed = []
    for name in list(os.environ):
        if not _is_allowed(name):
            removed.append(name)
            os.environ.pop(name, None)
    return removed
