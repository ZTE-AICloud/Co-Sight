#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
CoSightBot 可见的 overview.md 路径解析与状态检查 CLI。

复用 runtime/watch_dog/file_watcher/config.py 中的路径函数，
封装成 LLM agent 可调用的命令。推荐经技能入口调用（带环境自检）：

    python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main
    python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main read-doc --node-id f001

也可直接调用（跳过 preflight 自检）：

    python runtime/common/overview_resolver.py --agent-id main [--check-only]

退出码：
    0 = 全部 route 就绪
    1 = 有 route 未就绪
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path


def _resolve_runtime_root() -> Path:
    """定位 runtime 根目录（本模块位于 <workdir>/runtime/common/，parents[1] 即 runtime）。"""
    return Path(__file__).resolve().parents[1]


_src_root = _resolve_runtime_root()
# 把 runtime 和 watch_dog 加入 sys.path，让绝对导入生效
sys.path.insert(0, str(_src_root))
sys.path.insert(0, str(_src_root / "watch_dog"))

from common.port_resolver import cosight_state_root  # noqa: E402
from common.logging_setup import log_event, preview_items, preview_text  # noqa: E402
from watch_dog.file_watcher.config import (  # noqa: E402
    get_llamaindex_storage_dirs,
    get_session_storage_dirs,
)

# 日志输出到 <state_root>/logs/cosightbot.log
logger = logging.getLogger("overview_resolver")

# 从 overview_builder 导入唯一的 OVERVIEW_HEADER 常量（写在 overview.md 文件头部，
# 以及 merged_overview 顶部都使用同一份）。overview_resolver 自身不维护这份字符串，
# 避免双份内容漂移。
sys.path.insert(0, str(_src_root / "watch_dog"))
from watch_dog.file_watcher.overview_builder import (  # noqa: E402
    OVERVIEW_HEADER,
    _read_indexed_files,
)
from watch_dog.file_watcher.artifact_paths import (  # noqa: E402
    POWERPOINT_SLIDE_SUFFIXES,
    SCANNED_PAGE_SUFFIXES,
)


def _strip_overview_header(content: str) -> str:
    """如果 overview.md 开头包含标准 header（由 overview_builder.py 写入），剥掉它。

    overview.md 的结构：
        ## 📋 overview 索引说明（...）
        ...
        ---

        <pre_dir 绝对路径>/
        ├── [DIR] xxx/
        ...

    剥掉 header 后只剩树形部分，避免 merged_overview 中 header 重复。
    兼容旧版本（没有 header 的 overview.md）：原样返回。
    兼容树根为 `[<name>]/` 老格式（按 `---` 切分即可，不需要识别根标签格式）。
    """
    marker = "## 📋 overview 索引说明"
    if not content.lstrip().startswith(marker):
        return content
    # 切分：以单独的 "---" 行作为 header 结束标记，header 之后全部为树形
    lines = content.split("\n")
    in_header = True
    tree_lines: list[str] = []
    for line in lines:
        if in_header:
            if line.strip() == "---":
                in_header = False
            continue
        tree_lines.append(line)
    # 去掉树根之前的空行
    while tree_lines and not tree_lines[0].strip():
        tree_lines.pop(0)
    return "\n".join(tree_lines)


# 匹配 `[F###]` 节点行（V3 节点 ID 模式）
# - 前缀缩进 + [├└]── + 节点 ID + basename
# - 用于 overview_resolver 把本地节点 ID 重写为全局 ID
_LOCAL_NODE_ID_RE = re.compile(r"\[(?P<local>[A-Z]\d{3,})\]")


