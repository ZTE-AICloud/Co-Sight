#!/usr/bin/env python3
"""把 11 个公开基准转成统一的 JSONL 清单。

用法::

    python3 tools/bench/prepare.py beir scifact
    python3 tools/bench/prepare.py beir-sampled msmarco --queries 2000 --negatives 28000
    python3 tools/bench/prepare.py hotpotqa --questions 2000
    python3 tools/bench/prepare.py musique --questions 1000
    python3 tools/bench/prepare.py 2wiki --per-type 75
    python3 tools/bench/prepare.py crag --questions 300
    python3 tools/bench/prepare.py rgb
    python3 tools/bench/prepare.py ragbench --per-domain 150
    python3 tools/bench/prepare.py crud --per-task 200

产物在 ``.metrics-data/bench/<name>/``：``corpus.jsonl``（pid/title/text）、
``queries.jsonl``（qid/question/answers/gold_pids/gold_titles/contexts/meta）、
``stats.json``。数据只落在 gitignore 目录，不随报告分发。
"""

from __future__ import annotations

import argparse
import bz2
import html
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from common import (RAW_DIR, REPO_ROOT, dataset_dir, hash_fraction,
                    read_jsonl, sample_rows, stable_hash, write_json, write_jsonl)

HF_CACHE = REPO_ROOT / 'eval-data' / 'hf-cache'
os.environ.setdefault('HF_HOME', str(HF_CACHE))
os.environ.setdefault('HF_DATASETS_CACHE', str(HF_CACHE / 'datasets'))

BEIR_SMALL = ('scifact', 'nfcorpus', 'arguana', 'fiqa', 'scidocs')
BEIR_LARGE = ('msmarco', 'nq')
RAGBENCH_DOMAINS = ('covidqa', 'emanual', 'finqa', 'hotpotqa', 'msmarco')


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _corpus_stats(corpus: Sequence[Dict[str, Any]],
                  queries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    golds = [len(q.get('gold_pids') or []) for q in queries if q.get('gold_pids')]
    lengths = [len(str(p.get('text') or '')) for p in corpus]
    return {
        'corpus_passages': len(corpus),
        'queries': len(queries),
        'queries_with_gold': len(golds),
        'qrels_pairs': sum(golds),
        'gold_per_query': {
            'min': min(golds) if golds else 0,
            'median': _median(golds),
            'max': max(golds) if golds else 0,
        },
        'passage_chars': {
            'median': _median(lengths),
            'p90': float(sorted(lengths)[int(len(lengths) * 0.9)]) if lengths else 0,
            'p99': float(sorted(lengths)[int(len(lengths) * 0.99)]) if lengths else 0,
        },
    }


def _write_dataset(name: str, corpus: Sequence[Dict[str, Any]],
                   queries: Sequence[Dict[str, Any]],
                   extra: Optional[Dict[str, Any]] = None) -> None:
    out = _ensure_dir(dataset_dir(name))
    write_jsonl(out / 'corpus.jsonl', corpus)
    write_jsonl(out / 'queries.jsonl', queries)
    stats = _corpus_stats(corpus, queries)
    if extra:
        stats.update(extra)
    write_json(out / 'stats.json', stats)
    print(json.dumps({'dataset': name, **stats}, ensure_ascii=False))


def _download(url: str, path: Path, timeout: int = 300) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return path
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    tmp = path.with_suffix(path.suffix + '.part')
    with tmp.open('wb') as handle:
        for chunk in response.iter_content(chunk_size=1 << 20):
            if chunk:
                handle.write(chunk)
    tmp.replace(path)
    return path


def _load_beir_qrels(name: str) -> Dict[str, Dict[str, float]]:
    qrels: Dict[str, Dict[str, float]] = {}
    last_error: Optional[Exception] = None
    # MS MARCO 的 test.tsv 只有 43 条 TREC-DL 查询（0~3 分级）；官方 dev
    # 是 6,980 条、二值相关，必须优先 dev.tsv。
    splits = ('dev.tsv', 'test.tsv') if name == 'msmarco' else ('test.tsv', 'dev.tsv')
    for split in splits:
        url = f'https://huggingface.co/datasets/BeIR/{name}-qrels/resolve/main/{split}'
        try:
            response = requests.get(url, timeout=120)
            if response.status_code != 200 or len(response.text) < 10:
                raise RuntimeError(f'HTTP {response.status_code}')
            for line in response.text.splitlines():
                parts = line.strip().split('\t')
                if len(parts) < 3 or parts[0] in ('query-id', 'qid'):
                    continue
                qid, pid, score = parts[0], parts[1], parts[2]
                if float(score) <= 0:
                    continue
                qrels.setdefault(qid, {})[pid] = float(score)
            if qrels:
                return qrels
        except Exception as error:  # noqa: BLE001
            last_error = error
    raise RuntimeError(f'no qrels for {name}: {last_error}')


def _load_beir_split(name: str, config: str) -> Any:
    from datasets import load_dataset
    return load_dataset(f'BeIR/{name}', config, split=config,
                        cache_dir=str(HF_CACHE))


def _beir_rows(name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]],
                                   Dict[str, Dict[str, float]]]:
    corpus_ds = _load_beir_split(name, 'corpus')
    queries_ds = _load_beir_split(name, 'queries')
    corpus = [{'pid': str(row['_id']), 'title': str(row.get('title') or ''),
               'text': str(row.get('text') or '')} for row in corpus_ds]
    queries = [{'qid': str(row['_id']), 'question': str(row.get('text') or '')}
               for row in queries_ds]
    return corpus, queries, _load_beir_qrels(name)


