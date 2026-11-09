#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — e2e-test-runner 的跨模块工具（IO / 路径解析 / 时间戳 / 校验）。"""

import glob
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import config


# ============================== 错误与退出 ==============================

class RunnerError(Exception):
    """可预期的业务失败：打印后以退出码 1 结束，不打印堆栈。"""


def fail(message: str) -> None:
    """打印 ERROR 并以退出码 1 退出。"""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


# ============================== JSON / JSONL IO ==============================

def read_json(path: Path):
    """读取 JSON；文件不存在返回 None，解析失败抛 RunnerError。"""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"无法解析 JSON：{path}（{exc}）") from exc


def write_json(path: Path, payload) -> None:
    """原子写入 JSON（先写临时文件再替换）。"""
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_text(path: Path, text: str) -> None:
    """原子写入文本；父目录按需创建。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path: Path) -> list:
    """逐行读取 JSONL；文件不存在返回 []，坏行抛 RunnerError。"""
    path = Path(path)
    if not path.is_file():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunnerError(f"JSONL 第 {lineno} 行非法：{exc}") from exc
        if not isinstance(obj, dict):
            raise RunnerError(f"JSONL 第 {lineno} 行不是 JSON 对象")
        records.append(obj)
    return records


def write_jsonl(path: Path, records: list) -> None:
    """写入 JSONL（每行一个紧凑 JSON 对象）。"""
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))


# ============================== 路径解析 ==============================

def newest_run_dir(parent: Path, glob: str) -> Path | None:
    """在 parent 下按**目录名倒序**取第一个匹配的目录。

    按名字而非 mtime：run 目录名本身带 %Y%m%d-%H%M%S 时间戳，字典序即时间序，
    且不受 git checkout / 拷贝导致的 mtime 漂移影响。
    """
    parent = Path(parent)
    if not parent.is_dir():
        return None
    candidates = sorted(
        (p for p in parent.glob(glob) if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def locate_seed(input_arg: str | None) -> Path:
    """把 --input 解析成 seed.jsonl 的绝对路径。

    接受三种形态：seed.jsonl 文件本身 / 含 seed.jsonl 的目录 / run 目录
    （其下 generated_datasets/seed.jsonl）。目录形态按 config.SEED_PROBE_RELPATHS
    顺序探测。解析不出即抛 RunnerError——不做静默回退。
    """
    if input_arg:
        path = Path(input_arg).expanduser()
        if not path.exists():
            raise RunnerError(f"--input 指向的路径不存在：{path}")
        if path.is_file():
            if path.name != config.SEED_FILENAME:
                raise RunnerError(f"--input 指向的文件不是 {config.SEED_FILENAME}：{path}")
            return path.resolve()
        for relparts in config.SEED_PROBE_RELPATHS:
            candidate = path.joinpath(*relparts)
            if candidate.is_file():
                return candidate.resolve()
        tried = "、".join("/".join(r) for r in config.SEED_PROBE_RELPATHS)
        raise RunnerError(
            f"--input 目录下找不到 {config.SEED_FILENAME}：{path}\n"
            f"  已探测：{tried}"
        )

    parent = Path(config.RUN_PARENT_DIR)
    run_dir = newest_run_dir(parent, config.RUN_DIR_GLOB)
    if run_dir is None:
        raise RunnerError(
            f"未指定 --input，且 {parent.resolve()} 下没有 {config.RUN_DIR_GLOB} 目录。\n"
            f"  请显式指定：--input <run 目录|generated_datasets 目录|seed.jsonl>"
        )
    return locate_seed(str(run_dir))


def run_dir_of(seed_path: Path) -> Path:
    """从 seed.jsonl 的路径反推它所属的 run 目录。

    两种形态：
      <run>/generated_datasets/seed.jsonl → <run>
      <seed.jsonl 直接放在某目录下>        → 该目录
    """
    seed_path = Path(seed_path)
    if seed_path.parent.name == config.INPUT_ARTIFACT_DIRNAME:
        return seed_path.parent.parent
    return seed_path.parent


def resolve_agent_root(agent_arg: str | None, seed_path: Path) -> Path:
    """确定被测 agent 根目录（并发调度的共享 cwd）。

    显式 --agent 优先；为空时读 <seed 所在交付目录>/manifest.json 的 agent_root。
    agent_root 不存在即报错——不静默回退到别的目录：用例的 precondition 引用了
    相对路径的 fixture，跑在错的根上会让全部用例假失败，比报错危险得多。
    """
    if agent_arg:
        path = Path(agent_arg).expanduser()
        if not path.is_dir():
            raise RunnerError(f"--agent 指向的目录不存在：{path}")
        return path.resolve()

    manifest_path = Path(seed_path).parent / config.MANIFEST_FILENAME
    manifest = read_json(manifest_path)
    if manifest is None:
        raise RunnerError(
            f"--agent 未指定，且找不到 {config.MANIFEST_FILENAME}：{manifest_path}\n"
            f"  请显式指定：--agent <被测 agent 目录>"
        )

    agent_root = str(manifest.get(config.AGENT_ROOT_KEY) or "").strip()
    if not agent_root:
        raise RunnerError(
            f"{manifest_path} 里没有 {config.AGENT_ROOT_KEY} 字段。\n"
            f"  请显式指定：--agent <被测 agent 目录>"
        )

    root = Path(agent_root).expanduser()
    if not root.is_dir():
        raise RunnerError(
            f"{config.MANIFEST_FILENAME} 里的 {config.AGENT_ROOT_KEY} 不存在：\n"
            f"  {root}\n"
            f"  该路径属于生成中途的解包中间态，可能已被清理。\n"
            f"  请显式指定：--agent <被测 agent 目录>"
        )
    return root.resolve()


# ============================== 校验 ==============================

def case_id_of(record: dict, index: int) -> str:
    """取用例标识（= 目录名）。缺失或含路径分隔符即报错。"""
    data_id = str(record.get(config.DATA_ID_KEY) or "").strip()
    if not data_id:
        raise RunnerError(
            f"{config.SEED_FILENAME} 第 {index} 条记录缺少 {config.DATA_ID_KEY} 字段"
        )
    for bad in config.FORBIDDEN_CASE_ID_PARTS:
        if bad in data_id:
            raise RunnerError(
                f"{config.DATA_ID_KEY} 不能用作目录名（含 {bad!r}）：{data_id}"
            )
    return data_id


def input_of(record: dict, index: int) -> str:
    """取送进 claude -p stdin 的 prompt。precondition 刻意不参与组装。"""
    value = record.get(config.INPUT_KEY)
    if value is None or not str(value).strip():
        raise RunnerError(
            f"{config.SEED_FILENAME} 第 {index} 条记录缺少 {config.INPUT_KEY} 字段"
        )
    return str(value)


def timeout_of(record: dict) -> int:
    """单用例超时：seed 带 timeout 字段时以它为准，否则用默认值。"""
    raw = record.get(config.TIMEOUT_KEY)
    if raw is None:
        return config.CASE_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise RunnerError(
            f"{config.TIMEOUT_KEY} 必须是整数：{raw!r}"
        ) from None
    if value <= 0:
        raise RunnerError(f"{config.TIMEOUT_KEY} 必须为正数：{value}")
    return value


def stamp_now() -> str:
    """秒级时间戳，与生成器同一格式。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ============================== 会话日志 ==============================

