"""Text2SQL 领域模型：入参校验与「数据库行 → 前端 DTO」映射。

数据库列用 snake_case；接口体用 camelCase，字段名与前端 ``text2sql`` 工作区
一致（``database`` / ``schema`` / ``scannedAt`` / ``selectedTables`` 等）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from text_to_sql.errors import Text2SqlValidationError

SUPPORTED_DB_TYPES = {'postgresql': 'PostgreSQL'}

STATUS_CONFIGURED = 'configured'
STATUS_SCANNED = 'scanned'
STATUS_INDEXED = 'indexed'

SEMANTIC_TYPES = {'identifier', 'measure', 'dimension', 'time', 'category'}

DEFAULT_PORT = 5432
DEFAULT_TIMEZONE = 'UTC'
DEFAULT_MAX_BYTES = 1024 * 1024
#: 只读由执行层强制（只读事务 + AST 白名单），不是可配置项。
DEFAULT_QUERY_POLICY = {'max_rows': 1000, 'timeout_ms': 30000,
                        'max_bytes': DEFAULT_MAX_BYTES}

_MAX_SCHEMAS = 20
_MAX_ALIASES = 20


# ---------------------------------------------------------------------------
# 基础校验
# ---------------------------------------------------------------------------
def _text(value: Any, field: str, *, max_length: int, required: bool = False,
          allow_empty: bool = False) -> Optional[str]:
    if value is None:
        if required:
            raise Text2SqlValidationError(f'{field} 不能为空')
        return None
    if not isinstance(value, str):
        raise Text2SqlValidationError(f'{field} 必须是字符串')
    text = value.strip()
    if not text and not allow_empty:
        if required:
            raise Text2SqlValidationError(f'{field} 不能为空')
        return None
    if len(text) > max_length:
        raise Text2SqlValidationError(f'{field} 长度不能超过 {max_length}')
    return text


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise Text2SqlValidationError(f'{field} 必须是布尔值')
    return value


def _int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Text2SqlValidationError(f'{field} 必须是整数')
    if value < minimum or value > maximum:
        raise Text2SqlValidationError(f'{field} 必须在 {minimum}–{maximum} 之间')
    return value


def _aliases(value: Any, field: str) -> Optional[list[str]]:
    if value is None:
        return None
    if not isinstance(value, list):
        raise Text2SqlValidationError(f'{field} 必须是字符串数组')
    if len(value) > _MAX_ALIASES:
        raise Text2SqlValidationError(f'{field} 最多 {_MAX_ALIASES} 项')
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise Text2SqlValidationError(f'{field} 必须是字符串数组')
        text = item.strip()
        if not text:
            continue
        if len(text) > 100:
            raise Text2SqlValidationError(f'{field} 单项长度不能超过 100')
        if text not in result:
            result.append(text)
    return result


def _schemas(value: Any) -> list[str]:
    if value is None:
        return ['public']
    if not isinstance(value, list) or not value:
        raise Text2SqlValidationError('schemas 必须是非空数组')
    if len(value) > _MAX_SCHEMAS:
        raise Text2SqlValidationError(f'schemas 最多 {_MAX_SCHEMAS} 项')
    result: list[str] = []
    for item in value:
        text = _text(item, 'schemas', max_length=128, required=True)
        if text not in result:
            result.append(text)
    return result


def _timezone(value: Any) -> str:
    name = _text(value, 'businessTimezone', max_length=64) or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise Text2SqlValidationError(f'未知时区：{name}') from error
    return name


def _query_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return dict(DEFAULT_QUERY_POLICY)
    if not isinstance(value, dict):
        raise Text2SqlValidationError('queryPolicy 必须是对象')
    max_rows = _int(value.get('max_rows', DEFAULT_QUERY_POLICY['max_rows']),
                    'queryPolicy.max_rows', minimum=1, maximum=10000)
    timeout_ms = _int(value.get('timeout_ms', DEFAULT_QUERY_POLICY['timeout_ms']),
                      'queryPolicy.timeout_ms', minimum=100, maximum=120000)
    # 单查询结果体的硬上限。行数管不住宽度：1000 行 × 500KB 仍是 500MB。
    max_bytes = _int(value.get('max_bytes', DEFAULT_MAX_BYTES),
                     'queryPolicy.max_bytes', minimum=1024,
                     maximum=16 * 1024 * 1024)
    return {'max_rows': max_rows, 'timeout_ms': timeout_ms,
            'max_bytes': max_bytes}


def _topic(value: Any) -> dict[str, str]:
    if value is None:
        return {'name': '', 'description': '', 'owner': ''}
    if not isinstance(value, dict):
        raise Text2SqlValidationError('topic 必须是对象')
    return {
        'name': _text(value.get('name'), 'topic.name', max_length=60,
                      allow_empty=True) or '',
        'description': _text(value.get('description'), 'topic.description',
                             max_length=2000, allow_empty=True) or '',
        'owner': _text(value.get('owner'), 'topic.owner', max_length=60,
                       allow_empty=True) or '',
    }


# ---------------------------------------------------------------------------
# 写接口入参
# ---------------------------------------------------------------------------
def parse_create_datasource(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    db_type = (_text(payload.get('dbType'), 'dbType', max_length=32) or 'postgresql').lower()
    if db_type not in SUPPORTED_DB_TYPES:
        raise Text2SqlValidationError(f'暂不支持的数据库类型：{db_type}')
    return {
        'name': _text(payload.get('name'), 'name', max_length=128, required=True),
        'db_type': db_type,
        'host': _text(payload.get('host'), 'host', max_length=255, required=True),
        'port': _int(payload.get('port', DEFAULT_PORT), 'port', minimum=1, maximum=65535),
        'database_name': _text(payload.get('database'), 'database', max_length=128,
                               required=True),
        'username': _text(payload.get('username'), 'username', max_length=128,
                          required=True),
        'password': _text(payload.get('password'), 'password', max_length=1024,
                          required=True),
        'include_schemas': _schemas(payload.get('schemas')),
        'topic': _topic(payload.get('topic')),
        'business_description': _text(payload.get('businessDescription'),
                                      'businessDescription', max_length=4000,
                                      allow_empty=True) or '',
        'business_timezone': _timezone(payload.get('businessTimezone')),
        'embedding_model': _text(payload.get('embeddingModel'),
                                 'embeddingModel', max_length=255),
        # SQL 生成模型：空 = 跟随部署默认；与 embedding 不同，不受版本构建锁定。
        'llm_model': _text(payload.get('llmModel'), 'llmModel', max_length=255),
        'query_policy': _query_policy(payload.get('queryPolicy')),
        'enabled': True if payload.get('enabled') is None
        else _bool(payload.get('enabled'), 'enabled'),
    }


def parse_update_datasource(payload: dict[str, Any]) -> dict[str, Any]:
    """PATCH 语义：只返回请求体里出现的字段。``password`` 为空串视为「不修改」。"""
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'name' in payload:
        fields['name'] = _text(payload.get('name'), 'name', max_length=128, required=True)
    if 'dbType' in payload:
        db_type = (_text(payload.get('dbType'), 'dbType', max_length=32) or 'postgresql').lower()
        if db_type not in SUPPORTED_DB_TYPES:
            raise Text2SqlValidationError(f'暂不支持的数据库类型：{db_type}')
        fields['db_type'] = db_type
    if 'host' in payload:
        fields['host'] = _text(payload.get('host'), 'host', max_length=255, required=True)
    if 'port' in payload:
        fields['port'] = _int(payload.get('port'), 'port', minimum=1, maximum=65535)
    if 'database' in payload:
        fields['database_name'] = _text(payload.get('database'), 'database',
                                        max_length=128, required=True)
    if 'username' in payload:
        fields['username'] = _text(payload.get('username'), 'username',
                                   max_length=128, required=True)
    if 'password' in payload:
        password = _text(payload.get('password'), 'password', max_length=1024,
                         allow_empty=True)
        if password:
            fields['password'] = password
    if 'schemas' in payload:
        fields['include_schemas'] = _schemas(payload.get('schemas'))
    if 'topic' in payload:
        fields['topic'] = _topic(payload.get('topic'))
    if 'businessDescription' in payload:
        fields['business_description'] = _text(
            payload.get('businessDescription'), 'businessDescription',
            max_length=4000, allow_empty=True) or ''
    if 'businessTimezone' in payload:
        fields['business_timezone'] = _timezone(payload.get('businessTimezone'))
    if 'embeddingModel' in payload:
        fields['embedding_model'] = _text(payload.get('embeddingModel'),
                                          'embeddingModel', max_length=255)
    if 'llmModel' in payload:
        # 空串是有效输入：清空 = 回到部署默认模型（可随时改，不影响已发布版本）。
        fields['llm_model'] = _text(payload.get('llmModel'), 'llmModel',
                                    max_length=255)
    if 'queryPolicy' in payload:
        fields['query_policy'] = _query_policy(payload.get('queryPolicy'))
    if 'queryExamples' in payload:
        fields['query_examples'] = _query_examples(payload.get('queryExamples'))
    if 'enabled' in payload:
        fields['enabled'] = _bool(payload.get('enabled'), 'enabled')
    return fields


ASSIST_KINDS = ('descriptions', 'tables', 'values', 'relations', 'metrics',
                'questions')


def _query_examples(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 8:
        raise Text2SqlValidationError('queryExamples 必须是不超过 8 项的数组')
    examples: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            question, hint = item, ''
        elif isinstance(item, dict):
            question = _text(item.get('question'), 'question', max_length=200)
            hint = _text(item.get('hint'), 'hint', max_length=200,
                         allow_empty=True) or ''
        else:
            raise Text2SqlValidationError('queryExamples 每一项必须是字符串或对象')
        if not question:
            continue
        examples.append({'question': question, 'hint': hint})
    return examples


def parse_assist(payload: dict[str, Any]) -> dict[str, Any]:
    """AI 辅助请求：kind + 可选表范围 + 是否发送样本。"""
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    kind = _text(payload.get('kind'), 'kind', max_length=16) or ''
    if kind not in ASSIST_KINDS:
        raise Text2SqlValidationError(
            f"kind 必须是 {'/'.join(ASSIST_KINDS)}")
    raw_ids = payload.get('tableIds') or []
    if not isinstance(raw_ids, list) or len(raw_ids) > 50:
        raise Text2SqlValidationError('tableIds 必须是不超过 50 项的数组')
    table_ids = [_uuid_text(item, 'tableIds') for item in raw_ids]
    include_samples = payload.get('includeSamples')
    return {
        'kind': kind,
        'table_ids': table_ids,
        'include_samples': (True if include_samples is None
                            else _bool(include_samples, 'includeSamples')),
        'question': _text(payload.get('question'), 'question',
                          max_length=500, allow_empty=True) or '',
        'model': _text(payload.get('model'), 'model',
                       max_length=128, allow_empty=True),
    }


def parse_table_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'enabled' in payload:
        fields['enabled'] = _bool(payload.get('enabled'), 'enabled')
    if 'businessName' in payload:
        fields['business_name'] = _text(payload.get('businessName'), 'businessName',
                                        max_length=255, allow_empty=True)
    if 'businessDescription' in payload:
        fields['business_description'] = _text(
            payload.get('businessDescription'), 'businessDescription',
            max_length=4000, allow_empty=True)
    if 'aliases' in payload:
        fields['business_aliases'] = _aliases(payload.get('aliases'), 'aliases')
    return fields


def parse_column_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'enabled' in payload:
        fields['enabled'] = _bool(payload.get('enabled'), 'enabled')
    if 'businessName' in payload:
        fields['business_name'] = _text(payload.get('businessName'), 'businessName',
                                        max_length=255, allow_empty=True)
    if 'businessDescription' in payload:
        fields['business_description'] = _text(
            payload.get('businessDescription'), 'businessDescription',
            max_length=4000, allow_empty=True)
    if 'aliases' in payload:
        fields['business_aliases'] = _aliases(payload.get('aliases'), 'aliases')
    if 'semanticType' in payload:
        value = payload.get('semanticType')
        if value is None or value == '':
            fields['semantic_type'] = None
        elif not isinstance(value, str) or value not in SEMANTIC_TYPES:
            raise Text2SqlValidationError(
                'semanticType 必须是 identifier/measure/dimension/time/category')
        else:
            fields['semantic_type'] = value
    return fields


# ---------------------------------------------------------------------------
# 行 → API
# ---------------------------------------------------------------------------
def derive_status(row: dict[str, Any]) -> str:
    """``configured/scanned/indexed``：由同步时间与「当前修订的活动版本」推导。"""
    if (row.get('active_version_id')
            and row.get('active_status') == 'READY'
            and row.get('active_revision') == row.get('config_revision')):
        return STATUS_INDEXED
    if row.get('last_sync_at'):
        return STATUS_SCANNED
    return STATUS_CONFIGURED


def datasource_to_api(row: dict[str, Any], *,
                      selected_tables: Optional[Iterable[str]] = None) -> dict[str, Any]:
    status = derive_status(row)
    indexed = status == STATUS_INDEXED
    return {
        'id': str(row['id']),
        'name': row.get('name') or '',
        'type': SUPPORTED_DB_TYPES.get(row.get('db_type') or 'postgresql', 'PostgreSQL'),
        'dbType': row.get('db_type') or 'postgresql',
        'host': row.get('host') or '',
        'port': row.get('port') or DEFAULT_PORT,
        'database': row.get('database_name') or '',
        'schema': (row.get('include_schemas') or ['public'])[0],
        'includeSchemas': list(row.get('include_schemas') or ['public']),
        'username': row.get('username') or '',
        'passwordConfigured': bool(row.get('credential_ref')),
        'status': status,
        'enabled': bool(row.get('enabled', True)),
        'revision': row.get('config_revision') or 1,
        'scannedAt': row.get('last_sync_at'),
        'indexedAt': row.get('active_ready_at') if indexed else None,
        'connectionTestedAt': row.get('connection_tested_at'),
        'lastSyncAt': row.get('last_sync_at'),
        'activeVersionId': str(row['active_version_id']) if row.get('active_version_id') else None,
        'requiresPublication': not indexed,
        'topic': {
            'name': row.get('topic_name') or '',
            'description': row.get('topic_description') or '',
            'owner': row.get('maintainer_ref') or '',
        },
        'businessDescription': row.get('business_description') or '',
        'businessTimezone': row.get('business_timezone') or DEFAULT_TIMEZONE,
        'embeddingModel': row.get('embedding_model'),
        'llmModel': row.get('llm_model'),
        'queryPolicy': row.get('query_policy') or dict(DEFAULT_QUERY_POLICY),
        'queryExamples': row.get('query_examples') or [],
        'selectedTables': sorted(selected_tables or []),
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }


def column_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'tableId': str(row['table_id']),
        'name': row.get('column_name') or '',
        'dataType': row.get('data_type') or '',
        'ordinalPosition': row.get('ordinal_position'),
        'nullable': bool(row.get('is_nullable', True)),
        'defaultValue': row.get('default_value'),
        'primaryKey': bool(row.get('is_primary_key')),
        'unique': bool(row.get('is_unique')),
        'dbComment': row.get('db_comment'),
        'businessName': row.get('business_name'),
        'businessDescription': row.get('business_description'),
        'aliases': list(row.get('business_aliases') or []),
        'semanticType': row.get('semantic_type'),
        'enabled': bool(row.get('enabled', True)),
        'valueCardinality': row.get('value_cardinality') or 'UNKNOWN',
        'distinctValueCount': row.get('distinct_value_count'),
        'missingSince': row.get('missing_since'),
        'lastSeenAt': row.get('last_seen_at'),
    }


def table_to_api(row: dict[str, Any],
                 columns: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'schema': row.get('schema_name') or '',
        'name': row.get('table_name') or '',
        'fullName': f"{row.get('schema_name')}.{row.get('table_name')}",
        'type': row.get('table_type') or 'BASE_TABLE',
        'dbComment': row.get('db_comment'),
        'businessName': row.get('business_name'),
        'businessDescription': row.get('business_description'),
        'aliases': list(row.get('business_aliases') or []),
        'enabled': bool(row.get('enabled')),
        'schemaHash': row.get('schema_hash'),
        'missingSince': row.get('missing_since'),
        'lastSeenAt': row.get('last_seen_at'),
        'columns': [column_to_api(column) for column in columns],
    }


# ---------------------------------------------------------------------------
# 关联 / 枚举 / 指标：写接口
# ---------------------------------------------------------------------------
CARDINALITIES = {'ONE_TO_ONE', 'ONE_TO_MANY', 'MANY_TO_ONE', 'MANY_TO_MANY'}
DEPENDENCY_ROLES = {'MEASURE', 'FILTER', 'TIME', 'DIMENSION', 'JOIN'}
VALUE_SOURCE_TYPES = {'DATABASE', 'MANUAL', 'ENUM'}
AGGREGATION_BEHAVIORS = {'ADDITIVE', 'SEMI_ADDITIVE', 'NON_ADDITIVE'}
METRIC_STATUSES = {'DRAFT', 'APPROVED', 'DISABLED'}


def _uuid_text(value: Any, field: str, *, required: bool = True) -> Optional[str]:
    from uuid import UUID

    if value is None or value == '':
        if required:
            raise Text2SqlValidationError(f'{field} 不能为空')
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise Text2SqlValidationError(f'{field} 不是合法的 UUID') from error


def _uuid_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Text2SqlValidationError(f'{field} 必须是数组')
    result: list[str] = []
    for item in value:
        item = _uuid_text(item, field)
        if item not in result:
            result.append(item)
    return result


def _column_pairs(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list) or not value:
        raise Text2SqlValidationError('columnPairs 不能为空')
    if len(value) > 16:
        raise Text2SqlValidationError('columnPairs 最多 16 组')
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise Text2SqlValidationError('columnPairs 必须是对象数组')
        pairs.append((
            _uuid_text(item.get('sourceColumnId'), 'sourceColumnId'),
            _uuid_text(item.get('targetColumnId'), 'targetColumnId'),
        ))
    return pairs


def _cardinality(value: Any, *, required: bool = False) -> Optional[str]:
    if value is None or value == '':
        if required:
            raise Text2SqlValidationError('cardinality 不能为空')
        return None
    if not isinstance(value, str) or value not in CARDINALITIES:
        raise Text2SqlValidationError('cardinality 取值不合法')
    return value


def parse_relation_create(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    relation_type = (_text(payload.get('type'), 'type', max_length=32)
                     or 'MANUAL').upper()
    if relation_type not in ('MANUAL', 'INFERRED'):
        raise Text2SqlValidationError('type 只能是 MANUAL 或 INFERRED')
    return {
        'relation_name': _text(payload.get('name'), 'name', max_length=255,
                               required=True),
        'relation_type': relation_type,
        'source_table_id': _uuid_text(payload.get('sourceTableId'), 'sourceTableId'),
        'target_table_id': _uuid_text(payload.get('targetTableId'), 'targetTableId'),
        'cardinality': _cardinality(payload.get('cardinality')),
        'description': _text(payload.get('description'), 'description',
                             max_length=2000, allow_empty=True) or '',
        'enabled': True if payload.get('enabled') is None
        else _bool(payload.get('enabled'), 'enabled'),
        'column_pairs': _column_pairs(payload.get('columnPairs')),
    }


def parse_relation_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'cardinality' in payload:
        fields['cardinality'] = _cardinality(payload.get('cardinality'))
    if 'description' in payload:
        fields['description'] = _text(payload.get('description'), 'description',
                                      max_length=2000, allow_empty=True) or ''
    if 'enabled' in payload:
        fields['enabled'] = _bool(payload.get('enabled'), 'enabled')
    if 'columnPairs' in payload:
        fields['column_pairs'] = _column_pairs(payload.get('columnPairs'))
    return fields


def parse_relation_verification(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or 'verified' not in payload:
        raise Text2SqlValidationError('verified 不能为空')
    return _bool(payload.get('verified'), 'verified')


def parse_value_create(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    source_type = (_text(payload.get('sourceType'), 'sourceType',
                         max_length=32) or 'MANUAL').upper()
    if source_type not in VALUE_SOURCE_TYPES:
        raise Text2SqlValidationError('sourceType 取值不合法')
    return {
        'column_id': _uuid_text(payload.get('columnId'), 'columnId'),
        'raw_value': _text(payload.get('rawValue'), 'rawValue', max_length=1000,
                           required=True),
        'value_type': _text(payload.get('valueType'), 'valueType',
                            max_length=64) or 'varchar',
        'business_name': _text(payload.get('businessName'), 'businessName',
                               max_length=255, allow_empty=True),
        'aliases': _aliases(payload.get('aliases'), 'aliases') or [],
        'description': _text(payload.get('description'), 'description',
                             max_length=2000, allow_empty=True) or '',
        'source_type': source_type,
        'enabled': True if payload.get('enabled') is None
        else _bool(payload.get('enabled'), 'enabled'),
    }


def parse_value_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'businessName' in payload:
        fields['business_name'] = _text(payload.get('businessName'), 'businessName',
                                        max_length=255, allow_empty=True)
    if 'aliases' in payload:
        fields['aliases'] = _aliases(payload.get('aliases'), 'aliases')
    if 'description' in payload:
        fields['description'] = _text(payload.get('description'), 'description',
                                      max_length=2000, allow_empty=True) or ''
    if 'enabled' in payload:
        fields['enabled'] = _bool(payload.get('enabled'), 'enabled')
    return fields


def _dependencies(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Text2SqlValidationError('columnDependencies 必须是数组')
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise Text2SqlValidationError('columnDependencies 必须是对象数组')
        column_id = _uuid_text(item.get('columnId'), 'columnId')
        role = item.get('role')
        if role not in DEPENDENCY_ROLES:
            raise Text2SqlValidationError('dependencyRole 取值不合法')
        key = (column_id, role)
        if key in seen:
            continue
        seen.add(key)
        result.append({'column_id': column_id, 'role': role})
    return result


#: ``count(distinct x)`` / ``sum(distinct x)`` 这类表达式天然不可加。
_DISTINCT_AGGREGATE = re.compile(r'\b(?:count|sum|avg)\s*\(\s*distinct\b',
                                 re.IGNORECASE)


def _aggregation(value: Any, expression: str = '') -> str:
    """可加性：显式值优先，缺省时按表达式推导。

    ``COUNT(DISTINCT user_id)`` 的月度值不能相加——把它默认成 ``ADDITIVE``
    等于把错误语义写进指标库，所以这里按表达式推导，而不是一律 ADDITIVE。
    """
    text = (_text(value, 'aggregationBehavior', max_length=32) or '').upper()
    if not text:
        return 'NON_ADDITIVE' if _DISTINCT_AGGREGATE.search(expression) else 'ADDITIVE'
    if text not in AGGREGATION_BEHAVIORS:
        raise Text2SqlValidationError('aggregationBehavior 取值不合法')
    return text


def _filter_definition(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Text2SqlValidationError('filterDefinition 必须是对象')
    return value


def _metric_fields(payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if not partial or 'key' in payload:
        fields['metric_key'] = _text(payload.get('key'), 'key', max_length=128,
                                     required=True)
    if not partial or 'businessName' in payload:
        fields['business_name'] = _text(payload.get('businessName'), 'businessName',
                                        max_length=255, required=True)
    if 'businessDescription' in payload:
        fields['business_description'] = _text(
            payload.get('businessDescription'), 'businessDescription',
            max_length=4000, allow_empty=True) or ''
    if 'aliases' in payload:
        fields['aliases'] = _aliases(payload.get('aliases'), 'aliases') or []
    if not partial or 'baseTableId' in payload:
        fields['base_table_id'] = _uuid_text(payload.get('baseTableId'), 'baseTableId')
    if not partial or 'expressionSql' in payload:
        fields['expression_sql'] = _text(payload.get('expressionSql'), 'expressionSql',
                                         max_length=4000, required=True)
    if 'filterDefinition' in payload:
        fields['filter_definition'] = _filter_definition(payload.get('filterDefinition'))
    if 'timeColumnId' in payload:
        fields['time_column_id'] = _uuid_text(payload.get('timeColumnId'),
                                              'timeColumnId', required=False)
    if 'unit' in payload:
        fields['unit'] = _text(payload.get('unit'), 'unit', max_length=64,
                               allow_empty=True)
    if 'businessTimezone' in payload:
        fields['business_timezone'] = _timezone(payload.get('businessTimezone'))
    elif not partial:
        fields['business_timezone'] = DEFAULT_TIMEZONE
    if 'aggregationBehavior' in payload or not partial:
        fields['aggregation_behavior'] = _aggregation(
            payload.get('aggregationBehavior'), fields.get('expression_sql') or '')
    if 'attributionDescription' in payload:
        fields['attribution_description'] = _text(
            payload.get('attributionDescription'), 'attributionDescription',
            max_length=4000, allow_empty=True) or ''
    if 'columnDependencies' in payload or not partial:
        fields['column_dependencies'] = _dependencies(payload.get('columnDependencies'))
    if 'relationDependencies' in payload or not partial:
        fields['relation_dependencies'] = _uuid_list(
            payload.get('relationDependencies'), 'relationDependencies')
    return fields


def parse_metric_create(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    return _metric_fields(payload, partial=False)


def parse_metric_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    return _metric_fields(payload, partial=True)


def parse_metric_status(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    status = _text(payload.get('status'), 'status', max_length=16)
    if status not in {'APPROVED', 'DISABLED'}:
        raise Text2SqlValidationError('status 只能是 APPROVED 或 DISABLED')
    return status


# ---------------------------------------------------------------------------
# 关联 / 枚举 / 指标：行 → API
# ---------------------------------------------------------------------------
def relation_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'name': row.get('relation_name') or '',
        'type': row.get('relation_type'),
        'cardinality': row.get('cardinality'),
        'description': row.get('description') or '',
        'enabled': bool(row.get('enabled', True)),
        'verified': bool(row.get('verified')),
        'verifiedBy': row.get('verified_by'),
        'verifiedAt': row.get('verified_at'),
        'sourceTableId': str(row['source_table_id']),
        'sourceTable': row.get('source_table'),
        'targetTableId': str(row['target_table_id']),
        'targetTable': row.get('target_table'),
        'columnPairs': [{
            'sourceColumnId': str(pair['source_column_id']),
            'sourceColumn': pair.get('source_column_name'),
            'targetColumnId': str(pair['target_column_id']),
            'targetColumn': pair.get('target_column_name'),
        } for pair in row.get('column_pairs') or []],
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }


def value_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'columnId': str(row['column_id']),
        'column': row.get('column_name'),
        'table': row.get('table_name'),
        'rawValue': row.get('raw_value'),
        'valueType': row.get('value_type'),
        'businessName': row.get('business_name'),
        'aliases': list(row.get('aliases') or []),
        'description': row.get('description') or '',
        'sourceType': row.get('source_type'),
        'enabled': bool(row.get('enabled', True)),
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }


def metric_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'key': row.get('metric_key'),
        'businessName': row.get('business_name'),
        'businessDescription': row.get('business_description') or '',
        'aliases': list(row.get('aliases') or []),
        'baseTableId': str(row['base_table_id']),
        'baseTable': row.get('base_table'),
        'expressionSql': row.get('expression_sql'),
        'filterDefinition': row.get('filter_definition') or {},
        'timeColumnId': str(row['time_column_id']) if row.get('time_column_id') else None,
        'timeColumn': row.get('time_column'),
        'unit': row.get('unit'),
        'businessTimezone': row.get('business_timezone'),
        'aggregationBehavior': row.get('aggregation_behavior'),
        'attributionDescription': row.get('attribution_description') or '',
        'status': row.get('status'),
        'verifiedBy': row.get('verified_by'),
        'verifiedAt': row.get('verified_at'),
        'columnDependencies': [{
            'columnId': str(item['column_id']),
            'column': item.get('column_name'),
            'table': item.get('table_name'),
            'role': item.get('dependency_role'),
        } for item in row.get('column_dependencies') or []],
        'relationDependencies': list(row.get('relation_dependencies') or []),
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }


# ---------------------------------------------------------------------------
# 配置版本
# ---------------------------------------------------------------------------
def job_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'jobType': row.get('job_type'),
        'status': row.get('status'),
        'attempt': row.get('attempt'),
        'totalCount': row.get('total_count'),
        'processedCount': row.get('processed_count'),
        'failedCount': row.get('failed_count'),
        'errorMessage': row.get('error_message'),
        'workerId': row.get('worker_id'),
        'startedAt': row.get('started_at'),
        'finishedAt': row.get('finished_at'),
        'createdAt': row.get('created_at'),
    }


def version_to_api(row: dict[str, Any], *, include_snapshot: bool = False) -> dict[str, Any]:
    result = {
        'id': str(row['id']),
        'datasourceId': str(row['datasource_id']),
        'revision': row.get('revision'),
        'status': row.get('status'),
        'contentHash': row.get('content_hash'),
        'expectedKnowledgeCount': row.get('expected_knowledge_count'),
        'indexedCount': row.get('indexed_count'),
        'failedCount': row.get('failed_count'),
        'embeddingModel': row.get('embedding_model'),
        'embeddingDimensions': row.get('embedding_dimensions'),
        'createdBy': row.get('created_by'),
        'readyAt': row.get('ready_at'),
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }
    if include_snapshot:
        result['snapshot'] = row.get('snapshot')
        result['knowledge'] = [{
            'objectType': item.get('object_type'),
            'indexStatus': item.get('index_status'),
            'count': item.get('count'),
        } for item in row.get('knowledge') or []]
        result['jobs'] = [job_to_api(job) for job in row.get('jobs') or []]
        result['bindings'] = [{
            'storeKind': item.get('store_kind'),
            'state': item.get('state'),
            'count': item.get('count'),
        } for item in row.get('bindings') or []]
    return result


# ---------------------------------------------------------------------------
# 查询工作台 / 常用查询 / 反馈 / 草稿
# ---------------------------------------------------------------------------
DATE_POLICIES = {'relative', 'fixed', 'all'}
FEEDBACK_CATEGORIES = {'helpful', 'meaning', 'sql', 'data'}


def _parameters(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Text2SqlValidationError('parameters 必须是对象')
    if len(value) > 50:
        raise Text2SqlValidationError('parameters 最多 50 项')
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > 20000:
        raise Text2SqlValidationError('parameters 过大')
    return value


def _date_policy(value: Any) -> str:
    policy = _text(value, 'datePolicy', max_length=16) or 'relative'
    if policy not in DATE_POLICIES:
        raise Text2SqlValidationError('datePolicy 必须是 relative/fixed/all')
    return policy


def _object(value: Any, field: str) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise Text2SqlValidationError(f'{field} 必须是对象')
    return value


def parse_query_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    question = _text(payload.get('question'), 'question', max_length=2000,
                     required=True)
    date_policy = _date_policy(payload.get('datePolicy'))
    fixed = _object(payload.get('fixedTimeRange'), 'fixedTimeRange')
    if date_policy == 'fixed' and not fixed:
        raise Text2SqlValidationError('fixed 日期策略需要 fixedTimeRange')
    if date_policy != 'fixed':
        fixed = None
    sql = _text(payload.get('sql'), 'sql', max_length=20000)
    return {
        'question': question,
        'parameters': _parameters(payload.get('parameters')),
        'date_policy': date_policy,
        'fixed_time_range': fixed,
        'parent_run_id': (_uuid_text(payload.get('parentRunId'), 'parentRunId',
                                     required=False)
                          if payload.get('parentRunId') else None),
        'sql': sql,
        'model': _text(payload.get('model'), 'model', max_length=255),
    }


def parse_favorite_create(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    date_policy = _date_policy(payload.get('datePolicy'))
    fixed = _object(payload.get('fixedTimeRange'), 'fixedTimeRange')
    if date_policy == 'fixed' and not fixed:
        raise Text2SqlValidationError('fixed 日期策略需要 fixedTimeRange')
    if date_policy != 'fixed':
        fixed = None
    datasource = payload.get('datasourceId')
    return {
        'datasource_id': (_uuid_text(datasource, 'datasourceId', required=False)
                          if datasource else None),
        'name': _text(payload.get('name'), 'name', max_length=80, required=True),
        'question': _text(payload.get('question'), 'question', max_length=2000,
                          required=True),
        'parameters': _parameters(payload.get('parameters')),
        'date_policy': date_policy,
        'fixed_time_range': fixed,
        'notes': _text(payload.get('notes'), 'notes', max_length=2000,
                       allow_empty=True) or '',
    }


def parse_favorite_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    fields: dict[str, Any] = {}
    if 'datasourceId' in payload:
        fields['datasource_id'] = (_uuid_text(payload.get('datasourceId'),
                                              'datasourceId', required=False)
                                   if payload.get('datasourceId') else None)
    if 'name' in payload:
        fields['name'] = _text(payload.get('name'), 'name', max_length=80,
                               required=True)
    if 'question' in payload:
        fields['question'] = _text(payload.get('question'), 'question',
                                   max_length=2000, required=True)
    if 'parameters' in payload:
        fields['parameters'] = _parameters(payload.get('parameters'))
    if 'notes' in payload:
        fields['notes'] = _text(payload.get('notes'), 'notes', max_length=2000,
                                allow_empty=True) or ''
    if 'datePolicy' in payload or 'fixedTimeRange' in payload:
        policy = _date_policy(payload.get('datePolicy'))
        fixed = _object(payload.get('fixedTimeRange'), 'fixedTimeRange')
        if policy == 'fixed' and not fixed:
            raise Text2SqlValidationError('fixed 日期策略需要 fixedTimeRange')
        fields['date_policy'] = policy
        fields['fixed_time_range'] = fixed if policy == 'fixed' else None
    return fields


def parse_feedback_create(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    category = _text(payload.get('category'), 'category', max_length=16,
                     required=True)
    if category not in FEEDBACK_CATEGORIES:
        raise Text2SqlValidationError('category 必须是 helpful/meaning/sql/data')
    helpful = payload.get('helpful')
    if category == 'helpful':
        if not isinstance(helpful, bool):
            raise Text2SqlValidationError('helpful 反馈需要布尔值 helpful')
    else:
        helpful = None
    notes = _text(payload.get('notes'), 'notes', max_length=4000,
                  allow_empty=True) or ''
    if category != 'helpful' and not notes:
        raise Text2SqlValidationError('该反馈类型需要填写说明')
    return {'category': category, 'helpful': helpful, 'notes': notes}


def parse_workspace_update(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise Text2SqlValidationError('请求体必须是对象')
    datasource = payload.get('datasourceId')
    return {
        'datasource_id': (_uuid_text(datasource, 'datasourceId', required=False)
                          if datasource else None),
        'question_draft': _text(payload.get('questionDraft'), 'questionDraft',
                                max_length=2000, allow_empty=True) or '',
        'sql_draft': _text(payload.get('sqlDraft'), 'sqlDraft',
                           max_length=20000, allow_empty=True) or '',
        'preferences': _object(payload.get('preferences'), 'preferences') or {},
    }


def favorite_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'datasourceId': str(row['datasource_id']) if row.get('datasource_id') else None,
        'datasource_id': str(row['datasource_id']) if row.get('datasource_id') else None,
        'name': row.get('name'),
        'question': row.get('question'),
        'parameters': row.get('parameters') or {},
        'datePolicy': row.get('date_policy'),
        'date_policy': row.get('date_policy'),
        'fixedTimeRange': row.get('fixed_time_range'),
        'notes': row.get('notes') or '',
        'verifiedVersionId': (str(row['verified_version_id'])
                              if row.get('verified_version_id') else None),
        'verifiedBy': row.get('verified_by'),
        'verifiedAt': row.get('verified_at'),
        'createdAt': row.get('created_at'),
        'updatedAt': row.get('updated_at'),
    }


def feedback_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(row['id']),
        'runId': str(row['run_id']),
        'category': row.get('category'),
        'helpful': row.get('helpful'),
        'notes': row.get('notes') or '',
        'status': row.get('status'),
        'createdAt': row.get('created_at'),
    }


def workspace_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'datasourceId': str(row['datasource_id']) if row.get('datasource_id') else None,
        'questionDraft': row.get('question_draft') or '',
        'sqlDraft': row.get('sql_draft') or '',
        'preferences': row.get('preferences') or {},
        'updatedAt': row.get('updated_at'),
    }
