#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-respond —— 批量历史范式应答器。

读取需求 JSON 数组，在本地知识库的「历史应答范式」向量库中检索最高相关条目，
自动继承历史应答的合规度（FC/PC/NC）、备注说明和参考文件，产出
`<stem>-已应答.json`（与输入同目录），供下游复核/回填使用。

要点：
  - 检索前做本地就绪校验 check_enabled_kbs_ready（知识库由 cosightbot-soc-kb-build 本地构建）；
  - embedding 端点走 COSIGHTBOT_EMBEDDING_API_URL/KEY（data/.env 注入）；
  - agent-id 默认 "soc"，一般无需传入。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-respond/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

import os  # noqa: E402

import requests  # noqa: E402

from common.soc_kb_readiness import check_enabled_kbs_ready  # noqa: E402
from common.soc_kb_registry.paths import SOC_AGENT_ID  # noqa: E402
from common.soc_retrieval import multi_kb_retrieve_paradigms  # noqa: E402

EMBEDDING_API_URL = os.environ.get("COSIGHTBOT_EMBEDDING_API_URL")
EMBEDDING_API_KEY = os.environ.get("COSIGHTBOT_EMBEDDING_API_KEY")


def get_embeddings(texts: list) -> list:
    if not texts:
        return []
    if not EMBEDDING_API_URL:
        print(
            "\n❌ Embedding 接口未配置（缺少 COSIGHTBOT_EMBEDDING_API_URL），"
            "没有向量就没法检索知识库，本次应答被迫终止。"
            "请在 data/.env 中配置后重试。",
            flush=True,
        )
        sys.exit(1)
    texts = [t if isinstance(t, str) else "" for t in texts]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {EMBEDDING_API_KEY}"
    }
    batch_size = 30
    all_embeddings = [None] * len(texts)
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        payload = json.dumps({"input": batch}, ensure_ascii=False)
        try:
            response = requests.post(
                EMBEDDING_API_URL, headers=headers, data=payload.encode("utf-8"), timeout=60)
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            # Embedding 接口调用失败 = 整批向量缺失 = 检索结果不可信
            # 必须直接报错退出，绝不能让用户拿到一份"看起来已应答"但向量完全是随机的产物。
            print(
                f"\n❌ Embedding 接口错误: 调用失败（batch {start}~{start + len(batch)}）: {e}",
                flush=True,
            )
            print(
                "❌ 没有向量就没法检索知识库，本次应答被迫终止；请检查网络/embedding 服务。",
                flush=True,
            )
            sys.exit(1)
        for item in result.get("data", []):
            idx = item.get("index")
            if 0 <= idx < len(batch):
                all_embeddings[start + idx] = item.get("embedding")
    if any(e is None for e in all_embeddings):
        # 捕获并立刻终止，避免 caller 拿不到向量还继续后续逻辑。
        print(
            "\n❌ Embedding 接口错误: 返回不完整，至少有一条文本没有拿到向量",
            flush=True,
        )
        print(
            "❌ 部分向量缺失 = 检索结果不可信，本次应答被迫终止；请重试或检查 embedding 服务。",
            flush=True,
        )
        sys.exit(1)
    return all_embeddings


