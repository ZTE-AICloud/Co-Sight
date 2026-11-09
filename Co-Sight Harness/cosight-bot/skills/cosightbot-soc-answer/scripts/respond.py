#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-answer —— 单条需求智能应答器。

通过 runtime/common/ 下的共享模块实现：
  - 检索：common.soc_retrieval.multi_kb_retrieve（产品规范 + 历史范式；spec 内部 BGE 重排）
  - 排序：vector_score + 0.15（spec）
  - 合成：common.answer_synthesis.synthesize_cited_answer（带引文的 Markdown）
  - 引文：common.citation_writer.save_citations / stage_source_files /
          save_merged_paradigm_citations / save_merged_spec_citations

要点：
  - 检索前做本地就绪校验 check_enabled_kbs_ready；
  - 引文/参考文档链接全部是 file:// 本地文件 URL；
  - LLM 配置走 common.cosight_runtime（纯环境变量 ANTHROPIC_* / OPENAI_*）；
  - --agent-id 默认 "soc"，一般无需传入。
"""
import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-answer/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）

# 强制 UTF-8 输出
if sys.platform == 'win32':
    # reconfigure 原地改编码，不新建 TextIOWrapper：新 wrapper 会接管底层 buffer，
    # 旧对象 GC 时连坐关闭宿主句柄（pytest capture 流正是这样被打穿的）。
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')

# 共享模块导入
from common.answer_synthesis import synthesize_cited_answer  # noqa: E402
from common.citation_writer import (  # noqa: E402
    stage_source_files, save_citations,
    save_merged_paradigm_citations, save_merged_spec_citations,
)
from common.cosight_runtime import resolve_runtime_llm_config  # noqa: E402
from common.port_resolver import cosight_state_root  # noqa: E402
from common.skill_utils import extract_first_json  # noqa: E402
from common.soc_kb_readiness import check_enabled_kbs_ready  # noqa: E402
from common.soc_kb_registry.paths import SOC_AGENT_ID  # noqa: E402
from common.soc_retrieval import multi_kb_retrieve  # noqa: E402
try:
    from common.soc_retrieval import EmbeddingServiceError  # noqa: E402
except ImportError:
    class EmbeddingServiceError(RuntimeError):
        """测试桩或旧安装缺少共享异常类型时的兼容定义。"""

# LLM
from llama_index.llms.openai_like import OpenAILike  # noqa: E402


def _load_llm_config():
    cfg = resolve_runtime_llm_config("soc_answer")
    if not cfg:
        return None
    return {
        "base_url": cfg.get("base_url"),
        "api_key": cfg.get("api_key"),
        "model": cfg.get("model"),
        "context_window": cfg.get("context_window", 256000),
        "max_tokens": cfg.get("max_tokens"),
    }


def _build_llm():
    cfg = _load_llm_config()
    if not cfg or not cfg.get("base_url") or not cfg.get("api_key"):
        return None
    return OpenAILike(
        model=cfg["model"],
        api_base=cfg["base_url"],
        api_key=cfg["api_key"],
        context_window=cfg.get("context_window", 256000),
        # max_tokens 缺省为 None,让 LlamaIndex 使用其内部默认值
        max_tokens=cfg.get("max_tokens"),
        is_chat_model=True,
    )


# =====================================================================
# Markdown 答案后处理：替换 [N] 为 [N](file:// 引文 URL)
# =====================================================================


def _citation_file_uri(citation_paths: List[str], n: int) -> str:
    """第 n 条引文（1-based）的 file:// URL；越界返回空串。"""
    if 1 <= n <= len(citation_paths):
        try:
            return Path(citation_paths[n - 1]).resolve().as_uri()
        except (ValueError, OSError):
            return ""
    return ""


def _postprocess_answer(answer_str: str, citation_paths: List[str]) -> str:
    """替换 [N] 为 [N](file://...)（引文链接指向本地文件）。"""
    def replace_li_citation(match):
        try:
            n = int(match.group(1))
            url = _citation_file_uri(citation_paths, n)
            if url:
                return f" [{match.group(1)}]({url})"
            return f" [{match.group(1)}]"
        except Exception:
            return match.group(0)

    pattern_li = r'(?<![\(\[#])\[(\d+)\](?![\)\]])'
    return re.sub(pattern_li, replace_li_citation, answer_str)


def _load_product_taxonomy(agent_id: str) -> dict:
    """加载产品 taxonomy 映射表（**多 KB 版本**：从所有启用 KB 的 pd_spec_vector_library 目录聚合）。

    返回格式：{kb_id: taxonomy_dict}，每个 KB 都有自己的 taxonomy。
    """
    from common.soc_kb_registry import load_registry
    from common.soc_vector_paths import kbs_root

    registry = load_registry(agent_id=agent_id)
    result: Dict[str, dict] = {}
    for kb in registry.enabled_kbs():
        path = kbs_root(agent_id) / kb.kb_id / "pd_spec_vector_library" / "product_taxonomy.json"
        if not path.is_file():
            print(f"  KB [{kb.kb_id}] 没有 product_taxonomy.json", flush=True)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result[kb.kb_id] = data
            n_cats = len(data.get("categories", []))
            print(f"  KB [{kb.kb_id}] taxonomy 加载成功，共 {n_cats} 个分类", flush=True)
        except Exception as e:
            print(f"  KB [{kb.kb_id}] taxonomy 加载失败: {e}", flush=True)
    return result


def _llm_extract_product_scope(
    llm, req_text: str, taxonomy_by_kb: dict
) -> dict:
    """把完整 taxonomy 交给 LLM，让其自主识别用户问题涉及的产品分类（跨 KB）。

    taxonomy_by_kb: {kb_id: {"categories": [...]}}
    返回 {"matched_paths": [{"kb_id": kb, "canonical_path": path}, ...], "confidence": float, "reason": str}
    """
    # 汇总：每个 KB 一段，标注 kb_id
    kb_payload: dict = {}
    for kb_id, tax in taxonomy_by_kb.items():
        kb_payload[kb_id] = [
            {
                "category_id": c.get("category_id", ""),
                "canonical_path": c.get("canonical_path", ""),
                "aliases": c.get("aliases", []),
            }
            for c in tax.get("categories", [])
        ]
    taxonomy_json = json.dumps(kb_payload, ensure_ascii=False, indent=2)

    prompt = f"""\
你是一个产品分类识别专家。请根据用户问题和下面的产品分类表（多个 KB），判断用户问题涉及哪些产品分类。

产品分类表（按 KB 分组）：
{taxonomy_json}

用户问题：{req_text}

请输出 JSON：
{{
  "matched_paths": [
    {{"kb_id": "<kb_id>", "canonical_path": "产品A/01_概述/"}},
    {{"kb_id": "<kb_id>", "canonical_path": "产品C/"}}
  ],
  "confidence": 0.95,
  "reason": "用户提到了..."
}}

要求：
- matched_paths 中每条必须是 {{"kb_id": <kb>, "canonical_path": <path>}}：
  - kb_id 必须是产品分类表中存在的 KB 名
  - canonical_path 必须是该 KB 分类表中存在的 canonical_path
- 如果没有涉及任何产品分类，matched_paths 为空数组
- confidence 为 0-1，明确匹配时应 >= 0.7
- 不要编造产品分类表中不存在的 KB 或路径
- 多 KB 同名产品分类时，matched_paths 应分别列出（不同 kb_id）
- 当用户问题中的产品词是通用词时，请返回该通用词下**所有相关分类**（多 KB 时每个 KB 的通用词分类都列）
"""
    try:
        from llama_index.core import PromptTemplate
        resp = llm.complete(PromptTemplate(prompt).format())
        text = str(resp).strip()
        data = extract_first_json(text)
        if not isinstance(data, dict):
            print(f"LLM 产品范围提取返回非 dict: {text}", flush=True)
            return {}
        return data
    except Exception as e:
        print(f"LLM 产品范围提取失败: {e}", flush=True)
        return {}


