"""pypdfium2 书签 API 兼容层（4.x 属性式 / 5.x 方法式）。

pypdfium2 未锁版本，镜像里已是 5.x：

* 4.x：``PdfDocument.get_toc()`` 产出对象带 ``title`` / ``page_index`` 属性，
  ``level`` 也是属性；
* 5.x：``title`` 变成 ``get_title()``，页码藏在 ``get_dest().get_index()`` 里
  （目标缺失时 ``get_dest()`` 返回 ``None``），``level`` 仍是属性。

两套写法都在这里收口，调用点不再直接摸书签字段。不要 import 本模块之外的解析依赖——
它是轻量测试的目标。
"""

from __future__ import annotations

from typing import Any


def bookmark_title(item: Any) -> str:
    """书签标题。5.x 用 ``get_title()``，4.x 读 ``title`` 属性。"""
    getter = getattr(item, 'get_title', None)
    if callable(getter):
        return getter()
    return getattr(item, 'title', '')


def bookmark_level(item: Any) -> int:
    """零基层级（两代 API 都是 ``level`` 属性）。"""
    return int(getattr(item, 'level', 0) or 0)


def bookmark_page_index(item: Any) -> int:
    """零基页码。5.x 从 ``get_dest().get_index()`` 取；目标缺失时回落 0。"""
    getter = getattr(item, 'get_dest', None)
    if callable(getter):
        dest = getter()
        index_getter = getattr(dest, 'get_index', None)
        if callable(index_getter):
            return int(index_getter())
    return int(getattr(item, 'page_index', 0) or 0)
