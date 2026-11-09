#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 读取适配层 —— 用宽松许可组件替代 AGPL 的 PyMuPDF / pymupdf4llm。

背景
----
原实现直接依赖 ``pymupdf``（AGPL-3.0 / Artifex 商业双许可）与 ``pymupdf4llm``
（同族 AGPL），在开源 cosight-harness 的许可审核中不满足要求。本模块用等价栈
替换，许可全部宽松、无 copyleft 传染：

    - ``pypdfium2``（BSD-3-Clause OR Apache-2.0）：PDFium 绑定，负责**页面渲染、
      文字抽取（含坐标）、内嵌图片抽取（含坐标）**——对位 PyMuPDF 的 fitz 部分。
    - ``pdfplumber``（MIT，内含 ``pdfminer.six`` MIT）：负责 **PDF→Markdown 的
      表格检测**——对位 pymupdf4llm 的表格能力。

两套引擎的分工是刻意的：主链路（doc_image_extractor / ppt_slide_extractor）
只碰 PDFium，渲染与抽图是热路径，PDFium 是 C++ 实现、量级快于纯 Python 的
pdfminer；表格检测只在**兜底**的 PDF→Markdown 路径用 pdfplumber，那里不在
性能关键路径上。

坐标约定
--------
对外接口刻意做成 PyMuPDF 的形状（``get_text`` / ``get_text_blocks`` /
``get_images`` / ``render_png`` / ``extract_image_png``），让上层
``doc_image_extractor`` / ``ppt_slide_extractor`` 的改动面最小。**但 PDFium 的
坐标原点在左下（y 向上），PyMuPDF 在左上（y 向下）**——本模块在内部统一转成
PyMuPDF 语义（左上原点、y 向下），上层代码无感知。这是替换中最容易出错的一处，
所有对外返回的 bbox / y0 都是左上原点。

依赖说明
--------
``requirements.txt`` 只直接声明 ``pypdfium2`` 与 ``pdfplumber``：
``pdfminer.six`` 由 pdfplumber 传递引入；``Pillow``（MIT-CMU，本模块用它做
PNG 编码与图片尺寸探测）由 pdfplumber 以及既有的 ``llama-index-core`` /
``python-pptx`` 传递引入，均无需单独声明。
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("file_watcher.pdf_backend")

# 文字 run 合并成行时，垂直重叠率阈值（相对较矮的那个 run）
_LINE_OVERLAP_RATIO = 0.5
# 相邻两行切分的判据是**基线间距（pitch）相对字号**的倍率，而不是行间距
# （gap）相对行框高的倍率——两者的行框高口径不同：PyMuPDF 的行框是字体度量盒
# （高 ≈ 1.37×字号），PDFium 的文字对象框是墨迹盒（高 ≤ 1.0×字号，且有无降部
# 会差 2pt）。pitch（行顶到行顶的距离）在两个引擎里口径一致，可以直接比。
#
# 1.50 是实测 PyMuPDF ``get_text('blocks')`` 的切块阈值：以 0.01×字号 为步长
# 扫描字号 6/8/11/14/20，阈值都落在 **1.501×字号**——与字号无关，也与该行
# 有无降部字符无关（PyMuPDF 的行框是字体度量盒，不受墨迹影响）。
# 阈值取的是**后一行**的字号：实测「前 11pt / 后 16pt」在 pitch=24.0（=1.5×16）
# 才切块，「前 16pt / 后 11pt」在 pitch=16.5（=1.5×11）就切。
_BLOCK_PITCH_RATIO = 1.50
# PDF→Markdown 的段落切分阈值：与切块阈值一致——生成的 markdown 段落边界
# 即 PyMuPDF 的块边界，便于与旧实现产出的 md 逐段对齐。
_MD_PITCH_RATIO = 1.50
# 标题判定的字号倍率（相对正文字号）：略大即需配合「醒目」信号，显著更大则直接算
_HEADING_SIZE_RATIO = 1.15
_HEADING_STRONG_RATIO = 1.60
# 与正文同字号但整块加粗也算标题
_HEADING_SAME_RATIO = 0.95
# 标题文本长度上限（超过按正文处理）
_MAX_HEADING_CHARS = 100
# 标题层级阶梯：(标题字号 / 正文字号) 的下限 → 层级。档位照 pymupdf4llm 的实际
# 输出标定（56/26/22/16/12/10pt → h1..h6，正文 9pt）。
_HEADING_LEVEL_LADDER = ((4.00, 1), (2.60, 2), (2.00, 3), (1.50, 4), (1.25, 5))
# 表格检测的最小行数（pdfplumber 会对短表格产生噪声）
_MIN_TABLE_ROWS = 2
# 表格单元格里换行的占位符（markdown 表格不能有裸换行）
_CELL_NEWLINE = " "
# 标题最大层级
_MAX_HEADING_LEVEL = 6