def _keyword_extract_product_scope(
    req_text: str, taxonomy_by_kb: dict
) -> List[Tuple[str, str]]:
    """基于 taxonomy 中的 canonical_path 和 aliases 做关键词匹配（跨 KB 兜底）。

    返回 [(kb_id, canonical_path), ...]
    """
    text = req_text.lower()
    matched: List[Tuple[str, str]] = []
    for kb_id, tax in taxonomy_by_kb.items():
        for cat in tax.get("categories", []):
            canonical = cat.get("canonical_path", "")
            if not canonical:
                continue
            aliases = [canonical] + list(cat.get("aliases", []))
            for alias in aliases:
                if alias and alias.lower() in text:
                    matched.append((kb_id, canonical))
                    print(f"关键词匹配 [{kb_id}]: {canonical} (alias={alias})", flush=True)
                    break
    return matched


def _extract_product_scope(
    req_text: str, taxonomy_by_kb: dict
) -> List[Tuple[str, str]]:
    """跨 KB 产品范围提取，返回 [(kb_id, canonical_path), ...]。

    优先使用 LLM 读取完整 taxonomy 自主识别；失败或置信度低时回退关键词匹配。
    """
    if not taxonomy_by_kb:
        print("无任何 KB 的 taxonomy，跳过产品范围提取", flush=True)
        return []

    total_cats = sum(len(t.get("categories", [])) for t in taxonomy_by_kb.values())
    print(
        f"开始产品范围提取，{len(taxonomy_by_kb)} 个 KB 共 {total_cats} 个分类，问题: {req_text!r}",
        flush=True,
    )

    matched: List[Tuple[str, str]] = []
    try:
        llm = _build_llm()
        if llm is not None:
            result = _llm_extract_product_scope(llm, req_text, taxonomy_by_kb)
            print(f"LLM 提取结果: {result}", flush=True)
            confidence = float(result.get("confidence", 0) or 0)
            # 构造合法 (kb_id, canonical_path) 集合 + canonical → kb_ids 索引
            valid_pairs: set = set()
            canonical_to_kbs: Dict[str, List[str]] = {}
            for kb_id, tax in taxonomy_by_kb.items():
                for c in tax.get("categories", []):
                    canonical = c.get("canonical_path", "")
                    if canonical:
                        valid_pairs.add((kb_id, canonical))
                        canonical_to_kbs.setdefault(canonical, []).append(kb_id)

            paths = result.get("matched_paths") or []
            for item in paths:
                if not isinstance(item, dict):
                    continue
                kb_id = str(item.get("kb_id", "")).strip()
                canonical = str(item.get("canonical_path", "")).strip()
                if (kb_id, canonical) in valid_pairs:
                    matched.append((kb_id, canonical))
                    continue
                # kb_id 容错：LLM 可能写错 KB 名（如抄了 prompt 示例占位符）。
                # canonical_path 在 taxonomy 中唯一存在，或按前缀关系能定位到唯一 KB 时，自动纠正 kb_id
                candidate_kbs = canonical_to_kbs.get(canonical, [])
                corrected = ""
                if len(candidate_kbs) == 1:
                    corrected = candidate_kbs[0]
                elif kb_id:
                    prefix_hits = [
                        k for k in candidate_kbs
                        if k.startswith(kb_id) or kb_id.startswith(k)
                    ]
                    if len(prefix_hits) == 1:
                        corrected = prefix_hits[0]
                if corrected:
                    print(
                        f"kb_id 纠错: '{kb_id}' → '{corrected}' (canonical={canonical})",
                        flush=True,
                    )
                    matched.append((corrected, canonical))
                elif canonical:
                    print(
                        f"LLM 返回项无法匹配 taxonomy，已丢弃: "
                        f"kb_id={kb_id!r}, canonical={canonical!r}",
                        flush=True,
                    )

            if confidence >= 0.6 and matched:
                print(f"LLM+taxonomy 匹配范围: {matched}", flush=True)
                return matched
            elif confidence < 0.6:
                print(f"LLM 置信度 {confidence} 过低，回退关键词", flush=True)
            else:
                print("LLM 返回的路径无效或为空，回退关键词", flush=True)
        else:
            print("LLM 未配置，使用关键词规则", flush=True)
    except Exception as e:
        print(f"LLM+taxonomy 提取异常，回退关键词: {e}", flush=True)

    return _keyword_extract_product_scope(req_text, taxonomy_by_kb)


# =====================================================================
# 主流程
# =====================================================================


