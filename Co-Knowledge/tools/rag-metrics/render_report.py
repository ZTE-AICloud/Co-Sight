"""把 results.json 渲染成可提交的 Markdown 验收报告。

只做展示与措辞，不重算指标；所有数字都来自 ``run_retrieval_metrics.py`` 的产物。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
from typing import Any, Dict, Optional

HEADLINE = [
    ('ndcg@10', 'NDCG@10'),
    ('recall@10', 'Recall@10'),
    ('recall@80', 'Recall@80'),
    ('mrr@10', 'MRR@10'),
    ('hit@10', 'Hit@10'),
    ('precision@10', 'Precision@10'),
    ('precision_retrieved@10', 'Precision@10（实际返回为分母）'),
]
K_VALUES = [1, 3, 5, 10, 20, 50, 80]


def pct(value: Optional[float]) -> str:
    return '—' if value is None else f'{value * 100:.2f}%'


def pp(value: Optional[float]) -> str:
    return '—' if value is None else f'{value * 100:+.2f} pp'


def metric_row(system: Dict[str, Any], key: str) -> Dict[str, Any]:
    return (system.get('metrics') or {}).get(key) or {}


def headline_table(results: Dict[str, Any]) -> str:
    systems = results['systems']
    names = [name for name in ('vector', 'keyword') if name in systems]
    lines = ['| 指标 | ' + ' | '.join(names) + ' | Δ (vector − keyword) |',
             '|---|' + '---|' * len(names) + '---|']
    diff = results.get('paired_diff') or {}
    for key, label in HEADLINE:
        cells = []
        for name in names:
            row = metric_row(systems[name], key)
            mean = row.get('mean')
            low, high = row.get('ci95_low'), row.get('ci95_high')
            cells.append(f'{pct(mean)} [{pct(low)}, {pct(high)}]')
        delta = '—'
        if 'vector' in systems and 'keyword' in systems and key in diff:
            item = diff[key]
            delta = f'{pp(item["mean_diff"])} [{pp(item["ci95_low"])}, {pp(item["ci95_high"])}]'
        lines.append(f'| {label} | ' + ' | '.join(cells) + f' | {delta} |')
    return '\n'.join(lines)


def sensitivity_table(results: Dict[str, Any]) -> str:
    lines = ['| 系统 | 指标 | 有效查询（剔除空结果） | 含空结果（按 0 分） |',
             '|---|---|---|---|']
    for name, system in results['systems'].items():
        valid = system.get('metrics') or {}
        allm = system.get('metrics_including_empty') or {}
        for key in ('ndcg@10', 'recall@10', 'recall@80'):
            lines.append(
                f'| {name} | {key} | {pct((valid.get(key) or {}).get("mean"))} | '
                f'{pct((allm.get(key) or {}).get("mean"))} |')
    return '\n'.join(lines)


def stability_notes(results: Dict[str, Any]) -> str:
    notes = []
    for name, system in results['systems'].items():
        notes.append(
            f'- **{name}**：有效查询 {system.get("evaluated_queries")}/'
            f'{system.get("queries")}，空结果 {system.get("empty_responses")} 条'
            f'（其中 {system.get("empty_retried", 0)} 条经过一次重试），'
            f'HTTP 错误 {system.get("error_responses", 0)} 条，'
            f'检索失败日志 {system.get("retrieve_failed_log_lines", "未采集")} 行，'
            f'未映射文档占比 {system.get("unmapped_rate", 0.0):.2%}。')
    return '\n'.join(notes)


def verdict(results: Dict[str, Any]) -> str:
    if 'vector' not in results['systems'] or 'keyword' not in results['systems']:
        return ''
    vector = metric_row(results['systems']['vector'], 'ndcg@10').get('mean')
    keyword = metric_row(results['systems']['keyword'], 'ndcg@10').get('mean')
    diff = (results.get('paired_diff') or {}).get('ndcg@10') or {}
    if vector is None or keyword is None:
        return ''
    low, high = diff.get('ci95_low'), diff.get('ci95_high')
    ci = (f'，配对差值 {pp(diff.get("mean_diff"))}'
          f'（95% CI [{pp(low)}, {pp(high)}]）') if diff else ''
    return (f'**结论**：向量路 NDCG@10 **{pct(vector)}**，关键词路 '
            f'**{pct(keyword)}**{ci}。在本次全量数据上，向量路是主检索路径，'
            '关键词路作为补充；qrels 覆盖与检索稳定性见下方。')


def stability_conclusion(results: Dict[str, Any]) -> str:
    clean = all(
        system.get('empty_responses', 0) == 0
        and system.get('error_responses', 0) == 0
        and system.get('retrieve_failed_log_lines') == 0
        for system in results['systems'].values())
    if clean:
        return '- 本次运行空结果、HTTP 错误、检索失败日志均为 0，可表述为「无静默失败」。'
    return '- 本次运行存在空结果/HTTP 错误/日志增量，**不能**表述为「无静默失败」，详见 §5.4。'


def per_k_table(results: Dict[str, Any], metric: str, label: str) -> str:
    systems = results['systems']
    names = [name for name in ('vector', 'keyword') if name in systems]
    lines = ['| K | ' + ' | '.join(names) + ' |', '|---|' + '---|' * len(names)]
    for k in K_VALUES:
        key = f'{metric}@{k}'
        cells = [pct(metric_row(systems[name], key).get('mean')) for name in names]
        lines.append(f'| {k} | ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def distribution_table(results: Dict[str, Any]) -> str:
    lines = ['| 系统 | 指标 | 均值 [95% CI] | 中位数 | P10 | P90 |',
             '|---|---|---|---|---|---|']
    for name, system in results['systems'].items():
        for key, label in HEADLINE:
            row = metric_row(system, key)
            if not row:
                continue
            lines.append(
                f'| {name} | {label} | {pct(row.get("mean"))} '
                f'[{pct(row.get("ci95_low"))}, {pct(row.get("ci95_high"))}] | '
                f'{pct(row.get("median"))} | {pct(row.get("p10"))} | {pct(row.get("p90"))} |')
    return '\n'.join(lines)


def latency_table(results: Dict[str, Any]) -> str:
    lines = ['| 系统 | 查询数 | 空结果 | HTTP 错误 | 非语料占位 | 返回文档数 min/中位/max | 有效 pid 数 min/中位/max | 平均延迟 | P50 | P95 | 检索失败日志行 |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    for name, system in results['systems'].items():
        latency = system.get('latency_ms') or {}
        docs = system.get('docs_returned') or {}
        ranked_counts = [len(row.get('ranked') or []) for row in system.get('per_query') or []]
        if ranked_counts:
            ranked_text = (f'{min(ranked_counts)}/'
                           f'{statistics.median(ranked_counts):.0f}/{max(ranked_counts)}')
        else:
            ranked_text = '—'
        logs = system.get('retrieve_failed_log_lines', '未采集')
        lines.append(
            f'| {name} | {system.get("queries")} | {system.get("empty_responses")} | '
            f'{system.get("error_responses", 0)} | {system.get("unmapped_docs")} | '
            f'{docs.get("min", "—")}/{docs.get("median", "—")}/{docs.get("max", "—")} | '
            f'{ranked_text} | '
            f'{latency.get("mean", 0):.1f} ms | '
            f'{latency.get("p50", 0):.1f} ms | {latency.get("p95", 0):.1f} ms | {logs} |')
    return '\n'.join(lines)


def worst_queries(results: Dict[str, Any], system_name: str, limit: int = 10) -> str:
    system = results['systems'].get(system_name)
    if not system:
        return ''
    rows = sorted(system['per_query'],
                  key=lambda row: row.get('metrics', {}).get('ndcg@10', 0.0))[:limit]
    lines = ['| # | 查询 | 问题（截断） | Gold 数 | 首个命中排名 | NDCG@10 |',
             '|---|---|---|---|---|---|']
    for index, row in enumerate(rows, start=1):
        question = (row.get('question') or '').replace('|', '\\|')[:60]
        rank = row.get('first_gold_rank')
        lines.append(
            f'| {index} | `{row.get("qid")}` | {question} | {row.get("gold_count")} | '
            f'{rank if rank is not None else "未命中"} | '
            f'{pct(row.get("metrics", {}).get("ndcg@10"))} |')
    return '\n'.join(lines)


def comparison_summary(results: Dict[str, Any]) -> str:
    if 'vector' not in results['systems'] or 'keyword' not in results['systems']:
        return ''
    vector = {row['qid']: row for row in results['systems']['vector']['per_query']}
    keyword = {row['qid']: row for row in results['systems']['keyword']['per_query']}
    common = sorted(qid for qid in set(vector) & set(keyword)
                    if not vector[qid].get('empty') and not keyword[qid].get('empty'))
    wins = ties = losses = 0
    vector_only = keyword_only = 0
    for qid in common:
        left = vector[qid]['metrics'].get('ndcg@10', 0.0)
        right = keyword[qid]['metrics'].get('ndcg@10', 0.0)
        if left > right + 1e-12:
            wins += 1
        elif left < right - 1e-12:
            losses += 1
        else:
            ties += 1
        left_recall = vector[qid]['metrics'].get('recall@10', 0.0)
        right_recall = keyword[qid]['metrics'].get('recall@10', 0.0)
        if left_recall > 0 and right_recall == 0:
            vector_only += 1
        elif right_recall > 0 and left_recall == 0:
            keyword_only += 1
    return (
        f'- 共同查询：**{len(common)}** 条。\n'
        f'- NDCG@10 逐查询胜负：向量胜 **{wins}**、平 **{ties}**、关键词胜 **{losses}**。\n'
        f'- Recall@10 互补性：仅向量命中 **{vector_only}** 条，仅关键词命中 **{keyword_only}** 条。\n'
    )


def storage_table(db_stats: Optional[Dict[str, Any]]) -> str:
    if not db_stats:
        return '未采集（运行 `db_stats.py` 后通过 `--db-stats` 传入）。'
    rows = [
        ('向量行', db_stats.get('vector_rows')),
        ('新库形态（text=NULL，正文在 chunk 表）', db_stats.get('vector_text_null')),
        ('无 chunk 行的正文行', db_stats.get('text_without_chunk_rows')),
        ('chunk 行', db_stats.get('chunk_rows')),
        ('关键词索引文档数', db_stats.get('es_docs', db_stats.get('es_docs_error', '未采集'))),
        ('关键词索引有 text 的文档数', db_stats.get('es_docs_with_text', '未采集')),
        ('重复子片组（失败重试残留）', db_stats.get('duplicate_part_groups')),
        ('孤儿向量行（含有正文的）', db_stats.get('orphan_vector_rows')),
        ('真正孤儿（空正文）', db_stats.get('true_orphan_rows')),
        ('已导入 pid', db_stats.get('imported_pids')),
        ('qrels pid 总数', db_stats.get('qrels_pids_total')),
    ]
    lines = ['| 项 | 值 |', '|---|---|']
    lines.extend(f'| {label} | {value} |' for label, value in rows)
    return '\n'.join(lines)


def as_shipped_table(results: Dict[str, Any],
                     as_shipped: Optional[Dict[str, Any]]) -> str:
    if not as_shipped:
        return '未采集 as-shipped 对照。'
    lines = ['| 系统 | 指标 | as-shipped（默认 ef_search） | 本报告（显式设置） |',
             '|---|---|---|---|']
    for name in ('vector', 'keyword'):
        if name not in results['systems'] or name not in as_shipped['systems']:
            continue
        current = results['systems'][name].get('metrics') or {}
        old = as_shipped['systems'][name].get('metrics') or {}
        # 只对比在更浅候选集上仍有意义的指标；Recall@80 会被 ef_search 截断，不放进表。
        for key, label in (('ndcg@10', 'NDCG@10'), ('recall@10', 'Recall@10'),
                           ('mrr@10', 'MRR@10'), ('hit@10', 'Hit@10')):
            lines.append(
                f'| {name} | {label} | '
                f'{pct((old.get(key) or {}).get("mean"))} | '
                f'{pct((current.get(key) or {}).get("mean"))} |')
    shipped_docs = (as_shipped['systems'].get('vector') or {}).get('docs_returned') or {}
    tuned_docs = (results['systems'].get('vector') or {}).get('docs_returned') or {}
    lines.append(
        f'\n向量路返回文档数：as-shipped min/median/max = '
        f'{shipped_docs.get("min", "—")}/{shipped_docs.get("median", "—")}/'
        f'{shipped_docs.get("max", "—")}；本报告 = '
        f'{tuned_docs.get("min", "—")}/{tuned_docs.get("median", "—")}/'
        f'{tuned_docs.get("max", "—")}。')
    max_shipped = shipped_docs.get('max')
    if isinstance(max_shipped, (int, float)) and max_shipped < 80:
        median_shipped = shipped_docs.get('median', '—')
        old_recall80 = ((as_shipped['systems'].get('vector') or {})
                        .get('metrics') or {}).get('recall@80') or {}
        recall_text = (
            f'as-shipped 的 Recall@80 = {pct(old_recall80.get("mean"))}，'
            f'但实际深度中位 {median_shipped}，不能解释为 Recall@80。'
            if old_recall80 else '')
        lines.append(
            f'\n> as-shipped 向量路返回文档数中位 {median_shipped}、最大 '
            f'{int(max_shipped)}，因此其 K>40 的指标实际是在更浅的候选集上计算，'
            '不能与显式设置 `ef_search` 后的数值直接比较。'
            + (f' {recall_text}' if recall_text else ''))
    return '\n'.join(lines)


def render(results: Dict[str, Any], title: str, date: str,
           db_stats: Optional[Dict[str, Any]] = None,
           as_shipped: Optional[Dict[str, Any]] = None,
           import_note: str = '', rerank_note: str = '') -> str:
    config = results.get('config') or {}
    stats = results.get('dataset_stats') or {}
    coverage = results.get('coverage') or {}
    systems = results['systems']
    names = [name for name in ('vector', 'keyword') if name in systems]
    best_lines = []
    for key, label in HEADLINE[:4]:
        values = {name: metric_row(systems[name], key).get('mean', 0.0) for name in names}
        if not values:
            continue
        winner = max(values, key=values.get)
        best_lines.append(f'- {label}：**{winner}** 最高（{pct(values[winner])}）')

    observations = '- 未采集存储侧统计。'
    if db_stats:
        notes = []
        if db_stats.get('text_without_chunk_rows'):
            notes.append(
                f"- 并发导入时手工切片写入有 **{db_stats['text_without_chunk_rows']}** 行回落成"
                '「无 chunk 行的正文行」（正文落在 `vector.text`）。这类行仍能按正文'
                '映射回 pid，不影响本次指标；但它说明无 chunk 行的写入在并发下会出现。')
        if db_stats.get('duplicate_part_groups'):
            notes.append(
                f"- 有 **{db_stats['duplicate_part_groups']}** 组（下界）「同一 pid + 同一正文」"
                '的重复子片（多为导入失败后的重试残留）。指标在 pid 级去重，重复子片'
                '不会重复计分，但会占用原始 top-k 名额。')
        if db_stats.get('true_orphan_rows'):
            notes.append(
                f"- 存在 **{db_stats['true_orphan_rows']}** 条空正文的孤儿向量行"
                '（导入失败的部分提交 / 删除切片后未清向量行）。它们不是语料；'
                '检索若命中会按「非相关」占一个排名位。')
        observations = '\n'.join(notes) or '- 未观察到无 chunk 行的正文行或孤儿向量行。'

    return f"""# {title}

