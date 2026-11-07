"""图谱数据导入引擎：zip → PostgreSQL 图存储。

对照 ``GraphDataImportServiceImpl``（795 行）。**抽图与导图共用这一份** ——
``/graph/import`` 直接调它，``AsyncGraphExtractServiceV2`` 抽完图也是调到它。

## 两条「不这么做就会静默失败」的地方

1. **端点必须落在「本次实际导入成功」的实体里，而且必须是边声明的那一类。**
   不校验的后果是边的端点指向不存在的实体时仍然「成功」返回 ——
   实测会出现「任务报 COMPLETED edge=2/2，库里 E=0」。
   更隐蔽的是只查 id 存在：``WorksAt`` 声明 ``source_entity=Company`` 而 ``source_id``
   指向一个 Person 时，id 校验会过，但类型不对 —— 同样静默不建边。
2. **导入完要回查一遍**「声称写入成功」的记录。本项目接连出现过三次
   「任务报 COMPLETED 而库里没数据」；回查是最后一道兜底。

## 计数不变量

``total == success + failed``。拒绝路径**也计 total**；重复 ``edge_id``
**完全跳过**（total/success/failed 都不计）。
"""

from __future__ import annotations

import re

import json
import uuid
import zipfile
from typing import Any, Callable, Optional

from graph.constants import GRAPH_TABLE_PREFIX
from graph.repository import graph_pg
from graph.service import graph_common
from graph.repository import graph_import_store as store
from infrastructure.logging.logutil import log

# ``GraphDataImportServiceImpl`` 的常量
VERIFY_BATCH_SIZE = 1000
ENTITIES_ENTRY = 'entities.jsonl'
EDGES_ENTRY = 'edges.jsonl'
NOT_PERSISTED = 'not-persisted'

# ``SAFE_IDENTIFIER``：属性名会被拼进反引号标识符，来自上传的 zip（**不是** schema），
# 所以必须挡一道。`/graph/import` 在 AUTH_MODE=none 下是无需鉴权的入口。
_SAFE_IDENTIFIER = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')


class Counters:
    """``Counters``：四个计数 + 失败明细。"""

    def __init__(self):
        self.total = 0
        self.success = 0
        self.failed = 0
        self.failed_records: list[dict] = []


# ----------------------------------------------------------------------
# 名称归一（``toGraphDbName`` / ``toKbaseId``）
# ----------------------------------------------------------------------


def _strip_import_prefix(kb_index_name: str) -> str:
    for prefix in (store.KB_ID_PREFIX, GRAPH_TABLE_PREFIX):
        if kb_index_name.startswith(prefix):
            return kb_index_name[len(prefix):]
    return kb_index_name


def to_graph_db_name(kb_index_name: str) -> str:
    """``graph_<kbId>`` / 裸 ``<kbId>`` → ``graph_<kbId>``。

    已带 ``graph_`` 前缀的**不重复加**（否则会拼成 ``graph_graph_<id>``）。
    ``kb_index_<kbId>`` 任务 id 已不再受理。
    """
    if kb_index_name is None or not str(kb_index_name).strip():
        raise ValueError('kbIndexName must not be blank')
    name = _strip_import_prefix(str(kb_index_name))
    if name.startswith(GRAPH_TABLE_PREFIX):
        return name
    return f'{GRAPH_TABLE_PREFIX}{name}'


def to_kbase_id(kb_index_name: Optional[str]) -> Optional[str]:
    """取出原始 kbaseId（用来查 ``kb_kbase``）。``graph_<id>`` 也容忍。"""
    if kb_index_name is None:
        return None
    return _strip_import_prefix(str(kb_index_name))