def cmd_beir(args: argparse.Namespace) -> None:
    corpus, queries, qrels = _beir_rows(args.name)
    for query in queries:
        query['gold_pids'] = sorted(qrels.get(query['qid'], {}))
        query['gold_scores'] = dict(qrels.get(query['qid'], {}))
        query['answers'] = []
    queries = [q for q in queries if q['gold_pids']]
    mode = 'full'
    if args.corpus_limit and len(corpus) > args.corpus_limit:
        gold_pids = {pid for q in queries for pid in q['gold_pids']}
        keep = [row for row in corpus if row['pid'] in gold_pids]
        rest = [row for row in corpus if row['pid'] not in gold_pids]
        budget = max(0, args.corpus_limit - len(keep))
        sampled = sorted(rest, key=lambda row: stable_hash(f'42:{row["pid"]}'))[:budget]
        corpus = keep + sampled
        mode = 'sampled'
    _write_dataset(f'beir-{args.name}', corpus, queries,
                   {'benchmark': 'BEIR', 'task': args.name, 'split': 'test',
                    'corpus_mode': mode,
                    'corpus_limit': args.corpus_limit})


def _beir_queries_and_qrels(name: str,
                            limit: int) -> Tuple[List[Dict[str, Any]],
                                                 Dict[str, Dict[str, float]],
                                                 set[str]]:
    """只加载 queries split + qrels；**不要**为抽样加载全量 corpus（8.8M/2.68M 行）。"""
    queries_ds = _load_beir_split(name, 'queries')
    queries = [{'qid': str(row['_id']), 'question': str(row.get('text') or '')}
               for row in queries_ds]
    qrels = _load_beir_qrels(name)
    by_qid = {q['qid']: q for q in queries}
    eligible = [qid for qid in qrels if qid in by_qid and qrels[qid]]
    picked = sorted(eligible, key=lambda qid: stable_hash(f'42:{qid}'))[:limit]
    gold: set[str] = set()
    out: List[Dict[str, Any]] = []
    for qid in picked:
        gold.update(qrels[qid])
        out.append({'qid': qid, 'question': by_qid[qid]['question'],
                    'answers': [], 'gold_pids': sorted(qrels[qid]),
                    'gold_scores': dict(qrels[qid])})
    return out, {qid: qrels[qid] for qid in picked}, gold


