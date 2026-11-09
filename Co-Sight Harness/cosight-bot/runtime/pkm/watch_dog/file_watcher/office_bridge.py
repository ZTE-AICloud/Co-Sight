#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Linux 侧 Office 自动化桥 —— 承担 Windows win32com 在 Linux 上的角色。

Windows 的转换回退链（preprocessor._try_win32com_conversion /
doc_image_extractor._convert_doc_to_docx）是生产验证过的代码，原地冻结不动；
本模块只在非 Windows 平台被调用，把「老格式规范化到 OOXML」这件事补齐：

    .doc  --→ .docx   （LibreOffice headless）
    .xls  --→ .xlsx   （LibreOffice headless）
    .pptx --→ 逐页 PNG（LibreOffice headless + PDFium 渲染，见
    ppt_slide_extractor）
    .docx/.xlsx 也走一遍规范化（与 Windows 语义一致：兼容"伪装成 .xlsx 的
    BIFF8"等场景——扩展名不可信，交给真实 Office 引擎重存一次）

后端：soffice --headless（纯 CLI，无 GUI 依赖）。后端自探测 + 进程级缓存，
首次使用时打探测日志。

原先的 WPS 引擎后端（pywpsrpc）已移除：它依赖 WPS 私有 RPC 轮子，许可证
无法核实，不满足开源要求；切页能力改由 LibreOffice + PDFium 渲染承担
（ppt_slide_extractor），老格式规范化保留 LibreOffice 一条路径。
"""
from __future__ import annotations

import atexit
import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("file_watcher.office_bridge")

# 单文件转换超时（与 Windows 侧 preprocessor._WIN32COM_TIMEOUT_SEC 同值同语义：
# 含 soffice 冷启动；Open 挂死由看门狗强杀，该文件按失败处理，构建继续）
_CONVERT_TIMEOUT_SEC = 60.0
# soffice headless 转换超时（ppt_slide_extractor 同款量级）
_SOFFICE_TIMEOUT_SEC = 120.0

# 本进程内所有桥产物/工作目录的根；atexit 统一清理
_TEMP_ROOT = Path(tempfile.mkdtemp(prefix="office_bridge_"))
atexit.register(shutil.rmtree, _TEMP_ROOT, True)

_probe_cache: dict[str, object] = {}


# ---------------------------------------------------------------------------
# 探测
# ---------------------------------------------------------------------------

def find_soffice_binary() -> Optional[Path]:
    """定位 LibreOffice soffice 可执行文件（进程级缓存）。

    全平台走系统安装发现：PATH（shutil.which）+ Linux/Windows 常见安装路径。
    """
    cached = _probe_cache.get("soffice")
    if cached is not None:
        return cached or None
    resolved: Optional[Path] = None
    for cand in (
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
        "C:/Program Files/LibreOffice/program/soffice.exe",
        "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            resolved = Path(cand)
            break
    if resolved is None:
        for pattern in ("/opt/libreoffice*/program/soffice",):
            for cand in sorted(glob.glob(pattern)):
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    resolved = Path(cand)
                    break
            if resolved is not None:
                break
    _probe_cache["soffice"] = resolved if resolved is not None else False
    if resolved is None:
        logger.info("office_bridge: LibreOffice soffice not found on PATH/common locations")
    return resolved


# ---------------------------------------------------------------------------
# 后端实现：入参都是「已暂存的 input.<ext>」，产出「同目录 output.<target>」
# ---------------------------------------------------------------------------

def _backend_soffice(src: Path, dst: Path, target: str, timeout: float) -> None:
    soffice = find_soffice_binary()
    if soffice is None:
        raise RuntimeError("soffice not found")
    profile = _TEMP_ROOT / f"lo_profile_{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(soffice),
        f"-env:UserInstallation=file://{profile.as_posix()}",  # 独立 profile：允许多实例并发
        "--headless", "--norestore", "--convert-to", target.lstrip("."),
        "--outdir", dst.parent.as_posix(), src.as_posix(),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0 or not dst.is_file():
            raise RuntimeError(
                f"soffice convert failed (rc={proc.returncode}): {proc.stderr[-300:]}"
            )
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# 各扩展名 → 目标格式
_CANONICALIZE_TARGETS = {
    ".doc": ".docx",
    ".docx": ".docx",
    ".xls": ".xlsx",
    ".xlsx": ".xlsx",
}


def canonicalize_to_ooxml(src: Path, timeout: float = _CONVERT_TIMEOUT_SEC) -> Path:
    """把 Office 文档规范化到 OOXML，返回转换产物路径（桥临时目录内）。

    后端：soffice --headless。后端不可用抛 _NoBackendError；可用但转换失败
    抛最后一个异常。
    """
    ext = src.suffix.lower()
    target = _CANONICALIZE_TARGETS.get(ext)
    if target is None:
        raise ValueError(f"office_bridge: unsupported extension {ext}")

    # 先探测后端再动文件：无可用后端直接抛 _NoBackendError（软失败契约，
    # 调用方返回 None），不产生临时目录、不因源文件缺失产生误导性报错
    backends: list[tuple[str, Callable[[Path, Path, str, float], None]]] = []
    if find_soffice_binary() is not None:
        backends.append(("soffice", _backend_soffice))
    if not backends:
        raise _NoBackendError(
            "无可用 Office 自动化后端（请安装 LibreOffice）"
        )

    # 暂存为 ASCII 短名（与 Windows 侧同理：规避引擎对 CJK/长路径的怪癖，
    # 也让 soffice 产物名可预测：output<target>）
    job_dir = _TEMP_ROOT / f"job_{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True)
    src_copy = job_dir / f"input{ext}"
    dst = job_dir / f"output{target}"
    shutil.copy2(src, src_copy)

    last_err: Optional[Exception] = None
    for name, backend in backends:
        try:
            t0 = time.perf_counter()
            backend(src_copy, dst, target, timeout)
            logger.info(
                "office_bridge: %s 规范化 %s → %s via %s (%.1fs)",
                ext, src.name, target, name, time.perf_counter() - t0,
            )
            return dst
        except Exception as e:
            last_err = e
            logger.warning("office_bridge: 后端 %s 失败 for %s: %s", name, src.name, e)
    assert last_err is not None
    raise last_err


class _NoBackendError(Exception):
    pass


# ---------------------------------------------------------------------------
# 解析规范化产物（与 preprocessor._win32com_convert_blocking 的解析段同语义；
# Windows 侧代码冻结不动，此处独立实现，两处需保持一致）
# ---------------------------------------------------------------------------

# 内容健全性：Office 引擎对打不开但"容错打开"的加密/损坏文件会另存出整篇乱码
# （实测：乱码产物 _x00XX_ 转义 ~84/KB，正常产物 0/KB——Excel 系把控制字符
# 存成 _x00XX_ 字面转义）。乱码入库比文件失败更糟（污染向量库），必须拦截。
_GARBAGE_ESCAPE_RE = re.compile(r"_x00[0-9A-Fa-f]{2,3}_")
_GARBAGE_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_GARBAGE_MAX_ESCAPES_PER_KB = 2  # 与正常产物(0)和乱码产物(84)各留一个数量级余量


def _looks_like_text(text: str) -> bool:
    """转换产物是否像正常文本（乱码密度超阈值判为垃圾）。"""
    if not text or len(text.strip()) < 32:
        return False
    n = max(len(text), 1)
    escapes = len(_GARBAGE_ESCAPE_RE.findall(text)) + len(_GARBAGE_CTRL_RE.findall(text))
    return escapes * 1000 / n <= _GARBAGE_MAX_ESCAPES_PER_KB


def _docx_text_sane(out_file: Path) -> bool:
    """规范化产物 docx 的正文健全性（供返回路径的契约用）。"""
    try:
        import zipfile

        with zipfile.ZipFile(out_file) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        text = re.sub(r"<[^>]+>", "", xml)
        return _looks_like_text(text)
    except Exception:
        return False


def _parse_canonicalized(out_file: Path, orig_ext: str) -> str:
    if orig_ext in (".doc", ".docx"):
        import mammoth
        import markdownify

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


# ---------------------------------------------------------------------------
# 公开接口（契约与 Windows 侧对应函数一致）
# ---------------------------------------------------------------------------

def convert_office_to_markdown(word_path: Path):
    """preprocessor 第 4 级回退的 Linux 实现。

    契约与 preprocessor._try_win32com_conversion 完全一致：
      - 成功：返回 markdown 字符串
      - 无可用后端（软失败）：返回 None（调用方落到 RuntimeError）
      - 转换失败（硬失败）：返回 Exception（调用方 raise，文件按失败计）
    """
    word_path = Path(word_path)
    try:
        out_file = canonicalize_to_ooxml(word_path)
    except _NoBackendError as e:
        logger.info(f"office_bridge: {e}, skipping for {word_path.name}")
        return None
    except Exception as e:
        return e

    try:
        markdown = _parse_canonicalized(out_file, word_path.suffix.lower())
    except Exception as e:
        logger.warning(f"office_bridge: 解析规范化产物失败 for {word_path.name}: {e}")
        return e

    if not _looks_like_text(markdown):
        logger.warning(
            f"office_bridge: {word_path.name} 转换产物为乱码（源文件疑似加密/损坏），按失败处理"
        )
        return RuntimeError(
            f"转换产物为乱码（源文件疑似加密/损坏）: {word_path.name}"
        )
    return markdown


def convert_doc_to_docx(doc_path: Path) -> Optional[str]:
    """doc_image_extractor 老 .doc → 临时 .docx 的 Linux 实现。

    契约与 doc_image_extractor._convert_doc_to_docx 一致：成功返回临时
    docx 路径字符串，失败返回 None（不抛）。产物在桥的临时根目录下，
    进程退出统一回收；调用方对文件本身的 unlink 照常生效。
    """
    doc_path = Path(doc_path)
    try:
        out_file = canonicalize_to_ooxml(doc_path)
    except _NoBackendError as e:
        logger.info(f"office_bridge: {e}, doc->docx unavailable for {doc_path.name}")
        return None
    except Exception as e:
        logger.info(f"office_bridge: doc->docx failed for {doc_path.name}: {e}")
        return None
    if not _docx_text_sane(out_file):
        logger.warning(
            f"office_bridge: {doc_path.name} 规范化产物为乱码（源文件疑似加密/损坏），按失败处理"
        )
        return None
    return str(out_file)