class PdfBackendError(RuntimeError):
    """PDF 读取失败（文件损坏 / 加密 / 引擎异常）。"""


# ---------------------------------------------------------------------------
# 文字结构
# ---------------------------------------------------------------------------

class _TextRun:
    """一个 PDFium 文字对象（一次文字绘制操作）。"""

    __slots__ = ("x0", "y_top", "x1", "y_bottom", "text", "size", "bold",
                 "italic", "font")

    def __init__(self, x0: float, y_top: float, x1: float, y_bottom: float,
                 text: str, size: float, bold: bool, italic: bool,
                 font: str = "") -> None:
        self.x0 = x0
        self.y_top = y_top
        self.x1 = x1
        self.y_bottom = y_bottom
        self.text = text
        self.size = size
        self.bold = bold
        self.italic = italic
        self.font = font

    @property
    def height(self) -> float:
        return max(self.y_bottom - self.y_top, 0.0)


class _Line:
    """一行文字（若干 run 合并而成）。"""

    __slots__ = ("x0", "y_top", "x1", "y_bottom", "text", "size", "bold",
                 "italic", "font")

    def __init__(self) -> None:
        self.x0 = 0.0
        self.y_top = 0.0
        self.x1 = 0.0
        self.y_bottom = 0.0
        self.text = ""
        self.size = 0.0
        self.bold = False
        self.italic = False
        self.font = ""

    @property
    def height(self) -> float:
        return max(self.y_bottom - self.y_top, 0.0)

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.0)


class _Block:
    """一个文本块（若干行合并而成，对位 PyMuPDF 的 ``get_text('blocks')`` 一项）。"""

    __slots__ = ("x0", "y_top", "x1", "y_bottom", "text", "size", "bold",
                 "italic", "font")

    def __init__(self, x0: float, y_top: float, x1: float, y_bottom: float,
                 text: str, size: float = 0.0, bold: bool = False,
                 italic: bool = False, font: str = "") -> None:
        self.x0 = x0
        self.y_top = y_top
        self.x1 = x1
        self.y_bottom = y_bottom
        self.text = text
        self.size = size
        self.bold = bold
        self.italic = italic
        self.font = font

    def as_tuple(self) -> tuple[float, float, float, float, str]:
        return (self.x0, self.y_top, self.x1, self.y_bottom, self.text)


class PdfImageRef:
    """页面上的一张内嵌图片（坐标为左上原点）。"""

    __slots__ = ("key", "x0", "y_top", "x1", "y_bottom", "_obj")

    def __init__(self, key: str, x0: float, y_top: float, x1: float, y_bottom: float,
                 obj: Any) -> None:
        self.key = key
        self.x0 = x0
        self.y_top = y_top
        self.x1 = x1
        self.y_bottom = y_bottom
        self._obj = obj

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y_top, self.x1, self.y_bottom)


# ---------------------------------------------------------------------------
# 文档 / 页面
# ---------------------------------------------------------------------------

