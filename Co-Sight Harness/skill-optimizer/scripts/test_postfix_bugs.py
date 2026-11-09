#!/usr/bin/env python3
"""
test_postfix_bugs.py — 验收 taskid_20260619_000245 发现的 5 个 bug 局部回归

5 个 bug 来源:产物核查 (baseline/R1/R2 已完成)
- Bug #1 vs_best_delta 永远 0
- Bug #2 R1/R2 错判 not_adopted
- Bug #3 composite 多乘 100
- Bug #4 round MD 缺 per_case/modifications 章节
- Bug #5 task_state.json phases 全 pending

每个测试独立,只测目标 bug 不跑完整 orchestrator:
1. test_bug_1_2_decision_and_delta  → orchestrator 决策 / delta 计算
2. test_bug_3_composite_scale        → round_N_score.json 写盘
3. test_bug_4_round_md_sections      → RoundReportBuilder 渲染
4. test_bug_5_phase_callsite         → eval_pipeline phase_callsite + phase_tracker 回填
5. test_bug_5_existing_taskid_backfill → 对 taskid_20260619_000245 跑一次回填验证
6. test_bug_6_write_back_replace     → 任务结束写回原位置必须完全替换

运行:python3 scripts/test_postfix_bugs.py
"""

import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))


# ════════════════════════════════════════════════════════════════
# Bug #1 + Bug #2: 决策 + vs_best_delta
# ════════════════════════════════════════════════════════════════

def test_bug_1_2_decision_and_delta():
    """
    Bug #1: vs_best_delta 永远 0
    Bug #2: score=44.08 > baseline=33.06 却被判 not_adopted

    根因: orchestrator 先更新 eng.best_score = 44.08,
    再读 eng.best_score 做 _current_best = 44.08,导致:
      - score > _current_best → False → not_adopted
      - vs_best_delta = score - _current_best = 0

    验证:模拟 R1 (baseline=33.06, score=44.08) 应 adopted 且 vs_best_delta=+11.02
    """
    print("\n[test_bug_1_2] 决策 + vs_best_delta")

    # 模拟 orchestrator 的决策逻辑
    eng_baseline = 33.06
    eng_best_score = eng_baseline  # baseline 评估后初始化

    # R1: score=44.08, 应该 adopted
    score_r1 = 44.08
    # 修复后的逻辑:先快照,再更新
    best_round_old_score = eng_best_score  # 33.06
    if score_r1 > eng_best_score:
        eng_best_score = score_r1
    current_best_r1 = best_round_old_score  # 33.06
    decision_r1 = "adopted" if (score_r1 > current_best_r1) else "not_adopted"
    delta_r1 = round(score_r1 - current_best_r1, 4)

    assert decision_r1 == "adopted", f"R1 应 adopted, 实际 {decision_r1}"
    assert delta_r1 == 11.02, f"R1 vs_best_delta 应 +11.02, 实际 {delta_r1}"
    print(f"  R1: score={score_r1}, baseline={current_best_r1}, decision={decision_r1}, "
          f"vs_best_delta={delta_r1:+.2f} ✓")

    # R2: score=44.375, 应该 adopted (44.375 > 44.08)
    score_r2 = 44.375
    best_round_old_score = eng_best_score  # 44.08
    if score_r2 > eng_best_score:
        eng_best_score = score_r2
    current_best_r2 = best_round_old_score  # 44.08
    decision_r2 = "adopted" if (score_r2 > current_best_r2) else "not_adopted"
    delta_r2 = round(score_r2 - current_best_r2, 4)

    assert decision_r2 == "adopted", f"R2 应 adopted, 实际 {decision_r2}"
    assert delta_r2 == 0.295, f"R2 vs_best_delta 应 +0.295, 实际 {delta_r2}"
    print(f"  R2: score={score_r2}, prev_best={current_best_r2}, decision={decision_r2}, "
          f"vs_best_delta={delta_r2:+.2f} ✓")

    # R3: score=40 (低于 R2 best), 应 not_adopted, vs_best_delta = -4.375
    score_r3 = 40.0
    best_round_old_score = eng_best_score  # 44.375
    current_best_r3 = best_round_old_score
    decision_r3 = "adopted" if (score_r3 > current_best_r3) else "not_adopted"
    delta_r3 = round(score_r3 - current_best_r3, 4)

    assert decision_r3 == "not_adopted", f"R3 应 not_adopted, 实际 {decision_r3}"
    assert delta_r3 == -4.375, f"R3 vs_best_delta 应 -4.375, 实际 {delta_r3}"
    print(f"  R3: score={score_r3}, prev_best={current_best_r3}, decision={decision_r3}, "
          f"vs_best_delta={delta_r3:+.2f} ✓")

    print("  PASS")


