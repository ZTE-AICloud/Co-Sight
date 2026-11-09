"""Shared document type definitions for SOC source downloaders."""
from __future__ import annotations

import os
from pathlib import Path


# These are the document formats that the builtin source builders
# are allowed to retain. Macro-enabled Office files are source documents too,
# but archives and images are handled separately. Images are source assets
# retained by the builders, not text-preprocessor inputs.
WORD_DOCUMENT_EXTS: frozenset[str] = frozenset(
    {".doc", ".docx", ".docm"}
)
EXCEL_DOCUMENT_EXTS: frozenset[str] = frozenset(
    {".xls", ".xlsx", ".xlsm"}
)
POWERPOINT_DOCUMENT_EXTS: frozenset[str] = frozenset(
    {".ppt", ".pptx", ".pptm"}
)
OFFICE_DOCUMENT_EXTS: frozenset[str] = frozenset(
    WORD_DOCUMENT_EXTS | EXCEL_DOCUMENT_EXTS | POWERPOINT_DOCUMENT_EXTS
)

SUPPORTED_DOCUMENT_EXTS: tuple[str, ...] = (
    ".pdf",
    ".ppt",
    ".pptx",
    ".pptm",
    ".doc",
    ".docx",
    ".docm",
    ".xls",
    ".xlsx",
    ".xlsm",
)

IMAGE_EXTS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
        ".ico",
        ".heic",
        ".heif",
        ".avif",
    }
)

SUPPORTED_SOURCE_EXTS: frozenset[str] = frozenset(
    {
        *SUPPORTED_DOCUMENT_EXTS,
        *IMAGE_EXTS,
        ".zip",
        ".rar",
        ".7z",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
    }
)
VISION_DOCUMENT_EXTS: frozenset[str] = frozenset(
    {".pdf", *WORD_DOCUMENT_EXTS}
)


def file_extension(name: str | os.PathLike[str]) -> str:
    """Return a lower-case file extension, including the leading dot."""
    return Path(str(name or "")).suffix.casefold()


def is_supported_document_name(name: str | os.PathLike[str]) -> bool:
    """Return whether a name is a directly supported document."""
    return file_extension(name) in SUPPORTED_DOCUMENT_EXTS


def is_supported_source_name(name: str | os.PathLike[str]) -> bool:
    """Return whether a name is a supported document, image, or archive."""
    return file_extension(name) in SUPPORTED_SOURCE_EXTS


__all__ = [
    "WORD_DOCUMENT_EXTS",
    "EXCEL_DOCUMENT_EXTS",
    "POWERPOINT_DOCUMENT_EXTS",
    "OFFICE_DOCUMENT_EXTS",
    "SUPPORTED_DOCUMENT_EXTS",
    "IMAGE_EXTS",
    "SUPPORTED_SOURCE_EXTS",
    "VISION_DOCUMENT_EXTS",
    "file_extension",
    "is_supported_document_name",
    "is_supported_source_name",
]