class PdfPage:
    """单页视图。坐标一律左上原点（PyMuPDF 语义）。"""

    def __init__(self, page: Any, page_height: float) -> None:
        self._page = page
        self._height = page_height
        self._text_runs: Optional[list[_TextRun]] = None
        self._images: Optional[list[PdfImageRef]] = None
        self._image_objs: dict[str, Any] = {}
        self._textpage: Optional[Any] = None
        self._chars: Optional[list[tuple[int, float, float, float, float]]] = None

    # -- 文本页 --

    def _get_textpage(self) -> Any:
        """取（并缓存）PDFium 文本页——用于按区域抽取文字。"""
        if self._textpage is None:
            self._textpage = self._page.get_textpage()
        return self._textpage

    def _load_chars(self) -> list[tuple[int, float, float, float, float]]:
        """本页字符表 ``(序号, x0, y_top, x1, y_bottom)``（左上原点）。"""
        if self._chars is not None:
            return self._chars
        chars: list[tuple[int, float, float, float, float]] = []
        try:
            textpage = self._get_textpage()
            for index in range(textpage.count_chars()):
                try:
                    left, bottom, right, top = textpage.get_charbox(index)
                except Exception:
                    continue
                chars.append((
                    index,
                    float(left),
                    self._height - float(top),
                    float(right),
                    self._height - float(bottom),
                ))
        except Exception as e:
            logger.warning("pdf_backend: 字符表抽取失败: %s", e)
            chars = []
        self._chars = chars
        return chars

    # -- 基础属性 --

    @property
    def width(self) -> float:
        return float(self._page.get_width())

    @property
    def height(self) -> float:
        return float(self._height)

    # -- 文字 --

    def _load_text_runs(self) -> list[_TextRun]:
        if self._text_runs is not None:
            return self._text_runs
        runs: list[_TextRun] = []
        try:
            import pypdfium2.raw as pdfium_c

            textpage = self._page.get_textpage()
            for obj in self._page.get_objects(
                filter=[pdfium_c.FPDF_PAGEOBJ_TEXT], textpage=textpage
            ):
                text = obj.extract()
                if not text or not text.strip():
                    continue
                left, bottom, right, top = obj.get_bounds()
                size = 0.0
                bold = False
                italic = False
                font_name = ""
                try:
                    size = _effective_font_size(obj)
                except Exception:
                    pass
                try:
                    font = obj.get_font()
                    base_name = (font.get_base_name(errors="replace") or "").lower()
                    font_name = _normalize_font_name(base_name)
                    italic = "italic" in base_name or "oblique" in base_name
                    bold = ("bold" in base_name or "black" in base_name
                            or "heavy" in base_name)
                    try:
                        weight = font.get_weight()
                        if weight is not None and int(weight) >= 600:
                            bold = True
                    except Exception:
                        pass
                except Exception:
                    pass
                runs.append(_TextRun(
                    x0=float(left),
                    y_top=self._height - float(top),
                    x1=float(right),
                    y_bottom=self._height - float(bottom),
                    text=text,
                    size=size,
                    bold=bold,
                    italic=italic,
                    font=font_name,
                ))
        except Exception as e:
            logger.warning("pdf_backend: 文字抽取失败: %s", e)
            runs = []
        self._text_runs = runs
        return runs

    def get_text(self) -> str:
        """整页纯文本（对位 ``page.get_text()``）。"""
        try:
            textpage = self._page.get_textpage()
            return textpage.get_text_range()
        except Exception as e:
            logger.warning("pdf_backend: get_text 失败: %s", e)
            return ""

    def get_text_blocks(self) -> list[tuple[float, float, float, float, str]]:
        """文本块列表 ``(x0, y_top, x1, y_bottom, text)``（对位 PyMuPDF 的 blocks）。

        合并策略与 PyMuPDF 的 ``get_text('blocks')`` 对齐：先按基线把文字 run 合并
        成行，再把间距紧凑的相邻行合并成块（一个自然段）。块内换行保留为 ``\\n``。

        文字内容用 **PDFium 自己的文本生成**（按行矩形抽取），而不是自己按 run 间隙
        拼字符串——PDFium 用的是字体 advance 宽度判定空格，与 PyMuPDF 的规则同源，
        自己拼会多出空格（例如把「邮编：518057」拼成「邮编： 518057」、把目录点引导
        线拆成「. . . .」）。
        """
        runs = self._load_text_runs()
        if not runs:
            return []
        lines = _merge_runs_into_lines(runs)
        self._apply_native_text(lines)
        return [b.as_tuple() for b in _blocks_from_lines(lines, _BLOCK_PITCH_RATIO)]

    def _apply_native_text(self, lines: list[_Line]) -> None:
        """用 PDFium 的文本抽取覆盖行内文字（失败时保留 run 拼接的结果）。

        按**行**矩形抽取而不是按块：块的矩形会罩住并排的其他块（双栏、表格），
        按行取才不会把邻块文字混进来。
        """
        try:
            textpage = self._get_textpage()
        except Exception as e:  # pragma: no cover - 依赖异常兜底
            logger.warning("pdf_backend: 文本页获取失败: %s", e)
            return
        for line in lines:
            text = self._extract_native_text(line.x0, line.y_top, line.x1, line.y_bottom)
            if text and text.strip():
                line.text = text

    def _extract_native_text(self, x0: float, y_top: float,
                             x1: float, y_bottom: float) -> str:
        """抽取矩形区域内的文字（PDFium 自己决定字与字之间要不要空格）。"""
        try:
            textpage = self._get_textpage()
            text = textpage.get_text_bounded(
                left=float(x0),
                bottom=self._height - float(y_bottom),
                right=float(x1),
                top=self._height - float(y_top),
            )
        except Exception as e:
            logger.warning("pdf_backend: 区域文本抽取失败: %s", e)
            return ""
        return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")

    # -- 图片 --

    def _load_images(self) -> list[PdfImageRef]:
        if self._images is not None:
            return self._images
        refs: list[PdfImageRef] = []
        seen: set[str] = set()
        try:
            import pypdfium2.raw as pdfium_c

            for obj in self._page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
                key = _image_key(obj)
                if key in seen:
                    # 同一张图在本页被绘制多次：与 PyMuPDF 按 xref 去重的行为一致，
                    # 只保留第一次出现的位置。
                    continue
                seen.add(key)
                left, bottom, right, top = obj.get_bounds()
                ref = PdfImageRef(
                    key=key,
                    x0=float(left),
                    y_top=self._height - float(top),
                    x1=float(right),
                    y_bottom=self._height - float(bottom),
                    obj=obj,
                )
                self._image_objs[key] = obj
                refs.append(ref)
        except Exception as e:
            logger.warning("pdf_backend: 图片枚举失败: %s", e)
            refs = []
        self._images = refs
        return refs

    def get_images(self) -> list[PdfImageRef]:
        """本页内嵌图片列表（坐标左上原点，已按内容去重）。"""
        return list(self._load_images())

    def extract_image_png(self, ref: PdfImageRef) -> bytes:
        """把一张内嵌图片编码成 PNG 字节。"""
        obj = self._image_objs.get(ref.key) or ref._obj
        if obj is None:
            raise PdfBackendError(f"pdf_backend: 图片 {ref.key} 不可用")
        # render=False：取图像自身的原生像素（与 PyMuPDF ``Pixmap(doc, xref)`` 同
        # 尺寸），且不叠加 SMask 透明蒙版——与旧实现行为一致。
        # PDFium 已在内部完成色彩空间转换（CMYK→RGB 等），输出恒为 RGB/RGBA。
        #
        # 不显式 close()：``to_pil()`` 得到的 PIL 图与 bitmap 缓冲区共享内存，
        # 提前释放会导致 use-after-free（pypdfium2 也会就此告警）。交给 GC 终结
        # 即可——缓冲区由 Pillow 侧持有引用，生命周期不会短于图片本身。
        bitmap = obj.get_bitmap(render=False)
        image = bitmap.to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    # -- 渲染 --

    def render_png(self, out_path: Path, dpi: float) -> Path:
        """把整页渲染成 PNG（对位 ``page.get_pixmap(matrix=...)`` + ``pix.save``）。"""
        scale = float(dpi) / 72.0
        # 同 extract_image_png：PIL 图与 bitmap 缓冲区共享内存，不显式 close()
        bitmap = self._page.render(scale=scale)
        image = bitmap.to_pil()
        image.save(str(out_path), format="PNG")
        return out_path


