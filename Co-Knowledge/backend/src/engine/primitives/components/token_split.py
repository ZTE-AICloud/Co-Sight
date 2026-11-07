"""自研编排原语：token 截断（`PromptHelper.truncate` 的对位实现）。

替代 llama-index-core 0.10.31 的 `indices/prompt_helper.py` +
`node_parser/text/token.py`（`TokenTextSplitter`）+ `node_parser/text/utils.truncate_text`
+ `prompts/prompt_utils.get_empty_prompt_txt` —— 只实现**非流式合成路径实际走到的那一条**
（`truncate(prompt, text_chunks=[单块])`）。

⚠️ **词表是本仓 vendor 的，不是 tiktoken 联网下载的**：
镜像里**没有**默认的 tiktoken 缓存目录（`/root/.cache/tiktoken` 不存在）；
今天能跑是因为 llama-index 把 cl100k_base 词表打包在 `llama_index/core/_static/
tiktoken_cache/` 并在 `get_tokenizer()` 里设了 `TIKTOKEN_CACHE_DIR`。摘掉库之后那条路
就断了 —— 第一次截断会去 openaipublic 下载词表，**离线镜像直接失败**。
因此词表已复制到 `primitives/_static/tiktoken_cache/`（见该目录 README 的出处与许可），
本模块把 `TIKTOKEN_CACHE_DIR` 指过去（仅当环境未显式指定时，与库的写法一致）。

算法与库一致：`available = context_window - num_prompt_tokens - num_output` →
`chunk_size = available // num_chunks - padding(5)` → `TokenizerTextSplitter(sep=" ",
backup=["\\n"], overlap=int(0.1 * chunk_size))` → `split_text(chunk)[0]`。
`num_prompt_tokens` 来自把**空模板**（未填变量替空串）过一遍分词器。
"""
from __future__ import annotations

import os
from functools import partial
from typing import Any, Callable, List, Optional

from engine.primitives.templating import BasePromptTemplate

DEFAULT_PADDING = 5
DEFAULT_CHUNK_OVERLAP_RATIO = 0.1
DEFAULT_CONTEXT_WINDOW = 3900
DEFAULT_NUM_OUTPUTS = 256

# 库 `TokenTextSplitter.__init__` 的 backup_separators 默认值（不是 None！）：
# 切分降级链是"先按空格 → 再按换行 → 最后按字符"。少这一环会让截断结果整体变短。
_DEFAULT_BACKUP_SEPARATORS: List[str] = ['\n']

_STATIC_TIKTOKEN_CACHE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_static', 'tiktoken_cache'))

_TOKENIZER: Optional[Callable[[str], List[int]]] = None


def get_tokenizer() -> Callable[[str], List[int]]:
    """与库同口径：tiktoken 的 `gpt-3.5-turbo` 编码（= cl100k_base）+ `allowed_special='all'`。"""
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            import tiktoken
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可执行的指引
            raise ImportError('需要 tiktoken（截断算术用）：pip install tiktoken') from exc

        should_revert = False
        if 'TIKTOKEN_CACHE_DIR' not in os.environ:
            should_revert = True
            os.environ['TIKTOKEN_CACHE_DIR'] = _STATIC_TIKTOKEN_CACHE
        try:
            encoder = tiktoken.encoding_for_model('gpt-3.5-turbo')
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f'tiktoken 词表加载失败（缓存目录 {_STATIC_TIKTOKEN_CACHE}）：'
                '本仓不依赖联网下载，词表随包 vendor；请确认该目录未被裁掉。'
            ) from exc
        finally:
            if should_revert:
                os.environ.pop('TIKTOKEN_CACHE_DIR', None)
        _TOKENIZER = partial(encoder.encode, allowed_special='all')
    return _TOKENIZER


# --------------------------------------------------------------------------
# 与库同形的切分器（只保留 truncate 用到的路径）
# --------------------------------------------------------------------------
def _split_text_keep_separator(text: str, separator: str) -> List[str]:
    parts = text.split(separator)
    result = [separator + s if i > 0 else s for i, s in enumerate(parts)]
    return [s for s in result if s]


