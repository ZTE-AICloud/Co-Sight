#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SOC KB 构建器管理核心（增删配置 / remove 两阶段清理）。

soc-kb-build 技能 CLI（kb_cli.py）共享的实现都收敛在这里。

所有磁盘布局收敛到工作目录下：
  data/workspace-soc/builder/
    configs/<kb_id>.json  构建器配置
    sources/<kb_id>/      本地源目录（镜像）
    builds/<kb_id>/       构建产物与状态
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol



# ─────────────────────────────────────────────
# 状态根
# ─────────────────────────────────────────────

def state_root() -> Path:
    """数据根目录（工作目录下 data/，COSIGHTBOT_HOME 覆盖）。"""
    from common.port_resolver import cosight_state_root

    return cosight_state_root()


def builder_root() -> Path:
    """构建器根目录：data/workspace-soc/builder/。"""
    return state_root() / "workspace-soc" / "builder"


def configs_dir() -> Path:
    return builder_root() / "configs"


def config_path(kb_id: str) -> Path:
    return configs_dir() / f"{kb_id}.json"


def sources_dir(kb_id: str) -> Path:
    return builder_root() / "sources" / kb_id


def builds_dir(kb_id: str) -> Path:
    return builder_root() / "builds" / kb_id


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # tmp 名带 pid：与 kb_scheduler._atomic_write_json / runner._write_status
    # 保持同一约定，防并发写同一路径时互相 replace 走对方的 tmp。
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ─────────────────────────────────────────────
# add-builtin
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class AddResult:
    ok: bool
    kb_id: str
    config_path: str = ""
    error: str = ""
    suggestion: str = ""
    # 非致命告警（注册成功但调用侧应明示给操作者）
    warnings: tuple[str, ...] = ()


def add_builtin(
    *,
    kb_id: str,
    name: str | None,
    source_dir: str | None,
) -> AddResult:
    """注册 builtin KB 构建器配置（本地源目录）。

    重复注册拒绝，不覆盖现有配置。所有 KB 都是本机用户自己的数据。
    """
    if not kb_id:
        return AddResult(ok=False, kb_id=kb_id, error="add-builtin 需要 --kb-id")

    cfg_path = config_path(kb_id)
    if cfg_path.is_file():
        return AddResult(
            ok=False,
            kb_id=kb_id,
            config_path=str(cfg_path),
            error=f"构建器配置已存在，不重复添加: {cfg_path}",
            suggestion=f"如需重新注册，请先执行 remove {kb_id} --confirm",
        )

    if source_dir:
        src = Path(os.path.expanduser(source_dir))
        # 显式指定的路径不存在视为拼写错误，拒绝（防手滑写错路径）
        if not src.exists():
            return AddResult(ok=False, kb_id=kb_id, error=f"source_dir 不存在: {src}")
    else:
        # 缺省：data/workspace-soc/builder/sources/<kb_id>，自动创建
        src = sources_dir(kb_id)
        src.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "kb_id": kb_id,
        "kb_type": "builtin",
        "kb_name": name or kb_id,
        "source_dir": str(src),
    }
    atomic_write_json(cfg_path, payload)
    return AddResult(
        ok=True,
        kb_id=kb_id,
        config_path=str(cfg_path),
    )


# ─────────────────────────────────────────────
# remove（两阶段：探测 → 确认清理）
# ─────────────────────────────────────────────

def dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return round(total / 1024 / 1024, 1)


def rmtree_retry(path: Path, attempts: int = 3, delay: float = 2.0) -> None:
    """删目录带重试 + Windows 长路径兜底。

    重试原因：刚 cancel 的进程可能还握着 builds/ 下的文件句柄。
    长路径原因：builds/ 下是深层嵌套（pre-processed/<table>/Support官方产品文档/
    <多级中文目录>/<文件>_md_chapters/...），全路径很容易超 MAX_PATH 260——
    os.unlink/os.rmdir 的"路径过长"失败会被 shutil.rmtree 掩盖成
    WinError 145 "目录不是空的"，纯重试永远救不回来。

    依次尝试：普通 rmtree → \\?\\ 前缀 rmtree（绕过 MAX_PATH）→ cmd rd /s /q
    （Windows 自带删除，自身不受 MAX_PATH 限制）。
    """
    import shutil
    import subprocess
    import time

    def _try_rmtree(p: Any, why: str) -> None:
        last_exc: OSError | None = None
        for i in range(attempts):
            try:
                shutil.rmtree(p)
                return
            except OSError as exc:
                last_exc = exc
                if i < attempts - 1:
                    time.sleep(delay)
        raise OSError(f"rmtree({why}) 失败: {last_exc}")

    # 1) 普通删除（短路径场景的常规路径）
    try:
        _try_rmtree(path, "普通")
        return
    except OSError:
        pass

    if sys.platform != "win32":
        raise OSError(f"无法删除: {path}")

    # 2) \\?\ 前缀绕过 MAX_PATH（要求绝对路径 + 反斜杠；abspath 是纯字符串
    #    运算，不会因超长路径而失败）
    abs_path = os.path.abspath(str(path))
    try:
        _try_rmtree("\\\\?\\" + abs_path, "长路径前缀")
        return
    except OSError:
        pass

    # 3) rd /s /q：rd 内部不受 MAX_PATH 限制，中文/空格路径由 list2cmdline 加引号
    proc = subprocess.run(
        ["cmd", "/c", "rd", "/s", "/q", abs_path],
        capture_output=True, timeout=120, check=False,
    )
    if not path.exists():
        return
    raise OSError(
        f"rd /s /q 仍无法删除 {abs_path}（rc={proc.returncode}，"
        f"stderr={proc.stderr.decode(errors='replace')[:200]}）"
    )


