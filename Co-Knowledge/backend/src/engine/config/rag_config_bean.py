"""编排配置的**契约模型**。

字段名/别名/默认值必须保持（`query-engine` / `pre-retriever` / `post-retriever` /
`response-synthesizer` 这些带横线的键就是线上报文形状，**不能改**）。

这是 `translator.py` 的产出与 `RagContext`（vendored 领域代码）之间的接口。
丢掉它就等于丢掉了对画布翻译结果的结构校验 —— 一份形状不对的配置会一直往下走到
算子实例化才炸，报错点离原因很远。所以在
`flow_config_provider.get_workflow_config()` 里对翻译结果做一次校验。

未搬的成员 `RagConfig.collect_llm_info()` 用于一条安装期绑定流程，本部署没有对应链路，
且没有任何调用方，故不搬 —— 不搬比搬一个永远不会被执行的死代码更容易看懂。
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ConfigBean(BaseModel):
    id: int
    package: str
    operator: str
    desc: str = ''
    kwargs: dict


class RagConfig(BaseModel):
    workflow_id: str = Field(..., min_length=1, max_length=100)
    query_engine: ConfigBean = Field({}, alias='query-engine')
    pre_retriever: List[ConfigBean] = Field([], alias='pre-retriever')
    retriever: List[ConfigBean] = []
    post_retriever: List[ConfigBean] = Field([], alias='post-retriever')
    response_synthesizer: List[ConfigBean] = Field([], alias='response-synthesizer')
    workflow: dict = {}
    scope: Optional[str] = None
