"""每模型思考配置目录：匹配优先级、排除项、payload 校验与解析。"""

import json

import pytest

from model import thinking_presets as tp


# ---------------------------------------------------------------------------
# 目录与匹配
# ---------------------------------------------------------------------------
def test_preset_ids_are_unique_and_payloads_are_whitelisted():
    ids = [preset.preset_id for preset in tp.PRESETS]
    assert len(ids) == len(set(ids))
    for preset in tp.PRESETS:
        assert tp.validate_custom_payload(preset.payload) == preset.payload
        assert preset.confidence in (tp.CONFIDENCE_VERIFIED, tp.CONFIDENCE_STANDARD)


def test_endpoint_specific_preset_beats_generic_for_deepseek():
    official = tp.match_thinking_preset(
        'deepseek-chat', '', 'https://api.deepseek.com/v1')
    self_hosted = tp.match_thinking_preset(
        'deepseek-chat', '', 'http://10.0.0.1:4000/v1')

    assert official.preset.preset_id == 'deepseek-official'
    assert official.preset.payload == {'thinking': {'type': 'disabled'}}
    assert self_hosted.preset.preset_id == 'deepseek-vllm'
    assert self_hosted.preset.payload == tp.DEEPSEEK_VLLM_OFF_PAYLOAD
    assert self_hosted.preset.confidence == tp.CONFIDENCE_VERIFIED