def cmd_beir_sampled(args: argparse.Namespace) -> None:
    """大语料（MS MARCO / NQ）：gold + 哈希抽样的干扰 passage。"""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download, list_repo_files

    queries, qrels, gold = _beir_queries_and_qrels(args.name, args.queries)
    repo = f'BeIR/{args.name}'
    files = sorted(name for name in list_repo_files(repo, repo_type='dataset')
                   if name.startswith('corpus/') and name.endswith('.parquet'))
    if not files:
        raise SystemExit(f'{repo} 没有 corpus parquet')
    handles = [pq.ParquetFile(hf_hub_download(
        repo_id=repo, repo_type='dataset', filename=name,
        cache_dir=str(HF_CACHE))) for name in files]
    total = sum(handle.metadata.num_rows for handle in handles)
    threshold = min(1.0, (args.negatives / max(total, 1)) * 1.15)
    corpus: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add_row(row: Dict[str, Any]) -> None:
        pid = str(row.get('_id'))
        if pid in seen:
            return
        seen.add(pid)
        corpus.append({'pid': pid, 'title': str(row.get('title') or ''),
                       'text': str(row.get('text') or '')})

    for handle in handles:
        for batch in handle.iter_batches(batch_size=100_000,
                                         columns=['_id', 'title', 'text']):
            for row in batch.to_pylist():
                pid = str(row.get('_id'))
                if pid in gold or hash_fraction(pid) < threshold:
                    add_row(row)
            print(f'  scanned -> corpus={len(corpus)}', flush=True)
    missing = gold - seen
    if missing:
        raise SystemExit(f'{len(missing)} gold pids missing from corpus')
    _write_dataset(f'beir-{args.name}-{args.queries}q-{args.negatives}n', corpus,
                   queries,
                   {'benchmark': 'BEIR', 'task': args.name, 'split': 'test',
                    'corpus_mode': 'sampled',
                    'source_corpus_size': total,
                    'sampling': {'queries': args.queries, 'negatives': args.negatives,
                                 'threshold': threshold}})


def cmd_hotpotqa(args: argparse.Namespace) -> None:
    from datasets import load_dataset
    ds = load_dataset('hotpotqa/hotpot_qa', 'distractor', split='validation',
                      cache_dir=str(HF_CACHE))
    total = len(ds)
    threshold = min(1.0, args.questions / max(total, 1))
    corpus_by_pid: Dict[str, Dict[str, Any]] = {}
    queries: List[Dict[str, Any]] = []
    for index, row in enumerate(ds):
        if hash_fraction(str(row['id'])) >= threshold:
            continue
        context = row['context']
        titles = list(context['title'])
        sentences = list(context['sentences'])
        title_to_pid: Dict[str, str] = {}
        for title, sentence_list in zip(titles, sentences):
            text = ' '.join(str(s).strip() for s in sentence_list if str(s).strip())
            pid = 'hp_' + stable_hash(title)[:16]
            title_to_pid[title] = pid
            corpus_by_pid.setdefault(pid, {'pid': pid, 'title': str(title),
                                           'text': text})
        supporting = {str(title) for title in row['supporting_facts']['title']}
        gold_titles = sorted(supporting)
        queries.append({
            'qid': str(row['id']),
            'question': str(row['question']),
            'answers': [str(row['answer'])],
            'gold_pids': [title_to_pid[t] for t in gold_titles if t in title_to_pid],
            'gold_titles': gold_titles,
            'context_pids': sorted(set(title_to_pid.values())),
            'type': str(row.get('type') or ''),
            'meta': {'level': row.get('level')},
        })
        if index % 2000 == 0:
            print(f'  scanned {index}/{total}', flush=True)
    corpus = list(corpus_by_pid.values())
    _write_dataset('hotpotqa', corpus, queries,
                   {'benchmark': 'HotpotQA', 'split': 'validation',
                    'corpus_mode': 'distractor-union',
                    'source_questions': total, 'sampling_rate': threshold})


def cmd_musique(args: argparse.Namespace) -> None:
    rows = read_jsonl(RAW_DIR / 'musique_dev.jsonl')
    rows = sample_rows(rows, args.questions, key='id')
    corpus_by_pid: Dict[str, Dict[str, Any]] = {}
    queries: List[Dict[str, Any]] = []
    for row in rows:
        gold_titles: List[str] = []
        gold_pids: List[str] = []
        context_pids: List[str] = []
        for paragraph in row.get('paragraphs') or []:
            title = str(paragraph.get('title') or '')
            text = str(paragraph.get('paragraph_text') or '')
            pid = 'mq_' + stable_hash(f'{title}\n{text}')[:16]
            corpus_by_pid.setdefault(pid, {'pid': pid, 'title': title, 'text': text})
            context_pids.append(pid)
            if paragraph.get('is_supporting'):
                gold_pids.append(pid)
                if title not in gold_titles:
                    gold_titles.append(title)
        answers = [str(row.get('answer') or '')]
        answers.extend(str(item) for item in row.get('answer_aliases') or [])
        queries.append({
            'qid': str(row['id']),
            'question': str(row['question']),
            'answers': [a for a in answers if a],
            'gold_pids': gold_pids,
            'gold_titles': gold_titles,
            'context_pids': sorted(set(context_pids)),
            'type': str(row['id']).split('__')[0],
        })
    _write_dataset('musique', list(corpus_by_pid.values()), queries,
                   {'benchmark': 'MuSiQue', 'split': 'dev-answerable',
                    'corpus_mode': 'distractor-union'})