> 报告日期：{date}　|　范围：L1 检索指标（不含 LLM 答案质量）
> 数据集：{stats.get('dataset', 'duretrieval')}　|　知识库：`{config.get('kb_id', '')}`　|　产品版本：`{config.get('product_version') or '未记录'}`

## 1. 结论摘要

{chr(10).join(best_lines) if best_lines else '- 数据不足'}

{comparison_summary(results)}

{verdict(results)}

{stability_notes(results)}

本报告只回答一个问题：**在公开中文检索基准上，产品的向量检索与关键词检索分别能达到什么水平，两者是否互补。** 不涉及 LLM 生成质量、引用准确性或多轮对话。

## 2. 测试对象与环境

| 项 | 值 |
|---|---|
| 产品镜像 | `{config.get('product_version') or '未记录'}` |
| API 前缀 | `{config.get('base_url', '')}` |
| 检索入口 | `POST /retrieval`（type=0 向量 / type=1 关键词） |
| 评测知识库 | `{config.get('kb_id', '')}` |
| Embedding 模型 | `{config.get('embedding_model', 'Qwen3-Embedding-0.6B')}` |
| top_k | {config.get('top_k')}（产品 `RetrieveDTO` 上限 80） |
| 向量索引 | PostgreSQL 16.15 + pgvector 0.8.7，HNSW（m=16，ef_construction=64，测量时 `ef_search` = {config.get('ef_search') or '默认值（40）'}） |
| 关键词索引 | OpenSearch 2.19.6 + IK 分词 |
| 查询数 | {', '.join(f'{name}={systems[name].get("queries")}（有效 {systems[name].get("evaluated_queries")}）' for name in names)} |

