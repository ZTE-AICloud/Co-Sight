import copy
import logging
import os
import time
from typing import List

from infrastructure.http import egress

# 模型网关：替换原微服务总线发现 + config/service_infos.json（v1 改为环境变量直连）。
# 契约见 contracts/model-gateway.md：OpenAI 兼容子集，地址由环境变量注入。
#
# ⚠️ **本模块默认不接模型注册表**（别再改回去）。
# 它是四套调用栈里唯一仍走 `.env` 的一套，理由是行为差异：
# 抽图的生成调用从 `MODEL_GATEWAY_URL`（= llm 网关，也提供 chat）改到注册表里那条
# 默认 LLM 的端点（= `GENERATION_GATEWAY_URL`）之后，同一个 464B 文档的抽图
# **从 7.52s 变成 >8 分钟不返回**（两个端点对同名模型的行为不同：`reasoning_effort`
# 在生成端点上不生效，推理模型开始长篇「思考」）。对照实验见
#
# 所以**端点仍由这几个环境变量决定**。唯一的口子是 :func:`invoke_llm` 的
# ``endpoint`` 参数：**每次调用**可以带上一条显式的端点描述（``llmConfig``），
# 由父进程从注册表解析后经算子 kwargs 下发 —— 沙箱子进程按白名单**拿不到**
# 数据库凭据（见 ``ingestion/utility/sandbox_runtime.py``），所以不能在子进程里
# 查注册表。``.env`` 播种的模型（``source='env'``）仍走原网关，只有用户在模型
# 管理页新增的端点（``source='user'``）才带 ``endpoint`` —— 判据在
# ``graph/service/graph_extract_api.py::_llm_endpoint_config``。
MODEL_GATEWAY_URL = os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:8000").rstrip("/")
MODEL_GATEWAY_CHAT_PATH = os.environ.get("MODEL_GATEWAY_CHAT_PATH", "/v1/chat/completions")
# 推理型模型（如 deepseek 系列）对长 prompt 会先产出数万字符的「思考」，单次抽图
# 调用 >10 分钟不返回（同一 prompt 关掉思考后 ~10s 返回）。抽图是**逐 chunk** 调用，
# 必须能关。留空 = 不发该字段（保持对第三方网关的兼容）；置 `none` 关闭思考。
MODEL_GATEWAY_REASONING_EFFORT = os.environ.get("MODEL_GATEWAY_REASONING_EFFORT", "").strip()

#: 4xx 里**值得重试**的：超时与限流是暂时性的。其余 4xx（400/401/403/404/422…）
#: 是确定性错误 —— 重试只会把「立刻失败」拖成十分钟（模型名多打
#: 一个字符，单次调用 20×3s 重试、算子再重试 3 轮，10 分钟后才落「生成失败」，
#: 而真因只有一句 404）。确定性失败一律立即上抛。
RETRYABLE_CLIENT_ERRORS = frozenset({408, 429})


class _TerminalHttpError(RuntimeError):
    """确定性失败（4xx）：**不**进重试循环。"""


def check_status_code_ok(status_code, service_name):
    if not 200 <= status_code <= 300:
        error = 'request {} failed for bad status code: {}'.format(service_name, status_code)
        logging.warning(error)
        raise RuntimeError(error)


def _prepare_chat_request(endpoint, body: dict, request_headers, timeout: int):
    """叠加一条显式端点（``llmConfig``）：地址、鉴权、真实模型名、思考片段。

    ``endpoint`` 为 ``None``（``.env`` 播种的模型、老算子）时**保持原行为**：
    打到 ``MODEL_GATEWAY_URL + MODEL_GATEWAY_CHAT_PATH``。这条「不改默认路径」的
    约束就是上面那段注释里的实测结论，别把它一起「统一」掉。
    """
    default_url = f"{MODEL_GATEWAY_URL}{MODEL_GATEWAY_CHAT_PATH}"
    if not isinstance(endpoint, dict):
        return default_url, body, request_headers, timeout

    url = str(endpoint.get('url') or '').strip() or default_url
    # 注册名与发给端点的 ``model`` 字段是两个命名空间（见 ``model/models.py``）。
    if endpoint.get('model'):
        body['model'] = endpoint['model']

    headers = dict(request_headers or {"Content-Type": "application/json"})
    if endpoint.get('api_key'):
        headers['Authorization'] = f"Bearer {endpoint['api_key']}"

    payload = endpoint.get('thinking_payload')
    if isinstance(payload, dict):
        # 抽图是逐 chunk 的辅助调用：注册表里这条模型若挂着自己的思考片段，
        # 以它为准（``reasoning_effort`` 会覆盖下面那个环境变量的值）。
        body.update(copy.deepcopy(payload))

    if endpoint.get('timeout'):
        timeout = int(endpoint['timeout'])
    return url, body, headers, timeout


def invoke_llm(messages: List, model: str = '', temperature: float = 0.1, request_headers=None,
               stream: bool = False, endpoint=None):
    """调用 chat completions。

    ``endpoint``（可选）是父进程解析好的端点描述：``{url, model, api_key?,
    thinking_payload?, timeout?}``。缺省时行为保持不变。
    """
    if not model:
        raise RuntimeError('LLM model name is None.')

    body = {
        'model': model,
        'stream': stream,
        "temperature": temperature,
        'messages': messages
    }
    if MODEL_GATEWAY_REASONING_EFFORT:
        body['reasoning_effort'] = MODEL_GATEWAY_REASONING_EFFORT

    url, body, headers, timeout = _prepare_chat_request(
        endpoint, body, request_headers, timeout=1800)

    max_retries = 20
    retry_delay = 3  # seconds
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = egress.post(url, json=body, headers=headers, timeout=timeout)
            if (400 <= response.status_code < 500
                    and response.status_code not in RETRYABLE_CLIENT_ERRORS):
                detail = (response.text or '').strip().replace('\n', ' ')[:200]
                raise _TerminalHttpError(
                    f'LLM request rejected: HTTP {response.status_code}, '
                    f'model={body.get("model")!r}, url={url}'
                    + (f', body={detail}' if detail else ''))
            check_status_code_ok(response.status_code, 'model-gateway')
            llm_response_data = response.json()

            choices = llm_response_data.get('choices')
            if choices:
                message = choices[0].get('message', {})
                content = message.get('content')
                if content is not None:
                    return content
            return ''

        except _TerminalHttpError as error:
            # 不重试：确定性失败（模型名不存在 / 鉴权失败 / 路径不对）。
            logging.error('%s', error)
            raise RuntimeError(str(error)) from error
        except Exception as e:
            last_error = e
            logging.exception("Attempt %d failed: %s", attempt, e)
            if attempt < max_retries:
                logging.info("Retrying in %d seconds...", retry_delay)
                time.sleep(retry_delay)
            else:
                logging.error("All %d retry attempts failed.", max_retries)
                raise RuntimeError(f'request-gateway-failed: {last_error}') from last_error


