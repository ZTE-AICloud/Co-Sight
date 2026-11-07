"""OpenAI 兼容的 LLM 适配器。

这里只保留检索编排真正依赖的三件事：

  1. `ask_llm(prompt, stream, use_kwargs)` → 返回一个带 `.json()` 的对象
     （`query_rewrite` 读 `resp.json()['choices'][0]['message']['content']`）；
  2. 作为 llama-index `CustomLLM` 的 `complete()` / `stream_complete()`
     （`LLMRerank.predict()` 与 `SimpleSummarize` 走的是这条）；
  3. `metadata`（llama-index 需要 context_window 等）。

**流式（本文件的第二条路）**：`stream_complete()` 与 `generate_answer_stream()` 都走真 SSE。
`_chat_stream()` 按 OpenAI 兼容端点的 `stream: true` 拉流，逐帧产出 `prepare_text_data()`
的 JSON（`app._streamer` 直接把它包成 `data: <token>\n\n` 发给前端），末帧是裸的 `[DONE]`。
帧序列按上游实测设计：模型先吐 `reasoning_content` 再吐 `content`，空行分隔，以
`data: [DONE]` 收尾（没有心跳行、没有注释行；`_chat_stream` 仍显式跳过它们）。
**改写 / 重排 / 非流式合成一律走 `_chat`（`'stream': False`），不要动那条路。**

**`delta` 必须每帧都设**：llama-index 的 `stream_completion_response_to_tokens()` 取的是
`r.delta or ""` —— 只设置 `text` 会得到一条「全是空串」的流（HTTP 200、看起来完全正常、
前端一个字都收不到）。回归测试：`tests/test_llm_stream.py`。

**已知限制**（有意裁剪，不是缺陷）：
  * 不做图片占位符链 / citation 帧 / chatbot 格式 —— 那些服务于智能体对话场景；
  * `reasoning_content` **不经过敏感词滑窗**：推理内容是逐帧直出的，
    只有最终答案（`content`）过滑窗。合规上这是既定口径，不要当 bug 修；
  * 滑窗的残留尾巴（< 一个窗口）在 `[DONE]` 时**原样**冲出；
  * `<think>` 链：只有模型把思考放在 `reasoning_content` 里时才由适配器包标记；
    模型自己往 `content` 里写 `<think>` 时，整条解析路径关闭、原文透传。

**关于推理模型的静默失败**：这类模型先输出 `reasoning_content`，`max_tokens` 给小了会出现
`content` 为空、`finish_reason=length` —— 看起来调用成功，实际没有答案。
这里**不允许它静默通过**：content 为空时按情况抛 `llm-empty-content-truncated`
（只出了推理内容就被截断，指向 max_tokens 太小）或 `llm-empty-content`（其它）。
调用方各自有兜底（改写失败退回原问题、重排失败退回原始顺序），但日志里必须看得到。
"""
import json
from typing import Any, Dict, Iterator, List, Optional, Tuple

from infrastructure.http import egress
from engine.primitives.templating import BasePromptTemplate, PromptType
from engine.primitives.llm import (
    CompletionResponse,
    LLM,
    LLMMetadata,
    TokenGen,
    stream_completion_response_to_tokens,
)

import engine.i18n as i18n
from engine.common.const import default_no_context_prompt
from engine.common.exception.rag_exception import RagException
from engine.settings import Config
from engine.cache import chat_memory
from engine.cache.chat_memory import ChatHistory
from engine.config_loader.black_list_loader import get_black_list_dir, get_sensitive_words
from engine.gateways.llm_proxy_client import check_exec_result
from engine import json_utils
from engine.logutil import logger

# 默认上下文窗口：与 const.default_token 对齐（必须大于输出上限，见该常量注释）
DEFAULT_CONTEXT_WINDOW = 32768


# 推理内容在非流式回答里的包裹标记
REDACTED_THINKING_OPEN = '<think>'
REDACTED_THINKING_CLOSE = '</think>'


def _content_has_redacted_thinking_markup(text: str) -> bool:
    if not text:
        return False
    return REDACTED_THINKING_OPEN in text or REDACTED_THINKING_CLOSE in text


def _deployment_reasoning_effort(endpoint) -> str:
    """部署级 ``GENERATION_REASONING_EFFORT`` 只对 **env 回落端点** 生效。

    注册表行是权威：行内 ``none`` 也压住全局，否则「不发送」会被部署兜底
    悄悄改成 ``reasoning_effort=none``（与 ``contracts/model-gateway.md`` 的
    优先级表不一致）。
    """
    if getattr(endpoint, 'origin', 'env') != 'env':
        return ''
    return (Config.get('generation_reasoning_effort') or '').strip()


