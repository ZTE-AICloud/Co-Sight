#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — 跨阶段共享的工具函数（IO / 文本归一 / 哈希 / 校验）。"""

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import config


# ============================== 错误与退出 ==============================

class GoldevalError(Exception):
    """可预期的业务失败：打印后以退出码 1 结束，不打印堆栈。"""


def fail(message):
    """打印 ERROR 并以退出码 1 退出。"""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


# ============================== JSON IO ==============================

def read_json(path):
    """读取 JSON 文件；不存在返回 None，解析失败抛 GoldevalError。"""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldevalError(f"无法解析 JSON：{path}（{exc}）") from exc


def write_json(path, payload, *, indent=2):
    """原子写入 JSON（先写临时文件再替换）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=indent) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_text(path, text):
    """原子写入文本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_text(path, *, limit=None):
    """读取文本；缺失或不可读返回空串（不抛错——识别矩阵要求尽力而为）。"""
    path = Path(path)
    try:
        if not path.is_file():
            return ""
        data = path.read_bytes()
    except OSError:
        return ""
    cap = limit if limit is not None else config.MAX_READ_BYTES_PER_FILE
    if len(data) > cap:
        data = data[:cap]
    return data.decode("utf-8", errors="replace")


def read_jsonl(path):
    """逐行读取 JSONL；坏行抛 GoldevalError。"""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldevalError(f"JSONL 第 {lineno} 行非法：{exc}") from exc
        if not isinstance(obj, dict):
            raise GoldevalError(f"JSONL 第 {lineno} 行不是 JSON 对象")
        records.append(obj)
    return records


def write_jsonl(path, records):
    """写入 JSONL（每行一个紧凑 JSON 对象）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))


# ============================== 文本归一与相似度 ==============================

_PUNCT_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


def normalize_text(text):
    """归一化：转小写、去标点、空白折叠。用于去重比对。"""
    lowered = str(text).lower()
    stripped = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", stripped).strip()


def _ngrams(text, n):
    tokens = text.split()
    joined = "".join(tokens)
    if len(joined) < n:
        return {joined} if joined else set()
    return {joined[i:i + n] for i in range(len(joined) - n + 1)}


def jaccard(text_a, text_b, n=None):
    """3-gram Jaccard 相似度；任一为空返回 0.0。"""
    n = n or config.DEDUP_NGRAM
    set_a = _ngrams(normalize_text(text_a), n)
    set_b = _ngrams(normalize_text(text_b), n)
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def containment(text_case, text_source, n=None):
    """包含度：|A ∩ B| / min(|A|, |B|)。

    用于"用例是否由某段素材换皮而来"的判定。此时用例文本通常**长于**素材
    （素材是 Given 原文，用例还含 input 包装与要点分条），Jaccard 会因长度差
    被稀释到阈值以下而漏判——实测一条完整嵌入 Given 的用例 Jaccard 仅 0.51。
    包含度不受长度差影响，正是这个场景需要的度量。
    """
    n = n or config.DEDUP_NGRAM
    set_case = _ngrams(normalize_text(text_case), n)
    set_source = _ngrams(normalize_text(text_source), n)
    if not set_case or not set_source:
        return 0.0
    return len(set_case & set_source) / min(len(set_case), len(set_source))


def case_text(record):
    """取用例的比对文本（input + precondition + 全部要点）。"""
    parts = [str(record.get("input", "")), str(record.get("precondition", ""))]
    expected = record.get("expected_output") or []
    if isinstance(expected, list):
        parts.extend(str(item) for item in expected)
    else:
        parts.append(str(expected))
    return "\n".join(parts)


# ============================== 命名与哈希 ==============================

# 保留 CJK：中文 agent 名（如「明文密码智能体」）不应被清空成 fallback
_SLUG_RE = re.compile(r"[^a-zA-Z0-9一-鿿]+")


def slugify(name, *, fallback="agent"):
    """把任意名字转成可作文件名/标识符的 slug。"""
    slug = _SLUG_RE.sub("-", str(name)).strip("-").lower()
    return slug or fallback


# 形如 v1 / v2.1 / 1.0 的目录名只是版本号，单独用区分度太低
VERSION_DIR_RE = re.compile(r"^v?\d+(\.\d+)*$")
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")


def stem_of(path):
    """去掉压缩包扩展名后的名字。"""
    stem = Path(str(path)).name
    for suffix in ARCHIVE_SUFFIXES:
        if stem.lower().endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def name_from_path(path):
    """从路径推导可读名；叶子是版本号时退回父目录名。"""
    p = Path(str(path))
    stem = stem_of(p)
    if VERSION_DIR_RE.match(stem) and p.parent.name:
        return p.parent.name
    return stem


def slug_from_path(path):
    """**唯一**的 agent 命名推导：从 --agent 的路径取名。

    中间态目录、产出目录、用例 data_id 前缀三处共用它，因此三者必然一致。
    叶子是版本号目录（如 `.../v1`）时退回父目录名，压缩包则先去掉扩展名。

    刻意**不**采用 COSIGHT.md 里的 project_id：它跟目录名可以完全不同，
    一旦采用，中间态目录（S0 就得建好，那时还没扫画像）与产出目录
    （S1 之后才有画像）就会各叫各的。
    """
    return slugify(name_from_path(path))


def agent_slug(profile):
    """从路径推导的 agent 标识。

    以 S0 存进画像的 `agent_slug` 为准——它是 slug_from_path() 的结果，
    与中间态目录名同源。老画像没有该字段时回退到扫描根目录名。
    """
    profile = profile or {}
    explicit = str(profile.get("agent_slug") or "").strip()
    if explicit:
        return slugify(explicit)
    root = profile.get("root")
    if root:
        return slugify(name_from_path(root))
    return slugify(profile.get("project_name") or "", fallback="agent")


def naming_slug(profile):
    """**唯一**的产出命名推导：用例 data_id 前缀与 task_id 共用它。

    优先取画像里的 `project_id`（工程自报的规范名，来自锚点的正文表格或 YAML
    frontmatter）；缺失或 slugify 后为空时，回退到路径推导的 agent_slug()。

    run 目录名**不**走这里——S0 建目录时画像尚未生成，拿不到 project_id，
    所以它仍按 `--agent` 路径推导。因此 run 目录名与本函数结果可能不同名，
    这是刻意的（参考「task_id 与 run 目录名解耦」）。
    """
    profile = profile or {}
    project_id = str(profile.get("project_id") or "").strip()
    if project_id:
        # fallback="" 让纯符号类 project_id 返回空串，从而落到下面的回退分支
        slug = slugify(project_id, fallback="")
        if slug:
            return slug
    return agent_slug(profile)


def stamp_now():
    """秒级时间戳：中间态目录与产出目录共用同一种格式。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    """文件内容哈希；缺失返回空串。"""
    path = Path(path)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def sha256_tree(root):
    """目录内容指纹：按相对路径排序后逐个哈希，含路径与内容。"""
    root = Path(root)
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    entries = sorted(
        p for p in root.rglob("*") if p.is_file()
    )
    for path in entries:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()


# ============================== 工作目录 ==============================

def work_path(work_dir, key):
    """按 config.STAGE_FILES 的键取中间态文件路径。"""
    filename = config.STAGE_FILES.get(key, key)
    return Path(work_dir) / filename


def require(condition, message):
    """断言式前置检查；不满足即抛 GoldevalError。"""
    if not condition:
        raise GoldevalError(message)