def find_session_log(session_id: str, roots=None) -> list:
    """在会话日志根目录下搜出属于该 session_id 的全部路径。

    roots 为 glob 列表，缺省取 config.SESSION_LOG_GLOBS（本机是 `~/.*/projects`，
    同时覆盖 ~/.claude 与 ~/.cosight 两个配置根）。之所以做成参数，是为了让测试
    能把搜索根指到临时目录——默认行为不变，但不必去动真实的 home。

    命中两种形态（多轮会话可能两种同时存在）：
      <projects>/<cwd 编码>/<session_id>.jsonl              主会话
      <projects>/<cwd 编码>/<session_id>/subagents/*.jsonl  子代理

    **空 id 直接返回 []**：`rglob("")` 等价于 `rglob("*")`，会把整棵 projects 树
    都匹配上（实测：一个空串能匹配到全库每个文件与目录）。result.json 解析不出
    session_id 的场合真实存在，所以这个守卫不是防御性编程，是必须的。
    """
    sid = str(session_id or "").strip()
    if not sid:
        return []

    patterns = config.SESSION_LOG_GLOBS if roots is None else roots
    found = []
    seen = set()
    for pattern in patterns:
        for projects_root in sorted(glob.glob(os.path.expanduser(str(pattern)))):
            for path in sorted(Path(projects_root).rglob(f"{sid}*")):
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    found.append(path)
    return found


