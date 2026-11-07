"""Agent Key 的校验与读写编排（**不依赖 FastAPI**）。

CLI（``agent_api.cli``）与 UI 管理接口（``agent_api.admin_rest``）共用这里：

* 校验：名称 / scopes / 知识库白名单 / 限流 / 过期时间；
* 创建：生成 Key、HMAC、插入、前缀碰撞重试；
* 展示：DB 行 → 前端 camelCase DTO（**绝不带 key_hash**）。

⚠️ import-light 约束：``agent_api/__init__.py`` 要求 ``keys``/``cli`` 不拉起
FastAPI，而 ``http_api.py`` 会 import 路由模块。因此本模块**不得**在
顶层 import ``knowledge_base.*``；错误用下面的轻量异常表达，由 ``admin_rest``
翻译成 ``KbApiError`` 后再套信封，CLI 则转成 ``SystemExit``。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agent import config, keys, scopes, repository_pg as store_pg
from infrastructure.http.pagination import page as paginate
from agent.errors import AgentKeyStoreUnavailable

#: 用标准库 logger 而不是 ``tool.log``：本模块要能被 ``python3 -m agent_api.cli``
#: 在最小依赖下导入（见模块 docstring 的 import-light 约束）。
log = logging.getLogger(__name__)

CODE_SERVER_ERROR = '0001'
CODE_VALIDATION_ERROR = '0004'
CODE_BUSINESS_ERROR = '0005'


class KeyAdminError(Exception):
    """管理面的领域错误：文案键 + 参数 + kb 信封码。"""

    def __init__(self, key: str, *args, code: str = CODE_BUSINESS_ERROR):
        super().__init__(key, *args)
        self.key = key
        self.args = args
        self.code = code


class KeyValidationError(KeyAdminError):
    """入参校验失败（0004）。"""

    def __init__(self, key: str, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR)


def parse_expires(value: str) -> datetime:
    """把 ``YYYY-MM-DD`` / ISO 8601 解析成带时区的 UTC 时间。

    ``YYYY-MM-DD`` 表示**当天结束**（23:59:59 UTC），与 CLI 的历史语义一致。
    """
    text = (value or '').strip()
    if not text:
        raise ValueError('empty expiry')
    if len(text) == 10:
        date = datetime.strptime(text, '%Y-%m-%d').date()
        return datetime.combine(date, time(23, 59, 59), tzinfo=timezone.utc)
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_expired(expires_at, now: Optional[datetime] = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if getattr(expires_at, 'tzinfo', None) is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return current >= expires_at


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def to_public(row: dict[str, Any]) -> dict[str, Any]:
    """DB 行 → UI DTO。按字段显式构造，避免把 ``key_hash`` 透传出去。"""
    expires_at = row.get('expires_at')
    return {
        'keyPrefix': row.get('key_prefix') or '',
        'name': row.get('name') or '',
        'description': row.get('description') or '',
        'scopes': list(row.get('scopes') or []),
        'kbIds': list(row.get('kb_ids') or []),
        'rateLimitPerMin': int(row.get('rate_limit_per_min') or 0),
        'enabled': bool(row.get('enabled')),
        'expiresAt': _iso(expires_at),
        'expired': is_expired(expires_at),
        'lastUsedAt': _iso(row.get('last_used_at')),
        'createdAt': _iso(row.get('created_at')),
        'createdBy': row.get('created_by') or '',
    }


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
_CREATE_FIELDS = frozenset({'name', 'description', 'scopes', 'kbIds',
                            'rateLimitPerMin', 'expiresAt'})
_UPDATE_FIELDS = _CREATE_FIELDS | {'enabled'}


def _reject_unknown(payload: dict, allowed: frozenset[str]) -> None:
    unknown = [key for key in payload if key not in allowed]
    if unknown:
        raise KeyValidationError('agent.key.field.unknown', unknown[0])


def _validate_name(value, *, required: bool) -> Optional[str]:
    if value is None:
        if required:
            raise KeyValidationError('agent.key.name.required')
        return None
    if not isinstance(value, str):
        raise KeyValidationError('agent.key.name.required')
    name = value.strip()
    if not name:
        raise KeyValidationError('agent.key.name.required')
    if len(name) > scopes.MAX_NAME_LENGTH:
        raise KeyValidationError('agent.key.name.too.long', scopes.MAX_NAME_LENGTH)
    return name


def _validate_description(value) -> Optional[str]:
    """0.1.3「用途说明」：选填；``None`` 与空串都按「清空」处理。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise KeyValidationError('agent.key.description.invalid')
    description = value.strip()
    if len(description) > scopes.MAX_DESCRIPTION_LENGTH:
        raise KeyValidationError('agent.key.description.too.long',
                                 scopes.MAX_DESCRIPTION_LENGTH)
    return description