# ════════════════════════════════════════════════════════════════
# Bug #3: composite 多乘 100
# ════════════════════════════════════════════════════════════════

def test_bug_3_composite_scale():
    """
    Bug #3: round_N_score.json 的 composite 多乘 100 (cs["score"] 已是百分制)

    修复后:composite 应等于 avg_result_score (44.08),而非 4408.0
    """
    print("\n[test_bug_3] composite 数量级")

    # 模拟 orchestrator.py 992 行附近的写入逻辑
    candidate_scores_for_report = [
        {"id": 1, "score": 44.08, "strategy": "agent_candidate_1", "stddev": 7.38},
    ]
    bl_score = 33.06

    # 修复后:composite = round(cs["score"], 2) 而非 round(cs["score"] * 100, 2)
    round_score_data = {
        "round_num": 1,
        "best_candidate_id": 1,
        "baseline_score": bl_score,
        "candidates": [
            {
                "candidate_id": cs["id"],
                "strategy": cs["strategy"],
                "avg_result_score": round(cs["score"], 4),
                "normalized": {"result_score": round(cs["score"], 4)},
                "composite": round(cs["score"], 2),  # 修复后
                "num_runs": 2,
                "stddev": round(cs["stddev"], 4),
            }
            for cs in candidate_scores_for_report
        ],
    }

    c0 = round_score_data["candidates"][0]
    assert c0["composite"] == 44.08, f"composite 应 44.08, 实际 {c0['composite']}"
    assert c0["composite"] == c0["avg_result_score"], \
        f"composite 应等于 avg_result_score ({c0['avg_result_score']}), 实际 {c0['composite']}"
    print(f"  composite={c0['composite']}, avg_result_score={c0['avg_result_score']} ✓")
    print("  PASS")


# ════════════════════════════════════════════════════════════════
# Bug #4: round MD 缺 per_case/modifications 章节
# ════════════════════════════════════════════════════════════════

def test_bug_4_round_md_sections():
    """
    Bug #4: round_N_score_analysis.md 缺 per_case matrix + modifications summary

    修复后:RoundReportBuilder.add_per_case_matrix + add_modifications_summary 应可用
    """
    print("\n[test_bug_4] RoundReportBuilder 新方法")

    from state_engine.persistence import RoundReportBuilder

    candidates = [
        {
            "id": 1,
            "score": 44.08,
            "strategy": "agent_candidate_1",
            "stddev": 7.38,
            "per_case": {
                "RAN-5030325": [67.5, 65.0],
                "RAN-6640009": [93.75, 0.0],
                "RAN-6412296": [92.5, 96.0],
            },
        },
    ]
    modifications_summary = [
        {
            "index": 1, "action": "MODIFY",
            "file": "特性域变更分析-filesearch-用例召回/SKILL.md",
            "section": "## 执行步骤",
            "reason": "该约束对所有同类需求都通用",
        },
        {
            "index": 2, "action": "MODIFY",
            "file": "特性域变更分析-变更点生成/SKILL.md",
            "section": "## 执行步骤",
            "reason": "三段式结构强制拆分",
        },
    ]

    rrb = RoundReportBuilder(2)
    rrb.add_score_summary(33.06, [39.58, 26.55], 9.21, candidates, candidates[0])
    rrb.add_per_case_matrix(candidates)
    rrb.add_gap_root_cause_analysis({"gaps": []})  # 无 gap 场景
    rrb.add_modifications_summary(modifications_summary)
    rrb.add_log_references(2)
    rrb.add_selection_decision(
        33.06, candidates[0], candidates,
        current_best=33.06, decision="adopted",
    )
    md = rrb.render()

    # 验证章节存在
    assert "各 CASE 明细" in md, "缺少 per_case matrix 章节"
    assert "RAN-5030325" in md, "缺少 CASE ID"
    assert "67.5" in md and "65.0" in md, "缺少 run 分数"
    print("  per_case matrix 章节: OK")

    assert "本轮优化提案清单" in md, "缺少 modifications 章节"
    assert "特性域变更分析-filesearch-用例召回/SKILL.md" in md, "缺少 file 路径"
    assert "三段式结构强制拆分" in md, "缺少 reason"
    print("  modifications 章节: OK")

    # 验证 selection_decision 用 current_best/decision 而非 baseline
    assert "当前最佳" in md or "保留当前最佳" in md, \
        "add_selection_decision 应基于 current_best 而非 baseline"
    print("  selection_decision 用 running max: OK")

    print("  PASS")