def _judge_compliance(llm, req_text: str, source_nodes) -> Dict[str, Any]:
    """
    调用 LLM 对需求 vs 检索到的 RAG 片段做合规判定（FC/PC/NC）。

    source_nodes: 全部检索节点（默认 15 = 10 产品规范 + 5 历史范式）。

    Returns:
        {"compliance": "FC|PC|NC",
         "remarks": str,
         "confidence": float,
         "referenced_indices": [int, ...]}
    """
    matches_raw = []
    seen_doc_keys: Dict[str, int] = {}
    next_doc_seq = 1
    for idx, item in enumerate(source_nodes, 1):
        meta = item.node.metadata or {}
        # 兜底：product_spec 节点缺少 file_name 时，ref_file 提供空串避免 NameError
        ref_file = ""
        if meta.get("_source_kind") == "product_spec":
            spec_name = Path(meta.get("file_name", "产品规范")).stem if meta.get("file_name") else "产品规范"
            f_mtime = (
                meta.get("last_modified_date", "")
                or meta.get("file_mtime", "")
                or ""
            )
            content = item.node.get_content()[:500]
            matches_raw.append(
                f"【[{idx}] 产品规范: {spec_name}】(mtime: {f_mtime or '未知'}): {content}"
            )
        else:
            ref_file = meta.get("source_file", "历史记录")
            spec_name = Path(ref_file).stem if ref_file else "历史范式"
            f_mtime = (
                meta.get("last_modified_date", "")
                or meta.get("file_mtime", "")
                or ""
            )
            comp = meta.get("compliance", "")
            created_at = meta.get("created_at", "")
            content = item.node.get_content()[:300]
            matches_raw.append(
                f"【[{idx}] 历史范式 ({ref_file})[历史合规: {comp}, created_at: {created_at or '未知'}]]: {content}"
            )

        if hasattr(item.node, "metadata") and item.node.metadata is not None:
            # 统一用 file_name stem 计算 doc_key（spec 和 paradigm 都按"文件名"分）；
            # 多 KB 时 doc_key 必须包含 kb_id，否则不同子库同名文档共享 _doc_seq，
            # 造成参考列表位置/URL 错位。
            file_name_for_key = meta.get("file_name", "") or ref_file
            kb_id = (meta.get("kb_id", "") or "").strip()
            stem = Path(file_name_for_key).stem if file_name_for_key else spec_name
            doc_key = f"file::{kb_id}::{stem}" if kb_id else f"file::{stem}"
            if doc_key not in seen_doc_keys:
                seen_doc_keys[doc_key] = next_doc_seq
                next_doc_seq += 1
            item.node.metadata["_doc_seq"] = seen_doc_keys[doc_key]
            item.node.metadata["_doc_title"] = spec_name

    matches_text = "\n\n".join(matches_raw)
    prompt = (
        "你是一个严谨的标书技术审核和应答专家。请仔细判断以下客户需求与知识库匹配到的参考文本列表是否存在本质冲突，并给出合规性判定。\n\n"
        f"待应答的客户需求：【{req_text}】\n"
        f"知识库匹配到的参考文本列表（共 {len(matches_raw)} 条，每条以 [N] 编号）：\n{matches_text}\n\n"
        "判断原则：\n"
        "1. 只要参考文本列表中有任何一项能涵盖客户需求，或者表达的核心意图一致，判定为完全合规(FC)。\n"
        "2. 如果仅能部分满足需求，判定为部分合规(PC)。\n"
        "3. 如果存在明确冲突（如品牌互斥、数值矛盾、技术路线不同等），判定为不合规(NC)。\n"
        "4. 如果需求只是通用描述，只要参考列表中有相关的通用描述，视为完全合规(FC)。\n"
        "5. **冲突检测（新增）**：如果列表中存在来自不同文档、针对同一主题但结论/数值/技术路线矛盾的片段，"
        "请在 `conflicts` 数组中列出每一条冲突。当多文档冲突时，**优先采用更新时间较新的文档**作为最终依据。\n"
        "6. **compliance 判定与 conflicts 关联（关键）**：\n"
        "   - 如果 conflicts 数组**非空**（检测到冲突），compliance 字段**必须**判为 `PC`（部分合规）\n"
        "   - 如果 conflicts 数组为空，compliance 按判断原则 1-4 正常判 FC/PC/NC\n"
        "   - **禁止**自己合理解释文档间的差异（如「实现方式不同」「非技术路线冲突」等）来给 FC\n"
        "   - 只要存在表述差异 → conflicts 非空 → compliance = PC\n"
        "请将以下 JSON 结果用 markdown 代码块包裹（必须用 ```json ... ``` 包裹，避免被后续解析器当成嵌套 JSON 误解析）：\n"
        "```json\n"
        "{\n"
        '  "compliance": "FC或PC或NC",\n'
        '  "remarks": "简短说明判定原因或应答备注，基于知识库匹配的内容,**必须**使用 [N] 格式引用原文片段编号（多条用 [N] [M]），例如：根据 [1] 描述...基于 [3] 和 [4] 的对比...；如果有冲突，必须明确说明已采用哪个版本及理由",\n'
        '  "confidence": 0到1之间的浮点数，表示你基于提供的参考文本对该应答建议的把握程度,\n'
        '  "refs": 引用的片段编号列表，如 [1, 3, 5]，引用过几条就写几条，没有引用则写 [],\n'
        '  "conflicts": [\n'
        "    {\n"
        '      "old_doc": "旧版本文档名（如文件stem名）",\n'
        '      "old_mtime": "旧文档的完整 mtime（按参考资料中的 mtime 字符串原样保留，如 2026-06-26T12:16:07；不要简化为 YYYY-MM-DD）",\n'
        '      "new_doc": "新版本文档名",\n'
        '      "new_mtime": "新文档的完整 mtime（同上要求，保留到秒）",\n'
        '      "conflict_point": "具体冲突点描述（如：最大节点数从200变更为500）",\n'
        '      "adopted": "new_doc 或 old_doc（按更新时间更优原则）"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```\n"
        "注意：JSON 中的字符串值如果需要包含双引号，请用中文「」或单引号 ' 代替双引号 \"，避免JSON 转义问题。\n"
        "如果无冲突，conflicts 字段输出空数组 []。"
    )
    try:
        from llama_index.core import PromptTemplate
        resp = llm.complete(PromptTemplate(prompt).format())
        text = str(resp).strip()
        data = extract_first_json(text)
        if data:
            refs_raw = data.get("refs", [])
            refs: List[int] = []
            if isinstance(refs_raw, list):
                for r in refs_raw:
                    if isinstance(r, bool):
                        continue
                    if isinstance(r, (int, float)):
                        refs.append(int(r))
                    elif isinstance(r, str) and r.strip().isdigit():
                        refs.append(int(r.strip()))
            return {
                "compliance": data.get("compliance", ""),
                "remarks": data.get("remarks", ""),
                "confidence": float(data.get("confidence", 0.0)) if data.get("confidence") is not None else 0.0,
                "referenced_indices": refs,
                "conflicts": data.get("conflicts", []) or [],
            }
        # LLM 返回了非 JSON 内容 / JSON 解析失败
        print(
            f"\n❌ LLM 判定错误: 合规判定模型返回非 JSON，无法解析为合规结果。原文（前 200 字符）：\n{text[:200]!r}",
            flush=True,
        )
        print(
            "❌ 当前技能 [cosightbot-soc-answer] 的合规判定步骤失效，"
            "继续运行会得到一份无合规等级/无判定理由的假应答；现在立刻终止。",
            flush=True,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"\n❌ LLM 判定错误: 合规判定调用异常: {e}",
            flush=True,
        )
        print(
            "❌ 当前技能 [cosightbot-soc-answer] 的合规判定步骤失效，"
            "现在立刻终止；请检查 LLM 服务或配置。",
            flush=True,
        )
        sys.exit(1)


def _format_compliance_banner(
    judgment: Dict[str, Any],
    req_text: str,
    chunk_to_doc: Optional[Dict[int, int]] = None,
    doc_url_map: Optional[Dict[int, str]] = None,
    doc_title_map: Optional[Dict[int, str]] = None,
) -> str:
    """把合规判定结果格式化为 markdown 顶部的摘要横幅。

    若提供 chunk_to_doc / doc_url_map / doc_title_map，会对 remarks 里的
    `[N]` 调用 `_annotate_citations_with_doc_index` 改写为
    `[参考文档 M](doc_url)`（doc-level URL + 去掉 doc_title + 去重），
    与「详细分析」段落保持一致。
    """
    comp = judgment.get("compliance", "") or "N/A"
    conf = judgment.get("confidence", 0.0) or 0.0
    remarks = judgment.get("remarks", "") or "（无）"
    conf_pct = f"{conf * 100:.0f}%"
    banner = (
        f"## 📋 应答判定\n\n"
        f"- **合规等级**: `{comp}`\n"
        f"- **置信度**: `{conf:.2f}` ({conf_pct})\n"
        f"- **判定理由**: {remarks}\n\n"
        f"---\n\n"
        f"## 📖 详细分析\n\n"
    )
    if chunk_to_doc:
        banner = _annotate_citations_with_doc_index(
            banner, chunk_to_doc, doc_url_map, doc_title_map,
        )
    return banner


def _build_doc_title_map(source_nodes) -> Dict[int, str]:
    """
    构造 {doc_seq: doc_title} 映射。

    从源节点 metadata 临时标注的 _doc_seq、_doc_title 字段读出。
    """
    title_map: Dict[int, str] = {}
    seen_doc: set = set()
    for nws in source_nodes:
        meta = nws.node.metadata or {}
        doc_seq_val = meta.get("_doc_seq", "")
        doc_title = meta.get("_doc_title", "")
        if not doc_seq_val or not doc_title:
            continue
        try:
            doc_seq = int(doc_seq_val)
        except (TypeError, ValueError):
            continue
        if doc_seq in seen_doc:
            continue
        seen_doc.add(doc_seq)
        title_map[doc_seq] = doc_title
    return title_map


