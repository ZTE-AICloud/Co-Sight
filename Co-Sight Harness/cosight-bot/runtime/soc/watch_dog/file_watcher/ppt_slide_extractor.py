"""PPT per-slide extractor.

For each OOXML PowerPoint file (`.pptx` or `.pptm`), produce:

    <pre_dir>/<stem>_<ext>_slides/
        Slide_01_<title>.png
        Slide_01_<title>.md
        Slide_02_<title>.png
        Slide_02_<title>.md
        ...
        slides_index.json

Each per-slide `.md` contains:

    # <title>          (or "第 N 页" when no title)
    <text extracted from python-pptx>
    ![](Slide_NN_<title>.png)

The function never raises for downstream consumption; failures degrade to
`{"ok": false, "reason": "..."}` so the caller (preprocessor) can fall
back to plain text extraction and continue indexing the document.

The function does NOT call any LLM for OCR/vision.
It only uses python-pptx for text/title. For slide image export the backend
order is:

  1. Windows PowerPoint/WPS COM path (via comtypes) — Windows primary;
  2. LibreOffice fallback (pptx -> PDF via headless soffice, then per-page
     PNG via PDFium/pypdfium2) — portable, no Office/WPS dependency, but
     slower and lower rendering fidelity.

（原第二档「WPS 演示 via pywpsrpc」已移除：pywpsrpc 依赖 WPS 私有 RPC 轮子，
许可证无法核实，不满足开源要求；Linux 侧统一走 LibreOffice + PDFium 渲染。）
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("file_watcher.ppt_slide_extractor")

# 后台子进程（taskkill/soffice）不弹控制台窗口 —— worker 由 pythonw 托管、
# 自身无控制台，CREATE_NO_WINDOW 缺省时每个子进程都会闪一个黑色控制台框。
# 与 kb_scheduler._no_window_flags / uploader._NO_WINDOW 同款处理。
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# PowerPoint COM 创建失败时的常见 HRESULT（来自僵尸 POWERPNT.EXE 占着
# COM 注册表项的几种表征）。Python ctypes/comtypes 在不同调用栈下可能
# 返回有符号或无符号形式，统一按 32-bit 无符号值比较。
_ORPHAN_RETRY_HRESULTS = frozenset({
    0x8001011F,  # RPC_E_DISCONNECTED — 服务端已断开
    0x80010001,  # RPC_E_CALL_REJECTED — 调用被拒（僵尸占位时常返）
    0x80010105,  # RPC_E_SERVER_DIED — 服务进程死亡
    0x80080005,  # RPC_E_SERVERFAULT — 服务器进程崩溃（资源耗尽或 PPT 触发的 bug）
})

# HRESULTs that mean "this thread has not called CoInitialize" (or the
# apartment is wrong). When seen on a persistent worker sub-process, the
# most likely cause is that we entered the COM path on a thread that the
# comtypes import-time init never reached (worker loop re-entry after
# LibreOffice, exception path leaving a stale apartment, etc.). Fix:
# re-initialize as STA and retry CreateObject once.
#
# Note on 0x800401F0: signed-decimal -2147221008 maps to this HRESULT, not
# 0x80010106 (which is -2147417850). Both are in the retry set because in
# practice both are observed when probe-Quit left the COM registration in
# a half-released state and the immediately following CreateObject races
# against the teardown.
_COINIT_RETRY_HRESULTS = frozenset({
    0x80010106,  # CO_E_OBJNOTCONNECTED — 对象已断开，常在 CoUninit 后
    0x80010109,  # RPC_E_NOT_REGISTERED — COM 本身未在当前线程注册
    0x80010112,  # CO_E_NOTINITIALIZED — 经典 "CoInitialize has not been called"
    0x800401F0,  # CO_E_INVALIDSYNTAX / signed -2147221008 — 常见于 probe Quit
                # 与下一个 CreateObject 的毫秒级 race 窗口
})

# Sleep between CoInit-retry and the retried CreateObject. The race window
# between probe Quit() and the next CreateObject is sub-second on most
# machines but can stretch to a few hundred ms under load; 1s is a safe
# ceiling that keeps the fallback path quiet without becoming user-visible
# latency in the common case (probe never raced, no sleep happens).
_COINIT_RACE_SETTLE_SEC = 1.0

# Total CreateObject attempts before giving up and falling back to
# LibreOffice. The COM probe has already established that the ProgID is
# bindable, so transient CreateObject failures (RPC_E_*, E_FAIL, OOM,
# STG_E_* etc.) should retry rather than immediately degrading to LO.
# Sleeps between attempts scale 2s/4s so the worst-case extra latency
# (3 attempts) is ~6s before falling back — acceptable given the renderer
# quality difference (LO loses SmartArt / connectors / gradients / CJK
# fonts compared to PowerPoint/WPS native export).
_MAX_CREATE_ATTEMPTS = 3
_GENERIC_SETTLE_SEC = 2.0  # 2nd attempt sleeps 2s; 3rd sleeps 4s


def _extract_hresult(exc: BaseException) -> int | None:
    """Best-effort extraction of an HRESULT integer from a COM exception.

    comtypes / ctypes throw a WindowsError-derived OSError whose shape
    depends on the call layer:

      - ``exc.hresult`` — comtypes' own attribute on its custom exceptions.
      - ``exc.winerror`` — Python's built-in WindowsError / OSError errno
        when raised from a ctypes call. **This is the actual HRESULT** for
        ``_ole32.CoCreateInstance`` failures (-2147221008 / 0x800401F0 etc).
      - ``exc.args`` — tuple whose shape is unstable: a plain
        ``OSError(winerror, msg)`` packs HRESULT at args[0], but a
        full WindowsError carries a 5-tuple ``(errno, msg, filename, winerror, ...)``
        where args[0] is ``errno`` (e.g. 22 for EINVAL) and **the real HRESULT
        sits at args[3]**.

    Production logs captured during the V0.0.14 regression show that the
    previous implementation returned ``22`` (errno) instead of
    ``0x800401F0``, missing the retry path silently. We must look at every
    integer slot in args and pick the one that looks like an HRESULT
    (high bit set on the unsigned 32-bit value). Returning ``errno=22``
    without this filter routed CoInit-style failures to the "not a
    retry-able error" branch.

    Returns the unsigned 32-bit HRESULT (or None when none is found).
    """
    hr = getattr(exc, "hresult", None)
    if isinstance(hr, int):
        return hr & 0xFFFFFFFF
    winerror = getattr(exc, "winerror", None)
    if isinstance(winerror, int):
        # winerror is the most reliable carrier — prefer it when present.
        return winerror & 0xFFFFFFFF
    # Fall back to scanning args. Pick the FIRST integer whose unsigned
    # 32-bit representation has the high bit set (the HRESULT-sign bit),
    # so a leading ``errno`` value (typically < 0x10000) is skipped.
    for item in getattr(exc, "args", ()):
        if isinstance(item, int) and (item & 0x80000000):
            return item & 0xFFFFFFFF
    # Last resort: any int we find (matches the OSError(-2147221008, msg)
    # shape some callers produce via OSError subclasses).
    for item in getattr(exc, "args", ()):
        if isinstance(item, int):
            return item & 0xFFFFFFFF
    return None


def _kill_orphan_office() -> None:
    """Best-effort kill of leftover PPT-family COM processes.

    Covers PowerPoint (``POWERPNT.EXE``) and WPS Presentation
    (``WPP.EXE``) — both can hold a stale COM registration after an
    unclean previous session. Narrowly scoped to those two EXEs so we
    never touch the user's own Word/Excel/WPS Writer if they are open.

    Silently no-ops if no such process exists or taskkill is unavailable.
    """
    for exe in ("POWERPNT.EXE", "WPP.EXE"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", exe],
                capture_output=True,
                timeout=10,
                creationflags=_NO_WINDOW,
            )
        except Exception:
            # taskkill missing / access denied / timeout — never block on cleanup
            pass


# Backwards-compatible alias — keep the old name working for any caller
# that imported it directly.
_kill_orphan_powerpoint = _kill_orphan_office


# Lazy imports ------------------------------------------------------------
def _pptx():
    try:
        import pptx  # type: ignore
    except ImportError as e:
        raise ImportError(
            "python-pptx is required for PPT slide extraction"
        ) from e
    return pptx


def _comtypes():
    try:
        import comtypes  # type: ignore
        import comtypes.client  # type: ignore
    except ImportError:
        return None
    return comtypes.client


# Backend discovery --------------------------------------------------------


@dataclass(frozen=True)
class ComBackend:
    """A COM ProgID that can serve as the PPT automation backend.

    ``authoritative_clsid`` is a hard-coded fallback CLSID that's been
    verified stable across every observed WPS/Office release of the same
    product line. The probe tries the ProgID first, then the locally-
    resolved CLSID (when a 64-bit Python can't see the 32-bit program's
    ProgID registration under WOW6432Node), and finally the
    authoritative CLSID. Whichever one activates first wins.
    """
    progid: str
    label: str          # human-readable for logs
    priority: int       # lower = preferred
    authoritative_clsid: str = ""  # hard-coded CLSID fallback


# Order matters: PowerPoint first (most tested, full API surface); the
# WPS ProgIDs are fallbacks for hosts without Office. WPS registers
# different ProgIDs depending on version/edition — ``KWPP.Application``
# is the Presentation-specific entry point, while ``WPS.Application`` /
# ``Kingsoft.WPS.Application`` are suite-level entry points some WPS
# installs expose instead (so WPS-only machines are covered even when
# KWPP is not registered). Each ProgID is probed once per process via
# _PROBE_CACHE; the actual CreateObject call in _create_specific_app is
# the real test.
#
# Note: ``ET.Application`` (WPS Spreadsheet) is deliberately NOT listed —
# it has no Presentations collection and cannot export slides.
#
# Authoritative CLSIDs here are verified-stable across all observed
# Office/WPS versions (PowerPoint.Application -> MSDN ApplicationClass
# GUID; WPP/KWPP/WPS -> field observations on WPS 11 & 12 in 2026).
# If WPS ever rotates a CLSID we move the entry off the fallback list
# and rely on dynamic registry resolution instead.
_CANDIDATE_BACKENDS: tuple[ComBackend, ...] = (
    ComBackend("WPP.Application",            "WPS Presentation",            10,
               "{44720441-94BF-4940-926D-4F38FECF2A47}"),
    ComBackend("KWPP.Application",           "WPS Presentation (legacy)",    11,
               "{44720441-94BF-4940-926D-4F38FECF2A48}"),
    ComBackend("WPS.Application",            "WPS Office",                  20,
               "{000209FF-0000-4B30-A977-D214852036FE}"),
    ComBackend("Kingsoft.WPS.Application",   "WPS Office (legacy)",         30, ""),
)

# Process-lifetime cache of "is ProgID X bindable here?" — saves a fresh
# CreateObject (which costs ~10s of COM registration time) on every PPT.
_PROBE_CACHE: dict[str, dict[str, Any]] = {}


def _resolve_progid_via_32bit_registry(progid: str) -> Optional[str]:
    """Look up a ProgID's CLSID in the 32-bit registry view.

    On a 64-bit OS, 32-bit WPS registers under ``HKLM\\SOFTWARE\\
    WOW6432Node\\Classes``. Python's default winreg view is 64-bit on a
    64-bit OS, so a vanilla lookup misses every 32-bit-only ProgID. We
    open the 32-bit hive explicitly; the call also follows ``CurVer``
    when present (e.g. ``KWPP.Application`` -> ``KWPP.Application.9``).
    """
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    if not hasattr(winreg, "KEY_WOW64_32KEY"):
        return None

    locations: tuple[tuple[Any, str], ...] = (
        (winreg.HKEY_CURRENT_USER, "SOFTWARE\\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Classes"),
    )
    for root, base in locations:
        for clsid_subkey in (f"{progid}\\CLSID", f"{progid}\\CurVer\\CLSID"):
            subkey = f"{base}\\{clsid_subkey}"
            try:
                with winreg.OpenKey(
                    root, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value:
                        return value
            except OSError:
                continue
    return None


def _probe_com_progid(comtypes_client: Any, progid: str) -> dict[str, Any]:
    """Bind a single ProgID once; record availability + version.

    Tries three tiers:

      1. ``CreateObject(progid)`` — the standard path.
      2. ``CreateObject(GUID(clsid))`` where ``clsid`` is resolved via
         ``_resolve_progid_via_32bit_registry``. This rescues the common
         64-bit Python vs 32-bit WPS scenario where the ProgID just
         isn't visible to comtypes.
      3. The hard-coded ``authoritative_clsid`` from the matched
         ``ComBackend``. This rescues machines where the WPS install
         registered the COM class under a ProgID we don't probe for,
         or where the local registry has no record at all but the
         class itself happens to be exported via a Per-Machine entry
         point.

    Cached for the process lifetime via ``_PROBE_CACHE`` — saves the
    ~10s of COM registration time on every subsequent PPT. The probe
    creates then immediately Quits the COM app so it doesn't leave a
    process running.
    """
    cached = _PROBE_CACHE.get(progid)
    if cached is not None:
        return cached
    result: dict[str, Any] = {
        "progid": progid,
        "available": False,
        "version": None,
        "error": None,
        "bind": "progid",     # which tier won: progid / registry / authoritative
        "clsid": None,         # CLSID actually used (when bind != 'progid')
    }
    if comtypes_client is None:
        result["error"] = "comtypes not available"
        _PROBE_CACHE[progid] = result
        return result

    # Tier 1: standard ProgID path
    try:
        app = comtypes_client.CreateObject(progid)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    else:
        _record_probe_success(result, app)
        _PROBE_CACHE[progid] = result
        return result

    # Tier 2: locally-resolved CLSID (32-bit registry view)
    local_clsid = _resolve_progid_via_32bit_registry(progid)
    if local_clsid:
        try:
            from comtypes import GUID  # type: ignore
            app = comtypes_client.CreateObject(GUID(local_clsid))
        except Exception as e:
            result["error"] = f"registry CLSID {local_clsid}: {e}"
        else:
            result["bind"] = "registry"
            result["clsid"] = local_clsid
            _record_probe_success(result, app)
            _PROBE_CACHE[progid] = result
            return result

    # Tier 3: authoritative (hard-coded) CLSID for this ProgID
    backend = next((b for b in _CANDIDATE_BACKENDS if b.progid == progid), None)
    auth_clsid = backend.authoritative_clsid if backend else ""
    if auth_clsid and auth_clsid.lower() != (local_clsid or "").lower().strip("{}"):
        try:
            from comtypes import GUID  # type: ignore
            app = comtypes_client.CreateObject(GUID(auth_clsid))
        except Exception as e:
            result["error"] = f"authoritative CLSID {auth_clsid}: {e}"
        else:
            result["bind"] = "authoritative"
            result["clsid"] = auth_clsid
            _record_probe_success(result, app)
            _PROBE_CACHE[progid] = result
            return result

    _PROBE_CACHE[progid] = result
    return result


def _record_probe_success(result: dict[str, Any], app: Any) -> None:
    """Fill in the success-side fields of a probe result.

    Extracted because all three tiers of ``_probe_com_progid`` end with
    the same bookkeeping (read Version, Quit). A successful CreateObject
    is *not* enough — the COM object must also expose the
    ``Presentations`` collection; a hollow ``POINTER(IUnknown)`` returned
    by a stale CLSID will accept Quit but is useless for slide export,
    and the e2e test would then crash with
    ``'POINTER(IUnknown)' object has no attribute 'Presentations'``.
    """
    # Functional fitness check: must expose the Presentations collection
    # we actually need. ``hasattr`` returns False on AttributeError
    # without raising, so this is safe against broken COM objects.
    if not hasattr(app, "Presentations"):
        result["available"] = False
        result["error"] = (
            "CLSID activated but COM object has no 'Presentations' "
            "collection (no PPT binary installed, or CLSID stale in registry)"
        )
        try:
            app.Quit()
        except Exception:
            pass
        return
    result["available"] = True
    try:
        result["version"] = getattr(app, "Version", None)
    except Exception:
        pass
    try:
        app.Quit()
    except Exception:
        pass


def _discover_ppt_backend(comtypes_client: Any) -> Optional[ComBackend]:
    """Return the highest-priority available backend, or None.

    Side effect: logs the full probe table at INFO so the journal
    shows which backends were tried and why each non-chosen one failed.
    """
    chosen: Optional[ComBackend] = None
    for backend in _CANDIDATE_BACKENDS:
        probe = _probe_com_progid(comtypes_client, backend.progid)
        if probe["available"]:
            chosen = backend
            break
    if logger.isEnabledFor(logging.INFO):
        lines = ["ppt_slide_extractor: COM backend probe:"]
        for backend in _CANDIDATE_BACKENDS:
            probe = _probe_com_progid(comtypes_client, backend.progid)
            if probe["available"]:
                mark = "OK"
                bind = probe.get("bind", "progid")
                bind_note = "" if bind == "progid" else f" via {bind}"
                extra = f" v={probe['version']}{bind_note}"
            else:
                mark = "NO"
                extra = f" ({probe['error']})"
            lines.append(
                f"  [{mark}] {backend.progid} [{backend.label}]{extra}"
            )
        if chosen is None:
            lines.append("  -> no PPT COM backend available; will skip PNG export")
        else:
            probe = _PROBE_CACHE.get(chosen.progid, {})
            bind = probe.get("bind", "progid")
            if bind == "progid":
                lines.append(f"  -> using {chosen.progid}")
            else:
                clsid = probe.get("clsid")
                lines.append(
                    f"  -> using {chosen.progid} (via {bind} CLSID {clsid})"
                )
        logger.info("\n".join(lines))
    return chosen


# Public API --------------------------------------------------------------


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
        return Path("\\\\?\\UNC" + abs_str[1:])
    return Path("\\\\?\\" + abs_str)


def convert_pptx_with_slides(
    pptx_path: Path,
    slides_dir: Path,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
    on_libreoffice_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    pptx_path = Path(pptx_path).resolve()
    slides_dir = Path(slides_dir).resolve()
    if not pptx_path.is_file():
        return {"ok": False, "reason": f"pptx not found: {pptx_path}"}

    # Defensive: kill any leftover PPT-family COM process from a previous
    # task in this worker. We saw the COM probe succeed on the first pptx
    # but fail on the second with "CoInitialize has not been called"
    # (WinError -2147221008) — the root cause is a previous CreateObject
    # having left POWERPNT.EXE / WPP.EXE in a half-dead state that
    # races the new CreateObject on the next task. Killing orphans
    # before each task is cheap (taskkill /IM returns ~0.01s when the
    # process doesn't exist) and avoids the whole class of "second
    # task always fails" bugs that previously only surfaced after
    # reference repo had been running in production for a while.
    if os.name == "nt":
        _kill_orphan_office()

    try:
        pptx_mod = _pptx()
    except ImportError as e:
        return {"ok": False, "reason": str(e)}

    # comtypes is resolved lazily inside _export_slide_pngs so importing
    # this module never pays the COM import cost.
    comtypes_client = None

    try:
        prs = pptx_mod.Presentation(str(pptx_path))
    except Exception as e:
        return {"ok": False, "reason": f"python-pptx open failed: {e}"}

    total = len(prs.slides)
    titles = [_slide_title(slide, idx) for idx, slide in enumerate(prs.slides, 1)]

    # Windows MAX_PATH (260) budget: each per-slide filename is
    # ``Slide_NN_<title>.<ext>``. Truncate ``<title>`` so the full path
    # stays under 260 chars; otherwise ``open()``/``write_text()`` fails
    # with [Errno 2] No such file or directory even though the parent dir
    # exists. We compute the budget from the actual ``slides_dir`` length
    # so install paths with longer prefixes get shorter titles.
    _filename_overhead = 14  # "Slide_NN_" (10) + ".md" (3) + safety
    _windows_max_path = 260
    _path_budget = _windows_max_path - len(str(slides_dir)) - 1 - _filename_overhead
    _sanitize_max_len = min(80, max(20, _path_budget))
    safe_titles = [
        _sanitize_filename(t, idx, max_len=_sanitize_max_len)
        for idx, t in enumerate(titles, 1)
    ]

    # Collect per-page text from python-pptx. Done before the COM export so
    # the page dict is usable even when COM is unavailable.
    page_texts: list[list[str]] = []
    for slide in prs.slides:
        blocks: list[str] = []
        for shape in slide.shapes:
            if shape is None:
                continue
            if not getattr(shape, "has_text_frame", False):
                continue
            text = shape.text_frame.text if shape.text_frame else ""
            if text and text.strip():
                blocks.append(text.strip())
        # Also include speaker notes if available
        try:
            if slide.has_notes_slide and slide.notes_slide is not None:
                notes_tf = slide.notes_slide.notes_text_frame
                notes_text = notes_tf.text if notes_tf else ""
                if notes_text and notes_text.strip():
                    blocks.append(f"[备注] {notes_text.strip()}")
        except Exception:
            pass
        page_texts.append(blocks)

    # Export slide images via PowerPoint COM (Windows). Failures degrade
    # gracefully: the function still returns ok with the markdown + index
    # populated; PNGs are simply absent (their relative links in .md will
    # be broken and shown to humans as missing images, but LLM retrieval
    # still works against the .md text).
    #
    # 把 progress 回调穿透到 COM 导出循环：每张 PNG 导出**成功后**就 fire 一次，
    # 让用户在 22s 的 COM 导出期间也能看到 0→1→2→3→4 的进度（而不是只在
    # markdown 写入的 0.5s 内瞬间跳完）。
    png_status = _export_slide_pngs(
        pptx_path=pptx_path,
        slides_dir=slides_dir,
        total=total,
        comtypes_client=comtypes_client,
        safe_titles=safe_titles,
        on_libreoffice_fallback=on_libreoffice_fallback,
        progress=progress,
    )

    try:
        slides_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        if os.name == "nt":
            try:
                _to_long_path(slides_dir).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        else:
            raise

    pages: list[dict[str, Any]] = []
    for idx in range(1, total + 1):
        safe_title = safe_titles[idx - 1]
        stem = f"Slide_{idx:02d}_{safe_title}"
        png_filename = f"{stem}.png"
        md_filename = f"{stem}.md"
        png_path = slides_dir / png_filename
        md_path = slides_dir / md_filename
        text_blocks = page_texts[idx - 1]
        png_ok = png_status.get(idx, False) and png_path.is_file()

        md_lines: list[str] = []
        title = titles[idx - 1] or f"第 {idx} 页"
        md_lines.append(f"# {title}")
        md_lines.append("")
        if text_blocks:
            for block in text_blocks:
                for line in block.splitlines() or [""]:
                    md_lines.append(line)
                md_lines.append("")
        else:
            md_lines.append("(本页没有可提取的文本)")
            md_lines.append("")
        md_lines.append(f"![]({png_filename})")
        md_lines.append("")

        # Use the long-path form on Windows so writes succeed even when
        # the joined path is right at MAX_PATH (260). The exported PNG
        # and the slides_index.json are written by the COM/IO code
        # directly; we only need to bypass the limit on our .md writes.
        if os.name == "nt":
            try:
                md_write_path: Path = _to_long_path(md_path)
            except Exception:
                md_write_path = md_path
        else:
            md_write_path = md_path
        try:
            md_write_path.write_text("\n".join(md_lines), encoding="utf-8")
            md_ok = True
        except OSError as e:
            logger.warning(
                f"ppt_slide_extractor: failed to write {md_path}: {e}"
            )
            md_ok = False

        if progress is not None:
            try:
                progress(idx, total)
            except Exception:
                pass

        pages.append(
            {
                "page_index": idx,
                "title": title,
                "md_relpath": md_filename,
                "md_abspath": str(md_path),
                "image_relpath": png_filename,
                "image_abspath": str(png_path),
                "ok": bool(md_ok and png_ok),
            }
        )

    totals = {
        "pages": total,
        "ok": sum(1 for p in pages if p["ok"]),
        "failed": sum(1 for p in pages if not p["ok"]),
    }
    index = {
        "schema_version": 1,
        "kind": "ppt_slides",
        "source_pptx": str(pptx_path),
        "slides_dir": str(slides_dir),
        "pages": pages,
        "totals": totals,
    }
    try:
        index_path = slides_dir / "slides_index.json"
        if os.name == "nt":
            try:
                index_path = _to_long_path(index_path)
            except Exception:
                pass
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning(
            f"ppt_slide_extractor: failed to write slides_index.json: {e}"
        )
    return {"ok": True, "slides_dir": str(slides_dir), "pages": pages, "totals": totals}


# Helpers -----------------------------------------------------------------

_PLACEHOLDER_TYPES = (13, 14, 15)  # TITLE / CENTER_TITLE / ? — see pptx source


def _slide_title(slide, fallback_idx: int) -> str:
    """Best-effort slide title extraction.

    Mirrors the priority list used by the real-ppt reference and similar
    tooling:
      1. `slide.shapes.title` (layout-defined title placeholder)
      2. First placeholder whose type is a TITLE/CENTER_TITLE
      3. First non-empty text shape's first line
    """
    try:
        title_shape = slide.shapes.title
    except Exception:
        title_shape = None
    if title_shape is not None and getattr(title_shape, "has_text_frame", False):
        text = (title_shape.text_frame.text or "").strip()
        if text:
            return text
    for ph in getattr(slide, "placeholders", []):
        try:
            ph_type = ph.placeholder_format.type
        except Exception:
            ph_type = None
        if ph_type in _PLACEHOLDER_TYPES and getattr(ph, "has_text_frame", False):
            text = (ph.text_frame.text or "").strip()
            if text:
                return text
    for shape in slide.shapes:
        if not getattr(shape, "has_text_frame", False):
            continue
        text = (shape.text_frame.text or "").strip()
        if text:
            return text.split("\n", 1)[0].strip()
    return ""


_INVALID_FN_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MULTI_SPACE = re.compile(r"\s+")


def _sanitize_filename(title: str, idx: int, max_len: int = 80) -> str:
    """Turn a slide title into a safe filename stem component."""
    if not title:
        return ""
    name = title.strip()
    name = _INVALID_FN_CHARS.sub("_", name)
    name = _CONTROL_CHARS.sub("", name)
    name = _MULTI_SPACE.sub(" ", name).strip()
    name = name.strip(". ")
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or f"slide_{idx:02d}"


# LibreOffice portable backend (fallback) ----------------------------------
#
# Pipeline: headless soffice converts pptx -> PDF in one shot, then PDFium
# renders each PDF page to a per-slide PNG. This is the fallback for
# machines where no PowerPoint/WPS COM ProgID is bindable — LibreOffice
# 走系统安装（PATH / 常见安装路径发现），不依赖任何 Office/WPS 安装。

# 192 dpi -> 1920x1080 for 16:9 decks. Matches the effective DPI of typical
# embedded photos (~200) so rendered images stay sharp when zoomed, while
# keeping PNG size reasonable. (The legacy COM export produced 96 dpi.)
_LIBREOFFICE_RENDER_DPI = 192

# Headless soffice conversion timeout. 11-page deck ~8s cold; large decks
# scale roughly linearly.
_SOFFICE_TIMEOUT_SEC = 300

# Process-lifetime cache for the resolved soffice.exe path. ``False`` means
# "probed, not found" so we don't re-scan on every PPT.
_SOFFICE_CACHE: dict[str, Any] = {}


def _find_soffice_exe() -> Optional[Path]:
    """Locate the LibreOffice soffice binary, cached per process.

    统一走系统安装发现
    （office_bridge.find_soffice_binary：PATH + 常见安装路径）。
    """
    cached = _SOFFICE_CACHE.get("path")
    if cached is not None:
        return cached or None

    resolved = None
    try:
        from .office_bridge import find_soffice_binary
        resolved = find_soffice_binary()
    except Exception as e:
        logger.info("ppt_slide_extractor: office_bridge unavailable (%s)", e)
    _SOFFICE_CACHE["path"] = resolved if resolved is not None else False
    if resolved is None:
        logger.info(
            "ppt_slide_extractor: LibreOffice not found "
            "(install libreoffice to enable slide PNG export)"
        )
    return resolved


def _display_wpp_path() -> tuple[str, bool]:
    # COM 诊断模块不可用：WPS 路径探测跳过，
    # 返回占位值，告警载荷中 wpp_detected 恒为 False。
    return "", False


def _pdf_backend():
    """取 PDF 读取后端（pypdfium2 底座）。

    原实现用的是 PyMuPDF（AGPL 许可，不满足开源要求），已换成宽松许可的
    :mod:`pdf_backend`（PDFium）。渲染接口保持一致：``render_png(path, dpi)``。
    """
    try:
        from . import pdf_backend  # type: ignore
    except ImportError:
        return None
    return pdf_backend


def _pptx_to_pdf_via_soffice(soffice: Path, pptx_path: Path, work_dir: Path) -> Path:
    """Convert pptx to ``<work_dir>/<stem>.pdf`` via headless soffice.

    Uses a throwaway ``-env:UserInstallation`` profile so we never touch the
    user's own LibreOffice profile and concurrent conversions don't lock
    each other out.
    """
    profile_dir = Path(tempfile.mkdtemp(prefix="lo_profile_"))
    profile_uri = profile_dir.as_posix()
    if not profile_uri.startswith("/"):
        profile_uri = "/" + profile_uri  # file:///C:/... form
    cmd = [
        str(soffice),
        "--headless",
        "--norestore",
        "--nologo",
        f"-env:UserInstallation=file://{profile_uri}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(work_dir),
        str(pptx_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_SOFFICE_TIMEOUT_SEC,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"soffice timed out after {_SOFFICE_TIMEOUT_SEC}s"
        ) from e
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
    pdf_path = work_dir / (pptx_path.stem + ".pdf")
    if proc.returncode != 0 or not pdf_path.is_file():
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"soffice pdf conversion failed (exit={proc.returncode}): {stderr}"
        )
    return pdf_path


def _export_slide_pngs_libreoffice(
    *,
    pptx_path: Path,
    slides_dir: Path,
    total: int,
    safe_titles: list[str],
    on_selected: Optional[Callable[[dict[str, Any]], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Optional[dict[int, bool]]:
    """Export each slide as PNG via portable LibreOffice + PDFium.

    Returns ``{page_index: bool}`` on success (or per-slide partial
    success), or ``None`` when the LibreOffice backend cannot do the job
    (soffice missing, PDF 后端缺失, conversion failed) so the caller
    can degrade to "no PNGs exported".
    """
    soffice = _find_soffice_exe()
    if soffice is None:
        return None
    pdf_backend = _pdf_backend()
    if pdf_backend is None:
        logger.warning(
            "ppt_slide_extractor: pdf backend not available; "
            "cannot render slide PNGs via LibreOffice"
        )
        return None

    # "COM 不可用、降级到 LibreOffice" 的告警只对 Windows 有意义（COM 是
    # Windows 主路径，降级值得提示）；Linux 上 LibreOffice 本就是设计主路径，
    # COM 永不可用，推 com_unavailable /
    # wpp_detected（还是 Windows 路径）的告警是纯噪音且误导用户以为出了故障。
    if on_selected is not None and os.name == "nt":
        try:
            wpp_path, detected = _display_wpp_path()
            on_selected({
                "backend": "libreoffice",
                "com_unavailable": True,
                "soffice_path": str(soffice),
                "wpp_path": wpp_path,
                "wpp_detected": detected,
            })
        except Exception as e:
            logger.warning(
                "ppt_slide_extractor: failed to publish LibreOffice fallback "
                f"notification: {e}"
            )

    work_dir = Path(tempfile.mkdtemp(prefix="lo_pptx2png_"))
    t0 = time.time()
    t_pdf = 0.0
    try:
        try:
            pdf_path = _pptx_to_pdf_via_soffice(soffice, pptx_path, work_dir)
        except Exception as e:
            logger.warning(
                f"ppt_slide_extractor: LibreOffice pdf conversion failed: {e}"
            )
            return None
        t_pdf = time.time() - t0

        doc = pdf_backend.open_pdf(pdf_path)
        status: dict[int, bool] = {}
        try:
            page_count = len(doc)
            if page_count != total:
                # e.g. hidden slides are included in python-pptx's slide
                # list but not exported to PDF by LibreOffice. Map pages
                # sequentially and mark the tail as failed.
                logger.warning(
                    f"ppt_slide_extractor: LibreOffice exported {page_count} "
                    f"pdf pages but pptx has {total} slides; "
                    "mapping pages in order"
                )
            for idx, page in enumerate(doc, 1):
                if idx > total:
                    break
                safe_title = safe_titles[idx - 1]
                png_path = slides_dir / f"Slide_{idx:02d}_{safe_title}.png"
                try:
                    page.render_png(png_path, _LIBREOFFICE_RENDER_DPI)
                    status[idx] = png_path.is_file()
                except Exception as e:
                    logger.warning(
                        f"ppt_slide_extractor: LibreOffice render failed "
                        f"for slide {idx}: {e}"
                    )
                    status[idx] = False
                # 每张 fire 一次（与 COM 后端行为一致）
                if progress is not None:
                    try:
                        progress(idx, total)
                    except Exception as e:
                        logger.warning(
                            f"ppt_slide_extractor: progress callback error: {e}"
                        )
            for idx in range(page_count + 1, total + 1):
                status.setdefault(idx, False)
        finally:
            doc.close()
        logger.info(
            f"ppt_slide_extractor: LibreOffice exported "
            f"{sum(1 for v in status.values() if v)}/{total} slide PNGs "
            f"(pdf={t_pdf:.1f}s png={time.time() - t0 - t_pdf:.1f}s "
            f"total={time.time() - t0:.1f}s, soffice: {soffice})"
        )
        return status
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _export_slide_pngs(
    *,
    pptx_path: Path,
    slides_dir: Path,
    total: int,
    comtypes_client,
    safe_titles: Optional[list[str]] = None,
    on_libreoffice_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> dict[int, bool]:
    """Export each slide as PNG: PowerPoint/WPS COM first, LibreOffice fallback.

    Returns a dict ``{page_index: bool}`` indicating per-slide success.
    When neither backend is available (e.g. non-Windows host, no Office/WPS
    installed, comtypes missing, and no portable LibreOffice) the function
    logs a warning and returns an all-False dict — caller treats that as
    "no PNGs were exported".

    The caller should pass ``safe_titles`` (already computed with the
    correct MAX_PATH budget) so the PNG filenames match the .md filenames
    the caller will write in the next step. When omitted, this function
    recomputes them with the default 80-char cap, which may diverge from
    the caller's truncation when paths are near MAX_PATH (260).

    Backend order: Windows PowerPoint/WPS COM (via comtypes) first — it is
    the most faithful renderer (native Office export, honours hidden-slide
    semantics and embedded fonts); the portable LibreOffice backend runs
    only when COM cannot do the job.
    progress: 可选 (current, total) 回调。每张 PNG 导出**成功后**触发一次；
              让用户在 PPT 处理的 ~22 秒 COM 导出期间也能看到进度（而不是
              只在 markdown 写入阶段瞬间跳完）。
    """
    if total <= 0:
        return {}

    slides_dir.mkdir(parents=True, exist_ok=True)

    # Resolve safe_titles up-front so both backends produce identical
    # filenames (Slide_NN_<safe_title>.png).
    if safe_titles is None or len(safe_titles) != total:
        try:
            prs = _pptx().Presentation(str(pptx_path))
            titles = [_slide_title(s, i) for i, s in enumerate(prs.slides, 1)]
            safe_titles = [
                _sanitize_filename(t, i) for i, t in enumerate(titles, 1)
            ]
        except Exception:
            safe_titles = [f"slide_{i:02d}" for i in range(1, total + 1)]

    # Primary backend: PowerPoint/WPS COM. Returns None when COM cannot do
    # the job at all (comtypes missing, no bindable ProgID, deck open
    # failed) so we can fall through to LibreOffice.
    # Test hook: force the production LibreOffice fallback without changing
    # Office/WPS registration on the machine. This is intentionally opt-in
    # and only accepts the explicit value "1".
    force_libreoffice = os.environ.get("COSIGHTBOT_FORCE_LIBREOFFICE", "").strip() == "1"
    if force_libreoffice:
        logger.warning(
            "ppt_slide_extractor: COSIGHTBOT_FORCE_LIBREOFFICE=1; "
            "skipping PowerPoint/WPS COM for testing"
        )
        com_status = None
    else:
        com_status = _export_slide_pngs_com(
            pptx_path=pptx_path,
            slides_dir=slides_dir,
            total=total,
            comtypes_client=comtypes_client,
            safe_titles=safe_titles,
            progress=progress,
        )
    if com_status is not None:
        logger.info(
            f"ppt_slide_extractor: PowerPoint/WPS COM exported "
            f"{sum(1 for v in com_status.values() if v)}/{total} slide PNGs"
        )
        return com_status
    logger.info("ppt_slide_extractor: PowerPoint/WPS COM backend unavailable")

    logger.info(
        "ppt_slide_extractor: falling back to portable LibreOffice"
    )

    # Fallback backend: portable LibreOffice. Independent of any Office/WPS
    # installation, so it also covers machines whose COM ProgIDs are broken.
    lo_status = _export_slide_pngs_libreoffice(
        pptx_path=pptx_path,
        slides_dir=slides_dir,
        total=total,
        safe_titles=safe_titles,
        on_selected=on_libreoffice_fallback,
        progress=progress,
    )
    if lo_status is not None:
        return lo_status

    logger.warning(
        "ppt_slide_extractor: no PNG export backend available "
        "(COM failed and LibreOffice unavailable); skipping PNG export"
    )
    return {i: False for i in range(1, total + 1)}


def _export_slide_pngs_com(
    *,
    pptx_path: Path,
    slides_dir: Path,
    total: int,
    comtypes_client,
    safe_titles: list[str],
    progress: Optional[Callable[[int, int], None]] = None,
) -> Optional[dict[int, bool]]:
    """Export each slide as PNG via Windows PowerPoint/WPS COM (comtypes).

    Returns ``{page_index: bool}`` when the COM backend did the job
    (per-slide failures included), or ``None`` when COM cannot do the job
    at all (comtypes missing, no bindable ProgID, deck open failed) so
    the caller can fall back to the LibreOffice backend.

    progress: 可选 (current, total) 回调。每张 PNG 导出**完成后**触发一次；
              让用户在 PPT 处理的 ~22 秒 COM 导出期间也能看到进度。
    """
    if comtypes_client is None:
        comtypes_client = _comtypes()
    if comtypes_client is None:
        logger.info(
            "ppt_slide_extractor: comtypes not available; "
            "cannot use PowerPoint/WPS COM backend"
        )
        return None

    status: dict[int, bool] = {}

    application = None
    deck = None
    try:
        try:
            application = _create_powerpoint_app(comtypes_client)
        except Exception as e:
            logger.warning(
                f"ppt_slide_extractor: failed to start PowerPoint COM: {e}"
            )
            return None

        # Background-friendly: do not steal focus. The reference
        # implementation uses Visible=1; we deliberately switch to 0 so
        # the background process does not flash a window.
        try:
            application.Visible = 0
            application.DisplayAlerts = 0
        except Exception:
            pass

        try:
            deck = application.Presentations.Open(
                str(pptx_path), ReadOnly=True, WithWindow=False
            )
        except Exception as e:
            logger.warning(
                f"ppt_slide_extractor: failed to open deck {pptx_path}: {e}"
            )
            return None

        for idx in range(1, total + 1):
            safe_title = safe_titles[idx - 1]
            stem = f"Slide_{idx:02d}_{safe_title}"
            png_path = slides_dir / f"{stem}.png"
            try:
                # PowerPoint COM rejects \\?\ long-path prefixes
                # ("Invalid request. This is not a valid filename"),
                # so we rely on the MAX_PATH-aware filename budget
                # computed in convert_pptx_with_slides to keep the
                # path under 260 chars naturally.
                deck.Slides[idx].Export(str(png_path), "PNG")
                status[idx] = png_path.is_file()
            except Exception as e:
                logger.warning(
                    f"ppt_slide_extractor: COM export failed for slide {idx}: {e}"
                )
                status[idx] = False
            # 每张 PNG 导出**成功后** fire 一次回调（无论 ok/false 都 fire，
            # 避免卡在失败的一张上）。让用户在 22s 的 COM 导出期间也能看到进度。
            if progress is not None:
                try:
                    progress(idx, total)
                except Exception as e:
                    logger.warning(
                        f"ppt_slide_extractor: progress callback error: {e}"
                    )
        return status
    finally:
        try:
            if deck is not None:
                deck.Close()
        except Exception:
            pass
        try:
            if application is not None:
                application.Quit()
        except Exception:
            pass
        # Evict the probe cache for the ProgID we just used. The cache is the
        # root cause of the "first pptx works, subsequent ones spuriously
        # fall back to LibreOffice" bug: probe created a real COM app and
        # immediately Quit(), so the COM registration was still mid-teardown
        # when this task's CreateObject ran. The stale cache entry masked
        # that, and once evicted the next task re-probes (cheap) instead of
        # trusting a possibly-stale "available=True".
        progid_for_eviction = None
        if application is not None:
            try:
                progid_for_eviction = application._cosight_ppt_progid
            except Exception:
                progid_for_eviction = None
        if progid_for_eviction and progid_for_eviction in _PROBE_CACHE:
            _PROBE_CACHE.pop(progid_for_eviction, None)
            logger.info(
                f"ppt_slide_extractor: evicted probe cache for {progid_for_eviction} "
                f"after successful COM export (forces re-probe on next task)"
            )


def _create_powerpoint_app(comtypes_client: Any) -> Any:
    """Create the best-available PPT COM application with orphan-resilience.

    Probe order (see ``_CANDIDATE_BACKENDS``):
      1. ``PowerPoint.Application`` (Microsoft Office)
      2. ``WPP.Application`` (WPS Presentation — the modern, canonical
         ProgID since WPS 2016; most fresh installs register this)
      3. ``KWPP.Application`` (legacy "Kingsoft" era ProgID; still
         registered for compatibility on many corporate installs)
      4. ``WPS.Application`` / ``Kingsoft.WPS.Application`` (suite-level
         ProgIDs some WPS installs register instead of WPP/KWPP)

    If no backend is bindable at all, a one-shot WPS self-register repair is
    attempted before giving up; the probe cache is cleared before re-probing.

    If the chosen backend's first ``CreateObject`` call fails with one
    of the well-known "stale COM server" HRESULTs (RPC_E_DISCONNECTED
    0x8001011F, RPC_E_CALL_REJECTED 0x80010001, RPC_E_SERVER_DIED
    0x80010105), the most likely cause is a zombie PPT-family process
    from a previous unclean session still holding the COM
    registration. We taskkill it, sleep briefly, and retry once. Any
    other error — or a second failure — propagates so the caller can
    log it and degrade gracefully.

    Note: we do NOT cross-fallback from PowerPoint to WPS after the
    CreateObject call — once a backend is chosen, we trust it for the
    duration of this call. Per-slide ``Slides[i].Export`` failures are
    already handled by ``_export_slide_pngs`` (logged + per-page False).
    """
    backend = _discover_ppt_backend(comtypes_client)
    if backend is None:
        tried = ", ".join(b.progid for b in _CANDIDATE_BACKENDS)
        raise RuntimeError(f"no PPT COM backend available (tried: {tried})")
    # Respect the tier that won during probing: a "progid"-bound backend
    # creates by ProgID; a "registry" / "authoritative"-bound backend
    # creates by CLSID (the cached probe result recorded the CLSID used).
    probe = _PROBE_CACHE.get(backend.progid, {})
    clsid = probe.get("clsid")
    app: Any
    if clsid:
        app = _create_specific_app(comtypes_client, progid=backend.progid, clsid=clsid)
    else:
        app = _create_specific_app(comtypes_client, backend.progid)
    # Stash the chosen progid on the live COM app so _export_slide_pngs_com
    # can evict _PROBE_CACHE[progid] when this task finishes (see the
    # comment there). The cache must NOT outlive a successful export —
    # probe-Quit plus a same-process next-task CreateObject sits inside
    # the COM-registration teardown race window, and the cache stops us
    # from noticing.
    try:
        app._cosight_ppt_progid = backend.progid  # type: ignore[attr-defined]
    except Exception:
        # COM object may be frozen / not allow setattr — non-fatal, the
        # export finally block has a fallback that skips eviction.
        pass
    return app


def _create_specific_app(
    comtypes_client: Any,
    progid: str,
    clsid: Optional[str] = None,
    attempt: int = 1,
) -> Any:
    """Create a COM application by ProgID (or CLSID) with retry-on-transient.

    When ``clsid`` is supplied we use ``CreateObject(GUID(clsid))`` to
    bypass the buggy ProgID -> CLSID lookup that fires on 64-bit Python
    against 32-bit WPS.

    Retry strategy (3 attempts max):
      - CoInit-class HRESULTs (``_COINIT_RETRY_HRESULTS``) → evict probe
        cache, reinit STA apartment, sleep 1s, retry.
      - Orphan-class HRESULTs (``_ORPHAN_RETRY_HRESULTS``) → kill orphan
        POWERPNT/WPP, sleep 2-4s (server fault sleeps longer), retry.
      - Any other recognised HRESULT (E_FAIL, RPC_E_*, OOM, STG_E_* …)
        → assume the COM server is just temporarily flaky (probe had
        already proven the ProgID is bindable), kill orphan + sleep +
        retry. This is the "give COM one more chance" path added after
        seeing V0.0.14 fall back to LibreOffice on transient errors that
        would have cleared on a second attempt.
      - hr is None AND the exception is an OSError → one generic retry,
        then give up.
      - Anything else → propagate immediately (programming bugs must not
        be papered over).

    Sleeps between attempts scale 2s/4s so worst-case extra latency
    before falling back is ~6s. Acceptable because LibreOffice renders
    SmartArt / connectors / gradients / CJK fonts worse than
    PowerPoint/WPS native export.
    """
    def _try_create() -> Any:
        if clsid:
            from comtypes import GUID  # type: ignore
            return comtypes_client.CreateObject(GUID(clsid))
        return comtypes_client.CreateObject(progid)

    try:
        return _try_create()
    except Exception as e:
        logger.warning(
            f"ppt_slide_extractor: {progid} _create_specific_app caught "
            f"type={type(e).__name__} args={e.args!r} "
            f"hresult_attr={getattr(e, 'hresult', 'NO_ATTR')!r}"
        )
        hr32 = _extract_hresult(e)

        # CoInit-class errors: probe-Then-Real-Create race. We must
        # reinit the STA apartment and evict the probe cache so the
        # retry is forced to re-probe (rather than trusting a stale
        # [OK] verdict). Limited to a single attempt because STA
        # reinit only helps once per session.
        if hr32 in _COINIT_RETRY_HRESULTS:
            logger.warning(
                f"ppt_slide_extractor: {progid} CoInitialize-required error "
                f"0x{hr32:08X}; evicting stale probe cache, reinitializing "
                f"COM as STA, sleeping to clear the probe-Quit race window, "
                f"and retrying"
            )
            _PROBE_CACHE.pop(progid, None)
            if _ensure_sta_apartment():
                time.sleep(_COINIT_RACE_SETTLE_SEC)
                try:
                    return _try_create()
                except Exception:
                    # Second failure on this path means the COM subsystem
                    # is genuinely broken; let the caller fall back to
                    # LibreOffice rather than retrying again.
                    raise
            logger.warning(
                f"ppt_slide_extractor: {progid} _ensure_sta_apartment failed; "
                f"propagating original error"
            )
            raise

        # Orphan-class errors: COM server is sick (zombie / crashed /
        # unresponsive). Kill the PPT-family process, evict the probe
        # cache so the next attempt re-probes (a fresh probe is much
        # less likely to race against a real CreateObject), sleep, and
        # retry. Server-fault retries sleep longer because the COM
        # server actually crashed and Windows needs time to recycle it.
        if hr32 in _ORPHAN_RETRY_HRESULTS:
            settle = 4.0 if hr32 == 0x80080005 else 2.0
            if attempt >= _MAX_CREATE_ATTEMPTS:
                logger.warning(
                    f"ppt_slide_extractor: {progid} orphan-recoverable error "
                    f"0x{hr32:08X}; giving up after {attempt} attempts, "
                    f"falling back to LibreOffice"
                )
                raise
            logger.warning(
                f"ppt_slide_extractor: {progid} orphan-recoverable error "
                f"0x{hr32:08X} attempt {attempt}/{_MAX_CREATE_ATTEMPTS}; "
                f"killing orphan PPT-family process, evicting probe cache, "
                f"sleeping {settle:.1f}s"
            )
            _kill_orphan_office()
            _PROBE_CACHE.pop(progid, None)
            time.sleep(settle)
            return _create_specific_app(
                comtypes_client, progid, clsid=clsid, attempt=attempt + 1,
            )

        # Generic transient path: probe proved the ProgID is bindable, so
        # any unrecognised HRESULT is almost certainly a transient server
        # hiccup (RPC_E_*, E_FAIL, OOM, STG_E_*, …). Killing orphans and
        # giving the COM subsystem a moment almost always rescues the call.
        # Three attempts with exponentially-growing sleeps.
        if attempt >= _MAX_CREATE_ATTEMPTS:
            hr_text = f"0x{hr32:08X}" if hr32 is not None else "no-HRESULT"
            logger.warning(
                f"ppt_slide_extractor: {progid} transient error {hr_text}; "
                f"giving up after {attempt} attempts, falling back to "
                f"LibreOffice"
            )
            raise

        if hr32 is None:
            # No HRESULT in the exception. Only retry when it looks
            # COM-shaped (OSError/COMError); other exception types are
            # almost certainly programming bugs that retrying won't help.
            if not isinstance(e, (OSError,)):
                raise
        settle = _GENERIC_SETTLE_SEC * (2 ** (attempt - 1))
        hr_text = f"0x{hr32:08X}" if hr32 is not None else "no-HRESULT"
        logger.warning(
            f"ppt_slide_extractor: {progid} transient error {hr_text} "
            f"attempt {attempt}/{_MAX_CREATE_ATTEMPTS}; killing orphan "
            f"PPT-family process, evicting stale probe cache, and "
            f"sleeping {settle:.1f}s before retry"
        )
        _kill_orphan_office()
        _PROBE_CACHE.pop(progid, None)
        time.sleep(settle)
        return _create_specific_app(
            comtypes_client, progid, clsid=clsid, attempt=attempt + 1,
        )


def _ensure_sta_apartment() -> bool:
    """Make sure the current thread has an STA COM apartment.

    Called from the worker sub-process when CreateObject fails with one of
    the "COM not initialized" HRESULTs (RPC_E_NO_CALL_ACTIVE etc.).
    comtypes' import-time init only initializes the main thread once, and
    on a persistent worker that init may have been undone by an earlier
    CoUninitialize or may never have happened on the thread that ends up
    running the COM call. Re-initializing as STA is the canonical fix.

    Returns True when the apartment is now STA and CreateObject can be
    retried; False when re-initialization itself failed (rare — usually
    RPC_E_CHANGED_MODE if a different model was already set; in that case
    the existing apartment is still usable).
    """
    try:
        import comtypes  # type: ignore
    except ImportError:
        return False
    try:
        # COINIT_APARTMENTTHREADED (=2) is what PowerPoint/WPS require.
        # comtypes 1.x exposes CoInitializeEx as a module-level helper.
        comtypes.CoInitializeEx(getattr(comtypes, "COINIT_APARTMENTTHREADED", 2))
        return True
    except Exception as e:
        # RPC_E_CHANGED_MODE 0x80010106 / S_FALSE are fine — the apartment
        # is already set up, just not by us. Any other failure: bail.
        hr = getattr(e, "hresult", None)
        if hr is None:
            hr = getattr(e, "args", [None])[0]
        if hr is not None and (hr & 0xFFFFFFFF) in (0x00000001, 0x80010106):
            return True
        logger.warning(
            f"ppt_slide_extractor: CoInitializeEx failed: "
            f"{type(e).__name__}: {e}"
        )
        return False