> 产品版本取自测量时实际提供服务的容器镜像（见上表）；环境中若有其他任务重建 `latest`，请显式固定该 digest 复跑。

## 3. 数据集

| 项 | 值 |
|---|---|
| 数据集 | DuRetrieval（C-MTEB / MTEB 检索任务） |
| 上游 | {stats.get('citation', '')} |
| 论文 | DuReader_retrieval（EMNLP 2022，arXiv:2203.10232）；C-Pack / C-MTEB（SIGIR 2024，arXiv:2309.07597）；MTEB（arXiv:2210.07316） |
| 语料 passage | {stats.get('corpus_passages')} |
| 查询 | {stats.get('queries')} |
| qrels | {stats.get('qrels')}（二值相关性） |
| 有标注查询 | {stats.get('queries_with_qrels')} / {stats.get('queries')} |
| 每查询 gold 数 | 最少 {stats.get('gold_per_query_min')}，中位 {stats.get('gold_per_query_median')}，最多 {stats.get('gold_per_query_max')} |
| passage 长度（字符） | 中位 {stats.get('passage_chars_median')}，P90 {stats.get('passage_chars_p90')}，P99 {stats.get('passage_chars_p99')} |
| 重复正文 | {stats.get('duplicate_passage_texts', 0)} |
| License | 上游数据集卡未标注 license；本报告只使用聚合指标，不分发数据 |