def _load_node_index(lan_dir: Path) -> dict[str, str]:
    """从 lan_dir/node_index.json 读取节点 ID → rel_path 映射。

    文件不存在或解析失败时返回空 dict（调用方需 fallback）。

    schema：``{local_id: rel_path_str}``。历史版本在同一文件里还存过
    ``"_meta_:<local_id>"`` 形式的元数据条目；该字段已被移除（PPT 元数据
    由本模块运行时从 ``<stem>_pptx_slides/slides_index.json`` 反查），但为
    兼容可能仍在过渡的旧版文件，value 不是字符串的条目统一过滤掉。
    """
    node_index_path = lan_dir / "node_index.json"
    if not node_index_path.exists():
        return {}
    try:
        data = json.loads(node_index_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # value 必须是字符串；过滤掉历史遗留的 _meta_:* dict 条目
            # 与任何异常结构。
            return {
                k: str(v)
                for k, v in data.items()
                if isinstance(v, str)
            }
    except Exception as e:
        logger.warning(
            f"_load_node_index: parse failed path={node_index_path} error={e}"
        )
    return {}


def _renumber_tree_text(tree_text: str, local_to_global: dict[str, str]) -> str:
    """把 tree_text 里的 `[F###]` 本地节点 ID 重写为全局 ID（如 `[f001]`）。

    用于多 route 合并场景：每个 route 的 overview.md 用本地 F001/F002/...
    跨 route 时本地 ID 会冲突，merged_overview 需要用全局 ID 区分。
    """
    def _replace(m: re.Match) -> str:
        local = m.group("local")
        global_id = local_to_global.get(local)
        if global_id is None:
            return m.group(0)  # 未知 ID 保持原样（不会发生，仅防御）
        return f"[{global_id}]"

    return _LOCAL_NODE_ID_RE.sub(_replace, tree_text)


def _strip_ppt_suffix(stem: str) -> str:
    """把 <source_stem>_pptx / <source_stem>.pptx 等命名归一到 <source_stem>。

    与 overview_builder._strip_ppt_suffix 行为对齐；存在两份拷贝是为了
    common 层不依赖 file_watcher/。两份共改是设计上能接受的（只在 PPT
    命名约定变更时同步）。
    """
    lower = stem.lower()
    for suffix in (
        ".pptm",
        ".pptx",
        ".ppt",
        "_pptm",
        "_pptx",
        "_ppt",
    ):
        if lower.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _is_ppt_main_doc_relpath(rel_path: str) -> bool:
    """判断 rel_path 是否指向 PPT 主文档（python-pptx 整段提取的 .md）。"""
    lower = Path(rel_path).name.lower()
    return lower.endswith(
        (
            ".ppt.md",
            ".pptx.md",
            ".pptm.md",
            "_ppt.md",
            "_pptx.md",
            "_pptm.md",
        )
    )


def _is_ppt_slide_relpath(rel_path: str) -> bool:
    """判断 rel_path 是否指向 <stem>_pptx_slides/ 下的 .md（per-slide）。

    路径模式：父目录名以 ``_pptx_slides`` 结尾，且 basename 以 ``Slide_`` 开头。
    """
    parts = Path(rel_path).parts
    if not parts:
        return False
    if not any(
        any(p.lower().endswith(suffix) for suffix in POWERPOINT_SLIDE_SUFFIXES)
        for p in parts
    ):
        return False
    return Path(rel_path).name.lower().startswith("slide_")


def _resolve_doc_relpath(
    pre_dir: Path,
    source_stem: str,
    *,
    preferred_ext: str | None = None,
) -> str:
    """在 pre_dir 下探测 source_stem 对应的 PPT 主文档 .md，按下列优先级：

    1. ``<source_stem>_pptx.md`` （新版下划线命名）
    2. ``<source_stem>.pptx.md``  （旧版 dot 命名）
    3. ``<source_stem>_ppt.md`` / ``<source_stem>.ppt.md``
    4. 兜底返回 ``<source_stem>_pptx.md``

    返回**相对 pre_dir 的路径**，绝对路径 = ``pre_dir / doc_relpath``。
    """
    extensions = [
        preferred_ext,
        "pptm",
        "pptx",
        "ppt",
    ]
    ordered_extensions = tuple(dict.fromkeys(ext for ext in extensions if ext))
    candidates = tuple(
        candidate
        for ext in ordered_extensions
        for candidate in (f"{source_stem}_{ext}.md", f"{source_stem}.{ext}.md")
    )
    for c in candidates:
        if (pre_dir / c).is_file():
            return c
    return candidates[0]


def _rehydrate_ppt_meta(pre_dir: Path, rel_path: str) -> dict | None:
    """按 PPT 节点 rel_path 反查 ``<stem>_pptx_slides/slides_index.json``。

    节点是 PPT 主文档：
        rel_path 形如 ``<stem>_pptx.md``，归一到 ``<stem>_pptx_slides/slides_index.json``，
        返回 ``{kind: "ppt_slides", index_relpath, slide_count, doc_relpath}``。

    节点是 PPT 幻灯片：
        rel_path 形如 ``<stem>_pptx_slides/Slide_NN_<title>.md``，从 slides_index.json
        的 pages 列表中按 md_relpath 反查对应页条目，返回 ``{kind, doc_relpath,
        image_relpath, page_index, index_relpath, slide_count}``。

    非 PPT 节点返回 ``None``（调用方应跳过 PPT 路径处理）。
    找不到 slides_index.json / 解析失败 → 返回 ``None``。

    历史兼容性：此前 `doc_node_id` 字段是个本地节点 ID（"F001"），多 route
    合并后会被改写。本 helper 改用 `doc_relpath` —— 源 PPT 主文档的 rel_path，
    跨 route 稳定，调用方需要时可直接 `read-doc --rel-path` 二次定位。
    """
    rel_p = Path(rel_path)
    is_slide = _is_ppt_slide_relpath(rel_path)
    is_main = _is_ppt_main_doc_relpath(rel_path)
    if not (is_slide or is_main):
        return None
    if is_main:
        source_stem = _strip_ppt_suffix(rel_p.stem)
        lower_stem = rel_p.stem.lower()
        ppt_ext = next(
            (
                ext
                for ext in ("pptm", "pptx", "ppt")
                if lower_stem.endswith(f"_{ext}")
                or lower_stem.endswith(f".{ext}")
            ),
            "pptx",
        )
        slides_dir_rel = f"{source_stem}_{ppt_ext}_slides"
        doc_relpath = rel_path  # 主文档节点的 rel_path 就是它本身
    else:
        # slide 路径：父目录 <source_stem>_<ppt-ext>_slides
        parent_dir = rel_p.parts[-2]
        slide_suffix = next(
            (
                suffix
                for suffix in POWERPOINT_SLIDE_SUFFIXES
                if parent_dir.lower().endswith(suffix)
            ),
            None,
        )
        if slide_suffix is None:
            return None
        source_stem = parent_dir[: -len(slide_suffix)]
        slides_dir_rel = parent_dir
        ppt_ext = slide_suffix[1 : -len("_slides")]
        doc_relpath = _resolve_doc_relpath(
            pre_dir,
            source_stem,
            preferred_ext=ppt_ext,
        )

    index_abs = pre_dir / slides_dir_rel / "slides_index.json"
    if not index_abs.is_file():
        return None
    try:
        index_data = json.loads(index_abs.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(
            f"_rehydrate_ppt_meta: failed to parse {index_abs}: {e}"
        )
        return None
    if not isinstance(index_data, dict) or index_data.get("kind") != "ppt_slides":
        return None
    pages = index_data.get("pages") or []
    index_relpath = f"{slides_dir_rel}/slides_index.json"

    if is_main:
        return {
            "kind": "ppt_slides",
            "index_relpath": index_relpath,
            "slide_count": len(pages),
            "doc_relpath": doc_relpath,
        }

    # 幻灯片节点:按 md_relpath basename 严格匹配
    target_basename = rel_p.name
    matched = None
    for page in pages:
        if not isinstance(page, dict):
            continue
        md_relpath = page.get("md_relpath") or ""
        if not md_relpath:
            continue
        if Path(md_relpath).name == target_basename:
            matched = page
            break
    if matched is None:
        return None
    image_relpath = matched.get("image_relpath") or ""
    return {
        "kind": "ppt_slide",
        "doc_relpath": doc_relpath,
        "image_relpath": (
            f"{slides_dir_rel}/{image_relpath}" if image_relpath else ""
        ),
        "page_index": matched.get("page_index"),
        "index_relpath": index_relpath,
        "slide_count": len(pages),
    }


# ======== [CoSight-START] feature: pdf-word-image-vision ========
_DOC_PAGE_MD_RE = re.compile(r"^page_\d+\.md$", re.IGNORECASE)
# 预处理 md 命名后缀（report.pdf → report_pdf.md）；_docx 必须先于 _doc 匹配
_DOC_MD_SUFFIXES = ("_pdf", "_docx", "_docm", "_doc")
# 章节子目录后缀（preprocessor 命名约定：<stem>_<ext>_chapters/）
_DOC_CHAPTER_DIR_SUFFIX = "_chapters"

# 多模态模型识别后，遇到"示意图"类图片的还原规范。
# 优先级：架构图 / 拓扑图 / 模块关系图 / 流程图 / 系统框图 → 框线结构；
# 其他类型（截图、照片、扫描表格）→ 仍按文字描述处理。
# 用单独常量 + append 到所有图像识别的 instructions，避免在每条里重复粘贴同一段
# 中文/Unicode，长度会爆。
_DIAGRAM_RENDERING_INSTRUCTION = (
    "\n\n**示意图还原规范**：如果识别结果中有**架构图 / 拓扑图 / 模块关系图 / "
    "流程图 / 系统框图**等结构化示意图，**优先用形象化的框线结构**还原原图——"
    "使用 Unicode 框线字符（如 ┌─┐│└┘├┤┬┴┼）画出方框，"
    "模块名 / 组件名放在框内，连接关系用箭头（→ / ← / ↑ / ↓）表示，"
    "尽量保持原图的层级与布局；还原后再附简要文字说明。"
    "**不要**用纯文字段落描述代替框线还原。"
)
# ======== [CoSight-END] feature: pdf-word-image-vision ========


def _is_doc_page_relpath(rel_path: str) -> bool:
    """判断 rel_path 是否指向 <stem>_pages/ 下的 Page_NNN.md（扫描件页面）。"""
    rel_p = Path(rel_path)
    if not rel_p.parent.name.endswith("_pages"):
        return False
    return bool(_DOC_PAGE_MD_RE.match(rel_p.name))


def _is_doc_chapter_relpath(rel_path: str) -> bool:
    """判断 rel_path 是否在 <stem>_<ext>_chapters/ 目录下（混排 PDF/Word 章节子文件）。

    关键限定：必须是混排文档的 _chapters（依赖主文档的 _images 体系）——
    扫描件的 _chapters/ 在 overview_builder._read_indexed_files 已隐藏，
    不会进 read-doc。
    """
    rel_p = Path(rel_path)
    parent_name = rel_p.parent.name
    if not parent_name.endswith(_DOC_CHAPTER_DIR_SUFFIX):
        return False
    # 父目录名必须是 <stem>_<ext>_chapters 形态（含 _pdf/_docx/_doc 之一），
    # 否则推到 _images 目录会落空（防御非 docx 文档的 _chapters）
    main_part = parent_name[: -len(_DOC_CHAPTER_DIR_SUFFIX)]
    return any(main_part.endswith(s) for s in _DOC_MD_SUFFIXES)


def _strip_doc_md_suffix(stem: str) -> str | None:
    """把 report_pdf / report_docx / report_doc 归一到源文件 stem report。

    不是 PDF/Word 主文档命名时返回 None。
    """
    lower = stem.lower()
    for suffix in _DOC_MD_SUFFIXES:
        if lower.endswith(suffix):
            return stem[: -len(suffix)]
    return None


def _rehydrate_doc_image_meta(pre_dir: Path, rel_path: str) -> dict | None:
    """按 PDF/Word 节点 rel_path 反查 images_index.json，注入图片元数据。

    两类节点（与 doc_image_extractor 的产物布局约定一一对应）：

    扫描件页面节点：
        rel_path 形如 ``<stem>_<ext>_pages/Page_NNN.md``，
        索引在 ``<stem>_<ext>_pages/images_index.json``，按 md_relpath 反查本页条目，
        返回 ``{kind: "doc_page", ocr_status, image_relpath, page_index, ...}``。

    混排主文档节点：
        rel_path 形如 ``<stem>_pdf.md`` / ``<stem>_docx.md`` / ``<stem>_doc.md``，
        索引在 ``<stem>_<ext>_images/images_index.json``（目录名与 md 全 stem 对齐），
        返回全部图片条目，
        ``{kind: "doc_mixed", images: [{image_id, image_relpath, ocr_status, ...}]}``。

    非 PDF/Word 图片体系节点返回 None；索引缺失/解析失败返回 None。
    """
    rel_p = Path(rel_path)

    if _is_doc_page_relpath(rel_path):
        images_dir_rel = rel_p.parent.as_posix()
        index_abs = pre_dir / images_dir_rel / "images_index.json"
        kind = "doc_page"
        match_basename = rel_p.name
        match_field = "md_relpath"
    elif _is_doc_chapter_relpath(rel_path):
        # 章节子文件：父目录名 <stem>_<ext>_chapters → 剥 _chapters → 主 md 全 stem
        # 主 md 所在目录 = rel_p.parent.parent；images_dir = 主 md 同级 <stem>_<ext>_images
        parent_name = rel_p.parent.name
        main_stem_with_ext = parent_name[: -len(_DOC_CHAPTER_DIR_SUFFIX)]
        images_dir = rel_p.parent.parent / f"{main_stem_with_ext}_images"
        images_dir_rel = images_dir.as_posix()
        index_abs = pre_dir / images_dir_rel / "images_index.json"
        kind = "doc_chapter"
        match_basename = ""
        match_field = ""
    else:
        stem = _strip_doc_md_suffix(rel_p.stem)
        if stem is None:
            return None
        # 产物目录命名与 preprocessor 主 md（<stem>_<ext>.md）对齐：
        # <stem>_<ext>_images —— 直接用 md 全 stem，不再 strip 后缀
        images_dir = rel_p.parent / f"{rel_p.stem}_images"
        images_dir_rel = images_dir.as_posix()
        index_abs = pre_dir / images_dir_rel / "images_index.json"
        kind = "doc_mixed"
        match_basename = ""
        match_field = ""

    if not index_abs.is_file():
        return None
    try:
        index_data = json.loads(index_abs.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"_rehydrate_doc_image_meta: parse failed {index_abs}: {e}")
        return None
    if not isinstance(index_data, dict) or index_data.get("kind") != "doc_images":
        return None

    entries = [e for e in (index_data.get("images") or []) if isinstance(e, dict)]
    index_relpath = f"{images_dir_rel}/images_index.json"
    base = {
        "doc_type": index_data.get("doc_type"),
        "ocr_engine": index_data.get("ocr_engine"),
        "index_relpath": index_relpath,
    }

    if kind == "doc_page":
        matched = None
        for e in entries:
            md_relpath = e.get("md_relpath") or ""
            if md_relpath and Path(md_relpath).name == match_basename:
                matched = e
                break
        if matched is None:
            return None
        image_relpath = matched.get("image_relpath") or ""
        return {
            **base,
            "kind": "doc_page",
            "image_id": matched.get("image_id"),
            "ocr_status": matched.get("ocr_status"),
            "page_index": matched.get("page_index"),
            # 与 PPT slides 约定一致：image_relpath 拼上目录前缀，相对 pre_dir
            "image_relpath": (
                f"{images_dir_rel}/{image_relpath}" if image_relpath else ""
            ),
        }

    # doc_mixed / doc_chapter：返回主文档全部图片条目（image_relpath 拼目录前缀，相对 pre_dir）
    # doc_chapter 复用主文档的 images_index.json——但 images_index.json 的每张图
    # 条目有 chapter_relpaths 字段（chapter_splitter 切完章节后二扫填充），
    # 列出"哪些章节子文件引用了此图"。doc_chapter 节点**只**返回引用了当前
    # rel_path 的图，避免 LLM 读主文档全部图导致误关联无关图 + 浪费 token。
    # 兼容老数据：chapter_relpaths 字段缺失/为空时 fallback 走主文档全部图。
    if kind == "doc_chapter":
        # 收集所有 chapter_relpaths 含当前 rel_path 的图条目
        chapter_images = [
            e for e in entries
            if isinstance(e, dict)
            and rel_path in (e.get("chapter_relpaths") or [])
        ]
        if chapter_images:
            # 严格按 chapter_relpaths 过滤（精确集合）
            images = [
                {
                    "image_id": e.get("image_id"),
                    "ocr_status": e.get("ocr_status"),
                    "page_index": e.get("page_index"),
                    "image_relpath": (
                        f"{images_dir_rel}/{e.get('image_relpath', '')}"
                        if e.get("image_relpath") else ""
                    ),
                }
                for e in chapter_images
            ]
        else:
            # fallback：chapter_relpaths 为空（老数据 / 切章节未跑后处理）
            images = [
                {
                    "image_id": e.get("image_id"),
                    "ocr_status": e.get("ocr_status"),
                    "page_index": e.get("page_index"),
                    "image_relpath": (
                        f"{images_dir_rel}/{e.get('image_relpath', '')}"
                        if e.get("image_relpath") else ""
                    ),
                }
                for e in entries
                if isinstance(e, dict)
            ]
        return {
            **base,
            "kind": "doc_chapter",
            "main_md_stem": main_stem_with_ext,  # 供调用方/调试用
            "images": images,
        }
    # doc_mixed（主文档）：返回全部图
    images = []
    for e in entries:
        image_relpath = e.get("image_relpath") or ""
        images.append({
            "image_id": e.get("image_id"),
            "ocr_status": e.get("ocr_status"),
            "page_index": e.get("page_index"),
            "image_relpath": (
                f"{images_dir_rel}/{image_relpath}" if image_relpath else ""
            ),
        })
    return {**base, "kind": "doc_mixed", "images": images}
# ======== [CoSight-END] feature: pdf-word-image-vision ========


# ======== [CoSight-START] feature: web-image-vision ========
def _rehydrate_web_image_meta(pre_dir: Path, rel_path: str) -> dict | None:
    """按 .md 节点反查同目录 ``images_index.json``,注入网页内嵌图元数据。

    与 ``_rehydrate_doc_image_meta`` 平级,但走另一套路径约定:
      - **wiki 单页**:
        ``<slot>/<subpage>/<subpage>.md`` + ``<slot>/<subpage>/images_index.json``
      - **通用网页单页**:
        ``<slot_dir>/<title>.md`` + ``<slot_dir>/images_index.json``

    两种产物 layout 都满足:``rel_path.parent / images_index.json`` 恰好是索引所在。

    与 doc 体系的**互斥约束**(由 caller 在 ``_read_doc_by_node_id`` 里加守卫):
      一个 .md 节点要么走 ``_rehydrate_doc_image_meta``(匹配 ``*_pdf.md`` /
      ``*_docx.md`` / ``*_doc.md`` / ``<stem>_<ext>_pages/Page_NNN.md``),
      要么走本函数(任意 .md),不可能同时命中。

    Returns:
        ``None`` —— rel_path 非 .md / 索引文件不存在 / 解析失败 /
        ``kind != "web_images"`` 时返回。
        ``{"kind": "web_images", "ocr_engine", "index_relpath", "images": [...]}"`` —— 命中时。
    """
    rel_p = Path(rel_path)
    if rel_p.suffix.lower() != ".md":
        return None

    parent_dir = pre_dir / rel_p.parent
    index_abs = parent_dir / "images_index.json"
    if not index_abs.is_file():
        return None

    try:
        index_data = json.loads(index_abs.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug(f"_rehydrate_web_image_meta: parse failed {index_abs}: {e}")
        return None

    if not isinstance(index_data, dict) or index_data.get("kind") != "web_images":
        return None

    entries = [e for e in (index_data.get("images") or []) if isinstance(e, dict)]
    index_relpath = (rel_p.parent / "images_index.json").as_posix()

    images: list[dict] = []
    for e in entries:
        image_relpath = e.get("image_relpath") or ""
        images.append({
            "image_id": e.get("image_id"),
            "ocr_status": e.get("ocr_status"),
            # image_relpath 在索引里是相对 index_dir —— 把它拼成相对 pre_dir 的 rel
            "image_relpath": (
                f"{rel_p.parent.as_posix()}/{image_relpath}" if image_relpath else ""
            ),
            "source_url": e.get("source_url") or "",
        })

    return {
        "kind": "web_images",
        "source_kind": "web_images",
        "doc_type": None,
        "ocr_engine": index_data.get("ocr_engine"),
        "source_url": index_data.get("source") or "",
        "index_relpath": index_relpath,
        "images": images,
    }


# ======== [CoSight-END] feature: web-image-vision ========


# 全局节点 ID 路由前缀长度（md5(route_key) 的 hex 前缀）；同批路由碰撞时
# 确定性加长（见 _assign_route_prefixes）。
_ROUTE_PREFIX_LEN = 3


def _route_stable_key(route: dict) -> str:
    """路由的稳定标识：kind + lan_dir 相对 lancedb/ 根的路径。

    不含 workspace 绝对前缀，与机器无关、跨调用恒定；路由目录名本身已编码
    绑定路径/agent/session 的哈希，天然唯一。
    """
    kind = route.get("kind", "")
    parts = Path(route["lan_dir"]).parts
    rel = parts[-1] if parts else ""
    if "lancedb" in parts:
        idx = len(parts) - 1 - parts[::-1].index("lancedb")
        if idx + 1 < len(parts):
            rel = "/".join(parts[idx + 1:])
    return f"{kind}:{rel}"


def _assign_route_prefixes(routes: list[dict]) -> list[str]:
    """为每个路由分配稳定短前缀（md5(route_key) 的 hex 前缀）。

    长度从 _ROUTE_PREFIX_LEN 开始；同批路由前缀碰撞时对全体确定性加长
    （+3 直至无碰撞）——同一路由集合的分配结果逐位恒定，路由增删不影响
    存量路由的前缀（除非恰好触发碰撞加长）。
    """
    keys = [_route_stable_key(r) for r in routes]
    digests = [hashlib.md5(k.encode("utf-8")).hexdigest() for k in keys]
    length = _ROUTE_PREFIX_LEN
    while True:
        prefixes = [d[:length] for d in digests]
        if len(set(prefixes)) == len(prefixes):
            return prefixes
        length += 3


def _is_chapter_alias(rel_path: str) -> bool:
    """章节视图文件（``*_chapters/``）不计入文档分母。"""
    return any(part.endswith("_chapters") for part in Path(rel_path).parts)


_TREE_NODE_ID_RE = re.compile(r"\[(F\d{3,})\](?=\s+\S)")


def _overview_tree_rels(overview_md: str | Path, local_index: dict) -> set[str]:
    """overview 树中实际渲染的 rel_path 集合。

    M-3 下主文档为空/仅 TOC 时，部分 `_chapters/` 文件被提升进树；这些
    章节不再算 alias，应计入文档分母，也才能被 section 索引/动态检索看到。
    未提升的章节仍只在 node_index 里，作为 read-doc 兼容 alias。
    """
    path = Path(overview_md) if overview_md else None
    if not path or not path.is_file():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    marker = "# overview-format:"
    if marker in text:
        text = text.split(marker, 1)[1]
    out: set[str] = set()
    for node_id in _TREE_NODE_ID_RE.findall(text):
        rel = local_index.get(node_id)
        if isinstance(rel, str):
            out.add("/".join(Path(rel).parts))
    return out


def _count_doc_nodes(global_node_index: dict) -> int:
    """文档节点数（排除章节 alias）；动态分母/Tier 统计使用。"""
    return sum(
        1 for entry in global_node_index.values()
        if not entry.get("is_alias")
    )


def _lookup_global_id(global_node_index: dict, node_id: str) -> str | None:
    """归一化查询全局节点 ID。

    精确命中优先；未命中且形如 ``f###``/``F###``（无路由前缀的旧式全局 ID
    或本地 ID）时按数字后缀**唯一**匹配兜底——单路由场景下 caller 传本地
    ID "F001" 的历史兼容。多候选（跨路由歧义）返回 None，宁缺毋错。
    """
    nid = node_id.lower() if isinstance(node_id, str) else node_id
    if nid in global_node_index:
        return nid
    m = re.fullmatch(r"f(\d{3,})", nid or "")
    if m:
        # 优先按 entry 的 local_id 精确匹配：仅靠数字后缀会被
        # F006 / F1006 这类不同位数 ID 误伤（两者都以 "006" 结尾）。
        candidates = [
            g for g, entry in global_node_index.items()
            if str(entry.get("local_id", "")).lower() == nid
        ]
        if not candidates:
            # 兼容没有 local_id 字段的旧调用方/测试数据。
            candidates = [g for g in global_node_index if g.endswith(m.group(1))]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _build_global_node_index(
    routes: list[dict],
) -> tuple[dict[str, dict], list[tuple[dict, dict[str, str]]]]:
    """合并多 route 的 node_index，分配全局 ID。

    Returns:
        global_node_index: {global_id: {route_kind, rel_path, route_label, pre_dir,
                                         overview_md}}
            — 注意：不再带 ``_meta_`` 中转的 PPT 元数据字段
            （kind / image_relpath / doc_node_id / page_index / slide_count /
            index_relpath），这些由 ``_read_doc_by_node_id`` 在 read-doc 入口
            根据 rel_path 反查 ``<stem>_pptx_slides/slides_index.json`` 注入。
        per_route_remap: list[(route, text_remap)] —— 每个 route 自己的 {local_id: global_id}
                       用于改写该 route 的 overview.md 文本（避免多 route 同名 local_id 互相覆盖）
    """
    global_node_index: dict[str, dict] = {}
    per_route_remap: list[tuple[dict, dict[str, str]]] = []
    prefixes = _assign_route_prefixes(routes)
    # 路由顺序：session 优先于 agent（与 collect_routes 一致，文档优先级）
    for route, prefix in zip(routes, prefixes):
        lan_dir = Path(route["lan_dir"])
        local_index = _load_node_index(lan_dir)
        if not local_index:
            # 没找到 node_index.json 时仍然记录一个空 remap，确保 overview 文本被原样保留
            per_route_remap.append((route, {}))
            continue
        text_remap: dict[str, str] = {}
        tree_rels = _overview_tree_rels(route.get("overview_md", ""), local_index)
        for local_id, rel_path in local_index.items():
            m = re.match(r"^F(\d{3,})$", local_id)
            # 防御：非标准本地 ID（历史/异常数据）原样小写作后缀
            suffix = m.group(1) if m else local_id.lower()
            global_id = f"f{prefix}{suffix}"
            text_remap[local_id] = global_id
            rel_norm = "/".join(Path(rel_path).parts)
            global_node_index[global_id] = {
                "route_kind": route["kind"],
                "route_label": route["label"],
                "pre_dir": route["pre_dir"],
                "rel_path": rel_path,
                # 本地 ID（F###）：旧调用方传 F### 时用于精确反查全局 ID
                "local_id": local_id,
                # 章节 alias 仅用于旧 read-doc 兼容，不进入文档分母；
                # M-3 提升进 overview 树的章节视同普通文档。
                "is_alias": _is_chapter_alias(rel_path) and rel_norm not in tree_rels,
                # 给 read-doc 用：overview.md 原始路径
                "overview_md": route["overview_md"],
            }
        per_route_remap.append((route, text_remap))
    return global_node_index, per_route_remap


def _resolve_node_id_meta(
    node_id: str,
    routes: list[dict],
) -> dict:
    """把节点 ID 解析为 abs_path + kind 元数据（**不读文件正文**）。

    与 _read_doc_by_node_id 的差别：
    - 不读 abs_path.read_text()，省 I/O
    - 不返回 content / size_bytes / line_count 字段
    - 显式把节点 kind 归一化为统一命名：
      * chapter / image / page / slide / main_doc / unknown
    - 供只需节点元数据（不读正文）的轻量调用方使用

    Returns:
        dict: {ok, node_id, abs_path, rel_path, kind, route_kind, route_label,
               pre_dir, pre_dir_id} 或 {ok: False, error, node_id}
    """
    global_node_index, _ = _build_global_node_index(routes)
    normalized_id = _lookup_global_id(global_node_index, node_id)
    if normalized_id is None:
        return {
            "ok": False,
            "error": f"node_id '{node_id}' not found in any route's node_index",
            "node_id": node_id,
        }

    entry = global_node_index[normalized_id]
    pre_dir = Path(entry["pre_dir"])
    rel_path = entry["rel_path"]
    abs_path = pre_dir / rel_path

    # 节点 kind 判定：按 rel_path 父目录后缀
    kind = _infer_node_kind(rel_path)

    # 注入 PPT / 文档图片元数据（与 _read_doc_by_node_id 行为一致）
    ppt_meta = _rehydrate_ppt_meta(pre_dir, rel_path)
    doc_image_meta = _rehydrate_doc_image_meta(pre_dir, rel_path)
    # 把 slides_index / images_index 中的 kind 优先级提到最高
    if ppt_meta and ppt_meta.get("kind"):
        kind = ppt_meta["kind"]  # ppt_slides / ppt_slide
    elif doc_image_meta and doc_image_meta.get("kind"):
        kind = doc_image_meta["kind"]  # doc_page / doc_mixed / doc_chapter

    result: dict = {
        "ok": True,
        "node_id": normalized_id,
        "rel_path": rel_path,
        "abs_path": str(abs_path),
        "kind": kind,
        "route_kind": entry.get("route_kind", ""),
        "route_label": entry.get("route_label", ""),
        "pre_dir": str(pre_dir),
        "pre_dir_id": entry.get("pre_dir_id", ""),
    }
    if ppt_meta:
        for k, v in ppt_meta.items():
            result[k] = v
    if doc_image_meta:
        for k, v in doc_image_meta.items():
            result.setdefault(k, v)
    return result


def _resolve_all_node_ids(routes: list[dict]) -> dict:
    """批量返回所有节点的 ID → 元数据映射（--all 子命令）。

    Returns:
        dict: {ok: True, count: N, nodes: [{node_id, abs_path, kind, ...}, ...]}
    """
    global_node_index, _ = _build_global_node_index(routes)
    nodes: list[dict] = []
    for nid, entry in global_node_index.items():
        pre_dir = Path(entry["pre_dir"])
        rel_path = entry["rel_path"]
        kind = _infer_node_kind(rel_path)
        ppt_meta = _rehydrate_ppt_meta(pre_dir, rel_path)
        doc_image_meta = _rehydrate_doc_image_meta(pre_dir, rel_path)
        if ppt_meta and ppt_meta.get("kind"):
            kind = ppt_meta["kind"]
        elif doc_image_meta and doc_image_meta.get("kind"):
            kind = doc_image_meta["kind"]
        node_info: dict = {
            "node_id": nid,
            "rel_path": rel_path,
            "abs_path": str(pre_dir / rel_path),
            "kind": kind,
            "route_kind": entry.get("route_kind", ""),
            "route_label": entry.get("route_label", ""),
            "pre_dir": str(pre_dir),
            "pre_dir_id": entry.get("pre_dir_id", ""),
        }
        if ppt_meta:
            for k, v in ppt_meta.items():
                node_info[k] = v
        if doc_image_meta:
            for k, v in doc_image_meta.items():
                node_info.setdefault(k, v)
        nodes.append(node_info)
    return {"ok": True, "count": len(nodes), "nodes": nodes}


def _infer_node_kind(rel_path: str) -> str:
    """按 rel_path 父目录后缀推导节点 kind（统一命名）。

    Returns:
        chapter | image | page | slide | main_doc | unknown
    """
    if not rel_path:
        return "unknown"
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) < 2:
        return "main_doc"  # pre_dir 根下的 .md → 主文档
    parent_name = parts[-2]
    if parent_name.endswith("_chapters"):
        return "chapter"
    if parent_name.endswith(("_pdf_images", "_docx_images", "_doc_images")):
        return "image"
    if parent_name.endswith(SCANNED_PAGE_SUFFIXES):
        return "page"
    if parent_name.endswith(POWERPOINT_SLIDE_SUFFIXES):
        return "slide"
    return "main_doc"


def _parse_line_range(spec: str | None) -> tuple[int | None, int | None]:
    """解析 'A:B' / 'A:' / ':B' / 'A' 为 (start, end)（1-based 含端点）。

    返回 (None, None) 表示不限。非法格式抛 ValueError。
    """
    if not spec:
        return None, None
    spec = spec.strip()
    if not spec:
        return None, None
    if ":" in spec:
        a, _, b = spec.partition(":")
        start = int(a) if a.strip() else None
        end = int(b) if b.strip() else None
    else:
        start, end = int(spec), None
    if start is not None and start < 1:
        raise ValueError("line range start must be >= 1")
    if end is not None and end < 1:
        raise ValueError("line range end must be >= 1")
    if start is not None and end is not None and end < start:
        raise ValueError("line range end must be >= start")
    return start, end


def _read_doc_by_node_id(
    node_id: str,
    routes: list[dict],
    max_chars: int | None = None,
    line_range: str | None = None,
) -> dict:
    """按节点 ID 读取文件全文。

    Args:
        node_id: 全局节点 ID（如 `f001`）；``F001`` 本地 ID 也兼容（自动归一到小写）。
        routes: collect_routes() 返回的路由列表
        max_chars: 正文输出字符上限。None（默认）→ 自动盖帽
            _READDOC_AUTO_CAP_CHARS(30000)，超出截断、置 truncated=true
            （W6 read-doc 健壮性：CLI 自己盖帽，模型不必用 PS 管道 `| head`
            截输出——PS 重定向会把 UTF-8 重编码成 UTF-16 产生乱码坑。
            常量定义在本文件 W6 段、位于本函数之后，def 期不可引用，故用
            None 哨兵在函数体内解析）。传 0 可关闭（测试/内部全量读场景）。
        line_range: 只返回第 A 到 B 行（1-based 含端点），如 "100:200" / "50:" / ":80"。
            与 scan 子命令的 snippets.line_no 配合做定点阅读。

    Returns:
        dict 含 {node_id, rel_path, abs_path, content, size_bytes, line_count, ...} 或 {error}。
        节点为 PPT 幻灯片或 PPT 主文档时,从 slides_index.json 反查注入
        ``kind / index_relpath / slide_count``,幻灯片节点再注入 ``image_relpath`` /
        ``page_index`` / ``doc_relpath``,当前 chat 模型多模态时还附 ``image`` 字段。
    """
    # None → 自动盖帽（常量定义在本文件 W6 段、位于本函数之后，def 期不可引用）
    if max_chars is None:
        max_chars = _READDOC_AUTO_CAP_CHARS
    read_t0 = time.perf_counter()
    log_event(
        logger, "read_doc:start", node_id=node_id, line_range=line_range,
        max_chars=max_chars, routes=len(routes),
    )
    global_node_index, _ = _build_global_node_index(routes)
    # 兼容本地 ID / 旧式无前缀全局 ID：_lookup_global_id 做唯一后缀兜底。
    normalized_id = _lookup_global_id(global_node_index, node_id)
    if normalized_id is None:
        return {
            "ok": False,
            "error": f"node_id '{node_id}' not found in any route's node_index",
            "node_id": node_id,
        }

    try:
        range_start, range_end = _parse_line_range(line_range)
    except ValueError as e:
        return {
            "ok": False,
            "error": f"invalid --line-range '{line_range}': {e}",
            "node_id": node_id,
        }

    entry = global_node_index[normalized_id]
    pre_dir = Path(entry["pre_dir"])
    rel_path = entry["rel_path"]
    abs_path = pre_dir / rel_path

    if not abs_path.exists():
        return {
            "ok": False,
            "error": f"file not found: abs_path={abs_path}",
            "node_id": node_id,
            "rel_path": rel_path,
        }

    try:
        # 用 errors="replace" 防止罕见编码错误阻塞 read-doc
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        size_bytes = abs_path.stat().st_size
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        range_applied = None
        if range_start is not None or range_end is not None:
            lines = content.splitlines()
            lo = (range_start or 1) - 1
            hi = range_end if range_end is not None else len(lines)
            sliced = lines[lo:hi]
            range_applied = {
                "from": lo + 1,
                "to": min(hi, len(lines)),
                "total_lines": len(lines),
            }
            content = "\n".join(sliced)
        truncated = False
        content_total_chars = len(content)
        if max_chars and max_chars > 0 and len(content) > max_chars:
            content = (
                content[:max_chars]
                + f"\n...[read-doc truncated: {content_total_chars} chars total, "
                f"showing first {max_chars}]"
            )
            truncated = True
        result: dict = {
            "ok": True,
            "node_id": normalized_id,
            "rel_path": rel_path,
            "abs_path": str(abs_path),
            "route_kind": entry["route_kind"],
            "route_label": entry["route_label"],
            "size_bytes": size_bytes,
            "line_count": line_count,
            "content": content,
        }
        if range_applied is not None:
            result["line_range"] = range_applied
        if truncated:
            result["truncated"] = True
            result["content_chars_total"] = content_total_chars
        # ======== [CoSight-START] feature: ppt-slides ========
        # 当 node 是 PPT 主文档 / 幻灯片时,按 rel_path 反查 slides_index.json,
        # 把 kind / image_relpath / page_index / slide_count / index_relpath /
        # doc_relpath 注入到返回值。这取代了之前双写 _meta_:* 到 node_index.json
        # 的方案,统一权威源在 slides_index.json。
        ppt_meta = _rehydrate_ppt_meta(pre_dir, rel_path)
        if ppt_meta:
            for k, v in ppt_meta.items():
                result[k] = v
            # 节点是 PPT 幻灯片 + 当前 chat 模型多模态 → 切换为「强制读图模式」:
            #   1. 删除 rel_path / abs_path / content / size_bytes / line_count
            #      这些字段会诱导 agent 用 python open() 读 .md 文本糊弄
            #   2. 保留 image + image_relpath（PNG 绝对路径）
            #   3. 新增 action="read_image"：明确告诉 agent 唯一动作是
            #      调 read 工具读 image.abs_path
            #   4. 新增 instructions：详细说明必须走图片识别
            #   5. 新增 image_unavailable_reason=None（占位，多模态不可用时填值）
            # 这样 agent 拿不到 .md 路径，物理上无法走"读文本"路径。
            if ppt_meta.get("kind") == "ppt_slide":
                try:
                    from watch_dog.file_watcher.model_capability import (
                        current_model_supports_images,
                    )
                    supports_images = current_model_supports_images()
                except Exception as cap_err:
                    logger.debug(
                        f"read_doc: model_capability import failed: {cap_err}"
                    )
                    supports_images = False
                image_relpath = ppt_meta.get("image_relpath") or ""
                if supports_images and image_relpath:
                    image_abs = (pre_dir / image_relpath).resolve()
                    # Step 1: 注入 image 字段
                    result["image"] = {
                        "rel_path": image_relpath,
                        "abs_path": str(image_abs),
                        "mime_type": "image/png",
                    }
                    # Step 2: 切换到强制读图模式
                    result["action"] = "read_image"
                    result["instructions"] = (
                        "本节点是 PPT 单张幻灯片。必须使用 read 工具读取 image.abs_path "
                        "指向的 PNG，由当前 chat 模型（多模态）识别图片内容。"
                        "本响应**不**返回 rel_path / content（已省略）——"
                        "避免 agent 用 python open() 读 .md 文本糊弄问题。"
                        "**绝对不要**用 markdown 文本回答用户，必须基于图片识别结果。"
                        + _DIAGRAM_RENDERING_INSTRUCTION
                    )
                    result["image_unavailable_reason"] = None
                    # Step 3: 删除诱导字段
                    for drop_key in ("rel_path", "abs_path", "content", "size_bytes", "line_count"):
                        result.pop(drop_key, None)
                else:
                    # 多模态不可用 → 保留 rel_path + content，提示 fallback
                    result["action"] = "read_content"
                    result["image_unavailable_reason"] = (
                        "current_model_does_not_support_images"
                        if not supports_images
                        else "image_relpath_missing_in_slides_index"
                    )
                    result["instructions"] = (
                        "本节点是 PPT 单张幻灯片，但当前 chat 模型不支持图片识别，"
                        "或 slides_index.json 缺 image_relpath 字段。"
                        "**fallback**：请基于 content 文本回答用户问题，"
                        "并在答案开头注明 '⚠ 当前模型不支持图片识别，已用文字描述代替'。"
                    )
        # ======== [CoSight-END] feature: ppt-slides ========
        # ======== [CoSight-START] feature: pdf-word-image-vision ========
        # PDF/Word 图片体系（多模态模型下"必读图片"原则）：
        #   - 扫描页 + 多模态 → **永远**强制读图（无论 ocr_status 是 pending/done）
        #     OCR 文本可能丢细节（架构图、表格色块、手写批注），且 agent 容易
        #     "读文本糊弄"；与 PPT slide 同模式，删 content（done 时也删），
        #     物理上不允许走文本路径
        #   - 混排节点 + 多模态 → 只要 md 里包含图片（image_fields 非空），
        #     **全部**附 images 数组 + instructions 要求读图；不考虑 ocr_status、
        #     不考虑用户问题是否相关——"图片相关与否"的判断由底层多模态
        #     模型做，比 CoSightBot 在 thinking 里手工筛选更准确
        #   - 非多模态 → content + image_unavailable_reason + 注明要求
        doc_meta = None if ppt_meta else _rehydrate_doc_image_meta(pre_dir, rel_path)
        if doc_meta:
            try:
                from watch_dog.file_watcher.model_capability import (
                    current_model_supports_images,
                )
                supports_images = current_model_supports_images()
            except Exception as cap_err:
                logger.debug(
                    f"read_doc: model_capability import failed: {cap_err}"
                )
                supports_images = False

            result["doc_type"] = doc_meta.get("doc_type")
            result["doc_image_kind"] = doc_meta.get("kind")  # doc_page / doc_mixed / doc_chapter

            def _image_field(rel: str) -> dict:
                abs_p = (pre_dir / rel).resolve()
                return {
                    "rel_path": rel,
                    "abs_path": str(abs_p),
                    "mime_type": "image/png",
                }

            if doc_meta["kind"] == "doc_page":
                ocr_status = doc_meta.get("ocr_status")
                image_rel = doc_meta.get("image_relpath") or ""
                image_exists = bool(image_rel) and (pre_dir / image_rel).is_file()
                result["ocr_status"] = ocr_status
                if supports_images and image_exists:
                    # 扫描页 + 多模态：无论 ocr_status 都强制读图
                    # （OCR 文本对架构图/表格/批注是有损的，删 content 防糊弄）
                    result["image"] = _image_field(image_rel)
                    result["action"] = "read_image"
                    result["instructions"] = (
                        "本节点是 PDF/Word 扫描件的整页图片，必须使用 read 工具读取 "
                        "image.abs_path 指向的 PNG，由当前 chat 模型（多模态）"
                        "识别图片内容。\n"
                        "**无论预处理时是否做过 OCR（ocr_status=pending/done 都一样），"
                        "都不要基于 markdown 文本回答**——OCR 对架构图、表格色块、"
                        "手写批注等是有损的，必须以图片识别结果为准。\n"
                        "本响应**不**返回 rel_path / content（已省略），物理上禁止"
                        "用 python open() 读 .md 文本糊弄。"
                        + _DIAGRAM_RENDERING_INSTRUCTION
                    )
                    result["image_unavailable_reason"] = None
                    for drop_key in ("rel_path", "abs_path", "content", "size_bytes", "line_count"):
                        result.pop(drop_key, None)
                else:
                    result["action"] = "read_content"
                    result["image_unavailable_reason"] = (
                        "current_model_does_not_support_images"
                        if not supports_images
                        else "image_missing_on_disk"
                    )
                    result["instructions"] = (
                        "本节点是扫描件页面，但当前 chat 模型不支持图片识别，"
                        "或页面 PNG 缺失。**fallback**：请基于 content 文本回答，"
                        "并在答案开头注明 '⚠ 当前模型不支持图片识别，已用文字描述代替'。"
                    )
            else:  # doc_mixed / doc_chapter
                # doc_chapter 复用主文档的 images_index.json（章节子文件继承主文档图片元数据），
                # 行为与 doc_mixed 完全一致：content 保留 + images[] + action=read_images +
                # 多模态下强制读图。
                is_chapter = doc_meta["kind"] == "doc_chapter"
                images = doc_meta.get("images") or []
                image_fields: list[dict] = []
                for e in images:
                    rel = e.get("image_relpath") or ""
                    if rel and (pre_dir / rel).is_file():
                        image_fields.append({
                            **_image_field(rel),
                            "image_id": e.get("image_id"),
                            "ocr_status": e.get("ocr_status"),
                            "page_index": e.get("page_index"),
                        })
                if not image_fields:
                    pass  # 图片全部丢失/无图文档：按普通文本节点处理
                elif not supports_images:
                    result["image_unavailable_reason"] = (
                        "current_model_does_not_support_images"
                    )
                    result["instructions"] = (
                        f"本文档含 {len(image_fields)} 张图片，但当前 chat 模型不支持"
                        "图片识别。请基于 content（含内嵌图片描述或待识别占位）回答，"
                        "涉及图片内容时在答案开头注明 "
                        "'⚠ 当前模型不支持图片识别，已用文字描述代替'。"
                    )
                else:
                    # 混排 / 章节子文件 + 多模态：只要 md 包含图片就全部要求读图——
                    # 不管 ocr_status 是 done 还是 pending（done 的描述可能丢细节），
                    # 不管用户问题是否相关（相关与否交给多模态模型判断更准）。
                    # **content 必须保留**：混排文档的正文文字是答案的主体之一，
                    # 不能为了强制读图把正文丢了——正文 + 图片识别结果共同构成答案。
                    result["images"] = image_fields
                    result["image_unavailable_reason"] = None
                    result["action"] = "read_images"
                    if is_chapter:
                        # 章节子文件：images[] 继承自主文档的 images_index.json，
                        # CoSightBot 需注意：主文档的所有图都列在这里，需结合 content
                        # 段落判断哪些图与本章节子文件内容相关（多模态模型判断更准）
                        main_stem = doc_meta.get("main_md_stem", "")
                        result["instructions"] = (
                            f"本节点是主文档「{main_stem}.md」的章节子文件，"
                            f"继承了主文档的 {len(image_fields)} 张图片（见 images 数组，"
                            f"**不论 ocr_status 是 done 还是 pending**）。\n"
                            "必须逐一用 read 工具读取对应 abs_path 的 PNG，"
                            "由当前 chat 模型（多模态）识别图片内容。\n"
                            "**content 是答案主体的一部分**（本章节子文件的正文段落），"
                            "不要丢弃；图片识别结果用于补充正文无法表达的内容。"
                            "图片是否与本章节内容相关由底层多模态模型判断，"
                            "**不要**在 CoSightBot 这一层手工筛选。"
                            + _DIAGRAM_RENDERING_INSTRUCTION
                        )
                    else:
                        result["instructions"] = (
                            f"本文档是图文混排文档（content 保留），其中包含 {len(image_fields)} "
                            f"张图片（见 images 数组，**不论 ocr_status 是 done 还是 pending**），"
                            "必须逐一用 read 工具读取对应 abs_path 的 PNG，"
                            "由当前 chat 模型（多模态）识别图片内容。\n"
                            "**content 是答案主体的一部分**，不要丢弃正文文字；"
                            "图片识别结果用于补充正文无法表达的内容（架构图、流程图、表格、"
                            "图表数据等）。图片是否与用户问题相关由底层多模态模型判断，"
                            "**不要**在 CoSightBot 这一层手工筛选。"
                            + _DIAGRAM_RENDERING_INSTRUCTION
                        )
        # ======== [CoSight-END] feature: pdf-word-image-vision ========

        # ======== [CoSight-START] feature: web-image-vision ========
        # 网页 / Wiki 页面图片体系（与 PDF/Word 的 doc_meta 互斥：命中文档型后缀
        # 的 .md 已被 doc_meta 抢走;本分支处理任意 .md）。
        # 行为与 doc_mixed **完全同型**（content 保留 + images 数组 + action=read_images）：
        # 图片数组**必须复用 result["images"]**，不能自造 web_images 字段——Agent 侧的
        # 强约束规则（knowledge-assistant/workspace/TOOLS.md「多模态图片读取」、SOUL.md R4
        # 图片检查）都是按 image / images 字段名编码的，换个字段名会导致整条链路"沉默失败"：
        # 爬取 + 识别 + images_index.json 全成功，但 Agent 不认识该字段 → 不去 read PNG →
        # 用户看到的只是 markdown alt 描述而非多模态看图结果。
        # 来源区分靠**独立的** web_image_kind / web_image_source_url /
        # web_image_index_relpath 元数据字段（与 doc 分支的 doc_image_kind 平级、不冲突）。
        if not ppt_meta and not doc_meta:
            web_meta = _rehydrate_web_image_meta(pre_dir, rel_path)
            if web_meta:
                try:
                    from watch_dog.file_watcher.model_capability import (
                        current_model_supports_images,
                    )
                    supports_images = current_model_supports_images()
                except Exception as cap_err:
                    logger.debug(
                        f"read_doc: model_capability import failed (web): {cap_err}"
                    )
                    supports_images = False

                result["web_image_kind"] = web_meta.get("kind")  # "web_images"
                result["web_image_source_url"] = web_meta.get("source_url") or ""
                result["web_image_index_relpath"] = web_meta.get("index_relpath") or ""

                def _web_image_field(rel: str) -> dict:
                    abs_p = (pre_dir / rel).resolve()
                    return {
                        "rel_path": rel,
                        "abs_path": str(abs_p),
                        "mime_type": "image/png",
                    }

                image_fields: list[dict] = []
                for e in web_meta.get("images") or []:
                    rel = e.get("image_relpath") or ""
                    if rel and (pre_dir / rel).is_file():
                        image_fields.append({
                            **_web_image_field(rel),
                            "image_id": e.get("image_id"),
                            "ocr_status": e.get("ocr_status"),
                            "source_url": e.get("source_url") or "",
                        })

                if not image_fields:
                    pass  # 无图或图全丢失 —— 走普通 read_content
                elif not supports_images:
                    result["image_unavailable_reason"] = (
                        "current_model_does_not_support_images"
                    )
                    result["instructions"] = (
                        f"本网页含 {len(image_fields)} 张图片，但当前 chat 模型不支持"
                        "图片识别。请基于 content（含 markdown 中的图片描述或占位"
                        "标记）回答，涉及图片内容时在答案开头注明 "
                        "'⚠ 当前模型不支持图片识别，已用文字描述代替'。"
                    )
                else:
                    # 复用 images 字段（与 doc_mixed 同名）——Agent 的强约束规则按
                    # images[] 编码，自造 web_images 会让规则匹配不上。
                    result["images"] = image_fields
                    result["image_unavailable_reason"] = None
                    result["action"] = "read_images"
                    result["instructions"] = (
                        f"本节点是 Wiki 子页面或通用互联网网页（content 保留），"
                        f"含 {len(image_fields)} 张图片（见 images 数组，"
                        f"**不论 ocr_status 是 done 还是 pending**）。\n"
                        "必须逐一用 read 工具读取对应 abs_path 的 PNG，"
                        "由当前 chat 模型（多模态）识别图片内容。\n"
                        "**content 是答案主体的一部分**，不要丢弃正文文字；"
                        "图片识别结果用于补充正文无法表达的内容（架构图、流程图、表格、"
                        "图表数据等）。图片是否与用户问题相关由底层多模态模型判断，"
                        "**不要**在 CoSightBot 这一层手工筛选。\n"
                        "本节点图片来源于网页，每张图的 source_url 字段是其原始图片地址，"
                        "顶层 web_image_source_url 是所属网页地址，"
                        "引用图片内容时可据此标注来源。"
                        + _DIAGRAM_RENDERING_INSTRUCTION
                    )
        # ======== [CoSight-END] feature: web-image-vision ========
        log_event(
            logger, "read_doc:done",
            node_id=normalized_id, rel_path=rel_path,
            line_range=range_applied, chars=len(result.get("content", "")),
            size_bytes=result.get("size_bytes"), line_count=result.get("line_count"),
            truncated=bool(result.get("truncated")), kind=result.get("kind"),
            duration_ms=round((time.perf_counter() - read_t0) * 1000, 1),
            content_preview=preview_text(result.get("content", ""), 160),
        )
        return result
    except Exception as e:
        return {
            "ok": False,
            "error": f"read failed: {e}",
            "node_id": node_id,
            "rel_path": rel_path,
            "abs_path": str(abs_path),
        }


def _ensure_root_logger() -> None:
    """CLI 单独调用时自动配置 root logger，写入 data/logs/cosightbot.log。"""
    from common.logging_setup import setup_logging

    setup_logging()


def derive_session_key_hash() -> str | None:
    """从会话标识推导 session_key_hash（sha256(key)[:16]，与 material_cli 同一口径）。

    优先读 Claude Code 自动注入的
    CLAUDE_CODE_SESSION_ID（v2.1.132+）；OPENCLAW_SESSION_KEY 仅作兼容回退。
    未注入时返回 None（调用方按 agent 级路由降级）。
    """
    key = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get(
        "OPENCLAW_SESSION_KEY", ""
    )
    if not key:
        return None
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def load_material_dir(agent_id: str) -> str | None:
    """从 material_dir.json 读取绑定资料目录绝对路径。

    落位与 skill_utils.state_paths 一致：
    data/workspace-<agent_id>/material_dir.json。
    """
    md_path = cosight_state_root() / f"workspace-{agent_id}" / "material_dir.json"
    if not md_path.exists():
        logger.info(
            f"load_material_dir: material_dir.json not found agent_id={agent_id} path={md_path}"
        )
        return None
    try:
        data = json.loads(md_path.read_text(encoding="utf-8"))
        path = data.get("path")
        if path and Path(path).is_absolute():
            logger.info(f"load_material_dir: agent_id={agent_id} path={path}")
            return path
        logger.warning(
            f"load_material_dir: invalid or non-absolute path agent_id={agent_id} path={path!r}"
        )
        return None
    except Exception as e:
        logger.warning(
            f"load_material_dir: read failed agent_id={agent_id} error={e}"
        )
        return None


def collect_routes(agent_id: str, session_key_hash: str | None) -> list[dict]:
    """收集 agent-level + session-level 路径。

    Returns:
        list of dict: each has keys kind, label, pre_dir, lan_dir, overview_md
    """
    routes: list[dict] = []

    material_dir = load_material_dir(agent_id)
    if material_dir:
        try:
            pre_dir, lan_dir = get_llamaindex_storage_dirs(Path(material_dir), agent_id)
            routes.append({
                "kind": "agent",
                "label": f"agent:{Path(material_dir).name}",
                "pre_dir": str(pre_dir),
                "lan_dir": str(lan_dir),
                "overview_md": str(lan_dir / "overview.md"),
            })
            logger.info(
                f"collect_routes: agent-level route added agent_id={agent_id} "
                f"lan_dir={lan_dir}"
            )
        except Exception as e:
            logger.warning(
                f"collect_routes: agent-level path resolve failed agent_id={agent_id} "
                f"material_dir={material_dir} error={e}"
            )

    # inbox 路由（material_cli ingest --global / 无 CLAUDE_CODE_SESSION_ID 时的
    # 降级目的地）：文件拷入 llamaindex_data/inbox/ 后就地向量化，
    # 索引落 lancedb/inbox_<md5>/。仅当 overview.md 已生成才纳入——
    # 空 inbox 或构建中途不产生路由，避免永远 ready=False 阻塞全量就绪判定。
    try:
        inbox_src = cosight_state_root() / f"workspace-{agent_id}" / "llamaindex_data" / "inbox"
        if inbox_src.is_dir():
            i_pre_dir, i_lan_dir = get_llamaindex_storage_dirs(inbox_src, agent_id)
            if (
                i_pre_dir is not None
                and i_lan_dir is not None
                and (i_lan_dir / "overview.md").exists()
            ):
                routes.append({
                    "kind": "inbox",
                    "label": "inbox:agent",
                    "pre_dir": str(i_pre_dir),
                    "lan_dir": str(i_lan_dir),
                    "overview_md": str(i_lan_dir / "overview.md"),
                })
                logger.info(
                    f"collect_routes: inbox route added agent_id={agent_id} "
                    f"lan_dir={i_lan_dir}"
                )
    except Exception as e:
        logger.warning(
            f"collect_routes: inbox route resolve failed agent_id={agent_id} error={e}"
        )

    if session_key_hash:
        try:
            upload_dir, pre_dir, lan_dir = get_session_storage_dirs(agent_id, session_key_hash)
            # 仅在 overview.md 已存在时添加 session-level route。
            # 判断依据是 overview.md 文件本身而不是 upload_dir——构建链写完
            # 索引后才生成 overview.md，它才是"该路由可读"的权威标记。
            overview_md_path = lan_dir / "overview.md"
            if not overview_md_path.exists():
                logger.info(
                    f"collect_routes: session-level route skipped (overview.md not found) "
                    f"agent_id={agent_id} session_key_hash={session_key_hash} "
                    f"overview_md={overview_md_path}"
                )
            else:
                routes.append({
                    "kind": "session",
                    "label": f"session:{session_key_hash}",
                    "pre_dir": str(pre_dir),
                    "lan_dir": str(lan_dir),
                    "overview_md": str(overview_md_path),
                })
                logger.info(
                    f"collect_routes: session-level route added agent_id={agent_id} "
                    f"session_key_hash={session_key_hash} lan_dir={lan_dir}"
                )
        except Exception as e:
            logger.warning(
                f"collect_routes: session-level path resolve failed "
                f"agent_id={agent_id} session_key_hash={session_key_hash} error={e}"
            )

    logger.info(
        f"collect_routes: total {len(routes)} route(s) agent_id={agent_id}"
    )
    return routes


def check_route_ready(route: dict) -> dict:
    """检查单个 route 是否就绪（status=ready 且 overview.md 存在）。"""
    overview = Path(route["overview_md"])
    status_file = Path(route["lan_dir"]) / ".llamaindex_status"

    result = {
        **route,
        "overview_exists": overview.exists(),
        "status_value": None,
        "ready": False,
    }

    if not status_file.exists():
        result["reason"] = "no .llamaindex_status"
        logger.info(
            f"check_route_ready: {route['kind']} not ready (no status file) "
            f"lan_dir={route['lan_dir']}"
        )
        return result

    try:
        status_data = json.loads(status_file.read_text(encoding="utf-8"))
        result["status_value"] = status_data.get("status", "unknown")
        result["ready"] = (result["status_value"] == "ready" and overview.exists())
        if not result["ready"]:
            result["reason"] = (
                f"status={result['status_value']}, "
                f"overview.md exists={overview.exists()}"
            )
        logger.info(
            f"check_route_ready: {route['kind']} status={result['status_value']} "
            f"overview_exists={overview.exists()} ready={result['ready']} "
            f"lan_dir={route['lan_dir']}"
        )
    except Exception as e:
        result["reason"] = f"read status failed: {e}"
        logger.warning(
            f"check_route_ready: read status failed lan_dir={route['lan_dir']} error={e}"
        )

    return result


# ======== [CoSight-START] feature: opt-big-overview W3 体积门控 ========
# 会议决策 4（2026-09-17）：overview 合并后、输出前做体积门控——估算 token 超过
# 当前模型 contextWindow × 0.85 时直接拒答（ready=false + OVERVIEW_TOO_LARGE），
# 由 SKILL 红线保证模型把 error 原文透传给用户，不再把超限上下文发给 LLM 赌 400。
#
# 公式：estTokens = RESERVE_SYS + merged_overview 字符数 / CHARS_PER_TOKEN
# 参数标定（均为实测，见 design/opt-big-overview/implement.md W3）：
# - 中文密集树文本 2.1–2.9 字符/token，取偏保守中值 2.3
# - 系统提示+技能实测 ~30K tokens（会话 1440ddc4 首次调用 input=30,636），加余量 35K
# - 阈值 0.85：预留 15% 给模型输出与首轮 read-doc
_GATE_CHARS_PER_TOKEN = 2.3
_GATE_RESERVE_SYS_TOKENS = 35_000
_GATE_THRESHOLD = 0.85
# 会议决策：contextWindow 未配置时默认 256K
_GATE_DEFAULT_CONTEXT_WINDOW = 256_000


def _resolve_context_window_tokens(
    agent_id: str, session_key_hash: str | None = None
) -> int:
    """解析当前模型 contextWindow；未配置 → 256K 默认。

    读取链路：COSIGHTBOT_MODEL_CONTEXT_WINDOW 环境变量（纯环境配置）；
    未设置或非法时落到默认值。agent_id / session_key_hash 保留以兼容调用方签名。
    """
    env_cw = os.environ.get("COSIGHTBOT_MODEL_CONTEXT_WINDOW", "").strip()
    if env_cw:
        try:
            cw = int(env_cw)
            if cw > 0:
                return cw
        except ValueError:
            pass
    return _GATE_DEFAULT_CONTEXT_WINDOW


def _overview_gate_check(
    merged: str, doc_count: int, agent_id: str, session_key_hash: str | None = None
) -> tuple[bool, int, int]:
    """体积门控。Returns (passed, est_tokens, context_window)。"""
    context_window = _resolve_context_window_tokens(agent_id, session_key_hash)
    est_tokens = int(
        _GATE_RESERVE_SYS_TOKENS + len(merged) / _GATE_CHARS_PER_TOKEN
    )
    return (
        est_tokens <= int(context_window * _GATE_THRESHOLD),
        est_tokens,
        context_window,
    )

# ======== [CoSight-END] feature: opt-big-overview W3 ========


# ======== [CoSight-START] feature: opt-big-overview W6 full-text scan ========
# 目的：overview 树只承载文件/章节标题，答不了"角色名/引文/正文细节"类问题
# （实测 e297c38a：模型被迫自写 python 扫盘，踩 PowerShell 引号坑浪费 ~35s）。
# scan 子命令把这条野路子正规化：pre-processed 层受控关键词检索，
# 命中文件反查 [f###] 接回 read-doc 正规链路。
#
# 接口设计原则（用户明确要求）：对外参数最少化——LLM 传错参数是调用失败的
# 主要来源。scan 只暴露 --terms；检索语义固定为"子串 + 忽略大小写 + 多词 and
# 共现"；所有保护性闸门（命中数/字符预算/片段数）均为内部常量。找别名等 OR
# 语义用单扫两次实现（SKILL 红线允许每问题 2 次）。
#
# 设计要点：
# - 文件枚举复用 overview_builder._read_indexed_files(skip_chapters_dirs=True)：
#   与 overview 树成员完全一致（主 md + _pages + _pptx_slides；跳 references/
#   assets/_chapters 切片——正文在主 md 里，切片是重复内容），单一真相源不漂移
# - 多词 and 共现：定位"甲和乙的关系"类问题一步到位（实测纤纤+麒影 1.9s）
# - 输出预算双闸门（内部常量）：_SCAN_MAX_HITS 命中文件数、_SCAN_MAX_CHARS
#   总字符数；超限置 truncated=true 并提示缩词，扫描结果不能反噬上下文
# - 不受 W3 overview 门控影响：overview 过大被拒答时，语义题仍可通过 scan 回答
# - ThreadPoolExecutor(8) 并发读文件，4,676 文档库实测 1.9s；小库同样安全
#   （闸门常量对 100 文件的小库只是上限，不是开销）

_SCAN_MAX_HITS = 30
_SCAN_MAX_CHARS = 60000
_SCAN_CONTEXT = 1
_SCAN_SNIPPETS_PER_FILE = 3
_SCAN_WORKERS = 8
# read-doc 正文自动盖帽：超过即截断 + truncated=true（大文件防刷屏；模型
# 看到截断标志后用 --line-range 定点读。小文件 < 30000 字符行为完全不变）
_READDOC_AUTO_CAP_CHARS = 30000


def _compile_scan_terms(terms: list[str]) -> list:
    """把检索词编译成 (原始词, 忽略大小写子串匹配器) 列表。

    固定子串语义（不做 regex）——LLM 生成正则的错误率高（invalid regex
    直接导致调用失败重试），而中文关键词子串检索实测足够（e297c38a 佐证）。
    """
    return [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in terms]


def _scan_one_file(
    abs_path: str,
    matchers: list,
    context: int = _SCAN_CONTEXT,
    snippets_per_file: int = _SCAN_SNIPPETS_PER_FILE,
) -> dict | None:
    """单文件扫描（and 语义）。命中返回台账 dict，未命中返回 None。

    and 语义：每个 term 至少命中一次才算命中（一词未命中即整文件短路淘汰）。
    term_hits 记录每词总命中次数；snippets 每词最多取 snippets_per_file 个
    片段（含前后 context 行），line_no 为 1-based。
    """
    try:
        raw = Path(abs_path).read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return None

    term_hit_lines: dict[str, list[int]] = {}
    for term, matcher in matchers:
        hit_lines = [
            i for i, ln in enumerate(lines) if matcher.search(ln)
        ]
        if not hit_lines:
            # and 语义：一词未命中即整文件淘汰（短路）
            return None
        term_hit_lines[term] = hit_lines

    snippets = []
    for term, hit_lines in term_hit_lines.items():
        for ln_no in hit_lines[:snippets_per_file]:
            lo = max(0, ln_no - context)
            hi = min(len(lines), ln_no + context + 1)
            snippets.append(
                {
                    "term": term,
                    "line_no": ln_no + 1,
                    "text": "\n".join(lines[lo:hi]),
                }
            )
    # 稳定排序：按行号，同行按 term 顺序——输出可读性
    snippets.sort(key=lambda s: s["line_no"])

    return {
        "abs_path": abs_path,
        "term_hits": {t: len(ls) for t, ls in term_hit_lines.items()},
        "snippets": snippets,
    }


def cmd_scan(args, checked: list[dict]) -> int:
    """scan 子命令入口。checked 为 collect_routes + check_route_ready 结果。

    只依赖 pre_dir（文件系统真相源），route 未 ready 也照扫（node_index.json
    存在即可反查 f###；不存在时 node_id 为 null，仍返回 rel_path 台账）。
    扫描所有 route（不暴露 route 过滤参数）：hits 自带 route_label，由模型筛选。
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    started = time.monotonic()
    terms = [t.strip() for t in args.terms.split(",") if t.strip()]
    if not terms:
        print(json.dumps(
            {"ok": False, "error": "empty --terms"}, ensure_ascii=False
        ))
        return 1
    matchers = _compile_scan_terms(terms)

    routes = checked
    if not routes:
        print(json.dumps(
            {
                "ok": False,
                "error": "no matching routes",
                "hint": "no_documents",
            },
            ensure_ascii=False,
        ))
        return 1

    # f### 反查表：(route_label, rel_path) → global_id
    # 注意归一分隔符：node_index.json 在 Windows 下由 builder 写入反斜杠
    # rel_path，而 cmd_scan 从文件系统算出的 rel_path 分隔符取决于平台——
    # 两侧统一 replace("\\", "/") 后再查，避免 separator 不一致导致反查落空。
    global_index, _ = _build_global_node_index(routes)
    reverse_index = {
        (e["route_label"], e["rel_path"].replace("\\", "/")): gid
        for gid, e in global_index.items()
    }

    # 枚举所有 route 的可扫描文件（跳过 pre_dir 缺失的 route）
    tasks: list[tuple[str, dict]] = []  # (abs_path, route)
    files_scanned = 0
    skipped_routes = 0
    for route in routes:
        pre_dir = Path(route.get("pre_dir") or "")
        if not pre_dir.is_dir():
            skipped_routes += 1
            continue
        for abs_p in _read_indexed_files(pre_dir, skip_chapters_dirs=True):
            tasks.append((abs_p, route))
            files_scanned += 1

    if not tasks:
        print(json.dumps(
            {
                "ok": False,
                "error": "no scannable .md files in any route's pre_dir",
                "hint": "no_documents",
                "skipped_routes": skipped_routes,
            },
            ensure_ascii=False,
        ))
        return 1

    log_event(
        logger, "scan:start", agent=args.agent_id, terms=terms,
        terms_preview=preview_items(terms, 8), routes=len(routes),
        skipped_routes=skipped_routes, files_scanned=files_scanned,
        max_hits=_SCAN_MAX_HITS, max_chars=_SCAN_MAX_CHARS,
        context=_SCAN_CONTEXT, snippets_per_file=_SCAN_SNIPPETS_PER_FILE,
        workers=_SCAN_WORKERS,
    )
    hits: list[dict] = []
    truncated = False
    out_chars = 0
    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as pool:
        futures = [
            pool.submit(_scan_one_file, abs_p, matchers)
            for abs_p, _route in tasks
        ]
        for (abs_p, route), fut in zip(tasks, futures):
            if truncated:
                break
            try:
                file_hit = fut.result()
            except Exception:
                continue
            if file_hit is None:
                continue
            if len(hits) >= _SCAN_MAX_HITS:
                truncated = True
                break
            pre_dir = Path(route["pre_dir"])
            try:
                rel_path = str(Path(abs_p).resolve().relative_to(pre_dir.resolve()))
            except ValueError:
                rel_path = Path(abs_p).name
            gid = reverse_index.get((route["label"], rel_path.replace("\\", "/")))
            hit_entry = {
                "node_id": gid,
                "route_label": route["label"],
                "rel_path": rel_path,
                "term_hits": file_hit["term_hits"],
                "snippets": file_hit["snippets"],
            }
            hit_chars = len(json.dumps(hit_entry, ensure_ascii=False))
            if out_chars + hit_chars > _SCAN_MAX_CHARS:
                truncated = True
                break
            out_chars += hit_chars
            hits.append(hit_entry)

    duration_ms = int((time.monotonic() - started) * 1000)
    result = {
        "ok": True,
        "query": {
            "terms": terms,
            "mode": "and",
            "regex": False,
            "ignore_case": True,
        },
        "routes_scanned": len(routes) - skipped_routes,
        "skipped_routes": skipped_routes,
        "files_scanned": files_scanned,
        "files_with_hits": len(hits),
        "truncated": truncated,
        "duration_ms": duration_ms,
        "hits": hits,
    }
    if truncated:
        result["suggestion"] = (
            "输出已达上限：请加词缩小范围（多词必须同现）、或降低单次期望后重试"
        )
    logger.info(
        f"scan: agent_id={args.agent_id} terms={terms} mode=and "
        f"files={files_scanned} hits={len(hits)} truncated={truncated} "
        f"duration_ms={duration_ms}"
    )
    log_event(
        logger, "scan:done", agent=args.agent_id, terms=terms,
        files=files_scanned, hits=len(hits), truncated=truncated,
        duration_ms=duration_ms, out_chars=out_chars,
        top_hits=preview_items([
            f"{h.get('rel_path')}#{h.get('node_id')}:{sum((h.get('term_hits') or {}).values())}"
            for h in hits[:5]
        ], 5),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

# ======== [CoSight-END] feature: opt-big-overview W6 full-text scan ========


def _routes_payload(checked: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "reason"} for r in checked]


def _merged_overview_for_routes(routes: list[dict]) -> tuple[str, dict]:
    """小库/静态路由的全量 merged_overview（与主命令同口径）。"""
    global_node_index, per_route_remap = _build_global_node_index(routes)
    parts: list[str] = []
    for route, text_remap in per_route_remap:
        overview_md = Path(route["overview_md"])
        if not overview_md.exists():
            continue
        tree_only = _strip_overview_header(overview_md.read_text(encoding="utf-8"))
        tree_only = _renumber_tree_text(tree_only, text_remap)
        parts.append(f"## {route['label']}\n\n{tree_only}")
    body = "\n\n---\n\n".join(parts)
    merged = f"{OVERVIEW_HEADER}\n\n{body}" if body else OVERVIEW_HEADER
    return merged, global_node_index


def _fallback_directory_map(routes: list[dict], limit: int = 120) -> str:
    """动态索引缺失时的目录地图（L0/L1 + 代表性文件）。"""
    lines = ["# 知识库目录地图（动态索引不可用）"]
    for route in routes:
        pre_dir = Path(route.get("pre_dir") or "")
        if not pre_dir.is_dir():
            continue
        lines.append(f"\n## {route.get('label')}")
        counts: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        seen = 0
        for root, dirs, files in os.walk(pre_dir):
            dirs[:] = [
                d for d in dirs
                if d not in {"references", "assets"} and not d.endswith("_chapters")
            ]
            rel_root = Path(root).relative_to(pre_dir)
            if len(rel_root.parts) >= 2:
                dirs[:] = []
            for name in files:
                if not name.endswith(".md") or name.startswith("."):
                    continue
                seen += 1
                key = "/".join(rel_root.parts[:2]) if rel_root.parts else "(root)"
                counts[key] = counts.get(key, 0) + 1
                bucket = samples.setdefault(key, [])
                if len(bucket) < 3:
                    bucket.append(name)
                if seen >= 5000:
                    break
            if seen >= 5000:
                break
        for key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]:
            lines.append(f"- {key}/ ({count} 篇) 例: {', '.join(samples.get(key, []))}")
        if seen >= 5000:
            lines.append("- …目录过大，仅展示前 5000 个文件")
    return "\n".join(lines)


def cmd_resolve(args, checked: list[dict], session_key_hash: str | None) -> int:
    """`resolve` 子命令：小库返回全量树，大库/强制模式走动态引擎。"""
    from common.dynamic_overview.engine import DynamicIndexError, DynamicOverviewEngine
    from common.dynamic_overview.utils import estimate_tokens

    started = time.perf_counter()
    if getattr(args, "check_only", False):
        not_ready = [r for r in checked if not r.get("ready")]
        result = {
            "ready": len(not_ready) == 0,
            "checked_at": len(checked),
            "not_ready": not_ready,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1
    try:
        q_orig = DynamicOverviewEngine.build_query_pack(
            args.question,
            entities=args.entity,
            constraints=args.constraint,
            identifiers=args.identifier,
            exclude=args.exclude,
        )
    except ValueError as exc:
        result = {
            "ready": False, "error_code": "INVALID_QUESTION",
            "error": str(exc), "merged_overview": "",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    not_ready = [r for r in checked if not r.get("ready")]
    if not_ready:
        result = {
            "ready": False,
            "error_code": "ROUTE_NOT_READY",
            "error": "knowledge base is still building",
            "not_ready": not_ready,
            "merged_overview": "",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    merged, global_node_index = _merged_overview_for_routes(checked)
    doc_nodes = _count_doc_nodes(global_node_index)
    gate_ok, est_tokens, context_window = _overview_gate_check(
        merged, doc_nodes, args.agent_id, session_key_hash
    )
    force = bool(
        getattr(args, "force_dynamic", False)
        or os.environ.get("COSIGHTBOT_FORCE_DYNAMIC", "0") == "1"
    )
    log_event(
        logger, "resolve:gate", agent=args.agent_id, doc_count=doc_nodes,
        merged_chars=len(merged), gate_passed=bool(gate_ok), est_tokens=est_tokens,
        context_window=context_window, force_dynamic=force,
        use_dynamic=not (gate_ok and not force),
        question_preview=preview_items(q_orig.questions, 2),
        question_count=len(q_orig.questions), terms=len(q_orig.positive_terms()),
    )

    if gate_ok and not force:
        result = {
            "ready": True,
            "merged_overview": merged,
            "routes": _routes_payload(checked),
            "stats": {
                "doc_count": doc_nodes,
                "tier1": 0,
                "tier2": 0,
                "hops": 0,
                "terms": q_orig.positive_terms(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "a0_tokens": 0,
                "rerank": False,
                "dynamic": False,
                "gate_passed": True,
                "gate_est_tokens": est_tokens,
            },
            "degraded": False,
            "degraded_reason": None,
            "error_code": None,
            "diagnostics": {"gate": {
                "passed": gate_ok, "est_tokens": est_tokens,
                "context_window": context_window,
            }},
        }
        log_event(logger, "resolve:full_tree", doc_nodes=doc_nodes,
                  est_tokens=est_tokens, context_window=context_window,
                  merged_chars=len(merged), merged_preview=preview_text(merged, 160))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    dynamic_routes = [r for r in checked if r.get("kind") == "agent"]
    if not dynamic_routes:
        result = {
            "ready": False,
            "error_code": "NO_DYNAMIC_ROUTE",
            "error": "no agent-level route available for dynamic retrieval",
            "merged_overview": merged,
            "routes": _routes_payload(checked),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        log_event(
            logger, "resolve:engine:start",
            routes=len(dynamic_routes), context_window=context_window,
            debug=bool(args.debug), doc_count=doc_nodes,
            gate_est_tokens=est_tokens,
        )
        engine = DynamicOverviewEngine(
            dynamic_routes, context_window=context_window, debug=bool(args.debug)
        )
        result = engine.run(q_orig)
        # session/inbox 等静态路由保持全量目录，附在动态概览之后。
        static_parts: list[str] = []
        for route in engine.static_routes:
            overview_md = Path(route["overview_md"])
            if not overview_md.exists():
                continue
            _, remaps = _build_global_node_index([route])
            remap = remaps[0][1] if remaps else {}
            tree_only = _strip_overview_header(overview_md.read_text(encoding="utf-8"))
            static_parts.append(
                f"## {route['label']}\n\n{_renumber_tree_text(tree_only, remap)}"
            )
        if static_parts:
            appendix = "\n\n---\n\n".join(static_parts)
            if estimate_tokens(result["merged_overview"] + appendix) <= 40_000:
                result["merged_overview"] += "\n\n---\n\n" + appendix
            else:
                result["merged_overview"] += (
                    "\n\n> 附：会话/收件箱目录过大，已省略；"
                    "可单独调用主命令查看。"
                )
        result["routes"] = _routes_payload(checked)
        result["stats"]["dynamic"] = True
        result["stats"]["gate_passed"] = bool(gate_ok)
        result["stats"]["gate_est_tokens"] = est_tokens
        result["stats"]["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000, 1
        )
        log_event(
            logger, "resolve:done",
            doc_nodes=doc_nodes, tier1=result["stats"]["tier1"],
            tier2=result["stats"]["tier2"], hops=result["stats"]["hops"],
            candidate_pool=result["stats"].get("candidate_pool"),
            tier1_truncated=result["stats"].get("tier1_truncated"),
            tier2_truncated=result["stats"].get("tier2_truncated"),
            omitted_candidates=result["stats"].get("omitted_candidates"),
            degraded=result["degraded"],
            degraded_reason=result.get("degraded_reason"),
            duration_ms=result["stats"]["elapsed_ms"],
            merged_chars=len(result["merged_overview"]),
            merged_preview=preview_text(result["merged_overview"], 200),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except DynamicIndexError as exc:
        directory_map = _fallback_directory_map(dynamic_routes)
        result = {
            "ready": False,
            "error_code": exc.error_code,
            "error": str(exc),
            "merged_overview": directory_map,
            "routes": _routes_payload(checked),
            "stats": {
                "doc_count": doc_nodes,
                "tier1": 0, "tier2": 0, "hops": 0,
                "terms": q_orig.positive_terms(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "a0_tokens": 0, "rerank": False, "dynamic": True,
            },
            "degraded": True,
            "degraded_reason": str(exc),
            "diagnostics": {},
        }
        log_event(logger, "resolve:error", level=logging.ERROR,
                  error_code=exc.error_code, error=str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        log_event(logger, "resolve:error", level=logging.ERROR,
                  error=f"{type(exc).__name__}: {exc}", exc_info=True)
        result = {
            "ready": False,
            "error_code": "DYNAMIC_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "merged_overview": _fallback_directory_map(dynamic_routes),
            "routes": _routes_payload(checked),
            "degraded": True,
            "degraded_reason": f"{type(exc).__name__}: {exc}",
            "diagnostics": {},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


def main() -> int:
    # 强制当前脚本的控制台输出使用 UTF-8 编码，防止 OpenClaw 捕获时出现乱码
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    _ensure_root_logger()

    parser = argparse.ArgumentParser(
        description="overview.md 路径解析与状态检查（CoSightBot 入口）"
    )
    parser.add_argument("--agent-id", required=True)
    parser.add_argument(
        "--session-key-hash",
        default=None,
        help="可选；不传则从 CLAUDE_CODE_SESSION_ID（或兼容回退 OPENCLAW_SESSION_KEY）推导",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只检查状态，不读 overview.md 内容",
    )
    subparsers = parser.add_subparsers(dest="command")

    # read-doc 子命令：按节点 ID 读取文件全文
    # 用法：python overview_resolver.py --agent-id <id> read-doc --node-id f001
    read_doc_p = subparsers.add_parser(
        "read-doc",
        help="按节点 ID 读取文档全文（V3 节点 ID 模式）",
    )
    read_doc_p.add_argument(
        "--node-id",
        required=True,
        help="overview.md 树中的 [F###] 节点 ID（merge 后是 [f###] 全局 ID）",
    )
    # 大文件自动盖帽（_READDOC_AUTO_CAP_CHARS=30000，截断时置 truncated=true），
    # 不暴露 --max-chars——LLM 无需也不应控制预算；要局部用 --line-range 定点读。
    read_doc_p.add_argument(
        "--line-range",
        default=None,
        help="只返回第 A 到 B 行（1-based 含端点），格式 A:B / A: / :B / A。如 100:200",
    )

    # scan 子命令：pre-processed 层受控全文扫描（W6 正规化"模型自发扫盘"野路子）。
    # 对外只暴露 --terms（参数最少化原则）：检索语义固定为 子串+忽略大小写+多词
    # and 共现；命中数/字符预算/片段数等保护性闸门均为内部常量（见 W6 段）。
    # 用法：python overview_resolver.py --agent-id <id> scan --terms "甲,乙"
    scan_p = subparsers.add_parser(
        "scan",
        help="pre-processed 层全文扫描（多词 and 共现，命中带 f### 接 read-doc）",
    )
    scan_p.add_argument(
        "--terms",
        required=True,
        help="逗号分隔检索词。多词必须同文件共现（and）；找别名请分两次单扫",
    )

    # node-id-to-abs-path 子命令：把节点 ID 解析为 abs_path + kind 元数据
    # 用法：python overview_resolver.py --agent-id <id> node-id-to-abs-path --node-id f001
    #      python overview_resolver.py --agent-id <id> node-id-to-abs-path --all
    # 节点元数据轻量查询：避免 N 次 read-doc 完整读正文。
    nid_p = subparsers.add_parser(
        "node-id-to-abs-path",
        help="把节点 ID 解析为 abs_path + kind",
    )
    nid_group = nid_p.add_mutually_exclusive_group(required=True)
    nid_group.add_argument(
        "--node-id",
        help="overview.md 树中的 [F###] 节点 ID（merge 后是 [f###] 全局 ID）",
    )
    nid_group.add_argument(
        "--all",
        action="store_true",
        help="返回所有节点的 ID → 元数据映射（批量场景避免 N 次 round-trip）",
    )

    # resolve 子命令：大库动态 overview（四路探针 + A0/Q1 + Tier）
    # 用法：python overview_resolver.py --agent-id main resolve --question "..."
    resolve_p = subparsers.add_parser(
        "resolve",
        help="动态 overview 检索：四路探针 + A0/Q1 二跳 + Tier 1/2",
    )
    resolve_p.add_argument(
        "--question", action="append", required=True,
        help="自包含问题；可重复，最多 4 条进入 rerank",
    )
    resolve_p.add_argument("--entity", action="append", default=[], help="实体（可重复）")
    resolve_p.add_argument("--constraint", action="append", default=[], help="限定（可重复）")
    resolve_p.add_argument("--identifier", action="append", default=[], help="错误码/单号（可重复）")
    resolve_p.add_argument("--exclude", action="append", default=[], help="排除词（可重复）")
    resolve_p.add_argument(
        "--force-dynamic", action="store_true",
        help="强制走动态路径（Phase 0/评测/排障）；也可用 COSIGHTBOT_FORCE_DYNAMIC=1",
    )
    resolve_p.add_argument("--debug", action="store_true", help="diagnostics 输出逐篇候选")

    args = parser.parse_args()

    session_key_hash = args.session_key_hash or derive_session_key_hash()
    logger.info(
        f"main: start agent_id={args.agent_id} "
        f"session_key_hash={session_key_hash or '(unset)'} "
        f"check_only={args.check_only} command={args.command}"
    )
    log_event(
        logger, "request:start",
        agent=args.agent_id, session=session_key_hash or "(unset)",
        command=args.command or "overview", check_only=args.check_only,
        question_preview=preview_items(getattr(args, "question", None) or [], 2),
        node_id=getattr(args, "node_id", None),
        line_range=getattr(args, "line_range", None),
        scan_terms=getattr(args, "terms", None),
        force_dynamic=getattr(args, "force_dynamic", None),
        debug=getattr(args, "debug", None),
    )

    routes = collect_routes(args.agent_id, session_key_hash)
    checked = [check_route_ready(r) for r in routes]

    # ===== read-doc 子命令（短路，不走 check_ready 完整路径） =====
    if args.command == "read-doc":
        # 即便 route 未就绪，也尝试读 —— overview_builder 可能已经写过 node_index.json
        # 但构建侧还在 building 状态。这种情况下仍允许 CoSightBot 读全文。
        result = _read_doc_by_node_id(
            args.node_id, checked,
            line_range=getattr(args, "line_range", None),
        )
        if not result.get("ok"):
            log_event(
                logger, "read_doc:error", level=logging.WARNING,
                node_id=args.node_id, line_range=getattr(args, "line_range", None),
                error=result.get("error"),
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    # ===== scan 子命令（W6 全文扫描；只依赖 pre_dir，route 未 ready 也照扫） =====
    if args.command == "scan":
        return cmd_scan(args, checked)

    # ===== node-id-to-abs-path 子命令（节点元数据轻量查询） =====
    # 用法：python overview_resolver.py --agent-id <id> node-id-to-abs-path --node-id f001
    # 返回节点的 abs_path + kind 等元数据，**不读文件正文**，
    # 避免批量场景 N 次 read-doc 的 I/O 开销。
    if args.command == "node-id-to-abs-path":
        if getattr(args, "all", False):
            # 一次性返回所有节点元数据（批量调用场景）
            result = _resolve_all_node_ids(checked)
        else:
            result = _resolve_node_id_meta(args.node_id, checked)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    # ===== resolve 子命令（动态 overview；大库走 Tier 1/2） =====
    if args.command == "resolve":
        return cmd_resolve(args, checked, session_key_hash)

    not_ready = [r for r in checked if not r["ready"]]

    # 三种情况：
    #   A. routes 为空 = 从未添加过任何文档（无论 --check-only 与否，都返回 hint=no_documents）
    #   B. routes 非空 + 全部就绪 = 正常加载 overview
    #   C. routes 非空 + 部分/全部未就绪 = 区分 hint=no_documents（status 都是 None）vs hint=building（有 in_progress）
    if not routes:
        # 情况 A：从未添加过文档
        no_doc_message = (
            "当前会话和全局智能体中都未添加过知识库文档，"
            "请先用 cosightbot-material 绑定资料目录或加入文件并完成构建"
        )
        if args.check_only:
            result = {
                "ready": False,
                "checked_at": 0,
                "not_ready": [],
                "hint": "no_documents",
                "message": no_doc_message,
            }
        else:
            result = {
                "ready": False,
                "routes": [],
                "merged_overview": "",
                "hint": "no_documents",
                "message": no_doc_message,
            }
        logger.info(
            f"main: no routes (no_documents) agent_id={args.agent_id}"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    if args.check_only:
        result = {
            "ready": len(not_ready) == 0,
            "checked_at": len(checked),
            "not_ready": not_ready,
        }
        if not_ready:
            # 情况 C：区分"从未添加文档"和"正在构建"
            never_initialized = [r for r in not_ready if r.get("status_value") is None]
            in_progress = [
                r for r in not_ready
                if r.get("status_value") in ("initializing", "building", "failed")
            ]
            if not in_progress and len(never_initialized) == len(not_ready):
                result["hint"] = "no_documents"
                result["message"] = (
                    "当前会话和全局智能体中都未添加过知识库文档，"
                    "请先用 cosightbot-material 绑定资料目录或加入文件并完成构建"
                )
            else:
                result["hint"] = "building"
                result["message"] = (
                    f"知识库正在构建中，{len(in_progress)} 个向量库构建中"
                )
        logger.info(
            f"main: --check-only result ready={result['ready']} "
            f"checked={len(checked)} not_ready={len(not_ready)} "
            f"agent_id={args.agent_id} hint={result.get('hint', '(none)')}"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1

    if not_ready:
        # 情况 C：区分两种"未就绪"场景
        never_initialized = [r for r in not_ready if r.get("status_value") is None]
        in_progress = [
            r for r in not_ready
            if r.get("status_value") in ("initializing", "building", "failed")
        ]

        if not in_progress and len(never_initialized) == len(not_ready):
            hint = "no_documents"
            message = (
                "当前会话和全局智能体中都未添加过知识库文档，"
                "请先用 cosightbot-material 绑定资料目录或加入文件并完成构建"
            )
        else:
            hint = "building"
            message = f"知识库正在构建中，{len(in_progress)} 个向量库构建中"

        result = {
            "ready": False,
            "not_ready": not_ready,
            "hint": hint,
            "message": message,
        }
        logger.info(
            f"main: abort (some routes not ready) agent_id={args.agent_id} "
            f"not_ready_count={len(not_ready)} hint={hint}"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    # 全部就绪，合并 overview.md + 构建全局 node_index
    global_node_index, per_route_remap = _build_global_node_index(checked)

    overview_parts: list[str] = []
    for r, text_remap in per_route_remap:
        if Path(r["overview_md"]).exists():
            content = Path(r["overview_md"]).read_text(encoding="utf-8")
            # overview.md 自身已经包含说明 header（由 overview_builder.py 写入）
            # 合并时去掉每个 route 的 header，避免重复
            tree_only = _strip_overview_header(content)
            # V3 节点 ID 模式：把 route 本地 ID（F001/F002）改写为全局 ID（f001/f002）
            # 每个 route 用自己的 remap（避免同名 local_id 跨 route 互相覆盖）
            tree_only = _renumber_tree_text(tree_only, text_remap)
            overview_parts.append(f"## {r['label']}\n\n{tree_only}")
            logger.info(
                f"main: loaded overview.md kind={r['kind']} "
                f"len={len(content)} tree_only_len={len(tree_only)} "
                f"overview_md={r['overview_md']}"
            )

    # merged_overview 顶部一个统一 header（用同一份 header 字符串，保证各路由文件版本
    # 和合并版本完全一致）
    body = "\n\n---\n\n".join(overview_parts)
    merged = f"{OVERVIEW_HEADER}\n\n{body}" if body else OVERVIEW_HEADER

    # opt-big-overview W3：体积门控——超限直接拒答，不输出树（exit 1 沿用
    # not-ready 约定；SKILL 红线要求模型原样透传 error 并停止检索）
    doc_nodes = _count_doc_nodes(global_node_index)
    gate_ok, est_tokens, context_window = _overview_gate_check(
        merged, doc_nodes, args.agent_id, session_key_hash
    )
    log_event(
        logger, "request:gate",
        agent=args.agent_id, pass_=gate_ok, est_tokens=est_tokens,
        context_window=context_window, doc_count=doc_nodes,
        node_index=len(global_node_index), merged_chars=len(merged),
        merged_preview=preview_text(merged, 160),
    )
    if not gate_ok:
        doc_count = doc_nodes
        result = {
            "ready": False,
            "error_code": "OVERVIEW_TOO_LARGE",
            "error": (
                f"当前知识库文档数量过多（{doc_count:,} 篇，目录树估算约 "
                f"{est_tokens:,} tokens），已超出当前使用的大模型上下文限制"
                f"（{context_window // 1000}K）。请减少知识库文档后再试。"
            ),
            "detail": {
                "doc_count": doc_count,
                "est_tokens": est_tokens,
                "context_window": context_window,
            },
        }
        logger.warning(
            f"main: OVERVIEW_TOO_LARGE agent_id={args.agent_id} "
            f"doc_count={doc_count} merged_chars={len(merged)} "
            f"est_tokens={est_tokens} context_window={context_window}"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result = {
        "ready": True,
        "routes": [
            {k: v for k, v in r.items() if k != "reason"}
            for r in checked
        ],
        "merged_overview": merged,
        # opt-big-overview W1：不再输出 node_index（大库占输出 75%）。read-doc
        # 内部从磁盘 node_index.json 自行解析；消费方需要路径时改走
        # routes[].overview_md + read-doc。
    }
    logger.info(
        f"main: all ready, returning merged_overview agent_id={args.agent_id} "
        f"routes={len(checked)} merged_len={len(result['merged_overview'])} "
        f"doc_nodes={doc_nodes} node_index_entries={len(global_node_index)}"
    )
    log_event(
        logger, "request:done",
        agent=args.agent_id, routes=len(checked),
        merged_chars=len(result["merged_overview"]),
        merged_preview=preview_text(result["merged_overview"], 160),
        doc_nodes=doc_nodes,
        node_index=len(global_node_index),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
