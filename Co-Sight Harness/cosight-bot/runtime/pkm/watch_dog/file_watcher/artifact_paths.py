"""Shared names for generated preprocessor artifact directories."""
from __future__ import annotations


# Markdown under these generated directories is either duplicate content or
# an intermediate artifact and must not be split/indexed a second time.
CHAPTER_ARTIFACT_SUFFIX = "_chapters"
POWERPOINT_SLIDE_SUFFIXES: tuple[str, ...] = (
    "_ppt_slides",
    "_pptx_slides",
    "_pptm_slides",
)
POWERPOINT_CHAPTER_SUFFIXES: tuple[str, ...] = tuple(
    suffix.removesuffix("_slides") + CHAPTER_ARTIFACT_SUFFIX
    for suffix in POWERPOINT_SLIDE_SUFFIXES
)
SCANNED_PAGE_SUFFIXES: tuple[str, ...] = (
    "_pdf_pages",
    "_doc_pages",
    "_docx_pages",
    "_docm_pages",
)

PREPROCESSED_ARTIFACT_SUFFIXES: tuple[str, ...] = (
    "_chapters",
    "_images",
    "_pages",
    *POWERPOINT_SLIDE_SUFFIXES,
)


__all__ = [
    "CHAPTER_ARTIFACT_SUFFIX",
    "POWERPOINT_SLIDE_SUFFIXES",
    "POWERPOINT_CHAPTER_SUFFIXES",
    "SCANNED_PAGE_SUFFIXES",
    "PREPROCESSED_ARTIFACT_SUFFIXES",
]
