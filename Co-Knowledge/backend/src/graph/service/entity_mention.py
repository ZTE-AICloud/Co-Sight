"""轻量实体提及匹配：把问题里原样出现的实体名变成图谱种子。

MetaQA 这类基准的题目本身包含 topic 实体名（数据集用 ``[...]`` 标出，检索时
去掉括号但名字还在）。纯向量召回对「名字型实体」不够稳（实测 topic 召回
53–67%），加一条低成本词面路径即可把上限抬到 90%+。

实现是纯 Python 的 trie 扫描 + 词边界检查，不引入依赖：

* 名字/问题都做 casefold + 空白归一；
* ASCII 名字要求左右是非字母数字（避免 ``She`` 命中 ``Sherlock``）；
* 中文等非 ASCII 名字不做边界检查（中文没有空格分词）；
* 重叠匹配按长度优先、互不重叠取前 ``max_mentions`` 个。
"""
from __future__ import annotations

import re
from typing import Iterable

_SPACE_RE = re.compile(r'\s+')
_MIN_ASCII_LEN = 3
_MIN_NON_ASCII_LEN = 2


def normalize_text(text: object) -> str:
    if text is None:
        return ''
    return _SPACE_RE.sub(' ', str(text)).strip().casefold()


def build_mention_trie(names: Iterable[tuple[str, str]]) -> dict:
    """``(entity_id, name)`` → trie；终端节点存 ``entries: [(id, 原名), ...]``。"""
    root: dict = {}
    for entity_id, name in names:
        key = normalize_text(name)
        if not key:
            continue
        minimum = _MIN_ASCII_LEN if key.isascii() else _MIN_NON_ASCII_LEN
        if len(key) < minimum:
            continue
        node = root
        for char in key:
            node = node.setdefault(char, {})
        node.setdefault('entries', []).append((str(entity_id), str(name)))
    return root


def _boundary_ok(query: str, start: int, end: int) -> bool:
    left = query[start - 1] if start > 0 else ' '
    right = query[end] if end < len(query) else ' '
    return not (left.isalnum() or left == '_') and not (right.isalnum() or right == '_')


def find_mentions(query: str, trie: dict, *, max_mentions: int = 20) -> list[str]:
    """返回问题里出现的 entity_id（长名字优先、互不重叠）。"""
    text = normalize_text(query)
    if not text or not trie:
        return []
    matches: list[tuple[int, int, str, str]] = []
    for start in range(len(text)):
        node = trie
        for end in range(start, len(text)):
            node = node.get(text[end])
            if node is None:
                break
            entries = node.get('entries')
            if not entries:
                continue
            matched = text[start:end + 1]
            if matched.isascii() and not _boundary_ok(text, start, end + 1):
                continue
            for entity_id, name in entries:
                matches.append((start, end + 1, entity_id, name))

    # 有专名（大写或多词）命中时，丢掉小写单词的泛名词（film/director/movie…）。
    # MetaQA 的 topic 是专名；不筛会把 "film"、"director" 也当种子，稀释子图预算。
    if any(any(char.isupper() for char in name) or ' ' in name.strip()
           for _start, _end, _entity_id, name in matches):
        matches = [item for item in matches
                   if any(char.isupper() for char in item[3])
                   or ' ' in item[3].strip()]

    # 长匹配优先；同一区间/重叠的短匹配丢弃。同长度按出现顺序。
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0], item[2]))
    chosen: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    seen_ids: set[str] = set()
    for start, end, entity_id, _name in matches:
        if entity_id in seen_ids:
            continue
        if any(start < other_end and end > other_start
               for other_start, other_end in occupied):
            continue
        chosen.append((start, end, entity_id, _name))
        occupied.append((start, end))
        seen_ids.add(entity_id)
        if len(chosen) >= max_mentions:
            break
    return [entity_id for _start, _end, entity_id, _name in chosen]