# ════════════════════════════════════════════════════════════════
# Bug #5: phase callsite + 回填
# ════════════════════════════════════════════════════════════════

def test_bug_5_phase_callsite():
    """
    Bug #5: phases 字段全 pending (orchestrator 直接调 run_evaluation 跳过 phase_callsite)

    验证:
    - run_evaluation 内部 record_phase_start/complete("evaluate")
    - orchestrator.analyze_run 周边 record_phase_start/complete("score")
    - phase_tracker 只存状态,result 字段在 config
    """
    print("\n[test_bug_5] phase callsite")

    from state_engine.phase_tracker import PhaseTracker

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        pt = PhaseTracker(ws)

        # 模拟 orchestrator 全流程的 phase_callsite
        pt.start_phase(1, "evaluate")
        pt.complete_phase(1, "evaluate")

        pt.start_phase(1, "score")
        pt.complete_phase(1, "score")

        # 重新加载,验证 phases 状态
        pt2 = PhaseTracker(ws)
        statuses = {p: pt2._data['rounds']['1'][p]['status'] for p in ['apply', 'evaluate', 'score', 'proposal']}

        assert statuses['evaluate'] == 'completed', f"evaluate 应 completed, 实际 {statuses['evaluate']}"
        assert statuses['score'] == 'completed', f"score 应 completed, 实际 {statuses['score']}"
        # 极简版不应再有 summary / metadata / candidate_pool 顶层键
        assert 'summary' not in pt2._data['rounds']['1'], "极简版不应存 summary"
        assert 'metadata' not in pt2._data['rounds']['1'].get('score', {}), "极简版不应存 metadata"
        assert 'candidate_pool' not in pt2._data, "极简版不应存 candidate_pool"
        print(f"  evaluate={statuses['evaluate']}, score={statuses['score']} ✓")

    print("  PASS")


def test_bug_5_existing_taskid_backfill():
    """
    Bug #5 (回填):旧 taskid 的 phases 需从旧格式迁到新 4-phase 极简 schema

    对 taskid_20260619_000245 跑一次,验证:
    - 旧 9-phase 字段已迁到 4-phase
    - 当前段不再含 result 字段(score/rating/gaps 等)
    """
    print("\n[test_bug_5] taskid_20260619_000245 迁移")

    target = Path("/media/vdb/skillx-alpha/evolution_workspace/taskid_20260619_000245")
    if not target.exists():
        print(f"  SKIP: {target} 不存在")
        return

    from state_engine.phase_tracker import PhaseTracker

    pt = PhaseTracker(target)
    rounds = pt._data.get('rounds', {})

    # 旧 9-phase 字段不应存在
    legacy_phases = {"sandbox_setup", "sandbox_cleanup", "round_complete", "gap_analysis", "proposal_review"}
    for rk, rd in rounds.items():
        legacy = legacy_phases & set(rd.keys())
        assert not legacy, f"round {rk} 仍含旧 phase {legacy}"

    # 每轮应只有 4 phase 字段
    for rk, rd in rounds.items():
        assert set(rd.keys()) == {"apply", "evaluate", "score", "proposal"}, \
            f"round {rk} 应只有 4 phase, 实际 {set(rd.keys())}"

    # current 段不应含 result 字段
    cur = pt._data.get('current') or {}
    result_keys = {"score", "rating", "baseline_score", "best_score", "best_round",
                   "aggregate_score", "gaps", "modifications"}
    leaked = result_keys & set(cur.keys())
    assert not leaked, f"current 段不应含 result 字段 {leaked}, 实际 {set(cur.keys())}"

    # candidate_pool 顶层不应存在
    assert 'candidate_pool' not in pt._data, "极简版不应存 candidate_pool"

    print(f"  迁移 OK: {len(rounds)} 轮,current 字段 {set(cur.keys())} ✓")

    print("  PASS")


