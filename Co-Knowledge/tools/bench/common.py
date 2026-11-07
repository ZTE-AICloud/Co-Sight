"""公开基准评测的公共组件。

设计目标：一套最小接口覆盖 11 个公开基准，且所有口径都能在报告里复述。

* 语料/查询统一成 JSONL（``corpus.jsonl`` / ``queries.jsonl``），
  每个基准一个目录，产物只落在 ``.metrics-data/bench/``（已 gitignore）。
* 文档库导入走产品自己的 ``POST /knowledge-bases/{id}/chunks``（手工切片），
  一个 passage = 一/多个 chunk；``content`` 是干净正文（embedding + 关键词），
  ``supplement`` 带 ``【<PREFIX>-<pid>】`` 标记（向量路返回展示正文）。
* 端到端问答走已发布工作流的 ``POST /query``，每题独立 ``conversation_id``。
* 判定/评分函数与 ``tools/graph-metrics/run_2wiki_e2e.py`` 保持同一口径，
  新增网关 judge（与生成模型分开，避免自评）。
"""

from __future__ import annotations

import hashlib
import json
import re
import string
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'tools' / 'rag-metrics'))

from rkb_client import RkbClient, RkbError  # noqa: E402

BENCH_DATA = REPO_ROOT / '.metrics-data' / 'bench'
RAW_DIR = BENCH_DATA / 'raw'
RUNS_DIR = BENCH_DATA / 'runs'
DEFAULT_BASE = 'http://127.0.0.1/api/co-knowledge/v1'
DEFAULT_EMBEDDING = 'Qwen3-Embedding-0.6B'
DEFAULT_RERANK = 'Qwen3-Reranker-4B'
MAX_PART_CHARS = 4000
SHARD_SIZE = 2500

WHITESPACE_RE = re.compile(r'\s+')
THINK_RE = re.compile(r'<think\b[^>]*>.*?</think\s*>', re.I | re.S)
ARTICLES = {'a', 'an', 'the'}


# ----------------------------------------------------------------------
# 数据读写
# ----------------------------------------------------------------------

def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            count += 1
    return count


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def dataset_dir(name: str) -> Path:
    return BENCH_DATA / name


