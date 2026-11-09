#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF/Word 图片提取与多模态识别编排。

两种文档形态（doc_type）：
  - mixed（图文混排）：主体是文字，内嵌图片。
      转 md 时保留图片在原文中的位置，图片统一收集到 ``<stem>_images/``；
      md 中图片位置替换为「图片地址 + 多模态 50-100 字描述」。
  - scanned（扫描件）：文字层为空，内容全在图里。
      每页渲染/提取为 PNG，多模态整页 OCR，一页生成一个 md，
      放在 ``<stem>_pages/Page_NNN.md``。

产物布局（rel_dir = 预处理 md 所在目录；命名与主 md ``<stem>_<ext>.md`` 对齐）：
    <rel_dir>/<stem>_<ext>_images/
        images_index.json        # kind="doc_images", doc_type="mixed"
        p<page>_i<seq>.png        # PDF 内嵌图提取命名（PDFium 不暴露 xref，改用页内序号）
        docx_img001.png          # mammoth 命名
    <rel_dir>/<stem>_<ext>_pages/      # 仅 scanned
        images_index.json        # kind="doc_images", doc_type="scanned"
        Page_001.png / Page_001.md
        ...

与 PPT slides 体系（ppt_slide_extractor / slides_index.json）平级，
overview_resolver 按 rel_path 约定反查 images_index.json 注入图片元数据。

调用方：preprocessor.process_single_file（PDF/DOC/DOCX 分支）。
函数不向下游抛异常：失败返回 {"handled": False, ...}，调用方回退到
legacy 纯文本转换路径。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from common.document_types import VISION_DOCUMENT_EXTS

logger = logging.getLogger("file_watcher.doc_image_extractor")

# ---------------------------------------------------------------------------
# 常量（与 feature-record/pdf_word_image_vision_feature_record.md §10 对齐）
# ---------------------------------------------------------------------------

# scanned/mixed 判定阈值：平均每页有效字符数低于此值视为扫描件
SCAN_TEXT_CHARS_PER_PAGE_THRESHOLD = 50
# 内嵌图最小边长（px），小于则视为装饰图（图标/分隔线）跳过识别与收集
MIN_IMAGE_DIMENSION = 100
# 扫描件整页渲染 DPI
SCAN_RENDER_DPI = 144

# 大批网页图片 OCR 切片阈值 —— 单次 _recognize_pending 最多处理这么多张。
# 实测单页 454 张单批 OCR 时上游 vision API 单批 done time 从 50s 渐增到
# 285s（服务端排队）。切到 ≤ WEB_OCR_CHUNK_SIZE 张后每批 done time 稳定在
# 5-10s，且中途崩溃可从已完成 chunk 的 images_index.json 继续。
WEB_OCR_CHUNK_SIZE = 60

# chunk 间隔 sleep：给上游 vision API 喘息窗口。
WEB_OCR_CHUNK_INTERVAL = 5.0

# 支持图片处理的扩展名。`.docm` 使用与 `.docx` 相同的 OOXML 读取路径；
# VBA 项目不会被解析或执行。
EXT_VISION_DOC = set(VISION_DOCUMENT_EXTS)

# 独立图片文件扩展名（支持绑定纯图片目录构建知识库）
EXT_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}

# 逐页处理路径的二级进度 stage 文案。
# 必须在单个文档的整个处理期间保持不变：stage 一变，progress_ui
# 的 start_file_subprogress 就会把 current 归零（见 progress_ui 中的 stage
# 切换重置逻辑），逐页上报的进度会被打回 0 反复闪烁。
# "完成量"由 current/total 承载，全部以"已 OCR 图数 / 总图数"为单位，
# 不要把页码或图序写进 stage 文案。
STAGE_MIXED_PER_PAGE = "OCR 识别中"
STAGE_SCANNED_PER_PAGE = "OCR 识别中"

# md 中图片占位标记（read-doc 运行时的数据门控，见 overview_resolver）
_MARK_DONE = "<!-- image-ocr:done {image_id} -->"
_MARK_PENDING = "<!-- image-ocr:pending {image_id} -->"
_MARK_FAILED = "<!-- image-ocr:failed {image_id} -->"

# 网页 / 通用 markdown 内嵌图识别的允许扩展名（与 web_page.download_assets
# 的内容类型范围一致 —— content-type 已被 SSRF/体积/类型三道闸控制过,这里再
# 过滤一次是为了兜底,mht / doc 边缘场景仍可能漏入非图片字节）
_WEB_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}


# ---------------------------------------------------------------------------
# 图片格式探测（修复 docx 内嵌 WMF/EMF 矢量图被多数视觉服务拒识）
# ---------------------------------------------------------------------------
#
# 背景：mammoth / python-docx / word/media 暴露的 ``content_type`` 只是 docx
# XML 里的声明（``<a:blip r:content_type="image/png">``），Word/WPS 编辑时
# 经常插入**矢量图（WMF/EMF）但仍声明 image/png**。我们信了声明按 .png
# 落盘，文件扩展名是 png，但上游视觉服务按真实字节识别 → HTTP 400
# ``cannot find loader for this WMF file``，整批 5 张全失败。
#
# 修复：``_detect_image_format`` 按 magic bytes 探测真实格式；WMF/EMF 跳过
# （上游视觉服务也不认，省一次 OCR 调用 + 不再污染 .md）。其他格式走原路径
# （content_type 信任 + write_bytes + 图片尺寸检查），行为不变。
#
# Magic bytes 表（参考 Wikipedia "List of file signatures"）：
#   PNG  : 89 50 4E 47 0D 0A 1A 0A          8 bytes
#   JPEG : FF D8 FF                           3 bytes
#   GIF  : 47 49 46 38 (37|39 61)             6 bytes
#   BMP  : 42 4D                             2 bytes
#   WEBP : 52 49 46 46 ?? ?? ?? ?? 57 45 42 50  12 bytes (RIFF....WEBP)
#   WMF  : D7 CD C6 9A                        4 bytes (placeable header 起点)
#          —— 纯 WMF 文件常以 "01 00 00 00 02 00 ..." 开头（无 placeable），
#          与 EMF magic 难仅靠前 8 字节区分；本探测只认带 placeable header
#          的 WMF，实测覆盖率足够（Office 写出的 WMF 都带 placeable）。
#   EMF  : 20 45 4D 46 (\x20EMF) 或 EMR_HEADER (rec_type=1, size=0x9C)
#
# WMF/EMF 是 Windows 矢量图格式，绝大多数现代多模态服务的视觉前端只装载 raster
# decoder（PNG/JPEG/GIF/BMP/WEBP）。把矢量图栅格化（pillow + ghostscript /
# wand / LibreOffice 命令行）会引入重依赖；本版本选择**直接跳过**，对混排 docx
# 而言内嵌矢量图本来就是装饰性图示，OCR 收益低，失败影响最小。

# magic bytes 表（每个 entry: 前缀字节 + 最小长度）
_MAGIC_SIGNATURES: tuple[tuple[bytes, str, int], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png", 8),
    (b"\xff\xd8\xff", "jpeg", 3),
    (b"GIF87a", "gif", 6),
    (b"GIF89a", "gif", 6),
    (b"BM", "bmp", 2),
    (b"\xd7\xcd\xc6\x9a", "wmf", 4),       # WMF placeable header
    (b"\x20\x45\x4d\x46", "emf", 4),       # "\x20EMF" 标识（部分 EMF）
    (b"RIFF", "webp", 12),                  # 需 WEBP 在 offset 8-11
)