def _annotate_citations_with_doc_index(
    text: str,
    chunk_to_doc: Dict[int, int],
    doc_url_map: Optional[Dict[int, str]] = None,
    doc_title_map: Optional[Dict[int, str]] = None,
) -> str:
    """
    改写 [N] 为 [参考文档 M](doc_url)（doc-level URL + 去重）

    要点：
    1. **doc-level URL**：URL 来自 `doc_url_map[M]`，不再是 chunk URL。
       点击「参考文档 M」跳到的是该 doc 在末尾「📚 参考文档」段对应的
       条目 URL（包含该 doc 的多个切片合并内容），不是某个具体 chunk。
    2. **相邻相同引用去重**：多个 chunk 引用同一 doc 时，正文里只显示
       一次 `[参考文档 M](url)`。

    M 来自 chunk_to_doc[N]。
    """
    if not text or not chunk_to_doc:
        return text

    # 预处理：把 "Source 4"、"参考 9"、"来源 5" 这种裸数字加上方括号
    def _add_brackets_for_known_chunks(match):
        n = int(match.group(2))
        if n in chunk_to_doc:
            return f"{match.group(1)} [{n}]"
        return match.group(0)
    text = re.sub(r"(Source|参考|来源)\s+(\d+)", _add_brackets_for_known_chunks, text)

    # 预处理：纯裸数字加方括号
    def _add_brackets_for_bare_numbers(match):
        n = int(match.group(1))
        if n in chunk_to_doc:
            return f"[{n}]"
        return match.group(0)
    text = re.sub(r"(?<![\[\d/.:-])\b(\d{1,3})\b(?!\d|/|\.|:|-|\))", _add_brackets_for_bare_numbers, text)

    # 剥除 [N]（属于文档 M ...） 形式（避免重复）
    text = re.sub(
        r"\[(\d+)\]\s*[（\(]属于文档[^\)）]*[）\)]",
        r"[]",
        text,
    )

    # 改写 [N] → [参考文档 M](doc_url)
    pattern = re.compile(r"\[(\d+)\]")

    def repl(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        if n not in chunk_to_doc:
            return m.group(0)
        doc_seq = chunk_to_doc[n]
        doc_url = (doc_url_map or {}).get(doc_seq, "")
        if doc_url:
            return f"[参考文档 {doc_seq}]({doc_url})"
        return f"[参考文档 {doc_seq}]"

    text = pattern.sub(repl, text)

    # 合并相邻相同的 [参考文档 M] 引用，反复应用直到没有相邻重复
    dedup_pattern = re.compile(
        r"(\[参考文档\s+\d+\](?:\([^)]*\))?)(\s*)\1"
    )
    while dedup_pattern.search(text):
        text = dedup_pattern.sub(r"\1\2", text)

    return text


def _normalize_mtime(meta_or_s, fallback_path: str = "") -> str:
    """归一化 mtime 为 YYYY-MM-DD HH:MM:SS。"""
    if isinstance(meta_or_s, dict):
        raw = meta_or_s.get("last_modified_date", "") or meta_or_s.get("file_mtime", "")
        if raw and ("T" in raw or " " in raw):
            return raw.replace("T", " ", 1) if "T" in raw else raw
        candidate = meta_or_s.get("file_path", "") or fallback_path
        if candidate and Path(candidate).is_file():
            try:
                import datetime as _dt
                ts = Path(candidate).stat().st_mtime
                return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, ValueError):
                pass
        return raw or ""
    s = meta_or_s
    if not s or "T" not in s:
        return s
    if "." in s:
        s = s.split(".")[0]
    return s


def _extract_mtime_by_kind(meta: Dict[str, Any], fallback_path: str = "") -> str:
    """按 _source_kind 选时间字段：

      - 产品规范（product_spec）：显示资料修改时间 → last_modified_date / file_mtime
      - 历史范式（paradigm）    ：显示入库时间       → created_at

    返回 YYYY-MM-DD HH:MM:SS；字段都没有时返回空串（调用方显示「未知」）。
    """
    if not meta:
        return ""

    source_kind = meta.get("_source_kind", "paradigm")

    if source_kind == "product_spec":
        raw = meta.get("last_modified_date", "") or meta.get("file_mtime", "")
        if raw and ("T" in raw or " " in raw):
            return raw.replace("T", " ", 1) if "T" in raw else raw
        candidate = (meta.get("file_path", "") or "").strip() or fallback_path
        if candidate and Path(candidate).is_file():
            try:
                import datetime as _dt
                ts = Path(candidate).stat().st_mtime
                return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OSError, ValueError):
                pass
        return raw or ""

    # paradigm（历史范式）：用 created_at 入库时间
    raw = (
        meta.get("created_at", "")
        or meta.get("creation_time", "")
        or meta.get("入库时间", "")
        or meta.get("last_modified_date", "")  # 极少数老数据兜底
        or ""
    )
    if not raw:
        return ""
    # 归一化：T 改空格 + 去微秒
    if "T" in raw:
        raw = raw.split("T")[0] + " " + raw.split("T")[1]
    if "." in raw:
        raw = raw.split(".")[0]
    return raw.strip()


def _format_conflict_warning(
    conflicts: List[Dict[str, Any]],
    reranked: Optional[List[Any]] = None,
    chunk_to_doc: Optional[Dict[int, int]] = None,
    doc_url_map: Optional[Dict[int, str]] = None,
) -> str:
    """
    输出冲突检测的结构化列表。

    - 不使用表格语法（HTML / markdown / Unicode 字符画）—— 用户的渲染器
      不一定能渲染这些，且容易被 agent 包进代码块
    - 用 `**冲突 #N**` + 加粗字段 + 列表项，任何文本渲染器都正常显示
    - 冲突点文本里的 `[N]` chunk 索引会被 `_annotate_citations_with_doc_index`
      改写为 `[参考文档 M](url)`（与正文引文一致）
    """
    if not conflicts:
        return ""

    # 构建文件查找表（用 reranked 节点查完整 mtime，做 fallback）
    file_lookup: Dict[str, Dict[str, Any]] = {}
    if reranked:
        for n in reranked:
            meta = n.node.metadata or {}
            file_name = meta.get("file_name", "")
            file_path = meta.get("file_path", "")
            if file_name:
                for key in [file_name, Path(file_name).stem, file_path]:
                    if key:
                        file_lookup[key] = meta

    lines = [
        "<!--CONFLICT-START-->",
        "## ⚠️ 知识库冲突提示",
        "",
        f"本次应答检测到 **{len(conflicts)} 处**多源文档冲突。系统已**优先采用更新时间较新的版本**，请知悉以下差异：",
        "",
    ]
    for i, c in enumerate(conflicts, 1):
        old_doc = c.get("old_doc", "?")
        old_mtime = c.get("old_mtime", "?")
        new_doc = c.get("new_doc", "?")
        new_mtime = c.get("new_mtime", "?")
        point = c.get("conflict_point", "未描述")
        adopted = c.get("adopted", "new_doc")

        # mtime T 改空格（避免下游 LLM 简化）
        if isinstance(old_mtime, str) and "T" in old_mtime:
            old_mtime = old_mtime.replace("T", " ", 1)
        if isinstance(new_mtime, str) and "T" in new_mtime:
            new_mtime = new_mtime.replace("T", " ", 1)

        # mtime fallback（查文件实际 mtime）
        if old_mtime == "?" or "T" not in (old_mtime or ""):
            old_meta = file_lookup.get(old_doc) or file_lookup.get(
                Path(old_doc).stem if old_doc else ""
            )
            if old_meta:
                full = _normalize_mtime(old_meta)
                if full:
                    old_mtime = full
        if new_mtime == "?" or "T" not in (new_mtime or ""):
            new_meta = file_lookup.get(new_doc) or file_lookup.get(
                Path(new_doc).stem if new_doc else ""
            )
            if new_meta:
                full = _normalize_mtime(new_meta)
                if full:
                    new_mtime = full

        # 冲突点文本里的 [N] chunk 索引 → [参考文档 M](url)
        if chunk_to_doc:
            point = _annotate_citations_with_doc_index(
                point, chunk_to_doc, doc_url_map
            )

        lines.append(f"**冲突 #{i}**")
        lines.append(f"- **冲突点**: {point}")
        if adopted == "new_doc" or adopted == new_doc:
            lines.append(f"- **旧版本**: {old_doc}（{old_mtime}）")
            lines.append(f"- **新版本（已采用 ✓）**: 📄 **{new_doc}**（{new_mtime}）")
        else:
            lines.append(f"- **旧版本（已采用 ✓）**: 📄 **{old_doc}**（{old_mtime}）")
            lines.append(f"- **新版本**: {new_doc}（{new_mtime}）")
        lines.append("")  # 空行分隔

    lines.append("<!--CONFLICT-END-->")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n"