def build_pg_index(kb_index_name: str, zip_path: str,
                   imported: Optional[dict] = None,
                   imported_edges: Optional[dict] = None, *,
                   bulk: bool = False,
                   progress_cb: Optional[Callable[[int], None]] = None) -> dict:
    """导入后的向量化/切片落表（``embeddingEntityAndEdge`` + ``saveChunkData`` 的等价物）。

    表基名取 ``kb_kbase.table_name``（形如 ``graph_<uuid>``）；embedding 模型取该库
    ``embedding_model`` 列 —— **必须与检索时一致**，否则问题向量与库里的向量不可比。

    :param imported: ``{entity_type: {entity_id, ...}}``，导入引擎**实际成功**的集合；
        传入后只对这些记录建向量，避免 PG 指向不存在的实体。
    :param imported_edges: ``{edge_type: {edge_id, ...}}``，同上。
    """
    from model import gateway as model_gateway
    from knowledge_base.service.embedding_dimension import resolve_embedding_dimension
    from graph.repository import graph_index_store
    from knowledge_base.service import kbase_service as kbase_store

    kbase_id = to_kbase_id(kb_index_name)
    row = kbase_store.get_kbase_row(kbase_id) if kbase_id else None
    base = (row or {}).get('table_name') or f'{GRAPH_TABLE_PREFIX}{kbase_id}'
    if not base or base.endswith('None'):
        raise RuntimeError(f'cannot resolve graph table base name from {kb_index_name!r}')
    embedding_model = (row or {}).get('embedding_model')
    return graph_index_store.build_index(
        base=base,
        kbase_id=kbase_id or '',
        zip_path=zip_path,
        embedding_model=embedding_model,
        embed_many=model_gateway.embed_many,
        entity_ids=imported,
        edge_ids=imported_edges,
        dimension=resolve_embedding_dimension(embedding_model),
        bulk=bulk,
        progress_cb=progress_cb,
    )


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------


def _settle_kbase(kb_index_name: str, status: str,
                  reason: Optional[tuple[str, str]] = None) -> None:
    """把导入任务的终态回写到 ``kb_kbase``。

    只更新 ``graph_import_task`` 而不更新库状态，导入完成后库状态会停在 0（已创建）。
    图谱列表因此把“已就绪”显示成“已创建”，用户无法从状态判断导入是否结束。
    """
    from knowledge_base.service import kbase_service as kbase_store

    kbase_id = to_kbase_id(kb_index_name)
    if not kbase_id:
        return
    kbase_store.update_process_with_time(kbase_id, status, 100)
    if reason is not None:
        kbase_store.update_fail_reason(kbase_id, *reason)


def import_from_zip(kb_index_name: str, schema_id: str, zip_path: str,
                    kbase_schema_obj: Optional[dict] = None) -> str:
    """``importFromZip``。返回 taskId。

    **无论成败，返回前任务必为终态**（``COMPLETED`` / ``COMPLETED_WITH_ERRORS`` /
    ``FAILED``）—— 调用方的轮询是无上限的 ``while(true)``，留一个非终态就是死循环。
    """
    db_name = to_graph_db_name(kb_index_name)
    task_id = uuid.uuid4().hex
    # ⚠️ 任务行的 kb_id 保持调用方传来的 ``graph_<kbId>`` ——
    # deleteKbase 是按这个形状删任务行的
    store.create_task(task_id, kb_index_name, schema_id)

    entity, edge = Counters(), Counters()
    try:
        store.update_status(task_id, store.STATUS_PROCESSING)
        log.info('[graph-import] task=%s db=%s schema=%s zip=%s',
                 task_id, db_name, schema_id, zip_path)

        client = graph_pg.new_client(db_name)
        graph_pg.ensure_database_exists(client, db_name)

        schema = load_schema(schema_id, to_kbase_id(kb_index_name), kbase_schema_obj)
        _upsert_knowledge_graph_info(db_name, schema_id, schema)
        imported = import_entities(client, zip_path, schema, entity)
        imported_edges = import_edges(client, zip_path, schema, imported, edge)

        clean = entity.failed == 0 and edge.failed == 0

        # 导入后要向量化检索真正依赖的部分（entities/edges → graph_<uuid>_vector，
        # chunks → graph_<uuid>_chunk + chunk 向量）。失败**不判死整个导入**
        # （图数据仍然可用），但要把任务标成 COMPLETED_WITH_ERRORS 并写明原因 ——
        # 否则图谱检索又会静默返回空。
        index_error = None

        def _on_progress(percent: int) -> None:
            # 5% 一写：整段向量化只在 100 写一次的话，前端永远停在「已创建」。
            store.update_progress(task_id, percent, entity, edge)

        try:
            log.info('[graph-import] task=%s building vectors (bulk=True) '
                     'entities=%s edges=%s', task_id, entity.success, edge.success)
            index_stats = build_pg_index(kb_index_name, zip_path, imported, imported_edges,
                                         bulk=True, progress_cb=_on_progress)
            log.info('[graph-import] task=%s index: %s', task_id, index_stats)
        except Exception as error:                                 # noqa: BLE001
            log.exception('[graph-import] task=%s index build failed', task_id)
            index_error = store.abbrev(f'index build failed: {error}')
            clean = False

        not_persisted = 0
        verify_attempted = True
        try:
            not_persisted = (_count_not_persisted(client, imported, 'entity_id', entity)
                             + _count_not_persisted(client, imported_edges, 'edge_id', edge))
        except Exception as verify_error:                          # noqa: BLE001
            # 校验本身失败不能把导入判死；但也不能假装校验过了
            verify_attempted = False
            log.warning('[graph-import] task=%s post-import verification could not run: %s',
                        task_id, verify_error)

        if not_persisted > 0:
            log.error('[graph-import] task=%s claims %s record(s) that are NOT in graph storage',
                      task_id, not_persisted)
            clean = False
            entity.failed_records.append({
                'id': '<post-import-verification>',
                'error': f'{not_persisted} record(s) reported as succeeded but not found '
                         'in graph storage after import',
            })

        store.update_progress(task_id, 100, entity, edge)
        message = index_error
        if not verify_attempted:
            message = '; '.join(part for part in (message,
                                                  'post-import verification could not run') if part)
        store.update_status(
            task_id,
            store.STATUS_COMPLETED if clean else store.STATUS_COMPLETED_WITH_ERRORS,
            message)
        if clean:
            _settle_kbase(kb_index_name, '5')
        else:
            _settle_kbase(
                kb_index_name, '104',
                ('知识图谱导入完成但有失败记录：' + (message or ''),
                 'Knowledge graph import completed with errors: ' + (message or '')))
    except Exception as error:                                     # noqa: BLE001
        log.exception('[graph-import] task=%s failed', task_id)
        store.update_progress(task_id, 0, entity, edge)
        store.update_status(task_id, store.STATUS_FAILED, store.abbrev(str(error)))
        _settle_kbase(kb_index_name, '104',
                      ('知识图谱导入失败：' + store.abbrev(str(error)),
                       'Knowledge graph import failed: ' + store.abbrev(str(error))))
    return task_id