class PdfDocument:
    """PDF 文档视图。"""

    def __init__(self, doc: Any) -> None:
        self._doc = doc
        self._closed = False

    @property
    def page_count(self) -> int:
        return len(self._doc)

    def __len__(self) -> int:
        return self.page_count

    def __getitem__(self, index: int) -> PdfPage:
        page = self._doc[index]
        return PdfPage(page, float(page.get_height()))

    def __iter__(self):
        for index in range(self.page_count):
            yield self[index]

    def page(self, index: int) -> PdfPage:
        return self[index]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._doc.close()
        except Exception:
            pass

    def __enter__(self) -> "PdfDocument":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def open_pdf(path: str | Path) -> PdfDocument:
    """打开 PDF（对位 ``fitz.open``）。"""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover - 依赖缺失由部署保证
        raise PdfBackendError(f"pypdfium2 未安装: {e}") from e
    path = str(path)
    try:
        doc = pdfium.PdfDocument(path)
    except Exception as e:
        raise PdfBackendError(f"打开 PDF 失败 {path}: {e}") from e
    return PdfDocument(doc)


def image_size(data: bytes) -> Optional[tuple[int, int]]:
    """从图片字节读出 ``(宽, 高)``（对位 ``fitz.Pixmap(data).width/height``）。

    读不出尺寸时返回 None——调用方按「保留图片」处理（旧实现里 PyMuPDF 抛异常
    时也是被 except 吞掉后保留）。
    """
    if not data:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return (int(img.width), int(img.height))
    except Exception:
        return None