def test_qwen_dashscope_vs_vllm():
    dashscope = tp.match_thinking_preset(
        '', 'qwen3-32b', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    vllm = tp.match_thinking_preset('', 'qwen3-32b', 'http://10.0.0.1:4000/v1')

    assert dashscope.preset.preset_id == 'qwen-dashscope'
    assert dashscope.preset.payload == {'enable_thinking': False}
    assert vllm.preset.preset_id == 'qwen-vllm'
    assert vllm.preset.payload == {'chat_template_kwargs': {'enable_thinking': False}}


def test_glm_hosted_vs_vllm():
    hosted = tp.match_thinking_preset('', 'glm-4.6', 'https://open.bigmodel.cn/api/paas/v4')
    vllm = tp.match_thinking_preset('', 'glm-4.6', 'http://10.0.0.1:4000/v1')

    assert hosted.preset.preset_id == 'glm-hosted'
    assert hosted.preset.payload == {'thinking': {'type': 'disabled'}}
    assert vllm.preset.preset_id == 'glm-vllm'


def test_api_model_wins_over_model_name():
    matched = tp.match_thinking_preset(
        'deepseek-chat', 'qwen3-32b', 'http://10.0.0.1:4000/v1')
    assert matched.preset.preset_id == 'deepseek-vllm'
    assert matched.matched_by == 'api_model'


def test_openal_and_gemini_presets():
    assert tp.match_thinking_preset('gpt-5.1', '', '').preset.preset_id == 'openai-gpt51'
    assert tp.match_thinking_preset('gpt-5', '', '').preset.preset_id == 'openai-gpt5'
    assert tp.match_thinking_preset('o3-mini', '', '').preset.preset_id == 'openai-o-series'
    assert tp.match_thinking_preset('gemini-2.5-flash', '', '').preset.preset_id == 'gemini-25-flash'
    assert tp.match_thinking_preset('gemini-3-pro', '', '').preset.preset_id == 'gemini-3'


@pytest.mark.parametrize('name', [
    'qwen3-235b-a22b-thinking-2507',
    'qwq-plus',
    'qvq-max',
    'kimi-k3',
    'kimi-k2-thinking',
    'minimax-m1',
    'minimax-m2.5',
    'minimax-m3.1-flash',
    'glm-5',
    'deepseek-r1',
])
def test_models_that_cannot_disable_thinking_have_no_preset(name):
    assert tp.match_thinking_preset(name, '', 'http://10.0.0.1:4000/v1') is None


def test_unknown_model_has_no_match():
    assert tp.match_thinking_preset('my-private-model', '', 'http://10.0.0.1:4000/v1') is None


# ---------------------------------------------------------------------------
# payload 校验
# ---------------------------------------------------------------------------
def test_custom_payload_accepts_all_whitelisted_keys():
    payload = {
        'chat_template_kwargs': {'enable_thinking': False},
        'thinking': {'type': 'disabled'},
        'reasoning_effort': 'none',
        'enable_thinking': False,
        'google': {'thinking_config': {'thinking_budget': 0}},
    }
    assert tp.validate_custom_payload(payload) == payload


@pytest.mark.parametrize('value', [None, [], 'x', 1, {}])
def test_custom_payload_rejects_non_object_or_empty(value):
    with pytest.raises(tp.ThinkingConfigError) as exc:
        tp.validate_custom_payload(value)
    assert exc.value.key == 'model.thinking.payload.invalid'


def test_custom_payload_rejects_reserved_keys():
    with pytest.raises(tp.ThinkingConfigError) as exc:
        tp.validate_custom_payload({'messages': []})
    assert exc.value.key == 'model.thinking.payload.key'
    assert exc.value.args == ('messages',)


@pytest.mark.parametrize('payload', [
    {'chat_template_kwargs': 'x'},
    {'thinking': 1},
    {'reasoning_effort': ''},
    {'enable_thinking': 'false'},
    {'google': []},
])
def test_custom_payload_rejects_wrong_types(payload):
    with pytest.raises(tp.ThinkingConfigError) as exc:
        tp.validate_custom_payload(payload)
    assert exc.value.key == 'model.thinking.payload.invalid'


def test_custom_payload_size_limit():
    payload = {'chat_template_kwargs': {'padding': 'x' * tp.MAX_PAYLOAD_BYTES}}
    with pytest.raises(tp.ThinkingConfigError) as exc:
        tp.validate_custom_payload(payload)
    assert exc.value.key == 'model.thinking.payload.tooLarge'


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def test_resolve_none_returns_nothing():
    assert tp.resolve_payload(tp.MODE_NONE) is None


def test_resolve_auto_uses_catalog():
    assert tp.resolve_payload(
        tp.MODE_AUTO, api_model='deepseek-chat',
        base_url='http://10.0.0.1:4000/v1') == tp.DEEPSEEK_VLLM_OFF_PAYLOAD
    assert tp.resolve_payload(tp.MODE_AUTO, api_model='unknown') is None


def test_resolve_preset_prefers_snapshot_then_catalog():
    snapshot = {'thinking': {'type': 'disabled'}}
    assert tp.resolve_payload(
        tp.MODE_PRESET, preset_id='deepseek-official', stored_payload=snapshot) == snapshot
    assert tp.resolve_payload(
        tp.MODE_PRESET, preset_id='deepseek-official') == {'thinking': {'type': 'disabled'}}
    # 未知 preset 退回自动匹配
    assert tp.resolve_payload(
        tp.MODE_PRESET, preset_id='gone', api_model='deepseek-chat') == tp.DEEPSEEK_VLLM_OFF_PAYLOAD


def test_resolve_custom():
    payload = {'reasoning_effort': 'minimal'}
    assert tp.resolve_payload(tp.MODE_CUSTOM, stored_payload=payload) == payload
    assert tp.resolve_payload(tp.MODE_CUSTOM, stored_payload=None) is None


def test_aux_profile_forces_thinking_off_even_when_answer_mode_is_none():
    """改写/重排用 aux：模型回答配置为 none，也要按目录选关闭预置。"""
    assert tp.resolve_payload(
        tp.MODE_NONE, api_model='deepseek-chat',
        profile=tp.PROFILE_AUX) == tp.DEEPSEEK_VLLM_OFF_PAYLOAD
    assert tp.resolve_payload(
        tp.MODE_NONE, api_model='deepseek-chat',
        profile=tp.PROFILE_ANSWER) is None


def test_aux_profile_ignores_explicit_preset_and_custom():
    """模型行的显式配置只作用于回答；辅助调用固定按目录匹配关闭/最低档。"""
    # preset 选了 Qwen 写法，但 aux 仍按模型名（DeepSeek）匹配，不沿用 Qwen 快照
    assert tp.resolve_payload(
        tp.MODE_PRESET, preset_id='qwen-vllm', api_model='deepseek-chat',
        profile=tp.PROFILE_AUX) == tp.DEEPSEEK_VLLM_OFF_PAYLOAD
    # custom 的高推理不能漏到改写/重排
    custom = {'reasoning_effort': 'high'}
    assert tp.resolve_payload(
        tp.MODE_CUSTOM, stored_payload=custom, api_model='deepseek-chat',
        profile=tp.PROFILE_AUX) == tp.DEEPSEEK_VLLM_OFF_PAYLOAD
    # 目录没覆盖的模型：不会因为行里有 custom 就把它发给辅助调用
    assert tp.resolve_payload(
        tp.MODE_CUSTOM, stored_payload=custom, api_model='private-model',
        profile=tp.PROFILE_AUX) is None


def test_aux_profile_unknown_model_sends_nothing():
    assert tp.resolve_payload(
        tp.MODE_NONE, api_model='private-model', profile=tp.PROFILE_AUX) is None


def test_public_catalog_and_metadata():
    catalog = tp.public_catalog()
    assert {entry['presetId'] for entry in catalog} >= {'deepseek-vllm', 'qwen-vllm', 'glm-hosted'}
    assert all(entry['label'] and entry['labelEn'] for entry in catalog)
    assert json.dumps(catalog, ensure_ascii=False)
    metadata = tp.public_metadata()
    assert 'thinkingMode' not in metadata
    assert set(metadata['allowedPayloadKeys']) == tp.ALLOWED_PAYLOAD_KEYS
    assert metadata['maxPayloadBytes'] == tp.MAX_PAYLOAD_BYTES