def _validate_scopes(value, *, required: bool) -> Optional[list[str]]:
    if value is None:
        if required:
            raise KeyValidationError('agent.key.scopes.required')
        return None
    if not isinstance(value, list):
        raise KeyValidationError('agent.key.scopes.required')
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise KeyValidationError('agent.key.scopes.required')
        scope = item.strip()
        if scope not in scopes.KNOWN_SCOPES:
            raise KeyValidationError('agent.key.scope.unknown', scope)
        if scope not in result:
            result.append(scope)
    if not result:
        raise KeyValidationError('agent.key.scopes.required')
    return result


def _validate_kb_ids(value, *, required: bool) -> Optional[list[str]]:
    if value is None:
        if required:
            return []
        return None
    if not isinstance(value, list):
        raise KeyValidationError('agent.key.kb_ids.invalid')
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise KeyValidationError('agent.key.kb_ids.invalid')
        kb_id = item.strip()
        if not kb_id:
            continue
        if len(kb_id) > 128:
            raise KeyValidationError('agent.key.kb_ids.invalid')
        if kb_id not in result:
            result.append(kb_id)
    if len(result) > scopes.MAX_KB_IDS:
        raise KeyValidationError('agent.key.kb_ids.too.many', scopes.MAX_KB_IDS)
    return result


def _validate_rate_limit(value, *, required: bool) -> Optional[int]:
    if value is None:
        if required:
            return scopes.DEFAULT_RATE_LIMIT_PER_MIN
        return None
    # bool 是 int 的子类：True/False 会被当成 1/0，必须显式拒绝。
    if isinstance(value, bool) or not isinstance(value, int):
        raise KeyValidationError('agent.key.rate_limit.invalid',
                                 scopes.MAX_RATE_LIMIT_PER_MIN)
    if value < 0 or value > scopes.MAX_RATE_LIMIT_PER_MIN:
        raise KeyValidationError('agent.key.rate_limit.invalid',
                                 scopes.MAX_RATE_LIMIT_PER_MIN)
    return value


def _validate_expires_at(value, *, required: bool) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise KeyValidationError('agent.key.expires_at.invalid')
    try:
        parsed = parse_expires(value)
    except ValueError:
        raise KeyValidationError('agent.key.expires_at.invalid') from None
    if parsed <= datetime.now(timezone.utc) - timedelta(seconds=60):
        raise KeyValidationError('agent.key.expires_at.past')
    return parsed


def validate_create(payload: dict) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise KeyValidationError('RetCode.illegalArgument')
    _reject_unknown(payload, _CREATE_FIELDS)
    return {
        'name': _validate_name(payload.get('name'), required=True),
        'description': _validate_description(payload.get('description')),
        'scopes': _validate_scopes(payload.get('scopes'), required=True),
        'kb_ids': _validate_kb_ids(payload.get('kbIds'), required=True),
        'rate_limit_per_min': _validate_rate_limit(
            payload.get('rateLimitPerMin'), required=True),
        'expires_at': _validate_expires_at(payload.get('expiresAt'), required=True),
    }


def validate_update(payload: dict) -> dict[str, Any]:
    """返回 ``store_pg.update_key`` 的关键字参数；只包含请求里出现的字段。"""
    if not isinstance(payload, dict):
        raise KeyValidationError('RetCode.illegalArgument')
    _reject_unknown(payload, _UPDATE_FIELDS)
    changes: dict[str, Any] = {}
    if 'name' in payload:
        changes['name'] = _validate_name(payload.get('name'), required=True)
    if 'description' in payload:
        changes['description'] = _validate_description(payload.get('description'))
    if 'scopes' in payload:
        changes['scopes'] = _validate_scopes(payload.get('scopes'), required=True)
    if 'kbIds' in payload:
        changes['kb_ids'] = _validate_kb_ids(payload.get('kbIds'), required=True)
    if 'rateLimitPerMin' in payload:
        changes['rate_limit_per_min'] = _validate_rate_limit(
            payload.get('rateLimitPerMin'), required=True)
    if 'expiresAt' in payload:
        # 显式传 null = 清空过期时间；传字符串 = 新时间。
        changes['expires_at'] = _validate_expires_at(payload.get('expiresAt'),
                                                     required=False)
    if 'enabled' in payload:
        value = payload.get('enabled')
        if not isinstance(value, bool):
            raise KeyValidationError('RetCode.illegalArgument')
        changes['enabled'] = value
    if not changes:
        raise KeyValidationError('agent.key.no.fields')
    return changes


