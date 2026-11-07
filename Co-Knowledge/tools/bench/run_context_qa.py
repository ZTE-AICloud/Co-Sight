#!/usr/bin/env python3
"""上下文注入式端到端评测（RGB / RAGBench / CRAG）。

这些基准的标准协议是「给定问题 + 文档，直接生成答案」，检索不是变量。
本工具用**产品部署的生成模型**（网关直连）复现协议，并用独立 judge 交叉核对；
它与走产品 ``/query`` 的 ``run_e2e.py`` 分开报告，避免把「生成鲁棒性」误写成
「产品检索链路的端到端能力」。

用法::

    python3 tools/bench/run_context_qa.py --mode rgb-noise --noise-rate 0.4
    python3 tools/bench/run_context_qa.py --mode rgb-int
    python3 tools/bench/run_context_qa.py --mode rgb-fact
    python3 tools/bench/run_context_qa.py --mode ragbench --limit-per-domain 100
    python3 tools/bench/run_context_qa.py --mode crag --limit 300
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Sequence

from common import (RUNS_DIR, GatewayJudge, is_refusal, load_manifest, mean_ci,
                    read_jsonl, sample_rows, write_json)

RGB_SYSTEM_ZH = (
    '你是一个准确和可靠的人工智能助手，能够借助外部文档回答问题，请注意外部文档可能存在噪声事实性错误。'
    '如果文档中的信息包含了正确答案，你将进行准确的回答。如果文档中的信息不包含答案，'
    '你将生成“文档信息不足，因此我无法基于提供的文档回答该问题。”。'
    '如果部分文档中存在与事实不一致的错误，请先生成“提供文档的文档存在事实性错误。”，并生成正确答案。'
)
RGB_INSTRUCTION_ZH = '文档：\n{DOCS} \n\n问题：\n{QUERY}'
RAGBENCH_PROMPT = (
    'Answer the question using only the provided documents. Be concise, do not '
    'invent facts, and state when the documents are insufficient.\n\n'
    'Documents:\n{DOCS}\n\nQuestion: {QUERY}\nAnswer:'
)
CRAG_PROMPT = (
    'You are provided with a question and various references. Your task is to '
    'answer the question succinctly, using the fewest words possible. If the '
    'references do not contain the necessary information to answer the '
    'question, respond with "I don\'t know". There is no need to explain the '
    'reasoning behind your answers.\n\n'
    'Question: {QUERY}\nReferences:\n{DOCS}\nAnswer:'
)


def _shuffle(seed: int, docs: List[str]) -> List[str]:
    rng = random.Random(seed)
    shuffled = list(docs)
    rng.shuffle(shuffled)
    return shuffled


def build_rgb_docs(row: Dict[str, Any], noise_rate: float, passage_num: int = 5,
                   correct_rate: float = 0.0) -> List[str]:
    """严格复刻 RGB ``evalue.py::processdata`` 的口径。"""
    rng = random.Random(2333)
    if row.get('type') == 'integration':
        groups = [list(group) for group in row.get('positive') or []]
        for group in groups:
            rng.shuffle(group)
        docs = [group[0] for group in groups if group]
        max_num = max((len(group) for group in groups), default=0)
        for index in range(1, max_num):
            for group in groups:
                if len(group) > index and len(docs) < passage_num:
                    docs.append(group[index])
            if len(docs) >= passage_num:
                break
        neg_num = max(0, passage_num - len(docs))
        docs += list(row.get('negative') or [])[:neg_num]
    elif row.get('type') == 'counterfactual':
        neg_num = math.ceil(passage_num * noise_rate)
        correct_num = math.ceil(passage_num * correct_rate)
        pos_num = passage_num - neg_num - correct_num
        indices = list(range(len(row.get('positive') or [])))
        selected = rng.sample(indices, min(len(indices), max(pos_num, 0)))
        docs = [row['positive_wrong'][i] for i in selected
                if i < len(row.get('positive_wrong') or [])]
        remain = [i for i in indices if i not in selected]
        if correct_num > 0 and remain:
            docs += [row['positive'][i] for i in
                     rng.sample(remain, min(len(remain), correct_num))]
        docs += list(row.get('negative') or [])[:neg_num]
    else:
        neg_num = math.ceil(passage_num * noise_rate)
        pos_num = passage_num - neg_num
        if noise_rate == 1:
            neg_num, pos_num = passage_num, 0
        else:
            if neg_num > len(row.get('negative') or []):
                neg_num = len(row.get('negative') or [])
                pos_num = passage_num - neg_num
            elif pos_num > len(row.get('positive') or []):
                pos_num = len(row.get('positive') or [])
                neg_num = passage_num - pos_num
        docs = list(row.get('positive') or [])[:pos_num]
        docs += list(row.get('negative') or [])[:neg_num]
    return _shuffle(2333, docs)


def rgb_checkanswer(prediction: str, ground_truth: Any) -> List[int]:
    prediction = (prediction or '').lower()
    if not isinstance(ground_truth, list):
        ground_truth = [ground_truth]
    labels: List[int] = []
    for instance in ground_truth:
        flag = True
        if isinstance(instance, list):
            flag = False
            lowered = [str(i).lower() for i in instance]
            if any(item and item in prediction for item in lowered):
                flag = True
        else:
            if str(instance).lower() not in prediction:
                flag = False
        labels.append(int(flag))
    return labels


def _generate(client: GatewayJudge, system: str, instruction: str,
              question: str, docs: Sequence[str], model: str = '') -> str:
    content = instruction.replace('{DOCS}', '\n'.join(docs)).replace('{QUERY}', question)
    prompt = system + '\n\n' + content if system else content
    return client.chat(prompt, max_tokens=512, temperature=0.01)


def _run_rows(rows: Sequence[Dict[str, Any]], work, workers: int,
              out_path: Path, resume: bool) -> List[Dict[str, Any]]:
    done: Dict[str, Dict[str, Any]] = {}
    if out_path.exists() and resume:
        for row in read_jsonl(out_path):
            done[str(row['qid'])] = row
    elif out_path.exists():
        out_path.unlink()
    todo = [row for row in rows if str(row['qid']) not in done]
    print(f'rows={len(rows)} todo={len(todo)} workers={workers}', flush=True)
    lock = threading.Lock()
    with out_path.open('a', encoding='utf-8') as handle:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, row): row for row in todo}
            for index, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {'qid': str(row['qid']), 'type': row.get('type'),
                              'error': str(exc)[:300], 'prediction': ''}
                with lock:
                    handle.write(json.dumps(result, ensure_ascii=False) + '\n')
                    handle.flush()
                if index % 20 == 0:
                    print(f'  {index}/{len(todo)}', flush=True)
    merged = dict(done)
    for row in read_jsonl(out_path):
        merged[str(row['qid'])] = row
    return list(merged.values())


def mode_rgb(args: argparse.Namespace) -> None:
    dataset = {'noise': 'rgb-noise', 'int': 'rgb-int', 'fact': 'rgb-fact'}[args.mode.split('-')[1]]
    _, queries, _ = load_manifest(dataset)
    if args.limit:
        queries = sample_rows(queries, args.limit, key='qid')
    judge = GatewayJudge(model=args.judge_model)
    generator = GatewayJudge(model=args.model)
    out_dir = RUNS_DIR / dataset / f'{args.mode}-noise{args.noise_rate}'
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(row: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        docs = build_rgb_docs(row, args.noise_rate, args.passage_num, args.correct_rate)
        prediction = _generate(client=generator, system=RGB_SYSTEM_ZH,
                               instruction=RGB_INSTRUCTION_ZH,
                               question=str(row['question']), docs=docs,
                               model=args.model)
        labels = rgb_checkanswer(prediction, row.get('answers') or [])
        result = {
            'qid': str(row['qid']),
            'type': row.get('type'),
            'question': str(row['question']),
            'noise_rate': args.noise_rate,
            'docs': len(docs),
            'prediction': prediction,
            'labels': labels,
            'elapsed_s': time.perf_counter() - started,
        }
        if row.get('type') == 'counterfactual':
            result['factlabel'] = 1 if ('事实性错误' in prediction
                                        or 'factual errors' in prediction.lower()) else 0
        if args.judge:
            gold = row.get('answers') or []
            judged = judge.judge_correct(str(row['question']), gold, prediction)
            result['judge_correct'] = judged['correct']
            result['judge_reason'] = judged['reason']
        return result

    rows = _run_rows(queries, work, args.workers, out_dir / 'results.jsonl', not args.no_resume)
    if args.mode == 'rgb-noise':
        labels = [row.get('labels') or [] for row in rows]
        if args.noise_rate >= 1:
            rate = sum(1 for label in labels
                       if label and label[0] == -1) / max(len(rows), 1)
            metric = {'rejection_rate': rate}
        else:
            ok = sum(1 for label in labels
                     if label and 0 not in label and 1 in label)
            metric = {'accuracy': ok / max(len(rows), 1)}
    elif args.mode == 'rgb-int':
        ok = sum(1 for row in rows
                 if row.get('labels') and 0 not in row['labels'] and 1 in row['labels'])
        metric = {'accuracy': ok / max(len(rows), 1)}
    else:
        fact_rows = [row for row in rows if row.get('factlabel') == 1]
        correct_rows = [row for row in fact_rows
                        if row.get('labels') and 0 not in row['labels']]
        metric = {
            'fact_check_rate': len(fact_rows) / max(len(rows), 1),
            'correction_rate': len(correct_rows) / max(len(fact_rows), 1),
            'answer_accuracy': sum(1 for row in rows
                                   if row.get('labels') and 0 not in row['labels'])
                              / max(len(rows), 1),
        }
    summary = {
        'config': {'mode': args.mode, 'model': args.model, 'noise_rate': args.noise_rate,
                   'passage_num': args.passage_num, 'correct_rate': args.correct_rate,
                   'judge_model': args.judge_model if args.judge else None},
        'metrics': metric,
        'n': len(rows),
    }
    write_json(out_dir / 'results.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def mode_ragbench(args: argparse.Namespace) -> None:
    _, queries, _ = load_manifest('ragbench')
    if args.limit_per_domain:
        queries = _per_type_limit(queries, args.limit_per_domain)
    generator = GatewayJudge(model=args.model)
    judge = GatewayJudge(model=args.judge_model)
    out_dir = RUNS_DIR / 'ragbench' / args.model
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(row: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        docs = [str(ctx.get('text') or '') for ctx in row.get('contexts') or []]
        prediction = _generate(client=generator, system='', instruction=RAGBENCH_PROMPT,
                               question=str(row['question']), docs=docs, model=args.model)
        # 一次 judge 调用返回四个指标：MiniMax 单次 7–16 s，5 次拆开会把
        # 250 题放大到 1,250 次调用，实测是整轮评测的瓶颈。
        # 一次调用、四行 YES/NO。JSON 四指标实测会被模型抄成同一个值；
        # 行式输出更容易逐项解析，也避免 5 次/题的网关放大。
        prompt = (
            f'Question: {row["question"]}\n'
            'Documents:\n' + '\n'.join(docs)[:12000] + '\n'
            f'Answer: {prediction}\n\n'
            'Grade each axis with exactly YES or NO, one per line:\n'
            'correct: is the answer factually correct for the question?\n'
            'adherence: is every claim supported by the documents?\n'
            'utilization: does it use the documents rather than outside knowledge?\n'
            'completeness: does it cover the key information needed to answer?\n'
            'Format:\ncorrect: YES\nadherence: NO\nutilization: YES\ncompleteness: YES'
        )
        text = judge.chat(prompt, max_tokens=64)
        scores = {}
        for name in ('correct', 'adherence', 'utilization', 'completeness'):
            match = re.search(rf'\b{name}\s*:\s*(YES|NO)\b', text, re.I)
            scores[name] = 1 if match and match.group(1).upper() == 'YES' else 0
        return {
            'qid': str(row['qid']), 'type': row.get('type'),
            'question': str(row['question']), 'prediction': prediction,
            'reference_response': row.get('reference_response'),
            'scores': scores, 'elapsed_s': time.perf_counter() - started,
        }

    rows = _run_rows(queries, work, args.workers, out_dir / 'results.jsonl', not args.no_resume)
    metric_keys = ('correct', 'adherence', 'utilization', 'completeness')
    by_type = {}
    for type_name in sorted({str(row.get('type') or '') for row in rows}):
        subset = [row for row in rows if str(row.get('type') or '') == type_name
                  and row.get('scores')]
        by_type[type_name] = {key: mean_ci([row['scores'][key] for row in subset])
                              for key in metric_keys}
        by_type[type_name]['n'] = len(subset)
    summary = {
        'config': {'mode': 'ragbench', 'model': args.model, 'judge_model': args.judge_model},
        'n': len(rows),
        'by_type': by_type,
        'overall': {key: mean_ci([row['scores'][key] for row in rows if row.get('scores')])
                    for key in metric_keys},
    }
    write_json(out_dir / 'results.json', summary)
    print(json.dumps(summary['overall'], ensure_ascii=False, indent=2))


def mode_crag(args: argparse.Namespace) -> None:
    _, queries, _ = load_manifest('crag')
    if args.limit:
        queries = sample_rows(queries, args.limit, key='qid')
    generator = GatewayJudge(model=args.model)
    judge = GatewayJudge(model=args.judge_model)
    out_dir = RUNS_DIR / 'crag' / args.model
    out_dir.mkdir(parents=True, exist_ok=True)

    def work(row: Dict[str, Any]) -> Dict[str, Any]:
        started = time.perf_counter()
        docs = [str(ctx.get('text') or '') for ctx in row.get('contexts') or []]
        prediction = _generate(client=generator, system='', instruction=CRAG_PROMPT,
                               question=str(row['question']), docs=docs, model=args.model)
        judged = judge.judge_correct(str(row['question']), row.get('answers') or [], prediction)
        return {
            'qid': str(row['qid']), 'type': row.get('type'),
            'question': str(row['question']), 'prediction': prediction,
            'answers': row.get('answers') or [],
            'judge_correct': judged['correct'], 'judge_reason': judged['reason'],
            'refusal': is_refusal(prediction),
            'meta': row.get('meta') or {},
            'elapsed_s': time.perf_counter() - started,
        }

    rows = _run_rows(queries, work, args.workers, out_dir / 'results.jsonl', not args.no_resume)
    by_type = {}
    for type_name in sorted({str(row.get('type') or '') for row in rows}):
        subset = [row for row in rows if str(row.get('type') or '') == type_name]
        by_type[type_name] = {
            'n': len(subset),
            'accuracy': mean_ci([row.get('judge_correct') for row in subset
                                 if row.get('judge_correct') is not None]),
            'refusal_rate': sum(1 for row in subset if row.get('refusal')) / max(len(subset), 1),
        }
    summary = {
        'config': {'mode': 'crag', 'model': args.model, 'judge_model': args.judge_model},
        'n': len(rows),
        'overall': {
            'accuracy': mean_ci([row.get('judge_correct') for row in rows
                                 if row.get('judge_correct') is not None]),
            'refusal_rate': sum(1 for row in rows if row.get('refusal')) / max(len(rows), 1),
            'error_rate': sum(1 for row in rows if row.get('error')) / max(len(rows), 1),
        },
        'by_type': by_type,
    }
    write_json(out_dir / 'results.json', summary)
    print(json.dumps(summary['overall'], ensure_ascii=False, indent=2))


def _per_type_limit(rows: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get('type') or ''), []).append(row)
    out: List[Dict[str, Any]] = []
    for type_name in sorted(buckets):
        out.extend(sample_rows(buckets[type_name], limit, key='qid'))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True,
                        choices=('rgb-noise', 'rgb-int', 'rgb-fact', 'ragbench', 'crag'))
    parser.add_argument('--model', default='deepseek-chat')
    parser.add_argument('--judge-model', default='deepseek-chat.1-Flash')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--noise-rate', type=float, default=0.0)
    parser.add_argument('--passage-num', type=int, default=5)
    parser.add_argument('--correct-rate', type=float, default=0.0)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--limit-per-domain', type=int, default=None)
    parser.add_argument('--judge', action='store_true')
    parser.add_argument('--no-resume', action='store_true')
    args = parser.parse_args()
    if args.mode.startswith('rgb'):
        mode_rgb(args)
    elif args.mode == 'ragbench':
        mode_ragbench(args)
    else:
        mode_crag(args)


if __name__ == '__main__':
    main()
