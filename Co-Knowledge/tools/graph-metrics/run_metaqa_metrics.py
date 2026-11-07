#!/usr/bin/env python3
"""MetaQA 图谱检索指标（L1）：种子召回 + 子图答案覆盖 + 延迟。

协议（报告里必须原样保留）：

1. 数据：MetaQA vanilla ``qa_test``；题目里的 ``[topic]`` 是数据集自带标注，
   检索时去掉括号，只用正文。答案就是 KB 实体名。
2. 参数：``seed_k`` 默认 10、``depth`` 默认等于 hop（1-hop→1，2-hop→2，
   3-hop→3；可用 ``--depths`` 覆盖成 1,2,3 看深度收益）、``limit=1000``。
3. 指标：
   * ``topic_hit``      topic entity ∈ ``seed_entity_ids``（实体链接）
   * ``answer_covered`` 任一标准答案 ∈ 返回子图实体（子图覆盖）
   * ``answer_recall``  多答案题的覆盖比例
   每个比例给题目级 95% bootstrap 区间；同时给「含错误按 0 分」的保守值。
4. 失败不静默：每题的异常落 ``results.jsonl`` 并计入 ``errors``；
   ``truncated`` 标记子图实体是否撞到 ``limit`` 上限。

复跑是增量的：``results.jsonl`` 里已有的 ``hop|depth|qid`` 直接跳过。
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence

from graph_client import DEFAULT_EMBEDDING, GraphClient, RkbError
from metrics import aggregate, evaluate_retrieval, mean, percentile
from prepare_metaqa import strip_brackets

DEFAULT_DATA = Path('.metrics-data/metaqa')
DEFAULT_HOPS = (1, 2, 3)
SAMPLE_SEED = 20261030


# ----------------------------------------------------------------------
# 数据
# ----------------------------------------------------------------------


def load_questions(data_dir: Path) -> list[dict]:
    path = data_dir / 'questions.jsonl'
    if not path.exists():
        raise RkbError(f'{path} 不存在；先跑 prepare_metaqa.py')
    with path.open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def hop_number(hop: str) -> int:
    return int(hop.split('-')[0])


def sample_questions(rows: Sequence[dict], *, hops: Iterable[int],
                     limit_per_hop: int, seed: int = SAMPLE_SEED) -> list[dict]:
    """每个 hop 固定抽样；``limit_per_hop<=0`` 表示全量。"""
    selected: list[dict] = []
    for hop in hops:
        group = sorted((row for row in rows if hop_number(row['hop']) == hop),
                       key=lambda row: row['qid'])
        if limit_per_hop > 0 and len(group) > limit_per_hop:
            rng = random.Random(seed + hop)
            group = sorted(rng.sample(group, limit_per_hop),
                           key=lambda row: row['qid'])
        selected.extend(group)
    return selected


def resolve_limits(limits: str, hops: Iterable[int], default: int) -> dict[int, int]:
    """``--limits 1000,3000,5000`` 按 hop 给边预算；空串用统一 ``default``。"""
    hops = list(hops)
    if not limits.strip():
        return {hop: default for hop in hops}
    parts = [int(part) for part in limits.split(',') if part.strip()]
    if len(parts) == 1:
        return {hop: parts[0] for hop in hops}
    if len(parts) != len(hops):
        raise ValueError(f'--limits 需要 1 个或 {len(hops)} 个值: {limits!r}')
    return dict(zip(hops, parts))


def resolve_depths(depths: str, hops: Iterable[int]) -> dict[int, list[int]]:
    """``--depths hop`` 按 hop 取深度；显式列表对所有 hop 生效。"""
    hops = list(hops)
    if depths.strip().lower() == 'hop':
        return {hop: [hop] for hop in hops}
    parsed = sorted({int(part) for part in depths.split(',') if part.strip()})
    if not parsed:
        raise ValueError('--depths 为空')
    for depth in parsed:
        if depth < 1 or depth > 10:
            raise ValueError(f'depth 必须在 1-10: {depth}')
    return {hop: list(parsed) for hop in hops}


# ----------------------------------------------------------------------
# 单题
# ----------------------------------------------------------------------


def retrieve_one(client: GraphClient, *, table: str, row: dict, depth: int,
                 embedding: str, seed_k: int, limit: int,
                 retries: int = 2) -> dict:
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body = client.retrieve_graph(
                table, strip_brackets(row['question']), embedding=embedding,
                seed_k=seed_k, depth=depth, limit=limit)
            break
        except Exception as error:                                  # noqa: BLE001
            last_error = error
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    else:
        return {
            'hop': row['hop'], 'depth': depth, 'qid': row['qid'],
            'question': row['question'], 'topic': row['topic'],
            'answers': row['answers'], 'error': str(last_error),
            'latency_s': round(time.perf_counter() - started, 3),
        }

    result = (body.get('base_results') or [{}])[0] or {}
    seeds = result.get('seed_entity_ids') or []
    entities = result.get('entities') or []
    edges = result.get('edges') or []
    entity_ids = [entity.get('entity_id') for entity in entities
                  if entity.get('entity_id') is not None]
    evaluated = evaluate_retrieval(row['topic'], row['answers'], seeds, entity_ids,
                                   edges=edges, depth=depth)
    return {
        'hop': row['hop'], 'depth': depth, 'qid': row['qid'],
        'question': row['question'], 'topic': row['topic'],
        'answers': row['answers'], **evaluated,
        'seed_count': len(seeds),
        'limit': limit,
        'entity_count': len(entities),
        'edge_count': len(edges),
        # limit 现在作用于「边」；实体只取返回边端点，所以以边为准，
        # 同时保留实体撞上限的旧口径（非检索路径可能仍是实体上限）。
        'truncated': 1.0 if len(edges) >= limit or len(entities) >= limit else 0.0,
        'latency_s': round(time.perf_counter() - started, 3),
        'error': '',
    }


# ----------------------------------------------------------------------
# 聚合与报告
# ----------------------------------------------------------------------


def summarize(rows: Sequence[dict], *, rounds: int) -> dict:
    ok = [row for row in rows if not row.get('error')]
    errors = len(rows) - len(ok)
    summary: Dict[str, Any] = {
        'attempted': len(rows), 'ok': len(ok), 'errors': errors,
        'error_rate': (errors / len(rows)) if rows else 0.0,
    }
    for metric in ('topic_hit', 'answer_covered', 'answer_reachable',
                   'answer_recall', 'answer_reach_recall'):
        stats = aggregate(ok, metric=metric, rounds=rounds)
        conservative = (sum(float(row[metric]) for row in ok) / len(rows)) if rows else 0.0
        summary[metric] = {**stats, 'conservative': conservative}
    summary['empty_seed_rate'] = mean(
        1.0 if row.get('seed_count', 0) == 0 else 0.0 for row in ok)
    summary['truncated_rate'] = mean(
        float(row.get('truncated', 0.0)) for row in ok)
    summary['mean_entities'] = mean(float(row.get('entity_count', 0)) for row in ok)
    latencies = sorted(float(row.get('latency_s', 0.0)) for row in ok)
    summary['latency_p50'] = percentile(latencies, 0.5)
    summary['latency_p95'] = percentile(latencies, 0.95)
    return summary


def group_rows(rows: Sequence[dict], hops: Iterable[int],
               depths_by_hop: dict[int, list[int]]) -> dict[tuple[int, int], list[dict]]:
    groups: dict[tuple[int, int], list[dict]] = {}
    for hop in hops:
        for depth in depths_by_hop[hop]:
            groups[(hop, depth)] = [
                row for row in rows
                if hop_number(row['hop']) == hop and row['depth'] == depth]
    return groups


def product_digest(container: str = 'rag-studio-rag-knowledge-base-1') -> str:
    """尽力而为：优先仓库 digest，本地构建没有 digest 时回落到 image id。"""
    try:
        image = subprocess.run(
            ['docker', 'inspect', '--format', '{{.Image}}', container],
            capture_output=True, text=True, check=True).stdout.strip()
        if not image:
            return ''
        raw = subprocess.run(
            ['docker', 'image', 'inspect', image, '--format',
             '{{json .RepoDigests}}'],
            capture_output=True, text=True, check=True).stdout.strip()
        digests = json.loads(raw or '[]')
        return digests[0] if digests else image
    except Exception:                                               # noqa: BLE001
        return ''


def write_report(path: Path, *, config: dict, summary: dict,
                 dataset: dict) -> None:
    lines = [
        '# MetaQA 图谱检索指标（L1）',
        '',
        f'> 报告时间：{config["started_at"]}　|　知识库：`{config["table"]}`'
        f'　|　embedding：`{config["embedding"]}`',
        f'> 产品镜像：`{config.get("product_digest") or "未取到"}`',
        '',
        '## 1. 结论摘要',
        '',
    ]
    for (hop, depth), cell in sorted(summary.items()):
        topic = cell['topic_hit']
        covered = cell['answer_covered']
        reachable = cell['answer_reachable']
        lines.append(
            f'- **{hop}-hop / depth={depth}**：topic 召回 '
            f'**{topic["mean"] * 100:.1f}%**，答案覆盖 '
            f'**{covered["mean"] * 100:.1f}%**，答案可达 '
            f'**{reachable["mean"] * 100:.1f}%**，覆盖召回 '
            f'{cell["answer_recall"]["mean"] * 100:.1f}%，可达召回 '
            f'{cell["answer_reach_recall"]["mean"] * 100:.1f}%；'
            f'空种子 {cell["empty_seed_rate"] * 100:.1f}%，'
            f'截断 {cell["truncated_rate"] * 100:.1f}%，'
            f'P95 {cell["latency_p95"]:.2f}s。')
    lines += [
        '',
        '## 2. 数据集与协议',
        '',
        '| 项 | 值 |',
        '|---|---|',
        '| 数据集 | MetaQA（vanilla，test split） |',
        f'| KB | WikiMovies：{dataset.get("edges", "?")} 条三元组 / '
        f'{dataset.get("entities", "?")} 个实体 |',
        '| 题量（本次） | ' + ' / '.join(
            f'{hop}-hop {config["per_hop"].get(f"{hop}-hop", 0)}'
            for hop in (1, 2, 3)) + ' |',
        f'| 抽样上限 | {config["limit_per_hop"] or "全量"} 题/跳 |',
        f'| seed_k | {config["seed_k"]} |',
        '| limit | ' + ' / '.join(
            f'{hop}-hop {config.get("limits", {}).get(str(hop), config["limit"])}'
            for hop in (1, 2, 3)) + '（边数上限；实体只带返回边端点） |',
        f'| depth | {config["depths"]} |',
        f'| 并发 | {config["workers"]} |',
        '',
        '口径：题目里的 `[topic]` 是 MetaQA 自带标注；检索时去掉括号，只用正文。'
        '`topic_hit` 看 topic 是否出现在 `seed_entity_ids`；'
        '`answer_covered` 看任一标准答案是否出现在返回子图实体；'
        '`answer_reachable` 从 topic 出发、用返回子图的边做 depth 跳内无向 BFS，'
        '看任一答案是否真的可达（比「在实体列表里」严格，避免被 Comedy/English 这类'
        '高频答案蒙中）；`answer_recall` 是多答案题在返回实体里的覆盖比例，'
        '`answer_reach_recall` 是多答案题在返回边上的可达比例（全答案口径）。'
        '区间为题目级 95% bootstrap。',
        '',
        '## 3. 结果',
        '',
        '| hop | depth | n | topic 召回 | 答案覆盖 | 答案可达 | 覆盖召回 | 可达召回 | 空种子 | 截断 | P95(s) |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for (hop, depth), cell in sorted(summary.items()):
        topic = cell['topic_hit']
        covered = cell['answer_covered']
        reachable = cell['answer_reachable']
        recall = cell['answer_recall']
        reach_recall = cell['answer_reach_recall']
        lines.append(
            f'| {hop} | {depth} | {cell["ok"]} | '
            f'{topic["mean"] * 100:.1f}% '
            f'[{topic["ci_low"] * 100:.1f}, {topic["ci_high"] * 100:.1f}] | '
            f'{covered["mean"] * 100:.1f}% '
            f'[{covered["ci_low"] * 100:.1f}, {covered["ci_high"] * 100:.1f}] | '
            f'{reachable["mean"] * 100:.1f}% '
            f'[{reachable["ci_low"] * 100:.1f}, {reachable["ci_high"] * 100:.1f}] | '
            f'{recall["mean"] * 100:.1f}% '
            f'[{recall["ci_low"] * 100:.1f}, {recall["ci_high"] * 100:.1f}] | '
            f'{reach_recall["mean"] * 100:.1f}% '
            f'[{reach_recall["ci_low"] * 100:.1f}, {reach_recall["ci_high"] * 100:.1f}] | '
            f'{cell["empty_seed_rate"] * 100:.1f}% | '
            f'{cell["truncated_rate"] * 100:.1f}% | '
            f'{cell["latency_p95"]:.2f} |')
    lines += [
        '',
        '## 4. 失败与保守口径',
        '',
        '| hop | depth | 尝试 | 成功 | 错误率 | topic 召回（含错误按 0） | '
        '答案覆盖（含错误按 0） | 答案可达（含错误按 0） |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for (hop, depth), cell in sorted(summary.items()):
        lines.append(
            f'| {hop} | {depth} | {cell["attempted"]} | {cell["ok"]} | '
            f'{cell["error_rate"] * 100:.1f}% | '
            f'{cell["topic_hit"]["conservative"] * 100:.1f}% | '
            f'{cell["answer_covered"]["conservative"] * 100:.1f}% | '
            f'{cell["answer_reachable"]["conservative"] * 100:.1f}% |')
    lines += [
        '',
        '## 5. 复跑',
        '',
        '```bash',
        'python3 tools/graph-metrics/prepare_metaqa.py',
        'python3 tools/graph-metrics/import_metaqa.py',
        f'python3 tools/graph-metrics/run_metaqa_metrics.py --kb-id {config["kb_id"]} '
        f'--limit-per-hop {config["limit_per_hop"]} --depths {config["depths"]} '
        f'--seed-k {config["seed_k"]} --limit {config["limit"]} '
        f'--limits ' + ','.join(
            str(config.get('limits', {}).get(str(hop), config['limit']))
            for hop in (1, 2, 3)),
        '```',
        '',
    ]
    path.write_text('\n'.join(lines), encoding='utf-8')


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


def run(data_dir: Path, *, kb_id: str, table: str = '', embedding: str = '',
        hops: Iterable[int] = DEFAULT_HOPS, limit_per_hop: int = 500,
        depths: str = 'hop', seed_k: int = 10, limit: int = 1000,
        limits: str = '',
        workers: int = 8, out_dir: Path | None = None,
        rounds: int = 2000, resume: bool = True,
        client: GraphClient | None = None) -> dict:
    hops = sorted(set(hops))
    if not hops:
        raise ValueError('至少一个 hop')
    depths_by_hop = resolve_depths(depths, hops)
    limits_by_hop = resolve_limits(limits, hops, limit)
    rows = sample_questions(load_questions(data_dir), hops=hops,
                            limit_per_hop=limit_per_hop)
    api_id = kb_id[6:] if kb_id.startswith('graph_') else kb_id
    table = table or f'graph_{api_id}'
    embedding = embedding or DEFAULT_EMBEDDING
    out_dir = out_dir or Path('.metrics-data/runs') / f'metaqa-{api_id}'
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / 'results.jsonl'

    done: set[str] = set()
    if not resume:
        results_path.write_text('', encoding='utf-8')
    elif results_path.exists():
        with results_path.open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('qid'):
                    done.add(f'{row["hop"]}|{row["depth"]}|{row["qid"]}')

    tasks = [
        (row, depth, limits_by_hop[hop_number(row['hop'])])
        for row in rows
        for depth in depths_by_hop[hop_number(row['hop'])]
        if f'{row["hop"]}|{depth}|{row["qid"]}' not in done
    ]
    client = client or GraphClient()
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'kb={api_id} table={table} questions={len(rows)} '
          f'cells={sum(len(value) for value in depths_by_hop.values())} '
          f'tasks={len(tasks)} (skipped {len(done)})')
    completed = 0
    with results_path.open('a', encoding='utf-8') as sink:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(retrieve_one, client, table=table, row=row,
                            depth=depth, embedding=embedding, seed_k=seed_k,
                            limit=task_limit): (row, depth, task_limit)
                for row, depth, task_limit in tasks
            }
            for future in as_completed(futures):
                result = future.result()
                sink.write(json.dumps(result, ensure_ascii=False) + '\n')
                sink.flush()
                completed += 1
                if completed % 50 == 0 or completed == len(tasks):
                    print(f'progress {completed}/{len(tasks)}')

    all_rows = []
    with results_path.open(encoding='utf-8') as handle:
        for line in handle:
            try:
                all_rows.append(json.loads(line))
            except ValueError:
                continue
    groups = group_rows(all_rows, hops, depths_by_hop)
    summary = {key: summarize(value, rounds=rounds)
               for key, value in groups.items()}
    per_hop = {
        f'{hop}-hop': sum(1 for row in all_rows
                          if hop_number(row['hop']) == hop
                          and row['depth'] == depths_by_hop[hop][0])
        for hop in hops
    }
    dataset = {}
    imported_path = data_dir / 'imported.json'
    stats_path = data_dir / 'stats.json'
    imported = json.loads(imported_path.read_text(encoding='utf-8')) \
        if imported_path.exists() else {}
    if imported.get('kb_id') == api_id:
        dataset = {'entities': imported.get('entities'),
                   'edges': imported.get('edges')}
    elif stats_path.exists():
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        dataset = {'entities': stats.get('entities'), 'edges': stats.get('edges')}
    config = {
        'started_at': started_at,
        'kb_id': api_id, 'table': table, 'embedding': embedding,
        'seed_k': seed_k, 'limit': limit,
        'limits': {str(hop): limits_by_hop[hop] for hop in hops},
        'depths': depths,
        'limit_per_hop': limit_per_hop, 'workers': workers,
        'per_hop': per_hop, 'product_digest': product_digest(),
    }
    payload = {
        'config': config, 'dataset': dataset,
        'summary': {f'{hop}|{depth}': value for (hop, depth), value in summary.items()},
        'errors': sum(cell['errors'] for cell in summary.values()),
        'attempted': sum(cell['attempted'] for cell in summary.values()),
    }
    (out_dir / 'results.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_report(out_dir / 'report.md', config=config,
                 summary=summary, dataset=dataset)
    print(json.dumps({key: value for key, value in payload.items()
                      if key != 'summary'}, ensure_ascii=False, indent=2))
    for (hop, depth), cell in sorted(summary.items()):
        print(f'{hop}-hop depth={depth}: topic_hit={cell["topic_hit"]["mean"]:.4f} '
              f'answer_covered={cell["answer_covered"]["mean"]:.4f} '
              f'answer_reachable={cell["answer_reachable"]["mean"]:.4f} '
              f'answer_recall={cell["answer_recall"]["mean"]:.4f} '
              f'errors={cell["errors"]} n={cell["ok"]}')
    print(f'wrote {out_dir}/results.json and report.md')
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb-id', required=True, help='知识库业务 id（可带 graph_ 前缀）')
    parser.add_argument('--table', default='', help='默认 graph_<kb-id>')
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--embedding', default=DEFAULT_EMBEDDING)
    parser.add_argument('--hops', default='1,2,3')
    parser.add_argument('--limit-per-hop', type=int, default=500,
                        help='每跳抽样题数；0 = 全量')
    parser.add_argument('--depths', default='hop',
                        help="'hop' 表示 depth=hop；或显式 '1,2,3'")
    parser.add_argument('--seed-k', type=int, default=10)
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--limits', default='',
                        help="按 hop 的边预算，如 '1000,3000,5000'；空=统一 --limit")
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--bootstrap', type=int, default=2000)
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args(argv)
    try:
        payload = run(
            args.data_dir, kb_id=args.kb_id, table=args.table,
            embedding=args.embedding,
            hops=[int(part) for part in args.hops.split(',') if part.strip()],
            limit_per_hop=args.limit_per_hop, depths=args.depths,
            seed_k=args.seed_k, limit=args.limit, limits=args.limits,
            workers=args.workers,
            out_dir=args.out, rounds=args.bootstrap, resume=not args.no_resume)
    except (RkbError, ValueError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0 if payload['errors'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
