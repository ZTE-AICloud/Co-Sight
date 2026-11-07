"""联网检索：当前版本**不支持**（占位实现）。

为什么留一个文件而不是删掉调用点：vendored 的 `core/rag/query_engine/__init__.py` 里有

    if user_request.enableWebSearch:
        operators['websearch'] = WebSearchRetriever(request_headers, user_request.apiKey)

删掉导入就要改那个文件，而它属于「不该漂移」的领域代码。这里用一个明确报错的
占位类把「没有这个能力」这件事表达出来：

  * `enableWebSearch` 默认 false → 正常链路一行都不受影响；
  * 真传了 true → 立刻拿到一句能看懂的失败原因，而不是 import 崩在启动期。

将来要恢复联网检索，替换这个占位类即可。
"""
from typing import Dict

from engine.common.exception.rag_exception import RagException
from engine.logutil import logger


class WebSearchRetriever:

    def __init__(self, request_headers=None, api_key: str = '', config_dict: Dict = None):
        logger.error('web search retriever is not supported in this build')
        raise RagException(-1, 'web-search-not-supported')

    @classmethod
    def from_args(cls, config_dict: Dict):
        return cls(config_dict=config_dict)
