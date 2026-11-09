#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 LanceDB + 源 markdown 构建 overview.md 树形索引。

由 handler.py 在每次构建/更新向量库完成后调用，输出 overview.md 到
lan_dir 下，与 .llamaindex_status 同级。

CoSightBot 通过 runtime/common/overview_resolver.py 读取此文件。

设计要点：
- 从 lancedb `chapters` 表的 metadata.file_path 拿到"已索引到本向量的文件列表"
- 对每个 .md 文件，从 pre_dir 下的 markdown 源文件解析 # / ## / ### 标题
- 按目录层级渲染树：每个节点是独立的文件夹名或 .md 文件名，文件下挂章节
  标题（与 pre_dir 实际目录 1:1 对应）
- 过滤 references/ assets/ 空目录 和非 .md 文件
- **节点 ID 模式**（V3 - 解决 LLM 路径拼接错误 + 路径冗余膨胀）：
  每个可读 [FILE] 节点分配稳定 ID `[F001]` `[F002]` ...，
  节点行只显示 **basename**（不再嵌入完整相对路径）。
  ID 与完整路径的映射由 overview_resolver.py 维护在 `node_index` 字段中。
  CoSightBot 调 `overview_resolver.py read-doc --node-id F001` 即可获取文件全文，
  不再自己拼路径。