def pdf_to_markdown(path: str | Path) -> str:
    """PDF → Markdown（对位 ``pymupdf4llm.to_markdown``）。

    产出结构：标题（按字号分档）+ 段落 + 有序/无序列表 + 表格（markdown 表格），
    **不含图片**——与旧实现的默认调用（``to_markdown(path)``，``write_images=False``、
    ``embed_images=False``）一致，其 ``save_image()`` 在该配置下直接返回空串。

    两套引擎各司其职：文字结构（行/段/标题/粗斜体）走 PDFium 的文字对象，表格
    走 pdfplumber 的 ``find_tables``——PDFium 没有表格检测能力，pdfplumber 有。
    两者坐标都是左上原点，可直接按 bbox 对齐去重（表格区域的文字不再重复输出）。
    """
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover - 依赖缺失由部署保证
        raise PdfBackendError(f"pdfplumber 未安装: {e}") from e

    doc = open_pdf(path)
    try:
        pdf = pdfplumber.open(str(path))
    except Exception as e:
        doc.close()
        raise PdfBackendError(f"打开 PDF 失败 {path}: {e}") from e

    try:
        size_stats: dict[float, int] = {}
        font_stats: dict[str, int] = {}
        pages_blocks: list[list[_Block]] = []
        for index in range(doc.page_count):
            page = doc[index]
            lines = _merge_runs_into_lines(page._load_text_runs())
            page._apply_native_text(lines)
            blocks = _blocks_from_lines(lines, _MD_PITCH_RATIO)
            pages_blocks.append(blocks)
            for block in blocks:
                if block.size > 0:
                    size_stats[block.size] = size_stats.get(block.size, 0) + len(block.text)
                if block.font:
                    font_stats[block.font] = font_stats.get(block.font, 0) + len(block.text)

        body_size = _body_font_size(size_stats)
        body_font = _body_font_family(font_stats)

        chunks: list[str] = []
        plumber_pages = list(pdf.pages)
        for index, blocks in enumerate(pages_blocks):
            tables = _page_tables(plumber_pages[index] if index < len(plumber_pages) else None)
            md = _page_to_markdown(blocks, tables, body_size, body_font)
            if md.strip():
                chunks.append(md.strip())
        return "\n\n".join(chunks)
    finally:
        try:
            pdf.close()
        except Exception:
            pass
        doc.close()


# ---------------------------------------------------------------------------
# 内部实现：文字结构
# ---------------------------------------------------------------------------

def _effective_font_size(obj: Any) -> float:
    """文字对象的真实字号（PDF 用户空间单位）。

    PDFium 的 ``get_font_size()`` 返回的是 ``Tf`` 里的**原始**字号，而真实字号还
    包含文字矩阵的缩放——两者必须相乘才对。有些 PDF（尤其是从 Word/Illustrator
    导出的）会写 ``Tf 1`` 再用矩阵放大 12 倍，此时 PDFium 只会报 1.0，不做这步
    换算就会把所有文字都当成 1pt（标题判定、正文行距全部失效）。

    缩放取矩阵行列式的平方根 √|a·d − b·c|——它是矩阵的整体缩放系数，**旋转
    90° 的竖排文字也成立**（此时 a=d=0，但行列式仍是缩放的平方）。与 PyMuPDF/
    MuPDF 的字号算法实测一致（``Tf 1`` + 矩阵 ``(8.8,0,0,11)`` → 9.8387、
    竖排矩阵 ``(0,-11,11,0)`` → 11.0）。
    """
    size = float(obj.get_font_size())
    try:
        matrix = obj.get_matrix()
        scale = math.sqrt(abs(matrix.a * matrix.d - matrix.b * matrix.c))
    except Exception:
        scale = 1.0
    if scale <= 0:
        return size
    return size * scale


def _image_key(obj: Any) -> str:
    """图片的稳定标识（用于跨页去重）。

    PDFium 不暴露底层 XObject 的 xref（PyMuPDF 用来去重的依据），这里退而用
    「原始流字节的哈希 + 像素尺寸」——同一张图在多页被引用时原始字节相同，
    天然去重；不同 xref 但内容相同的图也会被合并（语义上更接近「同一张图」，
    只会少一次 OCR，不会多）。
    """
    try:
        raw = bytes(obj.get_data())
    except Exception:
        raw = b""
    try:
        px_w, px_h = obj.get_px_size()
    except Exception:
        px_w, px_h = (0, 0)
    digest = hashlib.sha1(raw).hexdigest() if raw else ""
    return f"{px_w}x{px_h}:{digest}"


