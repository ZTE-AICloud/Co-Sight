"""JSON 小工具。

**`json_unescape_dumps` 的函数体保持原样，不要动。**
"""
import json


def json_unescape_dumps(content: str) -> str:
    escape = "unicode_escape"
    return json.dumps(content, ensure_ascii=False).encode(escape).decode(escape)
