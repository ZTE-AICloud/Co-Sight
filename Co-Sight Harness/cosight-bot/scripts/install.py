#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CoSightBot CC 插件首装脚本（幂等、非交互式）。

功能：
  1. 检查 python（>=3.10）；
  2. 为 PKM / SOC 两侧内核分别创建独立虚拟环境
     （<数据根>/.venv-pkm、<数据根>/.venv-soc，互不污染）；
  3. 安装各自 runtime/<侧>/requirements.txt；
  4. 初始化数据根目录结构（PKM 资料索引区 + SOC 知识库区 + 日志）；
  5. 生成数据根/.env（已存在则不覆盖；模板为 scripts/.env.template）；
  5.5 按平台探测 CA 证书包并写入 SSL_CERT_FILE（幂等，用户已配则不动）；
  6. 写入按侧命名的 .install-stamp-<侧>（对应 requirements.txt 的 sha256，
     preflight 据此判定依赖是否漂移）。

数据根目录解析链（与 runtime/common/port_resolver.py 一致）：
  COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > ~/.claude/plugins/data/cosightbot

非交互式：可能被 Claude 在会话中代为执行（无 stdin）。环境变量的收集走对话——
装完由 Claude 询问用户并代为写入 .env，或用户自行编辑。

技能 CLI（material_cli / retrieve_cli / kb_cli 等）启动时自动重入对应 venv 的
解释器，对用户透明；用任意 python 调用技能脚本即可。

用法：python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PKM_RUNTIME = PLUGIN_ROOT / "runtime" / "pkm"
SOC_RUNTIME = PLUGIN_ROOT / "runtime" / "soc"
ENV_TEMPLATE_FILE = PLUGIN_ROOT / "scripts" / ".env.template"

# 数据根解析链：与 runtime/common/port_resolver.py 保持一致
_PLUGIN_DATA_DEFAULT = Path.home() / ".claude" / "plugins" / "data" / "cosightbot"


def state_root() -> Path:
    """数据根目录：COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > 官方默认位置。"""
    for env_key in ("COSIGHTBOT_HOME", "CLAUDE_PLUGIN_DATA"):
        value = (os.environ.get(env_key) or "").strip()
        if value:
            return Path(value).expanduser()
    return _PLUGIN_DATA_DEFAULT


# 各侧 venv 与 stamp 命名（与 runtime/common/bootstrap.py 保持一致）
STACKS = [
    # (侧名, runtime 目录, venv 目录名, stamp 文件名)
    ("pkm", PKM_RUNTIME, ".venv-pkm", ".install-stamp-pkm"),
    ("soc", SOC_RUNTIME, ".venv-soc", ".install-stamp-soc"),
]

DATA_SUBDIRS = [
    # PKM 侧：资料索引
    "workspace-main/llamaindex_data/pre-processed",
    "workspace-main/llamaindex_data/lancedb",
    "workspace-main/llamaindex_data/inbox",
    "workspace-main/llamaindex_data/upload_files",
    # soc 侧：标书知识库与应答产物
    "workspace-soc",
    "canvas/deep-search",
    # 公共
    "logs",
]

# CA 证书包候选路径（Linux 按发行版惯例排序，取第一个存在的）
_CA_BUNDLE_CANDIDATES = [
    "/etc/pki/tls/certs/ca-bundle.crt",                  # RHEL/CentOS/openEuler 等 EL 系
    "/etc/ssl/certs/ca-certificates.crt",                # Debian/Ubuntu 系
    "/etc/ssl/ca-bundle.pem",                            # openSUSE 系
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", # EL ca-trust 直通
]


def _detect_ca_bundle(venv_python: Path) -> str:
    """按平台探测 CA 证书包路径；探测失败返回空串。

    背景：python-build-standalone 系的 Python 在 EL 系 Linux 上默认 CA 路径
    （/etc/ssl/cert.pem）不存在，任何 https 调用都会 CERTIFICATE_VERIFY_FAILED；
    Windows/macOS 的官方 Python 构建默认也不读系统 CA。显式写 SSL_CERT_FILE
    后，技能进程（bootstrap 加载 .env → ssl 读该变量）即可稳定验签。

    Linux 直接探测发行版 bundle；其余平台（Windows/macOS）统一取 venv 内
    certifi 的 cacert.pem（requirements 的 requests 依赖链保证 certifi 已装）。
    """
    if sys.platform.startswith("linux"):
        for cand in _CA_BUNDLE_CANDIDATES:
            if os.path.isfile(cand):
                return cand
        return ""
    cp = subprocess.run(
        [str(venv_python), "-c", "import certifi; print(certifi.where())"],
        capture_output=True, text=True,
    )
    path = cp.stdout.strip() if cp.returncode == 0 else ""
    return path if path and os.path.isfile(path) else ""


