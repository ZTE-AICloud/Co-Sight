from pydantic import BaseModel

from engine.common import const


class RagRequest(BaseModel):
    question: str
    llm: str = ''
    stream: bool = False
    workflow_id: str = const.default_workflow_id
    conversation_id: str
    chat_history: list = None
    kwargs: dict = {}
    chatbot_scene: bool = False
    session_info: dict = {}
    scope: str = ''
    safe_mode: str = ''
    enableWebSearch: bool = False
    apiKey: str = ''
    #: 是否随响应返回「本轮检索依据」（对话测试页用）。默认关闭，旧客户端行为不变。
    include_retrieval: bool = False
