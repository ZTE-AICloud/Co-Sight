import re
import json
import time
from abc import ABC
from typing import Dict, List, Optional, Any, Sequence, Union

from engine.primitives.components.summarizer import SimpleSummarize
from engine.primitives.models import MetadataMode, NodeWithScore, QueryBundle, Response, StreamingResponse
from engine.primitives.templating import PromptTemplate, PromptType, SelectorPromptTemplate

from engine.common import const
from engine.common.const import default_llm_prompt
from engine.custom_llm import get_custom_llm, Qwen
from engine import json_utils
from engine.logutil import logger

# 原库的 `base/response/schema.RESPONSE_TYPE` 与 `response_synthesizers.base.QueryTextType`
# 是纯类型别名；本仓按同一口径在本地定义（不做 union 展开，语义等同）。
RESPONSE_TYPE = Union[Response, StreamingResponse]
QueryTextType = Union[str, QueryBundle]

class RagSimpleSummarizer(SimpleSummarize, ABC):

    def __init__(self, streaming, config_info):
        context_window = config_info.get('generator-config')[0].get(const.max_token, const.default_token)
        super().__init__(streaming=streaming, llm=Qwen(context_window=context_window, config_info=config_info))
        self.config_info = config_info

    @classmethod
    def from_args(cls, config_dict: Dict) -> "SimpleSummarize":
        return RagSimpleSummarizer(
            streaming=config_dict.get('user_request').stream,
            config_info=config_dict
        )

    def update_llm_and_prompt(self, base_name: str):
        headers = self.config_info.get('headers', {})
        user_request = self.config_info.get('user_request', {})
        for params in self.config_info.get('generator-config', []):
            params_json = json.loads(params) if isinstance(params, str) else params
            params['headers'] = headers
            params['user_request'] = user_request
            if not base_name:
                self._llm = get_custom_llm(params.get('llm', 'qwen-14b-chat'), params)
                self._text_qa_template = _select_prompt(params.get('prompt', default_llm_prompt))
                logger.info('[synthesizer] default config selected llm=%r prompt_len=%s',
                            params.get('llm'), len(str(params.get('prompt') or default_llm_prompt)))
            knowledge_base_names = params.get('knowledge_base_name', [])
            processed_base_names = [knowledge_base_name.split('|#|')[0] for knowledge_base_name in knowledge_base_names]
            if base_name in processed_base_names or base_name == user_request.conversation_id.replace("-", ""):
                self._llm = get_custom_llm(params.get('llm', 'qwen-14b-chat'), params)
                self._text_qa_template = _select_prompt(params.get('prompt', default_llm_prompt))
                # 只记选择结果与体量：整份 params 含提示词与历史，INFO 级别全量打印会把
                # 日志冲到几十 MB（``=====>params_json`` 就是这种）。
                logger.info('[synthesizer] per-kb config selected base=%r llm=%r '
                            'configured_bases=%s prompt_len=%s',
                            base_name, params.get('llm'), len(processed_base_names),
                            len(str(params.get('prompt') or default_llm_prompt)))


    def synthesize(
            self,
            query: QueryTextType,
            nodes: List[NodeWithScore],
            additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
            **response_kwargs: Any,
    ) -> RESPONSE_TYPE:
        if self.config_info.get('headers').deepsearch:
            citation = {}
            for node_index, node in enumerate(nodes):
                citation_info = {
                    'source': node.metadata.get('source', '').replace('|*source#|', ''),
                    'content_expand': node.text.replace('|*expand#|', ''),
                    'node_id': node.node.id_
                }

                citation_index_text = '引文-' + str(node_index + 1)

                citation[citation_index_text] = {
                    'type': 'text',
                    'data': citation_info
                }

            result = {
                'conversation_id': self.config_info.get('user_request').conversation_id,
                'answer': '',
                'placeholder': {},
                'citation': citation
            }

            rsp = json_utils.json_unescape_dumps(result)

            return Response(rsp)

        if isinstance(query, str):
            query = QueryBundle(query_str=query)

        started = time.perf_counter()
        logger.info('[synthesizer] start streaming=%s nodes=%s query_len=%s',
                    self._streaming, len(nodes), len(query.query_str or ''))

        if len(nodes) == 0:
            # 零检索兜底：把**改写后**的 query 传给兜底提示词（多轮追问要靠它接上）。
            # query_bundle 由 pre-retriever 的 query_rewrite 原地改写后一路传到这里
            # （MultiTransformQueryEngine._query → SelectPromptQueryEngine._query），
            # 改写失败时它就是原始问句 —— 这里不区分，传什么用什么。
            logger.info('[synthesizer] no retrieved nodes, using zero-node fallback '
                        'streaming=%s', self._streaming)
            if self._streaming:
                return StreamingResponse(
                    response_gen=self._llm.generate_answer_stream(query.query_str),
                    query_str=query.query_str,
                )
            else:
                return Response(self._llm.generate_answer(query.query_str),
                                query_str=query.query_str)

        text_chunks = [n.node.get_content(metadata_mode=MetadataMode.LLM) for n in nodes]
        prefix_pattern = re.compile(r'^([^:]+):')
        text_chunks[:] = [prefix_pattern.sub(lambda m: f"|#|{m.group(1)}:", chunk, count=1) for chunk in
                          text_chunks]
        response_str = self.get_response(
            query_str=query.query_str,
            text_chunks=text_chunks,
            **response_kwargs,
        )

        # 非流式 + 有节点：合成成功后补记会话历史 —— 下一轮改写算子靠
        # `chat_memory.get_last_question(conversation_id)` 取 last_question，缺这一步时
        # 「上一轮有检索命中」的多轮会断（零检索两条路、流式两条路都各自在 LLM 侧保存，
        # 只有这一格是空的，见 `save_synthesis_history` 的注释）。
        # ⚠️ 不要把这个保存挪进 `OpenAICompatLLM.complete()`：重排算子（`LLMReranker`）
        # 也走 `complete()`，放那儿会把重排提示词写进同一份缓存。
        if not self._streaming:
            self._llm.save_synthesis_history(query.query_str, response_str, text_chunks)

        additional_source_nodes = additional_source_nodes or []
        source_nodes = list(nodes) + list(additional_source_nodes)

        logger.info('[synthesizer] done streaming=%s nodes=%s answer_len=%s elapsed=%.3fs',
                    self._streaming, len(source_nodes), len(str(response_str or '')),
                    time.perf_counter() - started)

        # 这里不包 Synthesize 回调/埋点事件（全仓没有订阅者，事件只产生开销）。
        # 响应形状与返回值完全不变。
        response = self._prepare_response_output(response_str, source_nodes)
        # 证据面板要展示「检索实际用的问句」（改写后的 query_str），挂在响应上带回 app 层。
        response.query_str = query.query_str
        return response


def _select_prompt(prompt):
    if prompt:
        return SelectorPromptTemplate(
            default_template=PromptTemplate(prompt, prompt_type=PromptType.QUESTION_ANSWER)
        )
