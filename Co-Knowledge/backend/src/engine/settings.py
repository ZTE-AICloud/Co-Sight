"""编排运行时的配置。

约定：**只读环境变量**，不在代码里放任何默认凭据。
"""
import os


def _env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


Config = {
    # 生成模型：OpenAI 兼容端点（compose 里是 model-gateway，实际由 .env 指到真实端点）
    "generation_base_url": _env('GENERATION_GATEWAY_URL', 'http://model-gateway:8000/v1'),
    "generation_model": _env('GENERATION_MODEL', 'deepseek-chat'),
    "generation_api_key": _env('GENERATION_API_KEY', ''),
    # 推理模型先输出 reasoning_content：content 为空 + finish_reason=length 会被当成
    # 「成功但没答案」，这里给足预算并要求调用方在 content 为空时**显式报错**
    "generation_max_tokens": _env('GENERATION_MAX_TOKENS', '2048'),
    "generation_temperature": _env('GENERATION_TEMPERATURE', '0.01'),
    "generation_timeout": _env('GENERATION_TIMEOUT', '120'),
    # 推理模型的思考开关（OpenAI 兼容 `reasoning_effort`）。留空 = 不发送该字段。
    # 典型值 `none`：deepseek-chat 这类模型默认会先吐 reasoning_content，把
    # max_tokens 烧在思考上；重排/改写这种短输出场景会被截成空 content
    # （`llm-empty-content-truncated`，超时后回落）。部署按模型能力配置。
    "generation_reasoning_effort": _env('GENERATION_REASONING_EFFORT', ''),
    # 重排专用模型（可选）：画布上的 LLMReranker 未显式写 llm 时用它，留空则沿用
    # 默认生成模型。重排提示词要塞进整批候选节点，推理模型在这里容易把 max_tokens
    # 烧在 reasoning 上（可能 20~60s、甚至 content 为空后回落）；换一个非推理模型
    # 可以显著降延迟，且不影响合成答案的模型。
    "generation_rerank_model": _env('GENERATION_RERANK_MODEL', ''),
    # rerank 端点（可选）：没配时 ExternalModelReranker 会显式失败，而不是返回空
    "rerank_url": _env('RERANK_URL', ''),
    # rerank 请求体里的模型名（可选）：消费方 model/llm_proxy_client.py:query_rerank_model。
    # 默认 '' 时回落到 'bge-reranker-large'；端点若校验 model 名（Cohere/Jina 系）必须配它。
    # ⚠️ deploy/docker-compose.yml 的 rag-knowledge-base 段**没有转发** RERANK_MODEL ——
    # 只改 .env 不会进容器（RERANK_URL 同理，见 compose 里的注释）。
    "rerank_model": _env('RERANK_MODEL', ''),
    # 黑名单（敏感词）目录：放 *.txt（文件名=词表名，关键词用 |#| 分隔）。
    # 目录不存在 = 该部署没有黑名单，只记日志。消费方见 core/rag/custom_llm/openai_llm.py
    "black_list_dir": _env('BLACK_LIST_DIR', '/app/black_list'),
    # DEV_MODE：'true'（大小写不敏感）时给 root logger 追加一个 console handler ——
    # 应用日志除文件外同时打到 stderr（docker logs 可见）。其余任何取值
    # （未设置 / '' / 'false'）与「没有这个键」的行为一致。
    "dev_mode": _env('DEV_MODE', 'false').lower(),
}

# 配置读取口径：`Config` 是 dict，调用方用 `Config.get(...)` 取值
assert isinstance(Config, dict)
