"""用产品的 ``LLMReranker`` 对候选做 LLM 重排（默认 deepseek-chat）。

输入：``prepare_rerank_input.py`` 生成的 JSONL（每行一个 query + top-N 候选）。
输出：JSONL（reranked pids + 指标 + 延迟 + fallback 标记）。

口径：
* ``top_n`` 就是最终交给下游的候选数（默认 10）；指标只在这个列表上算。
* ``LLMReranker`` 内部按 ``choice_batch_size``（默认 10）分批调模型，再按相关性
  分数合并取 top_n；失败时回退原顺序（这里用 ``last_fallback`` 记录）。
* 候选正文超过 4,000 字符在输入准备阶段已截断（与导入时子片大小一致）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import score_query  # noqa: E402

from engine.custom_llm import get_custom_llm  # noqa: E402
from engine.post_retriever.llm_reranker import LLMReranker  # noqa: E402
from engine.primitives.components.rerank import LLMRerank  # noqa: E402
from engine.primitives.models import (  # noqa: E402
    Node,
    NodeWithScore,
    QueryBundle,
)
from engine.primitives.templating import PromptTemplate, PromptType  # noqa: E402

FULL_SELECT_PROMPT = """下面是一组文档，每篇文档有编号。请根据问题，把**所有文档**按相关性从高到低排序，
输出与输入文档数量相同的行，每行格式严格为：
Doc: <编号>, Relevance: <1-10 的整数>
不要遗漏任何文档；与问题无关的文档给低分（1）。

{context_str}
Question: {query_str}
Answer:
"""

KS = [1, 3, 5, 10]


class RecordingLLMReranker(LLMReranker):
    """与 LLMReranker 相同的成功路径；失败时同样回退，但留下 fallback 标记。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.last_fallback = False
        self.last_error = ''

    def _postprocess_nodes(self, nodes, query_bundle=None):
        try:
            result = LLMRerank._postprocess_nodes(self, nodes, query_bundle)
            self.last_fallback = False
            self.last_error = ''
            return result
        except Exception as exc:                                  # noqa: BLE001
            self.last_fallback = True
            self.last_error = f'{type(exc).__name__}: {exc}'[:500]
            return nodes[:self.top_n]


def build_nodes(candidates: List[Dict[str, str]]) -> List[NodeWithScore]:
    nodes = [
        Node(text=item['text'], metadata={'pid': item['pid']},
             excluded_llm_metadata_keys=['pid'])
        for item in candidates
    ]
    return [NodeWithScore(node=node, score=1.0) for node in nodes]


def load_gold(path: str) -> Dict[str, set]:
    import pandas as pd
    qrels = pd.read_parquet(path)
    gold: Dict[str, set] = {}
    for row in qrels.itertuples(index=False):
        gold.setdefault(str(row.qid), set()).add(str(row.pid))
    return gold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='.metrics-data/rerank/candidates-top50.jsonl')
    parser.add_argument('--output', default='.metrics-data/rerank/reranked-top10.jsonl')
    parser.add_argument('--qrels', default='.metrics-data/duretrieval/qrels.parquet')
    parser.add_argument('--llm', default='deepseek-chat')
    parser.add_argument('--top-n', type=int, default=10)
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--max-tokens', type=int, default=2048)
    parser.add_argument('--temperature', type=float, default=0.0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--prompt-style', choices=['default', 'full'], default='default',
                        help='default=产品默认 prompt；full=要求模型输出全部候选并排序')
    parser.add_argument('--thinking', choices=['default', 'off', 'on'], default='default',
                        help='deepseek-chat 的 thinking；off = chat_template_kwargs.thinking=false')
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    done = set()
    if os.path.isfile(args.output):
        with open(args.output, encoding='utf-8') as handle:
            for line in handle:
                try:
                    done.add(json.loads(line)['qid'])
                except Exception:                                  # noqa: BLE001
                    continue
        print(f'resume: {len(done)} queries already done')

    rows = []
    with open(args.input, encoding='utf-8') as handle:
        for line in handle:
            item = json.loads(line)
            if item['qid'] in done:
                continue
            rows.append(item)
            if args.limit and len(rows) >= args.limit:
                break
    print(f'rerank {len(rows)} queries, llm={args.llm}, top_n={args.top_n}, '
          f'batch={args.batch_size}, workers={args.workers}')

    gold = load_gold(args.qrels)
    llm_config = {
        'llm': args.llm,
        'max_token': args.max_tokens,
        'temperature': args.temperature,
    }
    if args.thinking != 'default':
        llm_config['chat_template_kwargs'] = {'thinking': args.thinking == 'on'}
    llm = get_custom_llm(args.llm, llm_config)
    started = time.time()
    finished = 0
    prompt = (PromptTemplate(FULL_SELECT_PROMPT, prompt_type=PromptType.CHOICE_SELECT)
              if args.prompt_style == 'full' else None)

    def run(item: Dict[str, Any]) -> Dict[str, Any]:
        reranker = RecordingLLMReranker(
            llm=llm, top_n=args.top_n, choice_batch_size=args.batch_size,
            choice_select_prompt=prompt)
        wrapped = build_nodes(item['candidates'])
        begin = time.perf_counter()
        result = reranker._postprocess_nodes(wrapped, QueryBundle(item['question']))
        latency = (time.perf_counter() - begin) * 1000
        returned = [node.metadata.get('pid') for node in result
                    if node.metadata.get('pid')]
        query_gold = gold.get(str(item['qid']), set())
        scores = score_query(returned, {pid: 1.0 for pid in query_gold}, KS)
        return {
            'qid': item['qid'],
            'question': item['question'],
            'returned': returned,
            'metrics': scores,
            'candidate_count': len(item['candidates']),
            'returned_count': len(returned),
            'fallback': reranker.last_fallback,
            'error': reranker.last_error,
            'latency_ms': round(latency, 2),
        }

    with open(args.output, 'a', encoding='utf-8') as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run, item) for item in rows]
            for future in as_completed(futures):
                try:
                    record = future.result()
                except Exception as error:                        # noqa: BLE001
                    print(f'query failed: {error}', flush=True)
                    continue
                out.write(json.dumps(record, ensure_ascii=False) + '\n')
                out.flush()
                finished += 1
                if finished % 20 == 0:
                    rate = finished / max(time.time() - started, 1e-6)
                    print(f'{finished}/{len(rows)} queries, {rate:.2f} q/s', flush=True)

    print(f'wrote {finished} records to {args.output}')


if __name__ == '__main__':
    main()