数据集文件只落在 `.metrics-data/`（已 gitignore），**不入库**；本报告只包含聚合指标与少量查询示例。

## 4. 评测协议

1. **一 passage = 一（或数个）chunk**：通过产品的手工切片接口 `POST /knowledge-bases/{{kb-id}}/chunks` 导入，每条 passage 一个 chunk；超过 4,000 字符的 passage 按 4,000 字符切子片，子片共享同一 pid 标记，指标在 pid 级去重。这样把「切片策略」固定成变量，避免 512 字重新切片把多条 passage 混进一个 chunk。
2. **标记只用于展示**：`content`（embedding + 关键词索引正文）是干净 passage；`supplement`（向量路返回的展示正文）才带 `【DURET-<pid>】`。实测向量路返回 supplement、关键词路返回 content，两条路都能稳定映射回 pid，且标记不污染向量/BM25。
3. **非语料文档保守计分**：容器文件自身产生的正文、以及导入失败/删除切片后残留的空向量行，统一按「非相关、占一个排名位」处理（伪 pid），**不直接过滤**。
4. **指标**：Hit@K、Recall@K、Precision@K（分母固定 K，另报「实际返回为分母」的版本）、MRR@K、NDCG@K；K = {', '.join(map(str, config.get('ks') or K_VALUES))}。二值 qrels 下 NDCG 退化为折损命中。
5. **置信区间**：对查询做 2,000 次 bootstrap，报告中位数与 95% 分位区间；向量 vs 关键词用同一批查询做配对 bootstrap。
6. **静默失败检查**：`retrieve()` 在服务端把异常吞成空结果；空结果先重试一次，仍为空才计入。运行时统计 RKB 容器日志中 `retrieve failed, returning empty result` 的增量；headline 剔除空结果，另给「含空结果按 0 分」的敏感性表。
7. **单次运行**：检索在固定语料与固定模型下是确定性的（排序并列除外）；本报告不重复采样。
8. **排序深度**：向量路使用 pgvector HNSW；若 `hnsw.ef_search` 小于 `top_k`，实际只能返回 `ef_search` 条。正式测量前必须确认 `ef_search ≥ top_k`，并记录在环境表中。