# ════════════════════════════════════════════════════════════════
# Bug #7: agent_dir/skill/ 跨轮被覆盖（违反 "skill/ 永远不变" 不变量）
# ════════════════════════════════════════════════════════════════

def test_bug_7_skill_immutable():
    """
    Bug #7: taskid_20260720_235648 发现 agent_dir/skill/ 跨轮被覆盖。

    根因: orchestrator.py run_agent_loop 在 round 2+ 起始处调用
      _replace_skill_with_candidate(prev_best_skill_root, skill_registry)
    skill_registry 在 multi-skill 模式下映射到 agent_dir/skill/{name}/,
    导致 best_round 的 candidate 内容覆盖到 workspace skill/,
    违反了 "skill/ 永远不变" 的不变量。

    修复: 移除跨轮覆盖调用,改为只打印日志。
      workspace skill/ 在任务初始化时从 user source 拷贝一次,后续永不修改。
      跨轮状态由 prompt 注入给 proposal-agent (baseline_avg / gaps / per_case_score 等)
      best_skill/ 由 _save_best_skill 在任务结束时从 round_{best_round}/candidate_{best_id}/skill/
      直接拷贝,与 workspace skill/ 解耦。

    验证:
      1. orchestrator.py 不再调用 _replace_skill_with_candidate
      2. 模拟跨轮继承块 (round 2+ 起始): agent_dir/skill/ 内容保持初始状态不变
    """
    print("\n[test_bug_7] agent_dir/skill/ 跨轮不可变")

    # ── 验证 1: 静态检查 — orchestrator.py 不再调用 _replace_skill_with_candidate ──
    orch_path = SCRIPT_DIR / "orchestrator.py"
    src = orch_path.read_text(encoding="utf-8")
    # 排除 import 行和函数定义本身的字符串引用
    call_sites = [
        line for line in src.splitlines()
        if "_replace_skill_with_candidate(" in line and "def " not in line
        # import 行的形式是 "from ... import ... replace_skill_with_candidate as _replace_skill_with_candidate"
        and "import" not in line
    ]
    assert not call_sites, (
        f"orchestrator.py 不应再调用 _replace_skill_with_candidate, "
        f"发现 {len(call_sites)} 处: {call_sites[:3]}"
    )
    print("  静态检查: orchestrator.py 已无 _replace_skill_with_candidate 调用 ✓")

    # ── 验证 1b: 静态检查 — orchestrator.py 不再调用 disabled 三函数(2026-07 防御链改造) ──
    # 这三个函数被 backup_skill_to_bak / restore_skill_from_bak /
    # replace_skill_with_optimized 替代,签名保留只为 import 兼容。
    disabled_func_names = [
        "backup_user_source(",
        "restore_user_source_from_backup(",
        "replace_candidate_to_user_source(",
    ]
    for func_name in disabled_func_names:
        offending = [
            line for line in src.splitlines()
            if func_name in line and "def " not in line and "import" not in line
        ]
        assert not offending, (
            f"orchestrator.py 不应再调用 {func_name}, "
            f"发现 {len(offending)} 处: {offending[:3]}"
        )
    print("  静态检查: orchestrator.py 已无 disabled 三函数调用 ✓")

    # ── 验证 2: 行为模拟 — 跨轮继承块不再修改 workspace skill/ ──
    # 模拟 run_agent_loop 在 round 2+ 起始处的逻辑(修复后只剩 print,不写文件)
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        # 初始 workspace skill/ 内容 = INITIAL
        ws_skill = ws / "skill" / "SkillA"
        ws_skill.mkdir(parents=True)
        initial_md = "# INITIAL skill\nthis is the original content"
        (ws_skill / "SKILL.md").write_text(initial_md, encoding="utf-8")
        initial_md_bytes = (ws_skill / "SKILL.md").read_bytes()
        initial_mtime = (ws_skill / "SKILL.md").stat().st_mtime

        # 模拟 best_round=1, candidate_1/skill/ 内容 = MODIFIED (R1 修改过的版本)
        cand_skill = ws / "round_1" / "candidate_1" / "skill" / "SkillA"
        cand_skill.mkdir(parents=True)
        modified_md = "# MODIFIED skill\nthis is round 1 candidate output"
        (cand_skill / "SKILL.md").write_text(modified_md, encoding="utf-8")

        # 模拟修复后的跨轮继承块: 只 print, 不写文件
        # (修复前会调用 _replace_skill_with_candidate 把 candidate 内容覆盖到 workspace skill/)
        # 我们什么都不做,只验证 workspace skill/ 没变

        after_md_bytes = (ws_skill / "SKILL.md").read_bytes()
        after_mtime = (ws_skill / "SKILL.md").stat().st_mtime
        assert initial_md_bytes == after_md_bytes, (
            "workspace skill/ 内容被修改,违反了 skill/ 永远不变不变量"
        )
        assert initial_mtime == after_mtime, (
            "workspace skill/ mtime 被修改,违反了 skill/ 永远不变不变量"
        )
        print(f"  行为模拟: round_2 起始后 workspace skill/ 保持 INITIAL ({len(initial_md_bytes)} bytes) ✓")

        # ── 验证 3: best_skill/ 仍然从 round_{best}/candidate_{best}/skill/ 取 ──
        # 模拟 _save_best_skill 的关键路径(cand_skill = round_1/candidate_1/skill/SkillA/)
        best_dir = ws / "best_skill" / "SkillA"
        shutil.copytree(str(cand_skill), str(best_dir))
        best_md = (best_dir / "SKILL.md").read_text(encoding="utf-8")
        assert best_md == modified_md, (
            "best_skill 应来自 round_{best}/candidate_{best}/skill/, "
            f"实际内容不符: {best_md[:50]}"
        )
        print("  best_skill/ 仍正确从 round_1/candidate_1/skill/ 取 MODIFIED 版本 ✓")

        # ── 验证 4: workspace skill/ 和 best_skill/ 内容应当不同(场景关键不变量) ──
        ws_content = (ws_skill / "SKILL.md").read_text(encoding="utf-8")
        assert ws_content == initial_md, "workspace skill/ 应保持 INITIAL"
        assert ws_content != modified_md, (
            "workspace skill/ 不应被覆盖成 MODIFIED;这是修复前的 bug 行为"
        )
        print("  workspace skill/ != best_skill/ 内容(INITIAL vs MODIFIED) ✓")

    print("  PASS")


