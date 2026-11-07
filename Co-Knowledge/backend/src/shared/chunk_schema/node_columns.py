"""向量表 / chunk 表的**展开列** ↔ ``metadata`` dict 的唯一映射。

## 背景

``metadata_``（向量表）与 ``metadata``（chunk 表）已**整个展开成物理列**，
不再有 JSON 列，这才算真正"抛弃嵌套的数据格式"。

展开后的 4 个字段：

| 键 | 列型 | 说明 |
|---|---|---|
| ``type`` | ``SMALLINT`` | 0/1，类型位 |
| ``source`` | ``VARCHAR(255)`` | 源文件名（chunk 表本来就有这一列） |
| ``content_expand`` | ``TEXT`` | 新库存 chunkId、老库存真实内容 |
| ``chunk_id`` | ``INT4`` | 切片序号（实测全为整数） |

``pict_info``（图片信息占位）随图片能力退役；``chunk_index``
全库 100% 为空、不是任何读路径的输入，已从物理列与展开字段中移除。
ES 文档的 ``chunk_index`` 由写入时的原始 metadata 提供，不受影响。

## 本模块只做一件事

**行 ↔ dict 的双向映射**，读写两侧共用，避免"读的时候拼键、写的时候漏键"这类漂移。

⚠️ 两条必须守住的不变式：

1. **缺失的键不能凭空出现**：JSON 时代"键不存在"与"键为 null"在响应里是不同的 ——
   前者不出现在 ``metadata`` 里，后者会出现（值为 null）。展开成列后两者都变成 NULL，
   所以 ``metadata_from_row()`` 只收**非 NULL** 的列 —— 与老行为对齐。
2. **类型要原样往返**：``chunk_id`` 存 INT4、读回来是 ``int``（不是 ``"1"``）；
   响应键集因此与改造前逐键相同（有 ``test_kb_api_node_format.py`` 钉住）。
"""

from __future__ import annotations

from typing import Optional

# 展开后的字段。**顺序不是随便排的**：它必须等于原 JSON 里的键序 ——
# ``to_search_doc`` 是把 metadata dict **原样**透给前端的，键序变了响应字节就变了。
# 全库的存储键序都是这一种。
# ``chunk_index`` 全库为空且不是任何读路径的输入，已从物理列与这里一起移除；
# ES 文档的 ``chunk_index`` 由写入时的原始 metadata 提供，不受影响。
EXPANDED_FIELDS = ('source', 'content_expand', 'chunk_id', 'type')


def metadata_from_row(row: dict, prefix: str = '') -> dict:
    """一行（向量表或 chunk 表）→ ``metadata`` dict。

    只收**存在且非 NULL** 的展开列：JSON 时代"键缺失"与"键为 null"在响应里不同，
    前者不出现、后者出现（值为 null）。展开后两者都是 NULL，故一律按"缺失"处理 ——
    与改造前的实际数据一致（实测 288/294 行的 6 个键**都存在且非 null**；
    ``pict_info`` 退役后为 5 个键）。

    ``prefix``：联表查询里展开列会和别的表撞名（例如 ``list_by_file`` 里
    ``REL.id AS chunk_id`` 与向量表的 ``chunk_id`` 列），SQL 侧给展开列加前缀别名，
    这里按同样的前缀取。
    """
    return {name: row[prefix + name] for name in EXPANDED_FIELDS
            if prefix + name in row and row[prefix + name] is not None}


def columns_from_metadata(metadata: Optional[dict]) -> dict:
    """``metadata`` dict → ``{列名: 值}``；缺的键给 ``None``。

    写侧统一走这里：三个写点（入库 / 手工新增 / 编辑）都只传一份 dict，
    列怎么落由本函数决定 —— 不会再出现"外层改了、内层没改"那种双写不同步。
    """
    metadata = metadata or {}
    return {name: metadata.get(name) for name in EXPANDED_FIELDS}