**验收口径**（任何一条不满足，结论降级并显式登记）：

- 语料、查询、qrels 全量导入；qrels pid 覆盖率 100%；
- 每条查询至少执行一次；空结果重试一次后仍为空才计 0 分，并给出「含空结果」敏感性；
- 无 HTTP 错误；服务端 `retrieve failed` 日志增量为 0（或已逐条登记）；
- 两路都给出 K=1..80 的指标与查询级 95% bootstrap 区间；
- 未映射文档占比低于 5%，且能解释来源（容器文件/孤儿行）。

## 5. 结果

### 5.1 核心指标

{headline_table(results)}

> 方括号内为逐查询 bootstrap 的 95% 置信区间；Δ 为配对差值（正数表示向量更高）。
>
> K=10 时两路对全部查询都返回 ≥10 条，因此两种 precision 分母相同；K=80 时关键词路有少量查询返回不足 80 条（min 29），固定分母的 Precision@80 会被拉低，逐查询的 `precision_retrieved@80` 见 `results.json`。

**敏感性：空结果剔除 vs 按 0 分**

{sensitivity_table(results)}

### 5.2 指标随 K 的变化

**Recall@K**

{per_k_table(results, 'recall', 'Recall')}

**NDCG@K**

{per_k_table(results, 'ndcg', 'NDCG')}

