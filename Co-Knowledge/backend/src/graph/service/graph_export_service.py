"""``POST /graph/export``（图谱导出，返回 ZIP）。

对照 ``GraphExportServiceImpl``（930 行）+ ``GraphExportControllerV2``。

## 包结构与来源

``desc.json`` / ``schema.json`` / ``entities.jsonl`` / ``edges.jsonl``，
外加**可选**的 ``document_chunk.jsonl``：

============  =========================================================
desc.json     ``{name, id, embedding, desc}``，缩进 2 的 pretty JSON
schema.json   ``kb_kbase.schema_obj`` 原样 pretty 打印
entities.jsonl 一行一个实体，键 ``entity_type``/``entity_id``/``properties``(+``labels``)
edges.jsonl    一行一条边，键 ``edge_id``/``target_id``/``source_id``/``edge_type``/``properties``
document_chunk.jsonl  仅当 ``kb_index.graph_<kbId>_chunk`` 有行时才有
============  =========================================================

## 三条必须保持的行为

1. **错误走 JSON 信封**（HTTP 200），不是 404 —— 前端拿 blob 时先看
   ``blobData.type === 'application/json'`` 再决定是提示还是下载。
2. **schema 里没有 entities 时不是「空文件」，是报错**。``exportEntitiesToFile``
   在 ``entities`` 为空时**直接 return**、不建文件；而 ``exportEdgesToFile`` 两个分支
   都显式 ``createNewFile()``。于是打包阶段 ``Files.copy(entitiesFile)`` 抛
   ``NoSuchFileException`` → 客户端拿到 ``0005 导出失败`` 的信封。
   这是上游的**不对称 copy-paste bug**，保持。
3. **空的图数据不是错误**：图谱库不存在、或某个类 0 行，都产出**空文件**，
   仍然是合法的 200 zip。
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Optional

from infrastructure.http import binding
from graph.constants import GRAPH_ROW_SYSTEM_FIELDS, GRAPH_TABLE_PREFIX
from graph.repository import graph_pg
from shared.errors.api import KbApiError, KbLiteralValidationError
from graph.service import graph_common
from graph.repository import graph_delete_store
from knowledge_base.service import kbase_service as kbase_store
from infrastructure.logging.logutil import log

CATEGORY_KNOWLEDGE_GRAPH = 10

# ``GraphExportServiceImpl.PAGE_SIZE``
PAGE_SIZE = 10000

# ``GraphExportDTO``：只有一个字段，``@NotBlank`` 的 message 是**内联中文字面量**
GRAPH_EXPORT_FIELDS = {'kbId': binding.STRING}

# 与查询/写服务同一份系统字段集合
SYSTEM_FIELDS = GRAPH_ROW_SYSTEM_FIELDS

# ``convertEntityToJson`` / ``convertEdgeToJson`` 要丢掉的键
ENTITY_DROP_KEYS = frozenset(('entity_type', 'entity_id'))
EDGE_DROP_KEYS = frozenset(('edge_id', 'source_id', 'target_id', 'edge_type'))

# ``document_chunk.jsonl`` 的基础键（顺序固定）
CHUNK_BASE_KEYS = ('id', 'source', 'label', 'type', 'table_id',
                   'content_expand', 'table_name', 'chunk_id')


def export_graph(payload: dict) -> tuple[bytes, str]:
    """返回 ``(zip 字节, 文件名)``。错误一律抛 ``KbApiError``（上层装信封）。"""
    payload = binding.bind(payload, GRAPH_EXPORT_FIELDS)
    kb_id = payload.get('kbId')
    if kb_id is None or not str(kb_id).strip():
        # ``@NotBlank(message = "知识库ID不能为空")`` —— 内联字面量，恒中文
        raise KbLiteralValidationError('知识库ID不能为空')

    kbase = kbase_store.get_kbase_row(str(kb_id))
    if kbase is None:
        raise KbApiError('graph.export.kbase.not.found')
    if kbase.get('category') is None or int(kbase['category']) != CATEGORY_KNOWLEDGE_GRAPH:
        raise KbApiError('graph.export.kbase.not.graph')

    schema_obj = graph_common.schema_obj(kbase)
    if not schema_obj:
        raise KbApiError('graph.export.schema.not.found')

    try:
        entries = _build_entries(str(kb_id), kbase, schema_obj)
    except KbApiError:
        raise
    except Exception:
        log.exception('graph export failed for kb_id=%s', kb_id)
        raise KbApiError('graph.export.failed')

    return _zip(entries), f'graph_{kb_id}_{_timestamp()}.zip'


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime('%Y%m%d%H%M%S')


def _build_entries(kb_id: str, kbase: dict, schema_obj: dict) -> dict[str, bytes]:
    """按固定顺序产出五个条目。``entities.jsonl`` **可能缺席**（见模块注释第 2 条）。"""
    entries = {
        'desc.json': _desc_json(kbase),
        'schema.json': _pretty(schema_obj),
    }

    entities = _export_entities(kb_id, schema_obj)
    if entities is not None:
        entries['entities.jsonl'] = entities
    # 边**两个分支都建文件**，所以它一定在场
    entries['edges.jsonl'] = _export_edges(kb_id, schema_obj)

    chunks = _export_document_chunk(kb_id)
    if chunks is not None:
        entries['document_chunk.jsonl'] = chunks
    return entries


def _desc_json(kbase: dict) -> bytes:
    """描述文件：键序 ``name, id, embedding, desc``。"""
    payload = {
        'name': kbase.get('name'),
        'id': f'{GRAPH_TABLE_PREFIX}{kbase.get("kbase_id")}',
        'embedding': kbase.get('embedding_model'),
        'desc': kbase.get('description'),
    }
    return _pretty(payload)


def _pretty(value: Any) -> bytes:
    """格式化 JSON。

    产出的形状（与 Python ``json.dumps(indent=2)`` **不一样**）：

    * 对象：``{\n  "k" : v,\n  "k2" : v2\n}`` —— 键值间是 ``" : "``（带前空格）；空对象 ``{ }``
    * 数组：``[ v1, v2 ]`` —— 括号**贴着**元素、元素间 ``", "``；空数组 ``[ ]``
      （Python 默认会把每个元素单独换行，那样字节级就对不上）
    * **末尾没有换行**（写完就结束，不补 newline）

    数组里的对象照常多行展开，只是数组自己的括号留在同一行。
    """
    return _jackson_pretty(value).encode('utf-8')


def _jackson_pretty(value: Any, indent: int = 0) -> str:
    if isinstance(value, dict):
        if not value:
            return '{ }'
        pad, inner = '  ' * indent, '  ' * (indent + 1)
        entries = ',\n'.join(
            f'{inner}{json.dumps(str(key), ensure_ascii=False)} : '
            f'{_jackson_pretty(item, indent + 1)}'
            for key, item in value.items())
        return f'{{\n{entries}\n{pad}}}'
    if isinstance(value, list):
        if not value:
            return '[ ]'
        return '[ ' + ', '.join(_jackson_pretty(item, indent) for item in value) + ' ]'
    return json.dumps(value, ensure_ascii=False)


# ----------------------------------------------------------------------
# 实体 / 边
# ----------------------------------------------------------------------


def _export_entities(kb_id: str, schema_obj: dict) -> Optional[bytes]:
    """``exportEntitiesToFile``：**没有实体定义时返回 None**（不建文件）。

    这个 ``None`` 就是那个 bug 的载体 —— 打包阶段会转成「导出失败」。
    """
    definitions = schema_obj.get('entities')
    if not definitions:
        return None

    client = graph_pg.new_client(graph_pg.graph_db_name(kb_id))
    if not graph_pg.is_database_exists(client):
        # 图库不存在 → 空文件（不是错误）
        return b''

    lines = []
    for definition in definitions:
        entity_type = definition.get('entity_type')
        if not entity_type:
            continue
        names = _property_names(definition)
        for row in _select_all(client, entity_type, names, entity_kind=True):
            lines.append(_entity_line(entity_type, row, names))
    return _jsonl(lines)


def _export_edges(kb_id: str, schema_obj: dict) -> bytes:
    """``exportEdgesToFile``：**无论有没有边定义都会建文件**（与实体那边不对称）。"""
    definitions = schema_obj.get('edges')
    if not definitions:
        return b''

    client = graph_pg.new_client(graph_pg.graph_db_name(kb_id))
    if not graph_pg.is_database_exists(client):
        return b''

    lines = []
    for definition in definitions:
        edge_type = definition.get('edge_type')
        if not edge_type:
            continue
        names = _property_names(definition)
        for row in _select_all(client, edge_type, names, entity_kind=False):
            lines.append(_edge_line(edge_type, row, names))
    return _jsonl(lines)


def _property_names(definition: dict) -> list[str]:
    """``extractEntityPropertyNames``：``properties[].name``（只认 list 形态）。"""
    properties = definition.get('properties')
    if not isinstance(properties, list):
        return []
    names = []
    for prop in properties:
        if isinstance(prop, dict) and prop.get('name'):
            names.append(prop['name'])
    return names


def _select_all(client, type_name: str, names: list[str], *, entity_kind: bool) -> list[dict]:
    """按类型取全部行（平铺属性）。"""
    rows = (graph_pg.query_vertices(client.dbname, [{'entity_type': [type_name]}], 1_000_000, 0)
            if entity_kind else
            graph_pg.query_edges(client.dbname, [{'edge_type': [type_name]}], 1_000_000, 0))
    for row in rows:
        row['entity_type' if entity_kind else 'edge_type'] = row.get('@class')
    return rows


def _entity_line(entity_type: str, row: dict, names: list[str]) -> dict:
    """``convertEntityToJson``：``entity_type`` / ``entity_id`` / ``properties`` (+``labels``)。"""
    line = {
        'entity_type': entity_type,
        'entity_id': row.get('entity_id'),
        'properties': _filter_properties(row, names, ENTITY_DROP_KEYS),
    }
    labels = row.get('#labels')
    if labels is not None:
        line['labels'] = labels
    return line


def _edge_line(edge_type: str, row: dict, names: list[str]) -> dict:
    """``convertEdgeToJson``：键序 ``edge_id, target_id, source_id, edge_type, properties``。"""
    line = {
        'edge_id': row.get('edge_id'),
        'target_id': row.get('target_id'),
        'source_id': row.get('source_id'),
        'edge_type': edge_type,
        'properties': _filter_properties(row, names, EDGE_DROP_KEYS),
    }
    labels = row.get('#labels')
    if labels is not None:
        line['labels'] = labels
    return line


def _filter_properties(row: dict, names: list[str], drop_keys: frozenset) -> dict:
    """``filterPropertiesBySchema``：丢系统字段、null、以及 id 类键；只留 schema 声明的。

    ⚠️ ``#labels`` **不进 properties**：它只作为**行级**的 ``labels`` 出现
    （``convertEntityToJson`` 单独取 ``row["#labels"]``）。源码里那句
    ``"#labels".equals(key) || ...`` 看着像是要保留，但实测输出里没有 ——
    以实测为准。
    """
    if not names:
        return {}
    allowed = set(names)
    result = {}
    for key, value in row.items():
        if key in SYSTEM_FIELDS or key in drop_keys or value is None:
            continue
        if key in allowed:
            result[key] = value
    return result


def _jsonl(lines: list) -> bytes:
    """``BufferedWriter.write`` + ``newLine()``：UTF-8、``\\n`` 分行、**末尾也有换行**。"""
    if not lines:
        return b''
    # 紧凑分隔符：使用**不带** pretty printer 的 writer，输出
    # ``{"a":1,"b":2}`` 而不是 Python 默认的 ``{"a": 1, "b": 2}``
    return ('\n'.join(json.dumps(line, ensure_ascii=False, separators=(',', ':'))
                       for line in lines) + '\n').encode('utf-8')


# ----------------------------------------------------------------------
# document_chunk.jsonl（可选）
# ----------------------------------------------------------------------


def _export_document_chunk(kb_id: str) -> Optional[bytes]:
    """只有 ``graph_<kbId>_chunk`` 有行时才产出；表不存在/无行 → None（不建文件）。

    ⚠️ 必须读物理列，不能 ``SELECT ... metadata`` —— 该列已不存在，异常又被吞成
    ``None``，导出会永远不含 ``document_chunk.jsonl``。**非「表不存在」的异常
    不再静默**，直接按 ``graph.export.failed`` 让导出失败。
    """
    table = graph_delete_store.chunk_table(kb_id)
    try:
        rows = _chunk_rows(table)
    except Exception as error:                                     # noqa: BLE001
        log.exception('document_chunk export failed for %s', kb_id)
        raise KbApiError('graph.export.failed') from error
    if not rows:
        return None
    return _jsonl([_chunk_line(row) for row in rows])


def _chunk_rows(table: str) -> list[dict]:
    from infrastructure.db.kb import connection
    from infrastructure.db.identifiers import validate_identifier

    schema_name, _, table_name = table.partition('.')
    validate_identifier(table_name)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT EXISTS (SELECT 1 FROM information_schema.tables '
                           'WHERE table_schema = %s AND table_name = %s)',
                           (schema_name or 'kb_index', table_name))
            if not cursor.fetchone()[0]:
                return []
            cursor.execute(
                # 正文去重后新行 content_expand 为 NULL；导出仍要带内容，故回落到 text。
                'SELECT id, source, label, spilt_type, table_id, '
                'COALESCE(content_expand, text) AS content_expand, '
                'table_name, chunk_id, chunk_index, text, chunk_order '
                f'FROM {table} ORDER BY chunk_order')
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _chunk_line(row: dict) -> dict:
    """``convertChunkDataToJson``：八个基础键 + 正文/物理列扩展键。

    基础键顺序与 ``CHUNK_BASE_KEYS`` 一致（响应形状的一部分）；``text`` 等
    扩展键追加在后面，供导入侧 ``replace_chunks`` 还原正文与元数据。
    """
    line = {
        'id': row.get('id'),
        'source': row.get('source'),
        'label': row.get('label'),
        'type': row.get('spilt_type'),
        'table_id': row.get('table_id'),
        'content_expand': row.get('content_expand'),
        'table_name': row.get('table_name'),
        'chunk_id': row.get('chunk_id'),
    }
    for key in ('text', 'chunk_order', 'chunk_index'):
        value = row.get(key)
        if value is not None:
            line[key] = value
    return line


# ----------------------------------------------------------------------
# 打包
# ----------------------------------------------------------------------


def _zip(entries: dict[str, bytes]) -> bytes:
    """与 ``ZipUtil.compress`` 同为 DEFLATED 的 zip。

    ⚠️ zip **不是字节级可复现**：条目的时间戳来自临时文件 mtime，还带 UT/NTFS
    两个扩展字段，同一份数据跑两次都不一定一样。这里只保证**条目集合与内容**一致。
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('desc.json', 'schema.json', 'entities.jsonl',
                     'edges.jsonl', 'document_chunk.jsonl'):
            if name in entries:
                archive.writestr(name, entries[name])
    return buffer.getvalue()
