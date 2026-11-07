"""模型注册表的领域服务（校验 + 默认模型唯一性 + 连接测试 + 引用检查）。

**这一层不碰 SQL，也不碰 HTTP 细节**：读写走注入的 :class:`~model.repository.ModelStore`，
探测走 ``model.probe``（已实现「任何失败 = 无法判定」的语义），
于是单测全部不需要数据库。

四条与契约直接相关的取舍，改动前先看 ``contracts/model-gateway.md``：

1. **LLM 连接测试必须真实调用**。只探 ``GET /models`` 不够：那份清单是「网关声明了
   哪些模型名」，不保证真的能推理 —— 实测 ``qwen3-32b`` 一直在清单里，但
   ``POST /chat/completions`` 返回 404 ``Received Model Group=...``。所以 LLM 行必须
   真发一次最小 ``chat`` 请求，清单探测降级为补充信息。
2. **探测失败 ≠ 模型不可用**。连接测试如实报告「调用成功 / 失败 / 说不准」，
   **不据此拒绝保存**（判错代价不对称，误判会把用户挡在门外的教训写在契约里）。
3. **维度必须显式**。embedding 行的 ``dimension`` 是建库与写入时的校验基准，
   错了要显式失败 —— 契约明确禁止静默截断/补零。
4. **正在被知识库使用的 embedding 模型不许删**。删掉不会报错，只会让那些库在
   下次检索/导入时静默拿不到端点（768 维那批就是这么变成「关键词有、向量恒空」的）。
"""

from __future__ import annotations

import copy
import ipaddress
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

from infrastructure.http import egress
from infrastructure.http.pagination import page as paginate
from model.probe import probe_available_models
from model import thinking_presets
from model.errors import ModelBusinessError, ModelValidationError
from model.models import (
    MODEL_KIND_EMBEDDING,
    MODEL_KIND_LLM,
    MODEL_KIND_RERANK,
    MODEL_KINDS,
    OP_CHAT,
    OP_EMBEDDINGS,
    OP_RERANK,
    SOURCE_USER,
    ModelRecord,
    new_model_id,
)

#: 允许的端点协议。**同时是一道 SSRF 收窄**：本仓不做鉴权（见 contracts），
#: 能打开管理页的人就能让服务去打任意地址。挡住 file:// 之类的非网络协议，
#: 并把这个风险写进契约文档。
ALLOWED_URL_SCHEMES = ('http://', 'https://')

#: 与 ``repository_pg`` 的列宽保持一致。超长值若放过去，INSERT/UPDATE 会抛
#: DataError 变成 500；这里提前按 422 拒绝（4014 字符的
#: 端点地址返回了 500）。
MAX_BASE_URL_LENGTH = 1000
#: api_key 落库前先加密再 base64（约 4/3 倍 + 44 字符），列宽 varchar(2000)；
#: 1400 字节明文对应的密文约 1911 字符，留出安全余量。按 **UTF-8 字节**计，
#: 否则 500 个中文字符（1500 字节）仍会触发数据库截断。
MAX_API_KEY_BYTES = 1400
_TEXT_LIMITS = {
    'modelName': 255,
    'displayName': 255,
    'apiModel': 255,
    'baseUrl': MAX_BASE_URL_LENGTH,
    'chatPath': 255,
    'embeddingsPath': 255,
    'modelsPath': 255,
    'rerankPath': 255,
    'remark': 500,
}

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

#: 连接测试的单次 HTTP 超时（秒）。管理页是交互式的，宁可「说不准」也别挂着
TEST_TIMEOUT_SECONDS = 8.0

#: LLM 真实调用（``POST /chat/completions``）的超时。比清单探测宽：这是一次**真实生成**，
#: 推理模型首包可能明显慢于一次列表请求；但它仍是用户点「连接测试」时同步等待的，
#: 所以不放成分钟级 —— 超过这个时间就当「调不通」。
CHAT_TEST_TIMEOUT_SECONDS = 30.0
#: 连接测试只花几个 token，内容无关紧要；给 16 而不是 1，避开部分实现对极小
#: ``max_tokens`` 的边界校验（推理模型也会把思考 token 算进去）。
CHAT_TEST_MAX_TOKENS = 16
CHAT_TEST_PROMPT = 'hi'

#: 重排探测的固定输入：一篇与 query 相关、一篇无关。分数数值**不参与判定**（不同实现
#: 的刻度差很大），只要求响应里有合法的 ``index`` + ``relevance_score``。
RERANK_TEST_QUERY = 'hello'
RERANK_TEST_DOCUMENTS = ('hello world', 'goodbye world')