**Hit@K**

{per_k_table(results, 'hit', 'Hit')}

**MRR@K**

{per_k_table(results, 'mrr', 'MRR')}

### 5.3 分布

{distribution_table(results)}

### 5.4 延迟与稳定性

{latency_table(results)}

### 5.5 诊断

**向量路最差 10 条查询**

{worst_queries(results, 'vector')}

**关键词路最差 10 条查询**

{worst_queries(results, 'keyword')}

### 5.6 存储侧核对

{storage_table(db_stats)}

{observations}

> 导入对账：{import_note or '见 `repair-summary.json`。'}

### 5.7 as-shipped 对照（默认 `ef_search`）

{as_shipped_table(results, as_shipped)}

## 6. 结论与边界

### 6.1 能证明什么

- 在固定语料、固定 embedding 模型、固定 top_k 与 `ef_search` 的条件下，产品两条检索路径的可复现指标（有效查询 {', '.join(f'{name}={systems[name].get("evaluated_queries")}' for name in names)}）。
- 向量路与关键词路的互补程度（逐查询胜负与 Recall@10 互补计数）。
- 检索稳定性：空结果、HTTP 错误、检索失败日志与未映射文档占比均已在 §5.4 与 §1 登记。
{stability_conclusion(results)}

### 6.2 不能证明什么

