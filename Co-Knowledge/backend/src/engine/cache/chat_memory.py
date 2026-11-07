from typing import Dict, List, Optional

from cachetools import TTLCache

from engine.common.const import default_max_multi_chat_limit


class ChatHistory:
    question: str = ''
    contexts: List[str] = []
    answer: str = ''

    def __init__(self, question: str, contexts: List[str], answer: str):
        self.question = question
        self.contexts = contexts
        self.answer = answer


# maxsize/ttl 是硬编码常量，没有配置键可改：
#   `user_chat_question_cache: TTLCache(maxsize=1000, ttl=600)`
# **不要把它们接到 Config 上**：那会改变多轮缓存的生存期（行为变更），
# 要加就是新特性，并同步更新钉住 1000/600 与 1000/3600 的用例。
user_chat_question_cache: Dict[str, ChatHistory] = TTLCache(maxsize=1000, ttl=600)


def save_chat_history(conversation_id: str, history: ChatHistory) -> None:
    if history.question:
        user_chat_question_cache[conversation_id] = history


def get_chat_history(conversation_id: str) -> Optional[ChatHistory]:
    return user_chat_question_cache.get(conversation_id)


def get_last_question(conversation_id: str) -> str:
    history = get_chat_history(conversation_id)
    return history.question if history else ''


def get_last_context(conversation_id: str) -> List[str]:
    chat_history = get_chat_history(conversation_id)
    return chat_history.contexts if chat_history else []


# 同上：硬编码 `TTLCache(maxsize=1000, ttl=3600)`，不要接到 Config 上。
user_chat_question_history_cache: Dict[str, List[str]] = TTLCache(maxsize=1000, ttl=3600)


def save_chat_question_history(conversation_id: str, question: str) -> None:
    history = get_chat_question_history(conversation_id)
    if history:
        if len(history) >= default_max_multi_chat_limit:
            del history[0]
        history.append(question)
    else:
        user_chat_question_history_cache[conversation_id] = [question]


def get_chat_question_history(conversation_id: str) -> Optional[List[str]]:
    return user_chat_question_history_cache.get(conversation_id)
