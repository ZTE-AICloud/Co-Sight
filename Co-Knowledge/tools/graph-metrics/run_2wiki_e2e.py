#!/usr/bin/env python3
"""跑 2WikiMultiHopQA 端到端问答并计算答案级指标（EM / F1 / 覆盖 / 证据召回）。

前置：``prepare_2wiki.py`` + ``import_2wiki.py``，后者把文档库、图谱库、已发布
工作流传进 ``state.json``。

协议：

* 每题独立 ``conversation_id``（不带多轮历史），``include_retrieval=true``；
* 答案先去掉 ``<think>...</think>`` 推理片段再评分；
* ``answer`` 为字符串，多个可接受答案用 ``|`` 分隔时取最佳；
* 指标：Exact Match、token F1、答案被预测覆盖（短答案常见）、
  gold supporting title 在检索文本里的命中率、端到端延迟。
* 结果逐行落 ``results.jsonl``，默认断点续跑。

跑法::

    python3 tools/graph-metrics/run_2wiki_e2e.py --workers 4
    python3 tools/graph-metrics/run_2wiki_e2e.py --no-resume --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import string
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from graph_client import RkbClient

DEFAULT_BASE = 'http://127.0.0.1/api/co-knowledge/v1'
DEFAULT_DATA = Path('.metrics-data/2wiki/data')
DEFAULT_STATE = Path('.metrics-data/2wiki/state.json')
DEFAULT_OUT = Path('.metrics-data/runs/2wiki-e2e')
DEFAULT_RERANK_MODEL = 'Qwen3-Reranker-4B'
THINK_RE = re.compile(r'<think\b[^>]*>.*?</think\s*>', re.I | re.S)
WHITESPACE_RE = re.compile(r'\s+')
ARTICLES = {'a', 'an', 'the'}
TITLE_PREFIXES = (
    'king', 'queen', 'emperor', 'empress', 'prince', 'princess', 'duke',
    'duchess', 'count', 'countess', 'maharaja', 'maharani', 'saint', 'sir',
    'lord', 'lady',
)
PARENTHETICAL_RE = re.compile(r'\([^)]*\)')


def normalize_answer(text: str) -> str:
    """SQuAD 口径的小写 / 去标点 / 去冠词 / 压缩空白。"""
    text = (text or '').lower()
    text = ''.join(' ' if char in string.punctuation else char for char in text)
    text = ' '.join(word for word in text.split() if word not in ARTICLES)
    return WHITESPACE_RE.sub(' ', text).strip()


def normalize_variant(text: str) -> str:
    """严格 EM 之外的轻量归一：去括号、去爵位/王室前缀。"""
    text = PARENTHETICAL_RE.sub(' ', text or '')
    normalized = normalize_answer(text)
    changed = True
    while changed:
        changed = False
        for prefix in TITLE_PREFIXES:
            if normalized.startswith(prefix + ' '):
                normalized = normalized[len(prefix) + 1:].strip()
                changed = True
    return normalized


def variant_match(prediction: str, gold: str) -> bool:
    """答案变体：别名前缀/后缀、逗号后限定语、少量修饰词差异。

    * `Grammy` vs `Grammy Award`
    * `Nürtingen` vs `Nürtingen, Württemberg`
    * `Herod` vs `Herod the Great`
    * `King Gustaf VI Adolf of Sweden` vs `Gustaf VI Adolf of Sweden`
    """
    pred = normalize_variant(prediction)
    gold = normalize_variant(gold)
    if not pred or not gold:
        return False
    if pred == gold:
        return True
    pred_tokens = pred.split()
    gold_tokens = gold.split()
    # 一方是另一方的 token 前缀/后缀：允许最多 2 个限定词差异。
    if len(pred_tokens) > len(gold_tokens):
        longer, shorter = pred_tokens, gold_tokens
    else:
        longer, shorter = gold_tokens, pred_tokens
    extra = len(longer) - len(shorter)
    if extra > 2:
        return False
    # 前缀方向双向都接受（Grammy Award / Herod the Great / Paris, France）。
    if longer[:len(shorter)] == shorter:
        return True
    # 后缀：gold 是后缀（Louisiana），或较短的一方至少 2 个 token
    # （Port of Spain）。单 token 的预测（France vs Paris, France）不放行，
    # 否则会把“只答国家”的错答判对。
    if longer[-len(shorter):] != shorter:
        return False
    return shorter == gold_tokens or len(shorter) >= 2


def token_f1(prediction: str, gold: str) -> float:
    pred_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    if not pred_tokens or not gold_tokens:
        return float(pred_tokens == gold_tokens)
    common = 0
    remaining = list(gold_tokens)
    for token in pred_tokens:
        if token in remaining:
            remaining.remove(token)
            common += 1
    if common == 0:
        return 0.0
    precision = common / len(pred_tokens)
    recall = common / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def score_answer(prediction: str, gold: str) -> dict:
    golds = [part.strip() for part in re.split(r'\s*\|\s*', gold) if part.strip()]
    golds = golds or [gold]
    best_f1 = max(token_f1(prediction, candidate) for candidate in golds)
    best_em = max(normalize_answer(prediction) == normalize_answer(candidate)
                  for candidate in golds)
    best_em_normalized = max(variant_match(prediction, candidate)
                             for candidate in golds)
    normalized_pred = normalize_answer(prediction)
    contains = any(
        normalize_answer(candidate)
        and re.search(r'(?<!\w)' + re.escape(normalize_answer(candidate)) + r'(?!\w)',
                      normalized_pred)
        for candidate in golds)
    return {
        'em': float(best_em),
        'em_normalized': float(best_em_normalized),
        'f1': best_f1,
        'contains': float(contains),
    }


def strip_answer(answer: str) -> str:
    text = THINK_RE.sub('', answer or '')
    return text.strip().strip('"').strip("'").strip()


def evidence_hit(text: str, gold_titles: list[str]) -> float:
    lowered = (text or '').lower()
    if not gold_titles:
        return 0.0
    hit = sum(1 for title in gold_titles if title.lower() in lowered)
    return hit / len(gold_titles)


def load_questions(data_dir: Path, limit: int | None) -> list[dict]:
    rows = [json.loads(line) for line in
            (data_dir / 'questions.jsonl').open(encoding='utf-8') if line.strip()]
    return rows[:limit] if limit else rows


def query_one(client: RkbClient, workflow_id: str, row: dict) -> dict:
    started = time.time()
    response = client._request('POST', '/query', json_body={
        'question': row['question'],
        'conversation_id': str(uuid.uuid4()),
        'workflow_id': workflow_id,
        'stream': False,
        'include_retrieval': True,
    }, retries=2)
    elapsed = time.time() - started
    answer = strip_answer(response.get('answer') or '')
    retrieval = response.get('retrieval') or {}
    items = retrieval.get('items') or []
    context = '\n'.join(str(item.get('text') or '') for item in items)
    result = {
        **{key: row[key] for key in
           ('qid', 'type', 'question', 'answer', 'gold_titles', 'context_titles')},
        'prediction': answer,
        'elapsed_s': elapsed,
        'retrieval_items': len(items),
        'graph_items': sum(1 for item in items if item.get('kind') == 'graph'),
        'timings': retrieval.get('timings') or {},
    }
    result.update(score_answer(answer, row['answer']))
    result['evidence_hit'] = evidence_hit(context, row['gold_titles'])
    return result


def aggregate(rows: list[dict]) -> dict:
    def mean(values):
        return sum(values) / len(values) if values else 0.0

    latencies = [row['elapsed_s'] for row in rows]
    return {
        'n': len(rows),
        'em': mean([row['em'] for row in rows]),
        'em_normalized': mean([row.get('em_normalized', row['em']) for row in rows]),
        'f1': mean([row['f1'] for row in rows]),
        'contains': mean([row['contains'] for row in rows]),
        'evidence_hit': mean([row['evidence_hit'] for row in rows]),
        'avg_latency_s': mean(latencies),
        'p95_latency_s': (statistics.quantiles(latencies, n=20)[-1]
                          if len(latencies) > 1 else (latencies[0] if latencies else 0)),
        'avg_retrieval_items': mean([row['retrieval_items'] for row in rows]),
        'errors': sum(1 for row in rows if row.get('error')),
    }


def render_report(out_dir: Path, rows: list[dict], config: dict) -> None:
    overall = aggregate(rows)
    by_type = {}
    for type_name in sorted({row['type'] for row in rows}):
        by_type[type_name] = aggregate([row for row in rows if row['type'] == type_name])
    lines = [
        '# 2WikiMultiHopQA 端到端问答指标', '',
        f"> 报告时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　|　"
        f"workflow：`{config['workflow_id']}`　|　n={overall['n']}", '',
        '## 1. 结论摘要', '',
        f"- EM **{overall['em']:.2%}**，规范化 EM **{overall['em_normalized']:.2%}**，"
        f"F1 **{overall['f1']:.2%}**，"
        f"答案被预测覆盖 **{overall['contains']:.2%}**，"
        f"gold 证据片段召回 **{overall['evidence_hit']:.2%}**。",
        f"- 端到端平均 **{overall['avg_latency_s']:.2f}s**，P95 "
        f"**{overall['p95_latency_s']:.2f}s**；平均检索片段 "
        f"**{overall['avg_retrieval_items']:.1f}** 条；错误 **{overall['errors']}** 题。", '',
        '## 2. 协议', '',
        '| 项 | 值 |', '|---|---|',
        "| 数据集 | 2WikiMultiHopQA dev（分层抽样） |",
        f"| 题量 | {overall['n']} |",
        f"| 文档库 | `{config.get('doc_kb_id')}` |",
        f"| 图谱库 | `{config.get('graph_kb_id')}` |",
        f"| 工作流 | `{config['workflow_id']}`（Blended_normal_graph，图谱 depth=3） |",
        f"| 重排 | `{config.get('rerank_model', DEFAULT_RERANK_MODEL)}`，top_n=5 |",
        '| 检索 | 图谱 + 向量 + 关键词混合 |',
        '| 生成 | 工作流默认生成模型 |',
        '| 评分 | 严格 EM / 规范化 EM / token F1；多个 gold 用 `|` 分隔取最佳 |', '',
        '## 3. 分题型', '',
        '| 题型 | n | EM | 规范化 EM | F1 | 覆盖 | 证据召回 | 平均延迟 | P95 |',
        '|---|---|---|---|---|---|---|---|---|',
    ]
    for type_name, values in by_type.items():
        lines.append(
            f"| {type_name} | {values['n']} | {values['em']:.2%} | "
            f"{values['em_normalized']:.2%} | "
            f"{values['f1']:.2%} | {values['contains']:.2%} | "
            f"{values['evidence_hit']:.2%} | {values['avg_latency_s']:.2f}s | "
            f"{values['p95_latency_s']:.2f}s |")
    lines += ['', '## 4. 总体', '',
               '| n | EM | 规范化 EM | F1 | 覆盖 | 证据召回 | 平均延迟 | P95 |',
               '|---|---|---|---|---|---|---|---|',
               f"| {overall['n']} | {overall['em']:.2%} | "
               f"{overall['em_normalized']:.2%} | {overall['f1']:.2%} | "
               f"{overall['contains']:.2%} | {overall['evidence_hit']:.2%} | "
               f"{overall['avg_latency_s']:.2f}s | {overall['p95_latency_s']:.2f}s |",
               '', '## 5. 复跑', '', '```bash',
               'python3 tools/graph-metrics/prepare_2wiki.py --per-type 25',
               'python3 tools/graph-metrics/import_2wiki.py --resume',
               'python3 tools/graph-metrics/run_2wiki_e2e.py --workers 4',
               '```']
    (out_dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--rerank-model', default=DEFAULT_RERANK_MODEL)
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args()

    state = json.loads(args.state.read_text(encoding='utf-8'))
    workflow_id = state['workflow_id']
    questions = load_questions(args.data_dir, args.limit)
    args.out.mkdir(parents=True, exist_ok=True)
    results_path = args.out / 'results.jsonl'

    done = set()
    if args.no_resume:
        results_path.write_text('', encoding='utf-8')
    elif results_path.exists():
        for line in results_path.open(encoding='utf-8'):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('qid'):
                done.add(row['qid'])
    todo = [row for row in questions if row['qid'] not in done]
    print(f'questions={len(questions)} done={len(done)} todo={len(todo)}')
    client = RkbClient(args.base_url)
    client.health()
    lock = threading.Lock()

    with results_path.open('a', encoding='utf-8') as sink:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(query_one, client, workflow_id, row): row
                       for row in todo}
            for completed, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    result = future.result()
                except Exception as error:                          # noqa: BLE001
                    result = {
                        **{key: row[key] for key in
                           ('qid', 'type', 'question', 'answer', 'gold_titles',
                            'context_titles')},
                        'prediction': '', 'elapsed_s': 0.0,
                        'retrieval_items': 0, 'graph_items': 0, 'timings': {},
                        'em': 0.0, 'em_normalized': 0.0, 'f1': 0.0, 'contains': 0.0,
                        'evidence_hit': 0.0, 'error': str(error)[:500],
                    }
                with lock:
                    sink.write(json.dumps(result, ensure_ascii=False) + '\n')
                    sink.flush()
                if completed % 10 == 0 or completed == len(todo):
                    print(f'e2e {completed}/{len(todo)} '
                          f'last_f1={result["f1"]:.2f} err={result.get("error", "")[:80]}')

    rows = []
    for line in results_path.open(encoding='utf-8'):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('qid'):
            rows.append(row)
    render_report(args.out, rows, {
        'workflow_id': workflow_id,
        'doc_kb_id': state.get('doc_kb_id'),
        'graph_kb_id': state.get('graph_kb_id'),
        'rerank_model': args.rerank_model,
    })
    summary = aggregate(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'wrote {args.out / "report.md"}')


if __name__ == '__main__':
    main()
