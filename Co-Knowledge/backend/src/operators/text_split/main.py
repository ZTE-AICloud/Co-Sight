"""文本切分系统算子入口。

``-1`` 与 ``-2`` 原本是两个算子包，
但两者都转调同一个 ``file_split_common``，差别只有参数：

* ``-1`` 默认切分方法：由调用方传 ``maxWordCount`` / ``overlap``；
* ``-2`` 文件内容摘要切分：无参数，沿用引擎默认（512 字、无 overlap）。

``file_split_common`` 的 ``is_chunk_split`` 参数在两侧都未被使用，这里保留调用形态，
不额外引入行为差异。注册表用 ``operator_function`` 区分两个入口。
"""
from parsing.split_common import file_split_common


def file_split(file_path: str):
    """``-2``：文件内容摘要切分（引擎默认参数）。"""
    return file_split_common(file_path, 0, 0, False)


def file_split_with_chunk(file_path: str, maxWordCount: int, overlap: int):
    """``-1``：默认切分方法（参数由调用方给）。"""
    return file_split_common(file_path, maxWordCount, overlap, True)