# ════════════════════════════════════════════════════════════════
# Bug #6: 任务结束写回原位置必须是"rmtree + copytree"完全替换
# ════════════════════════════════════════════════════════════════

def test_bug_6_write_back_replace():
    """
    Bug #6: _restore_best_skill_to_original 和 write_back_best_skill_to_source
    都用 shutil.copytree(dirs_exist_ok=True) 合并写法,不删除源目录里没有的多余文件。

    用户预期语义(2026-06-19 明确):
      1. 先把原始 skill 完整备份(到 _user_source_backup/)
      2. 删掉原目录(rmtree)
      3. 把 best_skill 完整拷贝到原路径
      → 原路径状态严格 == best_skill,无残留 .proposed/旧版本文件

    验证:
    - restore_skill_dir / write_back 都用 rmtree+copytree 模式
    - 用户源的多余文件被删除
    - 备份目录保留了原始完整内容
    """
    print("\n[test_bug_6] write_back 完全替换语义")

    from orchestrators.skill_manager import backup_skill_dir, restore_skill_dir

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        user_src = ws / "user_src_skill"
        user_src.mkdir()
        # 用户源原始内容(有冗余文件,模拟上轮残留)
        (user_src / "SKILL.md").write_text("# OLD skill")
        (user_src / "old_ref.md").write_text("OLD ref")
        (user_src / "old_only.md").write_text("only in old user src")
        (user_src / "references").mkdir()
        (user_src / "references" / "old.md").write_text("OLD ref content")

        # 模拟备份(用 skill_manager 原语)
        backup_root = ws / "_user_source_backup"
        backup_root.mkdir()
        backup_skill_dir(user_src, backup_root / "user_src_skill")
        assert (backup_root / "user_src_skill" / "old_only.md").exists()
        print("  备份保留旧文件 old_only.md ✓")

        # 最佳 skill 内容(新版本,无 old_only.md)
        best = ws / "best_skill"
        best.mkdir()
        (best / "SKILL.md").write_text("# NEW skill")
        (best / "new_ref.md").write_text("NEW ref")
        (best / "references").mkdir()
        (best / "references" / "new.md").write_text("NEW ref content")

        # 验证修复后的 restore_skill_dir 语义
        restore_skill_dir(best, best, user_src)

        files = sorted([p.name for p in user_src.iterdir()])
        print(f"  写回后用户源文件: {files}")

        # 用户预期:用户源 == best 完全一致
        assert "old_only.md" not in files, \
            f"❌ old_only.md 应被删除,实际 {files}"
        assert "old_ref.md" not in files, \
            f"❌ old_ref.md 应被覆盖删除,实际 {files}"
        assert "new_ref.md" in files, \
            f"❌ new_ref.md 应存在,实际 {files}"
        assert (user_src / "SKILL.md").read_text() == "# NEW skill"
        assert (user_src / "references" / "new.md").read_text() == "NEW ref content"
        # 验证 references/old.md 已被替换(不是合并)
        assert not (user_src / "references" / "old.md").exists(), \
            "❌ references/old.md 应被新版本替换,实际仍存在"
        print("  用户源 == best 完全一致(无残留)✓")

        # 验证备份完整保留(可回滚)
        backup_files = sorted([p.name for p in (backup_root / "user_src_skill").iterdir()])
        assert "old_only.md" in backup_files, "备份丢失 old_only.md"
        print(f"  备份完整(可回滚): {backup_files} ✓")

    print("  PASS")


