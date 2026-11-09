"""文档类型定义（soc_kb_builder 兼容入口）。

单一真相源在 ``common.document_types``；本模块仅为保持 soc_kb_builder 包内
既有 import 路径不动的 re-export shim，禁止在此独立维护内容（两处拷贝已经
发生过一次注释漂移，故收敛）。
"""
from common.document_types import (  # noqa: F401
    EXCEL_DOCUMENT_EXTS,
    IMAGE_EXTS,
    OFFICE_DOCUMENT_EXTS,
    POWERPOINT_DOCUMENT_EXTS,
    SUPPORTED_DOCUMENT_EXTS,
    SUPPORTED_SOURCE_EXTS,
    VISION_DOCUMENT_EXTS,
    WORD_DOCUMENT_EXTS,
)