def _merge_runs_into_blocks(runs: list[_TextRun],
                            pitch_ratio: float = _BLOCK_PITCH_RATIO) -> list[_Block]:
    """文字 run → 行 → 块。

    ``pitch_ratio`` 决定「相邻两行算不算同一块」（判据是基线间距 / 后一行字号）：
      - ``_BLOCK_PITCH_RATIO``（1.50）：复刻 PyMuPDF ``get_text('blocks')`` 的
        块切分，供 :meth:`PdfPage.get_text_blocks` 使用。
      - ``_MD_PITCH_RATIO``（1.50）：段落语义（换行的续行并入同一段），供
        :func:`pdf_to_markdown` 使用。
    """
    return _blocks_from_lines(_merge_runs_into_lines(runs), pitch_ratio)


def _blocks_from_lines(lines: list[_Line],
                       pitch_ratio: float = _BLOCK_PITCH_RATIO) -> list[_Block]:
    """行 → 块：基线间距超过 ``pitch_ratio`` × 后一行字号就另起一块。"""
    if not lines:
        return []
    blocks: list[_Block] = []
    current: list[_Line] = [lines[0]]
    for prev, line in zip(lines, lines[1:]):
        if _is_same_paragraph(prev, line, pitch_ratio):
            current.append(line)
        else:
            blocks.append(_block_from_lines(current))
            current = [line]
    blocks.append(_block_from_lines(current))
    return blocks



def _merge_runs_into_lines(runs: list[_TextRun]) -> list[_Line]:
    """文字 run → 行：垂直重叠率达标视为同一基线，按 x 排序拼文本。"""
    ordered = sorted(runs, key=lambda r: (round(r.y_top, 1), r.x0))
    buckets: list[list[_TextRun]] = []
    for run in ordered:
        placed = False
        for bucket in buckets:
            ref = bucket[-1]
            inter = min(ref.y_bottom, run.y_bottom) - max(ref.y_top, run.y_top)
            min_h = min(ref.height, run.height)
            if min_h > 0 and inter / min_h >= _LINE_OVERLAP_RATIO:
                bucket.append(run)
                placed = True
                break
        if not placed:
            buckets.append([run])

    lines: list[_Line] = []
    for bucket in buckets:
        bucket.sort(key=lambda r: r.x0)
        line = _Line()
        line.x0 = min(r.x0 for r in bucket)
        line.x1 = max(r.x1 for r in bucket)
        line.y_top = min(r.y_top for r in bucket)
        line.y_bottom = max(r.y_bottom for r in bucket)
        parts: list[str] = []
        prev_end: Optional[float] = None
        for r in bucket:
            text = r.text.strip()
            if not text:
                continue
            # run 之间有明显横向间隔时补一个空格——这是**兜底**路径：正常情况下
            # 行文字由 PDFium 自己抽取（见 PdfPage._apply_native_text），这里的
            # 拼接只在 PDFium 抽取失败时才会被采用。阈值取 0.25em（一个西文空格的
            # 典型宽度），避免把词粘在一起又不至于到处塞空格。
            gap_limit = 0.25 * (r.size or bucket[0].size or 10.0)
            if (prev_end is not None and r.x0 - prev_end > gap_limit
                    and parts and not parts[-1].endswith(" ")):
                parts.append(" ")
            parts.append(text)
            prev_end = r.x1
        line.text = "".join(parts)
        sizes = [r.size for r in bucket if r.size > 0]
        line.size = max(set(sizes), key=sizes.count) if sizes else 0.0
        line.bold = all(r.bold for r in bucket)
        line.italic = all(r.italic for r in bucket)
        fonts = [r.font for r in bucket if r.font]
        line.font = max(set(fonts), key=fonts.count) if fonts else ""
        if line.text.strip():
            lines.append(line)
    lines.sort(key=lambda l: (l.y_top, l.x0))
    return lines


def _is_same_paragraph(prev: _Line, line: _Line, pitch_ratio: float) -> bool:
    """相邻两行是否属于同一段落。

    判据是基线间距（行顶到行顶）相对**后一行字号**的倍率——见
    ``_BLOCK_PITCH_RATIO`` 的说明：必须用 pitch 而不是 gap（两引擎的行框高
    口径不同），且倍率取后一行的字号（PyMuPDF 实测行为）。
    """
    pitch = line.y_top - prev.y_top
    size = line.size or prev.size or 1.0
    if pitch > pitch_ratio * size:
        return False
    # 水平方向要有重叠（同一栏），否则是并排的两栏
    overlap = min(prev.x1, line.x1) - max(prev.x0, line.x0)
    if overlap <= 0:
        narrow = min(prev.width, line.width)
        return narrow > 0 and overlap / narrow >= 0.3
    return True


