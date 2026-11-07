#!/usr/bin/env python3
"""图谱评测 HTTP 客户端：复用 rag-metrics 的登录/重试，补三条图谱路径。

* ``POST /graph-imports``          上传 zip（异步，返回 202）
* ``GET  /knowledge-bases/{id}``   轮询导入状态（5 = 就绪，104 = 失败/有错误）
* ``POST /retrieval/graph``        图检索（``bases`` 用 ``graph_<id>`` 表名）
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# 按文件路径加载 rag-metrics 的客户端：两个工具目录都有 metrics.py，
# 把兄弟目录塞进 sys.path 会让本目录的 ``import metrics`` 解析到错误的模块。
_RKB_CLIENT = Path(__file__).resolve().parents[1] / 'rag-metrics' / 'rkb_client.py'
_SPEC = importlib.util.spec_from_file_location('rag_metrics_rkb_client', _RKB_CLIENT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault('rag_metrics_rkb_client', _MODULE)
_SPEC.loader.exec_module(_MODULE)
RkbClient = _MODULE.RkbClient
RkbError = _MODULE.RkbError

STATUS_READY = 5
STATUS_FAILED = 104
DEFAULT_EMBEDDING = 'Qwen3-Embedding-0.6B'


class GraphClient(RkbClient):
    """产品图谱评测客户端；Session/登录/401 重登都在父类。"""

    def list_kbs(self) -> list[Dict[str, Any]]:
        """列表接口是 ``{items,total,page,pageSize}``（父类读的是旧 ``data``）。"""
        result = self._request(
            'GET', '/knowledge-bases?page=1&size=500&keyword=&categories=10') or {}
        return list(result.get('items') or [])

    def import_zip(self, path: Path) -> Any:
        """上传图谱导入包；服务端 202 + 空体，导入在后台线程跑。"""
        content = Path(path).read_bytes()
        return self._request(
            'POST', '/graph-imports',
            files={'file': (Path(path).name, content, 'application/zip')})

    def wait_ready(self, kb_id: str, *, timeout: int = 3600,
                   interval: float = 5.0, log=print) -> Dict[str, Any]:
        """轮询到终态；超时抛 ``RkbError``（不把「还在跑」当成成功）。"""
        deadline = time.monotonic() + timeout
        last = None
        while True:
            detail = self.get_kb(kb_id)
            status = detail.get('status')
            process = detail.get('process')
            if (status, process) != last:
                log(f'[import] kb={kb_id} status={status} process={process}%')
                last = (status, process)
            if status == STATUS_READY:
                return detail
            if status == STATUS_FAILED:
                raise RkbError(
                    f'导入失败 kb={kb_id}: {detail.get("failReason") or "unknown"}')
            if time.monotonic() >= deadline:
                raise RkbError(f'导入超时 kb={kb_id}（{timeout}s，最后状态 {status}）')
            time.sleep(interval)

    def retrieve_graph(self, base: str, query: str, *,
                       embedding: str = DEFAULT_EMBEDDING,
                       seed_k: int = 10, depth: int = 1,
                       limit: int = 1000, score: float = 0.0,
                       labels: Optional[list[str]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'query': query,
            'embedding': embedding,
            'bases': [base],
            'seed_k': seed_k,
            'depth': depth,
            'limit': limit,
            'score': score,
        }
        if labels:
            payload['labels'] = labels
        return self._request('POST', '/retrieval/graph', json_body=payload) or {}
