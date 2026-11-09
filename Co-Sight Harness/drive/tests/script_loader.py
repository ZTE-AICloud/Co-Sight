"""按路径加载岗位脚本 —— 测试基础设施。

生产中每个脚本以独立进程运行（各自 cwd，同目录 import 自然解析）。测试进程要
同时加载多个岗位的脚本，而各岗位都有同名 envelope.py，故隔离加载：exec 前腾空
裸名、exec 后原样还回，两个方向都不留污染。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# 岗位别名 → 脚本目录
ROLES: dict[str, str] = {
    "state-machine": "skills/state-machine/scripts",
    "drive": "skills/drive/scripts",
    "startup": "skills/startup/scripts",
    "wave-scheduling": "skills/wave-scheduling/scripts",
    "context-packaging": "skills/context-packaging/scripts",
    "wave-barrier": "skills/wave-barrier/scripts",
    "hooks": "hooks",
    "drive-record": "skills/drive-record/scripts",
    "dag-runtime": "skills/dag-runtime/scripts",
}


def scripts_dir(role: str) -> Path:
    if role not in ROLES:
        raise KeyError(f"未知岗位 {role!r}，可选: {sorted(ROLES)}")
    return PLUGIN_ROOT / ROLES[role]


def load(role: str, script: str) -> ModuleType:
    """加载某岗位的脚本。同一 (role, script) 复用已加载模块。"""
    directory = scripts_dir(role)
    path = directory / f"{script}.py"
    if not path.is_file():
        raise FileNotFoundError(f"脚本不存在: {path}")

    mod_name = f"_role_{role.replace('-', '_')}_{script}"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module

    siblings = {p.stem for p in directory.glob("*.py")}
    saved = {n: sys.modules.pop(n) for n in siblings if n in sys.modules}
    sys.path.insert(0, str(directory))
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    finally:
        try:
            sys.path.remove(str(directory))
        except ValueError:
            pass
        for name in siblings:
            sys.modules.pop(name, None)
        sys.modules.update(saved)
    return module