def _ensure_ssl_cert_file(env_file: Path, ca_bundle: str) -> None:
    """把 SSL_CERT_FILE 写入数据根/.env（幂等；用户已配置则不动）。"""
    content = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, _ = line.partition("=")
        if key.strip() == "SSL_CERT_FILE":
            print("[install] .env already has SSL_CERT_FILE, keeping it")
            return
    if not ca_bundle:
        print("[install] WARN: no CA bundle detected; if https calls fail with "
              "CERTIFICATE_VERIFY_FAILED, set SSL_CERT_FILE in the data-root .env manually")
        return
    with env_file.open("a", encoding="utf-8") as f:
        f.write("\n# --- CA bundle (auto-detected by install.py; needed for https endpoint verification) ---\n")
        f.write(f"SSL_CERT_FILE={ca_bundle}\n")
    print(f"[install] SSL_CERT_FILE written to data-root .env: {ca_bundle}")


def _setup_stack(stack: str, runtime_dir: Path, venv_name: str, stamp_name: str) -> int:
    """为单侧内核创建 venv 并安装依赖，写 install stamp。返回退出码。"""
    root = state_root()
    venv_dir = root / venv_name
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    if not venv_python.is_file():
        print(f"[install] creating virtual environment: {venv_dir} ...")
        cp = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)])
        if cp.returncode != 0 or not venv_python.is_file():
            print("[install] ERROR: venv creation failed (python3-venv installed?)")
            return 1

    requirements = runtime_dir / "requirements.txt"
    print(f"[install] installing {requirements.relative_to(PLUGIN_ROOT)} into {venv_name} ...")
    cp = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-r", str(requirements)],
    )
    if cp.returncode != 0:
        print("[install] ERROR: pip install failed (see output above)")
        return cp.returncode

    stamp = hashlib.sha256(requirements.read_bytes()).hexdigest()
    (root / stamp_name).write_text(stamp, encoding="utf-8")
    print(f"[install] {stack} install stamp written ({stamp_name})")
    return 0


def main() -> int:
    root = state_root()
    print(f"[install] plugin root: {PLUGIN_ROOT}")
    print(f"[install] data root: {root}")

    # 1. python 检查
    if sys.version_info < (3, 10):
        print(f"[install] ERROR: Python 3.10+ required, got {sys.version.split()[0]}")
        return 1
    print(f"[install] python: {sys.version.split()[0]}")

    # 2/3/6. 两侧内核：venv + 依赖 + stamp
    for stack, runtime_dir, venv_name, stamp_name in STACKS:
        code = _setup_stack(stack, runtime_dir, venv_name, stamp_name)
        if code != 0:
            return code

    # 4. 初始化数据根目录结构
    for sub in DATA_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    print(f"[install] data root initialized: {root}")

    # 5. .env 模板（不覆盖已有）
    env_file = root / ".env"
    if env_file.is_file():
        print("[install] data-root .env already exists, keeping it")
    else:
        try:
            env_template = ENV_TEMPLATE_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[install] ERROR: cannot read {ENV_TEMPLATE_FILE}: {exc}")
            return 1
        env_file.write_text(env_template, encoding="utf-8")
        print("[install] data-root .env created from scripts/.env.template")

    # 5.5 CA 证书探测：写入 SSL_CERT_FILE（对新建模板与既有 .env 都生效，幂等）
    pkm_venv_python = root / ".venv-pkm" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    _ensure_ssl_cert_file(env_file, _detect_ca_bundle(pkm_venv_python))

    print("[install] DONE. Next: configure the data-root .env (embedding required; "
          "LLM required for build), then use the plugin via /cosightbot:pkm or /cosightbot:soc.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