# 模型有时会凭空编出 `{{图*}}` 这类占位，必须清掉
ERROR_PICT_INFOS = ['{{图*}}', '图*']


def _strip_error_pict_marks(text: str) -> str:
    result = text or ''
    for mark in ERROR_PICT_INFOS:
        result = result.replace(mark, '')
    return result


def _mask_sensitive_words(text: str, vocabulary: str) -> str:
    """把命中黑名单的词替换成等长 `*`。

    命中词替换成等长 `*`（`'*' * len(word)`）。词表名来自算子的
    `config_info['black_vocabulary']`：

        * 这个键在算子的 kwargs → `config_info` 里（`kb_kbase` 的算子参数表才能配）；
        * 词表本身来自部署挂载的黑名单目录（见 `core/config_loader/black_list_loader.py`）；
        * 两者任一为空 → 原样返回（**不是错误**：默认部署就没有黑名单）。

    `text` 为 None（模型返回 shape 异常）时保持 None，交给调用方的空内容判定去报错。
    """
    if text is None or not vocabulary:
        return text
    sensitive_words = get_sensitive_words(vocabulary)
    if not sensitive_words:
        logger.warning('black vocabulary [%s] is declared by the workflow but not found in %s',
                       vocabulary, get_black_list_dir())
        return text
    for sensitive_word in sensitive_words:
        # 空串会无限膨胀（''.replace 不出东西，但 '*'*0 是空串会插进每个位置之间）
        if sensitive_word:
            text = text.replace(sensitive_word, '*' * len(sensitive_word))
    return text


def _merge_message_with_reasoning(content, reasoning_content) -> str:
    """合并语义：content 已有 thinking 标记就不重复包。"""
    c = '' if content is None else content
    r = reasoning_content.strip() if reasoning_content else ''
    if _content_has_redacted_thinking_markup(c):
        return c
    if r:
        return REDACTED_THINKING_OPEN + r + REDACTED_THINKING_CLOSE + c
    return c


def filter_sensitive_words(text: str, sensitive_words: List[str], max_kw_len: int) -> Tuple[str, str]:
    """命中词替换成等长 `*`，
    并返回 (可以直接发出去的前缀, 需要留在窗口里等后续 chunk 的尾巴)。

    尾巴的取法有讲究：默认留最后 `max_kw_len - 1` 个字符（一个还没对齐的敏感词最多这么长）；
    如果最后一个命中词离结尾更近，就从**那个词之后**开始留 —— 否则尾巴里会带着一串 `*`，
    而前缀会少掉本该发出去的正文。
    """
    end_text = text[-(max_kw_len - 1):]
    for sensitive_word in sensitive_words:
        idx = text.rfind(sensitive_word)
        if idx != -1:
            text = text.replace(sensitive_word, '*' * len(sensitive_word))
            end_str = text[idx + len(sensitive_word):]
            if len(end_str) < len(end_text):
                end_text = end_str
    start_text = text[:-len(end_text)] if len(end_text) > 0 else text
    return start_text, end_text


def prepare_text_data(conversation_id: str, text: str) -> str:
    """流式单帧的载荷。

    形如 `{"conversation_id": ..., "output": {"type": "text", "content": ...}}`；
    `app._streamer` 直接把它包成 `data: <token>\\n\\n`，所以**改动形状会同时改到下游**。
    """
    return json_utils.json_unescape_dumps({
        'conversation_id': conversation_id,
        'output': {'type': 'text', 'content': text}
    })


def _is_done_frame(data: str) -> bool:
    """`data: [DONE]` 才是结束帧。

    必须用「整帧相等」而不是子串判断：正文里真的出现 "[DONE]" 时，JSON 帧里是
    `\\"[DONE]\\"`，子串判断会把一帧正常内容误当结束帧、静默截断后面的答案。
    结束帧是裸的 `data: [DONE]`。
    """
    return data.strip() == '[DONE]'


