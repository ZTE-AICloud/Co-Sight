"""统一分页体：``{items,total,page,pageSize}``。

所有分页端点都从这里构造，避免「有的叫 data、有的叫 result、有的叫 totalCount」
再次分叉。``extra`` 用于少数带额外字段的响应（如单文档切片的 ``nameChain``）。
"""

from __future__ import annotations

from typing import Any, Iterable


def page(items: Iterable[Any], total: int, page_no: int, page_size: int,
         **extra: Any) -> dict:
    return {
        'items': list(items),
        'total': int(total),
        'page': int(page_no),
        'pageSize': int(page_size),
        **extra,
    }
