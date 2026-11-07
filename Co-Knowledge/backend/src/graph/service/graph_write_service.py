"""图谱实体/边的增删改（``/graph/{entity,edge}/{create,update,delete}``，6 个端点）。

## 四处「照直觉写就会错」的地方

1. **入参校验的文案是内联中文字面量**，所以**恒为中文** ——
   与 ``review`` 那三条一样，不跟 ``Accept-Language`` 走。见 messages.py 的说明。
2. **``entity/create`` 少了 kbase 判空**。别的实/边方法都会先确认库存在（查不到报
   ``RetCode.kbase.not.exist``），只有它直接取 schema —— 库不存在时抛错，被兜底包成
   ``RetCode.graph.entity.create.failed`` + 底层消息。
   也就是说「库不存在」在 create 上是一条**文案很怪的 0005**，不是「知识库不存在」。
3. **``edge/update`` 与 ``edge/delete`` 响应里的 ``sourceId``/``targetId`` 是 RID**
   （``#12:34``），不是实体 id —— 这里不做 id 提取。
   而 ``edge/create`` 回的是请求里的实体 id。**同一个字段三种含义**，别统一。
4. **属性校验是"白名单"且 schema 没声明属性时不校验**：``schemaProp`` 为空直接放行；
   非空时任何未声明的键都报 ``property.not.defined``。

## 事务

这六个方法有事务，但 **图存储的 REST 调用不参与事务** ——
所以「PG 回滚了、图库已经改了」是固有状态。这里不假装有跨库事务。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from graph.constants import GRAPH_ROW_SYSTEM_FIELDS
from graph.repository import graph_pg
from shared.errors.api import KbApiError
from infrastructure.http import binding
from knowledge_base.service import kbase_service as kbase_store
from graph.models.kg_struct import EdgeData, EntityData
from graph.errors import GraphException
from infrastructure.logging.logutil import log

ID_MAX_LENGTH = 100
ID_SUFFIX_PATTERN = re.compile(r'^[a-zA-Z0-9\-]+$')

ENTITY_SYSTEM_FIELDS = frozenset(('@rid', '@class', '@version', '@type', 'out', 'in',
                                   'entity_id'))
EDGE_SYSTEM_FIELDS = frozenset(('@rid', '@class', '@version', '@type', 'out', 'in', 'edge_id'))

# ``GraphPropertyTypeEnum``（与模板域的校验器同一张表）
PROPERTY_TYPES = frozenset((
    'BOOLEAN', 'BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE', 'DATE', 'DATETIME',
    'STRING', 'BINARY', 'EMBEDDED', 'EMBEDDEDLIST', 'EMBEDDEDSET', 'EMBEDDEDMAP',
    'LINK', 'LINKLIST', 'LINKSET', 'LINKMAP',
))
_INTEGRAL_TYPES = (int,)


# ----------------------------------------------------------------------
# 公共：kbase / schema
# ----------------------------------------------------------------------


def _kbase(kb_id: Optional[str]) -> Optional[dict]:
    if not kb_id or not str(kb_id).strip():
        # DTO 上的 @NotBlank 先拦；这里兜底 —— **恒为中文**
        raise KbApiError('知识库ID不能为空', code='0004')
    return kbase_store.get_kbase_row(str(kb_id))


def _require_kbase(kb_id: str) -> dict:
    """``getKbasePO``：查不到报「知识库不存在」（**跟随请求语言**）。"""
    kbase = _kbase(kb_id)
    if kbase is None:
        raise KbApiError('RetCode.kbase.not.exist')
    return kbase


def _schema_obj(kbase: dict) -> Optional[dict]:
    raw = (kbase or {}).get('schema_obj')
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _entity_definitions(schema_obj: dict) -> Optional[list]:
    entities = schema_obj.get('entities')
    return entities if isinstance(entities, list) else None


def _edge_definitions(schema_obj: dict) -> Optional[list]:
    edges = schema_obj.get('edges')
    return edges if isinstance(edges, list) else None


def _schema_properties(definition: dict) -> dict:
    """``extractSchemaProperties``：``properties`` 既可能是 List 也可能是 Map。

    实体/边的**写**服务支持两种形态（读服务只认 List）—— 这里照做。
    """
    properties = definition.get('properties')
    if isinstance(properties, list):
        return {prop.get('name'): prop for prop in properties if prop.get('name')}
    if isinstance(properties, dict):
        return {name: value for name, value in properties.items() if isinstance(value, dict)}
    return {}


# ----------------------------------------------------------------------
# 公共：格式与属性校验
# ----------------------------------------------------------------------


def _validate_id_format(value: Optional[str], kind: str, type_name: str,
                        type_key: str) -> None:
    """实体与边共用的 id 格式校验（四条分支，顺序固定）。"""
    if value is None:
        raise KbApiError(f'RetCode.graph.{kind}.id.format.invalid', type_name)
    if len(value) > ID_MAX_LENGTH:
        raise KbApiError(f'RetCode.graph.{kind}.id.length.exceed', len(value))
    if not value.startswith(type_name + '_'):
        raise KbApiError(f'RetCode.graph.{kind}.id.format.invalid', type_name)
    suffix = value[len(type_name) + 1:]
    if not suffix or not ID_SUFFIX_PATTERN.match(suffix):
        raise KbApiError(f'RetCode.graph.{kind}.id.format.invalid', type_name)


def _find_definition(definitions: Optional[list], type_field: str,
                     type_value: str) -> Optional[dict]:
    for definition in definitions or []:
        if definition.get(type_field) == type_value:
            return definition
    return None


def _validate_entity_type(schema_obj: dict, entity_type: str) -> dict:
    definitions = _entity_definitions(schema_obj)
    if definitions is None:
        raise KbApiError('RetCode.graph.entity.type.not.defined', entity_type)
    definition = _find_definition(definitions, 'entity_type', entity_type)
    if definition is None:
        raise KbApiError('RetCode.graph.entity.type.not.defined', entity_type)
    return definition


def _validate_edge_type(schema_obj: dict, edge_type: str) -> dict:
    definitions = _edge_definitions(schema_obj)
    if definitions is None:
        raise KbApiError('RetCode.graph.edge.type.not.defined', edge_type)
    definition = _find_definition(definitions, 'edge_type', edge_type)
    if definition is None:
        raise KbApiError('RetCode.graph.edge.type.not.defined', edge_type)
    return definition


def _validate_property_value_types(properties: dict, schema_properties: dict,
                                   dimension: str) -> None:
    """``GraphPropertyValueValidator.validatePropertyValueTypes``：**首个不匹配就抛**。

    两边为空都不校验；类型不在枚举里的也不校验（静默放行）。
    """
    if not properties or not schema_properties:
        return
    for name, value in properties.items():
        definition = schema_properties.get(name)
        if not isinstance(definition, dict):
            continue
        declared = definition.get('type')
        if not isinstance(declared, str) or declared not in PROPERTY_TYPES:
            continue
        if value is None:
            continue                        # null 一律接受
        if not _matches_type(declared, value):
            raise KbApiError(f'RetCode.graph.{dimension}.property.type.mismatch',
                             name, declared, value)


def _matches_type(declared: str, value: Any) -> bool:
    if declared == 'STRING':
        return isinstance(value, str)
    if declared == 'BOOLEAN':
        return isinstance(value, bool)
    if declared in ('BYTE', 'SHORT', 'INTEGER', 'LONG'):
        return isinstance(value, _INTEGRAL_TYPES) and not isinstance(value, bool)
    if declared in ('FLOAT', 'DOUBLE'):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared in ('DATE', 'DATETIME'):
        return isinstance(value, str) and _parses_as_date(value, declared)
    if declared == 'BINARY':
        return isinstance(value, (bytes, str))
    if declared in ('EMBEDDED', 'EMBEDDEDMAP', 'LINKMAP'):
        return isinstance(value, dict)
    if declared in ('EMBEDDEDLIST', 'LINKLIST'):
        return isinstance(value, list)
    if declared in ('EMBEDDEDSET', 'LINKSET'):
        return isinstance(value, (list, set))
    if declared == 'LINK':
        return isinstance(value, str)
    return True


def _parses_as_date(value: str, declared: str) -> bool:
    from datetime import datetime

    formats = ('%Y-%m-%d',) if declared == 'DATE' else (
        '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S')
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _validate_entity_properties(schema_obj: dict, entity_type: str, properties: dict) -> None:
    if not properties:
        return
    definition = _validate_entity_type(schema_obj, entity_type)
    schema_properties = _schema_properties(definition)
    if schema_properties:
        for key in properties:
            if key not in schema_properties:
                raise KbApiError('RetCode.graph.entity.property.not.defined', key)
    _validate_property_value_types(properties, schema_properties, 'entity')


def _validate_edge_properties(schema_obj: dict, edge_type: str, properties: dict) -> None:
    if not properties:
        return
    definition = _validate_edge_type(schema_obj, edge_type)
    schema_properties = _schema_properties(definition)
    if schema_properties:
        for key in properties:
            if key not in schema_properties:
                raise KbApiError('RetCode.graph.edge.property.not.defined', key)
    _validate_property_value_types(properties, schema_properties, 'edge')


def _validate_update_properties(schema_obj: dict, type_name: str, properties: dict,
                                kind: str) -> None:
    """``validateUpdateProperties``：系统字段 → 未声明键，两个循环都跑。

    注意 ``schemaProp`` 为空时**第二个循环仍然跑**，于是每个键都会报
    ``property.not.defined``（只有系统字段会因为先命中而报另一条）。
    """
    definition = (_find_definition(_entity_definitions(schema_obj), 'entity_type', type_name)
                  if kind == 'entity'
                  else _find_definition(_edge_definitions(schema_obj), 'edge_type', type_name))
    if definition is None:
        raise KbApiError(f'RetCode.graph.{kind}.type.not.defined', type_name)

    schema_properties = _schema_properties(definition)
    system_fields = ENTITY_SYSTEM_FIELDS if kind == 'entity' else EDGE_SYSTEM_FIELDS
    for key in properties:
        if key in system_fields:
            raise KbApiError(f'RetCode.graph.{kind}.system.field.cannot.update', key)
        if key not in schema_properties:
            raise KbApiError(f'RetCode.graph.{kind}.property.not.defined', key)

    _validate_property_value_types(properties, schema_properties, kind)


# ----------------------------------------------------------------------
# 实体
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# 向量索引同步
#
# 手工增删改实体/边时必须同步 ``graph_<uuid>_vector``；否则手工新增的实体永远
# 召回不到、手工删除的实体仍作为种子。这里做**尽力同步**：
# 索引失败不判死主操作（图存储已成功），但必须记 ERROR + needs_reindex。
# ----------------------------------------------------------------------


def _index_base(kbase: dict) -> Optional[str]:
    table_name = str((kbase or {}).get('table_name') or '')
    return table_name or None


def _clean_properties(properties: dict) -> dict:
    return {
        key: value for key, value in (properties or {}).items()
        if key not in GRAPH_ROW_SYSTEM_FIELDS
        and not str(key).startswith(('out_', 'in_'))
    }


def _embed_one(text: str, model: Optional[str]) -> list[float]:
    from model import gateway as model_gateway

    vectors = model_gateway.embed_many([text], model)
    if len(vectors) != 1:
        raise RuntimeError(f'embedding count mismatch: expected 1, got {len(vectors)}')
    return vectors[0]


def _sync_entity_index(kbase: dict, client, entity_id: str, entity_type: str) -> None:
    from graph.repository import graph_index_store

    base = _index_base(kbase)
    if not base:
        return
    try:
        properties = _clean_properties(
            graph_pg.get_entity_properties(client, entity_type, entity_id))
        record = {'entity_id': entity_id, 'entity_type': entity_type,
                  'properties': properties}
        text = graph_index_store.entity_text(record)
        if not text:
            return
        vector = _embed_one(text, kbase.get('embedding_model'))
        graph_index_store.upsert_vectors(
            base, graph_index_store.KEY_TYPE_ENTITY,
            [(entity_id, text, [entity_type], vector)])
    except Exception:                                              # noqa: BLE001
        log.exception('entity vector sync failed, needs_reindex: kb=%s entity=%s',
                      kbase.get('kbase_id'), entity_id)


def _edge_endpoints(properties: dict) -> tuple[Optional[str], Optional[str]]:
    """响应里的两端：优先业务端点列，缺失时回落到合成字段 ``out``/``in``。"""
    source_id = properties.get('source_id') or graph_pg.extract_entity_id_from_rid(
        properties.get('out'))
    target_id = properties.get('target_id') or graph_pg.extract_entity_id_from_rid(
        properties.get('in'))
    return source_id, target_id


def _sync_edge_index(kbase: dict, client, edge_id: str, edge_type: str,
                     source_id: Optional[str] = None,
                     target_id: Optional[str] = None) -> None:
    from graph.repository import graph_index_store

    base = _index_base(kbase)
    if not base:
        return
    try:
        properties = graph_pg.get_edge_properties(client, edge_type, edge_id)
        source_id = (source_id or properties.get('source_id')
                     or graph_pg.extract_entity_id_from_rid(properties.get('out')))
        target_id = (target_id or properties.get('target_id')
                     or graph_pg.extract_entity_id_from_rid(properties.get('in')))
        record = {'edge_id': edge_id, 'edge_type': edge_type,
                  'source_id': source_id, 'target_id': target_id,
                  'properties': _clean_properties(properties)}
        text = graph_index_store.edge_text(record)
        if not text:
            return
        vector = _embed_one(text, kbase.get('embedding_model'))
        graph_index_store.upsert_vectors(
            base, graph_index_store.KEY_TYPE_EDGE,
            [(graph_index_store.edge_key_id(record), text, [edge_type], vector,
              edge_id, source_id, target_id)])
    except Exception:                                              # noqa: BLE001
        log.exception('edge vector sync failed, needs_reindex: kb=%s edge=%s',
                      kbase.get('kbase_id'), edge_id)


def _delete_entity_index(kbase: dict, entity_id: str) -> None:
    from graph.repository import graph_index_store

    base = _index_base(kbase)
    if not base:
        return
    try:
        graph_index_store.delete_vector_keys(
            base, graph_index_store.KEY_TYPE_ENTITY, [entity_id])
        # 删实体时图存储连带删了相连的边，边向量也要一起清。
        graph_index_store.delete_edge_vectors_touching(base, [entity_id])
    except Exception:                                              # noqa: BLE001
        log.exception('entity vector delete failed, needs_reindex: kb=%s entity=%s',
                      kbase.get('kbase_id'), entity_id)


def _delete_edge_index(kbase: dict, edge_id: Optional[str]) -> None:
    from graph.repository import graph_index_store

    base = _index_base(kbase)
    if not base or not edge_id:
        return
    try:
        graph_index_store.delete_vector_keys(
            base, graph_index_store.KEY_TYPE_EDGE, [str(edge_id)])
    except Exception:                                              # noqa: BLE001
        log.exception('edge vector delete failed, needs_reindex: kb=%s edge=%s',
                      kbase.get('kbase_id'), edge_id)


def _mark_kbase_modified(kb_id: str) -> None:
    """Best-effort publish-state bookkeeping.

    This runs *after* the entity/edge has been written. Letting it raise turns
    a successful write into a reported failure and the user's retry into
    ``entity.already.exists`` — a regression did exactly that.
    Vector-index sync already follows the same "log, don't fail the write"
    rule; keep the two consistent.
    """
    try:
        kbase_store.set_kbase_status_modified(str(kb_id))
    except Exception:                                              # noqa: BLE001
        log.exception('kbase status update failed, needs_review: kb=%s', kb_id)


def create_entity(payload: dict, language: str = '') -> dict:
    """``POST /graph/entity/create``。"""
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.ENTITY_CREATE_FIELDS)
    kb_id = payload.get('kbId')
    entity_id = payload.get('entityId')
    entity_type = payload.get('entityType')
    properties = payload.get('properties')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(entity_id, '实体ID不能为空')
    _require_required(entity_type, '实体类型不能为空')
    _require_required(properties, '实体属性不能为空')

    try:
        # ⚠️ 这条路径**刻意不判 kbase 是否存在**：查不到时直接取 schema → 空指针，
        # 最终是 ``entity.create.failed`` + **空指针自己的消息**。
        # 也就是说「库不存在」在 create 上不是「知识库不存在」，而是一条空指针文案。
        # 这里把那句话**原样保留**（含 ``Cannot invoke "X.y()" because "z" is null``
        # 措辞）—— 它是当前对外可见的内容。运行时换版本时这句可能变，届时同步改。
        kbase = kbase_store.get_kbase_row(str(kb_id)) if kb_id else None
        if kbase is None:
            raise _NullKbaseNpe(
                'Cannot invoke "KbasePO.getSchemaObj()" '
                'because "kbase" is null')
        schema_obj = _schema_obj(kbase)
        if not schema_obj:
            raise KbApiError('RetCode.graph.entity.schema.undefined')

        _validate_entity_type(schema_obj, entity_type)
        _validate_id_format(entity_id, 'entity', entity_type, 'entity_id')

        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if graph_pg.entity_exists(client, entity_type, entity_id):
            raise KbApiError('RetCode.graph.entity.already.exists', entity_id)

        _validate_entity_properties(schema_obj, entity_type, properties or {})

        # Validate the edge **before** the entity write. Otherwise an invalid
        # relationship (wrong node-type pair, bad direction, …) leaves an
        # orphan entity behind while the API reports failure.
        edge_info = payload.get('edgeInfo')
        prepared_edge = (_prepare_edge_for_entity(client, schema_obj, entity_id, edge_info)
                         if edge_info else None)

        graph_pg.add_entity(client, EntityData(entity_id, entity_type, properties or {}))
        _sync_entity_index(kbase, client, entity_id, entity_type)
        if prepared_edge:
            try:
                _write_prepared_edge(client, kbase, prepared_edge)
            except Exception:
                _rollback_created_entity(client, kbase, entity_id, entity_type,
                                         prepared_edge['edge_id'])
                raise

        _mark_kbase_modified(str(kb_id))
        return _entity_response(True, 'RetCode.graph.entity.create.success',
                                entity_id, entity_type, None, language)
    except (KbApiError, GraphException):
        # **业务异常原样上抛**，
        # 不套 *.failed。早先漏了这条，导致所有校验失败的文案都多了个前缀。
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.entity.create.failed', language)


def update_entity(payload: dict, language: str = '') -> dict:
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.ENTITY_UPDATE_FIELDS)
    kb_id = payload.get('kbId')
    entity_id = payload.get('entityId')
    entity_type = payload.get('entityType')
    properties = payload.get('properties')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(entity_id, '实体ID不能为空')
    _require_required(entity_type, '实体类型不能为空')
    _require_required(properties, '更新属性不能为空')

    try:
        kbase = _require_kbase(kb_id)
        schema_obj = _schema_obj(kbase)
        if not schema_obj:
            raise KbApiError('RetCode.graph.entity.schema.undefined')
        _validate_entity_type(schema_obj, entity_type)

        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if not graph_pg.entity_exists(client, entity_type, entity_id):
            raise KbApiError('RetCode.graph.entity.not.exists', entity_id)

        _validate_update_properties(schema_obj, entity_type, properties or {}, 'entity')
        graph_pg.update_entity(client, entity_type, entity_id, properties or {})
        _sync_entity_index(kbase, client, entity_id, entity_type)

        _mark_kbase_modified(str(kb_id))
        return _entity_response(True, 'RetCode.graph.entity.update.success',
                                entity_id, entity_type, None, language)
    except (KbApiError, GraphException):
        # **业务异常原样上抛**，
        # 不套 *.failed。早先漏了这条，导致所有校验失败的文案都多了个前缀。
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.entity.update.failed', language)


def delete_entity(payload: dict, language: str = '') -> dict:
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.ENTITY_DELETE_FIELDS)
    kb_id = payload.get('kbId')
    entity_id = payload.get('entityId')
    entity_type = payload.get('entityType')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(entity_id, '实体ID不能为空')
    _require_required(entity_type, '实体类型不能为空')

    try:
        kbase = _require_kbase(kb_id)
        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if not graph_pg.entity_exists(client, entity_type, entity_id):
            raise KbApiError('RetCode.graph.entity.not.exists', entity_id)

        # 先删边再删点，返回值进响应的 affectedEdges
        affected = graph_pg.delete_edges_by_entity(client, entity_type, entity_id)
        graph_pg.delete_entity(client, entity_type, entity_id)
        _delete_entity_index(kbase, entity_id)

        _mark_kbase_modified(str(kb_id))
        return _entity_response(True, 'RetCode.graph.entity.delete.success',
                                entity_id, entity_type, affected, language)
    except (KbApiError, GraphException):
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.entity.delete.failed', language)


def _prepare_edge_for_entity(client, schema_obj: dict, entity_id: str,
                             edge_info: dict) -> dict:
    """Validate ``createEdgeForEntity`` without writing anything.

    ``currentEntityId`` 的**实体类型从 id 前缀现推**（``Person_001`` → ``Person``）——
    推不出类型就没法查这个实体，报 ``edge.target.not.exists``。
    """
    edge_id = edge_info.get('edgeId')
    edge_type = edge_info.get('edgeType')
    current_entity_id = edge_info.get('currentEntityId')
    direction = edge_info.get('direction') or 'out'

    definitions = _edge_definitions(schema_obj)
    if definitions is None:
        raise KbApiError('RetCode.graph.entity.schema.undefined')
    if _find_definition(definitions, 'edge_type', edge_type) is None:
        raise KbApiError('RetCode.graph.edge.type.not.defined', edge_type)

    _validate_id_format(edge_id, 'edge', edge_type, 'edge_id')

    current_type = graph_pg.extract_entity_type_from_id(current_entity_id)
    if not current_type or not graph_pg.entity_exists(client, current_type, current_entity_id):
        raise KbApiError('RetCode.graph.edge.target.not.exists', current_entity_id)

    if direction == 'out':
        source_id, target_id = entity_id, current_entity_id
    elif direction == 'in':
        source_id, target_id = current_entity_id, entity_id
    else:
        raise KbApiError('RetCode.graph.edge.direction.invalid', direction)

    matched = _validate_edge_node_types(schema_obj, edge_type, source_id, target_id)
    properties = edge_info.get('properties') or {}
    # Both create_edge paths must validate edge properties against the matched
    # definition: skipping it silently stores keys that the schema never declared.
    _validate_edge_properties_for_def(matched, properties)
    return {
        'edge_id': edge_id,
        'edge_type': edge_type,
        'source_id': source_id,
        'target_id': target_id,
        'properties': properties,
    }


def _write_prepared_edge(client, kbase: dict, prepared: dict) -> None:
    graph_pg.add_edge(client, EdgeData(
        prepared['edge_id'], prepared['edge_type'],
        prepared['source_id'], prepared['target_id'], prepared['properties']))
    _sync_edge_index(kbase, client, prepared['edge_id'], prepared['edge_type'],
                     prepared['source_id'], prepared['target_id'])


def _rollback_created_entity(client, kbase: dict, entity_id: str, entity_type: str,
                             edge_id: Optional[str]) -> None:
    """Best-effort compensation when the edge write fails after the entity write."""
    try:
        graph_pg.delete_edges_by_entity(client, entity_type, entity_id)
        graph_pg.delete_entity(client, entity_type, entity_id)
        _delete_entity_index(kbase, entity_id)
        if edge_id:
            _delete_edge_index(kbase, edge_id)
    except Exception:                                              # noqa: BLE001
        log.exception('rollback of created entity failed: entity=%s edge=%s',
                      entity_id, edge_id)


# ----------------------------------------------------------------------
# 边
# ----------------------------------------------------------------------


def create_edge(payload: dict, language: str = '') -> dict:
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.EDGE_CREATE_FIELDS)
    kb_id = payload.get('kbId')
    edge_id = payload.get('edgeId')
    edge_type = payload.get('edgeType')
    source_id = payload.get('sourceId')
    target_id = payload.get('targetId')
    properties = payload.get('properties')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(edge_id, '边ID不能为空')
    _require_required(edge_type, '边类型不能为空')
    _require_required(source_id, '起始实体ID不能为空')
    _require_required(target_id, '结束实体ID不能为空')
    _require_required(properties, '边属性不能为空')

    try:
        kbase = _require_kbase(kb_id)
        schema_obj = _schema_obj(kbase)
        if not schema_obj:
            raise KbApiError('RetCode.graph.edge.schema.undefined')
        _validate_edge_type(schema_obj, edge_type)
        _validate_id_format(edge_id, 'edge', edge_type, 'edge_id')

        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if graph_pg.edge_exists(client, edge_type, edge_id):
            raise KbApiError('RetCode.graph.edge.already.exists', edge_id)

        source_type = graph_pg.extract_entity_type_from_id(source_id)
        if source_type is None:
            raise KbApiError('RetCode.graph.entity.id.invalid', source_id)
        target_type = graph_pg.extract_entity_type_from_id(target_id)
        if target_type is None:
            raise KbApiError('RetCode.graph.entity.id.invalid', target_id)

        if not graph_pg.entity_exists(client, source_type, source_id):
            raise KbApiError('RetCode.graph.edge.source.not.exists', source_id)
        if not graph_pg.entity_exists(client, target_type, target_id):
            raise KbApiError('RetCode.graph.edge.target.not.exists', target_id)

        matched = _validate_edge_node_types(schema_obj, edge_type, source_id, target_id)
        _validate_edge_properties_for_def(matched, properties or {})
        graph_pg.add_edge(client, EdgeData(edge_id, edge_type, source_id, target_id,
                                           properties or {}))
        _sync_edge_index(kbase, client, edge_id, edge_type, source_id, target_id)

        _mark_kbase_modified(str(kb_id))
        return _edge_response(True, 'RetCode.graph.edge.create.success',
                              edge_id, edge_type, source_id, target_id, language)
    except (KbApiError, GraphException):
        # **业务异常原样上抛**，
        # 不套 *.failed。早先漏了这条，导致所有校验失败的文案都多了个前缀。
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.edge.create.failed', language)


def update_edge(payload: dict, language: str = '') -> dict:
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.EDGE_UPDATE_FIELDS)
    kb_id = payload.get('kbId')
    edge_id = payload.get('edgeId')
    edge_type = payload.get('edgeType')
    properties = payload.get('properties')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(edge_id, '边ID不能为空')
    _require_required(edge_type, '边类型不能为空')
    _require_required(properties, '更新属性不能为空')

    try:
        kbase = _require_kbase(kb_id)
        schema_obj = _schema_obj(kbase)
        if not schema_obj:
            raise KbApiError('RetCode.graph.edge.schema.undefined')
        _validate_edge_type(schema_obj, edge_type)

        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if not graph_pg.edge_exists(client, edge_type, edge_id):
            raise KbApiError('RetCode.graph.edge.not.exists', edge_id)

        _validate_update_properties(schema_obj, edge_type, properties or {}, 'edge')
        graph_pg.update_edge(client, edge_type, edge_id, properties or {})

        # ⚠️ 这里回的是 **RID**（不做 id 提取）。
        # PG 后端的 RID 是自增 id 合成的，业务上无意义；改用行上的业务 id。
        updated = graph_pg.get_edge_properties(client, edge_type, edge_id)
        source_id, target_id = _edge_endpoints(updated)
        # 向量行上的两端必须是业务 id（删实体时按它清理），不能是响应里的 RID。
        _sync_edge_index(kbase, client, edge_id, edge_type,
                         updated.get('source_id'), updated.get('target_id'))

        _mark_kbase_modified(str(kb_id))
        return _edge_response(True, 'RetCode.graph.edge.update.success',
                              edge_id, edge_type, source_id, target_id, language)
    except (KbApiError, GraphException):
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.edge.update.failed', language)


def delete_edge(payload: dict, language: str = '') -> dict:
    # 绑定先于校验 —— 与 query 同一套绑定语义，见 infrastructure/http/binding.py 的模块注释
    payload = binding.bind(payload, binding.EDGE_DELETE_FIELDS)
    kb_id = payload.get('kbId')
    edge_id = payload.get('edgeId')
    edge_type = payload.get('edgeType')

    _require_required(kb_id, '知识库ID不能为空')
    _require_required(edge_id, '边ID不能为空')
    _require_required(edge_type, '边类型不能为空')

    try:
        kbase = _require_kbase(kb_id)
        client = graph_pg.new_client(graph_pg.graph_db_name(str(kb_id)))
        if not graph_pg.edge_exists(client, edge_type, edge_id):
            raise KbApiError('RetCode.graph.edge.not.exists', edge_id)

        # 删之前先把 out/in 读出来（同样回 RID）
        properties = graph_pg.get_edge_properties(client, edge_type, edge_id)
        source_id, target_id = _edge_endpoints(properties)
        graph_pg.delete_edge(client, edge_type, edge_id)
        _delete_edge_index(kbase, edge_id)

        _mark_kbase_modified(str(kb_id))
        return _edge_response(True, 'RetCode.graph.edge.delete.success',
                              edge_id, edge_type, source_id, target_id, language)
    except (KbApiError, GraphException):
        raise
    except Exception as error:
        raise _failure(error, 'RetCode.graph.edge.delete.failed', language)


def _validate_edge_node_types(schema_obj: dict, edge_type: str, source_id: str,
                              target_id: str) -> dict:
    """``validateEdgeNodeTypes``：返回**第一个匹配上的定义**（供属性校验用）。

    匹配规则：``source_entity``/``target_entity`` **都为 null 的定义直接跳过**；
    两边都对上才算命中。一个都没命中报 ``node.type.pair.mismatch``。
    """
    definitions = [definition for definition in (_edge_definitions(schema_obj) or [])
                   if definition.get('edge_type') == edge_type]
    if not definitions:
        raise KbApiError('RetCode.graph.edge.type.not.defined', edge_type)

    source_type = graph_pg.extract_entity_type_from_id(source_id)
    if not source_type:
        raise KbApiError('RetCode.graph.edge.source.node.type.invalid',
                         edge_type, source_id, '')
    target_type = graph_pg.extract_entity_type_from_id(target_id)
    if not target_type:
        raise KbApiError('RetCode.graph.edge.target.node.type.invalid',
                         edge_type, target_id, '')

    entity_types = {entity.get('entity_type')
                    for entity in (_entity_definitions(schema_obj) or [])}

    for definition in definitions:
        declared_source = _ref(definition.get('source_entity'))
        declared_target = _ref(definition.get('target_entity'))
        if declared_source is None and declared_target is None:
            continue
        if declared_source == source_type and declared_target == target_type:
            if source_type not in entity_types:
                raise KbApiError('RetCode.graph.edge.source.node.type.undefined',
                                 edge_type, source_type)
            if target_type not in entity_types:
                raise KbApiError('RetCode.graph.edge.target.node.type.undefined',
                                 edge_type, target_type)
            return definition

    raise KbApiError('RetCode.graph.edge.node.type.pair.mismatch',
                     edge_type, source_type, target_type)


def _ref(value) -> Optional[str]:
    """``getStringOrNull``：null 或空串都当「没声明」。"""
    if value is None:
        return None
    text = str(value)
    return text or None


def _validate_edge_properties_for_def(definition: dict, properties: dict) -> None:
    if not properties:
        return
    schema_properties = _schema_properties(definition)
    if schema_properties:
        for key in properties:
            if key not in schema_properties:
                raise KbApiError('RetCode.graph.edge.property.not.defined', key)
    _validate_property_value_types(properties, schema_properties, 'edge')


# ----------------------------------------------------------------------
# 响应与兜底
# ----------------------------------------------------------------------


class _NullKbaseNpe(RuntimeError):
    """占位：语义上对应「库不存在时的空指针」。

    单独定一个类型而不是直接 ``RuntimeError``，是为了让调用点一眼看出
    这就是那种失败模式，而不是一句随便的运行时错误。
    ``_failure`` 会把它包成 ``entity.create.failed`` + 这句话。
    """


def _require_required(value, message: str) -> None:
    """DTO 上的 ``@NotBlank``/``@NotNull`` —— 文案是**内联中文**，恒为中文。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise KbApiError(message, code='0004')