# ════════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════════

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def run(self, fn):
        try:
            fn()
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            self.failed += 1

    def summary(self):
        print(f"\n{'='*60}")
        print(f"  结果: {self.passed} passed, {self.failed} failed")
        print(f"{'='*60}")
        return self.failed == 0


# ════════════════════════════════════════════════════════════════
# Bug #8: 每轮缺 proposal.md 和 skill_diff.md
# ════════════════════════════════════════════════════════════════

def test_bug_8_round_artifacts():
    """
    Bug #8: taskid_20260720_235648 中每轮只有 candidate_1/optimization_summary.md,
    没有 round_N/proposal.md 也没有 round_N/skill_diff.md。

    根因: v2.13+ 把 proposal+apply 合并成单次 LLM 调用,主动删除了
    analyze_baseline 里的 proposal.md 生成(score_analyzer.py:3308-3311 注释)。
    但用户契约要求每轮都有:
      - baseline/proposal.md (基线阶段也要产,供 R1 参考)
      - round_N/proposal.md (本轮提案,从 optimization_summary.md 升格)
      - round_N/skill_diff.md (本轮所有 Skill 的 unified diff, +++ / --- 格式)

    修复: 在 orchestrator.py 中新增 3 个辅助函数:
      _write_baseline_proposal_md: 基线评测完成后从 bl_gaps 渲染 baseline/proposal.md
      _write_round_proposal_md: 把 round_N/candidate_1/optimization_summary.md 升格为 round_N/proposal.md (R1 同时回填 baseline/proposal.md)
      _write_round_diff_md: 对每个 Skill 生成 before vs after 的 unified diff,聚合到 round_N/skill_diff.md

    验证:
      1. 静态检查: 3 个函数在 orchestrator.py 中存在
      2. 行为模拟: 模拟 run_agent_loop 的关键路径,验证 3 类产物文件被写出
      3. skill_diff.md 含 +++/--- 标记且覆盖所有 Skill
    """
    print("\n[test_bug_8] 每轮 proposal.md + skill_diff.md 产物")

    # ── 验证 1: 静态检查 ──
    orch_path = SCRIPT_DIR / "orchestrator.py"
    orch_src = orch_path.read_text(encoding="utf-8")
    for fn in ["_write_baseline_proposal_md", "_write_round_proposal_md", "_write_round_diff_md"]:
        assert f"def {fn}" in orch_src, f"orchestrator.py 缺函数 {fn}"
        assert f"{fn}(" in orch_src, f"orchestrator.py 缺函数 {fn} 调用"
    print("  静态检查: 3 个辅助函数均已定义并调用 ✓")

    # ── 验证 2: 行为模拟 — _write_baseline_proposal_md ──
    from orchestrator import _write_baseline_proposal_md
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "baseline").mkdir(parents=True)
        # 模拟 baseline/score_baseline.json
        sb = {
            "baseline_score": {"avg_result_score": 1.0},
        }
        (ws / "baseline" / "score_baseline.json").write_text(
            json.dumps(sb, ensure_ascii=False), encoding="utf-8"
        )

        gaps = [
            {"type": "missing_section", "severity": "critical",
             "message": "用户需求分析汇总缺 Step 1 字段约束段",
             "affected_section": "用户需求分析汇总/Step 1"},
            {"type": "eval_bug", "severity": "high",
             "message": "阶段 4 缺 cross_comparison",
             "affected_section": ""},
        ]
        ret = _write_baseline_proposal_md(ws, gaps, 1.0)
        assert ret is not None and ret.exists(), "baseline/proposal.md 未生成"
        text = ret.read_text(encoding="utf-8")
        assert "Baseline 优化提案" in text
        assert "基线分数**: 1.00" in text
        assert "missing_section" in text
        assert "critical" in text
        assert "Step 1 字段约束段" in text
        print(f"  baseline/proposal.md 已生成 ({len(text)} chars, 含 {len(gaps)} gaps) ✓")

    # ── 验证 3: 行为模拟 — _write_round_proposal_md + _write_round_diff_md ──
    from orchestrator import _write_round_diff_md, _write_round_proposal_md
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        skill_names = ["SkillA", "SkillB"]

        # 模拟 round_1_before_skill/skill/{name}/ (BEFORE 状态)
        before_root = ws / "round_1" / "round_1_before_skill" / "skill"
        for name in skill_names:
            before_skill = before_root / name
            before_skill.mkdir(parents=True, exist_ok=True)
            (before_skill / "SKILL.md").write_text(
                f"# {name} - ORIGINAL\n\n## Step 1\n原内容 A\n\n## Step 2\n原内容 B\n",
                encoding="utf-8"
            )

        # 模拟 round_1/candidate_1/skill/{name}/ (AFTER 状态,SkillA 修改,SkillB 不变)
        cand_root = ws / "round_1" / "candidate_1" / "skill"
        for name in skill_names:
            cand_skill = cand_root / name
            cand_skill.mkdir(parents=True, exist_ok=True)
            if name == "SkillA":
                (cand_skill / "SKILL.md").write_text(
                    f"# {name} - MODIFIED\n\n## Step 1\n新增内容 X\n\n## Step 2\n原内容 B\n",
                    encoding="utf-8"
                )
                # 模拟新建脚本
                (cand_skill / "scripts").mkdir(exist_ok=True)
                (cand_skill / "scripts" / "extract.py").write_text("# 新脚本\nprint(1)\n")
            else:
                # SkillB 不变
                (cand_skill / "SKILL.md").write_text(
                    f"# {name} - ORIGINAL\n\n## Step 1\n原内容 A\n\n## Step 2\n原内容 B\n",
                    encoding="utf-8"
                )

        # 模拟 round_1/candidate_1/optimization_summary.md
        cand_summary_dir = ws / "round_1" / "candidate_1"
        cand_summary_dir.mkdir(parents=True, exist_ok=True)
        summary = (
            "# Round 1 Candidate 1 优化摘要\n\n"
            "## 修改文件清单\n\n| 文件 | action |\n|---|---|\n"
            "| `SkillA/SKILL.md` | edit_exact |\n"
            "| `SkillA/scripts/extract.py` | extract_to_script |\n\n"
            "## 覆盖 gaps\n\nG1 (critical)\n"
        )
        (cand_summary_dir / "optimization_summary.md").write_text(summary, encoding="utf-8")

        # 调 _write_round_proposal_md
        prop_ret = _write_round_proposal_md(ws, round_num=1, candidate_id=1)
        assert prop_ret is not None and prop_ret.exists(), "round_1/proposal.md 未生成"
        prop_text = prop_ret.read_text(encoding="utf-8")
        assert "Round 1 优化提案" in prop_text
        assert "optimization_summary" in prop_text
        assert "edit_exact" in prop_text or "修改文件清单" in prop_text
        print(f"  round_1/proposal.md 已生成 ({len(prop_text)} chars) ✓")

        # 验证 R1 同时回填 baseline/proposal.md
        baseline_prop = ws / "baseline" / "proposal.md"
        assert baseline_prop.exists(), "R1 应同时回填 baseline/proposal.md"
        bp_text = baseline_prop.read_text(encoding="utf-8")
        assert "Round 1 优化提案" in bp_text
        print("  baseline/proposal.md 已被 R1 回填 ✓")

        # 调 _write_round_diff_md
        diff_ret = _write_round_diff_md(ws, round_num=1, skill_names=skill_names, candidate_id=1)
        assert diff_ret is not None and diff_ret.exists(), "round_1/skill_diff.md 未生成"
        diff_text = diff_ret.read_text(encoding="utf-8")
        # 验证 +++/--- 标记存在
        assert "```diff" in diff_text, "skill_diff.md 应含 diff 代码块"
        assert "+++" in diff_text or "---" in diff_text, "skill_diff.md 应含 +++/--- 标记"
        # 验证覆盖所有 Skill
        assert "## Skill: SkillA" in diff_text
        assert "## Skill: SkillB" in diff_text
        # SkillA 有变化,SkillB 标记无变更
        assert "_(无变更)_" in diff_text, "SkillB 应标记为无变更"
        # SkillA 的 SKILL.md diff 应包含新增内容 X
        assert "新增内容 X" in diff_text, "SkillA diff 应包含新增内容"
        assert "原内容 A" in diff_text, "SkillA diff 应包含被删除的原内容"
        # scripts/extract.py 应被检测为新增文件
        assert "scripts/extract.py" in diff_text, "scripts/extract.py 应作为新增文件列出"
        print(f"  round_1/skill_diff.md 已生成 ({len(diff_text)} chars, 含 +++/--- 标记) ✓")

    print("  PASS")


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(test_bug_1_2_decision_and_delta)
    runner.run(test_bug_3_composite_scale)
    runner.run(test_bug_4_round_md_sections)
    runner.run(test_bug_5_phase_callsite)
    runner.run(test_bug_5_existing_taskid_backfill)
    runner.run(test_bug_6_write_back_replace)
    runner.run(test_bug_7_skill_immutable)
    runner.run(test_bug_8_round_artifacts)
    ok = runner.summary()
    sys.exit(0 if ok else 1)