# ---------------------------------------------------------------------------
# 写操作
# ---------------------------------------------------------------------------
def create_key_record(*, name: str, description: Optional[str],
                      scopes_list: list[str], kb_ids: list[str],
                      rate_limit_per_min: int, expires_at,
                      created_by: str, pepper: str) -> tuple[str, str]:
    """插入一把 Key，返回 ``(完整 Key, 前缀)``。不回读数据库。"""
    last_error = None
    for _ in range(scopes.KEY_PREFIX_RETRIES):
        full_key, prefix = keys.generate_key()
        key_hash = keys.hash_key(full_key, pepper)
        try:
            store_pg.insert_key(
                name=name,
                description=description,
                key_prefix=prefix,
                key_hash=key_hash,
                scopes=scopes_list,
                kb_ids=kb_ids,
                rate_limit_per_min=rate_limit_per_min,
                expires_at=expires_at,
                created_by=(created_by or '')[:scopes.MAX_CREATED_BY_LENGTH] or None,
            )
        except Exception as error:                                 # noqa: BLE001
            # 唯一索引冲突（23505）说明前缀撞了，换一个重试；其它异常照抛。
            if getattr(error, 'pgcode', None) == '23505':
                last_error = error
                continue
            raise
        return full_key, prefix
    log.error('agent key prefix collision after %d attempts: %s',
              scopes.KEY_PREFIX_RETRIES, last_error)
    raise KeyAdminError('agent.key.create.failed', code=CODE_SERVER_ERROR)


def create_key(payload: dict, created_by: str) -> dict[str, Any]:
    data = validate_create(payload)
    pepper = config.key_pepper()
    if not pepper:
        raise KeyAdminError('agent.key.pepper.missing', code=CODE_SERVER_ERROR)
    full_key, prefix = create_key_record(
        name=data['name'],
        description=data.get('description'),
        scopes_list=data['scopes'],
        kb_ids=data['kb_ids'],
        rate_limit_per_min=data['rate_limit_per_min'],
        expires_at=data['expires_at'],
        created_by=created_by,
        pepper=pepper,
    )
    row = store_pg.get_key(prefix)
    if row is None:
        raise KeyAdminError('agent.key.create.failed', code=CODE_SERVER_ERROR)
    return {'key': to_public(row), 'plaintextKey': full_key}


def update_key(key_prefix: str, payload: dict) -> dict[str, Any]:
    if not keys.is_key_prefix(key_prefix):
        raise KeyAdminError('agent.key.not.found')
    changes = validate_update(payload)
    row = store_pg.update_key(key_prefix, **changes)
    if row is None:
        raise KeyAdminError('agent.key.not.found')
    return to_public(row)


def delete_key(key_prefix: str) -> dict[str, str]:
    if not keys.is_key_prefix(key_prefix):
        raise KeyAdminError('agent.key.not.found')
    if store_pg.delete_key(key_prefix) == 0:
        raise KeyAdminError('agent.key.not.found')
    return {'keyPrefix': key_prefix}


_SORT_FIELDS = {'name', 'keyPrefix', 'expiresAt', 'lastUsedAt'}

#: 「最近 N 天」= 含今天在内的 N 个自然日（Asia/Shanghai）。
USAGE_WINDOW_DAYS = 7
USAGE_TIMEZONE = ZoneInfo('Asia/Shanghai')


