#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-material CLI —— 资料目录绑定 / 入库 / 索引构建。

子命令：
  bind <目录>                绑定资料目录，成功后自动首次构建
  status                     绑定状态 + 索引状态 + 源目录变更对账（指纹比对）
  build [--force]            手动构建（默认指纹增量；--force 全量）
  list                       列出绑定目录文件 + 当前会话上传文件
  unbind                     解除绑定并清理该路由的索引数据
  ingest [--global] <路径>   把文件/目录加入知识库：默认进当前会话路由
                             （upload_files/<session_hash>/），--global 进 agent 级
                             收件箱（inbox/）；成功后自动增量构建
  remove <文件名...>         从当前会话路由（或 --global 收件箱）删除文件，自动增量删 nodes

会话标识：直接读 Claude Code 自动注入的 CLAUDE_CODE_SESSION_ID（v2.1.132+），
按 sha256[:16] 折算 session_hash；缺失时优雅降级到 agent 级 inbox 并说明。

无常驻进程（不注册 watcher、不 HTTP 通知）；构建为子进程调 llamaindex_task_runner 一次性 CLI。
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-material/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "pkm"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap, load_env  # noqa: E402

load_env()  # .env 先加载（preflight 可能在 install.py 尚未运行前失败，属预期）

from common.skill_utils import (  # noqa: E402
    cosight_state_root,
    load_state,
    setup_skill_logging,
    state_paths,
    validate_dir,
)
from common.logging_setup import log_event  # noqa: E402

AGENT_ID = "main"
_LOG = None


def get_log():
    global _LOG
    if _LOG is None:
        _LOG = setup_skill_logging("cosightbot_material", debug_env_var="COSIGHTBOT_MATERIAL_DEBUG")
    return _LOG


# ---------------------------------------------------------------------------
# 会话标识（CLAUDE_CODE_SESSION_ID，官方机制 v2.1.132+）
# ---------------------------------------------------------------------------