def _split_by_sep(sep: str) -> Callable[[str], List[str]]:
    return lambda text: _split_text_keep_separator(text, sep)


def _split_by_char() -> Callable[[str], List[str]]:
    return lambda text: list(text)


class TokenizerTextSplitter:
    """`TokenTextSplitter` 的最小对位：`split_text(text)` 走 split → merge 两步。"""

    def __init__(self, chunk_size: int, chunk_overlap: int = 0,
                 separator: str = ' ',
                 # ⚠️ 默认值必须与库一致：`TokenTextSplitter.__init__` 的 backup_separators
                 # 默认是 `["\n"]`（不是 None）。少它会让"先按空格、再按换行、最后按字符"
                 # 的降级链少一环 → 截断结果整体变短（差 33 字符）。
                 backup_separators: Optional[List[str]] = _DEFAULT_BACKUP_SEPARATORS,
                 tokenizer: Optional[Callable[[str], List[int]]] = None) -> None:
        if chunk_overlap > chunk_size:
            raise ValueError(
                f'Got a larger chunk overlap ({chunk_overlap}) than chunk size '
                f'({chunk_size}), should be smaller.')
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
        self._tokenizer = tokenizer or get_tokenizer()
        # 与库同义：`None` 表示"没有备用分隔符"，**默认**是 `["\n"]`
        all_seps = [separator] + list(backup_separators or [])
        self._split_fns = [_split_by_sep(sep) for sep in all_seps] + [_split_by_char()]

    def split_text(self, text: str) -> List[str]:
        return self._split_text(text, chunk_size=self.chunk_size)

    def _split_text(self, text: str, chunk_size: int) -> List[str]:
        if text == '':
            return [text]
        splits = self._split(text, chunk_size)
        return self._merge(splits, chunk_size)

    def _split(self, text: str, chunk_size: int) -> List[str]:
        if len(self._tokenizer(text)) <= chunk_size:
            return [text]

        splits: List[str] = []
        for split_fn in self._split_fns:
            splits = split_fn(text)
            if len(splits) > 1:
                break

        new_splits: List[str] = []
        for split in splits:
            split_len = len(self._tokenizer(split))
            if split_len <= chunk_size:
                new_splits.append(split)
            else:
                new_splits.extend(self._split(split, chunk_size=chunk_size))
        return new_splits

    def _merge(self, splits: List[str], chunk_size: int) -> List[str]:
        chunks: List[str] = []
        cur_chunk: List[str] = []
        cur_len = 0
        for split in splits:
            split_len = len(self._tokenizer(split))
            if cur_len + split_len > chunk_size:
                chunk = ''.join(cur_chunk).strip()
                if chunk:
                    chunks.append(chunk)
                while cur_len > self.chunk_overlap or cur_len + split_len > chunk_size:
                    first_chunk = cur_chunk.pop(0)
                    cur_len -= len(self._tokenizer(first_chunk))
            cur_chunk.append(split)
            cur_len += split_len

        chunk = ''.join(cur_chunk).strip()
        if chunk:
            chunks.append(chunk)
        return chunks


def truncate_text(text: str, text_splitter: TokenizerTextSplitter) -> str:
    """库实现：`chunks = splitter.split_text(text); return chunks[0]`。"""
    return text_splitter.split_text(text)[0]


# --------------------------------------------------------------------------
# PromptHelper（截断所需子集）
# --------------------------------------------------------------------------
def get_empty_prompt_txt(prompt: BasePromptTemplate) -> str:
    """把未填的模板变量替空串后 format —— 用来数"提示词本身占多少 token"。"""
    partial_kwargs = prompt.kwargs
    empty_kwargs = {v: '' for v in prompt.template_vars if v not in partial_kwargs}
    all_kwargs = {**partial_kwargs, **empty_kwargs}
    return prompt.format(llm=None, **all_kwargs)