# ----------------------------------------------------------------------
# 建类
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# 实体 / 边
# ----------------------------------------------------------------------


def import_entities(client, zip_path: str, schema: dict, counters: Counters) -> dict:
    valid_types = {d.get('entity_type') for d in (schema.get('entities') or [])}
    imported: dict[str, set] = {}
    pending: list[tuple] = []

    def flush() -> None:
        if not pending:
            return
        batch = pending[:]
        pending.clear()
        try:
            graph_pg.upsert_entities_bulk(client.dbname, [
                (entity_type, entity_id, properties, labels)
                for entity_type, entity_id, properties, labels, _line in batch])
        except Exception:                                          # noqa: BLE001
            # 整批失败时退回逐行，保持「哪一行坏了」的失败记录语义。
            for entity_type, entity_id, properties, labels, line_no in batch:
                try:
                    graph_pg.upsert_entity(client.dbname, entity_type, entity_id,
                                           properties, labels)
                except Exception as error:                         # noqa: BLE001
                    counters.failed += 1
                    counters.failed_records.append(
                        _failure(entity_id, line_no, 'entity', str(error)))
                    continue
                counters.success += 1
                imported.setdefault(entity_type, set()).add(entity_id)
            return
        counters.success += len(batch)
        for entity_type, entity_id, _properties, _labels, _line in batch:
            imported.setdefault(entity_type, set()).add(entity_id)

    def handle(line_no: int, parsed: dict, _counters: Counters) -> None:
        counters.total += 1
        entity_type = _str(parsed.get('entity_type'))
        if entity_type is None or entity_type not in valid_types:
            counters.failed += 1
            counters.failed_records.append(_failure(
                parsed.get('entity_id'), line_no, 'entity',
                f"entity_type '{entity_type}' is not defined in schema"))
            return
        entity_id = _str(parsed.get('entity_id'))
        if entity_id is None or not entity_id.strip():
            counters.failed += 1
            counters.failed_records.append(
                _failure(None, line_no, 'entity', 'entity_id is missing'))
            return
        raw_props = _as_map(parsed.get('properties'))
        unsafe = _find_unsafe_key(raw_props)
        if unsafe is not None:
            counters.failed += 1
            counters.failed_records.append(_failure(
                entity_id, line_no, 'entity',
                f'illegal property name (must match ^[A-Za-z][A-Za-z0-9_]*$): {unsafe}'))
            return
        pending.append((entity_type, entity_id, raw_props,
                        parsed.get('labels'), line_no))
        if len(pending) >= 500:
            flush()

    _for_each_json_line(zip_path, ENTITIES_ENTRY, handle, counters)
    flush()
    return imported


