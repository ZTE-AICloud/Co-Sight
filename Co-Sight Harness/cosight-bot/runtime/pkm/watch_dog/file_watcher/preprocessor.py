#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件预处理

将各种格式文档（PDF/Office/HTML/MHTML/Text）转换为 Markdown，
供 LlamaIndex 索引使用。

"""

import os
import re
import time
import hashlib
import tempfile
import logging
import threading
import json
from pathlib import Path
from typing import Any, Callable, Optional
from email import message_from_bytes
from typing import Callable, Optional

from common.document_types import (
    EXCEL_DOCUMENT_EXTS,
    OFFICE_DOCUMENT_EXTS,
    POWERPOINT_DOCUMENT_EXTS,
    SUPPORTED_DOCUMENT_EXTS,
    VISION_DOCUMENT_EXTS,
    WORD_DOCUMENT_EXTS,
)

logger = logging.getLogger("file_preprocessor")


class ProcessResult(list):
    """List of processed file paths, carrying success/failure counts.

    Behaves as a plain list for backward compatibility with callers that
    iterate or check truthiness, but exposes ``success_count`` and
    ``failed_count`` for statistics reporting.
    """
    success_count: int = 0
    failed_count: int = 0
    successful_files: list = []  # only files that succeeded (str paths)
    skipped_count: int = 0      # fingerprint-matched files (already processed)


# Try to import optional dependencies
try:
    import mammoth
    import markdownify
except ImportError:
    mammoth = None
    markdownify = None


try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None

try:
    import trafilatura
except ImportError:
    trafilatura = None

# Configurations
EXT_PDF = {".pdf"}
EXT_WORD = set(WORD_DOCUMENT_EXTS)
EXT_EXCEL = set(EXCEL_DOCUMENT_EXTS)
EXT_POWERPOINT = set(POWERPOINT_DOCUMENT_EXTS)
EXT_MARKITDOWN = set(SUPPORTED_DOCUMENT_EXTS) | {".html", ".htm"}
EXT_MHTML = {".mhtml", ".mht"}
EXT_TEXT = {".md", ".txt", ".markdown", ".csv", ".json", ".xml"}
# 独立图片文件（支持绑定纯图片目录构建知识库）
EXT_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}

_md_converter = None


def get_markitdown_converter():
    global _md_converter
    if _md_converter is None and MarkItDown is not None:
        try:
            _md_converter = MarkItDown()
            logger.info("Preprocessor: Initialized MarkItDown converter.")
        except Exception as e:
            logger.warning(f"Preprocessor: Failed to initialize MarkItDown: {e}")
    return _md_converter


def convert_pdf_to_md(pdf_path: Path) -> str:
    """PDF → Markdown。

    原实现用 ``pymupdf4llm.to_markdown``（AGPL 许可，不满足开源要求），已换成
    :func:`pdf_backend.pdf_to_markdown`——底层是 pypdfium2（BSD-3-Clause OR
    Apache-2.0）做文字结构、pdfplumber（MIT）做表格检测，许可宽松且功能等价：
    标题分档、段落、列表、表格均保留，且与旧实现一样**不输出图片**。
    """
    logger.info(f"Preprocessor: Converting PDF: {pdf_path.name}")
    try:
        from . import pdf_backend
    except ImportError as e:  # pragma: no cover - 依赖缺失由部署保证
        raise ImportError(f"pdf_backend is not available: {e}") from e
    return pdf_backend.pdf_to_markdown(pdf_path)


def convert_word_to_md(word_path: Path) -> str:
    logger.info(f"Preprocessor: Converting Office doc: {word_path.name}")
    file_ext = word_path.suffix.lower()

    # 1. For OOXML Word files, try mammoth first.  .docm is the same OOXML
    # container as .docx for text extraction; the VBA project is not read.
    if file_ext in {".docx", ".docm"} and mammoth and markdownify:
        try:
            with open(word_path, "rb") as docx_file:
                result = mammoth.convert_to_html(docx_file)
                html = result.value
                md_content = markdownify.markdownify(html, heading_style="ATX")
                return md_content
        except Exception as e:
            logger.warning(f"Preprocessor: Mammoth failed for {word_path.name}: {e}. Trying MarkItDown...")

    # 2. Try MarkItDown
    # Excel 例外：优先走 common.excel_to_md。MarkItDown 的 xlsx 转换器
    # （pandas to_html → markdownify）和下方 pandas to_markdown 兜底都会
    # 保留单元格内换行符（多行 cell 把 markdown 表格炸成散落的纯文本行）、
    # 把空单元格渲染成字面 NaN、无标题列渲染成 Unnamed: N——引用展示
    # 界面格式全乱（真实事故：RFP 合规矩阵检索引用）。excel_to_md 的
    # _escape_cell 折叠换行为空格、转义 '|'、空值渲染为空。
    if file_ext in EXT_EXCEL:
        try:
            from common.excel_to_md import convert_excel_to_md

            # drop_empty_cols=True：删掉"整列所有行（含表头）全空"的列。
            # 宽表格式刷到最大列（真实事故：某超宽端口表的 OMM/TMSP sheet
            # 声明 16384 列、真实列 ~18）时，空 padding 会把单行渲染到 ~49K
            # 字符、表头+分隔行 ~148K，打穿 split_table_aware 的字符预算，
            # embedding 输入被截断导致行数据语义全部丢失。只删全空列，不丢数据。
            md = convert_excel_to_md(word_path, drop_empty_cols=True)
            if md.strip():
                return md
        except Exception as e:
            logger.warning(
                f"Preprocessor: excel_to_md failed for {word_path.name}: {e}. "
                "Trying MarkItDown..."
            )

    converter = get_markitdown_converter()
    if converter:
        try:
            result = converter.convert(str(word_path))
            return result.text_content
        except Exception as e:
            logger.warning(f"Preprocessor: MarkItDown failed for {word_path.name}: {e}")

    # 3. Fallback based on file type (pure Python parsers)
    fallback_err = None
    try:
        if file_ext in EXT_WORD:
            import docx
            doc = docx.Document(word_path)
            full_text = [para.text for para in doc.paragraphs]
            return "\n\n".join(full_text)
        elif file_ext in EXT_POWERPOINT:
            import pptx
            prs = pptx.Presentation(word_path)
            full_text = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text:
                        full_text.append(shape.text)
            return "\n\n".join(full_text)
        elif file_ext in EXT_EXCEL:
            import pandas as pd
            # 读取所有 sheet
            excel_file = pd.ExcelFile(word_path)
            full_text = []

            def _fold_cell(v):
                # 空单元格渲染为空（而非字面 NaN）；单元格内换行折叠为空格，
                # 避免多行 cell 破坏 markdown 表格结构
                return v.replace("\r", " ").replace("\n", " ") if isinstance(v, str) else v

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name).fillna("")
                try:
                    df = df.map(_fold_cell)  # pandas >= 2.1
                except AttributeError:
                    df = df.applymap(_fold_cell)  # 旧版 pandas
                # 添加 sheet 标题
                full_text.append(f"## {sheet_name}\n")
                # 转换为 Markdown 表格
                full_text.append(df.to_markdown(index=False))
                full_text.append("")  # 空行分隔
            return "\n".join(full_text)
        else:
            fallback_err = f"No specific fallback parser for extension {file_ext}"
    except Exception as e:
        fallback_err = str(e)
        logger.warning(f"Preprocessor: Fallback parser failed for {word_path.name}: {e}")

    # 4. For Office documents, try native office automation (Word/WPS/Excel)
    # as final fallback. Triggers only when markitdown + python-docx +
    # python-openpyxl all failed.
    # - Word COM handles WPS-authored .doc files (non-standard OLE containers
    #   markitdown/python-docx reject).
    # - Excel COM handles .xls files masquerading as .xlsx (BIFF8 magic bytes
    #   with .xlsx extension — markitdown's XlsConverter rejects them without
    #   optional [xls] deps).
    # - Windows: win32com (pywin32，生产验证过的路径，原地保留)。
    # - Linux: office_bridge（LibreOffice headless），契约与 win32com 路径一致。
    # 两个平台都没有可用自动化后端时，fall through to RuntimeError at the bottom.
    if file_ext in (".doc", ".docx", ".xls", ".xlsx"):
        if os.name == "nt":
            win32com_err = _try_win32com_conversion(word_path)
        else:
            win32com_err = _convert_via_linux_office_backends(word_path)
        if win32com_err is not None:
            if isinstance(win32com_err, str):
                return win32com_err
            raise win32com_err

    raise RuntimeError(
        f"Preprocessor: All conversion methods failed for {word_path.name}.\n"
        f"- Fallback parser: {fallback_err or 'N/A'}\n"
        f"Tip: legacy .doc/.xls 需要 Office 自动化后端——Windows 装 pywin32 且确保 "
        f"Word 或 WPS 可用；Linux 装 LibreOffice。"
    )


def _convert_via_linux_office_backends(word_path: Path):
    """Linux：office_bridge（LibreOffice headless）承担 win32com 的角色。

    契约与 _try_win32com_conversion 完全一致：
    str=成功 markdown / None=无可用后端（落到下方 RuntimeError）/
    Exception=转换失败（调用方 raise，该文件按失败计，构建继续）。

    office_bridge 只在此处及 doc_image_extractor 的对应入口懒加载——
    Windows 路径（含本文件被 importlib 单文件加载的测试）完全不触碰它。
    """
    try:
        from .office_bridge import convert_office_to_markdown
    except Exception as e:
        logger.info(
            f"Preprocessor: office_bridge unavailable ({e}), skipping for {word_path.name}"
        )
        return None
    return convert_office_to_markdown(word_path)


# 正常 win32com 转换实测 ≈10-15s（构建日志统计），超时取正常上限的 4 倍余量
_WIN32COM_TIMEOUT_SEC = 60

# 各 Office 套件自动化实例的进程映像名（Word/WPS文字/Excel/WPS表格）
_OFFICE_IMAGE_NAMES = frozenset({"winword.exe", "wps.exe", "excel.exe", "et.exe"})

# Dispatch 与 PID 快照必须原子完成：process_directory 用 ThreadPoolExecutor(max_workers=2)
# 并行处理文件，两个转换可能同时 Dispatch，不加锁会把别人拉起的进程算到自己头上
_office_spawn_lock = threading.Lock()


def _automation_office_pids() -> set[int]:
    """当前存活的「自动化启动」Office 进程 PID（命令行含 /Automation 或 -Embedding）。

    只认自动化实例：用户手动打开的 Word/Excel 不带这些参数，永远不会被匹配，
    超时强杀不会误伤用户文档。psutil 不可用时返回空集（超时退化为仅放弃等待）。
    """
    try:
        import psutil
    except ImportError:
        return set()
    pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (proc.info.get("name") or "").lower() not in _OFFICE_IMAGE_NAMES:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if "/automation" in cmdline or "embedding" in cmdline:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return pids


def _kill_office_pids(pids: list[int]) -> None:
    """强杀指定 PID 的 Office 进程（逐个尝试，失败仅告警不中断）。"""
    if not pids:
        return
    try:
        import psutil
    except ImportError:
        logger.warning("Preprocessor: psutil 不可用，无法强杀挂起的 Office 进程")
        return
    for pid in pids:
        try:
            psutil.Process(pid).kill()
            logger.info(f"Preprocessor: 已强杀挂起的 Office 进程 pid={pid}")
        except Exception as exc:
            logger.warning(f"Preprocessor: 强杀 Office 进程 pid={pid} 失败: {exc}")


def _try_win32com_conversion(word_path: Path, timeout_sec: float = _WIN32COM_TIMEOUT_SEC):
    """带超时保护的 win32com 转换入口（保持 str/None/Exception 返回契约）。

    COM 的 Documents.Open / Workbooks.Open 对损坏/特殊文件可能无限期阻塞——
    Word 在无人值守会话里弹隐式修复对话框，没人点就一直挂（真实事故：一个
    .doc 卡死整个 KB 构建 31 分钟）。这里把转换放子线程跑，超时则强杀本次
    Dispatch 拉起的 Office 进程，返回 TimeoutError（硬失败），调用方按转换
    失败处理该文件、构建继续。
    """
    try:
        import win32com.client  # type: ignore  # noqa: F401
    except ImportError:
        logger.info(f"Preprocessor: win32com not available (Linux or pywin32 missing), skipping for {word_path.name}")
        return None

    result_holder: dict = {}
    spawned_pids: list[int] = []

    def _run() -> None:
        try:
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            result_holder["value"] = _win32com_convert_blocking(word_path, spawned_pids)
        except Exception as exc:  # 防御兜底：阻塞函数内部已自捕获，正常不会走到
            result_holder["value"] = exc

    worker = threading.Thread(target=_run, name="win32com-convert", daemon=True)
    worker.start()
    worker.join(timeout_sec)
    if not worker.is_alive():
        return result_holder.get("value")

    err = TimeoutError(f"win32com 转换超时（>{timeout_sec:.0f}s），按失败处理: {word_path.name}")
    logger.warning(f"Preprocessor: {err}")
    alive = _automation_office_pids()
    victims = [pid for pid in spawned_pids if pid in alive]
    if victims:
        _kill_office_pids(victims)
    else:
        logger.warning("Preprocessor: 未能定位本次转换拉起的 Office 进程，仅放弃等待（守护线程残留）")
    worker.join(10)  # 进程被杀后 COM 调用会以 RPC 失败返回，稍等线程收尾
    return err


def _win32com_convert_blocking(word_path: Path, spawned_pids: list[int]):
    """Convert legacy Office doc (.doc / .xls) via Word/WPS/Excel COM（阻塞实现）。

    Word COM handles WPS-authored .doc files (non-standard OLE containers
    markitdown/python-docx reject). Excel COM handles .xls files masquerading
    as .xlsx (BIFF8 magic bytes with .xlsx extension — markitdown's
    XlsConverter rejects them without optional [xls] deps installed).

    Returns the converted text/markdown string on success. None on soft failure
    (pywin32 not installed, no Office/WPS, unsupported extension). An Exception
    on hard failure (COM worked but conversion itself failed).

    spawned_pids: 本次 Dispatch 前后自动化 Office 进程的 PID 差集会 append 进去，
    供超时后精确强杀（只杀自己拉起的，不碰并行转换或用户进程）。

    Win32 COM is sensitive to path length and non-ASCII chars on Windows.
    We copy the source file to a short ASCII path before invoking COM,
    and use a short ASCII path for the converted output.
    """
    try:
        import win32com.client  # type: ignore
    except ImportError:
        logger.info(f"Preprocessor: win32com not available (Linux or pywin32 missing), skipping for {word_path.name}")
        return None

    import shutil
    import string

    file_ext = word_path.suffix.lower()
    if file_ext in (".doc", ".docx"):
        # WPS 优先：老 .doc 多为 WPS 生成，WPS 对自家非标 OLE 容器静默打开；
        # Word 对需修复的文件会弹「显示修复」通知框（OpenAndRepair 压不住），
        # 无人值守会话里没人关 → COM 调用永不返回，只能垫底 + 超时兜底
        com_prog_ids = ["Kwps.Application", "WPS.Application", "Word.Application"]
        out_ext = ".docx"
    elif file_ext in (".xls", ".xlsx"):
        com_prog_ids = ["Excel.Application"]
        out_ext = ".xlsx"
    else:
        logger.info(f"Preprocessor: win32com not applicable to {file_ext}, skipping")
        return None

    office_app = None
    src_copy = None
    out_file = None
    work_dir = None
    try:
        # Stage source file to short ASCII path to avoid Win32 path-length
        # and codepage issues (CJK paths / paths > 260 chars fail COM Open).
        safe_stem = "".join(c for c in word_path.stem if c in string.ascii_letters + string.digits + "_")[:40] or "doc_input"
        work_dir = tempfile.mkdtemp(prefix="cosight_office_")
        src_copy = os.path.join(work_dir, f"input{file_ext}")
        out_file = os.path.join(work_dir, f"output{out_ext}")
        shutil.copy2(word_path, src_copy)

        # Dispatch 前后各做一次自动化 Office PID 快照，差集即本次拉起的进程；
        # 持锁保证与并行转换（max_workers=2）的快照互不穿插，归因精确。
        with _office_spawn_lock:
            before_pids = _automation_office_pids()
            for prog_id in com_prog_ids:
                try:
                    office_app = win32com.client.Dispatch(prog_id)
                    if office_app:
                        break
                except Exception:
                    office_app = None
                    continue
            spawned_pids.extend(_automation_office_pids() - before_pids)
        if not office_app:
            logger.info(f"Preprocessor: no Office COM available for {word_path.name} (tried: {com_prog_ids})")
            return None

        office_app.Visible = False
        office_app.DisplayAlerts = 0

        # Open → SaveAs (canonicalize format) → Close
        if file_ext in (".doc", ".docx"):
            try:
                doc_obj = office_app.Documents.Open(
                    os.path.abspath(src_copy),
                    ConfirmConversions=False,  # 不弹文件转换确认
                    ReadOnly=True,             # 只读打开，避免锁定/编辑提示
                    OpenAndRepair=True,        # 结构异常时静默修复（无人值守必须：否则弹恢复确认框等人点，COM 调用永不返回）
                )
            except Exception:
                # WPS 等不完整 COM 实现可能不认识扩展参数，退回最小参数形式；
                # 若退回后触发交互弹窗卡死，由外层 _try_win32com_conversion 超时强杀兜底
                doc_obj = office_app.Documents.Open(os.path.abspath(src_copy))
            try:
                doc_obj.SaveAs2(out_file, FileFormat=12)  # wdFormatXMLDocument (.docx)
            finally:
                doc_obj.Close()
        else:  # .xls / .xlsx
            wb = office_app.Workbooks.Open(os.path.abspath(src_copy))
            try:
                wb.SaveAs(out_file, FileFormat=51)  # xlOpenXMLWorkbook (modern .xlsx)
            finally:
                wb.Close()
        office_app.Quit()
        office_app = None

        # Read the canonicalized output with the matching parser
        if file_ext in (".doc", ".docx"):
            with open(out_file, "rb") as f:
                result = mammoth.convert_to_html(f)
            return markdownify.markdownify(result.value, heading_style="ATX")
        else:  # .xls / .xlsx
            import openpyxl
            wb = openpyxl.load_workbook(out_file, data_only=True)
            rows = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    row_text = "\t".join(str(c) for c in row if c is not None)
                    if row_text.strip():
                        rows.append(row_text)
            return "\n".join(rows)
    except Exception as e:
        logger.warning(f"Preprocessor: win32com fallback failed for {word_path.name}: {e}")
        return e
    finally:
        if office_app:
            try:
                office_app.Quit()
            except Exception:
                pass
        for p in (src_copy, out_file):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass
        if work_dir:
            try:
                os.rmdir(work_dir)
            except Exception:
                pass


def convert_mhtml_to_md(mhtml_path: Path) -> str:
    logger.info(f"Preprocessor: Converting MHTML: {mhtml_path.name}")
    if not trafilatura:
        raise ImportError("trafilatura is not installed")

    try:
        with open(mhtml_path, "rb") as f:
            msg = message_from_bytes(f.read())

        html_content = ""
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    html_content = payload.decode(charset)
                except Exception:
                    try:
                        html_content = payload.decode("gbk")
                    except Exception:
                        html_content = payload.decode("utf-8", errors="ignore")
                break

        if not html_content:
            payload = msg.get_payload(decode=True)
            if payload:
                html_content = payload.decode("utf-8", errors="ignore")

        if not html_content:
            logger.warning(f"Preprocessor: No HTML content found in MHTML: {mhtml_path.name}")
            return ""

        result = trafilatura.extract(html_content, output_format='markdown', include_formatting=True, include_links=True)
        return result if result else ""
    except Exception as e:
        logger.error(f"Preprocessor: MHTML conversion failed for {mhtml_path.name}: {e}")
        return ""


def is_office_temp(path) -> bool:
    """Office/系统临时文件（Word/WPS 的 owner 锁文件 ~$xxx、.tmp、.ds_store 等）。

    这类文件不是有效文档（如 ~$ owner 文件内容并非 zip），一旦进入预处理会触发
    BadZipFile 之类的转换失败。所有派发预处理任务的入口都应先用它过滤。
    """
    p = Path(path)
    name = p.name.lower()
    if name.startswith("~$") or (name.startswith("~") and (".tmp" in name or ".bak" in name)) or name.endswith(".tmp") or name == ".ds_store":
        return True
    for part in p.parts:
        if ".tmp-" in part.lower():
            return True
    return False


# ======== [CoSight-START] feature: exclude-cosightpro-from-preprocessing ========
# 用户有时会把旧版状态目录（.cosightpro）放在绑定给智能体的工作目录里
# （典型场景：把工作区根目录直接作为 agent material）。该目录内部有大量
# .json/.md 状态文件（sessions 指纹、聊天历史、rag 缓存等），递归 rglob 进去
# 会让预处理永远跑不完——一边扫一边往 status 写"待处理"，UI 上看起来卡死在
# "正在预处理"。这些目录是运行时状态，绝不是用户文档源；预处理必须直接跳过整棵子树。
EXCLUDED_DIR_NAMES = (".cosightpro",)


def is_under_excluded_dir(path) -> bool:
    """路径是否落在 EXCLUDED_DIR_NAMES 中任一目录之下（含任意层级）。

    与 ``is_office_temp`` 同级——所有"扫源目录"的入口都应在派发任务前先调一次，
    把 .cosightpro 子树整体剪掉。
    """
    p = Path(path)
    for part in p.parts:
        if part in EXCLUDED_DIR_NAMES:
            return True
    return False
# ======== [CoSight-END] feature: exclude-cosightpro-from-preprocessing ========


def is_supported_file(file_path: Path) -> bool:
    if is_office_temp(file_path):
        return False
    return file_path.suffix.lower() in (EXT_PDF | EXT_MARKITDOWN | EXT_MHTML | EXT_TEXT | EXT_IMAGES)


# 批量构建的入库白名单：is_supported_file 去掉独立图片。
# 知识库不索引散装图片文件（文档内嵌图片走 doc_image_extractor，是另一条链路），
# 否则软件光盘解压出的成千上万 UI 截图/图标会被 vision 描述入库。
BUILD_INDEX_EXTS = frozenset(EXT_PDF | EXT_MARKITDOWN | EXT_MHTML | EXT_TEXT)


def is_build_indexable(file_path: Path) -> bool:
    """批量构建扫描源目录时判断该文件是否应入库。"""
    if is_office_temp(file_path):
        return False
    return Path(file_path).suffix.lower() in BUILD_INDEX_EXTS


# ---------------------------------------------------------------------------
# 企业加密/损坏文件护栏
#
# 背景（真实事故，某企业知识库子库）：企业透明加密的 docx 在磁盘上是高熵密文
# （既不是 zip 也不是 OLE2），但转换链路 Mammoth/MarkItDown 全失败后，
# office_bridge（WPS/LibreOffice COM）兜底会把密文当文本打开再另存，
# 产出"转换成功"的乱码 md 并静默入库——两个子库 506 个 docx 里 256 个
# 加密，除 3 个乱码形态恰好打爆 punkt 的报 RecursionError 外，其余全部
# 无声地以垃圾向量入库（含"Successfully processed"的也不例外）。
#
# 方案：源文件魔数前置拦截（确定性）。两个子库 506 个 docx 全量普查
# 验证：250 个正常文件（PK 魔数）零误伤、256 个加密文件（非 PK/OLE）
# 全部拦截。转换产物的内容级乱码检测曾评估过（常用字分布法），因存在
# 短文档/表格类语料的阈值边界问题，经评审决定不引入，本护栏只做魔数层。
# ---------------------------------------------------------------------------

# 老 Office（.doc/.xls/.ppt）= OLE2 复合文档魔数
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# 魔数探测读取窗口：PDF 规范要求 %PDF- 在文件头，少量工具会在前面加垃圾字节，
# 给 1KB 容差避免误杀（与 Adobe Acrobat 的容错窗口一致）
_MAGIC_PROBE_BYTES = 1024


def _office_file_magic_error(file_path: Path, file_ext: str) -> Optional[str]:
    """检查 Office/PDF 源文件魔数。返回错误描述字符串；None 表示正常。

    OOXML(.docx/.xlsx/.pptx 及宏变体) = zip(PK)，老 Office = OLE2 复合文档，
    PDF = %PDF-。Office 家族两种魔数都放行——.doc 改名为 .docx 之类的
    后缀错位但内容真实的文件仍能走 WPS/Word 转换；企业透明加密文件两者
    都不是，在这里被确定性拦截，避免 COM 兜底把密文转成乱码 md。
    """
    is_office = file_ext in OFFICE_DOCUMENT_EXTS
    is_pdf = file_ext in EXT_PDF
    if not (is_office or is_pdf):
        return None
    try:
        with open(file_path, "rb") as f:
            head = f.read(_MAGIC_PROBE_BYTES)
    except OSError as e:
        return f"无法读取源文件: {e}"
    if head.startswith(b"PK") or head.startswith(_OLE2_MAGIC):
        return None
    if is_pdf and b"%PDF-" in head[:_MAGIC_PROBE_BYTES]:
        return None
    kind = "Office" if is_office else "PDF"
    expect = "zip(PK)/OLE2" if is_office else "%PDF-"
    return (
        f"{kind} 文件魔数不匹配（既不是 {expect}），"
        f"疑似企业加密文件或已损坏，拒绝转换"
    )


def process_single_file(
    file_path: Path,
    output_dir: Path,
    input_root: Path,
    with_images: bool = False,
    on_ppt_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
    session_key: str = None, agent_id: str = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    skip_vision: bool = False,
    on_page_done: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """
    Process a single file and save its Markdown version to output_dir.
    Returns True if successful.

    session_key / agent_id：透传给 doc_image_extractor 解析会话级多模态模型配置
    （PDF/DOC/DOCX 图片识别用）；不传时按环境变量 / 默认配置解析。

    progress_callback: 可选 (current, total, stage) 回调，透传到 doc_image_extractor
    的视觉 OCR 流程；调用方负责包装成 global_progress 的 start/update_file_subprogress。
    PPT 切页走独立回调（_run_ppt_slide_extraction），不在本参数控制。

    skip_vision: True 时跳过 PDF/DOC/DOCX 的图片多模态识别路径（vision pipeline），
    直接走 legacy 纯文本转换（pdf_backend / mammoth / markitdown）。
    主要给批量构建脚本使用——避免大文件图多时把整晚耗在
    远端 vision_client 上。PPT slide 提取不依赖 vision 模型（仅本地 LibreOffice +
    python-pptx 渲染），不受此开关影响。默认 False 保持原有行为。
    """
    if not is_supported_file(file_path):
        logger.info(f"Preprocessor: Skipping {file_path.name} (unsupported extension)")
        return False

    t_file = time.perf_counter()
    file_ext = file_path.suffix.lower()
    relative_path = file_path.relative_to(input_root)
    # 预处理后的文件名规范：所有点替换为下划线 (filename_ext.md)
    md_name = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_") + ".md"
    md_path = output_dir / relative_path.with_name(md_name)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_mtime = file_path.stat().st_mtime
        if (
            md_path.is_file()
            and md_path.stat().st_mtime >= source_mtime
            and _required_artifacts_exist(
                file_path,
                output_dir,
                relative_path,
                skip_vision=skip_vision,
                session_key=session_key,
                agent_id=agent_id,
            )
        ):
            logger.info(
                f"Preprocessor: Skipping up-to-date file: {file_path.name}"
            )
            return True
    except OSError:
        # A missing or transiently inaccessible output/source file should
        # continue through the normal conversion path and report its failure.
        pass

    # 对非视觉类文件做简单的 mtime 增量跳过：产物已存在且不比源文件旧时直接返回成功。
    # PDF/DOC/DOCX/独立图片不在这里跳过，它们依赖 _is_fingerprint_match 里的
    # images_index.json pending 检查实现模型切换后的自愈重识别。
    if file_ext not in (".pdf", ".doc", ".docx") and file_ext not in EXT_IMAGES:
        if md_path.is_file():
            try:
                if md_path.stat().st_mtime >= file_path.stat().st_mtime:
                    logger.info(f"Preprocessor: Skipping up-to-date file {file_path.name}")
                    return True
            except OSError:
                pass

    # 企业加密/损坏文件前置拦截：魔数不匹配直接判预处理失败。
    # 必须放在 WPS/COM 兜底之前——兜底会把密文当文本打开并另存成
    # "转换成功"的乱码 md（真实事故：某子库半数 docx 加密静默乱码入库）。
    magic_err = _office_file_magic_error(file_path, file_ext)
    if magic_err:
        logger.error(f"Preprocessor: {magic_err}: {file_path.name}")
        return False

    try:
        markdown_content = None
        # ======== [CoSight-START] feature: pdf-word-image-vision ========
        # True 时跳过下方"剥离图片引用"的正则 —— doc_image_extractor 已经在
        # md 里原位插入了「图片描述 + 相对地址 + ocr 标记」，再剥就全删了。
        vision_handled = False
        # ======== [CoSight-END] feature: pdf-word-image-vision ========

        # ======== [CoSight-START] feature: pdf-word-image-vision ========
        # PDF/DOC/DOCX 先走图片提取 + 多模态识别编排；handled=False（转换失败、
        # COM 不可用等）时回退到下方 legacy 纯文本转换路径。
        # skip_vision=True 时跳过整个 vision block，直接走 legacy 文本路径。
        if file_ext in VISION_DOCUMENT_EXTS:
            if skip_vision:
                logger.info(
                    f"Preprocessor: skip_vision=True → 跳过图片识别，"
                    f"{file_path.name} 走 legacy 文本转换路径"
                )
                vision_res = {"handled": False, "reason": "skip_vision"}
            else:
                try:
                    from .doc_image_extractor import process_document_with_images
                    # doc_image_extractor.progress_callback 现在是 (current, total, stage) 三参
                    # （v8 fix 后）；直接传 progress_callback 即可，无需 2 参 wrapper。
                    vision_res = process_document_with_images(
                        file_path, output_dir, relative_path,
                        session_key=session_key, agent_id=agent_id,
                        progress_callback=progress_callback,
                        on_page_done=on_page_done,
                    )
                except Exception as ve:
                    logger.warning(
                        f"Preprocessor: doc_image_extractor crashed for {file_path.name}: {ve}"
                    )
                    vision_res = {"handled": False, "reason": str(ve)}
            if vision_res.get("handled"):
                # P3：按页增量路径——主 .md 已由 doc_image_extractor 逐页增量落盘，
                # 跳过整本重写，直接对已生成的 .md 拆章。
                if vision_res.get("md_written"):
                    vision_handled = True
                    try:
                        from .chapter_splitter import split_md_by_chapters
                        split_md_by_chapters(md_path)
                    except Exception as ce:
                        logger.warning(
                            f"Preprocessor: chapter split failed for {file_path.name}: {ce}"
                        )
                    logger.info(
                        f"Preprocessor: Successfully processed {file_path.name} (per-page) "
                        f"in {time.perf_counter() - t_file:.2f}s"
                    )
                    return True
                markdown_content = vision_res.get("markdown_content")
                vision_handled = True
                logger.info(
                    f"Preprocessor: vision pipeline handled {file_path.name} "
                    f"doc_type={vision_res.get('doc_type')} "
                    f"recognized={vision_res.get('images_recognized')} "
                    f"pending={vision_res.get('images_pending')}"
                )
        # ======== [CoSight-END] feature: pdf-word-image-vision ========

        if markdown_content is None and file_ext in EXT_PDF:
            markdown_content = convert_pdf_to_md(file_path)
        elif markdown_content is None and file_ext in EXT_MARKITDOWN:
            markdown_content = convert_word_to_md(file_path)
        elif file_ext in EXT_MHTML:
            markdown_content = convert_mhtml_to_md(file_path)
        elif file_ext in EXT_TEXT:
            logger.info(f"Preprocessor: Reading text file: {file_path.name}")
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                markdown_content = f.read()
        # ======== [CoSight-START] feature: standalone-image-preprocessing ========
        elif file_ext in EXT_IMAGES:
            from .doc_image_extractor import process_single_image
            image_res = process_single_image(
                file_path,
                output_dir,
                input_root,
                session_key=session_key,
                agent_id=agent_id,
                progress_callback=progress_callback,
            )
            if image_res.get("handled"):
                logger.info(
                    f"Preprocessor: Successfully processed image {file_path.name} "
                    f"doc_type={image_res.get('doc_type')} "
                    f"recognized={image_res.get('images_recognized')} "
                    f"pending={image_res.get('images_pending')} "
                    f"in {time.perf_counter() - t_file:.2f}s"
                )
                # 图片产物 md 已落盘，直接走 chapter_splitter + 返回
                try:
                    from .chapter_splitter import split_md_by_chapters
                    split_md_by_chapters(md_path)
                except Exception as ce:
                    logger.warning(
                        f"Preprocessor: chapter split failed for {file_path.name}: {ce}"
                    )
                return True
            logger.warning(
                f"Preprocessor: image processing failed for {file_path.name}: "
                f"{image_res.get('reason', 'unknown')}"
            )
            return False
        # ======== [CoSight-END] feature: standalone-image-preprocessing ========

        if markdown_content is not None:
            # 统一换行符
            markdown_content = markdown_content.replace('\r', '')

            if not with_images and not vision_handled:
                markdown_content = re.sub(r'!\[.*?\]\(.*?\)', '', markdown_content)

            # 标题降一级 + 全局文件名根标题
            markdown_content = re.sub(r'^(#+)', r'#\1', markdown_content, flags=re.MULTILINE)
            file_title = file_path.stem
            markdown_content = f"# {file_title}\n\n{markdown_content}"

            with open(md_path, "w", encoding="utf-8") as out_f:
                out_f.write(markdown_content)
            # ======== [CoSight-START] feature: chapter-split ========
            # 在写完完整 .md 后立即按 V3 算法拆分成章节子文件，供章节级读取使用
            try:
                from .chapter_splitter import split_md_by_chapters
                split_md_by_chapters(md_path)
            except Exception as ce:
                logger.warning(
                    f"Preprocessor: chapter split failed for {file_path.name}: {ce}"
                )
            # ======== [CoSight-END] feature: chapter-split ========
            # P3-5 PowerPoint：主 .md（markitdown 文本）先落盘 + 立即入库（on_page_done），
            # 让文本在耗时的 slide 渲染期间即可查询；slide 产物随后在后台生成。
            if file_ext in EXT_POWERPOINT:
                if on_page_done:
                    try:
                        on_page_done(1, 1)
                    except Exception as _e:
                        logger.warning(
                            f"Preprocessor: pptx early ingest failed for {file_path.name}: {_e}"
                        )
                try:
                    _run_ppt_slide_extraction(
                        file_path,
                        output_dir,
                        relative_path,
                        on_ppt_fallback=on_ppt_fallback,
                    )
                except Exception as pe:
                    logger.warning(
                        f"Preprocessor: ppt slide extraction failed for {file_path.name}: {pe}"
                    )
            logger.info(f"Preprocessor: Successfully processed {file_path.name} in {time.perf_counter() - t_file:.2f}s")
            return True
        else:
            logger.warning(f"Preprocessor: Unsupported or failed to process file: {file_path.name} ({time.perf_counter() - t_file:.2f}s)")
        return False

    except Exception as e:
        logger.error(f"Preprocessor: Failed to process {file_path.name}: {e} ({time.perf_counter() - t_file:.2f}s)")
        return False


# ======== [CoSight-START] feature: ppt-slides ========
def _run_ppt_slide_extraction(
    file_path: Path,
    output_dir: Path,
    relative_path: Path,
    *,
    on_ppt_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> None:
    """Generate per-slide artifacts next to the preprocessed PPT markdown.

    Output layout (created relative to the same output_dir parent as the
    preprocessed markdown):
        <output_dir>/<rel_dir>/<stem>_<ext>_slides/
            Slide_01_<title>.png
            Slide_01_<title>.md
            ...
            slides_index.json
    The <stem>_<ext>_slides/ directory is excluded from the overview tree
    (see overview_builder._EXCLUDED_DIR_NAMES) but its slides are
    re-projected as per-page children via slides_index.json.

    把 convert_pptx_with_slides 已有的 progress 回调接到 global_progress，
    显示 PPT 切页的二级进度（"PPT 切页中 N/M"）。
    """
    from .progress_ui import global_progress
    from .ppt_slide_extractor import convert_pptx_with_slides

    filename = file_path.name

    def _ppt_cb(current: int, total: int):
        try:
            global_progress.start_file_subprogress(filename, total, "PPT 切页中")
            global_progress.update_file_subprogress(filename, current)
        except Exception:
            pass

    # slides_dir 命名与主 md（<stem>_<ext>.md）保持一致：点号统一替换为下划线。
    # 避免原始文件名含 "."（如 "xxx-V1.0.pptx"）时 slides_dir 与 doc.md 文件名错位，
    # 导致下游按文件名关联 parent doc 时错位。
    doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
    slides_dir = (output_dir / relative_path.with_name(doc_base)).with_name(
        f"{doc_base}_slides"
    )

    def _notify(info: dict[str, Any]) -> None:
        if on_ppt_fallback is None:
            return
        payload = dict(info)
        payload.update({
            "filename": file_path.name,
            "relative_path": relative_path.as_posix(),
        })
        try:
            stat = file_path.stat()
            payload["size"] = stat.st_size
            payload["mtime_ns"] = str(stat.st_mtime_ns)
        except OSError:
            payload["size"] = 0
            payload["mtime_ns"] = "0"
        on_ppt_fallback(payload)

    result = convert_pptx_with_slides(
        file_path,
        slides_dir,
        on_libreoffice_fallback=_notify if on_ppt_fallback is not None else None,
        progress=_ppt_cb
    )
    if not result.get("ok"):
        logger.info(
            f"Preprocessor: ppt slide extraction skipped for {file_path.name}: "
            f"{result.get('reason', 'unknown reason')}"
        )
        # 清掉可能的残留（即使失败也不应遗留子进度）
        try:
            global_progress.finish_file_subprogress(filename)
        except Exception:
            pass
        return
    totals = result.get("totals") or {}
    logger.info(
        f"Preprocessor: ppt slide extraction ok for {file_path.name}: "
        f"pages={totals.get('pages', 0)} ok={totals.get('ok', 0)} "
        f"failed={totals.get('failed', 0)}"
    )
    # 子进度在 _process_file 的 finally 统一清理
# ======== [CoSight-END] feature: ppt-slides ========


def _calculate_file_hash(path: Path) -> str:
    """计算文件的 MD5 哈希值。"""
    try:
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def _required_artifacts_exist(
    file_path: Path,
    output_dir: Path,
    rel_path: Path,
    *,
    skip_vision: bool,
    session_key: str = None,
    agent_id: str = None,
) -> bool:
    """Check the main markdown and any format-specific sidecars."""
    md_name = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_") + ".md"
    md_path = output_dir / rel_path.with_name(md_name)
    if not md_path.is_file():
        return False

    extension = file_path.suffix.casefold()
    if extension in EXT_POWERPOINT:
        doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
        slides_dir = (output_dir / rel_path.with_name(doc_base)).with_name(
            f"{doc_base}_slides"
        )
        if not (slides_dir / "slides_index.json").is_file():
            return False

    if extension in VISION_DOCUMENT_EXTS and not skip_vision:
        doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
        rel_dir = output_dir / rel_path.parent
        index_path = next(
            (
                rel_dir / f"{doc_base}{suffix}" / "images_index.json"
                for suffix in ("_images", "_pages")
                if (rel_dir / f"{doc_base}{suffix}" / "images_index.json").is_file()
            ),
            None,
        )
        if index_path is None:
            return False
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(index_data, dict):
            return False
        if any(
            isinstance(entry, dict) and entry.get("ocr_status") == "pending"
            for entry in (index_data.get("images") or [])
        ):
            try:
                from .model_capability import current_model_supports_images
                if current_model_supports_images(
                    session_key=session_key,
                    agent_id=agent_id,
                ):
                    return False
            except Exception as exc:
                logger.info(
                    f"Preprocessor: model capability check failed for "
                    f"{file_path.name}: {exc}"
                )
                return False
        return True
    return True


def _is_fingerprint_match(file_path: Path, input_root: Path, recorded_files: dict, output_dir: Path, session_key: str = None, agent_id: str = None, skip_vision: bool = False) -> bool:
    """判断源文件指纹是否与上次成功处理的记录匹配。

    匹配条件：
      - recorded_files 中存在该文件的 POSIX 相对路径条目，且 status == "success"
      - 当前文件的 size 与记录的 size 相等
      - 当前文件的 mtime 与记录的 mtime 差距 < 0.1s，或 md5 hash 相等
      - 预处理产物 .md 已落盘到 output_dir 对应位置
      - 若源文件是 PowerPoint,还需 `<stem>_<ext>_slides/slides_index.json` 落盘

    用于全量构建前的快速跳过，避免对未变更文件重复转换与入库。

    session_key / agent_id 透传给 current_model_supports_images，
    确保多 session 进程复用 / 测试无 env 注入时，pending 自愈判断
    用的是"当前文件所属 session"的模型，而非进程级默认。
    """
    if not recorded_files:
        return False
    try:
        abs_file = file_path.expanduser().resolve()
        abs_root = input_root.expanduser().resolve()
        rel_path = abs_file.relative_to(abs_root)
    except (ValueError, OSError):
        return False
    std_rel = rel_path.as_posix()
    info = recorded_files.get(std_rel)
    if not info or info.get("status") != "success":
        return False
    try:
        stat = file_path.stat()
    except OSError:
        return False
    # 匹配逻辑：(mtime一致 且 size一致) OR (hash一致 且 size一致)
    mtime_match = abs(info.get("mtime", 0) - stat.st_mtime) < 0.1
    size_match = info.get("size") == stat.st_size
    current_hash = _calculate_file_hash(file_path) if not mtime_match else ""
    hash_match = bool(current_hash) and info.get("hash") == current_hash
    if not ((mtime_match and size_match) or (hash_match and size_match)):
        return False
    # 确认主 markdown 和格式专属副产物都已落盘；否则即使指纹匹配也要重做。
    if not _required_artifacts_exist(
        file_path,
        output_dir,
        rel_path,
        skip_vision=skip_vision,
        session_key=session_key,
        agent_id=agent_id,
    ):
        return False

    # PPT/PPTX 还要 per-slide 目录的 slides_index.json 也已落盘才算“产物完整”。
    # 命名与主 md 一致：doc_base = "<stem>_<ext>".replace(".", "_")，
    # slides_dir = <wrapper>/<doc_base>_slides。保持与下方 _rewrite_assets_urls 等下游模块的约定一致。
    if file_path.suffix.lower() in (".ppt", ".pptx"):
        doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
        slides_dir = (output_dir / rel_path.with_name(doc_base)).with_name(
            f"{doc_base}_slides"
        )
        if not (slides_dir / "slides_index.json").is_file():
            return False
    # ======== [CoSight-START] feature: pdf-word-image-vision ========
    # PDF/DOC/DOCX 图片产物完整性 + pending 自愈：
    # 1. <stem>_<ext>_images/ 或 <stem>_<ext>_pages/ 下的 images_index.json 必须落盘
    #    （老版本处理的文档没有该文件 → 重处理一次，补齐图片体系；
    #    命名与主 md <stem>_<ext>.md 对齐）
    # 2. images_index.json 中存在 ocr_status=pending 的图、且**当前文件所属 session
    #    的**模型已是多模态 → 指纹判不匹配，触发重新预处理补齐 OCR
    #
    # 注意：skip_vision=True 时不会跑 vision pipeline，
    # 不会生成 images_index.json。所以跳过这个检查，让 .md 产物存在即可判匹配。
    if file_path.suffix.lower() in (".pdf", ".doc", ".docx") and not skip_vision:
        rel_dir = output_dir / rel_path.parent
        doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
        images_index = rel_dir / f"{doc_base}_images" / "images_index.json"
        pages_index = rel_dir / f"{doc_base}_pages" / "images_index.json"
        index_path = images_index if images_index.is_file() else (
            pages_index if pages_index.is_file() else None
        )
        if index_path is None:
            return False
        try:
            import json as _json
            index_data = _json.loads(index_path.read_text(encoding="utf-8"))
            has_pending = any(
                isinstance(e, dict) and e.get("ocr_status") == "pending"
                for e in (index_data.get("images") or [])
            )
            if has_pending:
                from .model_capability import current_model_supports_images
                if current_model_supports_images(
                    session_key=session_key, agent_id=agent_id
                ):
                    logger.info(
                        f"Preprocessor: fingerprint mismatch (pending OCR + multimodal "
                        f"model), reprocess {file_path.name}"
                    )
                    return False
        except Exception as e:
            logger.info(
                f"Preprocessor: images_index check failed for {file_path.name}: {e}"
            )
            return False
    # ======== [CoSight-END] feature: pdf-word-image-vision ========
    # ======== [CoSight-START] feature: standalone-image-preprocessing ========
    # 独立图片文件产物完整性 + pending 自愈：
    # 1. <stem>_<ext>_images/images_index.json 必须落盘
    # 2. images_index.json 中存在 ocr_status=pending 的图、且当前模型已是多模态
    #    → 触发重新预处理补齐 OCR
    if file_path.suffix.lower() in EXT_IMAGES:
        rel_dir = output_dir / rel_path.parent
        doc_base = f"{file_path.stem}_{file_path.suffix.lstrip('.')}".replace(".", "_")
        index_path = rel_dir / f"{doc_base}_images" / "images_index.json"
        if not index_path.is_file():
            return False
        try:
            import json as _json
            index_data = _json.loads(index_path.read_text(encoding="utf-8"))
            has_pending = any(
                isinstance(e, dict) and e.get("ocr_status") == "pending"
                for e in (index_data.get("images") or [])
            )
            if has_pending:
                from .model_capability import current_model_supports_images
                if current_model_supports_images(
                    session_key=session_key, agent_id=agent_id
                ):
                    logger.info(
                        f"Preprocessor: fingerprint mismatch (pending image OCR + "
                        f"multimodal model), reprocess {file_path.name}"
                    )
                    return False
        except Exception as e:
            logger.info(
                f"Preprocessor: images_index check failed for {file_path.name}: {e}"
            )
            return False
    # ======== [CoSight-END] feature: standalone-image-preprocessing ========
    return True


def process_directory(
    input_dir: Path,
    output_dir: Path,
    with_images: bool = False,
    recorded_files: dict = None,
    on_ppt_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
    session_key: str = None, agent_id: str = None,
    skip_vision: bool = False,
):
    """
    Process all supported files in input_dir and save to output_dir.

    当传入 recorded_files（来自 .llamaindex_status 的 files 字典）时，
    会在派发任务前按 mtime/size 指纹 + 预处理产物存在性快速跳过未变更文件，
    减少全量构建时的重复转换与进度条虚高。

    skip_vision: 透传给 process_single_file，跳过 PDF/DOC/DOCX 的图片多模态识别。
    """
    from .progress_ui import global_progress

    t_total = time.perf_counter()
    logger.info(f"Preprocessor: Scanning directory: {input_dir}")
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"Preprocessor: Input directory does not exist or is not a directory: {input_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # ======== [CoSight-START] feature: exclude-cosightpro-from-preprocessing ========
    # 旧版状态目录（.cosightpro）下的所有文件直接剪掉——它们是运行时状态
    # （fingerprint、会话历史、rag 缓存等），不是用户文档源；如果用户把工作目录
    # 绑到状态根的上级，递归进去会导致预处理永远跑不完。用 os.walk 剪枝，
    # 避免先枚举整棵运行时子树。
    all_files = []
    if not is_under_excluded_dir(input_dir):
        for dirpath, dirnames, filenames in os.walk(input_dir):
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in EXCLUDED_DIR_NAMES
            ]
            all_files.extend(Path(dirpath) / filename for filename in filenames)
    # ======== [CoSight-END] feature: exclude-cosightpro-from-preprocessing ========

    supported_exts = EXT_PDF | EXT_MARKITDOWN | EXT_MHTML | EXT_TEXT
    supported_files = [f for f in all_files if f.suffix.lower() in supported_exts and not is_office_temp(f)]

    # 指纹预过滤：指纹匹配且 .md 产物已存在的文件跳过处理
    skipped_count = 0
    if recorded_files:
        to_process = []
        for f in supported_files:
            if _is_fingerprint_match(
                f, input_dir, recorded_files, output_dir,
                session_key=session_key, agent_id=agent_id,
                skip_vision=skip_vision,
            ):
                skipped_count += 1
            else:
                to_process.append(f)
        supported_files = to_process

    logger.info(
        f"Preprocessor: Found {len(supported_files)} supported files out of {len(all_files)} total files"
        f" (fingerprint-skipped {skipped_count})."
    )

    # 仅对真正需要处理的文件计入 waiting 与提交线程池
    global_progress.add_waiting(len(supported_files))

    if not supported_files:
        logger.info(f"Preprocessor: Nothing to process (all files fingerprint-matched).")
        return ProcessResult()

    success_count = 0
    successful_files = []
    lock = __import__('threading').Lock()

    def _process_file(file_path):
        nonlocal success_count
        filename = file_path.name
        global_progress.start_processing(filename)

        # 二级进度回调：(current, total, stage) → global_progress
        # stage 变化时（"渲染中" → "OCR 识别中"）重置 current 到 0，
        # 避免 OCR 阶段用户看到 "299/299" 之类的残留。
        # OCR/PPT 阶段内部 doc_image_extractor/ppt_slide_extractor 都通过这个回调上报。
        last_stage_holder = [None]  # 用 list 包住以支持内部修改
        def _vision_cb(current: float, total: int, stage: str):
            try:
                if last_stage_holder[0] != stage:
                    # stage 切换 → 重置 current=0
                    global_progress.start_file_subprogress(filename, total, stage)
                    global_progress.update_file_subprogress(filename, 0)
                    last_stage_holder[0] = stage
                else:
                    global_progress.start_file_subprogress(filename, total, stage)
                global_progress.update_file_subprogress(filename, current)
            except Exception:
                pass

        try:
            if process_single_file(
                file_path,
                output_dir,
                input_dir,
                with_images,
                on_ppt_fallback=on_ppt_fallback,
                session_key=session_key, agent_id=agent_id,
                progress_callback=_vision_cb,
                skip_vision=skip_vision,
            ):
                with lock:
                    success_count += 1
                    successful_files.append(str(file_path))
                global_progress.finish_processing(filename)
            else:
                global_progress.fail_processing(filename, str(file_path), "文件格式解析失败或已被跳过")
        except Exception as e:
            global_progress.fail_processing(filename, str(file_path), f"异常: {str(e)}")
        finally:
            # 无论成功/失败/异常，最终清理子进度，避免残留污染下一批次
            try:
                global_progress.finish_file_subprogress(filename)
            except Exception:
                pass

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="preprocessor") as executor:
        executor.map(_process_file, supported_files)

    logger.info(f"Preprocessor: Finished processing. Success: {success_count}/{len(supported_files)} in {time.perf_counter() - t_total:.2f}s")
    result = ProcessResult(supported_files)
    result.success_count = success_count
    result.failed_count = len(supported_files) - success_count
    result.successful_files = successful_files
    result.skipped_count = skipped_count
    return result
