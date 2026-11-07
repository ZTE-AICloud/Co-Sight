import json
from abc import ABC
from typing import Dict

from engine.primitives.interfaces import RagQueryTransform
from engine.primitives.models import QueryBundle

from engine.common.const import (
    default_max_multi_chat_limit,
    default_query_rewrite_prompt,
    default_same_sequence_prompt,
)
from engine.cache import chat_memory
from engine.gateways.llm_proxy_client import check_exec_result
from engine.custom_llm import get_custom_llm
from engine.pre_retriever.query_transform.base import BaseRagQueryTransform
from engine.logutil import logger


class LLMQueryRewriter(BaseRagQueryTransform, ABC):

    def __init__(self, config_dict: Dict):
        super().__init__(config_dict)
        # 改写是短输出，不需要思考；显式传了 thinking_profile 则以调用方为准。
        llm_config = dict(config_dict or {})
        llm_config.setdefault('thinking_profile', 'aux')
        self.llm = get_custom_llm(config_dict.get('llm'), llm_config)

    def _run(self, query_bundle: QueryBundle, metadata: Dict) -> QueryBundle:
        conversation_id = self.config_info.get('user_request').conversation_id
        current_question = _add_punctuation_2_question(query_bundle.query_str)
        prompt_template = self.config_info.get('prompt', default_query_rewrite_prompt)
        if 'multi_chat_limit' in self.config_info and self.config_info.get('user_request') and self.config_info.get(
                'user_request').chat_history:
            chat_history, multi_chat_limit = self.get_args()
            logger.info(
                'question %s use chat history (limit=%s, pairs=%s, conversation_id=%s)',
                current_question, multi_chat_limit, len(chat_history),
                conversation_id)
            same_sequence = self.is_same_sequence(self.get_limit_chat_history(chat_history, multi_chat_limit),
                                                  current_question)
            last_question = self.build_intention_question(
                self.get_limit_chat_question_history(chat_history, multi_chat_limit, conversation_id))
            if same_sequence and last_question:
                self.config_info.get('user_request', {}).kwargs['is_multi_chat'] = True
        else:
            logger.info(f'question {current_question} use last question')
            last_question = chat_memory.get_last_question(conversation_id)
        try:
            prompt = prompt_template.format(current_question=current_question, last_question=last_question)
            content = self.ask_llm_get_content(prompt)
            content = content[content.index('{'): content.rindex('}') + 1]
            answer = json.loads(content)
            query_bundle.query_str = answer["question"]
            chat_memory.save_chat_question_history(conversation_id, answer["question"])
            logger.info('question rewritten conversation_id=%s: %r -> %r',
                        conversation_id, current_question, answer["question"])
            return query_bundle
        except Exception as e:
            logger.warning('question rebuild failed')
            logger.exception(e)
            return query_bundle

    def get_args(self):
        multi_chat_limit = self.config_info.get('multi_chat_limit', 0)
        # 画布里 0 = 「关闭多轮」。前端现在会随请求
        # 带 chat_history，0 会让这条更可靠的路反而失效；契约改为「<=0 用默认 8 轮」。
        # 显式的正数仍然照用（用户可以在画布上把上限调小）。
        if not isinstance(multi_chat_limit, int) or isinstance(multi_chat_limit, bool) \
                or multi_chat_limit <= 0:
            multi_chat_limit = default_max_multi_chat_limit
        user_request = self.config_info.get('user_request', {})
        chat_history = user_request.chat_history
        return chat_history, multi_chat_limit


    @classmethod
    def from_args(cls, config_dict: Dict) -> RagQueryTransform:
        return LLMQueryRewriter(config_dict)

    def is_same_sequence(self, _chat_history: list, current_question: str):
        if not _chat_history:
            return False
        history_info = "\n".join([f'问题：{chat.get("question")}\n答案：{chat.get("answer")}' for chat in _chat_history])
        prompt = default_same_sequence_prompt.format(history_info=history_info, question=current_question)
        content = self.ask_llm_get_content(prompt)
        logger.info(f'question {current_question} sequence {content}')
        if "不相关" in content:
            return False
        return True

    def build_intention_question(self, _chat_history: list):
        if _chat_history:
            questions = [chat.get("question") for chat in _chat_history if chat.get("question") is not None]
            if questions:
                return "\n".join(questions)
        return ""

    def ask_llm_get_content(self, prompt):
        resp = self.llm.ask_llm(prompt, stream=False, use_kwargs=False)
        check_exec_result(resp.json())
        content = resp.json().get('choices')[0].get('message').get('content')
        logger.debug('rewrite LLM raw content length=%s', len(str(content or '')))
        # 检查是否满足所有条件
        if '</think>' in content:
            parts = content.split('</think>', 1)  # 只分割一次
            after_think = parts[1].strip()
            if '{' in after_think and '}' in after_think:
                logger.debug("Found valid JSON after </think>")
                content = after_think
        return content

    def get_limit_chat_history(self, chat_history, multi_chat_limit):
        if multi_chat_limit <= 0:
            logger.debug('chat history disabled (limit=%s)', multi_chat_limit)
            return []
        return chat_history[-multi_chat_limit:]

    def get_limit_chat_question_history(self, chat_history, multi_chat_limit, conversation_id):
        if multi_chat_limit <= 0:
            logger.debug('chat history disabled (limit=%s)', multi_chat_limit)
            return []
        questions = chat_memory.get_chat_question_history(conversation_id)
        if questions:
            _questions = questions[-multi_chat_limit:]
            _chat_history = []
            for _question in _questions:
                _chat_history.append({"question": _question})
            return _chat_history
        return chat_history[-multi_chat_limit:]



def _add_punctuation_2_question(user_request):
    user_request = user_request.rstrip()
    return user_request if user_request.endswith('？') or user_request.endswith('?') else user_request + "？"