def copy_session_log(session_id: str, session_dir: Path, roots=None) -> list:
    """把某会话的全部日志拷进 session_dir，返回实际拷到的源路径列表。

    返回空列表即"磁盘上没有该会话的日志"——调用方据此记 not_found，而不是在这里
    抛错：日志缺失属于基建问题，不该把被测 Agent 的用例判成失败。**拷贝本身的
    失败（IO 错误）则照常抛出**，由调用方记 copy_failed。

    目录用 copytree（子代理日志整棵带过来），文件用 copy2；`symlinks=False` 把
    符号链接解引用成真实内容，避免拷出一堆指向原 home 的悬空链接。

    两个刻意的偏离，都是被实测逼出来的：

    - **逐条判 `is_dir()` 而不是 `is_dir(follow_symlinks=False)`**：真机上
      session 目录若是符号链接（实际出现过），后者会被当成文件、丢给 copy2，
      直接抛 IsADirectoryError。
    - **不用 `copytree(dirs_exist_ok=True)`**：会话目录里可能有指回上一级、乃至
      指回自己的链接；`dirs_exist_ok` 会让 copytree **把目标当成源的一部分**，
      于是把正在写的文件当成自己的"已存在兄弟"→ `are the same file` 直接失败。
      这里把源整棵读进内存后先删目标再拷：源在读到时就固定了，因此不怕删到源，
      且重跑残留会被彻底清掉。
    """
    session_dir = Path(session_dir).resolve()
    targets = _exclude_within(find_session_log(session_id, roots), session_dir)
    if not targets:
        return []

    session_dir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        if target.is_dir():
            _replace_tree(target, session_dir / target.name)
        else:
            shutil.copy2(target, session_dir)
    return targets


def _exclude_within(paths: list, root: Path) -> list:
    """滤掉落在 root 内部的路径。

    目标目录若恰好在搜索根之内（测试里就会这么摆），上一次拷出来的副本会被当成
    源再搜回来，`copy2` 于是抛 `SameFileError`。生产布局（产物目录 vs
    `~/.*/projects`）不会重叠，但花两行换掉一整类难查的"自己是自己的源"故障划算。
    """
    kept = []
    for path in paths:
        try:
            if path.resolve().is_relative_to(root):
                continue
        except OSError:  # 解不出的路径照常保留，交给拷贝环节报错
            pass
        kept.append(path)
    return kept


def _read_tree(root: Path) -> list:
    """把目录整棵读进内存，返回 (相对路径, 是否为目录, 内容) 的列表。

    先读后写是刻意的：这样删除目标目录时，源已经完整握在手里——即便源与目标
    落在同一棵树下也不会读到自己写出来的东西。
    """
    entries = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_dir():
            entries.append((rel, True, None))
        else:
            entries.append((rel, False, path.read_bytes()))
    return entries


def _replace_tree(src: Path, dst: Path) -> None:
    """用 src 的内容整体替换 dst（dst 先删后建，保证没有上一轮的残留）。"""
    entries = _read_tree(src)
    if dst.is_symlink():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for rel, is_dir, data in entries:
        target = dst / rel
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            shutil.copystat(src / rel, target)


# ============================== 目录指纹 ==============================

def sha256_tree(root) -> str:
    """目录内容指纹：按相对路径排序后逐个哈希路径与内容。

    与 e2e-test-generator 的 `common.sha256_tree` 同一算法——本 skill 拿它比对
    `manifest.json` 的 `agent_sha256`（生成时刻的目录指纹），据此判断 agent_root
    是否已被上一轮写脏，所以两边必须逐字节一致。两个 skill 是各自独立的交付目录，
    不共享 import 路径，故此处保留一份受控重复；改动任一侧请同步另一侧。

    目录不存在返回空串。读不到的文件跳过（不因单个不可读文件让整个指纹失真）。
    """
    root = Path(root)
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()
