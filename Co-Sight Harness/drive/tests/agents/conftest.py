"""agent scripts 测试的模块加载 — 各 agent 的 scripts/ 是独立脚本目录，非包。

agent 履职时以 `python3 <scripts_dir>/x.py` 执行，各自独立进程、独立 cwd，
同目录 import（如 envelope）自然解析且互不干扰。测试进程要同时加载多个
agent 的脚本，按文件路径隔离加载以复现该独立性（各 agent 的 envelope 同名
但互不覆盖）。

agent 名 → scripts 目录的映射写在 AGENT_SCRIPTS_DIRS，未来新增 agent 的
scripts 时必须同步注册。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent

# agent 名 → scripts 目录。脚本执行 cwd = scripts 目录本身。
AGENT_SCRIPTS_DIRS: dict[str, Path] = {
    "wave-scheduling": PLUGIN_ROOT / "skills" / "wave-scheduling" / "scripts",
    "context-packaging": PLUGIN_ROOT / "skills" / "context-packaging" / "scripts",
    "wave-barrier": PLUGIN_ROOT / "skills" / "wave-barrier" / "scripts",
}


def load_agent_script(agent: str, script: str) -> ModuleType:
    """按文件路径加载某 agent 的脚本，附带其同目录依赖。

    Args:
        agent: 注册在 AGENT_SCRIPTS_DIRS 的 agent 名（如 "topo_sort"）
        script: 脚本文件名去掉 .py（如 "topo_sort"）

    Raises:
        KeyError: agent 名未注册
        FileNotFoundError: 脚本不存在
    """
    if agent not in AGENT_SCRIPTS_DIRS:
        raise KeyError(f"agent {agent!r} 未注册 scripts 目录")
    scripts_dir = AGENT_SCRIPTS_DIRS[agent]
    path = scripts_dir / f"{script}.py"
    mod_name = f"_agent_{agent.replace('-', '_')}_{script}"

    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module

    # 各 agent 的 scripts/ 都有同名 envelope.py。exec 前腾空这些裸名、exec 后
    # 原样还回，保证本 agent 加载到自己的版本，也不遮蔽其他 agent 的。
    siblings = {p.stem for p in scripts_dir.glob("*.py")}
    saved = {n: sys.modules.pop(n) for n in siblings if n in sys.modules}

    sys.path.insert(0, str(scripts_dir))
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass
        for n in siblings:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
    return module