"""
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Optional

from .artifact_paths import (
    POWERPOINT_CHAPTER_SUFFIXES,
    POWERPOINT_SLIDE_SUFFIXES,
    SCANNED_PAGE_SUFFIXES,
)

# 与 runner 一致，输出到 <state_root>/logs/cosightbot.log
logger = logging.getLogger("file_watcher.overview_builder")

# 跳过这些子目录（references 是引用子目录，assets 是图片等资源）
_EXCLUDED_DIR_NAMES = {"references", "assets"}

# 匹配 markdown 标题行：# / ## / ### ...
_HEADER_RE = re.compile(r"^(#+)\s+(.+?)\s*$")

# 匹配代码块起始/结束（用于跳过代码块中的 # 行）
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# compact(SOC) 模式下章节树的行数上限：超过则自动降级为纯 [DIR]/[F###] 树。
# 依据：章节树随文件数线性膨胀，--tree 输出要进 agent context，数千行的树
# 会把上下文打爆（30 文件的知识库约 300 行，1500+ 文件的库才会触顶）。
# 节点 ID 只按文件节点分配、与是否渲染章节无关，降级重渲染不影响 node_index。
_COMPACT_SECTIONS_MAX_LINES = 2000

# 文件名里含非法 UTF-8 字节时，Linux 文件系统经 surrogateescape 会把原始字节
# 呈现为 U+DC80–U+DCFF 区间的孤立代理字符。这类字符无法按 UTF-8 编码写出，
# 会导致 overview.md / node_index.json 整文件写失败——2026-09-14
# support_sub_737b6f9e 真实事故：几个 GBK 文件名 doc 让整个子库的
# overview.md 与 node_index.json 从未生成（doc_count 只能回退、node_sections
# 生成失败）。这里统一替换为 U+FFFD，保证索引文件可写；个别文件因此失去
# node-id 精确定位能力，但远好于整库无 node_index。
_SURROGATE_RE = re.compile(r"[\udc80-\udcff]")


def _sanitize_fs_text(s: str) -> str:
    """把 surrogateescape 产生的孤立代理字符替换为 U+FFFD。"""
    return _SURROGATE_RE.sub("�", s)


def _atomic_write_text(path: Path, text: str) -> None:
    """同目录临时文件 + os.replace，避免读者看到半截 overview/node_index。"""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# overview.md 顶部说明 header：标记 [DIR]/[FILE] 节点约定 + 路径拼接公式 + 严禁行为。
# 同时被本模块写入 overview.md 文件，以及被 common.overview_resolver 在 merged_overview
# 顶部预拼接。**两边内容必须保持一致**，否则 CoSightBot 在文件 vs merged 两种上下文看到
# 的指令会漂移。


# W7 迁移哨兵：overview.md 格式版本。
# 1 = 老格式（无 R1-R6 压缩，box-drawing 缩进 + 完整文件名）
# 2 = 当前（tab 缩进 + 清洗后展示名）—— 由 write_overview_md 在 OVERVIEW_HEADER
#     / OVERVIEW_COMPACT_HEADER 末尾写出
# 哨兵位于 header 块内、独立 "---" 行之前 → resolver._strip_overview_header 找到
# 第一个 "---" 就剥掉前面所有内容，哨兵随 header 一起被剥掉，对下游零影响。
_OVERVIEW_FORMAT_SENTINEL = "# overview-format: v2-compressed"
_CURRENT_OVERVIEW_FORMAT_VERSION = 2


def _detect_overview_format_version(overview_md_path) -> int:
    """读 overview.md 全文识别 builder 格式版本。

    返回 1 或 2（_CURRENT_OVERVIEW_FORMAT_VERSION）。

    - 哨兵存在 → 2（已用新 builder 写出，无需迁移）
    - 哨兵缺失但文件存在 → 1（老格式，需 v1→v2 压缩迁移）
    - 文件不存在 / 读取失败 → 1（按老格式处理，调用方决定是否重生成）

    实现说明：读完整文件（overview.md 最大 ~400KB，开销可忽略）。原因：先
    设计固定窗口（如 2000 字节）会被 Windows CRLF 击穿——tempfile 文本模式
    把每个 `\n` 变成 `\r\n`，把哨兵推到固定窗口之外，导致检测失败。全文读
    后 `in` 操作在 ssublinear（哨兵通常在前 ~2KB 命中）即返回。读 utf-8 显式
    解码避免 Windows GBK 误读（CJK 文件名场景）。
    """
    try:
        with open(overview_md_path, "rb") as f:
            content_bytes = f.read()
    except OSError:
        return 1
    text = content_bytes.decode("utf-8", errors="replace")
    return _CURRENT_OVERVIEW_FORMAT_VERSION if _OVERVIEW_FORMAT_SENTINEL in text else 1


OVERVIEW_HEADER = (
    "## 📋 overview 索引说明（**唯一入口，硬性规则**）\n\n"
    "本文件是当前 route 的**完整文档树**——所有可读的 .md 文档都在这里列出，\n"
    "CoSightBot 必须**只从这里**发现文档，不要去磁盘上 `Get-ChildItem` / `os.walk` / `ls` 自行查找。\n\n"
    "**节点标记**：\n"
    "树的层级用**行首 tab 缩进**表示（每深一层多一个 tab），同一 tab 数的连续行互为兄弟节点。\n"
    "- `[DIR] xxx/` — 父目录节点。命中此节点时，**整棵子树**的所有 `[FILE]` 文档都要进入候选，不能只看目录名。\n"
    "- `[F###] filename` — 实际可读文档。**`[F###]` 是稳定节点 ID**（如 `[F001]`），由 overview_builder.py 顺序分配；"
    "名称是**清洗后的展示名**（已去 `.md` 扩展名与构建哈希后缀），**不含任何父目录路径**——路径解析由工具完成，LLM 不要再自己拼。\n"
    "- `[F###] 🖼️ Page_NNN` — **扫描件页面节点**（位于 `<stem>_pages/` 目录下）。"
    "内容来自整页图片识别，read-doc 时可能返回 `action=read_image` 要求读取页面 PNG，"
    "届时**必须**用 read 工具读图，不要只凭文本回答。\n\n"
    "**路径解析（不再让 CoSightBot 拼）**：\n"
    "调用 `overview_resolver.py read-doc --node-id <F###>` 即可获取该节点对应的文件全文，"
    "工具内部解析绝对路径并返回内容。返回 JSON 含 `node_id`、`rel_path`、`abs_path`、`content` 等字段。\n"
    "**严禁**自己用 `os.path.join(pre_dir, ...)` 拼路径——会漏中间层或拼错中文路径。\n\n"
    "**已过滤的子目录**（不应出现在此树中，如果出现了说明索引状态异常）：\n"
    "- `references/` — 引用子目录，结构化知识库不需要看\n"
    "- `assets/` — 图片等资源\n\n"
    "**🚨 CoSightBot 红线（每次处理问题时都要在 thinking 里自检）**：\n"
    "- **不要自己解析表格 / 数行数** → 把文档扔给底层 LLM 处理\n"
    "- **不要重复调同一个 CLI**（例如 overview_resolver.py 每个问题只调一次）\n"
    "- **多看模式要把所有 `[FILE]` 全部纳入候选**（不要做相关性筛选）\n"
    "- **不要在磁盘上找文件**——overview 是唯一入口\n"
    "- **不要替 LLM 做 LLM 最擅长的事**——统计、分类、解析交给 LLM\n"
    "- **不要自己拼路径**——节点 ID 就是路径的代名词，调 `overview_resolver.py read-doc --node-id F###` 取内容\n\n"
    "**CoSightBot 的职责**：\n"
    "1. 从下方文档树中挑出与用户问题相关的 `[F###]` 节点（必要时整棵子树展开 `[DIR]`）\n"
    "2. **调 `overview_resolver.py read-doc --node-id <F###>` 读取每个候选节点的全文**（一个节点一次调用）\n"
    "3. 把所有文档全文 + 用户问题 + 输出规范一起喂给底层 LLM 出答案\n\n"
    # 格式哨兵：标识 overview 为 v2 压缩格式。必须放在独立 "---" 行之前 →
    # 随 header 整体被 resolver._strip_overview_header 剥掉（找第一个 "---" 行
    # 就停止剥），对下游零影响。手动改 OVERVIEW_HEADER 内容时务必保留此行。
    "# overview-format: v2-compressed\n"
    "---"
)


# SOC 标书知识库专用紧凑版 header（compact=True 时写入 overview.md）。
# 与 OVERVIEW_HEADER 的差异：
# - [DIR] 行直接显示相对知识库根的完整相对路径（客户端没有 pre_dir，无法靠目录名
#   逐级拼路径，必须一眼看到可传给 --path-prefixes 的值）
# - 指令面向 soc-general-qa-skill（qa.py --tree 打印本树、qa.py 过滤检索），
#   而不是 read-doc 读全文（SOC 客户端没有 pre-processed .md 源文件，read-doc 必然失败）
# - 章节标题是否展开由 show_sections 控制
#   --build-overview-only 均传 show_sections=True 开启）：章节树会让 overview.md
#   随文件数线性膨胀，故 compact 模式带 _COMPACT_SECTIONS_MAX_LINES 行数回退保护，
#   超阈值自动降级为纯 [DIR]/[F###] 树（见 write_overview_md）
# 首行仍以 "## 📋 overview 索引说明" 开头、以 "---" 收尾，保证
# overview_resolver._strip_overview_header 的剥离逻辑对两种 header 都成立。
OVERVIEW_COMPACT_HEADER = (
    "## 📋 overview 索引说明（紧凑版 · **唯一入口，硬性规则**）\n\n"
    "本文件是 SOC 标书知识库的**文档树**——列出目录与文件节点，并在文件节点下展开该文件的"
    "章节标题（帮助判断相关性与选范围；库过大时自动省略章节），由 `soc-general-qa-skill` 的 `--tree` 模式输出。\n"
    "CoSightBot 必须**只从这里**发现文档，不要去磁盘上 `Get-ChildItem` / `os.walk` / `ls` 自行查找。\n\n"
    "**节点标记**：\n"
    "- `[DIR] 产品A/01_概述/` — 目录节点，显示**相对知识库根的完整相对路径**。选中某目录时，"
    "把该路径原样作为 `--path-prefixes` 传给 soc-general-qa-skill，自动覆盖目录下全部文件。\n"
    "- `[F###] filename.md` — 文件节点。`[F###]` 是稳定节点 ID，选中时原样作为 `--node-ids` "
    "传给 soc-general-qa-skill（大小写不敏感）。\n"
    "- 文件节点下方的缩进行是该文件的**章节标题**（从 markdown 标题提取，按层级缩进），"
    "仅供判断相关性，**不是节点**、不能作为检索入参。\n"
    "- 章节被省略的库（大库），用 soc-general-qa-skill 的 `--sections \"F001,F002\"` "
    "下钻查看指定文件的章节标题清单（数据源 node_sections.json，随库下发），看完再敲定检索范围。\n\n"
    "**使用方式（SOC 普通问答流程）**：\n"
    "1. 根据用户问题，从下方文档树挑选相关的 `[DIR]` 目录 / `[F###]` 文件节点\n"
    "2. 调 `soc-general-qa-skill`：`--question \"<问题>\" --node-ids \"F001,F002\" "
    "--path-prefixes \"产品A/01_概述/\"`（节点/目录较多时用 `--input-file` 传 JSON）\n"
    "3. 基于返回的 chunks JSON 总结答案；0 命中或证据不足时从剩余未选节点再挑一批重试（最多 2~3 轮）\n\n"
    "**🚨 CoSightBot 红线**：\n"
    "- **不要**用 `overview_resolver.py read-doc` 读文件全文——SOC 客户端没有 .md 源文件，"
    "read-doc 会失败；检索一律走 soc-general-qa-skill\n"
    "- **不要在磁盘上找文件**——本树是唯一入口\n"
    "- **不要自己拼路径**——`[DIR]` 行的路径原样传给 `--path-prefixes` 即可\n\n"
    # W7 迁移哨兵：与 OVERVIEW_HEADER 同义（详见那里），让 SOC 紧凑版同样可被
    # _do_regenerate_overviews_for_ready_routes 识别并跳过重复迁移。位置必须在
    # 独立 "---" 行之前。
    "# overview-format: v2-compressed\n"
    "---"
)


def _ensure_root_logger() -> None:
    """脚本独立运行时也能把日志写到 data/logs/cosightbot.log。"""
    from common.logging_setup import setup_logging

    setup_logging()


def _read_indexed_files(pre_dir: Path, skip_chapters_dirs: bool = False) -> set[str]:
    """从 pre_dir 直接列举 .md 文件，返回绝对路径集合。

    overview 树的真理来源就是 pre_dir——有什么 .md 就显示什么节点。
    references/、assets/ 由 _EXCLUDED_DIR_NAMES 单独处理；其它子目录（包含
    *_ppt*_slides/ 与 Office 文档的 *_chapters/）都进入 overview 树作为实际物理路径节点。

    skip_chapters_dirs=True（compact/SOC 专用快速路径）：os.walk 剪枝遍历，
    整棵跳过所有 *_chapters/ 目录。SOC 向量库只索引主 md（nodes.lance 的
    file_path 恒为主 md），*_chapters/ 是 chapter_splitter 的中间产物，从不进
    向量库——它们进树只有两种可能：主 md 在 → 与主 md 重复；主 md 不在（源
    文档换版本删除后残留的过期切片）→ 无索引死节点，选中必然 0 命中。两种
    情形都不该出现。规模实证：1581 个主文档的库带 51 万个 _chapters 切片
    （含约 1.2 万个过期残留），剪枝同时把遍历规模从数十万压到主 md 量级。
    该模式下 _pages/、*_ppt*_slides/ 不剪（与原路径语义一致）；主智能体
    全量版（skip_chapters_dirs=False）行为完全不变。

    特殊排除：
    - ``<stem>_<ppt-ext>_chapters/``：chapter_splitter 拆出来的"每页=一个章节 .md"，
      但 PPT 的 per-slide 完整内容已在 ``<stem>_<ppt-ext>_slides/`` 下提供（每页一个
      独立 .md，含原文 + 图片链接），再列 _pptx_chapters 会与 _pptx_slides 完全
      重复。overview 树只展示 _pptx_slides，隐藏 _pptx_chapters。
    - **扫描件 PDF/Word 的 ``<stem>_<ext>_chapters/``**：扫描件同时有
      ``<stem>_<ext>_pages/``（每页 = 一个独立 md，整页 OCR 内容已在
      ``<stem>_<ext>.md`` 主 md 里按页 H2 合并展示） + ``<stem>_<ext>_chapters/``
      （chapter_splitter 二次切的"每页=一个章节 .md"）。两个目录内容**完全重叠**
      （扫描件每页正好是一个章节）。overview 树只展示 _pages，隐藏 _chapters——
      避免 CoSightBot 在"问扫描件第 N 页"场景下挑到 _chapters 重复内容、且
      _chapters 里的图片元数据会丢失（见 overview_resolver::_rehydrate_doc_image_meta
      暂未覆盖 _chapters 节点）。

    注意：混排 PDF/DOCX 的 ``<stem>_<ext>_chapters/`` **仍然展示** —— 混排文档
    没有 _pages/ 兄弟目录，章节 splitter 把长文档切片后供检索、与主 md 互补。

    为什么不读 lancedb chapters.lance：
        历史上 _read_indexed_files 用 chapters.lance 当"已索引文件清单"代理，
        但 chapters.lance 是章节聚合检索的产物，跟 overview 树没有强耦合。
        一旦 sync_chapters_table 在 delete/rebuild 路径上把 chapters.lance 删了，
        overview.md 也会跟着被清——这正是用户场景里"PPT 删除又放回"导致的
        overview.md 永久消失。pre_dir 才是 overview 树的真理来源。
    """
    # ======== [CoSight-START] feature: soc-general-qa ========
    if skip_chapters_dirs:
        # compact/SOC 快速路径：剪枝遍历，见 docstring。os.walk 默认吞掉
        # 个别不可读子目录的 scandir 错误（onerror=None），深路径/权限异常
        # 不会中断整体遍历。
        indexed: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(pre_dir):
            dirnames[:] = [
                d for d in dirnames
                if d not in _EXCLUDED_DIR_NAMES and not d.endswith("_chapters")
            ]
            for f in filenames:
                if f.lower().endswith(".md") and not f.startswith("."):
                    indexed.add(str(Path(dirpath) / f))
        return indexed
    # ======== [CoSight-END] feature: soc-general-qa ========

    indexed: set[str] = set()
    if not pre_dir or not pre_dir.exists():
        return indexed

    # ======== [CoSight-START] feature: scanned-hide-chapters ========
    # 预扫描：找出所有 <stem>_<ext>_pages/ 目录，建立"扫描件主 stem"集合。
    # 主循环遇到 _chapters/ 子文件时，若其父 stem 在此集合内 → 跳过。
    # 实现要点：按"父目录名 endswith _chapters"识别 + "剥离 _chapters 后缀
    # 的同层 _pages 目录存在"判定——避免误伤混排文档的 _chapters/。
    scanned_main_stems: set[str] = set()
    markdown_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(pre_dir):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in _EXCLUDED_DIR_NAMES
        ]
        current_dir = Path(dirpath)
        for dirname in dirnames:
            name = dirname
            entry = current_dir / dirname
            # 识别 _pages 后缀：report_pdf_pages / report_docx_pages / report_doc_pages
            for suffix in SCANNED_PAGE_SUFFIXES:
                if name.endswith(suffix):
                    # main stem 是 <source_stem>_<ext>（如 report_pdf）；chapters
                    # 目录命名是 <source_stem>_<ext>_chapters。两者 share
                    # `<source_stem>_<ext>` 前缀。
                    main_stem_with_ext = name[: -len("_pages")]
                    scanned_main_stems.add(
                        (entry.parent / main_stem_with_ext).resolve().as_posix()
                    )
                    break
        markdown_files.extend(
            current_dir / filename
            for filename in filenames
            if filename.lower().endswith(".md") and not filename.startswith(".")
        )
    # ======== [CoSight-END] feature: scanned-hide-chapters ========

    for fp in markdown_files:
        # _EXCLUDED_DIR_NAMES（references/、assets/）仅挡住"非文档类"子目录。
        if any(p in _EXCLUDED_DIR_NAMES for p in fp.parts):
            continue
        # PPT 文档的 *_ppt*_chapters/ 子目录不进 overview 树（与 *_slides 重复）
        if any(p.endswith(POWERPOINT_CHAPTER_SUFFIXES) for p in fp.parts):
            continue
        # ======== [CoSight-START] feature: scanned-hide-chapters ========
        # 扫描件的 _chapters/ 与 _pages/ 内容完全重复，隐藏前者保留后者。
        # 判定：当前 .md 在某 _chapters/ 子目录内 + 同一主文档存在 _pages/ 兄弟目录。
        chapters_parent = next(
            (p for p in fp.parts if p.endswith("_chapters")), None
        )
        if chapters_parent and chapters_parent.endswith("_chapters"):
            # 推导主文档 stem（与 _pages 推导一致）：剥 _chapters 后缀
            main_stem_with_ext = chapters_parent[: -len("_chapters")]
            main_md_dir = fp.parent.parent  # _chapters/ 的父目录 = 主 md 所在目录
            if (main_md_dir / main_stem_with_ext).resolve().as_posix() in scanned_main_stems:
                continue
        # ======== [CoSight-END] feature: scanned-hide-chapters ========
        indexed.add(str(fp.resolve()))
    return indexed


def _strip_ppt_suffix(stem: str) -> str:
    """把 <source_stem>_<ppt-ext> / <source_stem>.<ppt-ext> 等命名归一到 <source_stem>。

    preprocessor 历史上用了两种命名：
      - 旧版：<source_stem>.ppt.md / <source_stem>.pptx.md
      - 新版：<source_stem>_ppt.md / <source_stem>_pptx.md / <source_stem>_pptm.md
        （避免 . 把 stem 切成子目录）

    overview_builder 需要拿到 slides_dir 路径 = <source_stem>_<ppt-ext>_slides/，
    因此无论何种命名都要先剥掉 ppt/pptx 后缀再拼 slides 目录名。
    """
    lower = stem.lower()
    for suffix in (".pptm", ".pptx", ".ppt", "_pptm", "_pptx", "_ppt"):
        if lower.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _is_ppt_main_doc_filename(name: str) -> bool:
    """判断一个 .md 文件名是不是 PPT 主文档（python-pptx 整段提取产物）。

    兼容新旧命名：
      - 旧版 (dot)："<source_stem>.ppt.md" / "<source_stem>.pptx.md" / "<source_stem>.pptm.md"
      - 新版 (下划线)："<source_stem>_ppt.md" / "<source_stem>_pptx.md" / "<source_stem>_pptm.md"
    """
    lower = name.lower()
    return lower.endswith(
        (".ppt.md", ".pptx.md", ".pptm.md", "_ppt.md", "_pptx.md", "_pptm.md")
    )


def _is_scanned_main_doc_filename(name: str) -> bool:
    """判断一个 .md 文件名是不是扫描件 PDF/Word 主文档（doc_image_extractor 写的）。

    命名规则（preprocessor.py 的 `f"{stem}_{ext}".replace(".", "_")`）：
      - report.pdf → report_pdf.md
      - report.docx → report_docx.md
      - report.docm → report_docm.md
      - old.doc → report_doc.md

    与 _is_ppt_main_doc_filename 区别：扫描件主 md 拼合 `# 第 N 页 <title>-<desc>`，
    与 _pages/Page_NNN.md H1 章节完全重叠；ppt 主 md 拼合 `## Slide 1` 等，
    与 _pptx_slides/Slide_NN.md 节点重叠——两套都通过 skip_section_tree 避免重复。
    """
    lower = name.lower()
    return lower.endswith(("_pdf.md", "_docx.md", "_docm.md", "_doc.md"))


def _extract_headers(md_path: Path) -> list[tuple[int, str]]:
    """从 markdown 文件提取 (level, title) 列表，跳过代码块内的 # 行。"""
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"overview_builder: read failed md={md_path}: {e}")
        return []
    headers: list[tuple[int, str]] = []
    in_fence = False
    for raw in content.splitlines():
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADER_RE.match(raw)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if title:
                headers.append((level, title))
    return headers