class PromptHelper:
    """`PromptHelper` 的截断子集（`repack`/`get_text_splitter_given_prompt` 之外一律不做）。"""

    def __init__(
            self,
            context_window: int = DEFAULT_CONTEXT_WINDOW,
            num_output: int = DEFAULT_NUM_OUTPUTS,
            chunk_overlap_ratio: float = DEFAULT_CHUNK_OVERLAP_RATIO,
            chunk_size_limit: Optional[int] = None,
            separator: str = ' ',
    ) -> None:
        if chunk_overlap_ratio > 1.0 or chunk_overlap_ratio < 0.0:
            raise ValueError('chunk_overlap_ratio must be a float between 0. and 1.')
        self.context_window = context_window
        self.num_output = num_output
        self.chunk_overlap_ratio = chunk_overlap_ratio
        self.chunk_size_limit = chunk_size_limit
        self.separator = separator

    @classmethod
    def from_llm_metadata(
            cls,
            llm_metadata: Any,
            chunk_overlap_ratio: float = DEFAULT_CHUNK_OVERLAP_RATIO,
            chunk_size_limit: Optional[int] = None,
            separator: str = ' ',
    ) -> 'PromptHelper':
        context_window = llm_metadata.context_window
        num_output = (DEFAULT_NUM_OUTPUTS if llm_metadata.num_output == -1
                      else llm_metadata.num_output)
        return cls(context_window=context_window, num_output=num_output,
                   chunk_overlap_ratio=chunk_overlap_ratio,
                   chunk_size_limit=chunk_size_limit, separator=separator)

    def _get_available_context_size(self, num_prompt_tokens: int) -> int:
        context_size_tokens = self.context_window - num_prompt_tokens - self.num_output
        if context_size_tokens < 0:
            raise ValueError(
                f'Calculated available context size {context_size_tokens} was not non-negative.')
        return context_size_tokens

    def _get_available_chunk_size(self, prompt: BasePromptTemplate, num_chunks: int = 1,
                                 padding: int = DEFAULT_PADDING) -> int:
        prompt_str = get_empty_prompt_txt(prompt)
        num_prompt_tokens = len(get_tokenizer()(prompt_str))
        available_context_size = self._get_available_context_size(num_prompt_tokens)
        result = available_context_size // num_chunks - padding
        if self.chunk_size_limit is not None:
            result = min(result, self.chunk_size_limit)
        return result

    def get_text_splitter_given_prompt(self, prompt: BasePromptTemplate, num_chunks: int = 1,
                                       padding: int = DEFAULT_PADDING) -> TokenizerTextSplitter:
        chunk_size = self._get_available_chunk_size(prompt, num_chunks, padding=padding)
        if chunk_size <= 0:
            raise ValueError(f'Chunk size {chunk_size} is not positive.')
        chunk_overlap = int(self.chunk_overlap_ratio * chunk_size)
        return TokenizerTextSplitter(
            separator=self.separator,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tokenizer=get_tokenizer(),
        )

    def truncate(self, prompt: BasePromptTemplate, text_chunks: List[str],
                 padding: int = DEFAULT_PADDING) -> List[str]:
        """库实现：先算切分器，再对每个 chunk 取 `split_text(...)[0]`。"""
        text_splitter = self.get_text_splitter_given_prompt(
            prompt, num_chunks=len(text_chunks), padding=padding)
        return [truncate_text(chunk, text_splitter) for chunk in text_chunks]

    def repack(self, prompt: BasePromptTemplate, text_chunks: List[str],
               padding: int = DEFAULT_PADDING) -> List[str]:
        """库实现：合并所有 chunk（strip 后 `"\\n\\n"` 连接）再按可用窗口切分。"""
        text_splitter = self.get_text_splitter_given_prompt(prompt, padding=padding)
        combined_str = '\n\n'.join([c.strip() for c in text_chunks if c.strip()])
        return text_splitter.split_text(combined_str)