def list_keys(current_page: int = 1, page_size: int = 50,
              keyword: str = '', enabled=None,
              sort_by: str = '', sort_order: str = '') -> dict[str, Any]:
    items = [to_public(row) for row in store_pg.list_keys()]
    needle = (keyword or '').strip().lower()
    if needle:
        items = [item for item in items
                 if needle in item['name'].lower()
                 or needle in item['keyPrefix'].lower()
                 or needle in (item['createdBy'] or '').lower()]
    if enabled is not None:
        items = [item for item in items if bool(item.get('enabled')) == bool(enabled)]
    if sort_by in _SORT_FIELDS:
        present = [item for item in items
                   if item.get(sort_by) not in (None, '')]
        missing = [item for item in items
                   if item.get(sort_by) in (None, '')]
        present.sort(key=lambda item: str(item.get(sort_by)).lower(),
                     reverse=str(sort_order).lower() == 'desc')
        items = present + missing
    total = len(items)
    page = max(1, int(current_page or 1))
    size = min(max(1, int(page_size or 50)), 100)
    start = (page - 1) * size
    return paginate(items[start:start + size], total, page, size)


# ---------------------------------------------------------------------------
# 概览计数
# ---------------------------------------------------------------------------
def key_summary() -> dict[str, Any]:
    """所有 Key 的聚合计数（**不受列表分页上限影响**）。

    列表端点对 ``pageSize`` 有 100 的上限，页面顶部四张卡不能用「一次拉 500 条
    再本地数」——超过 100 把 Key 时会静默少算。这里从同一份全量结果聚合，
    口径与列表行 DTO（``to_public``）一致。
    """
    items = [to_public(row) for row in store_pg.list_keys()]
    kb_ids = {kb for item in items for kb in (item.get('kbIds') or [])}
    return {
        'total': len(items),
        'enabled': sum(1 for item in items if item.get('enabled')),
        'rateLimited': sum(
            1 for item in items if int(item.get('rateLimitPerMin') or 0) > 0),
        'kbScoped': sum(1 for item in items if item.get('kbIds')),
        # 「可访问知识库」：有任一把 Key 未限定白名单时视为全部可用；
        # 否则统计所有 Key 白名单里去重后的库数。
        'allKbs': any(not item.get('kbIds') for item in items),
        'kbCount': len(kb_ids),
    }


# ---------------------------------------------------------------------------
# 调用统计
# ---------------------------------------------------------------------------
def usage_stats(today: Optional[date] = None) -> dict[str, Any]:
    """页面顶部两个调用量指标：累计调用量 + 最近 7 个自然日请求数。

    数据来自 ``agent_api_key_usage``（鉴权通过时累加），不是内存计数 ——
    重启不丢，删 Key 时由外键级联清理。``today`` 仅供测试注入。
    """
    current = today or datetime.now(USAGE_TIMEZONE).date()
    window_start = current - timedelta(days=USAGE_WINDOW_DAYS - 1)
    summary = store_pg.usage_summary(window_start)
    return {
        'totalCalls': int(summary.get('total_calls') or 0),
        'requests7d': int(summary.get('calls_7d') or 0),
        'windowStart': window_start.isoformat(),
        'windowEnd': current.isoformat(),
    }


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
def build_status(root_path: str = '') -> dict[str, Any]:
    """页面用的只读状态。**不包含 pepper 或任何 Key 材料。**"""
    available = True
    try:
        store_pg.ping()
    except AgentKeyStoreUnavailable:
        available = False
    except Exception:                                              # noqa: BLE001
        log.warning('agent key admin: key store ping failed', exc_info=True)
        available = False

    prefix = (root_path or '').rstrip('/')
    from shared.prefixes import AGENT_MCP_PATH, AGENT_PREFIX

    return {
        'adminEnabled': config.key_admin_enabled(),
        'apiEnabled': config.api_enabled(),
        'restEnabled': config.rest_enabled(),
        'mcpEnabled': config.mcp_enabled(),
        'answerEnabled': config.answer_enabled(),
        'pepperConfigured': bool(config.key_pepper()),
        'keyStoreAvailable': available,
        'authMode': (os.environ.get('AUTH_MODE') or 'local').strip().lower(),
        'restBasePath': prefix + AGENT_PREFIX,
        'mcpPath': prefix + AGENT_MCP_PATH,
        'publicBase': config.public_base(),
        'scopes': list(scopes.KNOWN_SCOPES),
        'defaultScopes': list(scopes.DEFAULT_SCOPES),
        'defaultRateLimitPerMin': scopes.DEFAULT_RATE_LIMIT_PER_MIN,
        'maxKbs': config.max_kbs(),
        'maxKbIds': scopes.MAX_KB_IDS,
    }