def _build_dir_tree(rel_md_files: list[str], pre_dir: Path, show_sections: bool = True) -> dict:
    """将已索引的 .md 相对路径列表构造成嵌套 dict 树。

    返回结构：
    {
        "子目录名": {
            "再下一级子目录名": {
                "file.md": [(level, title), ...]   # 文件的章节列表
            }
        },
        "file.md": [(level, title), ...]
    }

    show_sections=False 时不提取章节标题（文件节点值为空 list），渲染层据此跳过
    章节子树，只输出 [DIR]/[F###] 行——章节树随文件数线性膨胀时的降级形态。
    """
    tree: dict = {}
    for rel in rel_md_files:
        parts = list(Path(rel).parts)
        cur = tree
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        md_path = pre_dir / rel
        cur[parts[-1]] = _extract_headers(md_path) if show_sections else []
    return tree


def _render_section_lines(headers: list[tuple[int, str]], indent_unit: str) -> list[str]:
    """渲染 .md 文件下的章节列表（按 # 层级缩进）。"""
    if not headers:
        return [f"{indent_unit}└── (无章节)"]
    lines: list[str] = []
    min_level = min(h[0] for h in headers)
    for i, (level, title) in enumerate(headers):
        is_last = (i == len(headers) - 1)
        branch = "└── " if is_last else "├── "
        prefix = indent_unit + "    " * (level - min_level)
        lines.append(f"{prefix}{branch}{title}")
    return lines