def _failure(error: Exception, key: str, language: str) -> KbApiError:
    """兜底：``0005`` + ``getMessageWithArgs(key, {e.getMessage()})``。

    最终码是 **0005**。业务异常（``KbApiError``）保留自己的本地化文案；
    **未预期异常只进日志**，不把 Python 模块名 / SQL 细节拼进用户提示。
    库不存在时的空指针文案是刻意保留的，单独保留。
    """
    log.exception('graph write failed (%s): %s', key, error)
    if isinstance(error, KbApiError):
        inner = error.render(language)
    elif isinstance(error, _NullKbaseNpe):
        inner = str(error)
    else:
        inner = ''
    return KbApiError(key, inner or '', code='0005')


def _entity_response(success: bool, message_key: str, entity_id: str, entity_type: str,
                     affected_edges: Optional[int], language: str = '') -> dict:
    from shared.i18n.messages import render

    return {
        'success': success,
        'message': render(message_key, language),
        'entityId': entity_id,
        'entityType': entity_type,
        'affectedEdges': affected_edges,
    }


def _edge_response(success: bool, message_key: str, edge_id: str, edge_type: str,
                   source_id: Any, target_id: Any, language: str = '') -> dict:
    from shared.i18n.messages import render

    return {
        'success': success,
        'message': render(message_key, language),
        'edgeId': edge_id,
        'edgeType': edge_type,
        'sourceId': source_id,
        'targetId': target_id,
    }