def cmd_2wiki(args: argparse.Namespace) -> None:
    raw = REPO_ROOT / '.metrics-data' / '2wiki' / 'raw' / 'dev_voidful.json'
    rows = json.loads(raw.read_text(encoding='utf-8'))
    types = ('bridge_comparison', 'comparison', 'compositional', 'inference')
    by_type: Dict[str, List[Dict[str, Any]]] = {t: [] for t in types}
    for row in rows:
        if row.get('answer') and row.get('type') in by_type:
            by_type[str(row['type'])].append(row)
    picked: List[Dict[str, Any]] = []
    for type_name in types:
        pool = sorted(by_type[type_name], key=lambda r: stable_hash(str(r['_id'])))
        picked.extend(pool[:args.per_type])
    corpus_by_pid: Dict[str, Dict[str, Any]] = {}
    queries: List[Dict[str, Any]] = []
    for row in picked:
        title_to_pid: Dict[str, str] = {}
        for title, sentences in row.get('context') or []:
            title = str(title).strip()
            text = ' '.join(str(s).strip() for s in sentences or [] if str(s).strip())
            pid = 'w2_' + stable_hash(title)[:16]
            title_to_pid[title] = pid
            # 同一标题在不同题里可能是不同片段；取正文更长的那份，
            # 否则 300 题并集里先出现的短版本会把答案截掉。
            previous = corpus_by_pid.get(pid)
            if previous is None or len(text) > len(previous['text']):
                corpus_by_pid[pid] = {'pid': pid, 'title': title, 'text': text}
        supporting = row.get('supporting_facts') or []
        if isinstance(supporting, dict):
            titles = supporting.get('title') or []
        else:
            titles = [item[0] for item in supporting if item]
        gold_titles = sorted({str(t) for t in titles})
        queries.append({
            'qid': str(row['_id']),
            'question': str(row['question']),
            'answers': [str(row['answer'])],
            'gold_pids': [title_to_pid[t] for t in gold_titles if t in title_to_pid],
            'gold_titles': gold_titles,
            'context_pids': sorted(set(title_to_pid.values())),
            'type': str(row['type']),
        })
    _write_dataset('2wiki', list(corpus_by_pid.values()), queries,
                   {'benchmark': '2WikiMultiHopQA', 'split': 'dev',
                    'corpus_mode': 'distractor-union',
                    'per_type': args.per_type})


HTML_TAG_RE = re.compile(r'<[^>]+>')
SPACE_RE = re.compile(r'\s+')


def _html_to_text(raw: str, limit: int = 8000) -> str:
    text = HTML_TAG_RE.sub(' ', raw or '')
    text = html.unescape(text)
    text = SPACE_RE.sub(' ', text).strip()
    return text[:limit]