# node_index.json 保留字段：下一个可分配的节点编号（int）。
# overview_resolver._load_node_index 只收 value 为 str 的条目，该字段对所有
# 读取方天然不可见。
NEXT_ID_KEY = "_next_id"

# 本地节点 ID 格式：F + ≥3 位数字（如 F001）
_LOCAL_NODE_ID_PATTERN = re.compile(r"^F(\d{3,})$")


def _load_old_node_index(lan_dir: Path) -> tuple[dict[str, str], int]:
    """读取上一轮构建的 node_index.json 编号分配状态。

    Returns:
        (path_to_id, next_id):
            path_to_id: {rel_path: node_id} —— 上一轮文件的编号分配（反解表）；
            next_id: 下一个可分配编号。优先取 ``_next_id``；老版本没有该字段
                时回退为 max(现有编号)+1；文件缺失/损坏时从 1 开始。
    """
    node_index_path = lan_dir / "node_index.json"
    if not node_index_path.exists():
        return {}, 1
    try:
        data = json.loads(node_index_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(
            f"overview_builder: old node_index.json unreadable, "
            f"falling back to fresh allocation path={node_index_path}: {e}"
        )
        return {}, 1
    if not isinstance(data, dict):
        return {}, 1
    path_to_id: dict[str, str] = {}
    max_num = 0
    for k, v in data.items():
        m = _LOCAL_NODE_ID_PATTERN.match(k)
        if not m or not isinstance(v, str):
            continue
        # 路径分隔符归一：渲染侧 current_path 一律 "/" 连接；旧表 value 在
        # Windows 历史版本里可能带反斜杠，两种形态都注册，保证复用命中。
        path_to_id.setdefault(v, k)
        path_to_id.setdefault(v.replace("\\", "/"), k)
        max_num = max(max_num, int(m.group(1)))
    next_raw = data.get(NEXT_ID_KEY)
    next_id = (
        next_raw
        if isinstance(next_raw, int) and not isinstance(next_raw, bool)
        and next_raw > max_num
        else max_num + 1
    )
    return path_to_id, next_id


class _StableNodeIdAllocator:
    """节点 ID 稳定分配器：存活路径复用旧编号，新路径从 next_id 续排。

    顺序计数器会让"按字典序插到前面的新文件"把后续所有文件编号 +1，导致
    模型持有的旧 overview 里的 [F###] 被解析到错误文档。本分配器以 rel_path
    为身份复用旧编号；删除路径的编号退役不复用（next_id 单调递增、随
    node_index.json 的 ``_next_id`` 持久化），防止 ABA。
    """

    def __init__(self, path_to_id: dict[str, str], next_id: int):
        self._path_to_id = path_to_id
        self._next = next_id
        self._used: set[str] = set()

    def assign(self, rel_path: str) -> str:
        node_id = self._path_to_id.get(rel_path)
        if node_id is None or node_id in self._used:
            node_id = f"F{self._next:03d}"
            self._next += 1
        self._used.add(node_id)
        return node_id

    @property
    def next_id(self) -> int:
        return self._next


def _node_id_sort_num(node_id: str) -> int:
    """节点 ID 的排序键（数字部分）；非标准 ID 排到最后。"""
    m = _LOCAL_NODE_ID_PATTERN.match(node_id or "")
    return int(m.group(1)) if m else 1 << 30


def _subtree_min_id_num(sub: dict, path_prefix: str, id_by_path: dict[str, str]) -> int:
    """目录节点的排序键：子树内最小节点编号（目录本身无编号）。"""
    best = 1 << 30
    for k, v in sub.items():
        cur = f"{path_prefix}/{k}"
        if isinstance(v, dict) and v:
            best = min(best, _subtree_min_id_num(v, cur, id_by_path))
        else:
            best = min(best, _node_id_sort_num(id_by_path.get(cur, "")))
    return best


def _render_tree_lines(
    tree: dict, prefix: str, is_root: bool, root_prefix: str = "",
    path_prefix: str = "",
    counter: Optional[list[int]] = None,
    node_index: Optional[dict[str, str]] = None,
    compact: bool = False,
    show_sections: bool = True,
    id_by_path: Optional[dict[str, str]] = None,
) -> list[str]:
    """递归渲染嵌套 dict 树为树形行。

    is_root=True: 顶级，无 prefix 缩进
    否则按 prefix 缩进（prefix = "│   " 重复 N 次）
    path_prefix: 从根到当前节点父级的完整相对路径（不含当前 name）
    counter: 单元素 list [int]，用于在跨目录遍历时累计分配 [F###] 节点 ID。
             传 None 时创建一个新 list（每次调用 write_overview_md 独立计数）。
    node_index: dict，渲染过程中填充 `{node_id: rel_path}` 映射，供 overview_resolver 解析。
    compact: SOC 紧凑版——[DIR] 行显示相对根的完整相对路径（而非当前层级名）。
    show_sections: 是否在文件节点下渲染章节子树（章节列表需已由 _build_dir_tree
             提取；为 False 时跳过渲染，只输出 [DIR]/[F###] 行）。
    id_by_path: 预分配的 {rel_path: node_id}（V4）。传入时节点按 **ID 升序**
             渲染（目录按子树最早文档编号定位）；为 None 时回退旧行为
             （按名称排序 + counter 顺序编号）。

    节点前缀约定（V3 - 节点 ID 模式）：
    - 目录节点：`[DIR] <name>/`（仅显示当前层级名；compact 模式显示完整相对路径）
    - 文件节点：`[F001] <basename>` —— **稳定节点 ID + basename**，不再嵌完整路径。
      完整路径由 overview_resolver.py 通过 node_index 解析。
    """
    if counter is None:
        counter = [0]
    if node_index is None:
        node_index = {}
    lines: list[str] = []
    keys = list(tree.keys())
    if id_by_path is not None:
        # 按编号升序：文件取自身编号，目录取子树最小编号；同号按名称兜底。
        keys = sorted(
            keys,
            key=lambda k: (
                _subtree_min_id_num(
                    tree[k], f"{path_prefix}/{k}" if path_prefix else k, id_by_path
                )
                if isinstance(tree[k], dict) and tree[k]
                else _node_id_sort_num(
                    id_by_path.get(f"{path_prefix}/{k}" if path_prefix else k, "")
                ),
                k,
            ),
        )

    # §8.8.1 树形去重：当某 .md 文件有对应的 _chapters/ 兄弟目录时，文件作为叶子渲染（不展开章节树）
    # 找出哪些 .md 文件有对应的 _chapters/ 兄弟目录
    md_stems = {
        k[:-3] for k in keys if k.lower().endswith(".md")
    }
    chapter_dirs = {
        k[: -len("_chapters")] for k in keys if k.lower().endswith("_chapters")
    }
    mds_with_chapters = md_stems & chapter_dirs

    for i, name in enumerate(keys):
        is_last = (i == len(keys) - 1)
        branch = "└── " if is_last else "├── "
        node_prefix = root_prefix if is_root else (root_prefix + prefix)

        # 当前节点的完整相对路径（递归用 + 节点 ID 映射表的 value）
        current_path = f"{path_prefix}/{name}" if path_prefix else name

        # 先看子节点类型，决定本行是 [DIR] 还是 [FILE]
        sub = tree[name]
        is_dir = isinstance(sub, dict) and sub
        md_stem = name[:-3] if name.lower().endswith(".md") else None
        # §8.8.1 树形去重 + 节点形态筛选：
        # 1. ``<stem>_chapters/`` 兄弟目录存在 → 主 md 不展章节（章节子节点
        #    挂在 _chapters/ 下，避免重复）。
        # 2. **PPT 主文档**（``<stem>_<ppt-ext>.md`` / 旧版 ``<stem>.<ppt-ext>.md``）
        #    且对应 ``*_<ppt-ext>_slides/`` 兄弟目录
        #    在树中 → 主 md 不展章节。python-pptx 整段抓 PPT 文本时，每个 slide 的
        #    title/text_frame 都被写进主 md 作为 H1/H2（如 "## Slide N"、"## Chart"、
        #    "## Notes:"），这些章节与 per-slide 内容**完全重叠**（per-slide 节点在
        #    _pptx_slides/ 下完整展示）。再列主 md 的章节列表会与 per-slide 节点
        #    重复，且带来大量 "Notes:" / "Chart" 噪声。
        # 3. **扫描件主文档**（``*_pdf.md`` / ``*_docx.md`` / ``*_docm.md`` /
        #    ``*_doc.md``）且
        #    ``*_pages/`` 兄弟目录在树中 → 主 md 不展章节（主 md 按页拼合的 H2
        #    与 _pages/Page_NNN.md 的 H1 完全重叠）。
        # 注意：2/3 两条的跳过依据是"与兄弟节点内容重复"，因此收紧为**兄弟目录
        # 真实出现在本级树中**才跳过。兄弟目录不存在时（例如 SOC 标书知识库只索引
        # 主 md、不下发 _pages/_slides，或 slides/pages 抽取失败）按文件名无条件
        # 跳过会误伤正常文档的章节展示——此时主 md 的章节树是唯一内容导航。
        ppt_slides_sibling = md_stem is not None and any(
            f"{_strip_ppt_suffix(md_stem)}{suffix}" in keys
            for suffix in POWERPOINT_SLIDE_SUFFIXES
        )
        scanned_pages_sibling = md_stem is not None and f"{md_stem}_pages" in keys
        skip_section_tree = (
            not is_dir
            and (
                md_stem in mds_with_chapters
                or (_is_ppt_main_doc_filename(name) and ppt_slides_sibling)
                or (_is_scanned_main_doc_filename(name) and scanned_pages_sibling)
            )
        )
        if is_dir:
            # compact 模式（SOC 客户端没有 pre_dir，无法逐级拼路径）：
            # [DIR] 行直接显示相对根的完整相对路径，可原样传给 --path-prefixes
            dir_display = current_path if compact else name
            lines.append(f"{node_prefix}{branch}[DIR] {dir_display}/")
        else:
            # 文件节点：优先使用预分配的稳定节点 ID；未提供映射时回退顺序编号。
            if id_by_path is not None:
                node_id = id_by_path.get(current_path)
                if node_id is None:
                    # 防御：预分配表缺失该路径时仍保证可渲染。
                    counter[0] += 1
                    node_id = f"F{counter[0]:03d}"
            else:
                counter[0] += 1
                node_id = f"F{counter[0]:03d}"
            # ======== [CoSight-START] feature: pdf-word-image-vision ========
            # 扫描件页面节点（父目录为 <stem>_pages/）加 🖼️ 前缀，agent 在 Step 2
            # 挑候选时即知这是图片节点，预期 read-doc 可能要求读图。
            parent_name = Path(path_prefix).name if path_prefix else ""
            display_name = (
                f"🖼️ {name}" if parent_name.endswith("_pages") else name
            )
            # ======== [CoSight-END] feature: pdf-word-image-vision ========
            # 只显示 basename（与父目录结构正交），不再嵌完整路径
            lines.append(f"{node_prefix}{branch}[{node_id}] {display_name}")
            # 记录 node_id → current_path，供 overview_resolver.py 解析
            node_index[node_id] = current_path

        # 子项缩进：└── 后 4 空格，├── 后 "│   "
        if is_last:
            child_prefix = "    "
        else:
            child_prefix = "│   "

        # 非 root 层级要把当前 prefix 加进去
        if not is_root:
            child_prefix = prefix + child_prefix

        if is_dir:
            lines.extend(
                _render_tree_lines(
                    sub, child_prefix, is_root=False, path_prefix=current_path,
                    counter=counter, node_index=node_index, compact=compact,
                    show_sections=show_sections, id_by_path=id_by_path,
                )
            )
        elif isinstance(sub, list) and not skip_section_tree and show_sections:
            lines.extend(_render_section_lines(sub, child_prefix))
    return lines


# ======== [CoSight-START] feature: opt-big-overview 树文本压缩（R1-R6）========
# 背景：大库 overview.md 达 742,982 字符（≈30 万 token），超出 256K 上下文预算。
# 渲染后做一次纯文本压缩，真实大库实测 742,982 → 392,642 字符（-47%），规则
# 与实测明细见 design/opt-big-overview/implement.md W2。
#
# 安全性依据：
# - read-doc 按 [F###] 从磁盘 node_index.json 解析真实路径，展示名清洗不影响解析；
# - overview_resolver._renumber_tree_text 的 _LOCAL_NODE_ID_RE 只匹配 [F###] 本身，
#   与缩进/绘制符无关；
# - compact(SOC) 模式不压缩——其 [DIR] 行承载完整相对路径，被 --path-prefixes
#   原样消费，清洗名称会产生不存在的路径。

# R1 行解析：前导缩进（"│   " / "    " 4 字符/层）+ 可选绘制符 + 正文
_COMPRESS_LINE_RE = re.compile(r"^((?:│   |    )*)(?:[├└]── )?(.*)$")
# R3 构建哈希后缀 __xxxxxxxx
_HASH_SUFFIX_RE = re.compile(r"__[0-9a-f]{8}")
# R4/R5 机械后缀与扩展名
_DOC_SUFFIX_RE = re.compile(r"_(?:docx|txt|pdf|pptx|xlsx)\.md$")
_MD_EXT_RE = re.compile(r"\.md$")
# R6 连续下划线
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")
# R2 判重规范化：去序号前缀、去空白
_NORM_SERIAL_RE = re.compile(r"^\d+_")
_NORM_WS_RE = re.compile(r"\s+")
# [F###]/[DIR] 节点行
_NODE_MARK_RE = re.compile(r"^(\[(?:F\d+|DIR)\]\s*)(.*)$")


def _compress_node_name(name: str) -> str:
    """R3-R6 名称清洗：去哈希后缀、机械后缀、加粗标记、.md 扩展名、重复下划线。"""
    s = name
    s = _HASH_SUFFIX_RE.sub("", s)
    s = s.replace("**", "")
    s = re.sub(r"_docx_chapters(?=/)", "_chapters", s)
    s = re.sub(r"_docx_pages(?=/)", "_pages", s)
    s = _DOC_SUFFIX_RE.sub("", s)
    s = _MD_EXT_RE.sub("", s)
    s = _MULTI_UNDERSCORE_RE.sub("_", s)
    return s.strip().strip("_")


def _compress_norm(s: str) -> str:
    """R2 判重规范化：去序号前缀（01_）、去所有空白。"""
    return _NORM_WS_RE.sub("", _NORM_SERIAL_RE.sub("", s))


def _compress_tree_lines(tree_lines: list[str]) -> list[str]:
    """对渲染后的树形行做 R1-R6 压缩（仅主智能体全量版；compact 模式勿用）。

    R1 缩进紧凑化：4 字符/层缩进 + ├──/└── 绘制符 → tab（1 字符/层）
    R2 去重复标题行：文档内标题的规范化文本与任一祖先节点（[DIR]/[F] 清洗后
        名称）相同 → 整行删除（按祖先栈判重，同名跨分支不互删）
    R3-R6 节点名清洗：见 _compress_node_name
    """
    out: list[str] = []
    stack: dict[int, str] = {}  # depth -> 该深度最近节点的规范化名（祖先链）
    for line in tree_lines:
        m = _COMPRESS_LINE_RE.match(line)
        if not m:
            out.append(line)
            continue
        depth = len(m.group(1)) // 4
        body = m.group(2)
        # 弹出同级/更深的祖先（当前行顶替旧分支）
        stack = {k: v for k, v in stack.items() if k < depth}

        mm = _NODE_MARK_RE.match(body)
        if mm:
            # [DIR]/[F###] 节点行：清洗名称，保留 ID 标记
            mark, name = mm.group(1), mm.group(2)
            new_name = _compress_node_name(name)
            out.append("\t" * depth + mark + new_name)
            stack[depth] = _compress_norm(new_name)
            continue
        # 文档内标题行：R2 与祖先链判重
        txt = _compress_node_name(body)
        t = _compress_norm(txt)
        if t and t in set(stack.values()):
            continue  # 与祖先节点名重复 → 整行删除
        out.append("\t" * depth + txt)
        stack[depth] = t
    return out

# ======== [CoSight-END] feature: opt-big-overview ========


# 匹配 [FILE]/[F###] 节点行，用于 overview_resolver 解析 node_index
# 兼容老格式 [FILE] ...（如迁移期间 overview.md 文件未刷新）—— 不强制要求 F 开头，
# 仅作为信息提示。
_NODE_ID_LINE_RE = re.compile(r"^\s*[├└]──\s*\[(?P<id>[A-Z]?\d{3,})\]\s+(?P<basename>.+?)\s*$")


def clear_overview_md(lan_dir: Path) -> bool:
    """显式删除 overview.md 和 node_index.json。

    调用方（handler.py 等）在确认"pre_dir 真的永久为空"时调用，比如用户把
    工作目录下所有源文件都删了、且不是瞬时状态。
    与 write_overview_md 的"瞬时空就保留旧版"语义互补。

    Returns:
        True  当 overview.md 或 node_index.json 被删了（或本来就不存在）
        False 当删除失败
    """
    removed = False
    for name in ("overview.md", "node_index.json"):
        p = lan_dir / name
        if p.exists():
            try:
                p.unlink()
                removed = True
                logger.info(f"overview_builder: cleared {name} lan_dir={lan_dir}")
            except Exception as e:
                logger.warning(
                    f"overview_builder: failed to clear {name} path={p} error={e}"
                )
    return removed


_CHAPTER_DIR_SUFFIX = "_chapters"
_TOC_LABEL_RE = re.compile(r"^(?:目录|目\s*录|contents|table of contents)$", re.IGNORECASE)
_TOC_LINK_RE = re.compile(r"^[-*+]\s+\[[^\]]+\]\([^)]*\)\s*$")
_TOC_LEADER_RE = re.compile(r"(?:\.{3,}|…{2,}|·{3,}|-{3,})\s*\d{1,4}\s*$")
_TOC_NUMBERED_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)、]?\s+).+\s+\d{1,4}\s*$")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+")
_MD_RULE_LINES = {"---", "***", "___"}


