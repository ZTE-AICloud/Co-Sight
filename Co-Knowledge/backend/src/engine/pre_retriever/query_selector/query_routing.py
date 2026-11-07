from abc import ABC
from typing import Dict, Sequence

from engine.primitives.components.selector import _build_choices_text, _structured_output_to_selector_result
from engine.primitives.models import QueryBundle, SelectorResult, SingleSelection, ToolMetadata

from engine.custom_llm import get_custom_llm
from engine.pre_retriever.query_selector.base import BaseRagSelector
from engine.logutil import logger


class LLMSemanticRouting(BaseRagSelector, ABC):

    @classmethod
    def from_args(cls, config_dict: Dict) -> BaseRagSelector:
        # 路由只做选择题，不需要思考；显式传了 thinking_profile 则以调用方为准。
        llm_config = dict(config_dict or {})
        llm_config.setdefault('thinking_profile', 'aux')
        return LLMSemanticRouting.from_defaults(
            llm=get_custom_llm(config_dict.get('llm', 'qwen-14b-chat'), llm_config),
            prompt_template_str=config_dict.get('prompt')
        )

    def _select(
            self, choices: Sequence[ToolMetadata], query: QueryBundle
    ) -> SelectorResult:
        # prepare input
        choices_text = _build_choices_text(choices)

        # predict
        prediction = self._llm.predict(
            prompt=self._prompt,
            num_choices=len(choices),
            context_list=choices_text,
            query_str=query.query_str,
        )

        # 当通过大模型路由query-engine时发生异常，则默认路由到第一个query-engine
        try:
            assert self._prompt.output_parser is not None
            parse = self._prompt.output_parser.parse(prediction)
            return _structured_output_to_selector_result(parse)
        except Exception as e:
            logger.exception(e)
            logger.info('Failed to select query engine, default use first node.')
            selections = [
                SingleSelection(index=0, reason='Failed to select')
            ]
            return SelectorResult(selections=selections)