class RemoveRuntime(Protocol):
    """remove 探测/清理需要的运行态通道。

    本地通道（kb_cli.py）：直接实例化构建器调同名方法。
    """

    def running_pid(self, kb_id: str) -> int | None:
        """返回运行中构建的 pid；无则 None。"""
        ...

    def cancel(self, kb_id: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class RemoveTargets:
    running_pid: int | None
    sources_dir: str | None
    sources_size_mb: float
    builds_dir: str | None
    builds_size_mb: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "running_pid": self.running_pid,
            "sources_dir": self.sources_dir,
            "sources_size_mb": self.sources_size_mb,
            "builds_dir": self.builds_dir,
            "builds_size_mb": self.builds_size_mb,
        }


@dataclass(frozen=True)
class RemoveResult:
    ok: bool
    kb_id: str
    error: str = ""
    confirm_required: bool = False
    message: str = ""
    will_cleanup: dict[str, Any] | None = None
    cancel: dict[str, Any] | None = None
    sources_dir_removed: bool = False
    builds_dir_removed: bool = False
    config_removed: bool = False
    exit_code: int = 0


def query_remove_targets(kb_id: str, runtime: RemoveRuntime) -> RemoveTargets:
    """探测 remove 需要一并清理的运行态：运行中构建 / sources / builds。"""
    running_pid = runtime.running_pid(kb_id)

    src_dir = sources_dir(kb_id)
    bld_dir = builds_dir(kb_id)
    return RemoveTargets(
        running_pid=running_pid,
        sources_dir=str(src_dir) if src_dir.exists() else None,
        sources_size_mb=dir_size_mb(src_dir) if src_dir.exists() else 0,
        builds_dir=str(bld_dir) if bld_dir.exists() else None,
        builds_size_mb=dir_size_mb(bld_dir) if bld_dir.exists() else 0,
    )


def remove_kb(kb_id: str, *, confirm: bool, runtime: RemoveRuntime) -> RemoveResult:
    """删除 KB 构建器（仅构建侧，两阶段）：

    1. confirm=False：探测运行中构建 / sources / builds，
       有需要清理的内容就返回 confirm_required，等用户确认；
    2. confirm=True：cancel 运行中构建 → 删 sources/builds 目录 → 最后删配置。

    仅清构建器自己的资产；检索侧归各自系统管，本函数不感知。

    config 已不存在但目录有残留（半删除孤儿态）时同样可以清理。
    顺序刻意为"目录在前、config 最后"：目录删除失败时 config 还在，
    用户可直接重试 remove --confirm，不会出现配置没了却剩一堆目录的半删除态。
    """
    if not kb_id:
        return RemoveResult(ok=False, kb_id=kb_id, error="remove 命令需要 <kb_id>", exit_code=2)

    cfg_path = config_path(kb_id)
    cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}

    targets = query_remove_targets(kb_id, runtime)
    need_confirm = any([
        targets.running_pid,
        targets.sources_dir,
        targets.builds_dir,
    ])

    if not cfg_path.is_file() and not need_confirm:
        return RemoveResult(
            ok=False,
            kb_id=kb_id,
            error=f"配置不存在且无残留可清理: {cfg_path}",
            exit_code=1,
        )

    if need_confirm and not confirm:
        return RemoveResult(
            ok=False,
            kb_id=kb_id,
            confirm_required=True,
            message=(
                f"remove [{kb_id}] 除配置外还将一并清理以下内容。"
                f"请向用户确认后重新执行: remove {kb_id} --confirm"
            ),
            will_cleanup={
                "config": str(cfg_path) if cfg_path.is_file() else None,
                **targets.to_payload(),
            },
            exit_code=1,
        )

    # 1) 先停运行中的构建（等 2 秒让进程释放 builds/ 下的文件句柄）
    cancel_payload: dict[str, Any] | None = None
    if targets.running_pid:
        cancel_payload = runtime.cancel(kb_id)
        if not cancel_payload.get("ok"):
            return RemoveResult(
                ok=False,
                kb_id=kb_id,
                error=f"取消运行中构建失败: {cancel_payload.get('error')}",
                cancel=cancel_payload,
                exit_code=1,
            )
        import time

        time.sleep(2)

    # 2) 删 sources / builds 目录（在前：失败时 config 还在，可整体重试）
    removed = {"sources_dir_removed": False, "builds_dir_removed": False}
    for key, flag in (("sources_dir", "sources_dir_removed"), ("builds_dir", "builds_dir_removed")):
        dir_str = getattr(targets, key)
        if not dir_str:
            continue
        try:
            rmtree_retry(Path(dir_str))
            removed[flag] = True
        except OSError as exc:
            return RemoveResult(
                ok=False,
                kb_id=kb_id,
                error=f"删除 {dir_str} 失败: {exc}",
                cancel=cancel_payload,
                exit_code=1,
            )

    # 3) 最后删配置（前面任何一步失败时 config 还在，可整体重试）
    config_removed = False
    if cfg_path.is_file():
        cfg_path.unlink()
        config_removed = True

    return RemoveResult(
        ok=True,
        kb_id=kb_id,
        cancel=cancel_payload,
        sources_dir_removed=removed["sources_dir_removed"],
        builds_dir_removed=removed["builds_dir_removed"],
        config_removed=config_removed,
        exit_code=0,
    )