def current_session_key() -> str:
    return (os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()


def session_hash_of(session_key: str) -> str:
    """sessionKeyToHash 算法保留：sha256(key)[:16]，key 来源换成 CC session id。"""
    return hashlib.sha256(session_key.encode()).hexdigest()[:16] if session_key else ""


def current_session_hash() -> str:
    return session_hash_of(current_session_key())


# ---------------------------------------------------------------------------
# 构建触发（runner 一次性 CLI 子进程）
# ---------------------------------------------------------------------------

def _runner_cmd() -> list[str]:
    return [sys.executable, str(_RUNTIME / "watch_dog" / "llamaindex_task_runner.py")]


def _stream_run(cmd: list[str]) -> tuple[bool, str]:
    """并发消费 runner 的 stdout/stderr，避免任一 PIPE 写满后互相等待。

    stdout 仍逐行透传进度；stderr 只保留末尾 20 行用于失败回报。
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None and proc.stderr is not None
    stderr_lines: deque[str] = deque(maxlen=20)

    def _forward_stdout() -> None:
        for line in proc.stdout:
            if not line.strip():
                continue
            try:
                print(line, end="", flush=True)
            except (BrokenPipeError, OSError):
                # Keep draining the child pipe even if the caller stops reading.
                pass

    def _collect_stderr() -> None:
        for line in proc.stderr:
            stderr_lines.append(line.rstrip("\r\n"))

    stdout_thread = threading.Thread(target=_forward_stdout, name="runner-stdout")
    stderr_thread = threading.Thread(target=_collect_stderr, name="runner-stderr")
    stdout_thread.start()
    stderr_thread.start()
    rc = proc.wait()
    stdout_thread.join()
    stderr_thread.join()
    if rc != 0:
        tail = "\n".join(stderr_lines)
        return False, tail or f"runner exited {rc}"
    return True, ""


def run_build(path: Path, *, force: bool = False, session_hash: str = "") -> tuple[bool, str]:
    """全量/指纹增量构建（common_build）。输出直接透传给调用方（进度行）。"""
    cmd = _runner_cmd() + ["common_build", "--agent_id", AGENT_ID, "--path", str(path)]
    if force:
        cmd.append("--force")
    if session_hash:
        cmd += ["--session_key_hash", session_hash, "--session_key", current_session_key()]
    get_log().info("[build] %s", " ".join(cmd))
    return _stream_run(cmd)


def run_update(src_path: Path, event_type: str, *, session_hash: str = "", route_dir: Path | None = None) -> tuple[bool, str]:
    """单文件增量（common_update，event_type: created/deleted/modified）。"""
    path_arg = str(route_dir) if route_dir else str(src_path.parent)
    cmd = _runner_cmd() + [
        "common_update", "--agent_id", AGENT_ID, "--path", path_arg,
        "--src_path", str(src_path), "--event_type", event_type,
    ]
    if session_hash:
        cmd += ["--session_key_hash", session_hash, "--session_key", current_session_key()]
    get_log().info("[update] %s", " ".join(cmd))
    return _stream_run(cmd)


# ---------------------------------------------------------------------------
# 路由目录
# ---------------------------------------------------------------------------

def workspace_root() -> Path:
    return cosight_state_root() / f"workspace-{AGENT_ID}"


def llamaindex_data() -> Path:
    return workspace_root() / "llamaindex_data"


def inbox_dir() -> Path:
    return llamaindex_data() / "inbox"


def session_upload_dir(session_hash: str) -> Path:
    return llamaindex_data() / "upload_files" / session_hash


def route_prefix_of(src_root: Path) -> str:
    abs_path = str(src_root.expanduser().resolve())
    return f"{src_root.name}_{hashlib.md5(abs_path.encode('utf-8')).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_bind(path_raw: str) -> int:
    ok, msg = validate_dir(path_raw)
    if not ok:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        return 1
    src_root = Path(msg)

    d, f = state_paths(AGENT_ID)
    d.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"path": str(src_root), "source": "user_text"}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "bound": str(src_root), "state_file": str(f)}, ensure_ascii=False))
    # 操作即构建：绑定后自动首次构建（指纹增量，重复 bind 秒退）
    build_ok, err = run_build(src_root)
    print(json.dumps({"auto_build": build_ok, **({} if build_ok else {"build_error": err})}, ensure_ascii=False))
    return 0 if build_ok else 1


def _index_status_file(src_root: Path) -> Path:
    return llamaindex_data() / "lancedb" / route_prefix_of(src_root) / ".llamaindex_status"


def _scan_source_files(src_root: Path) -> dict[str, tuple[int, int]]:
    """扫描源目录当前文件（rel_posix -> (mtime, size)），只统计构建器支持的类型。

    用办公构建链的权威扩展集 BUILD_INDEX_EXTS（含 .md/.txt/.html 等文本类），
    而非 SOC 下载器的 SUPPORTED_SOURCE_EXTS（不含 .md）。
    """
    from watch_dog.file_watcher.preprocessor import BUILD_INDEX_EXTS
    out: dict[str, tuple[int, int]] = {}
    for p in src_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in BUILD_INDEX_EXTS:
            try:
                st = p.stat()
            except OSError:
                continue
            out[p.relative_to(src_root).as_posix()] = (int(st.st_mtime), st.st_size)
    return out


def _pending_changes(src_root: Path) -> dict:
    """指纹对账：源目录当前状态 vs .llamaindex_status 记录。返回变更统计。"""
    status_file = _index_status_file(src_root)
    recorded: dict = {}
    if status_file.is_file():
        try:
            recorded = (json.loads(status_file.read_text(encoding="utf-8")).get("files") or {})
        except (OSError, json.JSONDecodeError):
            recorded = {}
    current = _scan_source_files(src_root)
    new = [r for r in current if r not in recorded]
    deleted = [r for r in recorded if r not in current]
    changed = []
    for r, (mtime, size) in current.items():
        rec = recorded.get(r)
        if rec and rec.get("status") == "success":
            if int(rec.get("mtime", 0)) != mtime or int(rec.get("size", -1)) != size:
                changed.append(r)
    return {"new": len(new), "modified": len(changed), "deleted": len(deleted)}


def cmd_status() -> int:
    data = load_state(AGENT_ID)
    configured = bool(data and isinstance(data.get("path"), str))
    path = data["path"] if configured else None
    exists = Path(path).is_dir() if path else False

    index_status = "none"
    pending = None
    if configured and exists:
        src_root = Path(path)
        status_file = _index_status_file(src_root)
        if status_file.is_file():
            try:
                index_status = json.loads(status_file.read_text(encoding="utf-8")).get("status", "none")
            except (OSError, json.JSONDecodeError):
                index_status = "failed"
        pending = _pending_changes(src_root)

    out = {
        "configured": configured,
        "path": path,
        "exists": exists,
        "index_status": index_status,
        "agent_id": AGENT_ID,
    }
    if pending:
        total = pending["new"] + pending["modified"] + pending["deleted"]
        out["pending_changes"] = pending
        if total:
            out["message"] = (
                f"源目录有 {total} 个文件变更待入库"
                f"（新增 {pending['new']} / 修改 {pending['modified']} / 删除 {pending['deleted']}），"
                "请运行 cosightbot-material build"
            )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_build(force: bool) -> int:
    data = load_state(AGENT_ID)
    if not (data and isinstance(data.get("path"), str) and Path(data["path"]).is_dir()):
        print(json.dumps({"ok": False, "error": "未绑定资料目录，请先 bind"}, ensure_ascii=False))
        return 1
    ok, err = run_build(Path(data["path"]), force=force)
    print(json.dumps({"ok": ok, **({} if ok else {"error": err})}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_unbind() -> int:
    _, f = state_paths(AGENT_ID)
    old = load_state(AGENT_ID)
    removed = f.is_file()
    if removed:
        f.unlink()

    cleaned: list[str] = []
    if old and isinstance(old.get("path"), str):
        prefix = route_prefix_of(Path(old["path"]))
        for target in (llamaindex_data() / "lancedb" / prefix,
                       llamaindex_data() / "pre-processed" / prefix):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                cleaned.append(str(target))

    print(json.dumps({"ok": True, "unbound": removed, "cleaned": cleaned}, ensure_ascii=False))
    return 0


def cmd_ingest(paths: list[str], global_scope: bool) -> int:
    """把文件/目录拷入对应路由目录，然后自动增量构建。"""
    if global_scope:
        target_dir = inbox_dir()
        scope = "global"
        sh = ""
    else:
        sh = current_session_hash()
        if not sh:
            # 优雅降级：老版本 CC 无 CLAUDE_CODE_SESSION_ID → 落 agent 级 inbox
            target_dir = inbox_dir()
            scope = "global_fallback"
            print(json.dumps({
                "notice": "CLAUDE_CODE_SESSION_ID 未注入（CC 版本低于 2.1.132 或非 CC 环境），"
                          "文件已加入 agent 级知识库（inbox/）而非会话级",
            }, ensure_ascii=False))
        else:
            target_dir = session_upload_dir(sh)
            scope = "session"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    errors: list[dict] = []
    copied_dirs: list[str] = []
    for raw in paths:
        src = Path(raw).expanduser()
        if not src.exists():
            errors.append({"path": raw, "error": "路径不存在"})
            continue
        dest = target_dir / src.name
        try:
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                copied_dirs.append(src.name)
            else:
                shutil.copy2(src, dest)
                copied.append(src.name)
        except OSError as e:
            errors.append({"path": raw, "error": str(e)})

    print(json.dumps({
        "ok": not errors, "scope": scope, "target_dir": str(target_dir),
        "copied_files": copied, "copied_dirs": copied_dirs,
        **({"errors": errors} if errors else {}),
    }, ensure_ascii=False))

    if not (copied or copied_dirs):
        return 1 if errors else 0

    # 操作即构建：单文件走 common_update 精准增量；目录走整路由 common_build
    failed: list[str] = []
    for name in copied:
        ok, err = run_update(target_dir / name, "created", session_hash=sh, route_dir=target_dir)
        if not ok:
            failed.append(f"{name}: {err}")
    if copied_dirs:
        ok, err = run_build(target_dir, session_hash=sh)
        if not ok:
            failed.append(err)
    print(json.dumps({"auto_build": not failed, **({"build_errors": failed} if failed else {})}, ensure_ascii=False))
    return 0 if not failed else 1


def cmd_remove(names: list[str], global_scope: bool) -> int:
    sh = "" if global_scope else current_session_hash()
    if not global_scope and not sh:
        print(json.dumps({"ok": False, "error": "CLAUDE_CODE_SESSION_ID 未注入，无法定位会话级目录；"
                                                "如需删除 agent 级文件请用 --global"}, ensure_ascii=False))
        return 1
    target_dir = inbox_dir() if global_scope else session_upload_dir(sh)
    if not target_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"目录不存在：{target_dir}"}, ensure_ascii=False))
        return 1

    deleted: list[str] = []
    failed: list[str] = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        target = (target_dir / name).resolve()
        try:
            target.relative_to(target_dir.resolve())  # 路径越界保护
        except ValueError:
            failed.append(f"{name}: 路径越界，拒绝操作")
            continue
        if not target.exists():
            failed.append(f"{name}: 不存在")
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            ok, err = run_update(target, "deleted", session_hash=sh, route_dir=target_dir)
            if ok:
                deleted.append(name)
            else:
                failed.append(f"{name}: 索引删除失败 {err}")
        except OSError as e:
            failed.append(f"{name}: {e}")

    print(json.dumps({"ok": not failed, "deleted": deleted,
                      **({"errors": failed} if failed else {})}, ensure_ascii=False))
    return 0 if not failed else 1


def cmd_list() -> int:
    data = load_state(AGENT_ID)
    agent_level: dict = {"configured": False}
    if data and isinstance(data.get("path"), str):
        root = Path(data["path"])
        if root.is_dir():
            files = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file()]
            agent_level = {"configured": True, "path": str(root), "file_count": len(files), "files": files[:2000]}
        else:
            agent_level = {"configured": True, "path": str(root), "error": "绑定路径不存在"}

    sh = current_session_hash()
    session_level: dict = {"available": False}
    if sh:
        up = session_upload_dir(sh)
        files = sorted(p.name for p in up.iterdir() if p.is_file()) if up.is_dir() else []
        session_level = {"available": True, "session_hash": sh, "upload_dir": str(up),
                         "files": files, "file_count": len(files)}
    else:
        session_level["notice"] = "CLAUDE_CODE_SESSION_ID 未注入，无会话级目录"

    ib = inbox_dir()
    inbox_files = sorted(p.name for p in ib.iterdir() if p.is_file()) if ib.is_dir() else []
    print(json.dumps({
        "ok": True, "agent_level": agent_level, "session_level": session_level,
        "inbox": {"dir": str(ib), "files": inbox_files, "file_count": len(inbox_files)},
    }, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="cosightbot-material: 资料目录绑定与索引构建")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("bind", help="绑定资料目录并自动首次构建")
    p.add_argument("path")
    sub.add_parser("status", help="绑定/索引状态 + 变更对账")
    p = sub.add_parser("build", help="手动构建（默认指纹增量）")
    p.add_argument("--force", action="store_true")
    sub.add_parser("list", help="列出绑定目录与各级上传文件")
    sub.add_parser("unbind", help="解除绑定并清理索引")
    p = sub.add_parser("ingest", help="把文件/目录加入知识库并自动增量构建")
    p.add_argument("paths", nargs="+")
    p.add_argument("--global", dest="global_scope", action="store_true", help="进 agent 级收件箱（默认会话级）")
    p = sub.add_parser("remove", help="删除已入库文件并自动增量删 nodes")
    p.add_argument("names", nargs="+")
    p.add_argument("--global", dest="global_scope", action="store_true")

    args = parser.parse_args()

    # preflight：install.py 未跑过时给出 please_run_install 引导（exit 3）
    bootstrap()

    log = get_log()

    def _run(name: str, fn, **fields):
        t0 = time.perf_counter()
        log_event(log, "material:cmd:start", cmd=name, **fields)
        try:
            rc = fn()
        except Exception as exc:
            log_event(log, "material:cmd:error", level=logging.ERROR, cmd=name,
                      error=f"{type(exc).__name__}: {exc}", exc_info=True, **fields)
            raise
        log_event(log, "material:cmd:done", cmd=name, rc=rc,
                  duration_ms=round((time.perf_counter() - t0) * 1000, 1), **fields)
        return rc

    if args.cmd == "bind":
        return _run("bind", lambda: cmd_bind(args.path), path=args.path)
    if args.cmd == "status":
        return _run("status", cmd_status)
    if args.cmd == "build":
        return _run("build", lambda: cmd_build(args.force), force=args.force)
    if args.cmd == "list":
        return _run("list", cmd_list)
    if args.cmd == "unbind":
        return _run("unbind", cmd_unbind)
    if args.cmd == "ingest":
        return _run("ingest", lambda: cmd_ingest(args.paths, args.global_scope),
                    paths=args.paths, global_scope=args.global_scope)
    if args.cmd == "remove":
        return _run("remove", lambda: cmd_remove(args.names, args.global_scope),
                    names=args.names, global_scope=args.global_scope)
    return 2


if __name__ == "__main__":
    sys.exit(main())