def load_manifest(name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    directory = dataset_dir(name)
    corpus = read_jsonl(directory / 'corpus.jsonl')
    queries = read_jsonl(directory / 'queries.jsonl')
    stats_path = directory / 'stats.json'
    stats = json.loads(stats_path.read_text(encoding='utf-8')) if stats_path.exists() else {}
    return corpus, queries, stats


def stable_hash(text: str) -> str:
    return hashlib.sha1(str(text).encode('utf-8')).hexdigest()


def hash_fraction(text: str, seed: int = 42) -> float:
    """[0,1) 的确定性哈希，用于可复现抽样。"""
    digest = hashlib.sha1(f'{seed}:{text}'.encode('utf-8')).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def sample_rows(rows: Sequence[Dict[str, Any]], limit: int,
                key: str = 'qid', seed: int = 42) -> List[Dict[str, Any]]:
    """按 key 的哈希排序取前 limit 条：可复现、与输入顺序无关。"""
    ordered = sorted(rows, key=lambda row: stable_hash(f'{seed}:{row.get(key, "")}'))
    return ordered[:limit]


def split_parts(text: str, max_chars: int = MAX_PART_CHARS) -> List[str]:
    text = str(text or '')
    if len(text) <= max_chars:
        return [text]
    return [text[start:start + max_chars] for start in range(0, len(text), max_chars)]


# ----------------------------------------------------------------------
# 评分（SQuAD 口径 + 覆盖）
# ----------------------------------------------------------------------

def normalize_answer(text: str) -> str:
    text = (text or '').lower()
    text = ''.join(' ' if char in string.punctuation else char for char in text)
    text = ' '.join(word for word in text.split() if word not in ARTICLES)
    return WHITESPACE_RE.sub(' ', text).strip()


def token_f1(prediction: str, gold: str) -> float:
    pred_tokens = normalize_answer(prediction).split()
    gold_tokens = normalize_answer(gold).split()
    if not pred_tokens or not gold_tokens:
        return float(pred_tokens == gold_tokens)
    remaining = list(gold_tokens)
    common = 0
    for token in pred_tokens:
        if token in remaining:
            remaining.remove(token)
            common += 1
    if common == 0:
        return 0.0
    precision = common / len(pred_tokens)
    recall = common / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def _gold_list(gold: str | Sequence[str]) -> List[str]:
    if isinstance(gold, str):
        parts = [part.strip() for part in re.split(r'\s*\|\s*', gold) if part.strip()]
        return parts or [gold]
    return [str(item) for item in gold if str(item).strip()]


def score_answer(prediction: str, gold: str | Sequence[str]) -> Dict[str, float]:
    golds = _gold_list(gold)
    best_f1 = max(token_f1(prediction, candidate) for candidate in golds)
    best_em = max(normalize_answer(prediction) == normalize_answer(candidate)
                  for candidate in golds)
    normalized_pred = normalize_answer(prediction)
    contains = any(
        normalize_answer(candidate)
        and re.search(r'(?<!\w)' + re.escape(normalize_answer(candidate)) + r'(?!\w)',
                      normalized_pred)
        for candidate in golds)
    return {'em': float(best_em), 'f1': best_f1, 'contains': float(contains)}


def strip_answer(answer: str) -> str:
    return THINK_RE.sub('', answer or '').strip().strip('"').strip("'").strip()


def evidence_hit(text: str, gold_titles: Sequence[str]) -> float:
    lowered = (text or '').lower()
    if not gold_titles:
        return 0.0
    hit = sum(1 for title in gold_titles if str(title).lower() in lowered)
    return hit / len(gold_titles)


def bootstrap_ci(values: Sequence[float], resamples: int = 2000,
                 seed: int = 42) -> Tuple[float, float]:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return (float('nan'), float('nan'))
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=(resamples, array.size))
    means = array[indices].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def mean_ci(values: Sequence[float]) -> Dict[str, float]:
    array = np.asarray([v for v in values if v is not None], dtype=float)
    if array.size == 0:
        return {'n': 0, 'mean': 0.0, 'ci95_low': 0.0, 'ci95_high': 0.0}
    low, high = bootstrap_ci(array)
    return {'n': int(array.size), 'mean': float(array.mean()),
            'ci95_low': low, 'ci95_high': high}


# ----------------------------------------------------------------------
# 产品客户端
# ----------------------------------------------------------------------

def safe_pid(pid: str) -> str:
    """标记里只放字母数字与 ._:-，避免分隔符把映射弄坏。"""
    text = re.sub(r'[^A-Za-z0-9_.:-]', '_', str(pid))
    if len(text) > 100:
        text = text[:80] + '_' + stable_hash(pid)[:12]
    return text