def _chapter_main_candidates(rel: str) -> list[str]:
    """把 ``<dir>/<stem>_chapters/...`` 映射回可能的主文档路径。

    markdown 源预处理后会多一个 ``_md`` 后缀（``main.md`` → ``main_md.md``），
    但章节目录仍叫 ``main_chapters/``，所以候选同时包含 ``main.md`` 与
    ``main_md.md``。
    """
    parts = Path(rel).parts
    for idx in range(len(parts) - 2, -1, -1):
        if not parts[idx].endswith(_CHAPTER_DIR_SUFFIX):
            continue
        base = parts[idx][: -len(_CHAPTER_DIR_SUFFIX)]
        prefix = parts[:idx]
        names = [f"{base}.md", f"{base}_md.md"]
        return ["/".join((*prefix, name)) for name in names]
    return []


def _chapter_main_rel(rel: str) -> str | None:
    """兼容旧调用：返回首个主文档候选。"""
    candidates = _chapter_main_candidates(rel)
    return candidates[0] if candidates else None


def _classify_main_doc(pre_dir: Path, rel: str) -> str:
    """把主文档归类为 content / empty / toc。

    只用于带 ``_chapters/`` 的文档；正常文档不做整文件读取，避免 51W 构建
    额外扫一遍主文档。
    """
    try:
        text = (pre_dir / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        # 读失败时保守保留主文档，不做章节提升。
        return "content"
    content_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _MD_HEADING_RE.match(line) or line in _MD_RULE_LINES:
            continue
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        content_lines.append(line)
    if not content_lines:
        return "empty"
    toc_like = sum(
        1 for line in content_lines
        if _TOC_LABEL_RE.match(line)
        or _TOC_LINK_RE.match(line)
        or _TOC_LEADER_RE.search(line)
        or _TOC_NUMBERED_RE.match(line)
    )
    if toc_like == len(content_lines):
        return "toc"
    return "content"


def _has_page_or_slide_sibling(rel: str, dirs: set[str]) -> bool:
    """主文档是否已有 ``_pages``/``_slides`` 内容节点（避免重复提升章节）。"""
    p = Path(rel)
    parent = "/".join(p.parent.parts) if p.parent.parts else ""
    stem = p.stem
    candidates = {f"{stem}_pages"}
    if _is_ppt_main_doc_filename(p.name):
        base = _strip_ppt_suffix(stem)
        candidates.update(f"{base}{suffix}" for suffix in POWERPOINT_SLIDE_SUFFIXES)
    for name in candidates:
        candidate_dir = f"{parent}/{name}" if parent else name
        if candidate_dir in dirs:
            return True
    return False


def write_overview_md(lan_dir: Path, pre_dir: Path, compact: bool = False,
                      show_sections: Optional[bool] = None) -> Path | None:
    """从 pre_dir 构建 overview.md，写到 lan_dir。

    Args:
        lan_dir: LanceDB 数据目录
        pre_dir: 预处理后的 markdown 目录
        compact: SOC 紧凑版模式。True 时：
            - [DIR] 行显示相对知识库根的完整相对路径（客户端无 pre_dir，
              路径必须一眼可见、可原样传给 soc-general-qa-skill 的
              --path-prefixes）
            - 顶部 header 换成 OVERVIEW_COMPACT_HEADER（指令面向过滤检索，
              而非 read-doc 读全文）
            - 根标签用占位符 "[pre_dir]/"（客户端没有构建机的绝对路径）
        show_sections: 是否在文件节点下展开章节标题子树。默认 None = 跟随
            compact（非 compact 展开、compact 不展开，保持历史行为）；
            SOC 构建侧显式传 compact=True + show_sections=True 以随 zip
            下发含章节的文档树。compact 模式下章节树超过
            _COMPACT_SECTIONS_MAX_LINES 行时自动降级为不展开（防大库
            --tree 输出打爆 agent context）。

    Returns:
        写入的 overview.md 路径。无文件可索引或生成失败时返回 None。

    树形结构：完全按目录层级渲染
        [pre_dir_name]/
        ├── subdir1/
        │   ├── file1.md
        │   │   ├── H1
        │   │   ├── H2
        │   ├── file2.md
        │   │   └── H1
        ├── subdir2/
        │   └── file.md
        │       ├── H1
        │       └── H2
    """
    _ensure_root_logger()

    import time
    from common.logging_setup import log_event

    _t0 = time.perf_counter()
    log_event(
        logger, "overview:start",
        pre_dir=str(pre_dir), lan_dir=str(lan_dir),
        compact=compact, show_sections=show_sections,
    )

    if show_sections is None:
        # 默认跟随 compact：非 compact（主智能体全量版）展开章节、compact
        # （SOC 紧凑版）不展开——保持两个历史调用方行为不变；SOC 构建侧显式
        # 传 show_sections=True 才会在紧凑版里带章节。
        show_sections = not compact

    if not pre_dir or not pre_dir.exists():
        logger.info(
            f"overview_builder: skip (pre_dir not found) lan_dir={lan_dir} pre_dir={pre_dir}"
        )
        return None

    # 1. 从 pre_dir 拿"应当出现在 overview 树中的 .md"绝对路径集合
    # compact(SOC) 模式走剪枝快速路径：*_chapters/ 切片目录整棵跳过
    # （SOC 向量库只索引主 md，切片是中间产物/过期残留，详见
    # _read_indexed_files docstring），大库遍历规模从数十万压到主 md 量级。
    indexed_abs = _read_indexed_files(pre_dir, skip_chapters_dirs=compact)
    if not indexed_abs:
        # pre_dir 瞬时/永久为空。保留旧 overview.md（如果有），避免 delete→rebuild
        # 竞争场景把 overview 树永久清掉。调用方应自己判断是否要 clear。
        existing = lan_dir / "overview.md"
        if existing.exists():
            logger.warning(
                f"overview_builder: pre_dir has no .md but overview.md exists; "
                f"preserving last good version lan_dir={lan_dir}"
            )
            return existing
        logger.info(
            f"overview_builder: skip (pre_dir has no indexable .md, no prior overview.md) "
            f"lan_dir={lan_dir}"
        )
        return None

    # 2. 转换为 pre_dir 下的相对路径；过滤 references/ assets/ 和非 .md 文件
    # 文件名含非法 UTF-8 字节时（Linux surrogateescape 的 U+DC80–DCFF），
    # 在此统一清洗为 U+FFFD——否则第 4/5 步写 overview.md / node_index.json
    # 会因 UnicodeEncodeError 整文件失败（见 _sanitize_fs_text 注释）。
    rel_md_files: set[str] = set()
    for fp in indexed_abs:
        try:
            rel = str(Path(fp).resolve().relative_to(pre_dir.resolve()))
        except ValueError:
            rel = Path(fp).name
        rel = _sanitize_fs_text(rel)
        # 排除目录：references/ assets/ 等
        parts = Path(rel).parts
        if any(p in _EXCLUDED_DIR_NAMES for p in parts):
            continue
        # 只保留 .md 文件
        if not rel.lower().endswith(".md"):
            continue
        # 排除 .wiki_state.json 等元数据
        if Path(rel).name.startswith("."):
            continue
        rel_md_files.add(rel)

    if not rel_md_files:
        logger.info(
            f"overview_builder: skip (no .md files after filtering) lan_dir={lan_dir}"
        )
        return None

    # 主文档为准：`<stem>_chapters/` 是章节视图，不进入 overview 树，避免同一
    # 文档在树里出现两次（主 md + 每个章节 md）。章节文件仍参与稳定 ID 分配并
    # 写入 node_index，作为旧 `read-doc --node-id <chapter_id>` 的兼容别名。
    # 兜底：若整个库只有章节文件、没有主文档，则退回展示全部文件。
    def _is_chapter_rel(rel: str) -> bool:
        return any(part.endswith(_CHAPTER_DIR_SUFFIX) for part in Path(rel).parts)

    def _norm_rel(rel: str) -> str:
        return "/".join(Path(rel).parts)

    main_rel_md_files = {rel for rel in rel_md_files if not _is_chapter_rel(rel)}
    chapter_rel_md_files = rel_md_files - main_rel_md_files
    if not main_rel_md_files:
        # 全库只有章节文件：保持旧的全局兜底，全部展示。
        tree_rel_md_files = rel_md_files
        logger.warning(
            f"overview_builder: no main docs, falling back to chapter files "
            f"lan_dir={lan_dir}"
        )
    else:
        # M-3 边界：主文档存在但为空/仅 TOC 时，把对应章节提升为文档节点；
        # 主文档缺失时，也保留其章节，避免整个文档从树中消失。
        # 只有带 _chapters/ 的文档才读主文档内容，正常文档零额外读取。
        rel_norm = {_norm_rel(rel) for rel in rel_md_files}
        chapter_norm = {_norm_rel(rel): rel for rel in chapter_rel_md_files}
        dirs = {"/".join(Path(rel).parent.parts) for rel in rel_md_files
                if Path(rel).parent.parts}
        promote_prefixes: set[str] = set()
        promote_reasons: dict[str, str] = {}
        for main_rel in sorted(main_rel_md_files):
            main_norm = _norm_rel(main_rel)
            stem = Path(main_norm).stem
            dir_stems = {stem}
            if stem.endswith("_md"):
                # 预处理给 markdown 主文档加了 _md 后缀，章节目录通常没有。
                dir_stems.add(stem[:-3])
            parent = Path(main_norm).parent
            prefixes = {
                "/".join((*parent.parts, f"{name}{_CHAPTER_DIR_SUFFIX}")) + "/"
                for name in dir_stems
            }
            matching = [
                prefix for prefix in prefixes
                if any(name.startswith(prefix) for name in chapter_norm)
            ]
            if not matching:
                continue
            if _has_page_or_slide_sibling(main_rel, dirs):
                continue
            kind = _classify_main_doc(pre_dir, main_rel)
            if kind in {"empty", "toc"}:
                promote_prefixes.update(matching)
                promote_reasons[main_norm] = kind
        promoted_norm = {
            name for name in chapter_norm
            if any(name.startswith(prefix) for prefix in promote_prefixes)
        }
        # 主文档缺失的章节：按目录映射反查，找不到任何主文档候选则提升。
        for name in chapter_norm:
            candidates = _chapter_main_candidates(name)
            if not candidates:
                continue
            if any(_norm_rel(candidate) in rel_norm for candidate in candidates):
                continue
            if any(_has_page_or_slide_sibling(candidate, dirs) for candidate in candidates):
                continue
            promoted_norm.add(name)
            promote_reasons.setdefault(_norm_rel(candidates[0]), "missing")
        tree_rel_md_files = main_rel_md_files | {
            chapter_norm[name] for name in promoted_norm
        }
        if promote_reasons:
            logger.info(
                f"overview_builder: promoted chapters "
                f"docs={len(promote_reasons)} files={len(promoted_norm)} "
                f"reasons={promote_reasons} lan_dir={lan_dir}"
            )

    # 3. 构造目录树
    # 树形直接反映 pre_dir 实际结构：`<stem>_pptx_slides/` 作为真实子目录进入
    # 树中，per-slide .md 文件作为该目录下的 `[F###]` 节点。PPT 主 md 文件
    # 的 H1/H2 章节列表照常渲染（与 `_chapters/` 兄弟目录去重规则相同：
    # 当 _chapters 兄弟目录存在时，主 md 不展章节；否则照常）。
    tree = _build_dir_tree(sorted(tree_rel_md_files), pre_dir, show_sections=show_sections)

    # 4. 渲染输出（顶部说明 + 树）+ 节点索引（V3 节点 ID 模式）
    # 根节点直接用 pre_dir 绝对路径（用正斜杠），CoSightBot 拼接时无需再去
    # routes[].pre_dir 取值拼接，少一次路径算术，避免偏差。
    # compact 模式（SOC）根标签用占位符——客户端没有构建机的绝对路径，
    # [DIR] 行已带完整相对路径，根标签只做视觉锚点。
    if compact:
        label = "[pre_dir]/"
    elif pre_dir:
        label = f"{pre_dir.as_posix()}/"
    else:
        label = "[data]/"
    header = OVERVIEW_COMPACT_HEADER if compact else OVERVIEW_HEADER
    # V4 稳定编号 + 两遍式渲染：先按路径排序统一分配 ID（存活路径复用旧编号、
    # 新路径续排），再按 ID 升序渲染，显示序与编号序一致。
    old_path_to_id, old_next_id = _load_old_node_index(lan_dir)
    allocator = _StableNodeIdAllocator(old_path_to_id, old_next_id)
    id_by_path: dict[str, str] = {}
    for rel in sorted(rel_md_files):
        norm = "/".join(Path(rel).parts)
        id_by_path[norm] = allocator.assign(norm)

    node_index: dict[str, str] = {}
    tree_lines = _render_tree_lines(
        tree, prefix="│   ", is_root=True, node_index=node_index,
        compact=compact, show_sections=show_sections, id_by_path=id_by_path,
    )
    if (
        compact and show_sections
        and len(tree_lines) > _COMPACT_SECTIONS_MAX_LINES
    ):
        # 大库保护：章节树超行数上限 → 降级为纯 [DIR]/[F###] 紧凑树，避免
        # --tree 输出打爆 agent context。节点 ID 只按文件节点分配、与是否
        # 渲染章节无关，降级重渲染复用同一 id_by_path。
        logger.warning(
            f"overview_builder: section tree too large "
            f"({len(tree_lines)} lines > {_COMPACT_SECTIONS_MAX_LINES}), "
            f"falling back to nodes-only compact tree lan_dir={lan_dir}"
        )
        node_index = {}
        tree_lines = _render_tree_lines(
            tree, prefix="│   ", is_root=True, node_index=node_index,
            compact=compact, show_sections=False, id_by_path=id_by_path,
        )

    # 章节 alias：章节文件不渲染，但保留 id → rel_path 映射，旧
    # `read-doc --node-id <chapter_id>` 仍可读取。
    chapter_alias_count = 0
    for rel in sorted(rel_md_files):
        if not _is_chapter_rel(rel) or rel in tree_rel_md_files:
            continue
        norm = "/".join(Path(rel).parts)
        node_id = id_by_path.get(norm)
        if node_id:
            node_index[node_id] = rel
            chapter_alias_count += 1
    if not compact:
        # opt-big-overview：R1-R6 压缩（tab 缩进 + 去重复标题行 + 名称清洗），
        # 真实大库实测 -47%。compact(SOC) 模式跳过——[DIR] 行承载完整相对路径，
        # 被 --path-prefixes 原样消费，不能清洗。
        before_chars = sum(len(l) + 1 for l in tree_lines)
        tree_lines = _compress_tree_lines(tree_lines)
        after_chars = sum(len(l) + 1 for l in tree_lines)
        logger.info(
            f"overview_builder: compressed tree {before_chars} -> {after_chars} chars "
            f"(-{(before_chars - after_chars) * 100 // max(before_chars, 1)}%) "
            f"lan_dir={lan_dir}"
        )
    lines: list[str] = [header, "", label]
    lines.extend(tree_lines)

    out_path = lan_dir / "overview.md"
    try:
        # 首建路由时 lan_dir 可能尚未创建（status 落盘晚于 overview 写入），
        # 不 mkdir 会 Errno 2 并连带跳过 node_index.json，路由却已被标 ready
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(out_path, "\n".join(lines) + "\n")
    except Exception as e:
        logger.warning(
            f"overview_builder: write overview.md failed out={out_path}: {e}"
        )
        return None

    # 5. 写 node_index 旁路文件（JSON）：供 overview_resolver.py 解析 node_id → rel_path
    #    不依赖从 markdown 反向解析（避免 markdown 格式变化时影响工具链）。
    #    路径解析脚本（read-doc --node-id）以此为唯一可信源。
    #    node_index 当前结构: { "_next_id": <int>, <F###>: <rel_path> }
    #    ``_next_id`` 是稳定编号的分配水位线（resolver 只收 str value，天然跳过）。
    #    旧 schema 还含 "_meta_:<node_id>": { kind, image_relpath, doc_node_id, ... }，
    #    现已删除——PPT 元数据按"反查 slides_index.json"原则由 resolver 运行时读取，
    #    node_index.json 只承担 node_id → rel_path 映射 + 编号分配状态职责。
    node_index_path = lan_dir / "node_index.json"
    try:
        node_index_payload = {NEXT_ID_KEY: allocator.next_id, **node_index}
        _atomic_write_text(
            node_index_path,
            json.dumps(node_index_payload, ensure_ascii=False, indent=2) + "\n",
        )
    except Exception as e:
        logger.warning(
            f"overview_builder: write node_index.json failed out={node_index_path}: {e}"
        )
        # node_index.json 写失败不回滚 overview.md —— overview 仍然可用，
        # 但 read-doc --node-id 会回退到 markdown 解析（见 overview_resolver.py）

    # show_sections=False 时 tree 里文件节点的章节列表本来就是空的（未提取），
    # total_headers 自然计 0；show_sections=True 时章节已提取进 tree，直接
    # 从 tree 统计，不再逐文件重读 markdown（原实现对全量库是纯浪费的二读）。
    def _count_headers(t: dict) -> int:
        total = 0
        for v in t.values():
            if isinstance(v, dict):
                total += _count_headers(v)
            else:
                total += len(v)
        return total

    total_headers = _count_headers(tree)
    log_event(
        logger, "overview:done",
        out=str(out_path),
        files=len(tree_rel_md_files),
        chapter_aliases=chapter_alias_count,
        headers=total_headers,
        node_index=len(node_index),
        next_id=allocator.next_id,
        reused_ids=len(id_by_path) - (allocator.next_id - old_next_id),
        tree_lines=len(tree_lines),
        tree_chars=sum(len(line) + 1 for line in tree_lines),
        compact=compact,
        show_sections=show_sections,
        duration_ms=round((time.perf_counter() - _t0) * 1000, 1),
    )
    return out_path


