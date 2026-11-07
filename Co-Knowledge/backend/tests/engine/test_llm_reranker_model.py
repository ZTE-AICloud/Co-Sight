"""重排模型的取用顺序：画布显式 llm > 部署级 GENERATION_RERANK_MODEL > 默认模型。

背景（实测）：重排提示词要塞进整批候选节点，deepseek-chat 这类推理
模型在这里会思考 20~60s，甚至把 max_tokens 烧完 → `llm-empty-content-truncated`
后静态回落到前 N 条。部署级换一个非推理模型可以把重排延迟降下来，同时不影响合成
答案用的模型。画布上显式写了 llm 时仍以画布为准（模板可移植性）。
"""
from __future__ import annotations

from engine.settings import Config
from engine.post_retriever import llm_reranker as mod


class _Captured:
    def __init__(self):
        self.models = []
        self.configs = []

    def __call__(self, model, config):
        self.models.append(model)
        self.configs.append(dict(config or {}))
        return object()


def test_canvas_llm_wins_over_deploy_override(monkeypatch):
    captured = _Captured()
    monkeypatch.setattr(mod, 'get_custom_llm', captured)
    monkeypatch.setitem(Config, 'generation_rerank_model', 'deepseek-chat')

    mod.LLMReranker.from_args({'llm': 'qwen3-32b', 'top_n': 5})

    assert captured.models == ['qwen3-32b']
    assert captured.configs[-1]['thinking_profile'] == 'aux'


def test_deploy_rerank_model_used_when_canvas_has_none(monkeypatch):
    captured = _Captured()
    monkeypatch.setattr(mod, 'get_custom_llm', captured)
    monkeypatch.setitem(Config, 'generation_rerank_model', 'deepseek-chat')

    mod.LLMReranker.from_args({'top_n': 5})

    assert captured.models == ['deepseek-chat']


def test_no_override_falls_back_to_default_model(monkeypatch):
    captured = _Captured()
    monkeypatch.setattr(mod, 'get_custom_llm', captured)
    monkeypatch.setitem(Config, 'generation_rerank_model', '')

    mod.LLMReranker.from_args({'llm': '', 'top_n': 5})

    assert captured.models == [None]
