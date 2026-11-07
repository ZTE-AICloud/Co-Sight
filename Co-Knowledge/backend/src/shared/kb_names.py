"""知识库检索基名的 scope 后缀处理。

前端把「未发布」组的下拉项存成 ``<库名>|#|dev``（见
``frontend/src/constants/kbase.js`` 的 ``KB_OPTION_KEY_HYPHEN='|#|'`` 与
``KB_PUBLISH_STATUS``）。知识库域与编排域都要剥这个后缀，放在 ``shared``
避免两个领域互相 import。
"""
from __future__ import annotations

SUFFIX_DEV = '|#|dev'
SUFFIX_PUBLISH = '|#|publish'


def drop_scope_suffix(name: str) -> str:
    """去掉知识库名的 scope 后缀（``|#|dev`` / ``|#|publish``）。"""
    for suffix in (SUFFIX_PUBLISH, SUFFIX_DEV):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name