def _extract_section(meta: Dict[str, Any]) -> str:
    """从源节点 metadata 提取章节名。

    支持以下 header_path 格式：
      - "/H1/H2/H3"           → 返回 "H2 / H3"（parts[1:]）
      - "/H1/ /H2/H3"          → 返回 "H2 / H3"（跳过空段）
      - "H1/H2/H3"（无前后斜杠）→ 同样返回 "H2 / H3"
      - "" / None              → fallback 到 chapter_title
    """
    header_path = (meta.get("header_path", "") or "").replace("\n", " ").replace("\r", "").strip()
    chapter_title = (meta.get("chapter_title", "") or "").strip()
    source_kind = meta.get("_source_kind", "paradigm")
    if source_kind != "product_spec":
        return ""
    parts = []
    if header_path:
        for p in header_path.split("/"):
            p_clean = p.strip().lstrip("#").strip()
            if p_clean:
                parts.append(p_clean)
    # 跳过第一段（通常是文档名 / H1），其余就是章节路径
    chapter_parts = parts[1:] if parts else []
    if chapter_parts:
        return " / ".join(chapter_parts)
    if chapter_title:
        _ct = chapter_title.lstrip("#").strip()
        if _ct and (not parts or _ct != parts[0]):
            return _ct
    return ""


def _extract_doc_title_from_filename(file_name: str, source_kind: str = "product_spec") -> str:
    """处理文件名的"显示标题"。

      - product_spec：文件名遵循 "前缀 - 真名.xlsx" 命名约定
          例 "01 - 应标问题库 V2.1.docx" → 取 "应标问题库 V2.1"
      - paradigm：文件名里的 " - " 是真实内容分隔符，不是命名约定，
          必须保留完整文件名，不能用 " - " 切
    """
    _stem = Path(file_name).stem if file_name else "未命名"
    # 只有 product_spec 才应用 " - " 分割；paradigm 保留完整 stem
    if source_kind == "product_spec" and " - " in _stem:
        return _stem.rsplit(" - ", 1)[-1].strip() or _stem
    return _stem


def _resolve_doc_filename(meta: Dict[str, Any]) -> str:
    """从 metadata 提取文档文件名（spec 和 paradigm 字段来源不同）。

    字段优先级：
      通用：
        1. file_name
        2. file_path 取 basename
      paradigm 专用（file_name / file_path 都为空时的兜底）：
        3. header_path 最后一段
        4. source_path 取 basename
        5. source_file

    返回：文件名（不含路径）。完全没有时返回空串。
    """
    if not meta:
        return ""

    file_name = (meta.get("file_name", "") or "").strip()
    if file_name:
        return file_name

    file_path = (meta.get("file_path", "") or "").strip()
    if file_path:
        return Path(file_path).name

    source_kind = meta.get("_source_kind", "paradigm")
    if source_kind == "paradigm":
        header_path = (meta.get("header_path", "") or "").strip()
        if header_path:
            normalized = header_path.replace("\\", "/")
            parts = [p.strip() for p in normalized.split("/") if p.strip()]
            if parts:
                return parts[-1]
        source_path = (meta.get("source_path", "") or "").strip()
        if source_path:
            return Path(source_path).name
        source_file = (meta.get("source_file", "") or "").strip()
        if source_file:
            return source_file

    return ""


def _compute_node_url(
    idx: int,
    nws: Any,
    citation_paths: List[str],
    source_url_map: Dict[str, str],
    paradigm_merged_paths: Optional[Dict[Tuple[str, str], str]],
    spec_merged_paths: Optional[Dict[Tuple[str, str, str], str]],
) -> str:
    """计算单个 source node 的 doc-level URL（与 _build_source_list_section 同一逻辑）。

    URL 优先级（citation_writer 返回的映射值均为 file:// 完整 URL，直接使用）：
      1. spec_merged_paths[kb_id, file_path, section] - spec section 合并 URL
      2. source_url_map[file_path] - 整文件 URL
      3. paradigm_merged_paths[kb_id, source_path/source_file] - paradigm 合并 URL
      4. citations/N.md 的 file:// URL - 单 chunk fallback
    """
    meta = nws.node.metadata or {}
    file_path = (meta.get("file_path", "") or "").strip()
    source_kind = meta.get("_source_kind", "paradigm")
    kb_id = (meta.get("kb_id", "") or "").strip()

    section = ""
    if source_kind == "product_spec":
        section = _extract_section(meta)

    if source_kind == "product_spec" and file_path and section:
        spec_merged_key = (kb_id, file_path, section)
        url = (spec_merged_paths or {}).get(spec_merged_key, "")
        if url:
            return url

    if file_path and source_url_map.get(file_path):
        return source_url_map[file_path]

    paradigm_fp = (
        (meta.get("source_path", "") or "").strip()
        or (meta.get("source_file", "") or "").strip()
    )
    paradigm_key = (kb_id, paradigm_fp) if paradigm_fp else None
    if paradigm_key:
        url = (paradigm_merged_paths or {}).get(paradigm_key, "")
        if url:
            return url

    return _citation_file_uri(citation_paths, idx)


