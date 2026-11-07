"""服务根 conftest：全局测试设施。

当前只做一件事：**可选的「已移除第三方库」导入阻断器**。

为什么需要它
------------
「把某个第三方索引库从编排层摘掉」的迁移里，只要库还装在环境里，
「替换已接线」与「替换根本没被调用」是同一种绿 —— 中间态的每次提交都不可证伪。
打开阻断器后，任何一处残留的 `import llama_index` 都会在收集期直接炸，
把"漏改一个文件"变成一条明确的红色用例。

为什么代码里还留着那个包名
--------------------------
阻断器必须**按真实模块名**匹配才能生效 —— 这是外部包的名字，不是本仓标识。
它只出现在下面的匹配条件里，包本身已不在任何依赖清单中。

用法
----
    RAG_FORBID_REMOVED_LIB=1 python -m pytest -q        # 要求全绿
    python -m pytest -q                                  # 不设变量：不阻断（默认）

迁移完成、库从依赖里摘掉之后，这个开关留着无害：不设变量即零行为。
与 `tools/verify/verify-baseline-fingerprint.py` 里的同名开关是**同一件事的两处实现**
（那边是独立脚本，跑在容器里，不能 import 本文件）。
"""
from __future__ import annotations

import os
import sys
from importlib.abc import MetaPathFinder

import pytest

_TRUTHY = {'1', 'true', 'yes', 'on'}
_REMOVED_PACKAGE = 'llama_index'


class _RemovedLibBlocker(MetaPathFinder):
    """命中已移除的包（及其子模块）即抛 ModuleNotFoundError（信息里点名开关）。"""

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if fullname == _REMOVED_PACKAGE or fullname.startswith(_REMOVED_PACKAGE + '.'):
            raise ModuleNotFoundError(
                f'RAG_FORBID_REMOVED_LIB=1：禁止 import {fullname} —— '
                '编排层不应再依赖该第三方库（见 tools/verify/verify-baseline-fingerprint.py 的基线）'
            )
        return None


def _install_blocker() -> None:
    if os.environ.get('RAG_FORBID_REMOVED_LIB', '').strip().lower() not in _TRUTHY:
        return
    if any(isinstance(f, _RemovedLibBlocker) for f in sys.meta_path):
        return
    sys.meta_path.insert(0, _RemovedLibBlocker())


_install_blocker()


@pytest.fixture(autouse=True)
def _default_auth_mode_none(monkeypatch):
    """单测默认按 ``AUTH_MODE=none`` 跑（鉴权用例自己显式设置）。

    生产默认值是 ``local``；单测若全部继承 ``local``，大量与鉴权无关的用例会被
    401 挡住，反而掩盖真正的回归。这里只在环境未显式设置时兜底。
    """
    if 'AUTH_MODE' not in os.environ:
        monkeypatch.setenv('AUTH_MODE', 'none')