def import_edges(client, zip_path: str, schema: dict, imported: dict,
                 counters: Counters) -> dict:
    # 同一 edge_type 可有多条定义（source_entity/target_entity 不同），
    # 只要匹配**其中任意一条**即合法。
    # 用 ``{edge_type: def}`` 取字典只剩最后一条，会把其余定义的合法边
    # 全判成 endpoint 不匹配（30 条边的测试包因此被跳过 11 条）。
    by_type: dict[str, list[dict]] = {}
    for definition in schema.get('edges') or []:
        by_type.setdefault(definition.get('edge_type'), []).append(definition)
    imported_edges: dict[str, set] = {}
    seen: set = set()
    pending: list[tuple] = []

    def flush() -> None:
        if not pending:
            return
        batch = pending[:]
        pending.clear()
        try:
            graph_pg.upsert_edges_bulk(client.dbname, [
                (edge_type, edge_id, source_id, target_id, properties, labels)
                for edge_type, edge_id, source_id, target_id,
                properties, labels, _line in batch])
        except Exception:                                          # noqa: BLE001
            for (edge_type, edge_id, source_id, target_id,
                 properties, labels, line_no) in batch:
                try:
                    graph_pg.upsert_edge(client.dbname, edge_type, edge_id,
                                         source_id, target_id, properties, labels)
                except Exception as error:                         # noqa: BLE001
                    counters.failed += 1
                    counters.failed_records.append(
                        _failure(edge_id, line_no, 'edge', str(error)))
                    continue
                counters.success += 1
                imported_edges.setdefault(edge_type, set()).add(edge_id)
            return
        counters.success += len(batch)
        for edge_type, edge_id, _source, _target, _properties, _labels, _line in batch:
            imported_edges.setdefault(edge_type, set()).add(edge_id)

    def handle(line_no: int, parsed: dict, _counters: Counters) -> None:
        edge_id = _str(parsed.get('edge_id'))
        if edge_id is None or not edge_id.strip():
            counters.total += 1
            counters.failed += 1
            counters.failed_records.append(
                _failure(None, line_no, 'edge', 'edge_id is missing'))
            return
        if edge_id in seen:
            # 重复 edge_id **完全跳过**，且不计入 total/success/failed
            log.warning('[graph-import] duplicate edge_id %s, skipped', edge_id)
            return
        seen.add(edge_id)
        counters.total += 1

        edge_type = _str(parsed.get('edge_type'))
        definitions = by_type.get(edge_type) if edge_type else None
        if not definitions:
            counters.failed += 1
            counters.failed_records.append(_failure(
                edge_id, line_no, 'edge',
                f"edge_type '{edge_type}' is not defined in schema"))
            return

        source_id = _str(parsed.get('source_id'))
        target_id = _str(parsed.get('target_id'))
        if source_id is None or target_id is None:
            counters.failed += 1
            counters.failed_records.append(_failure(
                edge_id, line_no, 'edge',
                'edge_id/source_id/target_id must all be present'))
            return

        raw_props = _as_map(parsed.get('properties'))
        unsafe = _find_unsafe_key(raw_props)
        if unsafe is not None:
            counters.failed += 1
            counters.failed_records.append(_failure(
                edge_id, line_no, 'edge',
                f'illegal property name (must match ^[A-Za-z][A-Za-z0-9_]*$): {unsafe}'))
            return

        matched = next(
            (definition for definition in definitions
             if source_id in imported.get(definition.get('source_entity'), set())
             and target_id in imported.get(definition.get('target_entity'), set())),
            None)
        if matched is None:
            declared = ', '.join(
                f"{definition.get('source_entity')}->{definition.get('target_entity')}"
                for definition in definitions)
            counters.failed += 1
            counters.failed_records.append(_failure(
                edge_id, line_no, 'edge',
                f'edge endpoint not present as declared type (declared: {declared}): '
                f'source_id={source_id}, target_id={target_id}'))
            return

        pending.append((edge_type, edge_id, source_id, target_id,
                        raw_props, parsed.get('labels'), line_no))
        if len(pending) >= 500:
            flush()

    _for_each_json_line(zip_path, EDGES_ENTRY, handle, counters)
    flush()
    return imported_edges


# ----------------------------------------------------------------------
# 入库后回查
# ----------------------------------------------------------------------