def _build_source_list_section(
    source_nodes,
    citation_paths: List[str],
    source_url_map: Dict[str, str],
    *,
    paradigm_merged_paths: Optional[Dict[Tuple[str, str], str]] = None,
    spec_merged_paths: Optional[Dict[Tuple[str, str, str], str]] = None,
) -> str:
    """
    构造 markdown 末尾的"参考文档"列表（doc 级别，按 doc_title + section + kb_id 去重）。

    形如：
        <!--SOURCE-LIST-START-->
        <!-- ⚠️ 参考文档列表：用户判断答案可信度的关键证据，保留所有条目 -->
        ## 📚 参考文档

        1. **[📄 产品规范]** [应标问题库 V2.1 - 章节X](file://...) — 修改时间: ... — 相似度: 0.85
        2. **[📜 历史范式]** [历史应答](file://...) — 修改时间: ... — 相似度: 0.72
        ...
        <!--SOURCE-LIST-END-->
    """
    if not source_nodes or not citation_paths:
        return ""

    lines: List[str] = [
        "\n\n---\n\n",
        "<!--SOURCE-LIST-START-->\n",
        "<!-- ⚠️ 参考文档列表：用户判断答案可信度的关键证据，保留所有条目，禁止简化/删除/重排 -->\n",
        "## 📚 参考文档\n\n",
        "> **重要提示**：以下是本次应答检索到的全部参考文档，**严禁**简化、删除或重排。\n\n",
    ]

    seen = {}
    for idx, nws in enumerate(source_nodes, 1):
        meta = nws.node.metadata or {}
        file_path = (meta.get("file_path", "") or "").strip()
        # paradigm 节点没有 file_name / file_path：从 header_path/source_path/source_file 取
        file_name = _resolve_doc_filename(meta) or "未命名"
        source_kind = meta.get("_source_kind", "paradigm")
        doc_title = _extract_doc_title_from_filename(file_name, source_kind=source_kind)
        section = _extract_section(meta)
        # 产品规范显示资料修改时间；历史范式显示入库时间（created_at）
        f_mtime = _extract_mtime_by_kind(meta, file_path)
        if not f_mtime and source_kind == "product_spec" and file_path and Path(file_path).is_file():
            try:
                import datetime as _dt
                f_mtime = _dt.datetime.fromtimestamp(
                    Path(file_path).stat().st_mtime
                ).strftime("%Y-%m-%dT%H:%M:%S")
            except OSError:
                f_mtime = ""
        # 链接优先级（映射值均为 file:// 完整 URL）
        kb_name = (meta.get("kb_name", "") or "").strip()
        kb_id = (meta.get("kb_id", "") or "").strip()
        # 多 KB 下合并引文 key 包含 kb_id，避免不同子库的同名同章节文档串内容
        spec_merged_key = (
            (kb_id, file_path, section)
            if (file_path and section and source_kind == "product_spec")
            else None
        )
        if spec_merged_key and spec_merged_paths and spec_merged_paths.get(spec_merged_key):
            url = spec_merged_paths[spec_merged_key]
        elif file_path and source_url_map and source_url_map.get(file_path):
            url = source_url_map[file_path]
        else:
            paradigm_fp = (
                (meta.get("source_path", "") or "").strip()
                or (meta.get("source_file", "") or "").strip()
            )
            paradigm_key = (kb_id, paradigm_fp) if paradigm_fp else None
            if paradigm_key and paradigm_merged_paths and paradigm_merged_paths.get(paradigm_key):
                url = paradigm_merged_paths[paradigm_key]
            else:
                url = _citation_file_uri(citation_paths, idx)

        if source_kind == "product_spec":
            type_label = f"📄 {kb_name} [KB]" if kb_name else "📄 产品规范"
        else:
            type_label = f"📜 {kb_name} [KB]" if kb_name else "📜 历史范式"
        if "vector_score" in meta:
            similarity = float(meta["vector_score"])
        else:
            similarity = float(getattr(nws, "score", 0.0) or 0.0)

        key = (doc_title, section, kb_id)
        if key not in seen:
            seen[key] = {
                "doc_title": doc_title, "section": section,
                "file_mtime": f_mtime, "url": url,
                "type_label": type_label, "similarity": similarity,
            }
        else:
            if not seen[key]["url"] and url:
                seen[key]["url"] = url
            if not seen[key]["file_mtime"] and f_mtime:
                seen[key]["file_mtime"] = f_mtime
            if similarity > seen[key]["similarity"]:
                seen[key]["similarity"] = similarity

    for i, entry in enumerate(seen.values(), 1):
        title = entry["doc_title"]
        section = entry["section"]
        mtime = entry["file_mtime"] or "未知"
        url = entry["url"]
        type_label = entry["type_label"]
        similarity = entry["similarity"]

        if section and section != title:
            full_title = f"{title} - {section}"
        else:
            full_title = title

        sim_str = f"{similarity:.2f}" if similarity > 0 else "未知"

        if url:
            lines.append(
                f"{i}. **{type_label}** [{full_title}]({url}) — 修改时间: {mtime} — 相似度: {sim_str}\n"
            )
        else:
            lines.append(
                f"{i}. **{type_label}** {full_title} — 修改时间: {mtime} — 相似度: {sim_str}\n"
            )

    lines.append("\n<!--SOURCE-LIST-END-->\n")
    return "".join(lines)