#: 只有这些 kind 需要维度
_DIMENSION_REQUIRED_KINDS = (MODEL_KIND_EMBEDDING,)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def _invalidate_resolver() -> None:
    """让 ``core/gateway/model_resolver`` 的缓存失效（延迟 import，避免 import 环）。"""
    from model import resolver as model_resolver

    model_resolver.invalidate()


def _text(payload: dict, key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ''


def _optional_int(payload: dict, key: str) -> Optional[int]:
    value = payload.get(key)
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ModelValidationError('model.dimension.invalid', value)


def _optional_float(payload: dict, key: str) -> Optional[float]:
    value = payload.get(key)
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ModelValidationError('model.dimension.invalid', value)


#: 云元数据/链路本地地址不可能是用户自己的模型端点，连接测试不应访问它们。
_BLOCKED_PROBE_HOSTS = {'169.254.169.254', 'metadata.google.internal',
                        'metadata.azure.internal'}


def _require_base_url(base_url: str) -> None:
    if not base_url:
        raise ModelValidationError('model.baseurl.required')
    if not base_url.lower().startswith(ALLOWED_URL_SCHEMES):
        raise ModelValidationError('model.baseurl.invalid')
    if len(base_url) > MAX_BASE_URL_LENGTH:
        raise ModelValidationError('model.baseurl.tooLong', MAX_BASE_URL_LENGTH)

    host = (urlsplit(base_url).hostname or '').strip('[]').lower()
    if host in _BLOCKED_PROBE_HOSTS:
        raise ModelValidationError('model.baseurl.invalid')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_link_local or address.is_unspecified:
        raise ModelValidationError('model.baseurl.invalid')


def _require_text_lengths(payload: dict) -> None:
    """按 ``model_registry`` 的列宽拒绝超长字段，避免落到数据库层变 500。"""
    for key, limit in _TEXT_LIMITS.items():
        if len(_text(payload, key)) > limit:
            raise ModelValidationError('model.field.tooLong', key, limit)


def _require_api_key_length(api_key: str) -> None:
    """apiKey 单独按字节数校验：只有用户提交新 key 时才检查。

    ``model_registry.api_key`` 存的是 AES 密文的 base64（约明文 4/3 + 44 字符），
    列宽 2000；按 UTF-8 字节计，1400 字节留有余量。编辑已存在的行时不能用解密后的
    旧值做长度判断，否则历史上接近上限的 key 会导致任何无关更新都被拒绝。
    """
    if len(api_key.encode('utf-8')) > MAX_API_KEY_BYTES:
        raise ModelValidationError('model.apikey.tooLong', MAX_API_KEY_BYTES)


def _validate_kind(kind: str) -> str:
    if kind not in MODEL_KINDS:
        raise ModelValidationError('model.kind.invalid', '/'.join(MODEL_KINDS))
    return kind


def _normalize_thinking(kind: str, payload: dict, existing: Optional[ModelRecord]):
    """把请求里的思考意图归一成 ``(mode, preset, payload)``。

    语义：
    * 非 LLM 一律 ``none``；
    * ``auto`` 不存 payload，运行时按目录匹配；
    * ``preset`` 存目录 payload 快照；同一个 preset 的无关编辑不重新快照；
    * ``custom`` 必须是非空 JSON 对象，走白名单/大小校验。
    """
    if kind != MODEL_KIND_LLM:
        return (thinking_presets.MODE_NONE, '', None)

    payload = payload or {}
    has_mode = 'thinkingMode' in payload
    has_preset = 'thinkingPreset' in payload
    has_payload = 'thinkingPayload' in payload

    mode = existing.thinking_mode if existing else thinking_presets.MODE_NONE
    preset_id = existing.thinking_preset if existing else ''
    stored = (copy.deepcopy(existing.thinking_payload)
              if existing and isinstance(existing.thinking_payload, dict) else None)

    if has_mode:
        mode = (_text(payload, 'thinkingMode') or thinking_presets.MODE_NONE).lower()
    elif existing is None:
        mode = thinking_presets.MODE_NONE

    if mode not in thinking_presets.THINKING_MODES:
        raise ModelValidationError(
            'model.thinking.mode.invalid', '/'.join(thinking_presets.THINKING_MODES))

    if mode == thinking_presets.MODE_NONE:
        return (thinking_presets.MODE_NONE, '', None)

    if mode == thinking_presets.MODE_AUTO:
        return (thinking_presets.MODE_AUTO, '', None)

    if mode == thinking_presets.MODE_PRESET:
        if has_preset:
            preset_id = _text(payload, 'thinkingPreset')
        if not preset_id:
            raise ModelValidationError('model.thinking.preset.required')
        preset = thinking_presets.get_preset(preset_id)
        if preset is None:
            raise ModelValidationError('model.thinking.preset.unknown', preset_id)
        keep_snapshot = (
            existing is not None
            and existing.thinking_mode == thinking_presets.MODE_PRESET
            and existing.thinking_preset == preset_id
            and isinstance(existing.thinking_payload, dict)
        )
        if not keep_snapshot:
            stored = thinking_presets.preset_payload(preset)
        return (thinking_presets.MODE_PRESET, preset_id, stored)

    # MODE_CUSTOM
    if has_payload:
        raw = payload.get('thinkingPayload')
        try:
            stored = thinking_presets.validate_custom_payload(raw)
        except thinking_presets.ThinkingConfigError as error:
            raise ModelValidationError(error.key, *error.args)
    elif not (existing is not None
              and existing.thinking_mode == thinking_presets.MODE_CUSTOM
              and isinstance(stored, dict)):
        raise ModelValidationError('model.thinking.payload.invalid')
    return (thinking_presets.MODE_CUSTOM, '', stored)


def _http_error_detail(response) -> str:
    """从 OpenAI 兼容的错误体里取一句可读原因（拿不到就返回空串）。

    LiteLLM 会把关键线索放在 ``error.message`` 里，例如
    ``litellm.NotFoundError: ... Received Model Group=qwen3-32b`` —— 这句话正是
    「清单里有、实际调不通」的第一现场，直接回给管理页比只显示 ``HTTP 404`` 有用。
    """
    try:
        body = response.json()
    except Exception:
        return ''
    if not isinstance(body, dict):
        return ''
    error = body.get('error')
    if isinstance(error, dict):
        message = error.get('message') or error.get('code') or ''
    else:
        # ``detail`` 是 FastAPI / vLLM 直接给的形状（``{"detail": "Method Not Allowed"}``），
        # 不带它就只剩一句 HTTP 状态，排查还得去翻服务端日志。
        message = error or body.get('message') or body.get('detail') or ''
    # 端点错误体里常带换行（LiteLLM 会追加 Available Model Group Fallbacks），
    # 压成一行再回给管理页，否则表格单元格里会出现断行。
    message = ' '.join(str(message).split())
    return f': {message[:300]}' if message else ''


def _probe_exception_message(prefix: str, exc: Exception, url: str = '') -> str:
    """把底层 HTTP 客户端异常归类成用户可读的短句；原始异常只进服务端日志。

    连接测试失败时不能把 ``HTTPConnectionPool(...) / NewConnectionError(...)``
    原样展示在管理页：既泄露内部实现也不便阅读。
    这里保留 fail 前缀与请求 URL（排查路径问题最有用），去掉库内部堆栈文本。
    """
    name = type(exc).__name__
    lowered = f'{name} {exc}'.lower()
    if 'timeout' in lowered or 'timed out' in lowered:
        reason = 'connection timed out'
    elif 'ssl' in lowered or 'certificate' in lowered:
        reason = 'TLS handshake failed'
    elif 'connection' in lowered or 'refused' in lowered:
        reason = 'connection failed'
    else:
        reason = 'request failed'
    suffix = f' (POST {url})' if url else ''
    return f'{prefix}: {reason}{suffix}'


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------
class ModelService:
    """模型注册表的领域服务。"""

    def __init__(self, store, reference_checker: Optional[Callable] = None,
                 http_post: Optional[Callable] = None, http_get: Optional[Callable] = None,
                 on_change: Optional[Callable] = None):
        self._store = store
        #: ``(kind, model_name) -> 引用它的知识库数量``。注入点让单测不碰跨库查询
        self._reference_checker = reference_checker or count_knowledge_bases_using
        self._http_post = http_post
        self._http_get = http_get
        #: 每次写成功后调用。默认让解析层的缓存失效 —— **模型管理接口与解析层在同一个
        #: 进程**，这就是「新增模型立即生效、不需要重启」的全部机制（见 model_resolver）。
        self._on_change = on_change or _invalidate_resolver

    def _notify_changed(self) -> None:
        try:
            self._on_change()
        except Exception:
            # 缓存失效失败不该让写操作回滚：下一次 TTL 到期自然会看到新数据
            from infrastructure.logging.logutil import log

            log.warning('model cache invalidation failed', exc_info=True)

    # -- 读 ---------------------------------------------------------------

    def list_models(self, kind: Optional[str] = None, keyword: str = '',
                    current_page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
        """管理页列表：``{'data': [...], 'recordsTotal': N}``。

        形状由前端 ``components/common/table/tableGroup.vue`` 的 ``returnStructFun``
        定死（它读 ``bo.data`` 与 ``bo.recordsTotal``），别改成别的分页字段名。
        """
        if kind:
            _validate_kind(kind)
        rows = self._store.list_records(kind)
        needle = (keyword or '').strip().lower()
        if needle:
            rows = [r for r in rows
                    if needle in r.model_name.lower() or needle in r.label().lower()
                    or needle in r.base_url.lower()]
        total = len(rows)
        size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
        start = max(0, (max(1, int(current_page or 1)) - 1) * size)
        return paginate([r.to_public() for r in rows[start:start + size]],
                        total, max(1, int(current_page or 1)), size)

    def get_model(self, model_id: str) -> ModelRecord:
        record = self._store.get_record(model_id)
        if record is None:
            raise ModelBusinessError('model.not.found', model_id)
        return record

    def all_records(self, kind: Optional[str] = None) -> list[ModelRecord]:
        """给解析层用（不分页、不脱敏）。"""
        return self._store.list_records(kind)

    def list_thinking_presets(self, kind: Optional[str] = None,
                              model_name: str = '', api_model: str = '',
                              base_url: str = '') -> dict:
        """模型管理页的思考预置目录 + 当前模型名的自动匹配结果。"""
        if kind:
            kind = _validate_kind(kind)
        result = dict(thinking_presets.public_metadata())
        if kind and kind != MODEL_KIND_LLM:
            result.update({
                'presets': [], 'matchedPresetId': '', 'matchedBy': '',
                'confidence': '', 'warning': '',
            })
            return result

        result['presets'] = thinking_presets.public_catalog()
        matched = thinking_presets.match_thinking_preset(
            api_model, model_name, base_url)
        result.update({
            'matchedPresetId': matched.preset.preset_id if matched else '',
            'matchedBy': matched.matched_by if matched else '',
            'confidence': matched.preset.confidence if matched else '',
            'warning': ('no_preset_match' if (api_model or model_name) and not matched else ''),
        })
        return result

    # -- 写 ---------------------------------------------------------------

    def create_model(self, payload: dict, creator: str = '') -> ModelRecord:
        kind = _validate_kind(_text(payload, 'modelKind'))
        model_name = _text(payload, 'modelName')
        if not model_name:
            raise ModelValidationError('model.name.required')
        base_url = _text(payload, 'baseUrl')
        _require_base_url(base_url)
        _require_text_lengths(payload)
        _require_api_key_length(_text(payload, 'apiKey'))

        dimension = _optional_int(payload, 'dimension')
        if kind in _DIMENSION_REQUIRED_KINDS and not dimension:
            raise ModelValidationError('model.dimension.required')

        if self._store.find_by_name(kind, model_name) is not None:
            raise ModelBusinessError('model.name.duplicate', model_name)

        api_model = _text(payload, 'apiModel')
        thinking_mode, thinking_preset, thinking_payload = (
            _normalize_thinking(kind, payload, None))

        record = ModelRecord(
            model_id=new_model_id(),
            model_kind=kind,
            model_name=model_name,
            display_name=_text(payload, 'displayName') or model_name,
            api_model=api_model,
            base_url=base_url,
            api_key=_text(payload, 'apiKey'),
            chat_path=_text(payload, 'chatPath'),
            embeddings_path=_text(payload, 'embeddingsPath'),
            models_path=_text(payload, 'modelsPath'),
            rerank_path=_text(payload, 'rerankPath'),
            dimension=dimension,
            max_tokens=_optional_int(payload, 'maxTokens'),
            temperature=_optional_float(payload, 'temperature'),
            timeout=_optional_int(payload, 'timeout'),
            is_reasoning=bool(payload.get('isReasoning')),
            thinking_mode=thinking_mode,
            thinking_preset=thinking_preset,
            thinking_payload=thinking_payload,
            is_default=bool(payload.get('isDefault')) and bool(payload.get('enabled', True)),
            enabled=bool(payload.get('enabled', True)),
            source=SOURCE_USER,
            remark=_text(payload, 'remark'),
            created_by=creator,
        )
        self._store.insert(record)
        self._notify_changed()
        return record

    def update_model(self, model_id: str, payload: dict) -> ModelRecord:
        """**部分合并**语义：请求里出现的键才改，没出现的保持原值。

        ``apiKey`` 的两个特例（前端拿不到明文，编辑页那个框默认是空的，不能把空当成清空）：

        * 缺席或空串 → **保持不变**；
        * 想清空就显式传 ``clearApiKey: true``。
        """
        existing = self.get_model(model_id)
        merged = existing.to_public()
        merged['modelKind'] = existing.model_kind
        merged['modelName'] = existing.model_name
        merged['baseUrl'] = existing.base_url
        # 路径字段在 to_public 里已经是「生效值」，不能反过来当覆盖值回写 ——
        # 否则「没改路径」会被固化成当前默认值，以后改默认值就不生效了
        for key, field in (('chatPath', 'chat_path'), ('embeddingsPath', 'embeddings_path'),
                           ('modelsPath', 'models_path'), ('rerankPath', 'rerank_path')):
            merged[key] = getattr(existing, field)
        merged['apiModel'] = existing.api_model
        merged['displayName'] = existing.display_name
        merged['apiKey'] = existing.api_key
        merged['isReasoning'] = existing.is_reasoning
        merged['isDefault'] = existing.is_default
        merged['enabled'] = existing.enabled
        merged['dimension'] = existing.dimension
        merged['maxTokens'] = existing.max_tokens
        merged['temperature'] = existing.temperature
        merged['timeout'] = existing.timeout
        merged['remark'] = existing.remark

        merged.update({k: v for k, v in (payload or {}).items() if k != 'apiKey'})
        if _text(payload or {}, 'apiKey'):
            merged['apiKey'] = _text(payload, 'apiKey')
        if payload and payload.get('clearApiKey'):
            merged['apiKey'] = ''

        kind = _validate_kind(_text(merged, 'modelKind'))
        model_name = _text(merged, 'modelName')
        if not model_name:
            raise ModelValidationError('model.name.required')
        base_url = _text(merged, 'baseUrl')
        _require_base_url(base_url)
        new_api_key = _text(payload or {}, 'apiKey')
        if base_url != existing.base_url and not new_api_key:
            # 端点换了却没重新提供 key：不能把旧 key 带过去。否则可以「先改 baseUrl
            # 再 /models/{id}/test」，让服务端把库里保存的凭据发到新端点。
            merged['apiKey'] = ''
        _require_text_lengths(merged)
        new_api_key = _text(payload or {}, 'apiKey')
        if new_api_key:
            _require_api_key_length(new_api_key)

        dimension = _optional_int(merged, 'dimension')
        if kind in _DIMENSION_REQUIRED_KINDS and not dimension:
            raise ModelValidationError('model.dimension.required')

        clash = self._store.find_by_name(kind, model_name)
        if clash is not None and clash.model_id != model_id:
            raise ModelBusinessError('model.name.duplicate', model_name)

        thinking_mode, thinking_preset, thinking_payload = (
            _normalize_thinking(kind, payload or {}, existing))

        updated = existing.with_changes(
            model_kind=kind, model_name=model_name,
            display_name=_text(merged, 'displayName') or model_name,
            api_model=_text(merged, 'apiModel'),
            base_url=base_url,
            api_key=_text(merged, 'apiKey'),
            chat_path=_text(merged, 'chatPath'),
            embeddings_path=_text(merged, 'embeddingsPath'),
            models_path=_text(merged, 'modelsPath'),
            rerank_path=_text(merged, 'rerankPath'),
            dimension=dimension,
            max_tokens=_optional_int(merged, 'maxTokens'),
            temperature=_optional_float(merged, 'temperature'),
            timeout=_optional_int(merged, 'timeout'),
            is_reasoning=bool(merged.get('isReasoning')),
            thinking_mode=thinking_mode,
            thinking_preset=thinking_preset,
            thinking_payload=thinking_payload,
            # 停用的模型不能同时是默认模型：运行时不会调用停用项，留着默认标记会误导 UI。
            is_default=bool(merged.get('isDefault')) and bool(merged.get('enabled', True)),
            enabled=bool(merged.get('enabled', True)),
            remark=_text(merged, 'remark'),
        )
        self._store.update(updated)
        self._notify_changed()
        return updated

    def delete_model(self, model_id: str) -> None:
        record = self.get_model(model_id)
        # 只有 embedding 需要挡：知识库按 model_name 绑定它，删掉不会报错，
        # 只会在下次检索/导入时静默拿不到端点
        if record.model_kind == MODEL_KIND_EMBEDDING:
            used = 0
            try:
                used = int(self._reference_checker(record.model_kind, record.model_name) or 0)
            except Exception:
                # 引用检查失败不该把删除变成不可能（跨库查询失败时宁可放行），但要留痕
                from infrastructure.logging.logutil import log

                log.warning('model reference check failed for %s', record.model_name, exc_info=True)
            if used > 0:
                raise ModelBusinessError('model.in.use', used)
        self._store.delete(model_id)
        self._notify_changed()

    # -- 连接测试 ----------------------------------------------------------

    def test_connection(self, payload: dict) -> dict:
        """真打一次端点，返回结果。**失败不抛错**（要回给管理页显示）。

        返回：``{ok, probed, models, chatOk, chatError, rerankOk, rerankError,
        embeddingsOk, embeddingsError, dimension, dimensionMatches, latencyMs, message}``

        * ``chatOk``：只有 LLM 会填 —— ``True`` 真实调用成功 / ``False`` 真实调用失败 /
          ``None`` 未尝试。**LLM 的 ``ok`` 只由它决定**：``/models`` 清单只说明网关
          「声明」了哪些模型名，不代表模型真的能推理（实测 ``qwen3-32b`` 一直在清单里，
          但 chat 返回 404 ``Received Model Group=...``）。
        * ``rerankOk``：只有 rerank 会填 —— ``True`` 真实调用成功 / ``False`` 真实调用失败 /
          ``None`` 未尝试。**rerank 的 ``ok`` 只由它决定**，理由同上：这类端点通常
          **根本没有** ``/models``（``Qwen3-Reranker-0.6B`` 只提供 ``/rerank`` 与
          ``/v1/models``，按注册行拼出来的 ``/models`` 恒 404）。若不做真实调用，
          正确的重排端点会被报成「端点可达，但无法确认模型清单」、耗时 0ms。
        * ``embeddingsOk``：只有 embedding 会填 —— ``True`` 真实调用成功 / ``False`` 真实调用
          失败 / ``None`` 未尝试。**embedding 的 ``ok`` 只由它决定**。失败时
          ``embeddingsError`` 必须带上**实际请求的 URL 与 HTTP 状态**：路径少一段
          （``/embeddings`` vs ``/v1/embeddings``）正是这类端点最常见的故障，只回一句
          「endpoint unreachable or undetermined」会把人引向网络排查。
        * ``probed``：``True`` 探到模型清单 / ``False`` 端点说没有这条能力 / ``None`` 说不准
        * ``dimension``：只有 embedding 会填（一次最小调用）
        * 这些都不是「模型不可用」的**拒绝依据** —— 契约要求调用方据此**放行**，
          别据 ``ok=False`` 拒绝保存
        """
        kind = _validate_kind(_text(payload, 'modelKind'))
        base_url = _text(payload, 'baseUrl')
        _require_base_url(base_url)
        model_name = _text(payload, 'modelName') or 'probe'
        api_model = _text(payload, 'apiModel')
        thinking_mode, thinking_preset, thinking_payload = (
            _normalize_thinking(kind, payload, None))
        record = ModelRecord(
            model_id='probe', model_kind=kind,
            model_name=model_name,
            base_url=base_url,
            api_model=api_model,
            display_name=_text(payload, 'displayName'),
            api_key=_text(payload, 'apiKey'),
            chat_path=_text(payload, 'chatPath'),
            embeddings_path=_text(payload, 'embeddingsPath'),
            models_path=_text(payload, 'modelsPath'),
            rerank_path=_text(payload, 'rerankPath'),
            dimension=_optional_int(payload, 'dimension'),
            thinking_mode=thinking_mode,
            thinking_preset=thinking_preset,
            thinking_payload=thinking_payload,
        )

        started = time.monotonic()
        result = {
            'ok': False, 'probed': None, 'models': None,
            'chatOk': None, 'chatError': '',
            'rerankOk': None, 'rerankError': '',
            'embeddingsOk': None, 'embeddingsError': '',
            'dimension': None, 'dimensionMatches': None,
            'latencyMs': 0, 'message': '',
        }

        # 清单探测：**只有 LLM 有这条能力**（见 ``DEFAULT_PATHS``），且只作为补充信息
        # （端点声明了哪些名字）。embedding 的证据是维度探测、rerank 的是重排调用。
        # ``path_for('models')`` 对这两类恒为空 —— 行内填了 modelsPath 也不会去拼。
        probed = None
        models_path = record.path_for('models')
        if models_path:
            probed = probe_available_models(
                record.base_url, record.api_key, models_path,
                timeout=TEST_TIMEOUT_SECONDS, http_get=self._http_get)
            if probed is not None:
                result['probed'] = True
                result['models'] = sorted(probed)

        if kind == MODEL_KIND_LLM:
            # 真实调用才是判据：清单里有名字 ≠ 能推理（见模块 docstring 第 1 条）
            chat_ok, chat_error = self._probe_chat(record)
            result['chatOk'] = chat_ok
            result['ok'] = chat_ok
            if chat_ok:
                result['message'] = 'model call succeeded'
                if probed is not None:
                    result['message'] += f'; {len(probed)} model(s) reported by endpoint'
            else:
                result['chatError'] = chat_error
                result['message'] = chat_error

        if kind == MODEL_KIND_EMBEDDING:
            dimension, embeddings_error = self._probe_embedding_dimension(record)
            result['embeddingsOk'] = dimension is not None
            if dimension is not None:
                result['dimension'] = dimension
                result['ok'] = True
                result['dimensionMatches'] = (
                    record.dimension is None or int(record.dimension) == dimension)
                if result['dimensionMatches'] is False:
                    result['message'] = (
                        f'dimension mismatch: endpoint returned {dimension}, '
                        f'registered {record.dimension}')
                else:
                    # 别落到收尾的兜底文案（「…model list undetermined」）——embedding 现在
                    # 压根不探测清单，那句话会让人以为还有一项没确认。
                    result['message'] = 'model call succeeded'
            else:
                # 如实回实际请求的 URL + HTTP 状态：路径少一段是这类端点的头号故障，
                # 兜底的「endpoint unreachable or undetermined」会误导成网络不可达。
                result['embeddingsError'] = embeddings_error
                result['message'] = embeddings_error

        if kind == MODEL_KIND_RERANK:
            # 与 LLM 同一条判据：只有真实调用能证明「这个端点能把候选重排一遍」。
            # 清单探测对 rerank 不适用（默认路径表里没有 models 这条能力）。
            rerank_ok, rerank_error = self._probe_rerank(record)
            result['rerankOk'] = rerank_ok
            result['ok'] = rerank_ok
            if rerank_ok:
                result['message'] = 'model call succeeded'
                if probed is not None:
                    result['message'] += f'; {len(probed)} model(s) reported by endpoint'
            else:
                result['rerankError'] = rerank_error
                result['message'] = rerank_error

        result['latencyMs'] = int((time.monotonic() - started) * 1000)
        if not result['message']:
            result['message'] = ('endpoint reachable but model list undetermined'
                                 if result['ok'] else 'endpoint unreachable or undetermined')
        return result

    def _probe_chat(self, record: ModelRecord) -> tuple[bool, str]:
        """真发一次最小 chat 请求，返回 ``(是否成功, 失败说明)``。

        **这是 LLM 连接测试的唯一有效判据**：``GET /models`` 返回的是网关的
        「声明清单」，实测过清单里有、``POST /chat/completions`` 却 404
        ``Received Model Group=...`` 的情形。请求形状与运行时一致（同 base、路径、key），
        ``model`` 取 ``effective_api_model()``。
        """
        from infrastructure.logging.logutil import log

        url = record.endpoint_for(OP_CHAT)
        if not url:
            return False, 'model call failed: chat path is not configured'
        headers = {'Content-Type': 'application/json'}
        if record.has_api_key():
            headers['Authorization'] = f'Bearer {record.api_key.strip()}'
        body = {
            'model': record.effective_api_model(),
            'messages': [{'role': 'user', 'content': CHAT_TEST_PROMPT}],
            'max_tokens': CHAT_TEST_MAX_TOKENS,
            'stream': False,
        }
        # 保存后该行就是注册表权威配置；探针要与运行时同形状，走同一套解析。
        # 这里不读全局 env：被测行一旦落库，全局开关对它就不再生效。
        thinking_payload = thinking_presets.resolve_payload(
            record.thinking_mode, record.thinking_preset, record.thinking_payload,
            record.effective_api_model(), record.model_name, record.base_url)
        if thinking_payload:
            body.update(thinking_payload)
        post = self._http_post or egress.post
        try:
            response = post(url, json=body, headers=headers,
                            timeout=CHAT_TEST_TIMEOUT_SECONDS)
        except Exception as exc:
            log.warning('chat probe failed to reach %s: %s: %s', url, type(exc).__name__, exc)
            return False, _probe_exception_message('model call failed', exc, url)

        status = getattr(response, 'status_code', None)
        if status is None:
            return False, 'model call failed: endpoint returned no HTTP status'
        if int(status) >= 400:
            detail = _http_error_detail(response)
            return False, f'model call failed: HTTP {status}{detail}'

        log.info('chat probe succeeded for model %s at %s', record.effective_api_model(), url)
        return True, ''

    def _probe_rerank(self, record: ModelRecord) -> tuple[bool, str]:
        """真发一次最小 ``POST {rerank}``，返回 ``(是否成功, 失败说明)``。

        请求形状与运行时（``engine/gateways/llm_proxy_client.invoke_rerank_client``）一致：
        同 base、路径、key，``model`` 取 ``effective_api_model()``。

        **判据是响应能不能被运行时用起来**，不只是 2xx：运行时从 ``results``（或 ``data``）
        里取 ``index`` + ``relevance_score``，缺这两个字段就静默退回原顺序（= 重排没生效）。
        所以这里也要求至少有一条带数值分数的结果，否则如实报失败并说明原因。
        """
        from infrastructure.logging.logutil import log

        url = record.endpoint_for(OP_RERANK)
        if not url:
            return False, 'rerank call failed: rerank path is not configured'
        headers = {'Content-Type': 'application/json'}
        if record.has_api_key():
            headers['Authorization'] = f'Bearer {record.api_key.strip()}'
        body = {
            'model': record.effective_api_model(),
            'query': RERANK_TEST_QUERY,
            'documents': list(RERANK_TEST_DOCUMENTS),
        }
        post = self._http_post or egress.post
        try:
            response = post(url, json=body, headers=headers, timeout=TEST_TIMEOUT_SECONDS)
        except Exception as exc:
            log.warning('rerank probe failed to reach %s: %s: %s', url, type(exc).__name__, exc)
            return False, _probe_exception_message('rerank call failed', exc, url)

        status = getattr(response, 'status_code', None)
        if status is None:
            return False, 'rerank call failed: endpoint returned no HTTP status'
        if int(status) >= 400:
            detail = _http_error_detail(response)
            return False, f'rerank call failed: HTTP {status}{detail}'

        try:
            entity = response.json()
        except ValueError:
            return False, 'rerank call failed: endpoint returned a non-JSON response'
        results = entity.get('results') if isinstance(entity, dict) else None
        if not isinstance(results, list):
            results = entity.get('data') if isinstance(entity, dict) else None
        scored = [item for item in (results or [])
                  if isinstance(item, dict) and item.get('index') is not None
                  and isinstance(item.get('relevance_score'), (int, float))]
        if not scored:
            return False, ('rerank call failed: response has no usable results '
                           '(expected results[].index + relevance_score)')

        log.info('rerank probe succeeded for model %s at %s (%d result(s))',
                 record.effective_api_model(), url, len(scored))
        return True, ''

    def _probe_embedding_dimension(self, record: ModelRecord) -> tuple[Optional[int], str]:
        """打一次 ``input=['hello']``，返回 ``(探测维度, 失败说明)``。

        成功 → ``(维度, '')``；失败 → ``(None, 原因)``。原因里**必须带实际请求的 URL**：
        这类端点最常见的故障是路径少一段（``/embeddings`` vs ``/v1/embeddings``），
        只写「不可达」会让人去查网络。注意 404 在本项目网关上是**二义**的
        （路径不存在与模型名不存在都回 404），所以 URL 与 HTTP 状态要一起摊开。
        """
        from infrastructure.logging.logutil import log

        url = record.endpoint_for(OP_EMBEDDINGS)
        if not url:
            return None, 'model call failed: embeddings path is not configured'
        headers = {'Content-Type': 'application/json'}
        if record.has_api_key():
            headers['Authorization'] = f'Bearer {record.api_key.strip()}'
        post = self._http_post or egress.post
        try:
            response = post(url, json={'input': ['hello'], 'model': record.effective_api_model()},
                            headers=headers, timeout=TEST_TIMEOUT_SECONDS)
            status = getattr(response, 'status_code', None)
            if status is not None and int(status) >= 400:
                detail = _http_error_detail(response)
                message = f'model call failed: HTTP {status}{detail} (POST {url})'
                log.warning('embedding dimension probe failed for %s: HTTP %s', url, status)
                return None, message
            response.raise_for_status()
            data = (response.json() or {}).get('data') or []
            embedding = (data[0] or {}).get('embedding') if data else None
            if not embedding:
                log.warning('embedding dimension probe got no vector from %s', url)
                return None, f'model call failed: response has no embedding vector (POST {url})'
            log.info('embedding dimension probe succeeded for %s (%d dims)',
                     record.effective_api_model(), len(embedding))
            return len(embedding), ''
        except Exception as exc:
            log.warning('embedding dimension probe failed for %s: %s: %s', url, type(exc).__name__, exc)
            return None, _probe_exception_message('model call failed', exc, url)


# ---------------------------------------------------------------------------
# 引用检查（跨库）
# ---------------------------------------------------------------------------
def count_knowledge_bases_using(kind: str, model_name: str) -> int:
    """有多少知识库绑着这个模型。

    知识库的绑定字段在 ``rag_studio`` 库的 ``kb_kbase.embedding_model``（不是 RKB 自有库），
    所以走 ``infrastructure/db/kb.py`` 那个跨库窄开关，而不是默认连接。

    查不到**返回 0**（宁可放行）：引用检查是保护性的附加检查，跨库查询失败时
    把删除变成不可能，比漏拦一次更糟。
    """
    if kind != MODEL_KIND_EMBEDDING:
        return 0
    try:
        from infrastructure.db.kb import connection

        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM kb_kbase WHERE embedding_model = %s",
                    (model_name,),
                )
                row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        from infrastructure.logging.logutil import log

        log.warning('could not count knowledge bases using %s', model_name, exc_info=True)
        return 0