def _related_context_from_prompt_args(prompt_args: Dict[str, Any]) -> List[str]:
    """从 llama-index 传进来的 `context_str` 还原「一条一条的上下文」。

    `SimpleSummarize.get_response()` 传的是 `prompt_helper.truncate()` 的结果 ——
    一个**字符串列表**；编排侧 `simple_summarizer` 又给每条前面加了 `|#|来源:` 前缀
    （`prefix_pattern`），这里按这个前缀切分。
    """
    raw = prompt_args.get('context_str')
    if raw is None:
        return []
    chunks = [raw] if isinstance(raw, str) else list(raw)
    related_context = []
    for chunk in chunks:
        chunk = chunk[3:] if chunk.startswith('|#|') else chunk
        related_context.extend(piece for piece in chunk.split('|#|') if piece)
    return related_context


def _format_rag_prompt(prompt_text: str, question: str, related_context: List[str]) -> str:
    """只做 `{query_str}` / `{context_str}` 替换。

    图片链需要在提示词前后插「必须保留 ![image](*.png)」的约束；本服务不做
    （见文件头「已知限制」）。
    """
    return (prompt_text or '') \
        .replace('{query_str}', question or '') \
        .replace('{context_str}', '\n'.join(related_context or []))


class HttpResponseAdapter:
    """把 requests 的响应包成带 `.json()` 的对象，省得改调用方。"""

    def __init__(self, payload: Dict[str, Any], status_code: int):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._payload