def _count_not_persisted(client, claimed_by_type: dict, id_field: str,
                         counters: Counters) -> int:
    """把「声称写入成功」的 id 拿去库里查，返回查不到的条数。"""
    missing = 0
    for type_name, ids in claimed_by_type.items():
        id_list = list(ids)
        for start in range(0, len(id_list), VERIFY_BATCH_SIZE):
            chunk = id_list[start:start + VERIFY_BATCH_SIZE]
            present = graph_pg.present_ids(client.dbname, id_field, chunk)
            for entity_id in chunk:
                if entity_id not in present:
                    missing += 1
                    counters.failed_records.append(_failure(
                        entity_id, -1, NOT_PERSISTED,
                        f'reported as succeeded but not found in graph storage '
                        f'({type_name}.{id_field})'))
    return missing


# ----------------------------------------------------------------------
# schema 与杂项
# ----------------------------------------------------------------------


def load_schema(schema_id: str, kbase_id: Optional[str],
                kbase_schema_obj: Optional[dict] = None) -> dict:
    """``loadSchema``：先查 ``graph_schema``，查不到回退 ``kb_kbase.schema_obj``。

    两条来源都存在是因为**不同入口写的表不同**：模板导入写 ``graph_schema``，
    图谱导入与抽取链路写 ``kb_kbase.schema_obj``。
    """
    raw = None
    try:
        raw = graph_common.schema_obj({'schema_obj': _schema_from_table(schema_id)})
    except Exception as error:                                     # noqa: BLE001
        log.info('[graph-import] graph_schema has no usable schema %s (%s), '
                 'falling back to kb_kbase.schema_obj', schema_id, error)

    if not raw and kbase_schema_obj:
        raw = kbase_schema_obj
    if not raw and kbase_id:
        from knowledge_base.service import kbase_service as kbase_store

        row = kbase_store.get_kbase_row(kbase_id)
        if row:
            raw = graph_common.schema_obj(row)

    if not raw:
        raise RuntimeError(f'Schema not found: {schema_id} (kb={kbase_id})')
    return raw


def _schema_from_table(schema_id: str) -> Optional[dict]:
    from graph.repository import graph_schema_store

    row = graph_schema_store.get_schema_by_id(schema_id)
    return row.get('schema_obj') if row else None


def _upsert_knowledge_graph_info(db_name: str, schema_id: str, schema: dict) -> None:
    """``upsertKnowledgeGraphInfo``：幂等登记图谱库（``ON CONFLICT`` 更新）。"""
    from infrastructure.db.kb import connection

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO graph_registry '
                '(kb_id, schema_id, graph_name, graph_desc) '
                'VALUES (%s, %s, %s, %s) '
                'ON CONFLICT (kb_id, schema_id) DO UPDATE SET '
                'graph_name = EXCLUDED.graph_name, graph_desc = EXCLUDED.graph_desc',
                (db_name, schema_id, schema.get('schema_name'),
                 schema.get('schema_desc')))


def _for_each_json_line(zip_path: str, entry_name: str,
                        handler: Callable[[int, dict, Counters], None],
                        counters: Counters) -> None:
    """逐行读 zip 里的 JSONL。坏行计入 failed 而**不中断**。

    条目名是**精确匹配**（``entities.jsonl``）—— 与 ``/graph/import`` 那个
    「按 ``endsWith`` 找 desc.json」的宽松规则不同，别混。条目不存在等价于 0 条。
    """
    try:
        with zipfile.ZipFile(zip_path) as archive:
            if entry_name not in archive.namelist():
                log.info('[graph-import] %s not present in zip, treated as empty', entry_name)
                return
            with archive.open(entry_name) as handle:
                for line_no, raw in enumerate(handle, start=1):
                    line = raw.decode('utf-8').strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except ValueError:
                        counters.total += 1
                        counters.failed += 1
                        counters.failed_records.append(
                            _failure(None, line_no, entry_name, 'Invalid JSON format'))
                        continue
                    handler(line_no, _as_map(parsed), counters)
    except zipfile.BadZipFile as error:
        raise RuntimeError(f'Invalid zip: {error}')


def _failure(record_id: Any, line_no: int, kind: str, error: str) -> dict:
    return {'id': record_id if record_id is not None else f'{kind}_line_{line_no}',
            'error': error}


def _find_unsafe_key(props: dict) -> Optional[str]:
    for key in props:
        if key is not None and not _SAFE_IDENTIFIER.match(str(key)):
            return key
    return None


def _as_map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> Optional[str]:
    return None if value is None else str(value)