class BenchClient(RkbClient):
    """在 RkbClient 之上补：批量灌库、建单库工作流、E2E 提问。"""

    def __init__(self, base_url: str = DEFAULT_BASE, timeout: int = 180, **kwargs: Any):
        super().__init__(base_url=base_url, timeout=timeout, **kwargs)

    def list_kbs(self) -> List[Dict[str, Any]]:
        """API 2.0 列表是 ``{items,total}``；父类读的旧 ``data`` 会恒空。"""
        result = self._request(
            'GET', '/knowledge-bases?page=1&size=500&keyword=&categories=1,10') or {}
        return list(result.get('items') or result.get('data') or [])

    def create_kb(self, name: str, embedding_model: str = DEFAULT_EMBEDDING,
                  description: str = 'bench', keyword_analyzer: str = '') -> Dict[str, Any]:
        props: Dict[str, Any] = {'embeddingModel': embedding_model}
        if keyword_analyzer:
            props['keywordAnalyzer'] = keyword_analyzer
        return self._request('POST', '/knowledge-bases', json_body={
            'name': name, 'description': description, 'props': props})

    def ensure_kb(self, name: str, embedding_model: str = DEFAULT_EMBEDDING,
                  keyword_analyzer: str = '') -> Dict[str, Any]:
        existing = self.find_kb(name)
        if existing:
            return self.get_kb(existing['id'])
        return self.create_kb(name, embedding_model, keyword_analyzer=keyword_analyzer)

    def list_files(self, kb_id: str) -> List[Dict[str, Any]]:
        page = self._request(
            'GET', f'/knowledge-bases/{kb_id}/documents?page=1&size=100') or {}
        return list(page.get('items') or page.get('data') or [])

    def default_directory(self, kb_id: str) -> str:
        """取默认目录；产品建库偶发没有建默认目录，补建一个根目录。"""
        rows = self._request(
            'GET', f'/knowledge-bases/{kb_id}/directories?type=folder&sort=true') or []
        if isinstance(rows, dict):
            rows = rows.get('items') or rows.get('data') or []
        for row in rows:
            if row.get('id'):
                return str(row['id'])
        created = self._request(
            'POST', f'/knowledge-bases/{kb_id}/directories',
            json_body={'title': 'benchmark'}) or {}
        if created.get('id'):
            return str(created['id'])
        raise RkbError(f'知识库 {kb_id} 没有默认目录，补建也失败: {created}')

    def wait_for_file(self, kb_id: str, filename: str, timeout: int = 120) -> None:
        deadline = time.time() + timeout
        last = None
        failed_since: Optional[float] = None
        while time.time() < deadline:
            for row in self.list_files(kb_id):
                if row.get('title') == filename:
                    last = row
                    if row.get('status') == 1:
                        error = row.get('failReason') or row.get('errorMsg')
                        if error:
                            print(f'[container] {filename} ready with warning: {error}')
                        return
                    if row.get('status') == 2:
                        # updateOrInsertException 等 DB 错误是瞬时的：先观察 30s，
                        # 仍失败才抛。直接抛会让整轮导入无谓中止。
                        failed_since = failed_since or time.time()
                        if time.time() - failed_since > 30:
                            raise RkbError(
                                f'容器文件导入失败: {filename} '
                                f'{row.get("failReason") or row.get("errorMsg") or ""}')
                    else:
                        failed_since = None
            time.sleep(1)
        raise RkbError(f'容器文件 {filename} 未在 {timeout}s 内就绪: {last}')

    # -- 灌库 ----------------------------------------------------------
    def marker_regex(self, prefix: str) -> re.Pattern[str]:
        return re.compile(r'【' + re.escape(prefix.upper()) + r'-([^】]+)】')

    def existing_pids(self, kb_id: str, prefix: str) -> set[str]:
        regex = self.marker_regex(prefix)
        found: set[str] = set()
        for row in self.list_chunks(kb_id):
            for field in ('supplement', 'content'):
                match = regex.search(row.get(field) or '')
                if match:
                    found.add(match.group(1))
                    break
        return found

    def ensure_shard_files(self, kb_id: str, directory_id: str, name: str,
                           passage_count: int) -> List[str]:
        existing = {row.get('title'): row for row in self.list_files(kb_id)}
        container = (
            f'# {name} benchmark shard {{index}}\n\n'
            '本文件仅作为评测切片的容器，不参与检索评分。它本身不包含任何评测语料，'
            '只用于承载通过手工切片接口写入的 passage；检索指标会把这段正文按'
            '「非相关、占一个排名位」处理。The container file only carries manually '
            'added benchmark chunks and is treated as non-relevant during scoring. '
            'It intentionally contains a short bilingual description so that the '
            'product split operator has enough text to process.\n'
        )
        file_ids: List[str] = []
        for index in range((passage_count + SHARD_SIZE - 1) // SHARD_SIZE):
            filename = f'{name}-shard-{index:03d}.md'
            row = existing.get(filename)
            # 切分失败时产品仍把 status 置 1，只把错误留在 errorMsg。容器本身
            # 仍是手工切片的合法锚点（实测 chunk/add 正常），**不能删**：
            # 删除文件会连带删掉已挂上去的切片。
            usable = bool(row and row.get('status') == 1)
            file_id = row.get('id') if usable else None
            if not file_id:
                if row and row.get('id'):
                    self.delete_file(kb_id, row['id'])
                    # 删除是异步的；立刻用同名重建会撞唯一约束
                    # （updateOrInsertException）。等旧行消失再传。
                    deadline = time.time() + 30
                    while time.time() < deadline:
                        if not any(item.get('title') == filename
                                   for item in self.list_files(kb_id)):
                            break
                        time.sleep(0.5)
                file_id = self.upload_container(
                    kb_id, directory_id, filename, container.format(index=index))
            file_ids.append(file_id)
        return file_ids

    @staticmethod
    def _display_text(prefix: str, pid: str, text: str) -> str:
        return f'【{prefix.upper()}-{pid}】\n{text}'

    def import_corpus(self, kb_name: str, passages: Sequence[Dict[str, Any]],
                      prefix: str, workers: int = 16,
                      embedding_model: str = DEFAULT_EMBEDDING,
                      resume: bool = True,
                      keyword_analyzer: str = '') -> Dict[str, Any]:
        """一 passage = 一/多个 chunk 灌入独立知识库；幂等可续灌。"""
        if resume:
            kb = self.ensure_kb(kb_name, embedding_model, keyword_analyzer)
        else:
            old = self.find_kb(kb_name)
            if old:
                raise RkbError(f'KB 已存在: {old["id"]}；复用请加 --resume')
            kb = self.create_kb(kb_name, embedding_model,
                                keyword_analyzer=keyword_analyzer)
        kb_id = str(kb['id'])
        directory_id = self.default_directory(kb_id)
        already = self.existing_pids(kb_id, prefix) if resume else set()

        pids: List[Tuple[str, str, str]] = []
        for row in passages:
            pid = safe_pid(row['pid'])
            text = str(row.get('text') or '')
            title = str(row.get('title') or '').strip()
            content = f'{title}\n{text}'.strip() if title else text
            pids.append((pid, content, text))
        todo = [item for item in pids if item[0] not in already]
        shard_files = self.ensure_shard_files(kb_id, directory_id, kb_name, len(pids))
        run_dir = RUNS_DIR / kb_id
        run_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = run_dir / 'imported.jsonl'

        items = [(pid, part) for pid, content, _ in todo for part in split_parts(content)]
        started = time.time()
        done = 0
        failures: List[Dict[str, str]] = []

        def add_one(item: Tuple[str, str]) -> None:
            pid, part = item
            file_id = shard_files[int(stable_hash(pid)[:12], 16) % len(shard_files)]
            self.add_chunk(kb_id, file_id, part,
                           self._display_text(prefix, pid, part))

        with checkpoint.open('a', encoding='utf-8') as handle:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(add_one, item): item for item in items}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        future.result()
                        handle.write(json.dumps({'pid': item[0]}) + '\n')
                        handle.flush()
                        done += 1
                    except Exception as error:  # noqa: BLE001
                        failures.append({'pid': item[0], 'error': str(error)[:500]})
                    if done and done % 200 == 0:
                        rate = done / max(time.time() - started, 1e-6)
                        print(f'  import {done}/{len(items)} parts, '
                              f'{rate:.1f} parts/s, failures={len(failures)}', flush=True)
        summary = {
            'kb_id': kb_id,
            'kb_name': kb_name,
            'passages': len(pids),
            'already_imported': len(already),
            'parts_attempted': len(items),
            'parts_succeeded': done,
            'failure_count': len(failures),
            'failures': failures[:30],
            'elapsed_seconds': round(time.time() - started, 1),
            'parts_per_second': round(done / max(time.time() - started, 1e-6), 2),
        }
        write_json(run_dir / 'import-summary.json', summary)
        return summary

    # -- 工作流 --------------------------------------------------------
    def ensure_workflow(self, workflow_id: str, name: str, kb_id: str,
                        prompt: str, top_k: int = 20, rerank_top_n: int = 8) -> str:
        try:
            flow = self._request('GET', f'/workflows/{workflow_id}/flow')
            print(f'[flow] reuse {workflow_id}')
        except RkbError:
            detail = self.get_kb(kb_id)
            bound = {
                'name': detail.get('name'),
                'type': detail.get('type') or 'document',
                'tableName': detail.get('tableName'),
                'embeddingModel': detail.get('embeddingModel') or DEFAULT_EMBEDDING,
                'category': 10,
            }
            self._request('POST', '/workflows', json_body={
                'name': name,
                'workFlowId': workflow_id,
                'template': 'Blended',
                'knowledgeType': 'knowledgeBase',
                'description': name,
                'boundInfo': {'running': [bound], 'dev': []},
            }, retries=1)
            print(f'[flow] created {workflow_id}')
            flow = self._request('GET', f'/workflows/{workflow_id}/flow')
        for node in flow.get('nodeConfigDTOList') or []:
            copies = [node.get('variables')]
            data = node.get('data')
            if isinstance(data, dict):
                copies.append(data.get('variables'))
            for variables in copies:
                if not isinstance(variables, dict):
                    continue
                for stage in ('retriever', 'postretriever', 'responsesynthesizer'):
                    for operator in variables.get(stage) or []:
                        kwargs = operator.setdefault('kwargs', {})
                        name_ = operator.get('operator') or ''
                        if name_ == 'VectorRetriever':
                            for info in kwargs.get('knowledge_info_list') or []:
                                info['top_k'] = top_k
                                info['score'] = 0.0
                        elif name_ == 'KeywordRetriever':
                            kwargs['top_k'] = top_k
                        elif name_ == 'FusionRetriever':
                            kwargs['top_k'] = max(top_k * 2, 30)
                        elif name_ in ('LLMReranker', 'BgeLargeReranker',
                                       'ExternalModelReranker'):
                            # 模板默认是 LLMReranker（单次 5–20 s，且 top_n=5 容易
                            # 把多跳证据挤掉）；改用注册表里的 cross-encoder。
                            operator['operator'] = 'ExternalModelReranker'
                            operator['package'] = \
                                'core.rag.post_retriever.external_model_reranker'
                            kwargs.clear()
                            kwargs.update({
                                'model': DEFAULT_RERANK,
                                'top_n': rerank_top_n,
                                'score': -100,
                                'desc_info': operator.get('desc_info')
                                             or 'Rerank retrieved nodes',
                            })
                        elif name_ in ('RagSimpleSummarizer', 'SimpleSummarizer'):
                            for config in kwargs.get('generator-config') or []:
                                config['prompt'] = prompt
                                config['no_context_prompt'] = prompt
        self._request('PUT', f'/workflows/{workflow_id}/flow', json_body=flow)
        self._request('POST', f'/workflows/{workflow_id}/publication', json_body={})
        return workflow_id

    def ask(self, workflow_id: str, question: str) -> Dict[str, Any]:
        started = time.perf_counter()
        response = self._request('POST', '/query', json_body={
            'question': question,
            'conversation_id': str(uuid.uuid4()),
            'workflow_id': workflow_id,
            'stream': False,
            'include_retrieval': True,
        }, retries=1)
        elapsed = time.perf_counter() - started
        retrieval = response.get('retrieval') or {}
        items = retrieval.get('items') or []
        return {
            'answer': strip_answer(response.get('answer') or ''),
            'items': items,
            'context': '\n'.join(str(item.get('text') or '') for item in items),
            'timings': retrieval.get('timings') or {},
            'elapsed_s': elapsed,
        }