- **不能与公开榜单直接对比**：本报告使用产品自己的 embedding 模型、手工切片方式与 top_k=80，而榜单通常用不同的模型、切片与 Recall@100。
- **不代表线上真实流量分布**：DuRetrieval 是中文网页检索基准，query 分布与产品用户问题不同。
- **不覆盖生成质量**：答案忠实性、相关性、正确性、引用准确性属于 L2，留给 `deepseek-chat` judge 体系。
- **不覆盖混合检索/重排/多轮**：本期只测 `type=0/1` 两条基础路径；融合、cross-encoder/LLM 重排、query rewrite 需要单独消融。
- **top_k 上限 80**：产品 `RetrieveDTO` 限制 1–80，无法报告 Recall@100；这是产品约束，不是数据集限制。
- **HNSW 有效深度依赖 `hnsw.ef_search`**：产品默认值为 40。本报告测量时显式设为 {config.get('ef_search') or '默认值（40）'}；若按默认值部署，向量路返回文档数中位约 40–41（绝大多数 40–42，个别可到 76），K>40 的指标不可直接复用。

### 6.3 复现

```bash
# 1) 准备数据（首次会从 HuggingFace 下载约 64 MB）
python3 tools/rag-metrics/prepare_dataset.py --out .metrics-data/duretrieval

# 2) 建库并灌语料（8 并发实测 ~19 parts/s；16 并发会打满 DB 连接池）
python3 tools/rag-metrics/import_corpus.py --workers 8 --kb-name <kb-name>

# 3) 按子片正文对账，补齐失败/漏导的子片（幂等）
python3 tools/rag-metrics/repair_parts.py --kb-id <kb-id> --workers 8

# 4) 从 PG 重建 OpenSearch 关键词索引：text = COALESCE(向量表 text, chunk 表 text)
#    注意：正文去重后新库的向量表 text 恒为 NULL，正文在 chunk 表；只读向量表会把
#    text 丢空（关键词路会掉到 ~1%）。本评测用 reindex_es.py（会剥掉 【DURET-<pid>】 标记）。
python3 tools/rag-metrics/reindex_es.py --kb-id <kb-id> --apply

# 5) 让向量路能返回 top_k=80 条（产品默认 ef_search=40 会截断）
docker exec rag-studio-postgresql-1 psql -U rag -d rag_studio \\
  -c "ALTER DATABASE rag_studio SET hnsw.ef_search = 80;"
docker restart rag-studio-rag-knowledge-base-1

# 6) 跑正式（tuned）与 as-shipped 两轮
#    客户端自动 POST /auth/login（RKB_USERNAME / RKB_PASSWORD，默认 admin / admin）
python3 tools/rag-metrics/run_retrieval_metrics.py \\
  --kb-id <kb-id> --systems vector,keyword --top-k 80 --ef-search 80 \\
  --out .metrics-data/runs/<kb-id>-tuned \\
  --product-version <image-digest> \\
  --log-container rag-studio-rag-knowledge-base-1 --strict-coverage
#    as-shipped：先 RESET ef_search 并重启，再以 --ef-search "默认（40）" 跑一轮

# 7) 存储侧核对 + 渲染
python3 tools/rag-metrics/db_stats.py --kb-id <kb-id> \\
  --es-index doc_<kb-id> \\
  --out .metrics-data/runs/<kb-id>-tuned/db-stats.json
python3 tools/rag-metrics/render_report.py \\
  --results .metrics-data/runs/<kb-id>-tuned/results.json \\
  --db-stats .metrics-data/runs/<kb-id>-tuned/db-stats.json \\
  --as-shipped-results .metrics-data/runs/<kb-id>-as-shipped/results.json \\
  --out docs/rag-retrieval-metrics.md

# 8) 恢复部署默认
docker exec rag-studio-postgresql-1 psql -U rag -d rag_studio \\
  -c "ALTER DATABASE rag_studio RESET hnsw.ef_search;"
docker restart rag-studio-rag-knowledge-base-1
```