def _block_from_lines(lines: list[_Line]) -> _Block:
    text = "\n".join(l.text for l in lines if l.text.strip())
    sizes = [l.size for l in lines if l.size > 0]
    size = max(set(sizes), key=sizes.count) if sizes else 0.0
    fonts = [l.font for l in lines if l.font]
    return _Block(
        x0=min(l.x0 for l in lines),
        y_top=min(l.y_top for l in lines),
        x1=max(l.x1 for l in lines),
        y_bottom=max(l.y_bottom for l in lines),
        text=text,
        size=size,
        bold=all(l.bold for l in lines),
        italic=all(l.italic for l in lines),
        font=max(set(fonts), key=fonts.count) if fonts else "",
    )


# ---------------------------------------------------------------------------
# 内部实现：PDF → Markdown
# ---------------------------------------------------------------------------

_LIST_RE = re.compile(r"^\s*(?:[-*•·▪◦]|\(?\d+[.)、]|[a-zA-Z][.)])\s+")
# 目录条目的点线引导（"4.1 配置参数............"）——这类不是标题
_DOT_LEADER_RE = re.compile(r"\.{3,}")
# 图/表题注（"图5-1 填写要部署功能的站点" / "表3-1 版本要求"）——中文技术文档
# 的固定写法，题注比正文小一号但仍应作为标题（与 pymupdf4llm 一致放在 h6）
_CAPTION_RE = re.compile(r"^\s*(?:附图|附表|图|表|Figure|Table|Fig\.?|Tab\.?)\s*\d+",
                         re.IGNORECASE)
# 字体子集前缀（"ABCDEF+SimHei"）——比较字体族前先剥掉
_FONT_SUBSET_RE = re.compile(r"^[A-Za-z]{6}\+")


def _normalize_font_name(name: str) -> str:
    """字体名归一：去子集前缀、去空白、转小写。"""
    name = _FONT_SUBSET_RE.sub("", (name or "").strip())
    return name.lower()


def _body_font_size(size_stats: dict[float, int]) -> float:
    """正文字号（按字符数加权众数）——标题分档的基准。"""
    if not size_stats:
        return 0.0
    return max(size_stats.items(), key=lambda kv: kv[1])[0]


def _body_font_family(font_stats: dict[str, int]) -> str:
    """正文主字体（按字符数加权众数）——中文文档的标题常用黑体，正文用宋体，
    字体族差异是比字号更可靠的标题信号。"""
    if not font_stats:
        return ""
    return max(font_stats.items(), key=lambda kv: kv[1])[0]


def _is_heading_block(block: "_Block", body_size: float, body_font: str) -> bool:
    """块是否是一个标题。

    判定用三个信号（任一命中即算标题，但都要先过下面的「排除规则」）：
      - **字号显著更大**（≥ 正文字号 × 1.6）：文档封面/大标题，直接算。
      - **字号略大**（≥ × 1.15）**且醒目**：字体族与正文不同（中文文档里标题
        常用黑体、正文用宋体）或整块加粗。
      - **与正文同字号但整块加粗**：Word/PDF 导出常见的「同字号加粗标题」。

    排除规则（这两类最容易被误判成标题，且会把知识库的章节切分切碎）：
      - **目录条目**：带点线引导（`4.1 配置参数...........`）。
      - **引导句**：以冒号结尾（`本章包含如下主题：`）——它是正文的一部分。

    旧实现（pymupdf4llm）用版面模型判定，这里用可解释的启发式——宁可漏判
    也不误判。
    """
    if body_size <= 0 or block.size <= 0:
        return False
    text = block.text.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return False
    if _DOT_LEADER_RE.search(text):
        return False
    if text.endswith(("：", ":")):
        return False
    if block.size >= body_size * _HEADING_STRONG_RATIO:
        return True
    prominent = block.bold or (block.font and body_font and block.font != body_font)
    if block.size >= body_size * _HEADING_SIZE_RATIO and prominent:
        return True
    if block.bold and block.size >= body_size * _HEADING_SAME_RATIO:
        return True
    return False


