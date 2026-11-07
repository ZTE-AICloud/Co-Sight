"""模型「思考配置」的预置目录、自动匹配与 payload 校验。

背景：关闭/压低模型的思考过程，各家字段并不相同：
DeepSeek 自建常用 ``chat_template_kwargs.thinking=false``，Qwen3 用
``chat_template_kwargs.enable_thinking=false``，GLM/Kimi/MiniMax/豆包/混元/星火
用顶层 ``thinking.type=disabled``，OpenAI 用 ``reasoning_effort``，Gemini 用
``google.thinking_config``。把某一个字段写死在适配器里只对一家成立（上一版就是
这样），所以这里把「常见写法」收成目录，按模型名 + 端点自动匹配；不认识的模型
让用户在模型管理页选预置或写自定义 JSON。

匹配规则（顺序即优先级）：
1. 先对 ``api_model`` 匹配，再对 ``model_name``；
2. 每个候选先试**端点特定**预置（如 api.deepseek.com / dashscope / bigmodel），
   再试通用（vLLM/SGLang）预置；
3. 全局排除只思考、不可关闭的模型（``*-thinking``、QwQ、Kimi K3、MiniMax M1/M2、
   GLM-5 等），排除项不返回预置，用户仍可用自定义 JSON。

payload 是**直接合并进 OpenAI Chat Completions 请求体**的顶层片段；只允许下列
安全键，避免模型行覆盖 ``model``/``messages``/``stream`` 等调用契约：
``chat_template_kwargs``、``thinking``、``reasoning_effort``、``enable_thinking``、
``google``。
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# 模式与 payload 约束
# ---------------------------------------------------------------------------
MODE_NONE = 'none'
MODE_AUTO = 'auto'
MODE_PRESET = 'preset'
MODE_CUSTOM = 'custom'
THINKING_MODES = (MODE_NONE, MODE_AUTO, MODE_PRESET, MODE_CUSTOM)

#: 调用场景：answer = 回答生成，用模型管理页的每模型配置；
#: aux = 改写/重排/路由等辅助调用，只按目录自动用关闭/最低思考的预置，
#:       **不读取模型行的 preset/custom**（避免回答侧的高推理漏到辅助调用）。
PROFILE_ANSWER = 'answer'
PROFILE_AUX = 'aux'
THINKING_PROFILES = (PROFILE_ANSWER, PROFILE_AUX)

#: DeepSeek 自建（vLLM/SGLang）关闭思考的 payload，也是目录里 ``deepseek-vllm`` 用的片段。
DEEPSEEK_VLLM_OFF_PAYLOAD = {'chat_template_kwargs': {'thinking': False}}

#: 自定义 payload 允许的顶层键（白名单，不是黑名单）。
ALLOWED_PAYLOAD_KEYS = frozenset({
    'chat_template_kwargs',
    'thinking',
    'reasoning_effort',
    'enable_thinking',
    'google',
})

#: payload 序列化后的上限（UTF-8 字节）。思考参数是很小的配置，不需要很大。
MAX_PAYLOAD_BYTES = 8192

CONFIDENCE_VERIFIED = 'verified'
CONFIDENCE_STANDARD = 'standard-doc'


class ThinkingConfigError(ValueError):
    """payload/模式校验失败；``key`` 是 model_api 文案表里的键。"""

    def __init__(self, key: str, *args) -> None:
        super().__init__(key)
        self.key = key
        self.args = args


# ---------------------------------------------------------------------------
# 目录条目
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ThinkingPreset:
    preset_id: str
    label_zh: str
    label_en: str
    note_zh: str
    note_en: str
    payload: dict
    model_patterns: tuple = ()
    endpoint_patterns: tuple = ()
    exclude_patterns: tuple = ()
    full_off: bool = True
    confidence: str = CONFIDENCE_STANDARD


@dataclass(frozen=True)
class ThinkingMatch:
    preset: ThinkingPreset
    matched_by: str  # api_model / model_name


#: 全局排除：这些是「只思考/不可关闭」或明确拒绝关闭参数的形态。
#: 命中的模型不会返回预置；UI 会提示用户选自定义或不配置。
EXCLUDED_MODEL_PATTERNS = (
    r'-thinking($|[-/.])',
    r'^thinking-',
    r'^(qwq|qvq)([-/]|$)',
    r'^deepseek-r1($|[-/.])',
    r'^deepseek-reasoner($|[-/.])',
    r'^kimi-k3($|[-/.])',
    r'^minimax-m[12]($|[.-])',
    r'^minimax-m3\.1-flash($|[.-])',
    r'^glm-?5($|[.\-])',
)


def _p(preset_id, label_zh, label_en, note_zh, note_en, payload, *,
       model_patterns=(), endpoint_patterns=(), exclude_patterns=(),
       full_off=True, confidence=CONFIDENCE_STANDARD) -> ThinkingPreset:
    return ThinkingPreset(
        preset_id=preset_id,
        label_zh=label_zh,
        label_en=label_en,
        note_zh=note_zh,
        note_en=note_en,
        payload=payload,
        model_patterns=tuple(model_patterns),
        endpoint_patterns=tuple(endpoint_patterns),
        exclude_patterns=tuple(exclude_patterns),
        full_off=full_off,
        confidence=confidence,
    )


#: 端点特定项在前，通用项在后。匹配函数本身会分两轮（先端点特定、再通用），
#: 这里保持顺序也让公开目录更容易读。
PRESETS: tuple[ThinkingPreset, ...] = (
    _p(
        'deepseek-official', 'DeepSeek 官方 API', 'DeepSeek official API',
        '顶层 thinking.type=disabled；官方 API 默认开启思考。',
        'Top-level thinking.type=disabled; the official API has thinking on by default.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'deepseek',),
        endpoint_patterns=(r'api\.deepseek\.com',),
    ),
    _p(
        'deepseek-vllm', 'DeepSeek（vLLM/SGLang）', 'DeepSeek (vLLM/SGLang)',
        'chat_template_kwargs.thinking=false；本部署 deepseek-chat 实测有效。',
        'chat_template_kwargs.thinking=false; verified on deepseek-chat in this deployment.',
        DEEPSEEK_VLLM_OFF_PAYLOAD,
        model_patterns=(r'deepseek',),
        confidence=CONFIDENCE_VERIFIED,
    ),
    _p(
        'qwen-dashscope', 'Qwen3（DashScope）', 'Qwen3 (DashScope)',
        '顶层 enable_thinking=false；阿里云百炼/DashScope。',
        'Top-level enable_thinking=false; Alibaba Cloud DashScope.',
        {'enable_thinking': False},
        model_patterns=(r'^qwen3', r'^qwen-(plus|max|turbo)'),
        endpoint_patterns=(r'dashscope|aliyuncs',),
    ),
    _p(
        'qwen-vllm', 'Qwen3（vLLM/SGLang）', 'Qwen3 (vLLM/SGLang)',
        'chat_template_kwargs.enable_thinking=false；自建 vLLM/SGLang 模板。',
        'chat_template_kwargs.enable_thinking=false; self-hosted vLLM/SGLang template.',
        {'chat_template_kwargs': {'enable_thinking': False}},
        model_patterns=(r'^qwen3', r'^qwen-(plus|max|turbo)'),
    ),
    _p(
        'glm-hosted', 'GLM-4.5/4.6/4.7（智谱）', 'GLM-4.5/4.6/4.7 (Z.AI)',
        '顶层 thinking.type=disabled；智谱 BigModel/Z.AI。',
        'Top-level thinking.type=disabled; Zhipu BigModel/Z.AI.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^glm-?4\.(5|6|7)',),
        endpoint_patterns=(r'bigmodel|z\.ai',),
    ),
    _p(
        'glm-vllm', 'GLM-4.5/4.6/4.7（vLLM/SGLang）', 'GLM-4.5/4.6/4.7 (vLLM/SGLang)',
        'chat_template_kwargs.enable_thinking=false；自建模板。',
        'chat_template_kwargs.enable_thinking=false; self-hosted template.',
        {'chat_template_kwargs': {'enable_thinking': False}},
        model_patterns=(r'^glm-?4\.(5|6|7)',),
    ),
    _p(
        'kimi-k2-hybrid', 'Kimi K2（混合模型）', 'Kimi K2 (hybrid)',
        '顶层 thinking.type=disabled；K2 Thinking/K3 不可关闭。',
        'Top-level thinking.type=disabled; K2 Thinking/K3 cannot be disabled.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^kimi-k2',),
        exclude_patterns=(r'thinking', r'k2\.7-code', r'k3'),
    ),
    _p(
        'minimax-m3', 'MiniMax M3', 'MiniMax M3',
        '顶层 thinking.type=disabled；M1/M2 不可关，M3.1-Flash 会拒绝。',
        'Top-level thinking.type=disabled; M1/M2 cannot disable, M3.1-Flash rejects it.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^minimax-m3(\.1)?$',),
        exclude_patterns=(r'flash',),
    ),
    _p(
        'openai-gpt51', 'GPT-5.1', 'GPT-5.1',
        'reasoning_effort=none；GPT-5.1+ 可完全关闭。',
        'reasoning_effort=none; GPT-5.1+ can turn reasoning off.',
        {'reasoning_effort': 'none'},
        model_patterns=(r'^gpt-5\.1',),
    ),
    _p(
        'openai-gpt5', 'GPT-5', 'GPT-5',
        'reasoning_effort=minimal；只能降到最低档，不能完全关闭。',
        'reasoning_effort=minimal; lowest level only, not a full off switch.',
        {'reasoning_effort': 'minimal'},
        model_patterns=(r'^gpt-5(?!\.1)',),
        full_off=False,
    ),
    _p(
        'openai-o-series', 'o1/o3/o4', 'o1/o3/o4',
        'reasoning_effort=low；只能降到最低档，不能完全关闭。',
        'reasoning_effort=low; lowest level only, not a full off switch.',
        {'reasoning_effort': 'low'},
        model_patterns=(r'^o[134](-|$)',),
        full_off=False,
    ),
    _p(
        'gemini-25-flash', 'Gemini 2.5 Flash', 'Gemini 2.5 Flash',
        'google.thinking_config.thinking_budget=0；取决于网关是否透传该字段。',
        'google.thinking_config.thinking_budget=0; depends on gateway passthrough.',
        {'google': {'thinking_config': {'thinking_budget': 0}}},
        model_patterns=(r'^gemini-2\.5-(flash|flash-lite)',),
    ),
    _p(
        'gemini-3', 'Gemini 3', 'Gemini 3',
        'reasoning_effort=minimal；仅最低档，可能仍会思考。',
        'reasoning_effort=minimal; lowest level, may still think.',
        {'reasoning_effort': 'minimal'},
        model_patterns=(r'^gemini-3',),
        full_off=False,
    ),
    _p(
        'doubao', '豆包 Doubao', 'Doubao',
        '顶层 thinking.type=disabled；火山方舟，部分模型支持。',
        'Top-level thinking.type=disabled; Volcengine Ark, model-dependent.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^doubao-',),
    ),
    _p(
        'hunyuan', '腾讯混元', 'Tencent Hunyuan',
        '顶层 thinking.type=disabled；部分模型支持。',
        'Top-level thinking.type=disabled; model-dependent.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^hunyuan-',),
    ),
    _p(
        'spark', '讯飞星火', 'iFlytek Spark',
        '顶层 thinking.type=disabled；X1/X2 系列。',
        'Top-level thinking.type=disabled; X1/X2 family.',
        {'thinking': {'type': 'disabled'}},
        model_patterns=(r'^spark-', r'^x[12](-|$)'),
    ),
    _p(
        'ernie-vllm', '文心 ERNIE（自建）', 'ERNIE (self-hosted)',
        'chat_template_kwargs.enable_thinking=false；自建 FastDeploy，托管千帆字段未确认。',
        'chat_template_kwargs.enable_thinking=false; self-hosted FastDeploy; hosted Qianfan unconfirmed.',
        {'chat_template_kwargs': {'enable_thinking': False}},
        model_patterns=(r'^ernie-',),
    ),
)

_PRESET_BY_ID = {preset.preset_id: preset for preset in PRESETS}
assert len(_PRESET_BY_ID) == len(PRESETS), 'preset id 不能重复'


# ---------------------------------------------------------------------------
# 名称与匹配
# ---------------------------------------------------------------------------
def normalize_model_name(name: str) -> str:
    """注册名/端点名归一：去空白、小写、去掉 ``org/`` 前缀。"""
    normalized = (name or '').strip().lower()
    if '/' in normalized:
        normalized = normalized.rsplit('/', 1)[-1]
    return normalized


def _search(patterns, text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def match_thinking_preset(api_model: str = '', model_name: str = '',
                          base_url: str = '') -> Optional[ThinkingMatch]:
    """按端点名、注册名、端地址匹配预置；没有匹配返回 ``None``。"""
    endpoint = (base_url or '').strip()

    for matched_by, raw_name in (('api_model', api_model), ('model_name', model_name)):
        name = normalize_model_name(raw_name)
        if not name or _search(EXCLUDED_MODEL_PATTERNS, name):
            continue

        # 第一轮：端点特定（DeepSeek 官方 / DashScope / 智谱托管）
        for preset in PRESETS:
            if not preset.endpoint_patterns:
                continue
            if not endpoint or not _search(preset.endpoint_patterns, endpoint):
                continue
            if _search(preset.exclude_patterns, name):
                continue
            if _search(preset.model_patterns, name):
                return ThinkingMatch(preset=preset, matched_by=matched_by)

        # 第二轮：通用自建（vLLM/SGLang 等）
        for preset in PRESETS:
            if preset.endpoint_patterns:
                continue
            if _search(preset.exclude_patterns, name):
                continue
            if _search(preset.model_patterns, name):
                return ThinkingMatch(preset=preset, matched_by=matched_by)

    return None


def get_preset(preset_id: str) -> Optional[ThinkingPreset]:
    return _PRESET_BY_ID.get((preset_id or '').strip())


def preset_payload(preset: ThinkingPreset) -> dict:
    return copy.deepcopy(preset.payload)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def resolve_payload(mode: str, preset_id: str = '', stored_payload=None,
                    api_model: str = '', model_name: str = '',
                    base_url: str = '',
                    profile: str = PROFILE_ANSWER) -> Optional[dict]:
    """把「意图」解析成最终请求片段；``None`` = 不发送。

    ``profile='aux'`` 用于改写/重排/路由这些**不需要思考**的调用：
    只按模型名匹配预置目录（关闭或最低档），**不读取**模型行的 preset/custom；
    目录未覆盖的模型返回 ``None``（不发送）。模型行的配置只管回答生成。
    """
    normalized_mode = (mode or MODE_NONE).strip().lower()

    if (profile or PROFILE_ANSWER).strip().lower() == PROFILE_AUX:
        matched = match_thinking_preset(api_model, model_name, base_url)
        return preset_payload(matched.preset) if matched else None

    if normalized_mode == MODE_AUTO:
        matched = match_thinking_preset(api_model, model_name, base_url)
        return preset_payload(matched.preset) if matched else None

    if normalized_mode == MODE_PRESET:
        preset = get_preset(preset_id)
        if isinstance(stored_payload, dict):
            return copy.deepcopy(stored_payload)
        if preset is not None:
            return preset_payload(preset)
        # 目录里已经没有这个 ID（升级/改名）：退回自动匹配，避免静默发错。
        matched = match_thinking_preset(api_model, model_name, base_url)
        return preset_payload(matched.preset) if matched else None

    if normalized_mode == MODE_CUSTOM:
        return copy.deepcopy(stored_payload) if isinstance(stored_payload, dict) else None

    return None


# ---------------------------------------------------------------------------
# 校验与公开目录
# ---------------------------------------------------------------------------
def _serialized_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def validate_custom_payload(value) -> dict:
    """校验自定义 payload；失败抛 :class:`ThinkingConfigError`。"""
    if not isinstance(value, dict) or not value:
        raise ThinkingConfigError('model.thinking.payload.invalid')

    for key, item in value.items():
        if key not in ALLOWED_PAYLOAD_KEYS:
            raise ThinkingConfigError('model.thinking.payload.key', key)
        if key == 'chat_template_kwargs' and not isinstance(item, dict):
            raise ThinkingConfigError('model.thinking.payload.invalid', key)
        if key == 'thinking' and not isinstance(item, (dict, bool)):
            raise ThinkingConfigError('model.thinking.payload.invalid', key)
        if key == 'reasoning_effort' and not (
                isinstance(item, str) and item.strip()):
            raise ThinkingConfigError('model.thinking.payload.invalid', key)
        if key == 'enable_thinking' and not isinstance(item, bool):
            raise ThinkingConfigError('model.thinking.payload.invalid', key)
        if key == 'google' and not isinstance(item, dict):
            raise ThinkingConfigError('model.thinking.payload.invalid', key)

    if _serialized_size(value) > MAX_PAYLOAD_BYTES:
        raise ThinkingConfigError('model.thinking.payload.tooLarge', MAX_PAYLOAD_BYTES)
    return copy.deepcopy(value)


def public_catalog() -> list:
    """给管理页的只读目录（中英双份 label/note，前端按语言选）。"""
    return [
        {
            'presetId': preset.preset_id,
            'label': preset.label_zh,
            'labelEn': preset.label_en,
            'note': preset.note_zh,
            'noteEn': preset.note_en,
            'payload': preset_payload(preset),
            'fullOff': preset.full_off,
            'confidence': preset.confidence,
        }
        for preset in PRESETS
    ]


def public_metadata() -> dict:
    return {
        'modes': list(THINKING_MODES),
        'allowedPayloadKeys': sorted(ALLOWED_PAYLOAD_KEYS),
        'maxPayloadBytes': MAX_PAYLOAD_BYTES,
    }


# 目录自带 payload 在 import 期就按同一套白名单校验一遍，防止手写错键。
for _preset in PRESETS:
    validate_custom_payload(_preset.payload)
