"""LLM 工厂：返回 OpenAI 兼容适配器。

对外类名 `Qwen` 指向它（vendored 算子按这个名字导入：
`from core.rag.custom_llm import Qwen`、`Qwen(context_window=..., config_info=...)`）。
"""
from typing import Dict

from engine.common import const
from engine.custom_llm.openai_llm import OpenAICompatLLM

# 对外的类名别名（vendored 算子按 Qwen 导入）
Qwen = OpenAICompatLLM


def get_custom_llm(llm: str, config_info: Dict) -> OpenAICompatLLM:
    context_window = (config_info or {}).get(const.max_token, const.default_token)
    # `llm` 参数就是算子里选的模型名；塞进 config_info 让适配器统一取用
    merged = dict(config_info or {})
    if llm:
        merged['llm'] = llm
    return OpenAICompatLLM(context_window=context_window, config_info=merged)