def respond_single(
    agent_id: str,
    req_text: str,
    *,
    product_scope: str = "",
    msg_sn: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检索 + 排序（spec +0.15）+ **应答判定** + 合成（Markdown）+ 引文。

    product_scope: 产品范围（产品名或分类路径，如 "某产品A" 或 "某领域/某产品A"）。
        非空时先匹配产品分类表、只在该分类下检索产品规范；
        为空时全局检索（默认）。由技能调用方根据用户意图决定是否传入。
    """
    if not msg_sn:
        msg_sn = str(uuid.uuid4())

    # 0. 提取产品范围（跨 KB：每个 KB 各自的 taxonomy 合并给 LLM）
    # 门禁：仅在调用方显式传入 product_scope 时启用产品分类过滤；
    # 否则直接全局搜索，避免 LLM 从需求正文猜产品导致误过滤。
    taxonomy_by_kb = _load_product_taxonomy(agent_id)
    matched_scopes: List[Tuple[str, str]] = []  # [(kb_id, canonical_path)]
    if not product_scope:
        print("未指定 product_scope，走全局搜索", flush=True)
    elif not taxonomy_by_kb:
        print("未找到任何 KB 的 product_taxonomy.json，走全局搜索", flush=True)
    else:
        print(f"指定产品范围: {product_scope!r}，开始匹配产品分类", flush=True)
        matched_scopes = _extract_product_scope(product_scope, taxonomy_by_kb)
        if matched_scopes:
            print(f"提取到产品范围: {matched_scopes}", flush=True)
        else:
            print(
                f"指定范围 {product_scope!r} 未匹配到任何产品分类，回退全局搜索",
                flush=True,
            )

    # 把 [(kb_id, canonical_path)] 转成 spec_path_prefix 列表（带 KB 前缀）
    spec_path_prefixes: List[str] = []
    for kb_id, path in matched_scopes:
        spec_path_prefixes.append(f"{kb_id}::{path}")

    # 1. SOC 检索（多 KB 模式：遍历所有启用 KB 的 spec + paradigm，spec +0.15 加成）
    print(f"开始检索，product_spec_path_prefix={spec_path_prefixes}", flush=True)
    raw_nodes = multi_kb_retrieve(
        agent_id=agent_id,
        query_text=req_text,
        top_spec=10,
        top_paradigm=5,
        scopes=None,
        spec_path_prefix=spec_path_prefixes or None,
    )
    print(f"检索完成，召回 {len(raw_nodes)} 条原始节点", flush=True)

    if not raw_nodes:
        # 按产品分类召回时未命中，需明确告知检索范围，便于用户判断是
        # "该产品确实不支持"还是"范围限定过窄"
        scope_note = ""
        if matched_scopes:
            scope_lines = "\n".join(
                f"- 知识库 `{kb}` → 产品分类 `{path}`" for kb, path in matched_scopes
            )
            scope_note = (
                "\n\n> 🔎 **检索范围**：本次应答按产品分类过滤，仅在以下范围召回：\n"
                f"{scope_lines}\n"
                "> 未命中可能与范围限定有关，可考虑去掉范围限定后全局重试。"
            )
        return {
            "requirement": req_text,
            "product_scopes": [
                {"kb_id": kb, "canonical_path": path} for kb, path in matched_scopes
            ],
            "markdown": f"## 📋 应答判定\n\n- **合规等级**: `N/A`\n- **置信度**: `0.00` (0%)\n- **判定理由**: 未命中知识库{scope_note}\n\n---\n\n## 📖 详细分析\n\n未命中知识库。{scope_note}",
            "source_count": 0,
            "top_score": 0.0,
            "answer_path": "",
            "compliance": "N/A",
            "confidence": 0.0,
        }

    # 2. 排序：直接按 vector_score + 0.15（spec）排序，不做二次重排。
    # - spec: vector_score 由检索层 BGE 重排保留（原始 cosine sim）
    # - paradigm: 没走 BGE，node.score 就是原始 cosine sim，回退到 node.score
    def _spec_sort_key(nws):
        meta = nws.node.metadata or {}
        if "vector_score" in meta:
            base = float(meta["vector_score"])
        else:
            base = float(getattr(nws, "score", 0.0) or 0.0)
        is_spec = meta.get("_source_kind") == "product_spec"
        return base + (0.15 if is_spec else 0.0)

    reranked = sorted(raw_nodes, key=_spec_sort_key, reverse=True)

    # 3. 准备 LLM（合成 + 应答判定共用）
    # LLM 配置缺失 = 没法合成应答也没法做合规判定，整份输出会变成"未命中知识库"的占位
    # 但用户看到 N 条检索命中后会误以为已经作答 → 立刻终止。
    llm = _build_llm()
    if llm is None:
        print(
            "\n❌ LLM 配置错误: 未找到可用的大模型配置，无法构造大模型客户端。",
            flush=True,
        )
        print(
            "❌ 当前技能 [cosightbot-soc-answer] 无法合成应答/做合规判定；"
            "请在 data/.env 中配置 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL"
            "（或 OPENAI_* 回退）后重试。",
            flush=True,
        )
        sys.exit(1)

    # 4. 应答判定（FC/PC/NC + confidence）
    # 用 reranked（按 vector_score + 0.15 if spec 排序后的 15 条），
    # 与合成阶段输入保持一致，LLM 看到的就是最终引文顺序。
    judgment = _judge_compliance(llm, req_text, reranked)

    # 5. 合成详细分析 Markdown
    prompt_dump_dir = cosight_state_root() / "canvas" / "deep-search" / agent_id / msg_sn
    response = synthesize_cited_answer(
        query_text=req_text,
        source_nodes=reranked,
        llm=llm,
        prompt_dump_dir=prompt_dump_dir,
    )

    # 6. 源文件暂存 + 引文
    source_url_map, assets_url_map = stage_source_files(
        agent_id, msg_sn, response.source_nodes
    )
    citation_paths = save_citations(
        agent_id, msg_sn, req_text, response.source_nodes,
        source_url_map=source_url_map,
        assets_url_map=assets_url_map,
        # SOC 场景:lancedb 由本地构建,metadata.file_path 指向构建时源目录的
        # 预处理 .md;若源目录已移动,save_citations 会经 _kb_relative_path
        # 裁剪为 KB 内相对路径,不再有误导性,让 Metadata 段显示相对路径定位文档。
        hide_file_path=False,
    )
    # 6b. 历史范式按文件合并（paradigm 是 .xlsx，stage_source_files 不暂存；
    #     这里把同文件多段合并写一个 citations/paradigm_{hash}.md，让参考列表链接到完整内容）
    paradigm_merged_paths = save_merged_paradigm_citations(
        agent_id, msg_sn, response.source_nodes,
    )
    # 6c. 产品规范按章节合并（同文件同章节多段 → 1 个 .md，
    #     让"参考文档"链接点进去看到的是该 section 的合并内容，不是整个文件）
    spec_merged_paths = save_merged_spec_citations(
        agent_id, msg_sn, response.source_nodes,
    )

    # 7. 拼接 markdown：应答横幅 + 详细分析 + 后处理 + 参考文档列表
    detail_body = str(response)
    detail_body = _postprocess_answer(detail_body, citation_paths)
    doc_title_map = _build_doc_title_map(response.source_nodes)

    # 构造参考列表的 (doc_title, section, kb_id) -> 位置 映射，
    # 引文标注 [参考文档 M] 中的 M 是参考列表的实际位置而不是 _doc_seq
    # （_doc_seq 跟参考列表位置可能不一致）；
    # 多 KB 时去重 key 必须包含 kb_id，否则不同子库的同名文档会合并。
    ref_list_positions: Dict[Tuple[str, str, str], int] = {}
    pos = 0
    for _nws in response.source_nodes:
        _meta = _nws.node.metadata or {}
        _source_kind = _meta.get("_source_kind", "paradigm")
        _file_name = _resolve_doc_filename(_meta) or "未命名"
        _doc_title = _extract_doc_title_from_filename(_file_name, source_kind=_source_kind)
        _section = _extract_section(_meta)
        _kb_id = (_meta.get("kb_id", "") or "").strip()
        _key = (_doc_title, _section, _kb_id)
        if _key not in ref_list_positions:
            pos += 1
            ref_list_positions[_key] = pos

    # 构造 _doc_seq -> 参考列表位置 的映射
    doc_seq_to_ref_pos: Dict[int, int] = {}
    for _nws in response.source_nodes:
        _meta = _nws.node.metadata or {}
        _source_kind = _meta.get("_source_kind", "paradigm")
        _file_name = _resolve_doc_filename(_meta) or "未命名"
        _doc_title = _extract_doc_title_from_filename(_file_name, source_kind=_source_kind)
        _section = _extract_section(_meta)
        _kb_id = (_meta.get("kb_id", "") or "").strip()
        _doc_seq = _meta.get("_doc_seq")
        if _doc_seq is not None and _doc_seq not in doc_seq_to_ref_pos:
            ref_pos = ref_list_positions.get((_doc_title, _section, _kb_id))
            if ref_pos:
                doc_seq_to_ref_pos[_doc_seq] = ref_pos

    # 从 source_nodes metadata 读 _doc_seq，翻译成参考列表位置
    chunk_to_doc_map = {
        idx: doc_seq_to_ref_pos.get(nws.node.metadata["_doc_seq"], nws.node.metadata["_doc_seq"])
        for idx, nws in enumerate(response.source_nodes, 1)
        if nws.node.metadata.get("_doc_seq") is not None
    }

    # 构造 doc_url_map —— 参考列表位置 -> 该 doc 的 URL
    # 点击正文里「参考文档 M」就跳到这一个 URL，看到的是该 doc 的合并内容
    doc_url_map: Dict[int, str] = {}
    for idx, nws in enumerate(response.source_nodes, 1):
        ref_pos = doc_seq_to_ref_pos.get(nws.node.metadata.get("_doc_seq"))
        if ref_pos is None or ref_pos in doc_url_map:
            continue
        url = _compute_node_url(
            idx, nws, citation_paths, source_url_map,
            paradigm_merged_paths, spec_merged_paths,
        )
        if url:
            doc_url_map[ref_pos] = url

    detail_body = _annotate_citations_with_doc_index(
        detail_body, chunk_to_doc_map, doc_url_map, doc_title_map,
    )

    source_list = _build_source_list_section(
        response.source_nodes, citation_paths, source_url_map,
        paradigm_merged_paths=paradigm_merged_paths,
        spec_merged_paths=spec_merged_paths,
    )

    # 把强制保留规则用 HTML 注释塞到工具输出最顶部
    _PRESERVATION_RULES = """\
<!--
================================================================
AGENT 必读保留规则（HTML 注释，渲染时对用户不可见）

下面是要给用户的最终回答。**你（agent）只做总结、加上下文、排版**，
但以下 3 个强制项必须原样保留到最终回答里：

✅ 强制保留 1：**冲突提示**（`## ⚠️ 知识库冲突提示` 段）
- 格式是**结构化列表**（`**冲突 #N**` + 加粗字段 + 列表项），**不是表格**
- **不要**包进 ` ``` ` 代码块（**是**列表不是代码）
- **不要**改成任何表格格式（markdown / HTML / Unicode 字符画）
- **不要**简化 / 删除 / 重排任何条目
- **不要**简化文档名（保留完整文件名）
- **不要**简化秒级时间戳（保留 `2026-06-25 19:34:07` 完整）
- **不要**简化 `📄` emoji / `**粗体**` / `（mtime）` 全角括号
- **不要**简化 `✓` 标记

✅ 强制保留 2：**判定理由**（`## 📋 应答判定` 段里的 `- **判定理由**`）
- **必须**含 `[参考文档 M](url)` 引文标注（说明这条判断的依据是哪条片段）
- **不要**简化为 `参考文档 M`（丢 URL，无法点击跳转）
- **不要**简化为裸数字 `[1]` / `Source 1` / `5 9 10`
- **不要**去掉 URL
- **不要**加 doc_title

✅ 强制保留 3：**详细分析**（`## 📖 详细分析` 段）
- **必须**保留所有 `[参考文档 M](url)` 引文标注
- 同 强制保留 2 的规则

✅ 强制保留 4：**末尾「📚 参考文档」段**
- **不要**删除任何条目
- **不要**简化文档名为"产品规范""历史范式"
- **不要**简化秒级时间戳
- **不要**改 markdown 链接 `[title](url)` 为纯文本

**判定理由和详细分析的引文标注特别重要**：用户需要知道每条判断的依据来自哪个片段，**不能**省略。

总结时如果丢掉这 4 项 = 输出失败。请原样保留。
================================================================
-->

"""

    # 检索范围提示：仅在按产品分类召回（--product-scope 生效）时生成，
    # 让 agent 最终总结时明确告知用户"在哪些知识库的哪些产品分类下召回的"
    scope_banner = ""
    if matched_scopes:
        scope_lines = "\n".join(
            f"> - 知识库 `{kb}` → 产品分类 `{path}`" for kb, path in matched_scopes
        )
        scope_banner = (
            "> 🔎 **检索范围**：本次应答按产品分类过滤，"
            "仅在以下知识库的产品分类下召回：\n"
            f"{scope_lines}\n\n"
        )
        _PRESERVATION_RULES = _PRESERVATION_RULES.replace(
            "-->",
            """\
✅ 强制保留 0：**检索范围提示**（回答开头的 `> 🔎 **检索范围**` 引用块）
- **必须**在最终总结中原样保留该段，明确告知用户本次应答是在哪些知识库的哪些产品分类下召回的
- **不要**删除、改写或弱化该段

-->
""",
            1,
        )

    final_markdown = (
        _PRESERVATION_RULES
        + scope_banner
        + _format_conflict_warning(
            judgment.get("conflicts", []), reranked,
            chunk_to_doc=chunk_to_doc_map,
            doc_url_map=doc_url_map,
        )
        + _format_compliance_banner(
            judgment, req_text,
            chunk_to_doc=chunk_to_doc_map,
            doc_url_map=doc_url_map,
            doc_title_map=doc_title_map,
        )
        + detail_body
        + source_list
    )

    # 落地完整 markdown 到 canvas 目录（data/canvas/deep-search/<agent>/<msg_sn>/output.md），
    # 汇总时给出 "可点击查看完整应答" 的 file:// 链接，
    # 避免长 markdown 在上下文截断导致摘要 / 引用失真。
    canvas_root = cosight_state_root() / "canvas" / "deep-search" / agent_id / msg_sn
    canvas_root.mkdir(parents=True, exist_ok=True)
    output_md_path = canvas_root / "output.md"
    output_md_path.write_text(final_markdown, encoding="utf-8")
    canvas_output_url = output_md_path.resolve().as_uri()

    # 字段顺序敏感：小字段必须全部放在巨大的 markdown 字段之前，
    # 避免上下文截断丢掉 canvas_output_url 等关键小字段。
    return {
        "canvas_output_url": canvas_output_url,
        "msg_sn": msg_sn,
        "compliance": judgment.get("compliance", ""),
        "confidence": float(judgment.get("confidence", 0.0) or 0.0),
        "conflicts": judgment.get("conflicts", []),
        "product_scopes": [
            {"kb_id": kb, "canonical_path": path} for kb, path in matched_scopes
        ],
        "source_count": len(response.source_nodes),
        "top_score": float(max((getattr(n, "score", 0.0) for n in response.source_nodes), default=0.0)),
        "answer_path": str(Path(citation_paths[0]).parent) if citation_paths else "",
        "requirement": req_text,
        # 完整 markdown 永远放最后：即使被截断，丢的也只是它
        # （完整内容本就在 canvas_output_url 指向的 output.md 里）。
        "markdown": final_markdown,
    }


# =====================================================================
# CLI
# =====================================================================


def main():
    parser = argparse.ArgumentParser(description="单条需求智能应答器（Markdown 输出）")
    parser.add_argument("req_text", help="待应答的需求文本")
    parser.add_argument("--agent-id", default=SOC_AGENT_ID,
                        help=f"智能体 ID（默认 {SOC_AGENT_ID}，一般无需传入）")
    parser.add_argument(
        "--product-scope",
        default="",
        help="产品范围（产品名或分类路径，如 '某产品A' 或 '某领域/某产品A'）。"
        "仅在用户明确要求限定在某个产品范围内应答时传入；"
        "不传则对所有产品分类全局检索（默认）。",
    )
    args = parser.parse_args()

    # 本地就绪校验：知识库由 cosightbot-soc-kb-build 本地构建（无云端同步）。
    # 未就绪 → 立刻终止（零兜底：不输出任何"看起来已应答"的占位 markdown）。
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
            "❌ 当前技能 [cosightbot-soc-answer] 无法继续。",
            flush=True,
        )
        sys.exit(1)

    print(f"Current Agent: {args.agent_id}", flush=True)

    try:
        result = respond_single(
            agent_id=args.agent_id,
            req_text=args.req_text,
            product_scope=args.product_scope,
        )
    except EmbeddingServiceError as e:
        print(f"\n❌ 向量模型调用失败: {e}", flush=True)
        print(
            "❌ 当前技能 [cosightbot-soc-answer] 已立即停止，未生成应答结果；"
            "请检查 Embedding 服务（COSIGHTBOT_EMBEDDING_API_URL）和网络后重试。",
            flush=True,
        )
        sys.exit(1)
    # 直接打印 markdown，不输出 JSON
    print(result["markdown"])


if __name__ == '__main__':
    main()