def cmd_crag(args: argparse.Namespace) -> None:
    path = RAW_DIR / 'crag_task_1_and_2_dev_v4.jsonl.bz2'
    _download('https://github.com/facebookresearch/CRAG/raw/refs/heads/main/'
              'data/crag_task_1_and_2_dev_v4.jsonl.bz2', path, timeout=600)
    chosen: List[Dict[str, Any]] = []
    with bz2.open(path, 'rt', encoding='utf-8') as handle:
        total = sum(1 for line in handle if line.strip())
    threshold = min(1.0, args.questions / max(total, 1) * 1.1)
    print(f'crag rows={total} threshold={threshold:.4f}', flush=True)
    with bz2.open(path, 'rt', encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if hash_fraction(str(row['interaction_id'])) < threshold:
                chosen.append(row)
                if len(chosen) >= args.questions:
                    break
    queries: List[Dict[str, Any]] = []
    for row in chosen:
        contexts = []
        for result in (row.get('search_results') or [])[:5]:
            snippet = str(result.get('page_snippet') or '').strip()
            body = _html_to_text(str(result.get('page_result') or ''))
            contexts.append({
                'title': str(result.get('page_name') or ''),
                'text': (snippet + '\n' + body).strip() if snippet else body,
                'url': str(result.get('page_url') or ''),
            })
        queries.append({
            'qid': str(row['interaction_id']),
            'question': str(row['query']),
            'answers': [str(row.get('answer') or '')]
                       + ([str(row['alternative_answers'])]
                          if row.get('alternative_answers') else []),
            'contexts': contexts,
            'type': str(row.get('question_type') or ''),
            'meta': {key: row.get(key) for key in
                     ('domain', 'static_or_dynamic', 'popularity', 'split')},
        })
    _write_dataset('crag', [], queries,
                   {'benchmark': 'CRAG', 'split': 'task1-2-dev',
                    'corpus_mode': 'provided-web-pages', 'sampled': len(queries)})


def _rgb_lines(path: Path) -> List[Dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def cmd_rgb(_: argparse.Namespace) -> None:
    noise = _rgb_lines(RAW_DIR / 'rgb_zh.json')
    refined = RAW_DIR / 'rgb_refine.json'
    if refined.exists():
        noise = _rgb_lines(refined)
    noise_queries = []
    for row in noise:
        noise_queries.append({
            'qid': str(row['id']),
            'question': str(row['query']),
            'answers': [str(a) for a in row.get('answer') or []],
            'positive': [str(x) for x in row.get('positive') or []],
            'negative': [str(x) for x in row.get('negative') or []],
            'type': 'noise',
        })
    integration = []
    for row in _rgb_lines(RAW_DIR / 'rgb_zh_int.json'):
        integration.append({
            'qid': str(row['id']),
            'question': str(row['query']),
            'answers': [str(a) for a in row.get('answer') or []],
            'positive': [[str(x) for x in group] for group in row.get('positive') or []],
            'negative': [str(x) for x in row.get('negative') or []],
            'type': 'integration',
        })
    factual = []
    for row in _rgb_lines(RAW_DIR / 'rgb_zh_fact.json'):
        factual.append({
            'qid': str(row['id']),
            'question': str(row['query']),
            'answers': [str(row.get('answer') or '')],
            'fake_answer': str(row.get('fakeanswer') or ''),
            'positive': [str(x) for x in row.get('positive') or []],
            'positive_wrong': [str(x) for x in row.get('positive_wrong') or []],
            'negative': [str(x) for x in row.get('negative') or []],
            'type': 'counterfactual',
        })
    _write_dataset('rgb-noise', [], noise_queries,
                   {'benchmark': 'RGB', 'subset': 'noise-robustness',
                    'language': 'zh', 'corpus_mode': 'provided-context'})
    _write_dataset('rgb-int', [], integration,
                   {'benchmark': 'RGB', 'subset': 'information-integration',
                    'language': 'zh', 'corpus_mode': 'provided-context'})
    _write_dataset('rgb-fact', [], factual,
                   {'benchmark': 'RGB', 'subset': 'counterfactual-robustness',
                    'language': 'zh', 'corpus_mode': 'provided-context'})


def cmd_ragbench(args: argparse.Namespace) -> None:
    from datasets import load_dataset
    queries: List[Dict[str, Any]] = []
    for domain in RAGBENCH_DOMAINS:
        ds = load_dataset('galileo-ai/ragbench', domain, split='test',
                          cache_dir=str(HF_CACHE))
        rows = sample_rows([dict(row) for row in ds], args.per_domain, key='id')
        for row in rows:
            queries.append({
                'qid': f'{domain}:{row["id"]}',
                'question': str(row['question']),
                'answers': [],
                'contexts': [{'title': f'{domain} doc {i}', 'text': str(doc)}
                             for i, doc in enumerate(row.get('documents') or [])],
                'reference_response': str(row.get('response') or ''),
                'type': domain,
                'meta': {
                    'adherence': bool(row.get('adherence_score')),
                    'relevance_score': row.get('relevance_score'),
                    'utilization_score': row.get('utilization_score'),
                    'completeness_score': row.get('completeness_score'),
                },
            })
    _write_dataset('ragbench', [], queries,
                   {'benchmark': 'RAGBench', 'split': 'test',
                    'corpus_mode': 'provided-context',
                    'domains': list(RAGBENCH_DOMAINS),
                    'per_domain': args.per_domain})


def cmd_crud(args: argparse.Namespace) -> None:
    data = json.loads((RAW_DIR / 'crud_split.json').read_text(encoding='utf-8'))
    corpus_by_pid: Dict[str, Dict[str, Any]] = {}
    queries: List[Dict[str, Any]] = []
    for task, docs_key in (('questanswer_1doc', ('news1',)),
                           ('questanswer_2docs', ('news1', 'news2')),
                           ('questanswer_3docs', ('news1', 'news2', 'news3'))):
        rows = sample_rows(data[task], args.per_task, key='ID')
        for row in rows:
            gold_pids = []
            for key in docs_key:
                text = str(row.get(key) or '')
                pid = f'cr_{task}_' + stable_hash(text)[:16]
                corpus_by_pid.setdefault(pid, {'pid': pid, 'title': str(row.get('event') or '')[:80],
                                               'text': text})
                gold_pids.append(pid)
            queries.append({
                'qid': f'{task}:{row["ID"]}',
                'question': str(row.get('questions') or ''),
                'answers': [str(row.get('answers') or '')],
                'gold_pids': gold_pids,
                'type': task,
            })
    hallu = sample_rows(data['hallu_modified'], args.per_task, key='ID')
    for row in hallu:
        reference = str(row.get('newsBeginning') or '') + str(row.get('newsRemainder') or '')
        pid = 'cr_hallu_' + stable_hash(reference)[:16]
        corpus_by_pid.setdefault(pid, {'pid': pid, 'title': str(row.get('headLine') or '')[:80],
                                       'text': reference})
        queries.append({
            'qid': f'hallu:{row["ID"]}',
            'question': ('下面这段续写是否包含与参考事实不一致的内容？如果包含，请指出并给出正确续写：\n'
                         + str(row.get('hallucinatedContinuation') or '')),
            'answers': [str(row.get('realContinuation') or '')],
            'gold_pids': [pid],
            'type': 'hallucination',
            'meta': {'keywords': row.get('allKeywords')},
        })
    summaries = sample_rows(data['event_summary'], args.per_task, key='ID')
    for row in summaries:
        text = str(row.get('text') or '')
        pid = 'cr_summary_' + stable_hash(text)[:16]
        corpus_by_pid.setdefault(pid, {'pid': pid, 'title': str(row.get('title') or '')[:80],
                                       'text': text})
        queries.append({
            'qid': f'summary:{row["ID"]}',
            'question': '请用一段话总结下面这条新闻：\n' + text,
            'answers': [str(row.get('summary') or '')],
            'gold_pids': [pid],
            'type': 'summary',
        })
    _write_dataset('crud-rag', list(corpus_by_pid.values()), queries,
                   {'benchmark': 'CRUD-RAG', 'split': 'split_merged',
                    'corpus_mode': 'news-subset', 'per_task': args.per_task})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('beir')
    p.add_argument('name', choices=BEIR_SMALL)
    p.add_argument('--corpus-limit', type=int, default=None,
                   help='只保留 gold + 哈希抽样的干扰 passage（默认全量）')
    p.set_defaults(func=cmd_beir)

    p = sub.add_parser('beir-sampled')
    p.add_argument('name', choices=BEIR_LARGE)
    p.add_argument('--queries', type=int, default=2000)
    p.add_argument('--negatives', type=int, default=28000)
    p.set_defaults(func=cmd_beir_sampled)

    p = sub.add_parser('hotpotqa')
    p.add_argument('--questions', type=int, default=2000)
    p.set_defaults(func=cmd_hotpotqa)

    p = sub.add_parser('musique')
    p.add_argument('--questions', type=int, default=1000)
    p.set_defaults(func=cmd_musique)

    p = sub.add_parser('2wiki')
    p.add_argument('--per-type', type=int, default=75)
    p.set_defaults(func=cmd_2wiki)

    p = sub.add_parser('crag')
    p.add_argument('--questions', type=int, default=300)
    p.set_defaults(func=cmd_crag)

    p = sub.add_parser('rgb')
    p.set_defaults(func=cmd_rgb)

    p = sub.add_parser('ragbench')
    p.add_argument('--per-domain', type=int, default=150)
    p.set_defaults(func=cmd_ragbench)

    p = sub.add_parser('crud')
    p.add_argument('--per-task', type=int, default=200)
    p.set_defaults(func=cmd_crud)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
