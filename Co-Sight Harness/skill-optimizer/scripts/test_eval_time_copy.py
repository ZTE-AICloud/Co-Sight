#!/usr/bin/env python3
"""
test_eval_time_copy.py — 验证 eval 时拷贝模式（每候选 backup→copy→eval→restore）

测试 3 个 helper:
1. backup_user_source: 完整目录备份（含 references/extra.txt）
2. replace_candidate_to_user_source: 覆盖式 copytree 到用户源
3. restore_user_source_from_backup: 从备份恢复到用户源,验证最终状态 = 原始

外加一个端到端循环测试：模拟 K 个候选循环,验证每次循环后用户源都被恢复,
最后用户源仍是原始状态（除非显式调用 replace 后未恢复）。

运行:python3 scripts/test_eval_time_copy.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from orchestrators.skill_manager import (backup_user_source,
                                         replace_candidate_to_user_source,
                                         restore_user_source_from_backup)


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list = []

    def assert_eq(self, name, expected, actual):
        if expected == actual:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.errors.append(f"{name}: expected {expected!r}, got {actual!r}")
            print(f"  ❌ {name}: expected {expected!r}, got {actual!r}")

    def assert_true(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  ✅ {name}")
        else:
            self.failed += 1
            self.errors.append(f"{name}: {detail}")
            print(f"  ❌ {name}: {detail}")

    def summary(self):
        print(f"\n{'=' * 60}")
        print(f"通过 {self.passed} / 失败 {self.failed} (共 {self.passed + self.failed})")
        if self.failed:
            print("\n失败列表:")
            for e in self.errors:
                print(f"  - {e}")
            sys.exit(1)
        print("所有测试通过 ✅")


def _setup(tmpdir: Path, source_skills: dict, candidate_skills: dict = None):
    """构造测试场景：用户源 skill + 候选 skill 副本。

    Returns: (skill_path_list, candidate_root)
    """
    src_root = tmpdir / "source_skills"
    src_root.mkdir()
    skill_path_list = []
    for name, content in source_skills.items():
        skill_dir = src_root / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(content["SKILL.md"], encoding="utf-8")
        if "references" in content:
            ref_dir = skill_dir / "references"
            ref_dir.mkdir()
            (ref_dir / "r1.md").write_text(content["references"], encoding="utf-8")
        if "extra.txt" in content:
            (skill_dir / "extra.txt").write_text(content["extra.txt"], encoding="utf-8")
        skill_path_list.append(str((skill_dir / "SKILL.md").resolve()))

    candidate_root = None
    if candidate_skills:
        candidate_root = tmpdir / "candidate"
        candidate_root.mkdir()
        for name, content in candidate_skills.items():
            cs_dir = candidate_root / name
            cs_dir.mkdir()
            (cs_dir / "SKILL.md").write_text(content["SKILL.md"], encoding="utf-8")
            if "references" in content:
                ref_dir = cs_dir / "references"
                ref_dir.mkdir()
                (ref_dir / "r1.md").write_text(content["references"], encoding="utf-8")
            if "extra.txt" in content:
                (cs_dir / "extra.txt").write_text(content["extra.txt"], encoding="utf-8")

    return skill_path_list, candidate_root


def test_backup_user_source_full():
    """backup_user_source: 完整目录备份（含 references/extra.txt）"""
    print("\n[测试 1] backup_user_source 完整目录备份")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_bk_"))
    try:
        skill_path_list, _ = _setup(tmpdir, source_skills={
            "SkillA": {
                "SKILL.md": "# ORIGINAL A\n",
                "references": "# ORIG REF A\n",
                "extra.txt": "orig extra A\n",
            },
        })
        backup_root = tmpdir / "backup"
        result = backup_user_source(skill_path_list, backup_root)

        r.assert_eq("backup_records 长度 = 1", 1, len(result["backup_records"]))
        # 备份目录存在且内容等于原始
        backup_dir = backup_root / "SkillA"
        r.assert_true("备份目录存在", backup_dir.exists())
        r.assert_eq("备份 SKILL.md",
                    "# ORIGINAL A\n",
                    (backup_dir / "SKILL.md").read_text(encoding="utf-8"))
        r.assert_eq("备份 references",
                    "# ORIG REF A\n",
                    (backup_dir / "references" / "r1.md").read_text(encoding="utf-8"))
        r.assert_eq("备份 extra.txt",
                    "orig extra A\n",
                    (backup_dir / "extra.txt").read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_replace_candidate_to_user_source_overwrite():
    """replace_candidate_to_user_source: 覆盖式写入（含 references/extra.txt）"""
    print("\n[测试 2] replace_candidate_to_user_source 覆盖")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_rep_"))
    try:
        skill_path_list, candidate_root = _setup(
            tmpdir,
            source_skills={
                "SkillA": {
                    "SKILL.md": "# ORIGINAL\n",
                    "references": "# ORIG REF\n",
                    "extra.txt": "orig extra\n",
                },
            },
            candidate_skills={
                "SkillA": {
                    "SKILL.md": "# OPTIMIZED\n",
                    "references": "# OPT REF\n",
                    "extra.txt": "opt extra\n",
                },
            },
        )
        result = replace_candidate_to_user_source(candidate_root, skill_path_list)

        r.assert_eq("replaced = 1", 1, len(result["replaced"]))
        r.assert_eq("skipped = 0", 0, len(result["skipped"]))

        # 用户源已被覆盖
        src_dir = Path(skill_path_list[0]).parent
        r.assert_eq("用户源 SKILL.md 已覆盖",
                    "# OPTIMIZED\n",
                    (src_dir / "SKILL.md").read_text(encoding="utf-8"))
        r.assert_eq("用户源 references 已覆盖",
                    "# OPT REF\n",
                    (src_dir / "references" / "r1.md").read_text(encoding="utf-8"))
        r.assert_eq("用户源 extra.txt 已覆盖",
                    "opt extra\n",
                    (src_dir / "extra.txt").read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_full_cycle_backup_replace_restore():
    """完整周期: backup → replace (修改用户源) → restore (还原为原始)"""
    print("\n[测试 3] backup→replace→restore 完整周期")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_cycle_"))
    try:
        original_content = "# ORIGINAL\n原始内容\nreferences: 重要"
        skill_path_list, candidate_root = _setup(
            tmpdir,
            source_skills={
                "SkillA": {
                    "SKILL.md": original_content,
                    "references": "# ORIG REF\n",
                    "extra.txt": "orig extra\n",
                },
            },
            candidate_skills={
                "SkillA": {
                    "SKILL.md": "# CANDIDATE OPT\n优化建议\nreferences: 极少",
                    "references": "# CAND REF\n",
                    "extra.txt": "cand extra\n",
                },
            },
        )
        # 1. Backup
        backup_root = tmpdir / "backup"
        backup_user_source(skill_path_list, backup_root)

        # 2. Replace (eval 期间用户源 = candidate)
        replace_candidate_to_user_source(candidate_root, skill_path_list)
        src_after_replace = Path(skill_path_list[0]).read_text(encoding="utf-8")
        r.assert_eq("replace 后用户源 = candidate",
                    "# CANDIDATE OPT\n优化建议\nreferences: 极少",
                    src_after_replace)

        # 3. Restore (eval 后用户源 = 原始)
        result = restore_user_source_from_backup(backup_root, skill_path_list)
        r.assert_eq("restored = 1", 1, len(result["restored"]))
        r.assert_eq("failed = 0", 0, len(result["failed"]))

        src_after_restore = Path(skill_path_list[0]).read_text(encoding="utf-8")
        r.assert_eq("restore 后用户源 = 原始",
                    original_content,
                    src_after_restore)
        # 附属文件也恢复
        src_dir = Path(skill_path_list[0]).parent
        r.assert_eq("references 恢复", "# ORIG REF\n",
                    (src_dir / "references" / "r1.md").read_text(encoding="utf-8"))
        r.assert_eq("extra.txt 恢复", "orig extra\n",
                    (src_dir / "extra.txt").read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_loop_K_candidates():
    """循环 K 候选：每次 candidate_eval 完都应还原为原始;最终用户源 = 原始"""
    print("\n[测试 4] K 候选循环：每次还原,最终用户源 = 原始")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_loop_"))
    try:
        original_content = "# ORIGINAL\n基线\n"
        skill_path_list, _ = _setup(
            tmpdir,
            source_skills={
                "SkillA": {"SKILL.md": original_content},
            },
        )
        backup_root = tmpdir / "backup"
        backup_user_source(skill_path_list, backup_root)

        # 模拟 K 个候选循环
        for k in range(1, 6):
            cand_root = tmpdir / f"candidate_{k}"
            cand_root.mkdir()
            cand_dir = cand_root / "SkillA"
            cand_dir.mkdir()
            (cand_dir / "SKILL.md").write_text(f"# CANDIDATE {k}\n第 {k} 个候选\n",
                                               encoding="utf-8")

            # eval 前：candidate → 用户源
            replace_candidate_to_user_source(cand_root, skill_path_list)
            src_during_eval = Path(skill_path_list[0]).read_text(encoding="utf-8")
            r.assert_eq(f"第 {k} 候选 eval 中用户源 = candidate {k}",
                        f"# CANDIDATE {k}\n第 {k} 个候选\n",
                        src_during_eval)

            # eval 后：恢复用户源
            restore_user_source_from_backup(backup_root, skill_path_list)
            src_after = Path(skill_path_list[0]).read_text(encoding="utf-8")
            r.assert_eq(f"第 {k} 候选 eval 后用户源恢复",
                        original_content,
                        src_after)

        # 全部循环结束后：用户源仍是原始
        final = Path(skill_path_list[0]).read_text(encoding="utf-8")
        r.assert_eq("K 候选后用户源 = 原始", original_content, final)
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_partial_skills_in_candidate():
    """候选只有部分 Skill:替换时缺的跳过,有的覆盖"""
    print("\n[测试 5] 部分 Skill 候选：缺的跳过")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_part_"))
    try:
        skill_path_list, _ = _setup(
            tmpdir,
            source_skills={
                "SkillA": {"SKILL.md": "# ORIG A\n"},
                "SkillB": {"SKILL.md": "# ORIG B\n"},
            },
            candidate_skills={
                "SkillA": {"SKILL.md": "# CAND A\n"},
                # SkillB 不在候选里
            },
        )
        backup_root = tmpdir / "backup"
        backup_user_source(skill_path_list, backup_root)

        cand_root = tmpdir / "candidate_partial"
        cand_root.mkdir()
        (cand_root / "SkillA").mkdir()
        (cand_root / "SkillA" / "SKILL.md").write_text("# CAND A\n", encoding="utf-8")

        result = replace_candidate_to_user_source(cand_root, skill_path_list)
        r.assert_eq("replaced = 1 (SkillA)", 1, len(result["replaced"]))
        r.assert_eq("skipped = 1 (SkillB)", 1, len(result["skipped"]))

        # SkillA 已覆盖
        src_a = Path(skill_path_list[0]).read_text(encoding="utf-8")
        r.assert_eq("SkillA 已覆盖", "# CAND A\n", src_a)
        # SkillB 未变
        src_b = Path(skill_path_list[1]).read_text(encoding="utf-8")
        r.assert_eq("SkillB 未变", "# ORIG B\n", src_b)

        # 恢复后两者都回原状
        restore_user_source_from_backup(backup_root, skill_path_list)
        r.assert_eq("SkillA 恢复", "# ORIG A\n",
                    Path(skill_path_list[0]).read_text(encoding="utf-8"))
        r.assert_eq("SkillB 恢复", "# ORIG B\n",
                    Path(skill_path_list[1]).read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_backup_overwrite_existing():
    """backup_user_source: 重复调用应覆盖旧备份（不留陈旧）"""
    print("\n[测试 6] backup 覆盖旧备份")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_bkovr_"))
    try:
        skill_path_list, _ = _setup(
            tmpdir,
            source_skills={"SkillA": {"SKILL.md": "# NEW ORIGINAL\n"}},
        )
        backup_root = tmpdir / "backup"

        # 第一次备份
        backup_user_source(skill_path_list, backup_root)
        r.assert_eq("第 1 次 backup",
                    "# NEW ORIGINAL\n",
                    (backup_root / "SkillA" / "SKILL.md").read_text(encoding="utf-8"))

        # 修改用户源
        src_dir = Path(skill_path_list[0]).parent
        (src_dir / "SKILL.md").write_text("# MODIFIED\n", encoding="utf-8")

        # 第二次备份应覆盖
        backup_user_source(skill_path_list, backup_root)
        r.assert_eq("第 2 次 backup 已覆盖旧备份",
                    "# MODIFIED\n",
                    (backup_root / "SkillA" / "SKILL.md").read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_restore_missing_backup_is_safe():
    """restore_user_source_from_backup: 备份目录不存在 → 不抛异常,返回 failed"""
    print("\n[测试 7] restore 备份目录缺失不抛异常")
    r = TestRunner()
    tmpdir = Path(tempfile.mkdtemp(prefix="test_eval_safe_"))
    try:
        skill_path_list, _ = _setup(
            tmpdir,
            source_skills={"SkillA": {"SKILL.md": "# ORIGINAL\n"}},
        )
        missing_backup = tmpdir / "no_such_backup"
        result = restore_user_source_from_backup(missing_backup, skill_path_list)
        r.assert_true("返回 reason 字段", "reason" in result)
        r.assert_eq("restored = 0", 0, len(result["restored"]))
        # 用户源不变
        r.assert_eq("用户源未被改动", "# ORIGINAL\n",
                    Path(skill_path_list[0]).read_text(encoding="utf-8"))
        r.summary()
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


if __name__ == "__main__":
    print("=" * 60)
    print("eval 时拷贝能力验证（backup_user_source / replace / restore）")
    print("=" * 60)
    test_backup_user_source_full()
    test_replace_candidate_to_user_source_overwrite()
    test_full_cycle_backup_replace_restore()
    test_loop_K_candidates()
    test_partial_skills_in_candidate()
    test_backup_overwrite_existing()
    test_restore_missing_backup_is_safe()
    print("\n所有 7 个测试套件通过 ✅")