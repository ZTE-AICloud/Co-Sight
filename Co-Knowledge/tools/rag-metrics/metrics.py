"""检索指标（L1）：Hit / Recall / Precision / MRR / NDCG。

输入是**排名位置列表**，每个位置可以是：
* 一个 pid 字符串（正常情况：一个 chunk 对应一条 passage）；
* 一个 pid 序列（一个 chunk 的正文同时对应多条 passage —— 语料正文重复，
  或长 passage 的子片恰好等于另一条 passage 的全文）。

后者必须按「一个位置、多条候选」计分：它只占一个排名位（不能把后面文档的
rank 挤后），Recall 可以覆盖组内所有 gold，NDCG 的增益取组内最大相关性
（不能一个位置重复吃两次 DCG）。

其余约定：
* 排名里的重复 pid **保留首次出现**（产品返回多份重复正文时也只算一次）。
* ``gold`` 为 ``{pid: relevance}``；DuRetrieval 是二值 qrels，但也接受分级相关性。
* 没有 gold 的查询返回 ``None``，由调用方显式跳过。
* ``precision@k`` 分母固定为 ``k``（标准 IR 口径）；``precision_at_retrieved``
  的分母是实际返回的位置数，两者都报，避免「返回不足 k 条」被误读成高精度。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

Relevance = Dict[str, float]
Ranked = Sequence[object]          # str 或 Sequence[str]
Groups = List[Tuple[str, ...]]


def normalize_groups(ranked: Ranked) -> Groups:
    """把排名归一成「位置 → pid 元组」，并去掉重复 pid（保留首次出现）。"""
    seen = set()
    out: Groups = []
    for item in ranked:
        if isinstance(item, str):
            group: Tuple[str, ...] = (item,)
        else:
            group = tuple(item)
        kept = tuple(pid for pid in group if pid not in seen)
        if not kept:
            continue
        for pid in kept:
            seen.add(pid)
        out.append(kept)
    return out


def _top(groups: Groups, k: int) -> Groups:
    if k <= 0:
        raise ValueError('k must be positive')
    return groups[:k]


def _any_gold(group: Tuple[str, ...], gold: Relevance) -> bool:
    return any(pid in gold for pid in group)


def hit_at_k(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """top-k 的任一位置是否命中 gold。无 gold 返回 None。"""
    if not gold:
        return None
    return 1.0 if any(_any_gold(group, gold) for group in _top(normalize_groups(ranked), k)) else 0.0


def recall_at_k(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """top-k 覆盖的 gold 比例（组内所有 pid 都算覆盖）。"""
    if not gold:
        return None
    covered = {pid for group in _top(normalize_groups(ranked), k)
               for pid in group if pid in gold}
    return len(covered) / len(gold)


def precision_at_k(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """top-k 中「命中 gold 的位置数」/ k（分母固定 k）。"""
    if not gold:
        return None
    groups = _top(normalize_groups(ranked), k)
    hit = sum(1 for group in groups if _any_gold(group, gold))
    return hit / k


def precision_at_retrieved(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """top-k 中命中位置数 / 实际返回位置数。"""
    if not gold:
        return None
    groups = _top(normalize_groups(ranked), k)
    if not groups:
        return 0.0
    return sum(1 for group in groups if _any_gold(group, gold)) / len(groups)


def mrr_at_k(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """第一条命中 gold 的位置的排名倒数；top-k 内没有则 0。"""
    if not gold:
        return None
    for rank, group in enumerate(_top(normalize_groups(ranked), k), start=1):
        if _any_gold(group, gold):
            return 1.0 / rank
    return 0.0


def _gain(relevance: float) -> float:
    return float(relevance)


def dcg_at_k(ranked: Ranked, gold: Relevance, k: int) -> float:
    total = 0.0
    for rank, group in enumerate(_top(normalize_groups(ranked), k), start=1):
        gain = max((_gain(gold.get(pid, 0.0)) for pid in group), default=0.0)
        total += gain / math.log2(rank + 1)
    return total


def ndcg_at_k(ranked: Ranked, gold: Relevance, k: int) -> Optional[float]:
    """DCG@K / IDCG@K；IDCG 按 gold 相关性降序。"""
    if not gold:
        return None
    dcg = dcg_at_k(ranked, gold, k)
    ideal = sorted(gold.values(), reverse=True)[:k]
    idcg = sum(_gain(rel) / math.log2(rank + 1)
               for rank, rel in enumerate(ideal, start=1))
    if idcg == 0:
        return None
    return dcg / idcg


ALL_METRICS = {
    'hit': hit_at_k,
    'recall': recall_at_k,
    'precision': precision_at_k,
    'precision_retrieved': precision_at_retrieved,
    'mrr': mrr_at_k,
    'ndcg': ndcg_at_k,
}


def score_query(ranked: Ranked, gold: Relevance, ks: Sequence[int]) -> Dict[str, float]:
    """单查询所有 ``指标@k`` 的分值（None 的指标不写入）。"""
    out: Dict[str, float] = {}
    for name, fn in ALL_METRICS.items():
        for k in ks:
            value = fn(ranked, gold, k)
            if value is not None:
                out[f'{name}@{k}'] = value
    return out
