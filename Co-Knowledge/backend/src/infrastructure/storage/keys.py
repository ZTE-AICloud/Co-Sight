"""知识库文件域的对象键规则。

键布局（相对 ``RKB_KBASE_STORAGE_PATH``）：

* ``core/<fileId 前 4 位>/<fileId>`` —— 上传原文件（``LocalDiskUtil.generateCoreFilePath``）
* ``tmp_preview/<uuid>``             —— 预览/解析中间件
* ``clean/<uuid 前 2 位>/<uuid>``    —— 清洗产物（只在进程内流转）
* ``dump/<文件名>``                  —— 资产包

本地后端把这些键拼到共享卷根下；MinIO 后端把它们当对象名。两边保持同一套键。

⚠️ ``fileId`` 可能来自请求里的 ``appendFileId``（前端可选已有文档），**必须**做字符校验，
否则 ``..`` 会让对象键逃出前缀、在本地后端则会写出卷外。
"""

from __future__ import annotations

import os

#: 单个分量最多这么长（fileId 实际是 32 位 hex / uuid；留足余量）
MAX_COMPONENT_LENGTH = 128
_FORBIDDEN = ('/', '\\', '\x00')


def validate_component(value, label: str = 'id') -> str:
    """校验单个路径分量：不允许空、分隔符、``.``/``..``（防对象键/本地路径逃逸）。

    刻意**不**限制字符集 —— fileId 形态由调用方决定，收紧会拒绝合法 id。
    """
    text = str(value or '')
    if (not text.strip() or len(text) > MAX_COMPONENT_LENGTH or text in ('.', '..')
            or any(char in text for char in _FORBIDDEN)):
        raise ValueError(f'invalid storage {label}: {value!r}')
    return text


def core_key(file_id: str) -> str:
    file_id = validate_component(file_id, 'file id')
    return f'core/{file_id[:4]}/{file_id}'


def tmp_preview_key(tmp_id: str) -> str:
    return f'tmp_preview/{validate_component(tmp_id, "tmp id")}'


def clean_key(clean_id: str) -> str:
    clean_id = validate_component(clean_id, 'clean id')
    return f'clean/{clean_id[:2]}/{clean_id}'


def safe_file_name(file_name) -> str:
    """资产包文件名：只取 basename，保留中文/空格（它只是对象名的一段）。"""
    name = os.path.basename(str(file_name or '').replace('\\', '/')).strip()
    if not name or name in ('.', '..'):
        name = 'unnamed'
    return name


def dump_key(file_name) -> str:
    return f'dump/{safe_file_name(file_name)}'
