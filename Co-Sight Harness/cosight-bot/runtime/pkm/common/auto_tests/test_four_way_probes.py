#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""底座-B1 四路并发探针单测：长文深层召回、短语防误杀、区间合并、闭合顺延。"""
from __future__ import annotations

import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from common.dynamic_overview import engine as engine_module  # noqa: E402
from common.dynamic_overview.engine import DynamicOverviewEngine  # noqa: E402
from common.dynamic_overview.models import Candidate, QueryPack  # noqa: E402
from common.text_tokenize import tokenize  # noqa: E402
from watch_dog.file_watcher.overview_builder import write_overview_md  # noqa: E402
from watch_dog.file_watcher.section_index import DIM, SectionIndex  # noqa: E402


class HashEmbedding:
    """确定性文本哈希 embedding：共享 token 的文本向量互相接近。"""

    def _get_text_embeddings(self, texts):
        out = []
        for text in texts:
            vec = np.zeros(DIM, dtype=np.float32)
            for token in tokenize(text):
                vec[zlib.crc32(token.encode("utf-8")) % DIM] += 1.0
            norm = float(np.linalg.norm(vec)) or 1.0
            out.append((vec / norm).tolist())
        return out


def fake_rerank(_query, documents):
    return [1.0 if "quorum" in text.lower() else 0.0 for text in documents]


def fake_a0(q_orig, evidence, **kwargs):
    return (
        {
            "hit_quality": "FULL_HIT",
            "intermediate_result_A": "",
            "unresolved_knowledge_gaps": [],
            "next_queries_Q1": {"sub_questions": [], "key_terms": []},
        },
        "",
        1.0,
        100,
    )


MARKER = (
    "Critical quorum failover policy: if sync lost, backup node ERR_9F7 "
    "takes over within 30 seconds."
)
QUERY = "quorum failover backup node ERR_9F7"

FILLER_WORDS = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
]


def _long_doc_lines(target_char_pos: int = 5200) -> tuple[str, int]:
    """构造无子标题 6000 字纯段落文档；MARKER 落在第 target_char_pos 字附近。"""
    lines: list[str] = []
    chars = 0
    marker_line = 0
    i = 0
    while chars < 6000:
        if chars >= target_char_pos and not marker_line:
            lines.append(MARKER)
            marker_line = len(lines)
            chars += len(MARKER)
            continue
        para = (
            f"{FILLER_WORDS[i % 8]} filler paragraph {i:03d} with routine "
            "maintenance notes and periodic review checkpoints for the platform."
        )
        lines.append(para)
        chars += len(para) + 1
        i += 1
    return "\n".join(lines), marker_line


LIST_DOC = """# 割接手册

## 3. 操作步骤

前置检查完成后，强制步骤如下：
1. 冻结变更窗口
2. 通知值班经理
3. 切换主用链路
4. 验证业务探活
5. 回收旧链路资源

收尾说明段落。
"""


class FourWayProbesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        self.lan.mkdir()
        long_text, self.marker_line = _long_doc_lines()
        (self.pre / "long.md").write_text(long_text, encoding="utf-8")
        (self.pre / "cutover.md").write_text(
            "# 割接总览\n\n## 专线应急割接方案\n\n专线应急割接方案适用于突发中断。\n",
            encoding="utf-8",
        )
        (self.pre / "list.md").write_text(LIST_DOC, encoding="utf-8")
        write_overview_md(self.lan, self.pre)
        builder = SectionIndex(self.lan, embedding=HashEmbedding(), enable_ann=False)
        builder.build_from_pre_dir(self.pre, full_build=True)
        builder.finalize()
        self.route = {
            "kind": "agent",
            "label": "agent:test",
            "lan_dir": str(self.lan),
            "pre_dir": str(self.pre),
            "overview_md": str(self.lan / "overview.md"),
        }
        with patch.object(SectionIndex, "_get_embedding", return_value=HashEmbedding()):
            self.engine = DynamicOverviewEngine([self.route], context_window=100_000)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # 1. 长文 6000 字深层答案：路 3 精准命中第 5200 字所在 Chunk
    # ------------------------------------------------------------------
    def test_deep_body_semantic_recall_in_long_doc(self) -> None:
        q = DynamicOverviewEngine.build_query_pack([QUERY])
        with patch.object(SectionIndex, "_get_embedding", return_value=HashEmbedding()), \
             patch.object(engine_module, "batch_rerank_scores", side_effect=fake_rerank):
            selected, docs, diag = self.engine._run_hop(q, 0)
        counts = diag["probe_counts"]
        # 四路计数全部输出
        for key in ("struct_semantic", "skeleton_fts", "body_semantic", "body_fts"):
            self.assertIn(key, counts)
        self.assertIn("semantic", counts)
        # 路 3 body_semantic 精准命中 marker 所在行号
        self.assertGreaterEqual(counts["body_semantic"], 1)
        self.assertGreaterEqual(counts["body_fts"], 1)
        hits = [
            c for c in selected
            if c.rel_path == "long.md" and c.start_line <= self.marker_line <= c.end_line
        ]
        self.assertTrue(hits, "marker 行号必须被某个候选区间覆盖")
        # rerank 后金标文档排入首位（fake_rerank 只给 quorum 文本满分）
        scored = sorted(docs.values(), key=lambda d: d.score, reverse=True)
        self.assertEqual(scored[0].rel_path, "long.md")

    # ------------------------------------------------------------------
    # 2. 中文短语骨架二次过滤防误杀：专线割接 vs 专线应急割接方案
    # ------------------------------------------------------------------
    def test_skeleton_term_match_phrase_not_killed(self) -> None:
        text = "1. 概述/专线应急割接方案 专线应急割接方案适用于突发中断"
        self.assertTrue(self.engine._skeleton_term_match(text, ["专线割接"]))
        self.assertTrue(self.engine._skeleton_term_match(text, ["专线", "割接"]))
        # 完全无关文本仍然拒绝
        self.assertFalse(self.engine._skeleton_term_match("值班表与排班安排", ["专线割接"]))
        # ASCII 硬标识符：精确子串，前缀相似不通过
        self.assertTrue(self.engine._skeleton_term_match("报错 ERR_401_02 退出", ["ERR_401_02"]))
        self.assertFalse(self.engine._skeleton_term_match("报错 ERR_401_03 退出", ["ERR_401_02"]))
        self.assertTrue(self.engine._skeleton_term_match("启用 X-Redwood-Cache", ["X-Redwood"]))
        self.assertFalse(self.engine._skeleton_term_match("启用 X-RW-Cache", ["X-Redwood"]))

    def test_probe_skeleton_fts_phrase_survives(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(["专线割接 应急方案"])
        ctx = self.engine.contexts[0]
        candidates = self.engine._probe_skeleton_fts(ctx, q)
        rels = {c.rel_path for c in candidates}
        self.assertIn("cutover.md", rels, "短语命中标题不得被二次过滤误杀")

    # ------------------------------------------------------------------
    # 3. 同文档重叠/相邻 Chunk 区间合并
    # ------------------------------------------------------------------
    def test_merge_adjacent_body_chunks(self) -> None:
        base = dict(
            route_index=0, doc_id="f001", local_doc_id="F001", rel_path="long.md",
            section_id="F001#1", structural=False,
        )
        c1 = Candidate(**base, chunk_id="F001#c0", start_line=10, end_line=14,
                       source_scores={"body_semantic": 0.9}, fallback_score=0.9)
        c2 = Candidate(**base, chunk_id="F001#c1", start_line=13, end_line=20,
                       source_scores={"body_fts": 0.7}, fallback_score=0.7)
        far = Candidate(**base, chunk_id="F001#c2", start_line=100, end_line=110,
                        source_scores={"body_fts": 0.5}, fallback_score=0.5)
        merged = self.engine._merge_candidates([c1, c2, far])
        adjacent = [c for c in merged if c.start_line == 10]
        self.assertEqual(len(adjacent), 1)
        merged_span = adjacent[0]
        self.assertEqual(merged_span.end_line, 20)
        self.assertEqual(merged_span.source_scores.get("body_semantic"), 0.9)
        self.assertEqual(merged_span.source_scores.get("body_fts"), 0.7)
        self.assertAlmostEqual(merged_span.fallback_score, 0.9)
        # 距离过远的不合并
        self.assertTrue(any(c.start_line == 100 for c in merged))

    # ------------------------------------------------------------------
    # 4. 跨路合并防误杀：body_fts 未过字面校验时保留向量路得分
    # ------------------------------------------------------------------
    def test_select_keeps_candidate_with_other_probe_scores(self) -> None:
        q = QueryPack(questions=[QUERY], terms=["quorum"])
        base = dict(
            route_index=0, doc_id="f001", local_doc_id="F001", rel_path="list.md",
            section_id="F001#1", structural=False,
        )
        both = Candidate(**base, chunk_id="F001#c0", start_line=1, end_line=5,
                         source_scores={"body_fts": 0.9, "body_semantic": 0.5},
                         fallback_score=0.9)
        only_fts = Candidate(**base, chunk_id="F001#c1", start_line=6, end_line=8,
                             source_scores={"body_fts": 0.8}, fallback_score=0.8)
        selected = self.engine._select_for_rerank([both, only_fts], q)
        rels = {c.chunk_id: c for c in selected}
        # 双来源候选保留，body_fts 分量被摘除且 fallback 分取向量路
        self.assertIn("F001#c0", rels)
        kept = rels["F001#c0"]
        self.assertNotIn("body_fts", kept.source_scores)
        self.assertAlmostEqual(kept.fallback_score, 0.5)
        # 唯一来源是 body_fts 且未过字面校验 → 丢弃
        self.assertNotIn("F001#c1", rels)

    # ------------------------------------------------------------------
    # 5. 规则 3 语义闭合顺延：引出列表完整还原
    # ------------------------------------------------------------------
    def test_restore_texts_extends_open_ended_list(self) -> None:
        # "强制步骤如下：" 在第 5 行，候选只覆盖到该行
        candidate = Candidate(
            route_index=0, doc_id="f001", local_doc_id="F001", rel_path="list.md",
            section_id="F001#1", start_line=5, end_line=5, chunk_id="F001#c0",
            structural=False, source_scores={"body_semantic": 0.9}, fallback_score=0.9,
        )
        self.engine._restore_texts([candidate])
        for item in ("冻结变更窗口", "通知值班经理", "切换主用链路", "验证业务探活", "回收旧链路资源"):
            self.assertIn(item, candidate.text)
        # 顺延到列表自然结束（第 11 行），不吞掉后面的收尾说明
        self.assertEqual(candidate.end_line, 10)
        self.assertNotIn("收尾说明段落", candidate.text)

    def test_restore_texts_no_extension_for_closed_block(self) -> None:
        candidate = Candidate(
            route_index=0, doc_id="f001", local_doc_id="F001", rel_path="list.md",
            section_id="F001#2", start_line=12, end_line=12, chunk_id="F001#c2",
            structural=False, source_scores={"body_fts": 0.8}, fallback_score=0.8,
        )
        self.engine._restore_texts([candidate])
        self.assertEqual(candidate.end_line, 12)
        self.assertIn("收尾说明段落", candidate.text)

    # ------------------------------------------------------------------
    # 6. 整章 3000 字盲截断拔除：纯结构路候选只取导言骨架
    # ------------------------------------------------------------------
    def test_restore_texts_skeleton_only_no_3000_truncation(self) -> None:
        long_lines, _ = _long_doc_lines()
        total_lines = len(long_lines.splitlines())
        candidate = Candidate(
            route_index=0, doc_id="f001", local_doc_id="F001", rel_path="long.md",
            section_id="F001#1", start_line=1, end_line=total_lines,
            structural=True, source_scores={"struct_semantic": 0.9}, fallback_score=0.9,
        )
        self.engine._restore_texts([candidate])
        # 导言骨架 ≤ 600 字（不含 header_path 前缀行）
        body_text = candidate.text.split("\n", 1)[-1]
        self.assertLessEqual(len(body_text), 600)
        # 不含深层正文（第 25 行之后的内容不进 Rerank 文本）
        deep_line = long_lines.splitlines()[30]
        self.assertNotIn(deep_line, candidate.text)
        # 候选行号区间不被改写（概览仍展示章节真实区间）
        self.assertEqual(candidate.end_line, total_lines)

    # ------------------------------------------------------------------
    # 7. 旧 v2 Tantivy fts/skeleton：按旧 Schema 只读打开（v2 兼容层），
    #    零写盘、路 2 域自动过滤； LanceDB 表为 v2 缺列形态时由
    #    COSIGHTBOT_DYNAMIC_LEGACY_COMPAT 开关决定放行或拒绝。
    # ------------------------------------------------------------------
    def test_engine_opens_legacy_v2_fts_readonly_with_field_filter(self) -> None:
        import shutil
        import tantivy

        skel_dir = self.lan / "fts" / "skeleton"
        shutil.rmtree(skel_dir)
        skel_dir.mkdir(parents=True, exist_ok=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("rel_path", stored=True, tokenizer_name="raw")
        builder.add_text_field("title", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("header_path", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("first_sentence", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("table_headers", stored=False, tokenizer_name="whitespace")
        old_idx = tantivy.Index(builder.build(), path=str(skel_dir))
        old_w = old_idx.writer()
        old_w.commit()
        del old_w, old_idx
        meta_before = (skel_dir / "meta.json").read_text(encoding="utf-8")

        # v2 兼容：fts 旧 Schema 只读打开（LanceDB 表为 v3 时无需任何开关）
        with patch.object(SectionIndex, "_get_embedding", return_value=HashEmbedding()):
            compat_engine = DynamicOverviewEngine([self.route], context_window=100_000)
        ctx = compat_engine.contexts[0]
        self.assertFalse(ctx.legacy_compat)
        self.assertTrue(ctx.index.fts_skeleton.legacy_schema)
        self.assertFalse(ctx.index.fts_skeleton.schema_mismatch)
        self.assertEqual(ctx.index.fts_skeleton.available_fields,
                         {"doc_id", "section_id", "rel_path", "title", "header_path",
                          "first_sentence", "table_headers"})
        # S-01 检索只读：旧 meta.json 一字未改
        self.assertEqual((skel_dir / "meta.json").read_text(encoding="utf-8"), meta_before)

    def test_engine_v2_lance_gate_respects_legacy_compat_switch(self) -> None:
        """LanceDB 表为 v2 缺列形态：开关关闭拒绝（原行为），开关开启放行并打标。"""
        import os

        import lancedb
        import pyarrow as pa

        # 把 doc_skeleton 降级为 v2 形态（无 jev_* 列），schema_version 置 2
        db = lancedb.connect(str(self.lan))
        db.drop_table("doc_skeleton")
        db.create_table("doc_skeleton", schema=pa.schema([
            pa.field("doc_key", pa.string()), pa.field("rel_path", pa.string()),
            pa.field("title", pa.string()), pa.field("doc_meta", pa.string()),
            pa.field("skeleton_json", pa.string()), pa.field("fingerprint", pa.string()),
            pa.field("line_count", pa.int64()), pa.field("char_count", pa.int64()),
            pa.field("updated_at", pa.int64()),
        ]))
        db.drop_table("build_meta")
        db.create_table("build_meta", schema=pa.schema([
            pa.field("key", pa.string()), pa.field("value", pa.string()),
        ]))
        db.open_table("build_meta").add([{"key": "schema_version", "value": "2"}])
        # nodes_pointer 同步降级为 v2 形态（无 vector 列），验证路 3 跳过
        db.drop_table("nodes_pointer")
        db.create_table("nodes_pointer", schema=pa.schema([
            pa.field("doc_key", pa.string()), pa.field("section_id", pa.string()),
            pa.field("chunk_id", pa.string()), pa.field("start_line", pa.int64()),
            pa.field("end_line", pa.int64()), pa.field("header_line", pa.int64()),
        ]))

        env_off = {k: v for k, v in os.environ.items()
                   if k != "COSIGHTBOT_DYNAMIC_LEGACY_COMPAT"}
        with patch.dict(os.environ, env_off, clear=True):
            with patch.object(SectionIndex, "_get_embedding", return_value=HashEmbedding()):
                with self.assertRaises(engine_module.DynamicIndexError) as cm:
                    DynamicOverviewEngine([self.route], context_window=100_000)
        self.assertEqual(cm.exception.error_code, "DYNAMIC_INDEX_MISSING")

        with patch.dict(os.environ, {"COSIGHTBOT_DYNAMIC_LEGACY_COMPAT": "1"}):
            with patch.object(SectionIndex, "_get_embedding", return_value=HashEmbedding()):
                compat_engine = DynamicOverviewEngine([self.route], context_window=100_000)
        ctx = compat_engine.contexts[0]
        self.assertTrue(ctx.legacy_compat)
        self.assertFalse(ctx.index.pointer_vector_ready)
        # 路 3 在 v2 库上优雅空转（返回空列表，不抛错）
        self.assertEqual(ctx.index.search_pointers(np.zeros(1024, dtype=np.float32)), [])


if __name__ == "__main__":
    unittest.main()