def _is_caption_block(block: "_Block") -> bool:
    """块是否是图/表题注（"图5-1 ..."、"表3-1 ..."）。

    题注单独识别，不依赖字号——题注字号通常比正文小一号（10pt vs 9pt），按字号
    判定会漏掉。点线引导的目录条目已在 :func:`_is_heading_block` 里排除。
    """
    text = block.text.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return False
    if _DOT_LEADER_RE.search(text):
        return False
    return bool(_CAPTION_RE.match(text))


def _heading_level(size: float, body_size: float) -> int:
    """标题层级 = 字号相对正文字号的比值落在哪一档。

    档位是照着 pymupdf4llm 的实际输出标定的（同一份中文技术文档：56pt→h1、
    26pt→h2、22pt→h3、16pt→h4、12pt→h5、10pt→h6），只是把绝对字号换成相对
    正文字号的倍数，这样换一份正文字号不同的文档依然对得上。
    """
    if body_size <= 0 or size <= 0:
        return _MAX_HEADING_LEVEL
    ratio = size / body_size
    for threshold, level in _HEADING_LEVEL_LADDER:
        if ratio >= threshold:
            return level
    return _MAX_HEADING_LEVEL


def _page_tables(page: Any) -> list[tuple[tuple[float, float, float, float], str]]:
    """单页表格检测 → ``[(bbox, markdown), ...]``。"""
    if page is None:
        return []
    try:
        tables = page.find_tables()
    except Exception as e:
        logger.warning("pdf_backend: 表格检测失败: %s", e)
        return []
    out: list[tuple[tuple[float, float, float, float], str]] = []
    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows or len(rows) < _MIN_TABLE_ROWS:
            continue
        md = _table_to_markdown(rows)
        if md:
            out.append((tuple(table.bbox), md))
    return out


def _page_to_markdown(blocks: list[_Block],
                      tables: list[tuple[tuple[float, float, float, float], str]],
                      body_size: float, body_font: str) -> str:
    """单页 → Markdown 片段。"""
    items: list[tuple[float, int, str]] = []  # (y, kind, payload)  kind: 0=文本 1=表格

    table_bboxes = [bbox for bbox, _ in tables]
    for bbox, md in tables:
        items.append((float(bbox[1]), 1, md))

    for block in blocks:
        if _inside_any(block.x0, block.y_top, block.x1, block.y_bottom, table_bboxes):
            continue
        level = None
        if _is_caption_block(block):
            level = _MAX_HEADING_LEVEL
        elif _is_heading_block(block, body_size, body_font):
            level = _heading_level(block.size, body_size)
        items.append((block.y_top, 0, _block_to_markdown(block, level)))

    items.sort(key=lambda it: (round(it[0], 1), it[1]))
    out: list[str] = []
    for _, kind, payload in items:
        if payload.strip():
            out.append(payload.strip())
    return "\n\n".join(out)


def _block_to_markdown(block: _Block, level: Optional[int]) -> str:
    """文本块 → Markdown 片段（标题 / 粗体 / 斜体 / 列表 / 段落）。"""
    text = block.text
    if not text.strip():
        return ""

    if level:
        return "#" * level + " " + text.replace("\n", " ")

    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""

    # 列表项：逐行识别，保留原有标记
    if all(_LIST_RE.match(ln) for ln in lines):
        out = []
        for ln in lines:
            stripped = ln.lstrip()
            indent = len(ln) - len(stripped)
            prefix = " " * indent
            if _LIST_RE.match(stripped):
                marker = stripped.split(" ", 1)[0]
                rest = stripped[len(marker):].lstrip()
                out.append(f"{prefix}{marker} {rest}")
            else:
                out.append(ln)
        return "\n".join(out)

    if block.bold:
        text = "\n".join(f"**{ln}**" for ln in lines)
    elif block.italic:
        text = "\n".join(f"*{ln}*" for ln in lines)
    return text


def _inside_any(x0: float, y0: float, x1: float, y1: float,
                bboxes: list[tuple[float, float, float, float]]) -> bool:
    """矩形是否落在任一给定矩形内（按中心点判定，避免大块跨越表格边界时漏判）。"""
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    for bx0, by0, bx1, by1 in bboxes:
        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
            return True
    return False


def _table_to_markdown(rows: list[list[Any]]) -> str:
    """二维表 → markdown 表格。"""
    cleaned: list[list[str]] = []
    for row in rows:
        cells = ["" if c is None else str(c).replace("\n", _CELL_NEWLINE).strip()
                 for c in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    head, *body = cleaned
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join("---" for _ in range(width)) + " |"]
    for row in body:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)
