"""岗位互不依赖 —— 没有横跨全局的公共库。

每个 skill / agent 自带 scripts/，脚本只 import 标准库、第三方库、以及同目录
兄弟模块。跨目录 import 会重新长出共享库，那正是本次重构要消灭的东西。

岗位之间需要协作时走进程边界（Bash 调对方的脚本），不走 Python import。

例外：
- workflow_runtime（skills/state-machine/scripts/workflow_runtime.py）由 hook 链
  通过 sys.path 共享，避免双副本漂移。
- envelope：各 skill 各自本地副本，drift 由各 skill 自负责。
- state_rules：hooks/state_rules.py 是 hooks 视角的独立副本，由
  tests/skills/state-machine/test_state_rules_sync.py 校验与 state-machine
  单点一致。

其它岗位**仍不**允许跨目录 import。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

THIRD_PARTY = {"yaml", "pytest"}
STDLIB_HINT = {
    "__future__", "argparse", "ast", "collections", "contextlib", "copy",
    "dataclasses", "datetime", "difflib", "enum", "fcntl", "fnmatch",
    "functools", "hashlib", "importlib", "io", "itertools", "json", "os",
    "pathlib", "re", "shlex", "shutil", "signal", "subprocess", "sys",
    "tarfile", "tempfile", "textwrap", "time", "types", "typing",
    "unicodedata", "uuid",
}
# workflow_runtime 单副本位于 state-machine/scripts/，hooks 链通过 sys.path
# 共享导入，避免双副本漂移。
# envelope / state_rules 已分别走各 skill 本地副本。
# 其它岗位继续走进程边界。
SHARED_MODULES: set[str] = {"workflow_runtime"}


def role_dirs() -> list[Path]:
    """所有岗位脚本目录。"""
    dirs = [PLUGIN_ROOT / "hooks"]
    for base in ("skills", "agents"):
        for scripts in (PLUGIN_ROOT / base).glob("*/scripts"):
            dirs.append(scripts)
    return sorted(d for d in dirs if d.is_dir())


def python_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.glob("*.py") if "__pycache__" not in p.parts
    )


def imported_roots(path: Path) -> set[str]:
    """抽出该文件 import 的顶层模块名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                roots.add(f"<relative level {node.level}>")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


ALL_SCRIPTS = [
    (d, f) for d in role_dirs() for f in python_files(d)
]


def _label(param):
    directory, file = param
    return f"{directory.parent.name}/{file.name}"


@pytest.mark.parametrize(
    "directory,path", ALL_SCRIPTS, ids=[_label(p) for p in ALL_SCRIPTS]
)
def test_script_imports_stay_local(directory: Path, path: Path):
    """脚本只能 import 标准库、白名单第三方库、或同目录兄弟模块。

    例外：SHARED_MODULES 允许 hook 共享 workflow_runtime（单副本避免双副本漂移）。
    """
    siblings = {p.stem for p in python_files(directory)}
    allowed = STDLIB_HINT | THIRD_PARTY | SHARED_MODULES | siblings

    offenders = sorted(imported_roots(path) - allowed)
    assert not offenders, (
        f"{path.relative_to(PLUGIN_ROOT)} 依赖了目录外的模块: {offenders}\n"
        f"岗位间协作应走进程边界（Bash 调对方脚本），不走 Python import。"
    )


@pytest.mark.parametrize(
    "directory,path", ALL_SCRIPTS, ids=[_label(p) for p in ALL_SCRIPTS]
)
def test_no_relative_imports(directory: Path, path: Path):
    """脚本目录不是 Python 包，相对 import 会在独立进程里失败。"""
    relatives = [r for r in imported_roots(path) if r.startswith("<relative")]
    assert not relatives, f"{path.relative_to(PLUGIN_ROOT)} 用了相对 import"


def test_no_shared_library_directory():
    """不存在横跨全局的公共代码目录。"""
    for name in ("lib", "common", "shared", "utils", "core"):
        assert not (PLUGIN_ROOT / name).is_dir(), f"发现公共库目录: {name}/"


def test_every_capability_skill_carries_own_scripts():
    """声明要跑脚本的 skill 必须自带 scripts/，不借用别人的。"""
    for skill_md in (PLUGIN_ROOT / "skills").glob("*/SKILL.md"):
        body = skill_md.read_text(encoding="utf-8")
        if "${CLAUDE_SKILL_DIR}/scripts" not in body:
            continue
        assert (skill_md.parent / "scripts").is_dir(), (
            f"{skill_md.parent.name} 引用了 CLAUDE_SKILL_DIR/scripts 但无该目录"
        )


def test_hooks_are_self_contained():
    """hooks 是不变量强制器，依赖目录外模块会让它因加载失败而失效。

    例外：hooks 可通过 sys.path 共享 workflow_runtime。其它岗位不享受此豁免。
    """
    hooks_dir = PLUGIN_ROOT / "hooks"
    siblings = {p.stem for p in python_files(hooks_dir)}
    for path in python_files(hooks_dir):
        offenders = sorted(
            imported_roots(path)
            - (STDLIB_HINT | THIRD_PARTY | SHARED_MODULES | siblings)
        )
        assert not offenders, f"{path.name} 依赖目录外模块: {offenders}"
