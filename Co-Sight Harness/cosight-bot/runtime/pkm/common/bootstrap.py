#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能脚本启动引导：.env 加载 + 运行环境自检（preflight）。

每个技能 CLI 入口在最前面调用：

    from common.bootstrap import bootstrap
    bootstrap()   # 加载 data/.env；环境未就绪时打印 JSON hint 并 exit 3

preflight 失败语义（与 SKILL.md 约定配套）：
    输出 {"hint": "please_run_install", "reason": ...}，退出码 3。
    Claude 见此即引导/代为执行 scripts/install.py，不得绕过。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from .port_resolver import cosight_state_root
from .logging_setup import get_logger, log_event, setup_logging

# 关键第三方依赖（import 名）：缺失即视为未安装
_REQUIRED_MODULES = [
    "llama_index",
    "lancedb",
    "filelock",
    "requests",
    "pypdfium2",  # PDF 渲染/抽字（PDFium 绑定，BSD-3-Clause OR Apache-2.0）
    "pdfplumber",  # PDF 表格检测（MIT）
    "openpyxl",
    "pptx",        # python-pptx
    "docx",        # python-docx
    "pandas",
]

_INSTALL_HINT = "please_run_install"


def runtime_root() -> Path:
    """本侧 runtime/ 目录（PKM 内核，位于 <插件根>/runtime/pkm/）。"""
    return Path(__file__).resolve().parents[1]


def ensure_venv() -> None:
    """若数据根下存在 .venv-pkm 且当前解释器不在其中，重入该 venv 的 python。

    install.py 把 PKM 侧第三方依赖装进 <数据根>/.venv-pkm（不污染系统
    python；与 soc 侧 .venv-soc 相互隔离）；技能 CLI 以任意 python 启动后，
    本函数在导入第三方依赖前 os.execv 重入，对用户透明。已是 venv 解释器
    （sys.prefix 命中）或 venv 不存在时直接返回。
    """
    venv_dir = cosight_state_root() / ".venv-pkm"
    if not venv_dir.is_dir():
        return
    try:
        if Path(sys.prefix).resolve() == venv_dir.resolve():
            return
    except OSError:
        return
    python_bin = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python_bin.is_file():
        return
    os.execv(str(python_bin), [str(python_bin), *sys.argv])


def load_env() -> None:
    """加载 <数据目录>/.env 到 os.environ（已存在的变量不覆盖，shell export 优先）。

    简易 KEY=VALUE 解析（不引 python-dotenv）：忽略注释/空行，值可带引号。
    重复 key 后者优先（允许文件尾部追加覆盖前部空占位）；空值不写入，
    避免模板里的空占位行遮蔽后追加的真实值。
    """
    env_file = cosight_state_root() / ".env"
    if not env_file.is_file():
        return
    try:
        parsed: dict[str, str] = {}
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                parsed[key] = value
        for key, value in parsed.items():
            if value and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def _requirements_sha256() -> str:
    req = runtime_root() / "requirements.txt"
    if not req.is_file():
        return ""
    return hashlib.sha256(req.read_bytes()).hexdigest()


def preflight() -> tuple[bool, str]:
    """运行环境自检。返回 (ok, reason)。"""
    missing = []
    for mod in _REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return False, f"missing python modules: {', '.join(missing)}"

    state_root = cosight_state_root()
    if not state_root.is_dir():
        return False, f"data directory not initialized: {state_root}"

    stamp_file = state_root / ".install-stamp-pkm"
    current = _requirements_sha256()
    if current:
        if not stamp_file.is_file():
            return False, "install stamp missing (run scripts/install.py)"
        recorded = stamp_file.read_text(encoding="utf-8").strip()
        if recorded != current:
            return False, "requirements.txt changed since install (re-run scripts/install.py)"

    return True, ""


def preflight_or_exit() -> None:
    """自检失败时输出 JSON hint 并 exit 3（SKILL.md 约定：引导执行 install.py）。"""
    ok, reason = preflight()
    if not ok:
        print(json.dumps({"hint": _INSTALL_HINT, "reason": reason}, ensure_ascii=False))
        sys.exit(3)


def bootstrap(*, skip_preflight: bool = False) -> None:
    """技能入口统一引导：重入 venv → 加载 .env → 配置日志 → 自检。"""
    ensure_venv()
    load_env()
    setup_logging()
    log_event(
        get_logger("bootstrap"),
        "bootstrap",
        python=sys.version.split()[0],
        data_root=str(cosight_state_root()),
        log_level=os.environ.get("COSIGHTBOT_LOG_LEVEL", "INFO"),
    )
    if not skip_preflight:
        preflight_or_exit()