# ----------------------------------------------------------------------
# 网关 judge（与产品生成模型分开）
# ----------------------------------------------------------------------

def load_deploy_env(path: Optional[Path] = None) -> Dict[str, str]:
    path = path or (REPO_ROOT / 'deploy' / '.env')
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class GatewayJudge:
    """直连生成网关做判定；不写 key，不打日志。"""

    def __init__(self, model: str = '', base_url: str = '',
                 api_key: str = '', timeout: int = 120):
        env = load_deploy_env()
        self.base_url = (base_url or env.get('GENERATION_GATEWAY_URL') or '').rstrip('/')
        if not self.base_url:
            raise ValueError('GENERATION_GATEWAY_URL (or base_url) is required')
        self.api_key = api_key or env.get('GENERATION_API_KEY') or ''
        self.model = model or env.get('GENERATION_MODEL') or 'your-chat-model'
        self.timeout = timeout
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, 'session', None)
        if session is None:
            import requests
            session = requests.Session()
            session.trust_env = True
            self._local.session = session
        return session

    def chat(self, prompt: str, max_tokens: int = 256,
             temperature: float = 0.0) -> str:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        payload = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': max_tokens,
            'temperature': temperature,
        }
        if self.model.startswith('deepseek'):
            payload['chat_template_kwargs'] = {'thinking': False}
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = self._session().post(
                    f'{self.base_url}/chat/completions', json=payload,
                    headers=headers, timeout=self.timeout)
                if response.status_code >= 400:
                    raise RuntimeError(f'HTTP {response.status_code}: {response.text[:200]}')
                data = response.json()
                return (data['choices'][0]['message'].get('content') or '').strip()
            except Exception as error:  # noqa: BLE001
                last_error = error
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f'judge failed: {last_error}')

    def judge_correct(self, question: str, gold: str | Sequence[str],
                      prediction: str) -> Dict[str, Any]:
        golds = _gold_list(gold)
        prompt = (
            'You are a strict but fair grader. Decide whether the prediction is '
            'factually correct for the question, allowing for paraphrasing, '
            'aliases, and extra explanation. If the gold answer is a list, the '
            'prediction must contain all required items. A refusal or "cannot '
            'answer" is correct only when the question is unanswerable.\n\n'
            f'Question: {question}\n'
            f'Gold answer(s): {json.dumps(golds, ensure_ascii=False)}\n'
            f'Prediction: {prediction}\n\n'
            'Return strict JSON: {"correct": 0 or 1, "reason": "<=20 words"}'
        )
        text = self.chat(prompt)
        match = re.search(r'\{.*\}', text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                return {'correct': 1 if int(data.get('correct', 0)) else 0,
                        'reason': str(data.get('reason') or '')[:200],
                        'raw': text[:500]}
            except (ValueError, TypeError):
                pass
        return {'correct': 1 if re.search(r'\b(correct|yes)\b', text, re.I) else 0,
                'reason': text[:200], 'raw': text[:500]}

    def judge_error_detection(self, prediction: str) -> int:
        prompt = (
            'Does the response explicitly state that the provided documents '
            'contain factual errors or incorrect information? Answer only YES '
            'or NO.\n\nResponse: ' + prediction
        )
        return 1 if re.search(r'\bYES\b', self.chat(prompt, max_tokens=8), re.I) else 0

    def judge_rejection(self, question: str, prediction: str) -> int:
        prompt = (
            'The question is unanswerable from the provided documents. Does '
            'the response refuse to answer (instead of guessing)? Answer only '
            'YES or NO.\n\n'
            f'Question: {question}\nResponse: {prediction}'
        )
        text = self.chat(prompt, max_tokens=8)
        if re.search(r'\bYES\b', text, re.I):
            return 1
        if re.search(r'\bNO\b', text, re.I):
            return 0
        return int(is_refusal(prediction))


REFUSAL_MARKERS = (
    'i cannot answer', 'i can not answer', 'cannot answer', 'can not answer',
    "i don't know", 'i do not know', "don't know", 'do not know',
    'insufficient information', 'not enough information', 'unable to answer',
    '无法回答', '不能回答', '信息不足', '文档信息不足', '无法基于', '没有足够',
)


def is_refusal(text: str) -> bool:
    lowered = (text or '').lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


# ----------------------------------------------------------------------
# 报告
# ----------------------------------------------------------------------

def summarize_values(rows: Sequence[Dict[str, Any]], key: str,
                     group_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """按 group_key 分组对 key 求均值 + 95% CI。"""
    buckets: Dict[str, List[float]] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        group = str(row.get(group_key, 'all')) if group_key else 'all'
        buckets.setdefault(group, []).append(float(value))
    return [{'group': group, **mean_ci(values)} for group, values in sorted(buckets.items())]