### 6.4 建议

1. **部署侧**：若对外承诺 `top_k=80`，请把 `hnsw.ef_search` 设为 ≥80（或在检索连接上按 `top_k` 动态 `SET LOCAL`）；否则向量路会静默只返回约 40 条。
2. **导入侧**：该评测库在并发导入时留下 {db_stats.get('text_without_chunk_rows', 0) if db_stats else '未采集'} 行无 chunk 行的正文、{db_stats.get('duplicate_part_groups', 0) if db_stats else '未采集'} 组重复子片。建议导入并发控制在 8–12（16 并发会打满 DB 连接池），或让手工切片写路径显式判定 chunk 表存在、按业务键做幂等。
3. **索引侧**：从 PG 重建关键词索引时必须取 `COALESCE(vector.text, chunk.text)`；正文去重后新库的向量表 `text` 恒为 NULL，只读向量表会把索引正文丢空。评测侧的 `reindex_es.py` 已按此实现，并在索引前剥掉评测标记。
4. **评测侧**：L2 用 `deepseek-chat` 做 judge，覆盖 faithfulness / answer_relevancy / answer_correctness / context_precision / context_recall、引用准确性与负样本拒答；混合检索、重排、多轮 rewrite 需单独消融。

> LLM rerank 的实测消融：当前 `LLMReranker` 不提升（NDCG@10 −3.1 pp、MRR@10 −5.2 pp，且单 query 82 s），默认不启用。

{rerank_note}

## 附录 A：指标定义

| 指标 | 定义 |
|---|---|
| Hit@K | top-K 中至少一条 gold 记为 1，否则 0 |
| Recall@K | top-K 覆盖的 gold 数 / gold 总数 |
| Precision@K | top-K 中 gold 数 / K（分母固定 K） |
| MRR@K | 第一条 gold 的排名倒数；top-K 内无命中记 0 |
| NDCG@K | DCG@K / IDCG@K；DCG = Σ rel_i / log2(i+1)，IDCG 按 gold 相关性降序 |

## 附录 B：数据覆盖

| 项 | 值 |
|---|---|
| 已导入 pid | {coverage.get('imported_pids')} |
| qrels pid 总数 | {coverage.get('qrels_pids_total')} |
| qrels pid 缺失 | {coverage.get('qrels_pids_missing')} |
| 限制到已导入语料后有 gold 的查询 | {coverage.get('queries_with_gold_after_restrict')} |
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--title', default='RAG 检索指标验收报告（L1）')
    parser.add_argument('--date', default=dt.date.today().isoformat())
    parser.add_argument('--db-stats', default='')
    parser.add_argument('--as-shipped-results', default='',
                        help='可选：默认 ef_search 下的 results.json，用于对照')
    parser.add_argument('--allow-partial', action='store_true',
                        help='允许在 qrels 覆盖不完整时渲染（默认拒绝）')
    parser.add_argument('--import-note', default='',
                        help='导入对账说明（写进 §5.6）')
    parser.add_argument('--rerank-note', default='',
                        help='rerank 结论说明（写进 §6.4 链接后）')
    args = parser.parse_args()
    with open(args.results, encoding='utf-8') as handle:
        results = json.load(handle)
    coverage = results.get('coverage') or {}
    if coverage.get('qrels_pids_missing') and not args.allow_partial:
        raise SystemExit(
            f'qrels 仍有 {coverage["qrels_pids_missing"]} 个 pid 未导入；'
            '拒绝渲染完整报告（确实要出部分结果请加 --allow-partial）')
    db_stats = None
    if args.db_stats:
        with open(args.db_stats, encoding='utf-8') as handle:
            db_stats = json.load(handle)
    as_shipped = None
    if args.as_shipped_results:
        with open(args.as_shipped_results, encoding='utf-8') as handle:
            as_shipped = json.load(handle)
    markdown = render(results, args.title, args.date, db_stats, as_shipped,
                      args.import_note, args.rerank_note)
    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(markdown)
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
