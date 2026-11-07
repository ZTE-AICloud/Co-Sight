"""模型注册表的领域模型（LLM / Embedding / Reranker 三类）。

**这张表的职责**：「本部署有哪些模型」的配置来源是 ``deploy/.env``
（``GENERATION_MODELS`` / ``REASONING_MODELS`` / ``RERANK_URL`` / ``EMBEDDING_*``）；
本表把模型定义变成**数据库里的行**，新增模型不需要改配置或重启容器。
契约说明见 ``contracts/model-gateway.md``「模型清单与动态纳管」一节。

**两个命名空间不要合并**（沿用约定，见
``contracts/model-gateway.md``）：``model_name`` 是**注册名**（下拉里显示、
``kb_kbase.embedding_model`` 里记的也是它），``api_model`` 才是**发给端点的
``model`` 字段**。embedding 侧分别对应 ``kb_embedding.model_name`` / ``model_code``
（该表已不存在，命名空间约定保留）。

**四个路径字段都要留**：契约里不同 OpenAI 兼容实现的路径不同
（``/embeddings`` vs ``/v1/embeddings``、``/models`` vs ``/v1/models``），
所以路径必须可配、不能写死。留空 = 用 :data:`DEFAULT_PATHS` 里的标准值。
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field, replace
from typing import Optional

from model import thinking_presets

# ---------------------------------------------------------------------------
# 三类模型
# ---------------------------------------------------------------------------
MODEL_KIND_LLM = 'llm'
MODEL_KIND_EMBEDDING = 'embedding'
MODEL_KIND_RERANK = 'rerank'
#: 顺序即管理页页签顺序
MODEL_KINDS = (MODEL_KIND_LLM, MODEL_KIND_EMBEDDING, MODEL_KIND_RERANK)

# ---------------------------------------------------------------------------
# 行来源（管理页上要能看出「这条是哪来的」）
# ---------------------------------------------------------------------------
#: 首次启动从环境变量（= ``deploy/.env``）播种进来的
SOURCE_ENV = 'env'
#: 用户在本管理页里登记的
SOURCE_USER = 'user'
SOURCE_VALUES = (SOURCE_ENV, SOURCE_USER)

# ---------------------------------------------------------------------------
# 各操作的路径名（``ModelRecord.path_for`` 的入参）
# ---------------------------------------------------------------------------
OP_CHAT = 'chat'
OP_EMBEDDINGS = 'embeddings'
OP_MODELS = 'models'
OP_RERANK = 'rerank'

#: 每个 kind 支持哪些操作 → 对应的字段名与 OpenAI 标准默认路径。
#: 默认值取 OpenAI 官方路径；常见两种偏差实现（Infinity 的 ``/embeddings``、
#: LiteLLM 的 ``/models``）靠**每行单独覆盖**解决，不要改这里的默认值。
#:
#: **``models`` 只属于 LLM**：它的消费者只有两处，且都是生成端点
#: —— 发布校验（``workflow.validation.find_unavailable_models``）与连接测试的补充信息。
#: embedding / rerank 端点的判据分别是**维度探测**与**重排调用**，清单探测对它们
#: 没有消费者；gateway ``/models`` 与 ``/v1/models`` 均 404、vLLM 重排端点只有
#: ``/v1/models``（按 base 拼 ``/models`` 恒 404）。留着只会每次测试白打一个必失败的
#: 请求，并在结果表里多一行「无法判定」误导人。
DEFAULT_PATHS: dict[str, dict[str, str]] = {
    MODEL_KIND_LLM: {OP_CHAT: '/chat/completions', OP_MODELS: '/models'},
    MODEL_KIND_EMBEDDING: {OP_EMBEDDINGS: '/embeddings'},
    MODEL_KIND_RERANK: {OP_RERANK: '/rerank'},
}

_PATH_FIELDS = {
    OP_CHAT: 'chat_path',
    OP_EMBEDDINGS: 'embeddings_path',
    OP_MODELS: 'models_path',
    OP_RERANK: 'rerank_path',
}


def new_model_id() -> str:
    """注册行主键。用 uuid4 而不是自增：播种行与用户行混在一起，自增号会被重排。"""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class ModelRecord:
    """一行注册记录。

    frozen：读写路径都把它当**不可变快照**传递（解析层会缓存实例，就地改会让缓存失效
    变成竞态）。要改字段用 :func:`dataclasses.replace` 造新实例。
    """

    model_id: str
    model_kind: str
    model_name: str
    base_url: str
    display_name: str = ''
    api_model: str = ''
    api_key: str = ''
    chat_path: str = ''
    embeddings_path: str = ''
    models_path: str = ''
    rerank_path: str = ''
    dimension: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    timeout: Optional[int] = None
    is_reasoning: bool = False
    #: 思考配置意图：none / auto / preset / custom（仅 LLM 有意义）。
    thinking_mode: str = thinking_presets.MODE_NONE
    thinking_preset: str = ''
    thinking_payload: Optional[dict] = None
    is_default: bool = False
    enabled: bool = True
    source: str = SOURCE_USER
    remark: str = ''
    created_at: str = ''
    updated_at: str = ''
    created_by: str = ''
    #: 非持久化字段：测试/解析层用它标注「这条实际是回落来的」。
    #: ``repr=False`` 免得日志里把它当成库里的列。
    origin: str = field(default='registry', repr=False, compare=False)

    # -- 派生 ---------------------------------------------------------------

    def effective_api_model(self) -> str:
        """发给端点的 ``model`` 字段。留空 = 与注册名同（最常见的情形）。"""
        return (self.api_model or '').strip() or self.model_name

    def label(self) -> str:
        """下拉里显示的名字。留空 = 用注册名。"""
        return (self.display_name or '').strip() or self.model_name

    def path_for(self, operation: str) -> str:
        """某操作的实际路径：行内覆盖优先，否则取该类模型的标准默认。

        不支持的操作返回空串 —— 调用方据此判「这个端点没这个能力」，不要瞎拼路径。
        """
        default = DEFAULT_PATHS.get(self.model_kind, {}).get(operation)
        if default is None:
            return ''
        override = (getattr(self, _PATH_FIELDS[operation], '') or '').strip()
        return override or default

    def endpoint_for(self, operation: str) -> str:
        """完整 URL（``base_url`` 去尾斜杠 + 路径）。不支持的操作返回空串。

        **路径可以是绝对 URL**：历史配置里 ``RERANK_URL`` 这类变量记的是**完整 URL**
        而不是 base，播种时拆不开就把它整个塞进路径字段（见 ``seed.split_endpoint_url``）。
        这时原样返回它，绝不把 base 再拼一遍 —— 拼出来的地址错得很难看出来。
        """
        path = self.path_for(operation)
        if not path:
            return ''
        if path.startswith('http://') or path.startswith('https://'):
            return path
        return self.base_url.rstrip('/') + path

    def has_api_key(self) -> bool:
        return bool((self.api_key or '').strip())

    def masked_api_key(self) -> str:
        """脱敏后的 key。

        **只保留末 4 位**：足够让人认出「是不是那一把」，又不足以拿去用。
        短于 8 位的 key 一律整串打码（保留末 4 位等于泄露一半）。
        """
        key = (self.api_key or '').strip()
        if not key:
            return ''
        return '****' + key[-4:] if len(key) >= 8 else '****'

    # -- 序列化 -------------------------------------------------------------

    def _public_thinking_fields(self, mode: str) -> dict:
        """把「思考配置」解析成可回写的意图字段 + 只读派生字段。"""
        matched = None
        preset = None
        warning = ''
        payload = None
        if mode == thinking_presets.MODE_AUTO:
            matched = thinking_presets.match_thinking_preset(
                self.effective_api_model(), self.model_name, self.base_url)
            if matched is None:
                warning = 'no_preset_match'
        elif mode == thinking_presets.MODE_PRESET:
            preset = thinking_presets.get_preset(self.thinking_preset)
            if preset is None:
                warning = 'preset_missing'
            payload = (copy.deepcopy(self.thinking_payload)
                       if isinstance(self.thinking_payload, dict)
                       else (thinking_presets.preset_payload(preset) if preset else None))
        elif mode == thinking_presets.MODE_CUSTOM:
            payload = (copy.deepcopy(self.thinking_payload)
                       if isinstance(self.thinking_payload, dict) else None)
        return {
            'thinkingMode': mode,
            'thinkingPreset': self.thinking_preset,
            'thinkingPayload': payload,
            'thinkingMatchedPresetId': matched.preset.preset_id if matched else '',
            'thinkingMatchedPresetLabel': matched.preset.label_zh if matched else '',
            'thinkingMatchedPresetLabelEn': matched.preset.label_en if matched else '',
            'thinkingPresetLabel': preset.label_zh if preset else '',
            'thinkingPresetLabelEn': preset.label_en if preset else '',
            'thinkingWarning': warning,
        }

    def to_public(self) -> dict:
        """对外 JSON（camelCase，与 kb_api 其余端点的字段风格一致）。

        **绝不返回明文 api_key** —— 只回 ``apiKeyMasked`` 与 ``hasApiKey``。

        ``thinkingMode/Preset/Payload`` 是**用户意图**（可回写）；
        ``thinkingMatchedPreset*`` / ``thinkingWarning`` 是只读派生值，
        更新接口绝不能把它们当输入再写回，否则 auto 会被冻结成某个预置。
        """
        mode = (self.thinking_mode or thinking_presets.MODE_NONE).strip().lower()
        if mode not in thinking_presets.THINKING_MODES:
            mode = thinking_presets.MODE_NONE
        if self.model_kind != MODEL_KIND_LLM:
            mode = thinking_presets.MODE_NONE

        return {
            'modelId': self.model_id,
            'modelKind': self.model_kind,
            'modelName': self.model_name,
            'displayName': self.label(),
            'apiModel': self.effective_api_model(),
            'baseUrl': self.base_url,
            'apiKeyMasked': self.masked_api_key(),
            'hasApiKey': self.has_api_key(),
            'chatPath': self.path_for(OP_CHAT),
            'embeddingsPath': self.path_for(OP_EMBEDDINGS),
            'modelsPath': self.path_for(OP_MODELS),
            'rerankPath': self.path_for(OP_RERANK),
            'dimension': self.dimension,
            'maxTokens': self.max_tokens,
            'temperature': self.temperature,
            'timeout': self.timeout,
            'isReasoning': self.is_reasoning,
            **self._public_thinking_fields(mode),
            'isDefault': self.is_default,
            'enabled': self.enabled,
            'source': self.source,
            'remark': self.remark,
            'createTime': self.created_at,
            'modifyTime': self.updated_at,
            'creator': self.created_by,
        }

    def with_changes(self, **changes) -> 'ModelRecord':
        """造一个改了若干字段的新实例（不就地改，见类 docstring）。"""
        return replace(self, **changes)