class OpenAICompatLLM(LLM):
    """走 OpenAI 兼容端点的 LLM（自研原语层 `LLM` 的适配器）。"""

    context_window: int = DEFAULT_CONTEXT_WINDOW
    config_info: Dict[str, Any] = {}

    def __init__(self, context_window: int = DEFAULT_CONTEXT_WINDOW, config_info: Optional[Dict] = None, **kwargs):
        super().__init__(**kwargs)
        self.context_window = context_window or DEFAULT_CONTEXT_WINDOW
        self.config_info = config_info or {}

    # ------------------------------------------------------------------
    # 自研原语层接口（`primitives/llm.py:LLM`）
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self._max_tokens(),
            is_chat_model=True,
            model_name=self._model(),
        )

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        """合成 / 重排阶段的模型调用：**返回裸文本**。

        不在这里包 JSON 信封：llama-index 0.10.31 里
        `LLM.predict()` 对 chat 模型走的是 `chat()` 而不是 `complete()`，
        `formatted` 这个参数根本区分不出「重排」和「合成」两条路
        （按 formatted 分支，合成拿到裸文本、`app` 侧 json.loads 失败）。
        信封改在**响应边界**（`app._get_answer_from_result`）统一补 —— 那里本来就知道
        自己要多轮上下文与引用信息，也是唯一该关心响应形状的地方。

        失败**直接抛出**：调用方各有自己的语义
          * 重排：`llm_reranker` 捕获后退回原始顺序（并记日志）
          * 合成：`app` 捕获后返回业务错误，不会给出一个「看起来正常」的空答案
        """
        payload = self._chat(self._messages(prompt, kwargs), stream=False)
        # 黑名单屏蔽放在 `complete` 的出口：合成/multiturn 两条路都过这里，
        # 屏蔽不会漏。取值用 `self.config_info.get('black_vocabulary', '')`。
        text = _mask_sensitive_words(self._extract_content(payload),
                                     (self.config_info or {}).get('black_vocabulary', ''))
        return CompletionResponse(text=text)

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        """真流式：每帧一个 `CompletionResponse(text=累计原文, delta=单帧 JSON)`。

        ⚠️ `delta` **必须**是字符串。llama-index 的
        `stream_completion_response_to_tokens()` 取的是 `r.delta or ""` ——
        只填 `text` 会得到一条「全是空串」的流：HTTP 200、上游以为成功、前端一个字都没有。
        这里把 `delta` 送进 `prepare_text_data()` 的 JSON；末帧是裸的 `[DONE]`
        （`app._streamer` 靠它判断流结束，不要包成 JSON）。

        状态机（含敏感词滑窗与 `<think>` 链）在 `_stream_deltas()`，
        与检索为空的 `generate_answer_stream()` 共用。
        """
        for accumulated, delta in self._stream_deltas(self._messages(prompt, kwargs),
                                                      question=kwargs.get('question', ''),
                                                      related_context=kwargs.get('related_context')):
            yield CompletionResponse(text=accumulated, delta=delta)

    def stream(self, prompt: BasePromptTemplate, **prompt_args: Any) -> TokenGen:
        """覆盖基类的 `LLM.stream()`：**不**走 chat 分发，自己拼好 prompt 再 `stream_complete()`。

        为什么要覆盖：`metadata.is_chat_model=True`（本文件 `metadata` 属性）会让基类
        绕道 `stream_chat()` → `messages_to_prompt()`，那是另一条 prompt 拼装路径
        （流式不走 chat 接口）。基类实现（`primitives/llm.py`）也这么分派，
        这里显式覆盖以保持该行为：一串 token，末帧是裸的 `[DONE]`。
        """
        self._log_template_data(prompt, **prompt_args)
        if prompt.metadata.get('prompt_type') == PromptType.QUESTION_ANSWER:
            question = prompt.kwargs.get('query_str') or prompt_args.get('query_str') or ''
            related_context = _related_context_from_prompt_args(prompt_args)
            formatted_prompt = _format_rag_prompt(prompt.get_template(), question, related_context)
            stream_response = self.stream_complete(formatted_prompt, question=question,
                                                   related_context=related_context)
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            stream_response = self.stream_complete(formatted_prompt)

        if prompt.output_parser is not None or self.output_parser is not None:
            raise NotImplementedError('Output parser is not supported for streaming.')
        return stream_completion_response_to_tokens(stream_response)

    def _final_response(self, conversation_id: str, text: str) -> str:
        return json_utils.json_unescape_dumps({
            'conversation_id': conversation_id,
            'answer': _strip_error_pict_marks(text),
            'placeholder': {},
            'citation': {},
        })

    def _conversation_id(self) -> str:
        user_request = (self.config_info or {}).get('user_request')
        return getattr(user_request, 'conversation_id', '') if user_request else ''

    # ------------------------------------------------------------------
    # 兼容接口
    # ------------------------------------------------------------------

    def ask_llm(self, prompt, stream: bool = False, use_kwargs: bool = True) -> HttpResponseAdapter:
        """兼容接口：返回带 `.json()` 的对象，内容是 OpenAI 风格响应。"""
        payload = self._chat(self._messages(prompt, {}), stream=stream)
        return HttpResponseAdapter(payload, 200)

    # ------------------------------------------------------------------
    # 兼容接口：无检索结果时的兜底回答
    # ------------------------------------------------------------------

    def generate_answer(self, question: str = '') -> str:
        """检索为空时，不带上下文直接问模型。

        `simple_summarizer` 在 `len(nodes) == 0` 时调它。契约必须一致：
          * 返回值是 **JSON 字符串** `{"conversation_id", "answer"}`（summarizer 直接塞进 Response）；
          * 成功时把这一轮记进会话历史（多轮改写依赖它）；
          * 失败时**不抛异常**，而是把错误消息当作 answer 返回（检索为空是常见情形，
            不该让整个请求 500）。

        多轮（⚠️ **不要写死 `user_request.question`**）：`question` 由调用方传入，是
        **已经过改写**的问句（`RagSimpleSummarizer.synthesize` 传 `QueryBundle.query_str`）。
        写死用户原话会让追问（「那它的缺点呢？」）在零检索兜底提示词里没有被改写补全，
        模型只能反问「您说的'它'指什么？」。没传参时仍回落到 `user_request.question`；
        历史里记的 question 与本次实际问模型的问句一致 —— 与命中路径同一口径
        （流式 `_stream_deltas` 记的就是 query_str），下一轮改写取到的 last_question 才带实体。
        """
        user_request = (self.config_info or {}).get('user_request')
        prompt_template = (self.config_info or {}).get('no_context_prompt') or default_no_context_prompt
        conversation_id = getattr(user_request, 'conversation_id', '') if user_request else ''
        question = question or (getattr(user_request, 'question', '') if user_request else '')
        answer = ''
        try:
            prompt = prompt_template.format(query_str=question)
            payload = self._chat(self._messages(prompt, {}), stream=False)
            choice = (payload.get('choices') or [{}])[0]
            message = choice.get('message') or {}
            answer = _merge_message_with_reasoning(message.get('content'), message.get('reasoning_content'))
            if not answer.strip():
                raise RagException(-1, 'llm-empty-content', str(choice.get('finish_reason')))
            self._save_chat_history(question, answer, conversation_id)
        except Exception as e:
            logger.exception(e)
            answer = i18n.get_i18n_safe(self._language_option(), 'request-llm-failed')
        return json_utils.json_unescape_dumps({'conversation_id': conversation_id, 'answer': answer})

    def generate_answer_stream(self, question: str = ''):
        """检索为空时的**流式**兜底回答（`simple_summarizer` 在 `len(nodes)==0` 且开流时走这条）。

        每帧是 `prepare_text_data()` 的 JSON，不是「一整个 `{'answer': ...}` JSON
        一次性 yield 出去」—— 后者对前端就是假流式，第一帧就拿到全部内容，
        `[DONE]` 之后再无输出。

        与 `stream_complete()` 共用 `_stream_deltas()`（同一套 `<think>` / 敏感词 / 结束 /
        异常分支），差别只在最外层：这里直接 yield delta 字符串（`StreamingResponse`
        的 `response_gen` 要的就是这个），不套 `CompletionResponse`。

        多轮（⚠️ **不要写死 `user_request.question`**）：`question` 由调用方传入，是
        **已经过改写**的问句（`RagSimpleSummarizer.synthesize` 传 `QueryBundle.query_str`）；
        写死用户原话会让追问在零检索兜底提示词里没有被改写补全（见 `generate_answer`
        的同款说明）。
        没传参时仍回落到 `user_request.question`。这里传的 question 同时进
        `_stream_deltas()` 的历史落盘，与命中路径同一个口径。
        """
        user_request = (self.config_info or {}).get('user_request')
        prompt_template = (self.config_info or {}).get('no_context_prompt') or default_no_context_prompt
        conversation_id = getattr(user_request, 'conversation_id', '') if user_request else ''
        question = question or (getattr(user_request, 'question', '') if user_request else '')
        try:
            prompt = prompt_template.format(query_str=question)
        except Exception as e:
            # 提示词模板本身有问题（配置错误）：仍然给一个可解析的失败帧 + 结束帧
            logger.exception(e)
            yield prepare_text_data(conversation_id, i18n.get_i18n_safe(self._language_option(), 'request-llm-failed'))
            yield '[DONE]'
            return
        for _, delta in self._stream_deltas(self._messages(prompt, {}), question=question,
                                            related_context=[]):
            yield delta

    def _stream_deltas(self, messages: list, question: str = '',
                       related_context: Optional[List[str]] = None) -> Iterator[Tuple[str, str]]:
        """SSE 帧 → `(累计原文, 单帧 delta)` 的共用生成器（`stream_complete` 与
        `generate_answer_stream` 两处复用）。

        状态机覆盖 `<think>` 链、敏感词滑窗、结束与异常分支；图片占位符链 /
        citation 帧 / chatbot 格式不做。逐条说明：

          * **`<think>` 链**：模型把思考放在 `reasoning_content` 里时，首个非空推理帧前
            补 `<think>`、首个正文帧前补 `</think>`；任一 `content` 帧自带 `<think>` /
            `</think>` 标记时（`native_thinking_in_content`）整条解析路径关闭，不重复包；
          * **敏感词滑窗**：只对 `content` 做。累计到 `window_size` 才调
            `filter_sensitive_words()`（不足则**整帧不发**，等后续 chunk 拼齐再判定 ——
            跨 chunk 断词靠这个），只发前缀、尾巴带回窗口；
            `reasoning_content` 不过滑窗（见模块 docstring）；
          * 词表用 `get_sensitive_words()` **懒加载**取，不要直读 `sensitive_words_cache`：
            本服务没有启动预热线程，冷启动直读会拿到 `[]`，
            于是 `len(sensitive_words) == 0` → 整条滑窗被静默跳过（合规风险，不报错）；
          * **结束**：`[DONE]` 时把窗口里剩下的尾巴冲出来再发 `[DONE]`；连接没等到
            `[DONE]` 就断了（`for...else`）也照样冲尾巴 + 补 `[DONE]`，正文尾巴不能丢；
          * **异常**：发一帧 `request-llm-failed` 文案 + `[DONE]`（不让调用方拿到半截流）；
          * `finally` 把这一轮写进会话历史（多轮改写要用），答不上来时也写。

        注意 `response`（返回的累计原文）**不含** `<think>`/`</think>` 标记本身：
        标记只出现在 delta 里，历史里留裸答案。
        """
        conversation_id = self._conversation_id()
        black_vocabulary = (self.config_info or {}).get('black_vocabulary', '')
        sensitive_words = get_sensitive_words(black_vocabulary)
        if black_vocabulary and not sensitive_words:
            # 声明了词表却没加载到：滑窗会被跳过（内容不屏蔽），这条日志是唯一的痕迹
            logger.warning('black vocabulary [%s] is declared by the workflow but not found in %s',
                           black_vocabulary, get_black_list_dir())
        max_kw_len = len(sensitive_words[0]) if sensitive_words else 0
        window_size = max_kw_len if max_kw_len > 5 else 5
        accumulated_text = ''
        response = ''
        has_reasoning_started = False
        has_reasoning_ended = False
        native_thinking_in_content = False
        try:
            for data in self._chat_stream(messages):
                if _is_done_frame(data):
                    # 结束帧：滑窗里还没冲出去的尾巴先补上，再发 [DONE]
                    if accumulated_text:
                        response += accumulated_text
                        yield response, prepare_text_data(conversation_id, accumulated_text)
                        accumulated_text = ''
                    yield response, '[DONE]'
                    break

                json_data = json.loads(data)
                check_exec_result(json_data)
                choices = json_data.get('choices') or []
                if choices:
                    delta = choices[0].get('delta') or {}
                    reasoning_content = delta.get('reasoning_content', '')
                    content = delta.get('content', '')
                else:
                    reasoning_content = ''
                    content = ''

                if _content_has_redacted_thinking_markup(content or ''):
                    native_thinking_in_content = True

                if not native_thinking_in_content:
                    if reasoning_content and not has_reasoning_started:
                        has_reasoning_started = True
                        yield response, prepare_text_data(conversation_id, REDACTED_THINKING_OPEN)

                    if reasoning_content:
                        response += reasoning_content
                        yield response, prepare_text_data(conversation_id, reasoning_content)

                    if content and not has_reasoning_ended and has_reasoning_started:
                        has_reasoning_ended = True
                        yield response, prepare_text_data(conversation_id, REDACTED_THINKING_CLOSE)

                if not content:
                    continue

                if len(sensitive_words) > 0:
                    accumulated_text += content
                    if len(accumulated_text) >= window_size:
                        filtered_text, end_text = filter_sensitive_words(accumulated_text, sensitive_words,
                                                                         max_kw_len)
                        accumulated_text = end_text
                        content = filtered_text
                    else:
                        continue

                response += content
                yield response, prepare_text_data(conversation_id, content)
            else:
                # 没等到 [DONE]（连接被中途掐断）：尾巴一样不能丢，补一个结束帧
                if accumulated_text:
                    response += accumulated_text
                    yield response, prepare_text_data(conversation_id, accumulated_text)
                yield response, '[DONE]'
        except Exception as e:
            logger.exception(e)
            fail_response = i18n.get_i18n_safe(self._language_option(), 'request-llm-failed')
            yield response, prepare_text_data(conversation_id, fail_response)
            yield response, '[DONE]'
        finally:
            self._save_chat_history(question, response, conversation_id, related_context)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def save_synthesis_history(self, question: str, answer: str,
                               text_chunks: Optional[List[str]] = None) -> None:
        """有节点合成成功后的会话历史落盘（`RagSimpleSummarizer.synthesize` 非流式分支调用）。

        语义与 `_save_chat_history` 完全一致（同表、同形状、失败只留痕）：question 是
        已经过改写的问句，contexts 是这次拼进提示词的上下文。缺了这一步时，非流式 +
        上一轮有检索命中 → 下一轮 `chat_memory.get_last_question(conversation_id)` 是空，
        改写算子拿不到 last_question，多轮断掉（流式路径在 `_stream_deltas` 的 finally
        里已经保存，零检索两条路各自保存）。

        ⚠️ **不要**把这个保存搬进 `complete()`：`LLMReranker` 等其他算子也走 `complete()`，
        会把重排提示词当用户问题写进 `user_chat_question_cache`。本适配器没有覆写
        `predict()`，所以在合成侧显式补记，落点选在唯一确定「这是合成」的位置。

        contexts 与流式路径取同一形态：把拼好的上下文按 `|#|` 标记还原成一条一条
        （`_related_context_from_prompt_args` 就是 `stream()` 那条路用的同一个函数）。
        """
        contexts = _related_context_from_prompt_args(
            {'context_str': ['\n'.join(text_chunks or [])]})
        self._save_chat_history(question, answer, self._conversation_id(), contexts)

    def _save_chat_history(self, question: str, answer: str, conversation_id: str,
                           contexts: Optional[List[str]] = None) -> None:
        if not conversation_id:
            return
        try:
            chat_memory.save_chat_history(conversation_id, ChatHistory(question, contexts or [], answer))
        except Exception as e:
            # 历史写失败不该影响本次回答，但必须留痕
            logger.warning('save chat history failed: %s', str(e))

    def _language_option(self) -> str:
        headers = (self.config_info or {}).get('headers')
        return getattr(headers, 'language_option', 'zh') if headers else 'zh'

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _model(self) -> str:
        # 算子 kwargs 里的 llm 优先（画布上选的是哪个模型就用哪个），否则用部署配置
        return (self.config_info or {}).get('llm') or Config.get('generation_model')

    def _thinking_profile(self) -> str:
        """answer（默认，用每模型思考配置）/ aux（改写/重排/路由，自动关思考）。"""
        value = (self.config_info or {}).get('thinking_profile')
        return 'aux' if value == 'aux' else 'answer'

    def _endpoint(self):
        """这次调用该打哪个端点。

        **按调用解析**（不是导入期）：``engine/settings.py`` 的 ``Config`` 是模块级
        dict，构造时就固定了 —— 用它就等于「模型清单变了要重启」。注册表路线下
        解析层带缓存、写模型时主动失效，所以新注册的模型**立即**可用。

        模型名点的是画布/算子选的那个（``_model()``）；注册表里没有它时，
        解析层会把这个名字原样放进请求体、端点回落 ``.env`` —— 与改造前一致。
        """
        from engine.gateways import model_bridge

        return model_bridge.resolve_llm(
            self._model(), thinking_profile=self._thinking_profile())

    def _max_tokens(self, endpoint=None) -> int:
        raw = (self.config_info or {}).get('max_token')
        if raw is None:
            raw = getattr(endpoint, 'max_tokens', None)      # 注册表里按模型配的
        if raw is None:
            raw = Config.get('generation_max_tokens')
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(Config.get('generation_max_tokens') or 2048)

    def _temperature(self, endpoint=None) -> float:
        raw = (self.config_info or {}).get('temperature')
        if raw is None:
            raw = getattr(endpoint, 'temperature', None)
        if raw is None:
            raw = Config.get('generation_temperature')
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.01

    def _generation_overrides(self, endpoint=None) -> Dict[str, Any]:
        """这次生成要合并进请求体的思考配置（顶层片段）。

        优先级：算子级 ``config_info['thinking_payload']`` /
        ``chat_template_kwargs`` / ``reasoning_effort`` > 注册表该模型的
        auto/preset/custom 解析结果 > 部署级 ``GENERATION_*``（仅 env 回落端点）。
        空 = 不发送。
        """
        from engine.gateways import model_bridge

        payload = model_bridge.effective_generation_overrides(endpoint)
        overrides = dict(payload) if isinstance(payload, dict) else {}
        config = self.config_info or {}

        operator_payload = config.get('thinking_payload')
        if isinstance(operator_payload, dict):
            overrides.update(operator_payload)
        operator_kwargs = config.get('chat_template_kwargs')
        if isinstance(operator_kwargs, dict) and operator_kwargs:
            overrides['chat_template_kwargs'] = operator_kwargs
        operator_effort = config.get('reasoning_effort')
        if isinstance(operator_effort, str) and operator_effort.strip():
            overrides['reasoning_effort'] = operator_effort.strip()
        return overrides

    def _messages(self, prompt: str, kwargs: Dict[str, Any]) -> list:
        messages = []
        system_prompt = (self.config_info or {}).get('system_prompt')
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})
        return messages

    def _chat(self, messages: list, stream: bool = False) -> Dict[str, Any]:
        endpoint = self._endpoint()
        url = endpoint.url
        if not url:
            raise RagException(-1, 'request-model-gateway-failed')
        body = {
            'model': endpoint.api_model,
            'messages': messages,
            'temperature': self._temperature(endpoint),
            'max_tokens': self._max_tokens(endpoint),
            'stream': False,  # 改写/重排/非流式合成一律走非流式；流式走 _chat_stream()
        }
        reasoning_effort = _deployment_reasoning_effort(endpoint)
        if reasoning_effort:
            body['reasoning_effort'] = reasoning_effort
        overrides = self._generation_overrides(endpoint)
        if overrides:
            body.update(overrides)
        headers = endpoint.headers()

        # 日志里只记形状，不记 key
        logger.info('LLM request: model=%s, messages=%d, max_tokens=%s, reasoning_effort=%r, '
                    'stream=%s', body['model'], len(messages), body['max_tokens'],
                    body.get('reasoning_effort'), stream)
        try:
            response = egress.post(url, json=body, headers=headers,
                                   timeout=float(endpoint.timeout or Config.get('generation_timeout') or 120))
        except Exception as e:
            logger.error('call generation model failed: %s', str(e))
            raise RagException(-1, 'request-model-gateway-failed')

        if response.status_code < 200 or response.status_code >= 300:
            logger.error('generation model returned HTTP %s: %s', response.status_code, response.text[:500])
            raise RagException(-1, 'request-model-gateway-failed')
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError):
            logger.error('generation model returned non-JSON body: %s', response.text[:500])
            raise RagException(-1, 'request-model-gateway-failed')

    def _chat_stream(self, messages: list) -> Iterator[str]:
        """POST 一个 `stream: true` 请求，逐条 yield SSE 帧的载荷（含裸 `[DONE]`）。

        与 `_chat()` 的差别只有三处：`stream` 字段、`requests.post(stream=True)`、
        返回的是**逐行**生成器而不是解析好的 JSON。手写 requests 原生能力（`iter_lines`），
        不引 `sseclient-py`：requirements 里没有它，也没必要为这点协议加依赖。

        帧的形态（上游实测）：`data: {...}` 与 `data: [DONE]`，空行分隔，没有心跳/注释行 ——
        空行与非 `data:` 开头的行仍然显式跳过（协议允许，跳过比崩掉好）。
        """
        endpoint = self._endpoint()
        url = endpoint.url
        if not url:
            raise RagException(-1, 'request-model-gateway-failed')
        body = {
            'model': endpoint.api_model,
            'messages': messages,
            'temperature': self._temperature(endpoint),
            'max_tokens': self._max_tokens(endpoint),
            'stream': True,
        }
        reasoning_effort = _deployment_reasoning_effort(endpoint)
        if reasoning_effort:
            body['reasoning_effort'] = reasoning_effort
        overrides = self._generation_overrides(endpoint)
        if overrides:
            body.update(overrides)
        headers = endpoint.headers()

        logger.info('LLM stream request: model=%s, messages=%d, max_tokens=%s, '
                    'reasoning_effort=%r', body['model'], len(messages),
                    body['max_tokens'], body.get('reasoning_effort'))
        try:
            response = egress.post(url, json=body, headers=headers, stream=True,
                                   timeout=float(endpoint.timeout or Config.get('generation_timeout') or 120))
        except Exception as e:
            logger.error('call generation model failed: %s', str(e))
            raise RagException(-1, 'request-model-gateway-failed')

        try:
            if response.status_code < 200 or response.status_code >= 300:
                logger.error('generation model returned HTTP %s: %s', response.status_code,
                             response.text[:500])
                raise RagException(-1, 'request-model-gateway-failed')
            # SSE 规定 UTF-8，但上游的 `text/event-stream` 不带 charset —— requests 对
            # text/* 会假设 ISO-8859-1，`iter_lines(decode_unicode=True)` 出来的中文是乱码。
            # 显式指回 utf-8（解码器是增量的，跨 chunk 的半截多字节字符也不会散）。
            response.encoding = 'utf-8'
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue  # 空行 = 帧分隔符
                if not line.startswith('data:'):
                    continue  # 注释行（`:` 开头）等非数据行
                payload = line[len('data:'):].strip()
                if payload:
                    yield payload
        finally:
            # 流没读完也要把连接还回去（生成器被 close/异常时同样会走到这里）
            response.close()

    def _extract_content(self, payload: Dict[str, Any]) -> str:
        """从响应里取 content，并在「空内容」时显式失败（见文件头注释）。"""
        choices = payload.get('choices') or []
        if not choices:
            logger.error('generation model returned no choices: %s', json.dumps(payload)[:400])
            raise RagException(-1, 'llm-empty-content', 'no-choices')

        choice = choices[0]
        message = choice.get('message') or {}
        content = (message.get('content') or '').strip()
        finish_reason = choice.get('finish_reason')

        if content:
            return content

        reasoning = (message.get('reasoning_content') or '').strip()
        if reasoning and finish_reason == 'length':
            # 推理模型的典型坑：推理内容吃光了预算，正文为空但 HTTP 200
            logger.error('model produced reasoning only and hit the token limit '
                         '(max_tokens=%s, reasoning_chars=%d)', self._max_tokens(), len(reasoning))
            raise RagException(-1, 'llm-empty-content-truncated', str(self._max_tokens()))
        logger.error('model returned empty content (finish_reason=%s, reasoning_chars=%d)',
                     finish_reason, len(reasoning))
        raise RagException(-1, 'llm-empty-content', str(finish_reason))
