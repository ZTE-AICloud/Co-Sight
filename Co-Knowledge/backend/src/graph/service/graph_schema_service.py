"""图谱模板域（``/graph/schema/*``，6 个端点）。

## 三个「写错就会错」的点

1. **``/list`` 与 ``/detail`` 的字段命名不一样**：``/list`` 返回 ``GraphSchemaVO``，
   **camelCase**（``schemaId``/``schemaName``/…，Vue 页面读的就是 ``s.schemaName``）；
   ``/detail`` 返回 ``GraphSchemaDetailVO``，**snake_case**（``schema_id``/``entities``/…）。
   同一个域两种风格，别"顺手统一"。

2. **``POST /create`` 不传 ``schema_id`` 会 500** —— ``graphSchemaObj`` 上生成了 UUID，
   却把 **DTO 的** ``schemaId``（可能是 null）绑进 INSERT，撞 ``NOT NULL`` 约束。
   这里保持一致（PG 会抛 23502 → 0001）。**不要"顺手修好"**：修了就和现网行为不一致了。

3. **校验器的长度文案与代码不符**：``validateSchemaName`` 的文案写"1-30"，
   实际判的是 **1-99**；``validateClassType`` 的正则 ``^[A-Za-z]*$`` 会**拒绝数字**，
   而文案写的是"首字母必须为字母"。**以实现为准**，文案保持一致。

## 权限

``/list`` 与 ``/delete`` 会调 ``naePermissionClient.getAuthorization(...)`` 判断是否管理员；
本部署里 ``msb.authority.nae-commoncomponent`` 未配置，该调用**必然抛异常 → 返回 false**
（``PermissionFeignClientService`` 的行为）。所以实际生效的是：

* ``/list``：永远按 ``created_by = 当前用户`` 过滤（租户条件仅在 ``X-Org-Id`` 非空时加）
* ``/delete``：只有创建者本人能删

这里「不加权限/鉴权」，但这两条是**服务层业务逻辑**（不是那个 AOP 切面），
保持实现；管理员分支在本部署下不可达，保留代码位置并注明。
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from typing import Optional

from shared.errors.api import KbApiError, KbServerError
from shared.i18n.messages import render
from graph.repository import graph_schema_store

# ``GraphSchemaServiceImpl`` 的常量
FILE_SIZE_OF_1_MB = 1024 * 1024
MAX_ZIP_FILE_SIZE_OF_MB = 1
MAX_EXTRACT_SIZE_OF_MB = 10

SCHEMA_NAME_MAX = 99          # 注意：文案写的是 30，代码判的是 99
CLASS_TYPE_MAX = 63
PROPERTY_NAME_MAX = 63
DESC_MAX = 1000
SCHEMA_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_一-龥]+$')
CLASS_TYPE_PATTERN = re.compile(r'^[A-Za-z]*$')
PROPERTY_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')

# ``GraphPropertyTypeEnum`` —— **没有 ``INT``**，32 位整型是 ``INTEGER``
PROPERTY_TYPES = frozenset((
    'BOOLEAN', 'BYTE', 'SHORT', 'INTEGER', 'LONG', 'FLOAT', 'DOUBLE', 'DATE', 'DATETIME',
    'STRING', 'BINARY', 'EMBEDDED', 'EMBEDDEDLIST', 'EMBEDDEDSET', 'EMBEDDEDMAP',
    'LINK', 'LINKLIST', 'LINKSET', 'LINKMAP',
))

# ``GraphSchemaValidator.SQL_RESERVED_KEYWORDS``，完全一致
SQL_RESERVED_KEYWORDS = frozenset("""
ORDER GROUP AS AND OR FROM WHERE SELECT INSERT UPDATE DELETE CREATE DROP ALTER
TABLE INDEX VIEW JOIN INNER LEFT RIGHT FULL OUTER ON HAVING DISTINCT UNION
INTERSECT EXCEPT LIMIT OFFSET NULL TRUE FALSE IS NOT IN EXISTS BETWEEN LIKE
CASE WHEN THEN ELSE END CAST COUNT SUM AVG MAX MIN IF ELSEIF WHILE FOR DO
BEGIN VERTEX EDGE
""".split())

# 声明顺序（序列化按它输出；构造 dict 时保持一致）
SCHEMA_OBJ_KEYS = ('schema_id', 'schema_name', 'schema_desc', 'entities', 'edges')
ENTITY_KEYS = ('entity_type', 'entity_desc', 'properties')
ENTITY_PROPERTY_KEYS = ('name', 'type', 'desc', 'is_primary', 'is_embedding', 'is_index')
EDGE_KEYS = ('edge_type', 'edge_desc', 'direction', 'source_entity', 'target_entity', 'properties')
EDGE_PROPERTY_KEYS = ('name', 'type', 'desc', 'is_embedding', 'is_index')


# ----------------------------------------------------------------------
# 校验器
#
# 每条都返回文案键 + 参数，由最外层按请求语言渲染，对外文案一致。
# ----------------------------------------------------------------------


def validate_graph_schema_obj(schema: dict) -> None:
    """``validateGraphSchemaObj``：名字 → 描述 → 实体 → 边。"""
    validate_schema_name(schema.get('schema_name'))
    validate_desc(schema.get('schema_desc'))
    validate_schema_entities(schema.get('entities'))
    validate_schema_edges(schema.get('edges'), schema.get('entities'))


def validate_schema_name(name: Optional[str]) -> None:
    if name is None:
        raise KbApiError('RetCode.graph.schema.name.invalid.chars')
    length = len(name)
    if length < 1 or length > SCHEMA_NAME_MAX:
        raise KbApiError('RetCode.graph.schema.name.invalid.length', length, 1, SCHEMA_NAME_MAX)
    if not SCHEMA_NAME_PATTERN.match(name):
        raise KbApiError('RetCode.graph.schema.name.invalid.chars')


def validate_desc(desc: Optional[str]) -> None:
    """实体/边/模板的描述共用这一条。"""
    if desc is None:
        raise KbApiError('RetCode.graph.schema.desc.null')
    length = len(desc)
    if length < 1 or length > DESC_MAX:
        raise KbApiError('RetCode.graph.schema.desc.invalid.length', length, 1, DESC_MAX)
    if not desc.strip():
        raise KbApiError('RetCode.graph.schema.desc.invalid.chars')


def validate_class_type(class_type: Optional[str]) -> None:
    """``validateClassType``：实体类型与边类型共用。

    ⚠️ 正则 ``^[A-Za-z]*$`` **不含数字**，所以 ``Person2`` 会被拒 —— 文案却说"首字母必须为字母"。
    以实现为准。
    """
    if class_type is None:
        raise KbApiError('RetCode.graph.schema.entity_type.null')
    length = len(class_type)
    if length < 1 or length > CLASS_TYPE_MAX:
        raise KbApiError('RetCode.graph.schema.entity_type.invalid.length',
                         length, 1, CLASS_TYPE_MAX)
    if not CLASS_TYPE_PATTERN.match(class_type):
        raise KbApiError('RetCode.graph.schema.entity_type.invalid.chars_or_start', class_type)
    if class_type.upper() in SQL_RESERVED_KEYWORDS:
        raise KbApiError('RetCode.graph.schema.entity_type.reserved', class_type)


def validate_property_name(name: Optional[str], null_key: str, reserved_key: str,
                           length_key: str, chars_key: str) -> None:
    if name is None:
        raise KbApiError(null_key)
    length = len(name)
    if length < 1 or length > PROPERTY_NAME_MAX:
        raise KbApiError(length_key, length, 1, PROPERTY_NAME_MAX)
    if not PROPERTY_NAME_PATTERN.match(name):
        raise KbApiError(chars_key)
    if name.upper() in SQL_RESERVED_KEYWORDS:
        raise KbApiError(reserved_key, name)


def validate_property_type(prop_type: Optional[str]) -> None:
    if prop_type is None:
        raise KbApiError('RetCode.graph.schema.entity.property.type.null')
    if prop_type not in PROPERTY_TYPES:
        raise KbApiError('RetCode.graph.schema.entity.property.type.invalid', prop_type)


def validate_schema_entities(entities: Optional[list]) -> None:
    if not entities:
        raise KbApiError('RetCode.graph.schema.entities.not.empty')

    seen: set[str] = set()
    for entity in entities:
        entity_type = entity.get('entity_type')
        if entity_type in seen:
            raise KbApiError('RetCode.graph.schema.entities.duplicate.entity_type', entity_type)
        seen.add(entity_type)

    for entity in entities:
        entity_type = entity.get('entity_type')
        validate_desc(entity.get('entity_desc'))
        validate_class_type(entity_type)
        validate_entity_properties(entity.get('properties'), entity_type)


def validate_entity_properties(properties: Optional[list], entity_type: Optional[str]) -> None:
    if not properties:
        raise KbApiError('RetCode.graph.schema.entity.property.not.empty', entity_type)

    seen: set[str] = set()
    for prop in properties:
        name = prop.get('name')
        if name in seen:
            raise KbApiError('RetCode.graph.schema.entity.property.duplicate.name', name, entity_type)
        seen.add(name)

    # 至少要有一个主键（只有显式 True 才算）
    if not any(prop.get('is_primary') is True for prop in properties):
        raise KbApiError('RetCode.graph.schema.entity.property.primary.not.found', entity_type)

    for prop in properties:
        validate_property_name(
            prop.get('name'),
            'RetCode.graph.schema.entity.property.name.null',
            'RetCode.graph.schema.entity.property.name.reserved',
            'RetCode.graph.schema.entity.property.name.invalid.length',
            'RetCode.graph.schema.entity.property.name.invalid.chars_or_start')
        validate_property_type(prop.get('type'))
        validate_desc(prop.get('desc'))


def validate_schema_edges(edges: Optional[list], entities: Optional[list]) -> None:
    """⚠️ ``edges`` 为 null 时抛 **0001**（没有判空就 for 循环）。

    这里显式抛一个"服务器错误"而不是让它自然空指针 —— 目的是让调用点一眼看出
    对应哪种失败模式。对外都是 0001。
    """
    if edges is None:
        raise KbServerError('edges is null')

    entity_types = [entity.get('entity_type') for entity in (entities or [])]
    seen: set[str] = set()
    for edge in edges:
        key = '%s||%s||%s' % (edge.get('edge_type'), edge.get('source_entity'),
                              edge.get('target_entity'))
        if key in seen:
            raise KbApiError('RetCode.graph.schema.edge.duplicate.type', key)
        seen.add(key)

    for edge in edges:
        source, target = edge.get('source_entity'), edge.get('target_entity')
        if source not in entity_types or target not in entity_types:
            raise KbApiError('RetCode.graph.schema.edge.entity.not.found', source, target)
        validate_desc(edge.get('edge_desc'))
        validate_class_type(edge.get('edge_type'))
        validate_edge_properties(edge.get('properties'), edge.get('edge_type'))


def validate_edge_properties(properties: Optional[list], edge_type: Optional[str]) -> None:
    """⚠️ 边属性为 null/空是**允许**的（提前返回）。

    ``RetCode.graph.schema.edge.property.not.empty`` 这个键在 properties 里有，但**从不抛出**。
    """
    if not properties:
        return

    seen: set[str] = set()
    for prop in properties:
        name = prop.get('name')
        if name in seen:
            raise KbApiError('RetCode.graph.schema.edge.property.duplicate.name', name, edge_type)
        seen.add(name)

    for prop in properties:
        validate_property_name(
            prop.get('name'),
            'RetCode.graph.schema.entity.property.name.null',
            'RetCode.graph.schema.entity.property.name.reserved',
            'RetCode.graph.schema.entity.property.name.invalid.length',
            'RetCode.graph.schema.entity.property.name.invalid.chars_or_start')
        validate_property_type(prop.get('type'))
        validate_desc(prop.get('desc'))


# ----------------------------------------------------------------------
# 结构转换
# ----------------------------------------------------------------------


def _entity(entity: dict) -> dict:
    return {
        'entity_type': entity.get('entity_type'),
        'entity_desc': entity.get('entity_desc'),
        'properties': None if entity.get('properties') is None else [{
            'name': prop.get('name'),
            'type': prop.get('type'),
            'desc': prop.get('desc'),
            'is_primary': prop.get('is_primary'),
            'is_embedding': prop.get('is_embedding'),
            'is_index': prop.get('is_index'),
        } for prop in entity['properties']],
    }


def _edge(edge: dict) -> dict:
    return {
        'edge_type': edge.get('edge_type'),
        'edge_desc': edge.get('edge_desc'),
        'direction': edge.get('direction'),
        'source_entity': edge.get('source_entity'),
        'target_entity': edge.get('target_entity'),
        'properties': None if edge.get('properties') is None else [{
            'name': prop.get('name'),
            'type': prop.get('type'),
            'desc': prop.get('desc'),
            'is_embedding': prop.get('is_embedding'),
            'is_index': prop.get('is_index'),
        } for prop in edge['properties']],
    }


def to_schema_obj(payload: dict) -> dict:
    """把请求 DTO 转成 schema 对象。

    ``entities`` / ``edges`` 缺失时要**保持 None** —— 校验器对 ``edges`` 是直接 for 循环，
    None 会炸成 0001，而 ``[]`` 不会。这个区别是刻意保留的。
    """
    entities = payload.get('entities')
    edges = payload.get('edges')
    return {
        'schema_id': payload.get('schema_id'),
        'schema_name': payload.get('schema_name'),
        'schema_desc': payload.get('schema_desc'),
        'entities': None if entities is None else [_entity(entity) for entity in entities],
        'edges': None if edges is None else [_edge(edge) for edge in edges],
    }


# ----------------------------------------------------------------------
# VO 装配
# ----------------------------------------------------------------------


def _millis(value) -> Optional[str]:
    """timestamptz → 13 位毫秒字符串（前端 ``Number(createTime)`` 的既有契约）。"""
    if value is None:
        return None
    if hasattr(value, 'timestamp'):
        return str(int(value.timestamp() * 1000))
    return str(value)


def _list_vo(row: dict) -> dict:
    """``GraphSchemaVO`` —— **camelCase**（与 detail 的 snake_case 不同）。"""
    return {
        'schemaId': row.get('schema_id'),
        'schemaName': row.get('schema_name'),
        'schemaDesc': row.get('schema_desc'),
        'createTime': _millis(row.get('created_at')),
        'modifyTime': _millis(row.get('updated_at')),
        'createUser': row.get('created_by'),
        'modifyUser': row.get('updated_by'),
        'tenantId': None,
        'status': row.get('status'),
    }


def _detail_vo(row: dict) -> dict:
    """``GraphSchemaDetailVO`` —— **snake_case**，且把 ``schema_obj`` 展开成 entities/edges。"""
    schema_obj = row.get('schema_obj') or {}
    entities = schema_obj.get('entities')
    edges = schema_obj.get('edges')
    return {
        'schema_id': row.get('schema_id'),
        'schema_name': row.get('schema_name'),
        'schema_desc': row.get('schema_desc'),
        'entities': None if entities is None else [{
            'entity_type': entity.get('entity_type'),
            'entity_desc': entity.get('entity_desc'),
            'properties': None if entity.get('properties') is None else [{
                # 注意这里把 JSON 里的 is_primary/is_embedding/is_index 映射成
                # primary/embedding/index（VO 的字段名），输出仍是 is_primary 等
                'name': prop.get('name'),
                'type': prop.get('type'),
                'desc': prop.get('desc'),
                'is_primary': prop.get('is_primary'),
                'is_embedding': prop.get('is_embedding'),
                'is_index': prop.get('is_index'),
            } for prop in entity['properties']],
        } for entity in entities],
        'edges': None if edges is None else [{
            'edge_type': edge.get('edge_type'),
            'edge_desc': edge.get('edge_desc'),
            'direction': edge.get('direction'),
            'source_entity': edge.get('source_entity'),
            'target_entity': edge.get('target_entity'),
            'properties': None if edge.get('properties') is None else [{
                'name': prop.get('name'),
                'type': prop.get('type'),
                'desc': prop.get('desc'),
                'is_embedding': prop.get('is_embedding'),
                'is_index': prop.get('is_index'),
            } for prop in edge['properties']],
        } for edge in edges],
        'create_time': _millis(row.get('created_at')),
        'modify_time': _millis(row.get('updated_at')),
        'create_user': row.get('created_by'),
        'modify_user': row.get('updated_by'),
        'tenant_id': None,
        'status': row.get('status'),
    }


# ----------------------------------------------------------------------
# 端点
# ----------------------------------------------------------------------


def list_schemas(emp_no: Optional[str]) -> list[dict]:
    """``GET /list``。

    管理员分支依赖未配置的 ``nae-commoncomponent``，本部署下**恒为 false**，
    所以永远按 created_by 过滤 —— 见模块 docstring。
    """
    return [_list_vo(row) for row in graph_schema_store.list_by_user(emp_no)]


def schema_detail(schema_id: str) -> dict:
    """``GET /detail/{schema_id}``。"""
    row = graph_schema_store.get_schema_by_id(schema_id)
    if row is None:
        raise KbApiError('RetCode.graph.extract.schema.not.found', schema_id)
    return _detail_vo(row)


def delete_schema(schema_id: str, emp_no: Optional[str], language: str = '') -> dict:
    """``POST /delete/{schema_id}``。

    先查存在性（不存在报「Schema未找到」），再判「管理员或创建者」——
    管理员分支不可达（见 :func:`has_manage_permission`），所以实际是**只有创建者能删**。

    ``message`` 字段是**已经渲染好**的文案（抛之前就渲染），
    所以语言要传进来，不能读模块级状态 —— 那在并发下会串。
    """
    row = graph_schema_store.get_schema_by_id(schema_id)
    if row is None:
        raise KbApiError('RetCode.graph.extract.schema.not.found', schema_id)
    if not has_manage_permission() and emp_no != row.get('created_by'):
        raise KbApiError('Recode.asset.permission.not.allow')

    graph_schema_store.delete_schema_by_id(schema_id)
    schema_name = row.get('schema_name')
    return {
        'schemaId': schema_id,
        'schemaName': schema_name,
        'deleted': True,
        'message': render('RetCode.graph.schema.delete.success', language, schema_name),
    }


def has_manage_permission() -> bool:
    """``naePermissionClient.getAuthorization(...)``。

    对端 ``msb.authority.nae-commoncomponent`` 在本部署**没有配置**，
    ``PermissionFeignClientService`` 在异常时返回 false。这里直接返回 False，
    并把「为什么」写在注释里 —— 而不是假装查了一次权限。
    """
    return False


def create_schema(payload: dict, emp_no: Optional[str], org_id: Optional[str]) -> dict:
    """``POST /create`` → ``{"schema_name": ...}``。

    ⚠️ **刻意保留的一个坏行为**：UUID 生成在 ``graphSchemaObj`` 上，但 INSERT 绑的是
    **DTO 的** ``schema_id``。不传 ``schema_id`` → 空值撞 NOT NULL → 0001。
    这里刻意不复用生成出来的那个 UUID。
    """
    schema_obj = to_schema_obj(payload)
    if not schema_obj.get('schema_id'):
        schema_obj['schema_id'] = str(uuid.uuid4())

    _validate_unique(schema_obj)
    validate_graph_schema_obj(schema_obj)

    graph_schema_store.insert_schema(
        schema_id=payload.get('schema_id'),          # ← DTO 的，不是生成出来的
        schema_name=payload.get('schema_name'),
        schema_desc=payload.get('schema_desc'),
        schema_obj=schema_obj,
        created_by=emp_no,
    )
    return {'schema_name': schema_obj.get('schema_name')}


def update_schema(payload: dict, emp_no: Optional[str]) -> dict:
    """``POST /update``。**没有权限校验**。"""
    schema_id = payload.get('schema_id')
    if not schema_id or not str(schema_id).strip():
        raise KbApiError('RetCode.graph.schema.id.required')

    existing = graph_schema_store.get_schema_by_id(schema_id)
    if existing is None:
        raise KbApiError('RetCode.graph.extract.schema.not.found', schema_id)

    new_name = payload.get('schema_name')
    if existing.get('schema_name') != new_name:
        same_name = graph_schema_store.get_schema_by_name(new_name)
        if same_name is not None and same_name.get('schema_id') != schema_id:
            raise KbApiError('RetCode.graph.schema.name.duplicate', new_name)

    schema_obj = to_schema_obj(payload)
    validate_graph_schema_obj(schema_obj)

    graph_schema_store.update_schema(
        schema_id=schema_id,
        schema_name=new_name,
        schema_desc=payload.get('schema_desc'),
        schema_obj=schema_obj,
        updated_by=emp_no or '',
    )
    return {'schema_name': schema_obj.get('schema_name')}


def _validate_unique(schema_obj: dict) -> None:
    """``validateUniqueSchemaIdAndName``：按 id 与 name **各查一次**。"""
    by_id = graph_schema_store.get_schema_by_id(schema_obj.get('schema_id'))
    by_name = graph_schema_store.get_schema_by_name(schema_obj.get('schema_name'))
    if by_id is not None or by_name is not None:
        raise KbApiError('RetCode.graph.schema.import.duplicate',
                         schema_obj.get('schema_name'), schema_obj.get('schema_id'))


def import_schema(filename: str, content: bytes, emp_no: Optional[str],
                  org_id: Optional[str]) -> dict:
    """``POST /import``（multipart ``schema_file``）。

    包里的每个 ``.json`` 条目是一份完整模板文档（结构同 ``/create``）。
    条目名按 **GBK** 解码 ——
    UTF-8 的非 ASCII 名字会变成乱码，但只要 ``.json`` 后缀还在就照样导入，保持一致。

    **``failedDetails`` 实际上是死的**：``processEachSchemaEntry`` 记完明细就 rethrow，
    所以整个导入是「一个文件失败全批回滚」；成功响应里 ``failedCount`` 恒为 0。
    这里保持同样的行为（不做「跳过坏文件继续」）。
    """
    if len(content) > MAX_ZIP_FILE_SIZE_OF_MB * FILE_SIZE_OF_1_MB:
        raise KbApiError('RetCode.file.size.limit.check', MAX_ZIP_FILE_SIZE_OF_MB)

    success_ids: dict[str, str] = {}
    total_size = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise KbApiError('RetCode.graph.schema.import.failed', filename) from error

    with archive:
        for info in archive.infolist():
            total_size += info.file_size
            if total_size > MAX_EXTRACT_SIZE_OF_MB * FILE_SIZE_OF_1_MB:
                raise KbApiError('RetCode.file.size.limit.check', MAX_EXTRACT_SIZE_OF_MB)
            if info.is_dir():
                continue
            if not _decode_entry_name(info).endswith('.json'):
                continue
            _import_one_entry(archive.read(info), filename, emp_no, org_id, success_ids)

    if not success_ids:
        raise KbApiError('RetCode.graph.schema.import.no.valid.structure')

    return {
        'successCount': len(success_ids),
        'successIds': success_ids,
        'failedCount': 0,
        'failedDetails': [],
    }


def _decode_entry_name(info: zipfile.ZipInfo) -> str:
    """条目名按 GBK 解码。没置 UTF-8 标志位时 Python 给的是 cp437。"""
    if info.flag_bits & 0x800:
        # 作者声明了 UTF-8 —— 这里仍按 GBK 解，会得到乱码。
        # 把 UTF-8 字节按 GBK 重解，结果一致（都可能是乱码，但一样）。
        try:
            return info.filename.encode('utf-8').decode('gbk')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return info.filename
    try:
        return info.filename.encode('cp437').decode('gbk')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _import_one_entry(raw: bytes, filename: str, emp_no: Optional[str],
                      org_id: Optional[str], success_ids: dict) -> None:
    """``processEachSchemaEntry``：解析 → 校验 → 查重 → 落库。"""
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as error:
        raise KbApiError('RetCode.graph.schema.import.failed', filename) from error
    if not isinstance(parsed, dict):
        raise KbApiError('RetCode.graph.schema.import.failed', filename)

    schema_obj = to_schema_obj(parsed)
    validate_graph_schema_obj(schema_obj)

    schema_id = schema_obj.get('schema_id')
    schema_id = schema_id.strip() if isinstance(schema_id, str) and schema_id.strip() \
        else str(uuid.uuid4())
    schema_name = schema_obj.get('schema_name').strip()
    schema_desc = schema_obj.get('schema_desc') or ''
    schema_obj['schema_id'] = schema_id
    schema_obj['schema_name'] = schema_name

    if graph_schema_store.is_schema_exist(schema_id, schema_name):
        raise KbApiError('RetCode.graph.schema.import.duplicate', schema_name, schema_id)

    graph_schema_store.insert_schema(
        schema_id=schema_id,
        schema_name=schema_name,
        schema_desc=schema_desc,
        schema_obj=schema_obj,
        created_by=emp_no,
    )
    success_ids[schema_name] = schema_id
