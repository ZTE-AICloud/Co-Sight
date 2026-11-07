#!/usr/bin/env python3
"""MetaQA 图谱检索指标：纯函数，便于手算单测。

口径：

* ``topic_hit``      题目标注的 topic entity 是否出现在 ``seed_entity_ids`` 里
                     —— 只测「向量种子召回/实体链接」，与子图展开无关。
* ``answer_covered`` 任一标准答案是否出现在返回子图的实体里
                     —— 测「种子 + depth 跳展开」能不能覆盖答案。
* ``answer_recall``  多答案题里，标准答案被覆盖的比例。
* 聚合值默认给 95% bootstrap 置信区间（对题目重采样，固定随机种子）。
"""
from __future__ import annotations

import math
import random
from typing import Iterable, Sequence


def normalize_entity(value: object) -> str:
    """实体名归一化：去空白、casefold。KB 与题目标注来自同一命名空间。"""
    if value is None:
        return ''
    return ' '.join(str(value).split()).casefold()


def evaluate_retrieval(topic: str, answers: Sequence[str],
                       seed_ids: Iterable[object],
                       entity_ids: Iterable[object],
                       edges: Iterable[dict] | None = None,
                       depth: int | None = None) -> dict:
    """单题评估；返回可直接落 JSON 的 0/1 与比例。

    ``edges``/``depth`` 给了时额外算 ``answer_reachable``：从题目标注的 topic
    出发，用返回子图的边做无向 BFS（和产品 ``_build_subgraph_text`` 的连通口径一致），
    看标准答案是否在 ``depth`` 跳内可达。比单纯的「答案在实体列表里」更严格 ——
    后者会被 Comedy / English 这类高频实体蒙中。
    """
    seed_set = {normalize_entity(value) for value in seed_ids}
    entity_set = {normalize_entity(value) for value in entity_ids}
    gold = {normalize_entity(answer) for answer in answers if normalize_entity(answer)}
    hits = gold & entity_set
    topic_key = normalize_entity(topic)
    result = {
        'topic_hit': 1.0 if topic_key and topic_key in seed_set else 0.0,
        'answer_covered': 1.0 if hits else 0.0,
        'answer_recall': (len(hits) / len(gold)) if gold else 0.0,
        'answer_hits': len(hits),
        'answer_total': len(gold),
    }
    if edges is not None and depth is not None:
        reached = reachable_entities(topic_key, edges, depth)
        reach_hits = gold & reached
        result.update({
            'answer_reachable': 1.0 if reach_hits else 0.0,
            'answer_reach_recall': (len(reach_hits) / len(gold)) if gold else 0.0,
        })
    return result


def reachable_entities(topic: str, edges: Iterable[dict], depth: int) -> set[str]:
    """从 topic 出发的无向 BFS（按产品子图文本的连通口径）。"""
    topic = normalize_entity(topic)
    if not topic or depth < 0:
        return set()
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        source = normalize_entity(edge.get('source_id'))
        target = normalize_entity(edge.get('target_id'))
        if not source or not target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)
    reached = {topic}
    frontier = {topic}
    for _ in range(depth):
        next_frontier = {
            neighbor
            for node in frontier
            for neighbor in adjacency.get(node, ())
            if neighbor not in reached
        }
        if not next_frontier:
            break
        reached |= next_frontier
        frontier = next_frontier
    return reached


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    """线性插值分位数；``q`` 取 0~1。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_ci(values: Sequence[float], *, rounds: int = 2000,
                 seed: int = 20261030, alpha: float = 0.05) -> tuple[float, float]:
    """对题目做有放回重采样，返回 ``(low, high)`` 分位区间。"""
    values = list(values)
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    size = len(values)
    means = []
    for _ in range(rounds):
        sample = [values[rng.randrange(size)] for _ in range(size)]
        means.append(sum(sample) / size)
    return percentile(means, alpha / 2), percentile(means, 1 - alpha / 2)


def aggregate(rows: Sequence[dict], *, metric: str,
              rounds: int = 2000, seed: int = 20261030) -> dict:
    values = [float(row[metric]) for row in rows]
    low, high = bootstrap_ci(values, rounds=rounds, seed=seed)
    return {
        'n': len(values),
        'mean': mean(values),
        'ci_low': low,
        'ci_high': high,
    }
