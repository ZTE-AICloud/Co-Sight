#!/usr/bin/env python3
"""co-knowledge 连通性自检（只读已发布工作流列表，不触发 RAG 查询、不产生 LLM 费用）。

地址与 API Key 的解析顺序与查询一致：函数/CLI 参数 > 框架「知识库路由设置」 > 环境变量。

用法::

    python check_env.py                              # 框架路由 > 默认 http://localhost:4910
    python check_env.py --base-url http://localhost:8080
    python check_env.py --json                       # 机器可读输出

退出码：0 = 服务可达且 Key 有效；1 = 不可达 / 缺 Key / Key 无效。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_knowledge_search import (  # noqa: E402
    build_opener,
    build_query_url,
    build_workflows_url,
    problem_detail,
    resolve_knowledge_source,
)


def _probe(url: str, api_key: str, timeout: float) -> Tuple[Optional[int], Optional[str]]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with build_opener(url).open(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200) or 200), None
    except urllib.error.HTTPError as exc:
        # 收到 HTTP 响应即视为服务可达；401/403 说明 Key 或权限有问题。
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # pragma: no cover - 读取失败不影响可达性结论
            body = ""
        return int(exc.code), f"HTTP {exc.code}: {problem_detail(body)}"
    except urllib.error.URLError as exc:
        return None, f"CONNECTION_ERROR: {exc.reason}"
    except Exception as exc:  # pragma: no cover - 兜底
        return None, f"INTERNAL_ERROR: {type(exc).__name__}: {exc}"


def check(base_url: Optional[str] = None, timeout: float = 5.0) -> dict:
    resolved_base, api_key = resolve_knowledge_source(base_url)
    query_url = build_query_url(resolved_base)
    result = {
        "reachable": False,
        "authorized": False,
        "base_url": resolved_base,
        "status": None,
        "error": None,
    }
    if query_url is None:
        result["error"] = f"INVALID_ARGUMENT: base_url 非法：{resolved_base!r}"
        return result
    if not api_key:
        result["error"] = "MISSING_API_KEY: 未配置知识库 Agent API Key"
        return result

    status, error = _probe(build_workflows_url(query_url), api_key, timeout)
    result.update(
        reachable=status is not None,
        authorized=status == 200,
        status=status,
        error=error,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="co-knowledge 连通性检查")
    parser.add_argument("--base-url", default=None, help="知识库地址，缺省读框架路由 / CO_KNOWLEDGE_BASE_URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="探测超时（秒）")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认即为 JSON）")
    args = parser.parse_args()

    result = check(args.base_url, args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["authorized"] else 1


if __name__ == "__main__":
    sys.exit(main())