class JsonResponder:
    def __init__(self, agent_id: str, desc_field="requirement", comp_field="compliance",
                 remarks_field="remarks", ref_field="reference_document"):
        self.agent_id = agent_id
        self.desc_field = desc_field
        self.comp_field = comp_field
        self.remarks_field = remarks_field
        self.ref_field = ref_field

    def _search_paradigms(self, query_text: str, query_vec=None, top_k=5):
        """遍历所有启用 KB 的 historical_paradigms 检索。

        query_vec：调用方批量 embedding 后的本条查询向量，传入可避免
        每条需求在检索层重复调用 embedding 服务。
        """
        try:
            nodes = multi_kb_retrieve_paradigms(
                self.agent_id, query_text, top=top_k, query_vec=query_vec,
            )
        except Exception as e:
            # 影响结果的异常：检索通道整体崩溃 = 本次匹配完全不可信。
            # 绝不静默返回 [] 让用户拿到 FC 占位应答。
            print(f"\n❌ 知识库错误: 历史范式检索失败: {e}", flush=True)
            print(
                "❌ 当前技能 [cosightbot-soc-respond] 无法继续，已立刻终止；"
                "请重试或检查向量库。",
                flush=True,
            )
            sys.exit(1)
        if not nodes:
            return []
        results = []
        for n in nodes:
            meta = dict(n.node.metadata or {})
            # final_score 是应用 KB 权重后的值；保留兼容字段名 similarity
            similarity = float(meta.get("final_score", 0.0) or 0.0)
            results.append(
                {
                    "compliance": meta.get("compliance", ""),
                    "remarks": meta.get("remarks", ""),
                    "reference": meta.get("reference_document", ""),
                    "matched_req": meta.get("description", ""),
                    "similarity": similarity,
                    "source": "paradigm",
                    "source_file": meta.get("source_file", ""),
                    "created_at": meta.get("created_at", ""),
                    "kb_id": meta.get("kb_id", ""),
                    "kb_name": meta.get("kb_name", ""),
                }
            )
        return results

    def respond(self, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        print(f"  [批处理] 生成 {len(requirements)} 个向量...", flush=True)
        descriptions = [req.get(self.desc_field, "") for req in requirements]
        query_embeddings = get_embeddings(descriptions)

        answered = []
        for i, req in enumerate(requirements):
            q_text = descriptions[i]
            q_vec = query_embeddings[i]

            # 传入批量预算的 q_vec，避免每条需求重复调用 embedding 服务
            paradigm_matches = self._search_paradigms(q_text, query_vec=q_vec)

            # 按相似度排序
            combined = sorted(
                paradigm_matches,
                key=lambda x: x.get("similarity", 0),
                reverse=True
            )

            # 未命中默认形态（红线）：知识库没覆盖的需求绝不带
            # "完全满足"默认文案直达回填——compliance 留空、置信度归零、
            # 其他说明写显式人工应答标记，fill validate 会强制列出未命中清单。
            req[self.comp_field] = ""
            req[self.remarks_field] = ""
            req[self.ref_field] = ""
            req["confidence"] = 0.0
            req["conflict"] = False
            req["review_notes"] = "未命中知识库（相似度阈值 0.45），需人工应答"
            req["matched_req"] = ""
            req["source_type"] = ""

            if not combined:
                answered.append(req)
                continue

            # 最佳匹配直接取排序后的第一个
            best_content = combined[0]
            best_sim = best_content.get("similarity", 0.0)

            if best_sim < 0.45:
                answered.append(req)
                continue

            matched_desc = best_content.get("matched_req", "")
            req["source_type"] = "历史范式"
            req["matched_req"] = matched_desc
            req["source_file"] = best_content.get("source_file", "")
            req["source_time"] = best_content.get("created_at", "")
            # 命中条目必须清掉未命中分支的默认标记，否则「需人工应答」会泄漏进
            # 已命中条目的【其他说明】列
            req["review_notes"] = ""

            # 填充应答数据
            req[self.comp_field] = best_content.get("compliance", "FC")
            req[self.remarks_field] = best_content.get("remarks", "")
            req[self.ref_field] = best_content.get("reference", "")

            # 置信度
            req["confidence"] = round(min(best_sim, 1.0), 2)

            answered.append(req)

            print(f"  [处理进度] {i + 1}/{len(requirements)}", flush=True)

        return answered


def main():
    parser = argparse.ArgumentParser(description="JSON 智能标书应答器")
    parser.add_argument("in_json", help="待应答的 JSON 文件路径")
    parser.add_argument("--req_field", default="requirement",
                        help="需求描述字段的 JSON 键名 (默认: requirement)")
    parser.add_argument("--comp_field", default="compliance",
                        help="合规性字段的 JSON 键名 (默认: compliance)")
    parser.add_argument("--remarks_field", default="remarks",
                        help="备注字段的 JSON 键名 (默认: remarks)")
    parser.add_argument("--ref_field", default="reference_document",
                        help="参考文件字段的 JSON 键名 (默认: reference_document)")
    parser.add_argument("--agent-id", default=SOC_AGENT_ID,
                        help=f"智能体 ID（默认 {SOC_AGENT_ID}，一般无需传入）")
    args = parser.parse_args()

    # 本地就绪校验：知识库由 cosightbot-soc-kb-build 本地构建（无云端同步）。
    # 未就绪 → 立刻终止（零兜底：不写任何"看起来已应答"的占位 JSON）。
    ready = check_enabled_kbs_ready(args.agent_id)
    if not ready["ok"]:
        print(
            f"RAG_SYNC_FAILED::sync_failed=true::reason=kb_not_ready::"
            f"agent={args.agent_id}",
            file=sys.stderr,
            flush=True,
        )
        print(f"\n❌ 知识库未就绪: {ready['reason']}", flush=True)
        print(
            "❌ 当前技能 [cosightbot-soc-respond] 无法继续，未生成任何中间文件。",
            flush=True,
        )
        sys.exit(1)

    in_path = Path(args.in_json).absolute()
    if not in_path.exists():
        print(f"错误: 文件不存在 {in_path}", flush=True)
        sys.exit(1)

    out_path = in_path.with_name(f"{in_path.stem}-已应答.json")

    print(f"[应答] 开始处理 JSON 应答: {in_path.name}", flush=True)
    print(f"[应答] 工作目录 (入参父目录): {in_path.parent}", flush=True)
    try:
        with open(in_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"错误: 读取 JSON 失败: {e}", flush=True)
        sys.exit(1)

    # 保存原始 JSON 结构，以便后续按原格式输出
    original_structure = None
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            # 标准格式：{"source_file": "...", "items": [...]}
            original_structure = {k: v for k,
                                  v in data.items() if k != "items"}
            data = data["items"]
        else:
            # 单个对象格式或列表
            if not isinstance(data, list):
                data = [data]

    responder = JsonResponder(
        agent_id=args.agent_id,
        desc_field=args.req_field,
        comp_field=args.comp_field,
        remarks_field=args.remarks_field,
        ref_field=args.ref_field,
    )
    answered_data = responder.respond(data)

    # 按照原始格式输出
    if original_structure is not None:
        # 恢复原始结构
        output_data = original_structure.copy()
        output_data["items"] = answered_data
    else:
        # 直接输出列表或单个对象
        output_data = answered_data if len(
            answered_data) != 1 else answered_data[0]

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    high = sum(1 for r in answered_data if r["confidence"] >= 0.9)
    med = sum(1 for r in answered_data if 0.7 <= r["confidence"] < 0.9)
    low = sum(1 for r in answered_data if r["confidence"] < 0.7)

    print(f"\n[成功] 应答完成! 数据已保存至: {out_path.name}", flush=True)
    print("--- 统计概览 ---", flush=True)
    print(f"  - 总需求数: {len(answered_data)}", flush=True)
    print(f"  - 高置信度 (>=0.9): {high}", flush=True)
    print(f"  - 中置信度 (0.7-0.9): {med}", flush=True)
    print(f"  - 低置信度 (<0.7): {low}", flush=True)
    unmatched = sum(1 for r in answered_data if not str(r.get("compliance", "")).strip())
    if unmatched:
        print(f"  - ⚠️ 未命中知识库（需人工应答）: {unmatched}", flush=True)


if __name__ == '__main__':
    main()