def _detect_image_format(data: bytes) -> Optional[str]:
    """按 magic bytes 探测真实图片格式；无法识别时返回 None。

    不依赖 Pillow，零开销；用于在落盘前决策是否信任 docx content_type。
    """
    if not data:
        return None
    for sig, fmt, need in _MAGIC_SIGNATURES:
        if len(data) < need:
            continue
        if fmt == "webp":
            # RIFF + 4 字节 size + "WEBP"（12 字节总长，sig 只取 "RIFF" 4 字节）
            if data[:4] == sig and data[8:12] == b"WEBP":
                return fmt
            continue
        if data[:need] == sig:
            return fmt
    # EMF magic 不一定在 offset 0：标准 EMF 头是 EMR_HEADER record，结构为
    #   iType (4) + nSize (4) + rclBounds (16) + rclFrame (16) + dSignature (4)
    # = 40 字节。``dSignature`` 在 offset 40，固定值 ``b"\\x20EMF"``。EMR_HEADER
    # 的 nSize 是**变量**（按字段裁剪）：
    #   0x58 (88)   最小头（无 szlMicrometers / bOpenGL）
    #   0x6C (108)  含 szlMicrometers           ← TECS OpenStack docx 实测命中
    #   0x70 (112)  + bOpenGL
    #   0x78 (120)  + 描述字符串
    #   0x9C (156)  完整头
    # 之前只接受 ``rec_size == 0x9C`` 漏掉了 0x6C 等变体，导致 docx_img008.png
    # （EMF magic 在 offset 40、nSize=0x6C）被误判为 None → 漏过滤 → 上游视觉
    # 服务返回 HTTP 400 ``unknown format (2013)``。修复：接受合法范围 + 校验 offset 40
    # 的 dSignature；并对前 64 字节扫 ``\x20EMF`` 作为未来变种兜底。
    if len(data) >= 44:
        import struct as _struct
        try:
            rec_type, rec_size = _struct.unpack("<II", data[:8])
            d_signature = data[40:44]
            if (rec_type == 1
                    and 0x58 <= rec_size <= 0x9C
                    and d_signature == b"\x20\x45\x4d\x46"):
                return "emf"
        except _struct.error:
            pass
    # 兜底：扫前 64 字节找 "\x20EMF" magic（应对未来 EMR_HEADER 字段顺序变化）
    if b"\x20\x45\x4d\x46" in data[:64]:
        return "emf"
    # WMF 无 placeable header：纯 WMF 文件以 record 列表起始，最常见为
    # ``01 00 00 00 02 00`` (setWindowOrg / setWindowExt 起始)，但和 EMF 难
    # 仅靠 magic 区分。这里简化：落到这里的认为是不可识别，不当成 WMF（避免
    # 误判）。WMF 实测都带 placeable header（D7 CD C6 9A），覆盖率足够。
    return None


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def process_document_with_images(
    file_path: Path,
    output_dir: Path,
    relative_path: Path,
    *,
    session_key: Optional[str] = None,
    agent_id: Optional[str] = None,
    progress_callback: Optional[Callable[[float, int, str], None]] = None,
    on_page_done: Optional[Callable[[int, int], None]] = None,
) -> dict[str, Any]:
    """处理一个 PDF/Word 文档：提取图片 + 多模态识别 + 生成最终 markdown。

    Args:
        file_path:     源文件绝对路径（.pdf / .doc / .docx / .docm）
        output_dir:    预处理输出根目录（pre_dir）
        relative_path: 源文件相对 input_root 的路径（含文件名）
        session_key:   当前会话 key（解析会话级模型覆盖用）
        agent_id:      当前 agent id
        progress_callback:
                     可选 (current, total, stage) 进度回调。逐页 PDF 路径以
                     "页"为单位上报（current 可为小数，表示页内 OCR 推进度），
                     stage 在整个文档处理期间恒定；其余路径按图片数上报。

    Returns:
        {"handled": True,  "doc_type": "mixed"|"scanned",
         "markdown_content": str, "images_recognized": int, "images_pending": int}
        或
        {"handled": False, "reason": str}   —— 调用方回退 legacy 转换
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    if ext not in EXT_VISION_DOC:
        return {"handled": False, "reason": f"unsupported ext: {ext}"}

    source_path = file_path
    tmp_docx: Optional[str] = None
    try:
        # 老 .doc：先 win32com 转临时 .docx（Word/WPS），再走 docx 流程
        if ext == ".doc":
            tmp_docx = _convert_doc_to_docx(file_path)
            if not tmp_docx:
                return {"handled": False, "reason": "doc->docx COM conversion unavailable"}
            source_path = Path(tmp_docx)
            ext = ".docx"

        stem = file_path.stem
        rel_dir = Path(output_dir) / relative_path.parent
        # 产物目录命名与主 md（<stem>_<ext>.md，preprocessor 约定）对齐：
        # <stem>_<ext>_images / <stem>_<ext>_pages，点号统一替换为下划线
        ext_tag = file_path.suffix.lstrip(".")
        base = f"{stem}_{ext_tag}".replace(".", "_")
        images_dir = rel_dir / f"{base}_images"
        pages_dir = rel_dir / f"{base}_pages"

        # 1. 判定 doc_type
        if ext == ".pdf":
            doc_type = _detect_doc_type_pdf(source_path)
        else:
            doc_type = _detect_doc_type_docx(source_path)
        logger.info(
            f"doc_image_extractor: {file_path.name} doc_type={doc_type}"
        )

        # 2. 解析多模态配置（非多模态 → 全部 pending，图片照常收集）
        from common.vision_client import resolve_vision_llm_config
        llm_config = resolve_vision_llm_config(session_key=session_key, agent_id=agent_id)

        # 3. 分形态处理
        if doc_type == "scanned":
            if ext == ".pdf":
                # P3：扫描件 PDF 走按页增量处理（逐页渲染+OCR+append+on_page_done）
                return _process_scanned_pdf_per_page(
                    source_path, file_path, pages_dir, llm_config,
                    progress_callback=progress_callback,
                    on_page_done=on_page_done,
                )
            return _process_scanned(
                source_path, file_path, pages_dir, llm_config,
                progress_callback=progress_callback,
            )
        if ext == ".pdf":
            # P3：混排 PDF 走按页增量处理（逐页提取+OCR+append+on_page_done）
            return _process_mixed_pdf_per_page(
                source_path, file_path, images_dir, llm_config,
                progress_callback=progress_callback,
                on_page_done=on_page_done,
            )
        return _process_mixed(
            source_path, file_path, ext, images_dir, llm_config,
            progress_callback=progress_callback,
        )
    except Exception as e:
        logger.warning(
            f"doc_image_extractor: failed for {file_path.name}: {e}", exc_info=True
        )
        return {"handled": False, "reason": f"{type(e).__name__}: {e}"}
    finally:
        if tmp_docx:
            try:
                os.unlink(tmp_docx)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 公开 API（独立图片文件，绑定纯图片目录时使用）
# ---------------------------------------------------------------------------

def process_single_image(
    file_path: Path,
    output_dir: Path,
    input_root: Path,
    *,
    session_key: str = None,
    agent_id: str = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """处理单个独立图片文件：复制原图、生成 markdown、可选多模态 OCR。

    用于用户把工作目录绑定给 agent 时，目录内全是图片的场景。
    产物布局与 PDF/Word 混排体系对齐：
        <output_dir>/<rel_dir>/<stem>_<ext>.md
        <output_dir>/<rel_dir>/<stem>_<ext>_images/<orig_name>
        <output_dir>/<rel_dir>/<stem>_<ext>_images/images_index.json

    模型不支持图片输入时（resolve_vision_llm_config 返回 None），不调用 OCR，
    但仍生成占位 md + images_index.json（ocr_status=pending），并返回 handled=True。
    这样 fingerprint 会记录 success，避免每次绑定都重复尝试；后续切换为多模态
    模型时，preprocessor._is_fingerprint_match 的 pending 自愈逻辑会触发重处理。

    Args:
        file_path: 源图片绝对路径
        output_dir: 预处理输出根目录（pre_dir）
        input_root: 用户绑定的 material 目录
        session_key / agent_id: 透传给 resolve_vision_llm_config 取会话级模型配置
        progress_callback: 可选 (current, total, stage) 回调，OCR 阶段上报进度

    Returns:
        {"handled": True, "doc_type": "standalone_image",
         "images_recognized": N, "images_pending": N}
        或 {"handled": False, "reason": str}
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()
    if ext not in EXT_IMAGES:
        return {"handled": False, "reason": f"unsupported image ext: {ext}"}

    relative_path = file_path.relative_to(input_root)
    rel_dir = Path(output_dir) / relative_path.parent
    ext_tag = file_path.suffix.lstrip(".")
    base = f"{file_path.stem}_{ext_tag}".replace(".", "_")
    images_dir = rel_dir / f"{base}_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 复制原图到 images_dir，供 read-doc 反查与显示
    dest_image = images_dir / file_path.name
    try:
        shutil.copy2(file_path, dest_image)
    except Exception as e:
        logger.warning(f"doc_image_extractor: failed to copy image {file_path.name}: {e}")
        return {"handled": False, "reason": f"copy failed: {e}"}

    image_id = "img_001"
    images = [{
        "image_id": image_id,
        "filename": file_path.name,
        "image_relpath": file_path.name,
        "page_index": None,
        "ocr_status": "pending",
        "ocr_text": "",
        "error": None,
        "chapter_relpaths": [],
    }]

    md_path = rel_dir / f"{base}.md"
    initial_md = (
        f"# {file_path.stem}\n\n"
        f"![待识别图片]({images_dir.name}/{file_path.name})\n\n"
        f"{_MARK_PENDING.format(image_id=image_id)}\n"
    )
    try:
        md_path.write_text(initial_md, encoding="utf-8")
    except Exception as e:
        logger.warning(f"doc_image_extractor: failed to write md {md_path}: {e}")
        return {"handled": False, "reason": f"write md failed: {e}"}

    # 解析多模态配置；模型不支持时 llm_config=None，保持 pending
    try:
        from common.vision_client import resolve_vision_llm_config
        llm_config = resolve_vision_llm_config(session_key=session_key, agent_id=agent_id)
    except Exception as e:
        logger.warning(f"doc_image_extractor: resolve_vision_llm_config failed: {e}")
        llm_config = None

    if llm_config is not None:
        try:
            _recognize_pending(
                images,
                images_dir,
                llm_config,
                inline=True,
                progress_callback=progress_callback,
                original_path=file_path,
            )
            # 回写 md：把 pending marker 替换为 done/failed + OCR 文本
            rewritten = _rewrite_image_refs(
                md_path.read_text(encoding="utf-8"), images
            )
            md_path.write_text(rewritten, encoding="utf-8")
        except Exception as e:
            logger.warning(f"doc_image_extractor: OCR failed for {file_path.name}: {e}")
            # 保持 pending/失败状态，仍写索引

    try:
        _write_images_index(images_dir, file_path, "standalone_image", images, llm_config)
    except Exception as e:
        logger.warning(f"doc_image_extractor: write images_index failed: {e}")

    recognized = sum(1 for i in images if i["ocr_status"] == "done")
    pending = sum(1 for i in images if i["ocr_status"] == "pending")
    logger.info(
        f"doc_image_extractor: standalone image {file_path.name} "
        f"recognized={recognized} pending={pending}"
    )
    return {
        "handled": True,
        "doc_type": "standalone_image",
        "images_recognized": recognized,
        "images_pending": pending,
    }


# ---------------------------------------------------------------------------
# 公开 API（网页 / 通用 markdown，与 PDF/Word 走的是同一组内部 helper）
# ---------------------------------------------------------------------------

