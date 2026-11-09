#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章节预拆分（V3 算法）

把 pre_dir 下的 .md 文件按"最浅且 ≥ 2 次出现的标题层级"拆分成章节子文件。
拆分后的章节文件放在 `{stem}_chapters/{idx:02d}__{sanitized-title}__{hash8}.md`。

关键设计：
- 剥 Wiki YAML frontmatter（改进 1）
- detect_split_level：选最浅的、出现 ≥ 2 次的层级（H2 → H3 → H4 → H5 → H6）（改进 2）
- _has_meaningful_content：正文 ≥ 50 字符才算有内容（改进 3）
- 第一个章节从文件头开始（改进 4，含 H1 + intro + orphan H4）
- Wiki 文档忽略 references/ 子目录（改进 5）
- 文件名带清理后的章节标题，hash8 作为内容指纹

被 `preprocessor.py:process_single_file` 在写完完整 .md 之后立即调用。
"""
import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path

from common.document_types import VISION_DOCUMENT_EXTS

# 输出到 <state_root>/logs/cosightbot.log
logger = logging.getLogger("file_watcher.chapter_splitter")

# 匹配 ATX 风格标题：# 开头，# 后至少一个空格
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# 匹配文件开头的 YAML frontmatter（---...---）
_YAML_FRONT_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)

# Windows 非法字符（含控制字符）
_INVALID_FN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows 保留名
_RESERVED_NAMES = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE
)

# 文件名最大长度（章节标题一般不会超过这个长度）
MAX_FILENAME_LEN = 80

# 正文内容最小字符数（去掉标题和 frontmatter 后）
MIN_CONTENT_CHARS = 50

# 混排 PDF/Word 主文档命名后缀（preprocessor 的 `f"{stem}_{ext}".replace(".", "_")`）
_DOC_MD_SUFFIXES = tuple(
    f"_{extension.lstrip('.')}" for extension in VISION_DOCUMENT_EXTS
)
# 章节子目录后缀（preprocessor 命名约定：<stem>_<ext>_chapters/）
_DOC_CHAPTER_DIR_SUFFIX = "_chapters"


# ======== [CoSight-START] feature: chapter-image-set ========
# 匹配 markdown 图片引用 `![alt](url)` —— 抓 url 即可
_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _extract_image_basenames(content: str) -> set[str]:
    """从章节正文里抓 `![...](<relpath>)` 图片引用的 basename 集合。

    basename 用于跨 images_index.json 反查（不依赖完整 relpath）——章节子文件
    引用形如 `test_mixed_kfa_pdf_images/p001_x0010.png` 时，basename 是
    `p001_x0010.png`，对应 images_index.json 条目的 `image_relpath` basename。
    """
    refs = set()
    for m in _IMG_REF_RE.finditer(content):
        url = m.group(1).strip()
        if "://" in url or url.startswith("/"):
            continue
        basename = url.rsplit("/", 1)[-1].strip()
        if basename:
            refs.add(basename)
    return refs


def _populate_chapter_relpaths(
    md_path: Path,
    chapters_dir: Path,
    written_files: list[tuple[str, str]],
) -> None:
    """二扫所有章节子文件，对每张图反查引用它的章节子文件，更新 images_index.json。

    流程：
    1. 推导主文档 images_index.json 路径（与 doc_image_extractor 命名一致）
    2. 读 images_index.json
    3. 对每个章节子文件：扫描正文里 `![...](<relpath>)` 引用，提取 basename 集合
    4. 对 images_index.json 每张图条目：把"引用了此图 basename"的章节 relpath
       追加到该图条目的 chapter_relpaths 字段
    5. 写回 images_index.json

    只对**混排 PDF/Word** 主文档处理（stem endswith _pdf/_docx/_doc）——
    扫描件没有 `![...](<relpath>)` 引用图（PNG 是单独 _pages/ 目录），
    PPT 走 _pptx_slides/ 不同机制。
    """
    if not md_path.exists():
        return
    # 推导 images_index.json 路径
    # md_path.stem 已 endswith _pdf/_docx/_doc（如 test_mixed_kfa_pdf），
    # 不需要再拼 ext——直接 stem + "_images" 即可
    stem = md_path.stem
    rel_dir = md_path.parent
    if not any(stem.endswith(s) for s in _DOC_MD_SUFFIXES):
        return
    images_dir_name = f"{stem}_images"
    images_index_path = rel_dir / images_dir_name / "images_index.json"
    if not images_index_path.is_file():
        return

    try:
        data = json.loads(images_index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.info(
            f"chapter_splitter: parse images_index failed {images_index_path}: {e}"
        )
        return
    if data.get("kind") != "doc_images" or data.get("doc_type") != "mixed":
        return
    entries = data.get("images") or []
    if not isinstance(entries, list):
        return

    # 对每张图：basename → chapter_relpaths 反向映射
    image_to_chapters: dict[str, list[str]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        image_relpath = e.get("image_relpath", "") or ""
        basename = image_relpath.rsplit("/", 1)[-1]
        image_to_chapters[basename] = e.setdefault("chapter_relpaths", [])

    for chapter_relpath, content in written_files:
        basenames = _extract_image_basenames(content)
        for basename in basenames:
            if basename in image_to_chapters:
                chapter_relpaths = image_to_chapters[basename]
                if chapter_relpath not in chapter_relpaths:
                    chapter_relpaths.append(chapter_relpath)

    try:
        images_index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.info(
            f"chapter_splitter: write images_index failed {images_index_path}: {e}"
        )
# ======== [CoSight-END] feature: chapter-image-set ========


def _strip_yaml_frontmatter(text: str) -> str:
    """改进 1：剥离 Wiki 同步元信息等。"""
    return _YAML_FRONT_RE.sub("", text, count=1)


def _has_meaningful_content(text: str) -> bool:
    """改进 3：去掉标题和 frontmatter 后正文 ≥ 50 字符。"""
    body = _HEADER_RE.sub("", text)
    body = _strip_yaml_frontmatter(body)
    return len(body.strip()) >= MIN_CONTENT_CHARS


def detect_split_level(md_text: str) -> int:
    """改进 2：选最浅的、出现 ≥ 2 次的层级（H2 → H3 → H4 → H5 → H6）。

    只考虑 H2-H6 作为 section-like 层级（H4+ 通常是页脚/装饰，不应作为切分层级）。
    返回 0 表示没有可拆的层级（所有层级 count < 2）。
    """
    level_counts = {lvl: 0 for lvl in range(2, 7)}
    for m in _HEADER_RE.finditer(md_text):
        lvl = len(m.group(1))
        if lvl in level_counts:
            level_counts[lvl] += 1
    for lvl in [2, 3, 4, 5, 6]:
        if level_counts[lvl] >= 2:
            return lvl
    return 0


def sanitize_filename(name: str, max_len: int = MAX_FILENAME_LEN) -> str:
    """§8.3.1：清理文件名非法字符，确保 Windows/Mac/Linux 都可用。

    - Windows 非法字符 `<>:"/\\|?*` + 控制字符 → _
    - 首尾空白 / . → 删除
    - Windows 保留名 CON/PRN/... → 前缀 _
    - 长度 > 80 → 截断
    - 空字符串 → _
    """
    # 替换非法字符
    name = _INVALID_FN_CHARS.sub("_", name)
    # 去掉首尾空白和 .
    name = name.strip(" .")
    # Windows 保留名
    if _RESERVED_NAMES.match(name):
        name = "_" + name
    # 截断
    if len(name) > max_len:
        name = name[:max_len].rstrip(" ._")
    return name or "_"


def _chapter_filename(idx: int, title: str, content_hash: str, max_len: int = MAX_FILENAME_LEN) -> str:
    """§8.3.2：拼装 {idx:02d}__{sanitized-title}__{hash8}.md。

    ``max_len`` is the caller-computed budget based on the actual
    ``chapters_dir`` path length, so the resulting full path stays under
    Windows MAX_PATH (260).
    """
    safe_title = sanitize_filename(title, max_len=max_len)
    return f"{idx:02d}__{safe_title}__{content_hash[:8]}.md"


def _is_in_references_dir(md_path: Path) -> bool:
    """改进 5：判断 .md 是否在 Wiki 文档的 references/ 子目录下（要跳过）。

    路径段匹配（不是子串匹配），避免误判文件名中含 "references" 的文档。
    大小写不敏感（macOS 文件系统默认大小写不敏感）。
    """
    return "references" in [p.lower() for p in md_path.parts]


def _to_long_path(path: Path) -> Path:
    r"""On Windows, return a ``\\?\``-prefixed Path to bypass MAX_PATH (260).

    The prefix tells the Win32 API to use the long-path form, supporting
    paths up to 32767 chars. We re-derive the absolute path so the
    prefix applies to a canonical, fully-resolved target.
    """
    if os.name != "nt":
        return path
    abs_str = str(path.resolve())
    if abs_str.startswith("\\\\?\\"):
        return Path(abs_str)
    if abs_str.startswith("\\\\"):
        # UNC path: \\server\share → \\?\UNC\server\share
        return Path("\\\\?\\UNC" + abs_str[1:])
    return Path("\\\\?\\" + abs_str)


def split_md_by_chapters(md_path: Path) -> int:
    """把 .md 按 V3 算法拆分成章节子文件。返回拆出的章节数。

    拆分后的目录布局：
        {parent}/{stem}_chapters/{idx:02d}__{title}__{hash8}.md
        {parent}/{stem}.md    ← 完整文档保留（CoSightBot 可回退读取）

    Returns: 拆出的章节数；0 表示不拆或失败。
    """
    if not md_path.exists() or md_path.suffix.lower() != ".md":
        return 0
    if _is_in_references_dir(md_path):
        # Wiki 引用资料不参与拆分
        return 0

    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"chapter_splitter: read failed {md_path}: {e}")
        return 0

    # 改进 1：剥 Wiki YAML frontmatter
    text = _strip_yaml_frontmatter(text)

    # 清理旧 hash 残留：章节文件名带 hash8 作内容指纹 → 内容变了 hash 就变 →
    # 旧 hash 文件留在 _chapters/ 里。在分析"该不该分章"前先清，保证
    # 任何返回路径（含 split_level=0 / 唯一标题 / 正文不足）overview 树都干净。
    # 读失败 / 不存在 / references 子目录的早返回路径不会到这里。
    chapters_dir = md_path.parent / f"{md_path.stem}_chapters"
    if chapters_dir.exists():
        try:
            shutil.rmtree(chapters_dir)
        except OSError as e:
            logger.warning(f"chapter_splitter: rmtree stale {chapters_dir}: {e}")

    # 改进 3：内容质量检查
    if not _has_meaningful_content(text):
        return 0

    # 改进 2：自适应切分级别
    split_level = detect_split_level(text)
    if split_level == 0:
        return 0

    # 找所有 split-level 标题
    matches = list(_HEADER_RE.finditer(text))
    split_matches = [m for m in matches if len(m.group(1)) == split_level]
    if len(split_matches) < 2:
        return 0

    # 改进 4：第一个章节从文件头开始（包含 H1 + intro + orphan H4）
    sections = []
    for i, m in enumerate(split_matches):
        start = 0 if i == 0 else m.start()
        if i + 1 < len(split_matches):
            end = split_matches[i + 1].start()
        else:
            end = len(text)
        sections.append((m.group(2).strip(), start, end))

    # 写文件
    # chapters_dir 已在 read 之后提前清过（旧 hash 残留），此处只需 mkdir。
    try:
        chapters_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"chapter_splitter: mkdir failed {chapters_dir}: {e}")
        return 0

    # Windows MAX_PATH (260) budget: each chapter filename is
    # ``{idx:02d}__{title}__{hash8}.md`` = 16 + len(title). Truncate
    # ``title`` so the full path stays under 260 chars; otherwise
    # ``write_text()`` fails with [Errno 2] No such file or directory.
    # We keep a 5-char safety margin because some Windows versions count
    # the trailing NUL terminator strictly, and 260 == MAX_PATH is the
    # exact boundary that some APIs reject.
    _chapter_filename_overhead = 16
    _windows_max_path = 260
    _path_budget = _windows_max_path - len(str(chapters_dir)) - 1 - _chapter_filename_overhead
    _sanitize_max_len = min(MAX_FILENAME_LEN, max(20, _path_budget - 5))

    written = 0
    written_files: list[tuple[str, str]] = []  # (chapter_relpath, content)
    for idx, (header, start, end) in enumerate(sections, 1):
        content = text[start:end].rstrip() + "\n"
        h = hashlib.md5(content.encode("utf-8")).hexdigest()
        chapter_filename = _chapter_filename(idx, header, h, max_len=_sanitize_max_len)
        chapter_path = chapters_dir / chapter_filename
        # On Windows, prefix with ``\\?\`` to bypass MAX_PATH entirely. The
        # resolved absolute path may be slightly different from the joined
        # one (e.g. forward vs back slashes) so we re-resolve before
        # prefixing.
        if os.name == "nt":
            try:
                long_path = _to_long_path(chapter_path)
            except Exception:
                long_path = chapter_path
        else:
            long_path = chapter_path
        try:
            long_path.write_text(content, encoding="utf-8")
            # 收集 (chapter_relpath, content) 供二扫填充 images_index.json
            chapter_relpath = chapter_path.relative_to(md_path.parent).as_posix()
            written_files.append((chapter_relpath, content))
            written += 1
        except Exception as e:
            logger.warning(
                f"chapter_splitter: write failed {chapter_path}: {e}"
            )

    # ======== [CoSight-START] feature: chapter-image-set ========
    # 切完所有章节后，二扫每张图：找出引用它的章节子文件，更新
    # `<stem>_<ext>_images/images_index.json` 的 `chapter_relpaths` 字段。
    # overview_resolver doc_chapter 路径按此字段精确过滤本章节图集合。
    if written and md_path.stem.endswith(_DOC_MD_SUFFIXES):
        _populate_chapter_relpaths(md_path, chapters_dir, written_files)

    if written:
        logger.info(
            f"chapter_splitter: split {md_path.name} into {written} chapters "
            f"(level=H{split_level}, dir={chapters_dir.name})"
        )
    return written