def process_web_page_with_images(
    md_path: Path,
    assets_dir: Path,
    *,
    source_url: str,
    rel_path_for_index: Optional[str] = None,
    markdown_text: Optional[str] = None,
    session_key: Optional[str] = None,
    agent_id: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    """对已落盘的 .md + assets/ 做多模态识别 → 写 images_index.json + 回写 md。

    与 ``process_document_with_images`` 的差别：
      - **不抽图**：调用方（wiki __main__.py / web_page.write_web_page）已经
        把图下载到 ``assets_dir``。本函数只负责扫 + 识别 + 元数据落盘。
      - **只走 inline 形态**（内嵌 50-100 字概括）：网页没有"整页扫描"概念，
        不存在 scanned 分支。
      - **images_index.json 落盘位置统一在 ``assets_dir.parent``** —— 与
        ``<title>.md`` 同级（wiki 流程）或与 slot 根 .md 同级（通用网页流程）。
        overview_resolver._rehydrate_web_image_meta 按 ``rel_path.parent / images_index.json``
        反查,与 PDF/Word 的 ``<stem>_<ext>_images/`` 命名约定不冲突。

    Args:
        md_path:               已写好的 .md 绝对路径(本函数会再回写一次)
        assets_dir:             图已下载到此目录(本函数从内部扫描)
        source_url:             原始 URL 字符串,写入 images_index.json 顶层 source
                               +每张图的 source_url 字段
        rel_path_for_index:     相对 pre_dir 的 .md 路径,写 index_relpath 用
        markdown_text:          直接传入 markdown 字符串(可选;为 None 时读 md_path)
        session_key / agent_id: 透传给 ``resolve_vision_llm_config``
        progress_callback:      可选 (current, total, stage) 三参进度回调。
                               阶段名固定为 ``"OCR 识别中"``,与 PDF/Word 流程
                               一致,便于 ``progress_ui`` 用同一渲染
                               路径显示二级进度条。
                               - 单批(<= WEB_OCR_CHUNK_SIZE 张)透传给
                                 ``_recognize_pending``,per-batch 精细进度。
                               - 多 chunk:本函数自己 fire chunk-level 进度
                                 (0 → 60 → 120 → ... → N),不传给内层,避免
                                 per-batch 信号淹没 chunk 信号。

    Returns:
        ``{"handled": True, "kind": "web_images",
           "images_recognized": N, "images_pending": N, "images_failed": M}``
        或 ``{"handled": False, "reason": str}``(以下场景一并落到这一支:
        assets_dir 不存在 / 读 md 失败 / 写索引失败 —— **异常一律吞掉不抛**)。

    降级契约:
      - 无 multimodal 模型:所有图 ocr_status=pending + ocr_text="";空 ocr_text 时
        overview 仍可解析索引。
      - API 调用失败:该图 ocr_status=failed + error;其余图不受影响。
    """
    md_path = Path(md_path)
    assets_dir = Path(assets_dir)
    try:
        if markdown_text is None:
            markdown_text = md_path.read_text(encoding="utf-8")

        # 1) 扫描本地图片(wiki / web_page 都已下载到此处)
        images = _load_local_assets(assets_dir, source_url=source_url)

        # 2) 无 multimodal 也要落盘"空"索引 + pending markdown,保证 read-doc 行为稳定
        try:
            from common.vision_client import resolve_vision_llm_config
            llm_config = resolve_vision_llm_config(
                session_key=session_key, agent_id=agent_id
            )
        except Exception as e:
            logger.info(
                f"doc_image_extractor: resolve_vision_llm_config failed: {e}"
            )
            llm_config = None

        if images:
            # 3) 复用 _recognize_pending:它会读 index_dir/images_index.json
            # 里的旧 done 条目按 image_id 命中,实现"只补识别 pending"。
            # inline=True 走 INLINE_IMAGE_SUMMARY_PROMPT(50-100 字中文概括)。
            #
            # 切片:超过 WEB_OCR_CHUNK_SIZE 张时,多次 _recognize_pending 之间
            # sleep WEB_OCR_CHUNK_INTERVAL 秒,避免大批请求堆上游导致单批 done
            # time 拉长(实测 152 batch 单批从 50s → 285s)。
            # _recognize_pending 会原地 mutate 传入的 chunk(写回 ocr_status /
            # ocr_text),跨 chunk 累积到 images 完整列表 —— 最终 _write_web_images_index
            # 用完整 images 落盘,中间态 index 只含当前 chunk 是允许的。
            #
            # 进度回调:单批透传给 _recognize_pending(per-batch 精细进度);
            # 多 chunk 由本函数自己 fire chunk-level 进度(0→60→...→N),
            # 不传给内层,避免 per-batch 信号淹没 chunk 信号。
            if len(images) <= WEB_OCR_CHUNK_SIZE:
                _recognize_pending(
                    images, assets_dir, llm_config, inline=True,
                    original_path=md_path, progress_callback=progress_callback,
                )
            else:
                total_chunks = (len(images) + WEB_OCR_CHUNK_SIZE - 1) // WEB_OCR_CHUNK_SIZE
                if progress_callback:
                    progress_callback(0, len(images), "OCR 识别中")   # 占位
                for chunk_idx, chunk_start in enumerate(range(0, len(images), WEB_OCR_CHUNK_SIZE), start=1):
                    chunk_end = min(chunk_start + WEB_OCR_CHUNK_SIZE, len(images))
                    chunk = images[chunk_start:chunk_end]
                    logger.info(
                        f"doc_image_extractor: web OCR chunk {chunk_idx}/{total_chunks} "
                        f"(images[{chunk_start + 1}-{chunk_end}/{len(images)}])"
                    )
                    # 多 chunk:把 progress_callback 透传给 _recognize_pending,
                    # 但加一层翻译把 chunk 内 current (cur_in_chunk) 翻成全局
                    # (chunk_start + cur_in_chunk)。_recognize_pending 内部 per-batch
                    # fire (cur, tot=len(chunk_todo), stage),底层 recognize_images
                    # 每 3 张图 done 就 fire 一次 —— 我们要让 UI 看到平滑的进度增长,
                    # 而不是只在 chunk 边界跳一次。
                    if progress_callback:
                        def _chunk_to_global(cur: int, _tot: int, stage: str) -> None:
                            progress_callback(chunk_start + cur, len(images), stage)
                        _recognize_pending(
                            chunk, assets_dir, llm_config, inline=True,
                            original_path=md_path, progress_callback=_chunk_to_global,
                        )
                    else:
                        _recognize_pending(
                            chunk, assets_dir, llm_config, inline=True,
                            original_path=md_path,
                        )
                    if chunk_end < len(images):
                        time.sleep(WEB_OCR_CHUNK_INTERVAL)
                    # chunk 完成时**不再**单独 fire —— per-batch fire 已经平滑
                    # 推进到 chunk_end 附近,避免 UI 显示从 0/N 突然跳到 60/N。

        # 4) markdown 改写 —— 复用 _rewrite_image_refs:它会按 image entry
        # 替换为 ![描述|待识别图片|识别失败](relpath) <!-- image-ocr:... -->
        if images:
            markdown_text = _rewrite_image_refs(markdown_text, images)

        # 5) 回写 md(无 images 时原地不动 —— 无图可替换)
        if images:
            md_path.write_text(markdown_text, encoding="utf-8")

        recognized = sum(1 for i in images if i["ocr_status"] == "done")
        pending = sum(1 for i in images if i["ocr_status"] == "pending")
        failed = sum(1 for i in images if i["ocr_status"] == "failed")

        # 6) 写 images_index.json —— 与 .md 同级(assets_dir.parent)
        #    仅在 assets_dir 本身存在时写 —— 没有 assets/ 目录的纯文字页
        #    无须落索引(overview_resolver 反查自然找不到,行为是普通的纯
        #    文本节点,与 doc_chapter 等无图情况一致)
        if assets_dir.is_dir():
            _write_web_images_index(
                assets_dir.parent, source_url, images, llm_config,
                rel_path_for_index=rel_path_for_index,
            )

        logger.info(
            f"doc_image_extractor: web image vision for {md_path.name}: "
            f"recognized={recognized} pending={pending} failed={failed}"
        )
        return {
            "handled": True,
            "kind": "web_images",
            "images_recognized": recognized,
            "images_pending": pending,
            "images_failed": failed,
        }
    except Exception as e:
        logger.warning(
            f"doc_image_extractor: process_web_page_with_images failed "
            f"for {md_path}: {e}", exc_info=True,
        )
        return {"handled": False, "reason": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# doc_type 判定
# ---------------------------------------------------------------------------

def _detect_doc_type_pdf(pdf_path: Path) -> str:
    """文字层平均每页字符 < 阈值 → scanned。"""
    from . import pdf_backend

    doc = pdf_backend.open_pdf(pdf_path)
    try:
        page_count = max(1, len(doc))
        total_chars = 0
        for page in doc:
            total_chars += len((page.get_text() or "").strip())
    finally:
        doc.close()
    avg = total_chars / page_count
    logger.info(
        f"doc_image_extractor: pdf text layer {total_chars} chars / "
        f"{page_count} pages (avg {avg:.0f})"
    )
    return "scanned" if avg < SCAN_TEXT_CHARS_PER_PAGE_THRESHOLD else "mixed"


def _detect_doc_type_docx(docx_path: Path) -> str:
    """正文文字 < 阈值 且存在嵌入图 → scanned。"""
    text_chars = 0
    try:
        import docx
        doc = docx.Document(str(docx_path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        text_chars = len("".join(parts).strip())
    except Exception as e:
        logger.info(f"doc_image_extractor: docx text probe failed: {e}")

    media_count = 0
    try:
        import zipfile
        with zipfile.ZipFile(str(docx_path)) as z:
            media_count = sum(1 for n in z.namelist() if n.startswith("word/media/"))
    except Exception:
        pass

    logger.info(
        f"doc_image_extractor: docx text {text_chars} chars, media {media_count}"
    )
    if text_chars < SCAN_TEXT_CHARS_PER_PAGE_THRESHOLD and media_count > 0:
        return "scanned"
    return "mixed"


# ---------------------------------------------------------------------------
# mixed（图文混排）
# ---------------------------------------------------------------------------

def _process_mixed(
    source_path: Path,
    original_path: Path,
    ext: str,
    images_dir: Path,
    llm_config: Optional[dict],
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    # 清理旧 PNG 残留：images_index.json 会被整体覆盖，但 _images/ 里多出的 PNG
    # 不会自动清——下次抽图减少 / 顺序变化时旧 PNG 残留。直接 rmtree 重建。
    if images_dir.exists():
        try:
            shutil.rmtree(images_dir)
        except OSError as e:
            logger.warning(f"doc_image_extractor: rmtree stale {images_dir}: {e}")
    images_dir.mkdir(parents=True, exist_ok=True)

    if ext == ".pdf":
        markdown_text, images = _extract_mixed_pdf(source_path, images_dir)
    else:
        markdown_text, images = _extract_mixed_docx(source_path, images_dir)

    # 多模态识别（复用已有 done 结果，只补识别未识别的图）
    _recognize_pending(
        images, images_dir, llm_config, inline=True,
        progress_callback=progress_callback, original_path=source_path,
    )

    # 用「描述 + 地址 + 标记」原位替换 md 中的图片引用
    markdown_text = _rewrite_image_refs(markdown_text, images)

    recognized = sum(1 for i in images if i["ocr_status"] == "done")
    pending = sum(1 for i in images if i["ocr_status"] == "pending")

    _write_images_index(
        images_dir, original_path, "mixed", images, llm_config
    )
    return {
        "handled": True,
        "doc_type": "mixed",
        "markdown_content": markdown_text,
        "images_recognized": recognized,
        "images_pending": pending,
    }


def _extract_mixed_pdf(pdf_path: Path, images_dir: Path) -> tuple[str, list[dict]]:
    """从混排 PDF 抽取文字 + 图片，按页面**纵向坐标交错**组装 markdown。

    走 :mod:`pdf_backend`（PDFium 底座），不依赖 pymupdf4llm：

      - **文字**：`page.get_text_blocks()` 拿段落矩形 + 文本（直接读整段），
        参考 ``run_eval_for_m3.extract_text_pdf`` 的写法。
        （之前用 pymupdf4llm.to_markdown 但它的图片落盘接口在空格路径上
        会触发 MuPDF C 层的 fz_save_pixmap_as_png 转义 bug；只取文字也不行——
        它会把图片输出成 ``**==> picture [W x H] intentionally omitted <==**``
        占位符，让图片无法按 y0 精确插入。）
      - **图片**：`page.get_images()`` + ``extract_image_png()`` 落盘
        （与 OCR 基准 ``run_eval_for_m3.extract_pdf_images`` 同样的实现）。
      - **位置**：把每页的文本块（y0 = 块顶）与图片 rect（y0 = 图顶）
        **合并到一个事件流，按 y0 升序排序**后逐项 emit，自然得出
        文字→图→文字→图 的 markdown 流水。

    图片命名：``p<page>_i<seq>.png``（``i<seq>`` 是本页图片的序号；PDFium 不
    暴露 PyMuPDF 的 xref，改用页内序号 + 内容哈希做跨页去重键）。
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    from . import pdf_backend

    doc = pdf_backend.open_pdf(pdf_path)
    images: list[dict] = []
    per_page_md: list[str] = []
    try:
        for pno in range(len(doc)):
            page = doc[pno]
            page_h: float = float(page.height) or 1.0

            # 第一遍：把本页所有图片存盘，收集 (y0, key, bbox, fname, ...)
            for seq, ref in enumerate(page.get_images()):
                x0, y0, x1, y1 = ref.bbox
                y_pct = (y0 / page_h)
                try:
                    data = page.extract_image_png(ref)
                    fname = f"p{pno + 1:03d}_i{seq:04d}.png"
                    (images_dir / fname).write_bytes(data)
                    img_id = Path(fname).stem
                except Exception as e:
                    logger.warning(
                        f"doc_image_extractor: pdf image key={ref.key} "
                        f"page={pno + 1} extract failed: {e}"
                    )
                    continue
                images.append({
                    "image_id": img_id,
                    "filename": fname,
                    "page_index": pno + 1,
                    "ocr_status": "pending",
                    "ocr_text": "",
                    "error": None,
                    # ======== [CoSight-START] feature: pdf-word-image-vision-position ========
                    # 位置信号：bbox (PDF 用户空间坐标) + y0 + y_pct（页内纵向百分比）。
                    "y0": y0,
                    "bbox": [x0, y0, x1, y1],
                    "y_pct": round(y_pct, 4),
                    "position_index": None,  # PDF 用 page_index+y0 定位，docx 用该字段
                    # ======== [CoSight-END] feature: pdf-word-image-vision-position ========
                })

            # 第二遍：构建一个统一事件流（kind="text"/"image"），按 y0 升序。
            # text 块只含文本块（pdf_backend 已按 type 过滤掉图片块）。
            events: list[tuple[float, int, dict]] = []
            for x0, y0, x1, y1, text in page.get_text_blocks():
                if not text or not text.strip():
                    continue
                events.append((float(y0), 0, {"text": text, "x0": x0, "y1": y1}))
            for img in images:
                if img["page_index"] != pno + 1:
                    continue
                events.append((
                    img["y0"], 1,
                    {"filename": img["filename"]},
                ))
            # 同 y 时：text 优先（保证图前后都有正文），再按 x0（左→右）
            events.sort(key=lambda e: (e[0], e[1], e[2].get("x0", 0)))

            # 第三遍：emit markdown——text 转干净段落，image 转 ``![待识别图片](rel)``
            page_parts: list[str] = []
            for y0, kind, payload in events:
                if kind == 0:
                    txt = payload["text"].strip()
                    # 合并块内多个 ``\n`` 为单换行，去前导 ``\n``
                    txt = re.sub(r"\n{2,}", "\n\n", txt)
                    page_parts.append(txt)
                else:
                    fname = payload["filename"]
                    page_parts.append(
                        f"![待识别图片]({images_dir.name}/{fname})"
                    )
            per_page_md.append("\n\n".join(p for p in page_parts if p))
    finally:
        doc.close()
    md = "\n\n".join(p for p in per_page_md if p)
    logger.info(
        f"doc_image_extractor: mixed pdf extracted {len(images)} image(s) "
        f"from {pdf_path.name}"
    )
    return md, images




# ---------------------------------------------------------------------------
# P3 按页增量处理（混排 PDF）
# ---------------------------------------------------------------------------

# 单页处理软超时（秒）。混排 PDF 逐页提取（PDFium）时，单页正常 <2s，
# 极端页（特大图/损坏页）可能卡；>PER_PAGE_TIMEOUT 跳过该页。
# 注意：OCR 不受此约束（OCR 已由 VISION_TOTAL_TIMEOUT 兜底）。
PER_PAGE_TIMEOUT = float(os.environ.get("COSIGHTBOT_PER_PAGE_TIMEOUT", "300"))
# 连续失败页数达到此值则放弃整个文件（防整文件卡在坏页）。
MAX_FAILED_PAGES = int(os.environ.get("COSIGHTBOT_MAX_FAILED_PAGES", "3"))


def _run_with_timeout(work_fn, timeout: float):
    """在守护子线程跑 work_fn，到点未完成则放弃（子线程随进程退出，不阻塞后续页）。

    返回 ('ok', result) / ('timeout', None) / ('err', exception)。
    用途：给 PDFium 提取等"无内部超时"的步骤加 per-page 硬约束。
    """
    import threading
    holder: dict = {}

    def _runner():
        try:
            holder["r"] = work_fn()
        except Exception as e:  # noqa: BLE001
            holder["e"] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return ("timeout", None)
    if "e" in holder:
        return ("err", holder["e"])
    return ("ok", holder.get("r"))


def _err_detail(res: Any) -> str:
    """失败详情（异常类型 + 消息），拼进告警日志。

    ``_run_with_timeout`` 把异常对象放在返回值里，不带出来的话日志只有
    "page 1/13 err"，定位不到是哪一步炸的。
    """
    if isinstance(res, BaseException):
        return f": {type(res).__name__}: {res}"
    return ""


def _append_text(md_path: Path, text: str) -> None:
    """原子追加：整体读 + 追加 + .tmp + os.replace。防中途崩溃丢半页。

    大文件（300 页）会随页数增长整体重写，I/O 为 O(N^2) 但 md 体积远小于源 PDF，
    可接受；换来"任何时刻中断都不丢半页"的可靠性。
    """
    if not text:
        return
    import os as _os
    existing = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    tmp = md_path.with_name(md_path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(existing)
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
    _os.replace(tmp, md_path)


def _extract_pdf_page(
    doc, pno: int, images_dir: Path,
    *,
    key_to_img: Optional[dict[str, dict]] = None,
) -> tuple:
    """抽取单页文本块 + 图片，返回 (页 md 片段, 本页图片 dict 列表, 本页新增图片映射)。

    图片 PNG 落盘到 images_dir；图片占位符暂为「待识别图片」，
    由调用方 OCR 后用 _rewrite_image_refs 原位替换。

    通过 ``key_to_img`` 对跨页/页内重复出现的同一张图去重：
    已处理过的图不再重复落盘和 OCR，markdown 里直接引用已有文件名，
    并同步其 OCR 状态，避免重复位置永远显示「待识别图片」。

    去重键是图片内容的哈希（PDFium 不暴露 PyMuPDF 的 xref），同一张图在多页
    重复出现时天然命中；仅在 /Resources 里声明但没画到本页的图，PDFium 根本
    不会枚举到，因此不会重复抽取。

    注意：本函数不修改传入的 ``key_to_img``，仅读取；本页首次出现的图片
    通过返回值 ``page_key_to_img`` 交给调用方在确认提取成功后合并，防止
    超时僵尸线程污染全局映射。
    """
    from . import pdf_backend

    page = doc[pno]
    page_h = float(page.height) or 1.0
    # 本地副本同时承载跨页去重和页内去重；new_keys 只收集本页首次出现。
    seen = dict(key_to_img) if key_to_img else {}
    new_keys: dict[str, dict] = {}
    new_imgs: list[dict] = []
    for seq, ref in enumerate(page.get_images()):
        key = ref.key
        x0, y0, x1, y1 = ref.bbox
        bbox = [x0, y0, x1, y1]
        y_pct = y0 / page_h

        existing = seen.get(key)
        if existing:
            # 重复图片：复用已有文件名与当前 OCR 状态，保证 markdown 重写正确
            fname = existing["filename"]
            img_id = existing["image_id"]
            ocr_status = existing.get("ocr_status", "pending")
            ocr_text = existing.get("ocr_text", "")
            error = existing.get("error")
            page_title = existing.get("page_title")
            page_desc = existing.get("page_desc")
        else:
            try:
                data = page.extract_image_png(ref)
                fname = f"p{pno + 1:03d}_i{seq:04d}.png"
                (images_dir / fname).write_bytes(data)
                img_id = Path(fname).stem
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"doc_image_extractor: pdf image key={key} "
                    f"page={pno + 1} extract failed: {e}"
                )
                continue
            ocr_status = "pending"
            ocr_text = ""
            error = None
            page_title = None
            page_desc = None

        img = {
            "image_id": img_id, "filename": fname, "page_index": pno + 1,
            "ocr_status": ocr_status, "ocr_text": ocr_text, "error": error,
            "y0": y0, "bbox": bbox, "y_pct": round(y_pct, 4), "position_index": None,
            "image_key": key,
        }
        if page_title is not None:
            img["page_title"] = page_title
        if page_desc is not None:
            img["page_desc"] = page_desc
        new_imgs.append(img)
        if key not in seen:
            seen[key] = img
            new_keys[key] = img
    events: list[tuple[float, int, dict]] = []
    for x0, y0, x1, y1, text in page.get_text_blocks():
        if not text or not text.strip():
            continue
        events.append((float(y0), 0, {"text": text, "x0": x0, "y1": y1}))
    for img in new_imgs:
        events.append((img["y0"], 1, {"filename": img["filename"]}))
    events.sort(key=lambda e: (e[0], e[1], e[2].get("x0", 0)))
    parts = []
    for y0, kind, payload in events:
        if kind == 0:
            txt = re.sub(r"\n{2,}", "\n\n", payload["text"].strip())
            parts.append(txt)
        else:
            parts.append(f"![待识别图片]({images_dir.name}/{payload['filename']})")
    return "\n\n".join(p for p in parts if p), new_imgs, new_keys


def _count_unique_images_in_pdf(doc) -> int:
    """预扫：返回整篇 PDF 中需要 OCR 的去重图片总数。

    过滤器与 ``_extract_pdf_page`` 完全一致：按图片内容哈希去重（同一张图被
    多页引用只算一次）。PDFium 只枚举**真正画到本页**的图片，仅在 /Resources
    里声明但未绘制的图（Word 转 PDF 常见）不会被计入。
    不解码像素：纯元数据查询，257 页亚秒级。
    """
    seen_keys: set[str] = set()
    for pno in range(len(doc)):
        page = doc[pno]
        for ref in page.get_images():
            seen_keys.add(ref.key)
    return len(seen_keys)


def _process_mixed_pdf_per_page(
    source_path: Path,
    original_path: Path,
    images_dir: Path,
    llm_config,
    *,
    progress_callback=None,
    on_page_done=None,
) -> dict:
    """混排 PDF 按页增量处理（P3）：逐页提取 → OCR → append 主 .md → on_page_done。

    每页完成即可 query（on_page_done 由调用方决定何时 ingest/overview）。
    单页超时（PDFium 提取，受 PER_PAGE_TIMEOUT 约束）不丢其余页；
    连续 MAX_FAILED_PAGES 页失败则放弃该文件（保留已完成页）。
    返回 md_written=True 提示调用方不要重写主 .md。
    """
    from . import pdf_backend
    # P3-4 断点续跑：若已有 images_index.json（上次部分处理的 OCR done 缓存），
    # 保留目录让 _recognize_pending 复用 done 项，重跑时只补未完成页的 OCR。
    # 无 index（全新或损坏）则 rmtree 重建，保证干净起点。
    _resume_index = images_dir / "images_index.json"
    if images_dir.exists() and not _resume_index.exists():
        shutil.rmtree(images_dir, ignore_errors=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    resumed = _resume_index.exists()
    if resumed:
        logger.info(
            f"doc_image_extractor: resume from existing images_index.json for "
            f"{original_path.name} (reuse done OCR)"
        )

    ext_tag = original_path.suffix.lstrip(".")
    base = f"{original_path.stem}_{ext_tag}".replace(".", "_")
    md_path = images_dir.parent / f"{base}.md"
    md_path.write_text(f"# {original_path.stem}\n\n", encoding="utf-8")

    doc = pdf_backend.open_pdf(source_path)
    total_pages = len(doc)
    total_images = _count_unique_images_in_pdf(doc)
    images: list[dict] = []
    key_to_img: dict[str, dict] = {}
    consecutive_fails = 0
    abandoned = False

    def _report(done_images: int) -> None:
        """按"已完成图数 / 总图数"上报二级进度。

        纯文字页（无图）OCR 不干活，进度条不动 —— 这是用户选择的语义，
        比"按页推进"更诚实反映实际工作量。
        """
        if not progress_callback:
            return
        try:
            progress_callback(int(done_images), max(1, total_images), STAGE_MIXED_PER_PAGE)
        except Exception:
            pass

    # 断点续跑起点：images_index.json 里已 done 的图数 —— 重跑时进度条不会
    # 从 0% 开始白跑已做完的图。
    done_images = 0
    if resumed and (images_dir / "images_index.json").is_file():
        try:
            _idx = json.loads((images_dir / "images_index.json").read_text(encoding="utf-8"))
            done_images = sum(
                1 for e in (_idx.get("images") or [])
                if isinstance(e, dict) and e.get("ocr_status") == "done"
                and (e.get("ocr_text") or "").strip()
            )
        except Exception as _ie:  # noqa: BLE001
            logger.info(f"doc_image_extractor: resume bootstrap failed: {_ie}")
    _report(done_images)

    try:
        for pno in range(total_pages):
            # 纯文字页（无图）OCR 不干活，按图计数的进度条不动 —— 用户选择的语义。
            status, res = _run_with_timeout(
                lambda p=pno: _extract_pdf_page(
                    doc, p, images_dir, key_to_img=key_to_img
                ),
                PER_PAGE_TIMEOUT,
            )
            if status != "ok":
                consecutive_fails += 1
                logger.warning(
                    f"doc_image_extractor: page {pno + 1}/{total_pages} {status} "
                    f"(consecutive_fails={consecutive_fails})"
                    f"{_err_detail(res)}"
                )
                if consecutive_fails >= MAX_FAILED_PAGES:
                    logger.error(
                        f"doc_image_extractor: abandon {original_path.name} after "
                        f"{consecutive_fails} consecutive page failures"
                    )
                    abandoned = True
                    break
                continue
            page_md, new_imgs, page_key_to_img = res
            # 提取成功后才合并本页新增 key，避免超时僵尸线程污染全局映射。
            key_to_img.update(page_key_to_img)
            unique_new_imgs = list(page_key_to_img.values())
            images.extend(unique_new_imgs)
            # OCR（主线程，受 VISION_TOTAL_TIMEOUT 约束；复用 done 缓存，增量写 index）
            # 用 callback 的 cur 计本页"新成功"的 OCR 数（_recognize_pending 已
            # 在内部把 image_id 命中 index 的项标 done、跳过 OCR；callback 只
            # 计本次实际 OCR 成功的项，不含复用项）。这样 done_images 不会把
            # 已经在 resume bootstrap 计数过的复用项重复加进来。
            latest_cur_holder = [0]
            def _img_cb(cur, _tot, _stage, _base=done_images):
                # 用 max() 而不是直接赋值：_recognize_pending 在 todo 内 OCR 之前
                # 会先发一次 (0, total, stage) 占位（见 _recognize_pending line 1793），
                # 那个 cur=0 不能覆盖真正的"本页新成功数"。
                if cur > latest_cur_holder[0]:
                    latest_cur_holder[0] = cur
                # _recognize_pending 的 callback 计的是本页 todo 内已成功数，
                # 折算成"已完成图数 = base + cur"。
                if progress_callback:
                    try:
                        progress_callback(
                            int(_base + cur), max(1, total_images), STAGE_MIXED_PER_PAGE
                        )
                    except Exception:
                        pass

            try:
                _recognize_pending(
                    unique_new_imgs, images_dir, llm_config, inline=True,
                    progress_callback=_img_cb if progress_callback else None,
                    original_path=original_path,
                    ocr_stage=STAGE_MIXED_PER_PAGE,
                    flush_images=images,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"doc_image_extractor: page {pno + 1} OCR failed: {e}")
            # done_images 增量 = 本页新 OCR 成功的图数（不包含 resume 复用项）
            done_images += latest_cur_holder[0]
            # 重写本页图片占位符（new_imgs 与 images 共享 dict 引用，OCR 状态已更新）
            page_md = _rewrite_image_refs(page_md, new_imgs)
            # 标题降一级（与 process_single_file 的最终产物一致）
            page_md = re.sub(r"^(#+)", r"#\1", page_md, flags=re.MULTILINE)
            page_md = page_md.replace("\r", "")
            _append_text(md_path, page_md)
            consecutive_fails = 0
            _report(done_images)
            if on_page_done:
                try:
                    on_page_done(pno + 1, total_pages)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"doc_image_extractor: on_page_done page {pno + 1} failed: {e}"
                    )
    finally:
        doc.close()

    recognized = sum(1 for i in images if i["ocr_status"] == "done")
    pending = sum(1 for i in images if i["ocr_status"] != "done")
    _write_images_index(images_dir, original_path, "mixed", images, llm_config)
    logger.info(
        f"doc_image_extractor: per-page mixed pdf {original_path.name} "
        f"pages={total_pages} recognized={recognized} pending={pending} abandoned={abandoned}"
    )
    return {
        "handled": True,
        "doc_type": "mixed",
        "md_written": True,
        "md_path": str(md_path),
        "markdown_content": md_path.read_text(encoding="utf-8"),
        "images_recognized": recognized,
        "images_pending": pending,
        "abandoned": abandoned,
    }


def _extract_mixed_docx(docx_path: Path, images_dir: Path) -> tuple[str, list[dict]]:
    """mammoth 自定义图片转换器：图片落盘 + 位置保留（<img src> 随文档顺序）。"""
    import mammoth
    import markdownify

    images: list[dict] = []

    def _save_image(image):
        with image.open() as f:
            data = f.read()
        # 🚨 不再信 mammoth 给的 content_type（Word/WPS 经常把 WMF/EMF 声明成
        # image/png，按声明落盘后上游视觉服务按真实字节识别为 WMF → HTTP 400
        # ``cannot find loader for this WMF file``）。先按 magic bytes 探测
        # 真实格式：WMF/EMF 直接跳过（上游视觉服务也不认，省一次 OCR 调用），
        # 其他格式走原 content_type 信任 + 原始 write_bytes(data) 路径。
        real_fmt = _detect_image_format(data)
        if real_fmt in ("wmf", "emf"):
            logger.warning(
                f"doc_image_extractor: skip unsupported vector image "
                f"(real_format={real_fmt}, declared_content_type="
                f"{(getattr(image, 'content_type', '') or 'unknown')!r}) "
                f"in {docx_path.name} — upstream vision service cannot "
                f"process WMF/EMF, dropping instead of wasting an OCR call"
            )
            return {"src": ""}
        # mammoth Image 提供 content_type（如 image/png）；旧版本无 extension 属性
        content_type = (getattr(image, "content_type", "") or "").lower()
        ext = content_type.rsplit("/", 1)[-1] if "/" in content_type else "png"
        if ext == "jpeg":
            ext = "jpg"
        if not ext.isalnum():
            ext = "png"
        # 装饰小图过滤：尺寸不可读时保守保留
        try:
            from . import pdf_backend
            dims = pdf_backend.image_size(data)
            if dims and (dims[0] < MIN_IMAGE_DIMENSION or dims[1] < MIN_IMAGE_DIMENSION):
                logger.info(
                    f"doc_image_extractor: skip decorative image "
                    f"{dims[0]}x{dims[1]} in {docx_path.name}"
                )
                return {"src": ""}
        except Exception:
            pass
        idx = len(images) + 1
        fname = f"docx_img{idx:03d}.{ext}"
        (images_dir / fname).write_bytes(data)
        images.append({
            "image_id": Path(fname).stem,
            "filename": fname,
            "page_index": None,
            # ======== [CoSight-START] feature: pdf-word-image-vision-position ========
            # mammoth 不暴露坐标 / 页号（只能按回调顺序推），用 position_index
            # 表达文档内第几张图；后续 python-docx 解析可补 page_index。
            "position_index": idx,
            "y0": None,
            "bbox": None,
            "y_pct": None,
            # ======== [CoSight-END] feature: pdf-word-image-vision-position ========
            "ocr_status": "pending",
            "ocr_text": "",
            "error": None,
        })
        return {"src": f"{images_dir.name}/{fname}"}

    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(_save_image)
        )
    md = markdownify.markdownify(result.value, heading_style="ATX")
    logger.info(
        f"doc_image_extractor: mixed docx extracted {len(images)} image(s) "
        f"from {docx_path.name}"
    )
    return md, images


_IMG_REF_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _rewrite_image_refs(markdown_text: str, images: list[dict]) -> str:
    """把 md 中的图片引用原位替换为「描述 + 相对地址 + ocr 标记」。

    图片地址统一收敛为 ``<images_dir.name>/<filename>``（相对 md 所在目录），
    兼容 pymupdf4llm 写出的绝对路径引用与 mammoth 写出的相对引用。
    """
    by_filename = {img["filename"]: img for img in images}

    def _replace(m: re.Match) -> str:
        ref_path = m.group(2).strip()
        fname = Path(ref_path.replace("\\", "/")).name
        img = by_filename.get(fname)
        if img is None:
            return m.group(0)  # 非本次收集的图（如 http 外链）保持原样
        rel = ref_path
        # 绝对路径 → 相对（只保留 目录名/文件名 两段）
        parts = Path(ref_path.replace("\\", "/")).parts
        if len(parts) >= 2:
            rel = f"{parts[-2]}/{parts[-1]}"
        status = img["ocr_status"]
        if status == "done":
            alt = _sanitize_alt_text(img["ocr_text"])
            mark = _MARK_DONE.format(image_id=img["image_id"])
        elif status == "failed":
            alt = "图片识别失败"
            mark = _MARK_FAILED.format(image_id=img["image_id"])
        else:
            alt = "待识别图片"
            mark = _MARK_PENDING.format(image_id=img["image_id"])
        return f"![{alt}]({rel}) {mark}"

    rewritten = _IMG_REF_RE.sub(_replace, markdown_text)
    # 装饰小图跳过时 mammoth 留下的空引用（![]() / ![]("")）顺手清掉
    rewritten = re.sub(r"!\[\]\(\s*(\"\"|'')\s*\)", "", rewritten)
    return rewritten


def _sanitize_alt_text(text: str) -> str:
    """OCR 描述转单行 markdown alt 文本（转义会破坏语法的括号）。"""
    one_line = re.sub(r"\s+", " ", (text or "")).strip()
    return (
        one_line.replace("[", "【").replace("]", "】")
        .replace("(", "（").replace(")", "）")
    )


# ---------------------------------------------------------------------------
# scanned（扫描件）
# ---------------------------------------------------------------------------

def _process_scanned(
    source_path: Path,
    original_path: Path,
    pages_dir: Path,
    llm_config: Optional[dict],
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, Any]:
    # 清理旧 pages 残留：Page_NNN.md 文件名稳定（按 idx 编号），但文档页数减少
    # 时老的 Page_NNN.md 仍留在 _pages/ 里；images_index.json 虽被覆盖，但旧 PNG 残留。
    # 直接 rmtree 重建。
    if pages_dir.exists():
        try:
            shutil.rmtree(pages_dir)
        except OSError as e:
            logger.warning(f"doc_image_extractor: rmtree stale {pages_dir}: {e}")
    pages_dir.mkdir(parents=True, exist_ok=True)

    if original_path.suffix.lower() == ".pdf":
        page_images = _render_scanned_pdf_pages(
            source_path, pages_dir,
            progress_callback=progress_callback,
        )
    else:
        page_images = _extract_scanned_docx_pages(
            source_path, pages_dir,
            progress_callback=progress_callback,
        )

    if not page_images:
        # 扫描件判定出错（连图都没有）→ 交回 legacy 文本路径
        return {"handled": False, "reason": "scanned doc has no page images"}

    images: list[dict] = []
    for idx, png in enumerate(page_images, start=1):
        images.append({
            "image_id": f"Page_{idx:03d}",
            "filename": png.name,
            "md_filename": f"Page_{idx:03d}.md",
            "page_index": idx,
            "ocr_status": "pending",
            "ocr_text": "",
            "error": None,
        })

    recognize_kwargs: dict[str, Any] = {}
    if progress_callback is not None:
        recognize_kwargs["progress_callback"] = progress_callback
        recognize_kwargs["original_path"] = source_path
    _recognize_pending(
        images,
        pages_dir,
        llm_config,
        inline=False,
        **recognize_kwargs,
    )

    # 标题/描述提取：扫描 OCR 文本前两行 `【标题: ...】\n【描述: ...】` 标记，
    # 写回 images[].page_title / page_desc。同时把"已剥离 marker 后的纯 OCR 正文"
    # 写回 images[].ocr_text 字段（避免 Page_NNN.md 正文里残留 marker 行）。
    # pending/failed 不提取（无文本）。
    for img in images:
        if img["ocr_status"] == "done" and img.get("ocr_text"):
            img["page_title"] = _extract_page_title(img["ocr_text"])
            img["page_desc"] = _extract_page_desc(img["ocr_text"])
            # 剥离 marker 行后存为 ocr_text_body（Page_NNN.md / 主 md 合并都读这个）
            img["ocr_text_body"] = _strip_title_marker(img["ocr_text"]).strip()

    # 每页写一个 md：done → OCR 全文；否则 → 占位标记（不写猜测性文本）
    for img in images:
        # Page_NNN.md 命名（**不嵌标题**）
        # - 标题已在主 md 的 H3 章节 `### 第 N 页 <title>-<desc>` 里——overview
        #   树展开章节节点就含完整描述
        # - 物理文件保持 Page_NNN.md 简短命名，避免中文 + hash 污染文件名
        # - read-doc 仍走 _is_doc_page_relpath 走物理路径（page_title / page_desc
        #   通过 images_index.json 注入到 read-doc 响应，不依赖文件名）
        page_no = img["page_index"]
        md_filename = f"Page_{page_no:03d}.md"
        img["md_filename"] = md_filename  # 让后续主 md 合并、images_index 都读到

        # Page_NNN.md H1 拼合：`# 第 N 页 <title>-<desc>`
        # - done 状态：H1 含完整描述（与主 md H3 章节内容一致）
        # - pending/failed 状态：H1 仅 "第 N 页"（无 OCR 文本可用）
        # overview_builder._render_section_lines 读 Page_NNN.md H1 作为章节子节点
        # 渲染（如 `├── 第 1 页 增值税发票-含服务费 13800 元`），与主 md H3 章节
        # 展示内容完全对齐，**避免物理文件 / overview 树两处信息漂移**。
        page_title = (img.get("page_title") or "").strip()
        page_desc = (img.get("page_desc") or "").strip()
        if img["ocr_status"] == "done" and page_title and page_desc:
            h1 = f"# 第 {page_no} 页 {page_title}-{page_desc}"
        elif img["ocr_status"] == "done" and page_title:
            h1 = f"# 第 {page_no} 页 {page_title}"
        elif img["ocr_status"] == "done" and page_desc:
            h1 = f"# 第 {page_no} 页 {page_desc}"
        else:
            h1 = f"# 第 {page_no} 页"
        lines = [h1, ""]
        if img["ocr_status"] == "done":
            body = (img.get("ocr_text_body") or img["ocr_text"] or "").strip()
            lines.append(body if body else "（OCR 无内容）")
        elif img["ocr_status"] == "failed":
            lines.append(_MARK_FAILED.format(image_id=img["image_id"]))
        else:
            lines.append(_MARK_PENDING.format(image_id=img["image_id"]))
        lines.append("")
        (pages_dir / md_filename).write_text(
            "\n".join(lines), encoding="utf-8"
        )

    recognized = sum(1 for i in images if i["ocr_status"] == "done")
    pending = sum(1 for i in images if i["ocr_status"] == "pending")

    _write_images_index(
        pages_dir, original_path, "scanned", images, llm_config
    )

    # 主 md：把每页 OCR 全文按页序合并为一份连贯文档（便于 LLM 入库检索，
    # 不必跳到 Page_001.md 之类去读）。每页区段**不写 H 标题**（避免与
    # _pages/Page_NNN.md 节点在 overview 树里重复展开——扫描件主 md 与
    # _pages/ 内容 1:1 重叠，写 ## 第 N 页 等于把页面节点画 2 次）。
    # 改用 `**第 N 页 · <标题>**` 粗体子标题 + > 描述 引述块——overview_builder
    # 只识别 H 标题，粗体/引述不会触发章节展开。
    # 每页仍保留：
    #   1. **粗体子标题** `**第 N 页 · <标题>**`
    #   2. `> <描述>` 引述（描述缺失时跳过）
    #   3. OCR 全文（done）/ 占位标记（pending|failed）
    #   4. 原始扫描图缩略图链接（指向 `<stem>_<ext>_pages/Page_NNN.png`）
    #   5. 逐页独立 md 链接（供 deep-link）
    # ——只有扫描件走这条路径。mixed 文档本身就是单 md，不重复合并。
    # 顶部 H1 文件名由 preprocessor 在写完 md 后自动加。
    pages_dir_name = pages_dir.name
    merged_parts: list[str] = [
        f"> 本文档为扫描件，共 {len(images)} 页。"
        f"正文按页识别后合并展示，原始逐页文件见 `{pages_dir_name}/` 目录。",
        "",
    ]
    for img in images:
        page_no = img["page_index"]
        page_png = f"{pages_dir_name}/{img['filename']}"
        page_md = f"{pages_dir_name}/{img['md_filename']}"
        page_title = (img.get("page_title") or "").strip()
        page_desc = (img.get("page_desc") or "").strip()

        # ======== [CoSight-START] feature: scanned-page-title ========
        # 主 md 页区用 H1 `# 第 N 页 <title>-<desc>` 拼合。
        # 与 Page_NNN.md H1 同层——两套展示**完全对齐**。
        # 为什么用 H1 不是 H2/H3：H1 不会被 preprocessor 升级（H1→H2 升级链
        # 对 H1 自身也升级，但 Page_NNN.md 在 _pages/ 子目录 preprocessor 不管），
        # 与 OCR 内部 H1 升级后到 H2 不冲突。
        if page_title and page_desc:
            merged_parts.append(f"# 第 {page_no} 页 {page_title}-{page_desc}")
        elif page_title:
            merged_parts.append(f"# 第 {page_no} 页 {page_title}")
        elif page_desc:
            merged_parts.append(f"# 第 {page_no} 页 {page_desc}")
        else:
            merged_parts.append(f"# 第 {page_no} 页")
        # ======== [CoSight-END] feature: scanned-page-title ========
        merged_parts.append("")

        if img["ocr_status"] == "done":
            body = (img.get("ocr_text_body") or img.get("ocr_text") or "").strip()
            merged_parts.append(body if body else "（OCR 无内容）")
        elif img["ocr_status"] == "failed":
            merged_parts.append(_MARK_FAILED.format(image_id=img["image_id"]))
        else:
            merged_parts.append(_MARK_PENDING.format(image_id=img["image_id"]))
        merged_parts.append("")
        merged_parts.append(
            f"![第 {page_no} 页原始扫描]({page_png}) "
            f"<!-- image-ocr:{img['ocr_status']} {img['image_id']} -->"
        )
        merged_parts.append("")
        merged_parts.append(
            f"> 完整逐页 md：[{img['md_filename']}]({page_md})"
        )
        merged_parts.append("")
    merged_md = "\n".join(merged_parts)
    return {
        "handled": True,
        "doc_type": "scanned",
        "markdown_content": merged_md,
        "images_recognized": recognized,
        "images_pending": pending,
    }




# ---------------------------------------------------------------------------
# P3 按页增量处理（scanned 扫描件 PDF）
# ---------------------------------------------------------------------------

def _write_page_md(pages_dir: Path, img: dict) -> None:
    """写单页 Page_NNN.md（与批量 _process_scanned 的产物一致）。"""
    page_no = img["page_index"]
    md_filename = img["md_filename"]
    page_title = (img.get("page_title") or "").strip()
    page_desc = (img.get("page_desc") or "").strip()
    if img["ocr_status"] == "done" and page_title and page_desc:
        h1 = f"# 第 {page_no} 页 {page_title}-{page_desc}"
    elif img["ocr_status"] == "done" and page_title:
        h1 = f"# 第 {page_no} 页 {page_title}"
    elif img["ocr_status"] == "done" and page_desc:
        h1 = f"# 第 {page_no} 页 {page_desc}"
    else:
        h1 = f"# 第 {page_no} 页"
    lines = [h1, ""]
    if img["ocr_status"] == "done":
        body = (img.get("ocr_text_body") or img.get("ocr_text") or "").strip()
        lines.append(body if body else "（OCR 无内容）")
    elif img["ocr_status"] == "failed":
        lines.append(_MARK_FAILED.format(image_id=img["image_id"]))
    else:
        lines.append(_MARK_PENDING.format(image_id=img["image_id"]))
    lines.append("")
    (pages_dir / md_filename).write_text("\n".join(lines), encoding="utf-8")


def _merged_page_section(img: dict, pages_dir_name: str) -> str:
    """生成主 md 中单页的合并区段（与批量 _process_scanned 的 merged 段一致）。
    注意：H1 `# 第 N 页` 由调用方在 append 前降一级（与 process_single_file 的最终产物对齐）。"""
    page_no = img["page_index"]
    page_png = f"{pages_dir_name}/{img['filename']}"
    page_md = f"{pages_dir_name}/{img['md_filename']}"
    page_title = (img.get("page_title") or "").strip()
    page_desc = (img.get("page_desc") or "").strip()
    parts: list[str] = []
    if page_title and page_desc:
        parts.append(f"# 第 {page_no} 页 {page_title}-{page_desc}")
    elif page_title:
        parts.append(f"# 第 {page_no} 页 {page_title}")
    elif page_desc:
        parts.append(f"# 第 {page_no} 页 {page_desc}")
    else:
        parts.append(f"# 第 {page_no} 页")
    parts.append("")
    if img["ocr_status"] == "done":
        body = (img.get("ocr_text_body") or img.get("ocr_text") or "").strip()
        parts.append(body if body else "（OCR 无内容）")
    elif img["ocr_status"] == "failed":
        parts.append(_MARK_FAILED.format(image_id=img["image_id"]))
    else:
        parts.append(_MARK_PENDING.format(image_id=img["image_id"]))
    parts.append("")
    parts.append(
        f"![第 {page_no} 页原始扫描]({page_png}) "
        f"<!-- image-ocr:{img['ocr_status']} {img['image_id']} -->"
    )
    parts.append("")
    parts.append(f"> 完整逐页 md：[{img['md_filename']}]({page_md})")
    parts.append("")
    return "\n".join(parts)


def _process_scanned_pdf_per_page(
    source_path: Path,
    original_path: Path,
    pages_dir: Path,
    llm_config,
    *,
    progress_callback=None,
    on_page_done=None,
) -> dict:
    """扫描件 PDF 按页增量处理（P3）：逐页渲染 → 整页 OCR → 写 Page_NNN.md
    → append 主 md 该页区段 → on_page_done。

    每页完成即可 query（on_page_done 决定何时 ingest/overview）。
    单页渲染超时（PER_PAGE_TIMEOUT）不丢其余页；连续 MAX_FAILED_PAGES 页失败放弃。
    返回 md_written=True 提示调用方不要重写主 .md。
    """
    from . import pdf_backend
    # P3-4 断点续跑：保留已有 images_index.json 以复用 done OCR
    _resume_index = pages_dir / "images_index.json"
    if pages_dir.exists() and not _resume_index.exists():
        shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    if _resume_index.exists():
        logger.info(
            f"doc_image_extractor: resume scanned from images_index.json for "
            f"{original_path.name} (reuse done OCR)"
        )

    ext_tag = original_path.suffix.lstrip(".")
    base = f"{original_path.stem}_{ext_tag}".replace(".", "_")
    md_path = pages_dir.parent / f"{base}.md"
    pages_dir_name = pages_dir.name

    doc = pdf_backend.open_pdf(source_path)
    total = len(doc)
    md_path.write_text(
        f"# {original_path.stem}\n\n"
        f"> 本文档为扫描件，共 {total} 页。"
        f"正文按页识别后合并展示，原始逐页文件见 `{pages_dir_name}/` 目录。\n\n",
        encoding="utf-8",
    )
    images: list[dict] = []
    consecutive_fails = 0
    abandoned = False
    try:
        if progress_callback:
            try:
                progress_callback(0, total, STAGE_SCANNED_PER_PAGE)
            except Exception:
                pass
        for pno in range(total):
            # 1. 渲染单页 PNG（per-page 超时硬约束）
            def _render(p=pno):
                out = pages_dir / f"Page_{p + 1:03d}.png"
                return doc[p].render_png(out, SCAN_RENDER_DPI)

            status, png_path = _run_with_timeout(_render, PER_PAGE_TIMEOUT)
            if status != "ok":
                consecutive_fails += 1
                logger.warning(
                    f"doc_image_extractor: scanned page {pno + 1}/{total} {status} "
                    f"(consecutive_fails={consecutive_fails})"
                    f"{_err_detail(res)}"
                )
                if consecutive_fails >= MAX_FAILED_PAGES:
                    logger.error(
                        f"doc_image_extractor: abandon scanned {original_path.name} "
                        f"after {consecutive_fails} consecutive page failures"
                    )
                    abandoned = True
                    break
                continue
            img = {
                "image_id": f"Page_{pno + 1:03d}",
                "filename": png_path.name,
                "md_filename": f"Page_{pno + 1:03d}.md",
                "page_index": pno + 1,
                "ocr_status": "pending", "ocr_text": "", "error": None,
            }
            images.append(img)
            # 2. 整页 OCR（主线程，受 VISION_TOTAL_TIMEOUT 约束；复用 done 缓存）
            try:
                _recognize_pending(
                    images, pages_dir, llm_config, inline=False,
                    progress_callback=None, original_path=original_path,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"doc_image_extractor: scanned page {pno + 1} OCR failed: {e}")
            # 提取 标题/描述
            if img["ocr_status"] == "done" and img.get("ocr_text"):
                img["page_title"] = _extract_page_title(img["ocr_text"])
                img["page_desc"] = _extract_page_desc(img["ocr_text"])
                img["ocr_text_body"] = _strip_title_marker(img["ocr_text"]).strip()
            # 3. 写 Page_NNN.md
            _write_page_md(pages_dir, img)
            # 4. append 主 md 该页区段（降一级标题与最终产物对齐）
            section = _merged_page_section(img, pages_dir_name)
            section = re.sub(r"^(#+)", r"#\1", section, flags=re.MULTILINE)
            _append_text(md_path, section)
            consecutive_fails = 0
            if progress_callback:
                try:
                    progress_callback(pno + 1, total, STAGE_SCANNED_PER_PAGE)
                except Exception:
                    pass
            if on_page_done:
                try:
                    on_page_done(pno + 1, total)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        f"doc_image_extractor: on_page_done scanned page {pno + 1} failed: {e}"
                    )
    finally:
        doc.close()

    recognized = sum(1 for i in images if i["ocr_status"] == "done")
    pending = sum(1 for i in images if i["ocr_status"] != "done")
    _write_images_index(pages_dir, original_path, "scanned", images, llm_config)
    logger.info(
        f"doc_image_extractor: per-page scanned pdf {original_path.name} "
        f"pages={total} recognized={recognized} pending={pending} abandoned={abandoned}"
    )
    return {
        "handled": True,
        "doc_type": "scanned",
        "md_written": True,
        "md_path": str(md_path),
        "markdown_content": md_path.read_text(encoding="utf-8"),
        "images_recognized": recognized,
        "images_pending": pending,
        "abandoned": abandoned,
    }


def _render_scanned_pdf_pages(
    pdf_path: Path,
    pages_dir: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> list[Path]:
    """PDFium 每页渲染 PNG（DPI=SCAN_RENDER_DPI）。

    progress_callback: 可选 (current, total, stage) 回调，每渲染 1 页触发一次。
    stage="抽取图片中" —— 区别于后续 OCR 阶段的 stage="OCR 识别中"。
    """
    from . import pdf_backend

    doc = pdf_backend.open_pdf(pdf_path)
    results: list[Path] = []
    total = len(doc)
    try:
        # 抽取图片开始：start(0, total, "抽取图片中") 让进度条立即出现（避免 1 分钟空白）
        if progress_callback:
            try:
                progress_callback(0, total, "抽取图片中")
            except Exception:
                pass
        for i in range(len(doc)):
            out_path = pages_dir / f"Page_{i + 1:03d}.png"
            doc[i].render_png(out_path, SCAN_RENDER_DPI)
            results.append(out_path)
            if progress_callback:
                try:
                    progress_callback(i + 1, total, "抽取图片中")
                except Exception:
                    pass
    finally:
        doc.close()
    logger.info(
        f"doc_image_extractor: rendered {len(results)} page(s) from {pdf_path.name}"
    )
    return results


def _extract_scanned_docx_pages(
    docx_path: Path,
    pages_dir: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> list[Path]:
    """Word 扫描件：按文档顺序提取嵌入图作为页面。

    注意：word/media/ 文件名字序不一定等于文档顺序，
    按 document.xml 中 drawing 引用（r:embed rId）顺序排序。

    progress_callback: 可选 (current, total, stage) 回调，每抽 1 张图触发一次。
    stage="抽图中" —— 区别于后续 OCR 阶段的 stage="OCR 识别中"。
    """
    import zipfile

    # 收集 ordered_media（无 progress hook；真正的进度在写文件循环）
    with zipfile.ZipFile(str(docx_path)) as z:
        # rId → media 文件名
        rels: dict[str, str] = {}
        try:
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
            for m in re.finditer(
                r'Id="([^"]+)"[^>]*Target="(media/[^"]+)"', rels_xml
            ):
                rels[m.group(1)] = m.group(2)
        except KeyError:
            pass
        # document.xml 中 r:embed 出现顺序 = 文档顺序。
        # 不去重：同一图片被引用 N 次就是 N 个页面位置（扫描件场景每页通常是
        # 不同图片；个别重复引用保留顺序语义，由后续 OCR 各自识别）。
        ordered_media: list[str] = []
        try:
            doc_xml = z.read("word/document.xml").decode("utf-8", "replace")
            for m in re.finditer(r'r:embed="([^"]+)"', doc_xml):
                target = rels.get(m.group(1))
                if target:
                    ordered_media.append(target)
        except KeyError:
            pass
        # 兜底：rels 解析失败时按文件名字序
        if not ordered_media:
            ordered_media = sorted(
                n[len("word/"):] for n in z.namelist() if n.startswith("word/media/")
            )

        total = len(ordered_media)
        # 抽取开始：start(0, total, "抽图中") 让进度条立即出现
        if progress_callback:
            try:
                progress_callback(0, total, "抽图中")
            except Exception:
                pass

        results: list[Path] = []
        skipped_unreadable: list[tuple[int, str, str]] = []  # (idx, media_rel, reason)
        for idx, media_rel in enumerate(ordered_media, start=1):
            data = z.read(f"word/{media_rel}")
            # 🚨 不再信 ``word/media/`` 的扩展名：Word/WPS 经常把 WMF/EMF 存成
            # .png/.jpg（content_type 也跟着声明错），落盘后上游视觉服务按真实
            # 字节识别失败 → ``cannot find loader for this WMF file``。先按
            # magic bytes 探测真实格式；WMF/EMF 跳过（上游视觉服务也不认），
            # 其他格式走原 write_bytes(data) + 扩展名路径。
            real_fmt = _detect_image_format(data)
            if real_fmt in ("wmf", "emf"):
                skipped_unreadable.append((idx, media_rel, real_fmt))
                # 总数仍按原 ordered_media 算（progress 反映真实抽图尝试数）
                if progress_callback:
                    try:
                        progress_callback(idx, total, "抽图中")
                    except Exception:
                        pass
                continue
            ext = Path(media_rel).suffix.lower() or ".png"
            out_path = pages_dir / f"Page_{idx:03d}{ext}"
            out_path.write_bytes(data)
            results.append(out_path)
            if progress_callback:
                try:
                    progress_callback(idx, total, "抽图中")
                except Exception:
                    pass

    logger.info(
        f"doc_image_extractor: extracted {len(results)} scanned page image(s) "
        f"from {docx_path.name}"
        + (f" (skipped {len(skipped_unreadable)} WMF/EMF page(s))"
           if skipped_unreadable else "")
    )
    if skipped_unreadable:
        # WARNING 而非 INFO：扫描件若跳过 WMF/EMF 页面，**实际页面内容会缺失**，
        # 管理员必须知情；混排 docx 那边是 WARNING 在 _save_image 内已打。
        logger.warning(
            f"doc_image_extractor: scanned docx skipped "
            f"{len(skipped_unreadable)} WMF/EMF page(s) from {docx_path.name} — "
            f"upstream vision service cannot process WMF/EMF, "
            f"rasterize the docx manually if these pages are needed: "
            + ", ".join(f"Page_{i:03d}({reason})" for i, _, reason in skipped_unreadable)
        )
    return results


# ---------------------------------------------------------------------------
# 标题提取（扫描页 OCR 文本首行 `=== 标题: ... ===` 解析）
# ---------------------------------------------------------------------------

# SCAN_PAGE_OCR_PROMPT 要求模型在 OCR 文本前两行输出 标题 + 描述 标记。
# marker 用 【】 而非 ===：避免与 vision_client._split_batch_response 的
# `=== 图 N ===` chunk 边界冲突。
# marker 关键字兼容中文「标题/描述」与英文 fallback「title/desc/titulo/description」。
_PAGE_TITLE_RE = re.compile(
    r"^\s*【\s*(?:标题|title|titulo)\s*:\s*(?P<title>.+?)\s*】\s*$",
    re.IGNORECASE,
)
_PAGE_DESC_RE = re.compile(
    r"^\s*【\s*(?:描述|desc|description)\s*:\s*(?P<desc>.+?)\s*】\s*$",
    re.IGNORECASE,
)
# OCR 标记字段长度上限（防御模型偶尔输出超长）：
# 标题 ≤ 20 中文字符 ≈ 40 Unicode 字符；描述 ≤ 40 中文字符 ≈ 80 Unicode 字符
_TITLE_MAX_CHARS = 40
_DESC_MAX_CHARS = 80


def _extract_page_title(ocr_text: str) -> str:
    """从 OCR 文本首行解析 `【标题: <≤20字>】`，剥掉后返回纯标题。"""
    if not ocr_text:
        return ""
    first_line = ocr_text.split("\n", 1)[0].strip()
    m = _PAGE_TITLE_RE.match(first_line)
    if not m:
        return ""
    title = m.group("title").strip()
    if len(title) > _TITLE_MAX_CHARS:
        title = title[:_TITLE_MAX_CHARS].rstrip()
    return title


def _extract_page_desc(ocr_text: str) -> str:
    """从 OCR 文本第二行解析 `【描述: <≤40字>】`，剥掉后返回纯描述。

    SCAN_PAGE_OCR_PROMPT 要求标题行 + 描述行**连写**（中间不要空行）。
    """
    if not ocr_text:
        return ""
    lines = ocr_text.split("\n", 5)  # 多查几行，避免前两行间有意外空行
    # 找标题行位置（首行匹配 _PAGE_TITLE_RE）
    title_idx = -1
    for i, line in enumerate(lines):
        if _PAGE_TITLE_RE.match(line.strip()):
            title_idx = i
            break
    if title_idx < 0 or title_idx + 1 >= len(lines):
        return ""
    next_line = lines[title_idx + 1].strip()
    m = _PAGE_DESC_RE.match(next_line)
    if not m:
        return ""
    desc = m.group("desc").strip()
    if len(desc) > _DESC_MAX_CHARS:
        desc = desc[:_DESC_MAX_CHARS].rstrip()
    return desc


def _strip_title_marker(ocr_text: str) -> str:
    """从 ocr_text 头部剥离 标题行 + 描述行（如果有），返回剩余正文。

    用于写 Page_NNN.md 的正文时不带 标题/描述 marker 行（它们已存为
    images[].page_title / page_desc）。

    额外处理：剩余正文里所有 H 标题行**降一级**（H1 → H2，H2 → H3...）——
    docx / mammoth 解析时会把文档内部小标题当成 H1 写进 OCR 全文
    （如 `# 增值税电子普通发票（第 1 / 3 页）`），不降级会污染 Page_NNN.md
    H1 拼合（让 _extract_headers 抓到 2 个 H1）。
    降一级而非剥掉：保留 docx 内部标题结构信息。

    升级实现参考 preprocessor.py:343（re.sub(r'^(#+)', r'#\1', ...)），反向
    应用——但因为正则从右边替换即可（preprocessor 用 `r'#\1'` 升级到 H+1），
    这里**从 H1 变成空 + 在原 H 前加 #**（reverse）较复杂；用**显式替换 # 为 ##
    + 限制**只对行首 # 处理（H 行才匹配），更直接。
    """
    if not ocr_text:
        return ocr_text
    lines = ocr_text.split("\n")
    # 找连续匹配 标题行 + 描述行 的前缀
    start_idx = 0
    if lines and _PAGE_TITLE_RE.match(lines[0].strip()):
        start_idx = 1
        if start_idx < len(lines) and _PAGE_DESC_RE.match(lines[start_idx].strip()):
            start_idx += 1
    # 剩余正文里所有 H 标题行降一级（H1 → H2、H2 → H3...）
    # 匹配行首 1-5 个 # + 空格，替换为 # + 1（升级一级）+ 原 # 序列
    body = "\n".join(lines[start_idx:])
    body = re.sub(r"^(#{1,5})", r"#\1", body, flags=re.MULTILINE)
    return body


# ---------------------------------------------------------------------------
# 识别编排（复用 done / 只补 pending / images_index.json）
# ---------------------------------------------------------------------------

def _recognize_pending(
    images: list[dict],
    index_dir: Path,
    llm_config: Optional[dict],
    *,
    inline: bool,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    original_path: Optional[Path] = None,
    ocr_stage: str = "OCR 识别中",
    flush_images: Optional[list[dict]] = None,
) -> None:
    """对 images 列表执行多模态识别（原地更新 ocr_status / ocr_text）。

    - 已有 images_index.json 中 ocr_status=done 的条目按 image_id 复用，
      实现"只补识别 pending 的图"，避免重建时重复消耗 token。
    - llm_config 为 None（当前模型非多模态）→ 全部保持 pending。
    - progress_callback 透传给 recognize_images（per-batch 触发）。
    - ocr_stage 允许调用方自定义 stage 文案。注意：stage 在单个文档处理期间必须
      恒定（逐页路径传 STAGE_*_PER_PAGE 常量），页码由调用方通过 current/total
      上报，不要拼进文案——见 STAGE_MIXED_PER_PAGE 处的说明。
    - flush_images 用于断点续传：OCR 完成后把 ``flush_images``（通常是调用方
      累积的全量列表）写入 images_index.json；默认与 ``images`` 相同。
    """
    if not images:
        return

    # 复用历史 done 结果
    index_path = index_dir / "images_index.json"
    if index_path.is_file():
        try:
            old = json.loads(index_path.read_text(encoding="utf-8"))
            old_done = {
                e.get("image_id"): e
                for e in (old.get("images") or [])
                if isinstance(e, dict) and e.get("ocr_status") == "done" and e.get("ocr_text")
            }
            for img in images:
                prev = old_done.get(img["image_id"])
                if prev:
                    img["ocr_status"] = "done"
                    img["ocr_text"] = prev["ocr_text"]
                    # 同步复用历史 page_title / page_desc（避免重建时丢失）
                    if prev.get("page_title"):
                        img["page_title"] = prev["page_title"]
                    if prev.get("page_desc"):
                        img["page_desc"] = prev["page_desc"]
        except Exception as e:
            logger.info(f"doc_image_extractor: reuse index failed {index_path}: {e}")

    todo = [img for img in images if img["ocr_status"] != "done"]
    if not todo:
        logger.info("doc_image_extractor: all images already recognized (reused)")
        return
    if llm_config is None:
        logger.info(
            f"doc_image_extractor: no multimodal model, {len(todo)} image(s) pending"
        )
        return

    from common.vision_client import (
        INLINE_IMAGE_SUMMARY_PROMPT,
        SCAN_PAGE_OCR_PROMPT,
        recognize_images,
    )
    prompt = INLINE_IMAGE_SUMMARY_PROMPT if inline else SCAN_PAGE_OCR_PROMPT
    total = len(todo)
    # recognize_images.progress_callback 签名是 (current, total) 两参；
    # 我们上层 progress_callback 现在是 (current, total, stage) 三参（v8 fix）；
    # 这里包一层把 ocr_stage 转发。
    if progress_callback:
        def _ocr_progress_cb(current, total):
            try:
                progress_callback(current, total, ocr_stage)
            except Exception:
                pass
        ocr_progress_cb = _ocr_progress_cb
        # 【v10 fix】渲染/抽取阶段结束后立刻占位发 (0, total, ocr_stage)，
        # 让 UI 从 "抽取图片中 ..." 立即切到 OCR stage，
        # 避免视觉上卡在抽取 100% 直到第一个 batch 完成。
        try:
            progress_callback(0, total, ocr_stage)
        except Exception:
            pass
    else:
        ocr_progress_cb = None
    results = recognize_images(
        [index_dir / img["filename"] for img in todo],
        prompt,
        llm_config=llm_config,
        progress_callback=ocr_progress_cb,
    )
    # P1-8 断点续传：OCR 全部跑完后立即写一次 images_index.json。
    # 若崩溃，已 done 项被持久化，下次重启时 _recognize_pending 入口的 reuse 逻辑会复用。
    for img, res in zip(todo, results):
        if res.get("ok") and res.get("text", "").strip():
            img["ocr_status"] = "done"
            img["ocr_text"] = res["text"].strip()
            img["error"] = None
        else:
            img["ocr_status"] = "failed"
            img["error"] = res.get("error") or "empty response"
    # 增量写一次 images_index.json（原子写，由 _write_images_index 提供）。
    # 使用 flush_images（默认 images）保证断点续传时全量历史记录被持久化。
    if original_path is not None:
        try:
            _write_images_index(
                index_dir,
                original_path,
                "mixed" if inline else "scanned",
                flush_images if flush_images is not None else images,
                llm_config,
            )
            _flush_list = flush_images if flush_images is not None else images
            logger.info(
                f"doc_image_extractor: incremental index flush ok "
                f"({sum(1 for x in _flush_list if x['ocr_status']=='done')}/{len(_flush_list)} done)"
            )
        except Exception as e:
            logger.warning(f"doc_image_extractor: incremental index flush failed: {e}")


def _write_images_index(
    index_dir: Path,
    original_path: Path,
    doc_type: str,
    images: list[dict],
    llm_config: Optional[dict],
) -> None:
    """写 images_index.json（read-doc 运行时判定的权威数据源）。"""
    entries: list[dict] = []
    for img in images:
        entry = {
            "image_id": img["image_id"],
            "image_relpath": img["filename"],  # 相对 index 所在目录
            "filename": img["filename"],       # 原始文件名，独立图片场景反查用
            "page_index": img.get("page_index"),
            "ocr_status": img["ocr_status"],
            "ocr_text": img.get("ocr_text") or "",
        }
        # 扫描页标题（≤20 字，OCR 阶段提取；pending/failed 时无）
        if img.get("page_title"):
            entry["page_title"] = img["page_title"]
        # 扫描页描述（≤40 字，OCR 阶段提取）
        if img.get("page_desc"):
            entry["page_desc"] = img["page_desc"]
        # 位置信号（PDF: bbox/y0/y_pct；DOCX: position_index）
        if img.get("bbox") is not None:
            entry["bbox"] = img["bbox"]
        if img.get("y0") is not None:
            entry["y0"] = img["y0"]
        if img.get("y_pct") is not None:
            entry["y_pct"] = img["y_pct"]
        if img.get("position_index") is not None:
            entry["position_index"] = img["position_index"]
        if img.get("md_filename"):
            entry["md_relpath"] = img["md_filename"]
        if img.get("error"):
            entry["error"] = img["error"]
        # 章节归属（混排 only）：chapter_splitter 切完章节后二扫填充
        # _chapters/ 子文件 relpath 列表。overview_resolver._rehydrate_doc_image_meta
        # doc_chapter 路径按此字段精确过滤本章节图集合，避免 LLM 读主文档全部图。
        # 初始空 list —— chapter_splitter 后处理填充。
        entry["chapter_relpaths"] = []
        entries.append(entry)

    index = {
        "schema_version": 1,
        "kind": "doc_images",
        "doc_type": doc_type,
        "source": str(original_path),
        "ocr_engine": (llm_config or {}).get("model_id"),
        "images": entries,
    }
    index_path = index_dir / "images_index.json"
    try:
        # P1-4 原子写：.tmp + os.replace，防硬杀 worker 时半写被读为合法 JSON
        import os as _os
        tmp = index_path.with_name(index_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        _os.replace(tmp, index_path)
    except OSError as e:
        logger.warning(f"doc_image_extractor: write index failed {index_path}: {e}")


# ---------------------------------------------------------------------------
# 网页内嵌图扫描 + 索引落盘（与 PDF/Word 的 _write_images_index 平级）
# ---------------------------------------------------------------------------

def _load_local_assets(
    assets_dir: Path,
    *,
    source_url: str,
) -> list[dict]:
    """扫 ``assets_dir`` 下的本地图片,组装成 ``_recognize_pending`` 用的 images 列表。

    与 PDF/Word 的 images entry 字段完全同形(让 _rewrite_image_refs/_recognize_pending
    直接复用):
      - ``image_id`` = ``img_NNN``(N 从 001 起,与 docx_imgNNN 同前缀避免混淆)
      - ``filename`` = basename(供 _rewrite_image_refs 按文件名匹配)
      - ``image_relpath``(本函数内计算,后面单独写到索引里)
      - ``page_index`` 固定 None(网页无整页概念)
      - ``source_url`` 来自 caller 传入的 source_url 字段
      - ``ocr_status`` 统一起手 pending
    """
    images: list[dict] = []
    if not assets_dir.is_dir():
        return images
    # 按文件名排序 —— 保证多次跑同一页面 image_id 一致,便于 _recognize_pending
    # 按 image_id 复用上次 done 结果
    candidates = sorted(
        (p for p in assets_dir.iterdir() if p.is_file() and p.suffix.lower() in _WEB_IMAGE_EXTS),
        key=lambda p: p.name,
    )
    for idx, p in enumerate(candidates, start=1):
        image_id = f"img_{idx:03d}"
        fname = p.name
        images.append({
            "image_id": image_id,
            "filename": fname,
            "image_relpath": fname,  # 写索引时使用,相对 index_dir
            "page_index": None,
            "ocr_status": "pending",
            "ocr_text": "",
            "error": None,
            "source_url": source_url,
            # 网页无章节切分 —— 留空 list 让 schema 与 PDF/Word 同形
            "chapter_relpaths": [],
        })
    return images


def _write_web_images_index(
    index_dir: Path,
    source_url: str,
    images: list[dict],
    llm_config: Optional[dict],
    *,
    rel_path_for_index: Optional[str] = None,
) -> None:
    """写 ``<index_dir>/images_index.json``(网页体系),schema 与 PDF/Word 同形。

    与 ``_write_images_index`` 的区别:
      - 顶层 ``kind = "web_images"``(新枚举值);``doc_type = None``
      - source 字段存 URL(不是本地文件路径)
      - image 条目额外带 ``source_url`` 字段,方便原图溯源
      - ``page_index / md_relpath`` 网页始终 None
      - ``chapter_relpaths`` 始终 []
    """
    entries: list[dict] = []
    for img in images:
        entry: dict = {
            "image_id": img.get("image_id"),
            "image_relpath": img.get("filename"),  # 相对 index_dir
            "page_index": None,
            "ocr_status": img.get("ocr_status", "pending"),
            "ocr_text": img.get("ocr_text") or "",
            "source_url": img.get("source_url") or source_url,
            "chapter_relpaths": [],
        }
        # 兼容:done 时保留 ocr_text/无 error,failed 时写 error
        if img.get("error"):
            entry["error"] = img["error"]
        entries.append(entry)
    index = {
        "schema_version": 1,
        "kind": "web_images",
        "source_kind": "web_images",
        "doc_type": None,
        "source": source_url,
        "ocr_engine": (llm_config or {}).get("model_id"),
        "images": entries,
    }
    if rel_path_for_index:
        index["rel_path"] = rel_path_for_index
    index_path = index_dir / "images_index.json"
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning(
            f"doc_image_extractor: write web index failed {index_path}: {e}"
        )


# ---------------------------------------------------------------------------
# 老 .doc → .docx（Windows：win32com，与 preprocessor.convert_word_to_md
# 同一套 ProgID；Linux：office_bridge，LibreOffice headless 承担同角色）
# ---------------------------------------------------------------------------

def _convert_doc_to_docx(doc_path: Path) -> Optional[str]:
    """把老 .doc 另存为临时 .docx，返回临时路径。

    可用 Office 自动化后端不可用（未装 Office/WPS）时返回 None。
    """
    if os.name != "nt":
        # Linux：走 office_bridge（soffice headless），
        # 契约一致——成功返回临时 docx 路径，失败返回 None
        try:
            from .office_bridge import convert_doc_to_docx as _bridge_convert
        except Exception as e:
            logger.info(f"doc_image_extractor: office_bridge unavailable: {e}")
            return None
        return _bridge_convert(doc_path)

    word_app = None
    tmp_fd, tmp_docx = tempfile.mkstemp(suffix=".docx")
    try:
        os.close(tmp_fd)
        import win32com.client
        for prog_id in ["Word.Application", "Kwps.Application", "WPS.Application"]:
            try:
                word_app = win32com.client.Dispatch(prog_id)
                if word_app:
                    break
            except Exception:
                continue
        if not word_app:
            logger.info("doc_image_extractor: no COM app available for .doc")
            return None
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        doc_obj = word_app.Documents.Open(os.path.abspath(str(doc_path)))
        doc_obj.SaveAs2(tmp_docx, FileFormat=12)  # 12 = wdFormatXMLDocument
        doc_obj.Close()
        word_app.Quit()
        word_app = None
        return tmp_docx
    except Exception as e:
        logger.info(f"doc_image_extractor: doc->docx failed for {doc_path.name}: {e}")
        return None
    finally:
        if word_app:
            try:
                word_app.Quit()
            except Exception:
                pass
