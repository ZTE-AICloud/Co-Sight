"""
Skill 管理模块
==============

负责 Skill 文件的备份、恢复、快照、复制、diff 等操作。

职责边界：
- Skill 路径解析（--skill-paths 解析、SKILL.md 定位）
- Skill 文件复制（拷贝到 workspace/baseline）
- Skill 备份/恢复（原始目录备份，任务结束后恢复）
- Skill 快照（内存快照，用于候选间快速恢复）
- Skill diff（对比 before/after 变更）
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List

# ── 路径解析 ──────────────────────────────────────────────

def parse_skill_paths(raw: str) -> list:
    """解析 --skill-paths 字符串为 Skill 路径列表。

    支持两种格式：
    - 目录路径：自动追加 SKILL.md
    - 文件路径：直接使用
    """
    if not raw:
        return []
    # 先规范化：去除换行符和多余空白
    raw = raw.replace("\n", "").replace("\r", "")
    paths = []
    for p in raw.split(","):
        # 去除首尾空白后，也清理路径中间连续的空格
        p = re.sub(r"\s+", "", p.strip())
        if not p:
            continue
        pp = Path(p).resolve()
        if pp.is_file():
            paths.append(str(pp))
        elif pp.is_dir():
            skill_md = pp / "SKILL.md"
            if skill_md.is_file():
                paths.append(str(skill_md))
            else:
                print(f"  ⚠️ 跳过无效目录（无 SKILL.md）: {p}")
        else:
            print(f"  ⚠️ 跳过无效路径: {p}")
    return paths


def make_skill_args(base_args, skill_path: str) -> object:
    """基于已有 args 创建指向单个 Skill 的新 args 对象"""
    import copy
    new_args = copy.copy(base_args)
    new_args.skill_path = skill_path
    # Agent 模式：传递原始 skill 路径（非 workspace 副本），使 target_skill_path 正确
    skill_paths = getattr(base_args, 'skill_paths', None)
    if skill_paths:
        _parsed = parse_skill_paths(skill_paths) if isinstance(skill_paths, str) else skill_paths
        new_args.skill_paths_original = _parsed
        if not getattr(new_args, 'original_skill_path', None):
            new_args.original_skill_path = _parsed[0] if _parsed else skill_path
    return new_args


# ── 文件复制 ──────────────────────────────────────────────

def copy_skill_files(skill_path: str, dest_dir: Path):
    """将 Skill 文件（SKILL.md + 附件）拷贝到目标目录。

    扫描 SKILL.md 同级所有子目录（除特殊隐藏目录外）一并拷贝，
    避免硬编码 references/scripts/templates 等导致漏文件。
    """
    src = Path(skill_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Skill 文件不存在: {src}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest_dir / src.name))

    # 拷贝 Skill 目录下的所有子目录（兼容 references/reference/scripts/templates/prompts/agents 等命名）
    parent = src.parent
    skip_names = {".git", "__pycache__", "node_modules", ".venv"}
    if parent.is_dir():
        for entry in parent.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue
            if entry.name in skip_names:
                continue
            dest_subdir = dest_dir / entry.name
            if dest_subdir.exists():
                shutil.rmtree(str(dest_subdir))
            shutil.copytree(str(entry), str(dest_subdir))


def stage_skills_for_baseline(baseline_dir: Path, skill_paths: List[str]):
    """拷贝所有 Skill 到 baseline/skill/{name}/。"""
    for sp in skill_paths:
        name = Path(sp).parent.name
        src = Path(sp).resolve().parent
        dest = baseline_dir / "skill" / name
        if src.exists() and not dest.exists():
            shutil.copytree(str(src), str(dest))


# ── 备份/恢复 ─────────────────────────────────────────────

def backup_skill_dir(src_dir: Path, backup_dir: Path) -> None:
    """备份 skill 目录完整内容到 backup_dir"""
    if backup_dir.exists():
        shutil.rmtree(str(backup_dir))
    if src_dir.exists():
        shutil.copytree(str(src_dir), str(backup_dir))


def restore_skill_dir(src_dir: Path, backup_dir: Path, dest_dir: Path) -> None:
    """从备份完整替换目标目录"""
    if dest_dir.exists():
        shutil.rmtree(str(dest_dir))
    if backup_dir.exists():
        shutil.copytree(str(backup_dir), str(dest_dir))


def backup_all_skills(skill_path_list: list, skill_registry: dict, agent_dir: Path) -> Path:
    """备份所有 skill 的完整内容（不限于 SKILL.md）到原始 skill 目录内的 .skillx_backup/

    返回备份根目录，所有任务结束后调用 restore_all_skills 恢复。
    """
    # 备份到第一个 skill 的父目录的父目录（原始 skills/ 目录）下
    first_sp = skill_path_list[0]
    backup_root = Path(first_sp).resolve().parent.parent / ".skillx_backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    for sp in skill_path_list:
        name = Path(sp).parent.name
        src_dir = Path(skill_registry[name]).parent
        backup_dir = backup_root / name
        backup_skill_dir(src_dir, backup_dir)
        print(f"  📦 已备份原始 skill: {name} -> {backup_dir}")
    return backup_root


def restore_all_skills(backup_root: Path, skill_registry: dict, cleanup: bool = True) -> bool:
    """从备份恢复所有 skill 目录（完整目录替换回原始路径）

    Args:
        backup_root: 备份根目录
        skill_registry: skill 名称到原始路径的映射
        cleanup: 是否在恢复后清理备份目录（默认 True）

    Returns:
        是否成功恢复至少一个 skill
    """
    if not backup_root or not backup_root.exists():
        return False
    restored_count = 0
    for backup_dir in sorted(backup_root.iterdir()):
        if not backup_dir.is_dir():
            continue
        name = backup_dir.name
        # 恢复到 skill_registry 中的原始路径
        dest_dir = Path(skill_registry[name]).parent
        restore_skill_dir(backup_dir, backup_dir, dest_dir)
        print(f"  🔙 已恢复 skill: {name} -> {dest_dir}")
        restored_count += 1
    if cleanup:
        shutil.rmtree(str(backup_root))
        print(f"  🧹 已清理备份目录: {backup_root}")
    return restored_count > 0


# ── 快照 ──────────────────────────────────────────────────

def save_skill_copy(skill_path: str) -> dict:
    """保存 Skill 文件及其附件目录的快照（内存快照，用于候选间快速恢复）"""
    p = Path(skill_path)
    snap = {"SKILL.md": p.read_text(encoding="utf-8")}
    for subdir in ["references", "scripts", "prompts", "agents"]:
        src = p.parent / subdir
        if src.exists():
            snap[subdir] = {f.name: f.read_text(encoding="utf-8") for f in src.iterdir() if f.is_file()}
    return snap


def restore_skill_copy(snapshots: dict, skill_registry: dict):
    """恢复 Skill 文件及其附件目录"""
    for name, snap in snapshots.items():
        skill_path = Path(skill_registry[name])
        if "SKILL.md" in snap:
            skill_path.write_text(snap["SKILL.md"], encoding="utf-8")
        for subdir, files in snap.items():
            if subdir == "SKILL.md":
                continue
            dest_dir = skill_path.parent / subdir
            dest_dir.mkdir(parents=True, exist_ok=True)
            for fname, content in files.items():
                (dest_dir / fname).write_text(content, encoding="utf-8")


# ── Diff ──────────────────────────────────────────────────

def skill_md_diff(agent_dir: Path, round_num: int, cand_id: int, skill_name: str) -> dict:
    """对比 round_N_before_skill/skill/{name}/SKILL.md 与 round_N/candidate_K/skill/{name}/SKILL.md。

    返回 {"added": int, "removed": int, "changed_lines": int, "diff_text": str}。
    - 行数统计基于行级 set 差集（统计意义够用）
    - diff_text 是 unified diff 格式（含 @@ hunk 头），用于 5.1 关键修改 章节直接渲染
    """
    import difflib
    before_md = agent_dir / f"round_{round_num}" / f"round_{round_num}_before_skill" / "skill" / skill_name / "SKILL.md"
    after_md = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}" / "skill" / skill_name / "SKILL.md"
    if not before_md.exists() or not after_md.exists():
        return {"added": 0, "removed": 0, "changed_lines": 0, "diff_text": ""}
    try:
        before_text = before_md.read_text(encoding="utf-8")
        after_text = after_md.read_text(encoding="utf-8")
    except Exception:
        return {"added": 0, "removed": 0, "changed_lines": 0, "diff_text": ""}
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)
    before_set = set(before_lines)
    after_set = set(after_lines)
    added = len(after_set - before_set)
    removed = len(before_set - after_set)
    diff_text = "".join(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"before/{skill_name}/SKILL.md",
        tofile=f"candidate_{cand_id}/{skill_name}/SKILL.md",
    ))
    return {
        "added": added,
        "removed": removed,
        "changed_lines": added + removed,
        "diff_text": diff_text,
    }


def extract_modified_sections(agent_dir: Path, round_num: int, skill_name: str) -> list:
    """从 diff 中提取被修改的 H2 章节标题（## xxx）。

    逻辑：取所有 changed lines，再在 before/after 中分别找到它们最近的 H2 标题，取并集。
    """
    before_md = agent_dir / f"round_{round_num}" / f"round_{round_num}_before_skill" / "skill" / skill_name / "SKILL.md"
    if not before_md.exists():
        return []
    try:
        before_text = before_md.read_text(encoding="utf-8")
    except Exception:
        return []
    # 在所有候选里找任一被改的版本
    sections = set()
    for cid in range(1, 10):
        after_md = agent_dir / f"round_{round_num}" / f"candidate_{cid}" / "skill" / skill_name / "SKILL.md"
        if not after_md.exists():
            continue
        try:
            after_text = after_md.read_text(encoding="utf-8")
        except Exception:
            continue
        if before_text == after_text:
            continue
        # 找差异行所在 H2 章节
        before_lines = before_text.splitlines()
        after_lines = after_text.splitlines()
        before_set = set(before_lines)
        after_set = set(after_lines)
        changed = (before_set - after_set) | (after_set - before_set)
        for text in (before_text, after_text):
            current_h2 = None
            for line in text.splitlines():
                m = re.match(r"^##\s+(.+?)\s*$", line)
                if m:
                    current_h2 = m.group(1).strip()
                # 看 changed 中是否有这一行
                if line in changed and current_h2:
                    sections.add(current_h2)
        if sections:
            break
    return sorted(sections)


# ── 用户源 eval 时拷贝（备份/恢复/覆盖） ───────────────
# 复用下方 backup_skill_dir / restore_skill_dir 原语,避免 shutil.copytree+rmtree
# 模式在多处重复。仅增加 skill_path_list 维度的迭代逻辑,核心拷贝走原语。
#
# 2026-07 防御链改造:新增 4 个原语替代了原 .13+ 硬约束 disabled 的 3 个函数。
# 关键不变式：原路径 byte-equal 初始状态(异常退出也成立,经 atexit/signal handler 兜底)。
# 备份目录 {SkillName}.bak/ 放在 skill 同级;整轮任务期间永远不删,任务成功结束才清理。


def backup_skill_to_bak(
    skill_path_list: list,
    skill_registry: dict,
    *,
    force: bool = False,
) -> dict:
    """init 阶段一次性备份每个 skill 到同级 {SkillName}.bak/。

    Args:
        skill_path_list: 业务方传入的 SKILL.md 路径列表
        skill_registry: skill_name → workspace_skill_path 的映射(本函数实际用 skill_path_list 派生)
        force: False(默认)= 已存在 .bak 跳过;True= 重新备份覆盖

    Returns:
        {"backup_roots": {name: bak_path}, "backed_up": [...], "skipped": [...]}

    Raises:
        FileNotFoundError: skill 目录不存在
    """
    backup_roots: dict[str, str] = {}
    backed_up: list[str] = []
    skipped: list[str] = []

    for sp in skill_path_list:
        name = Path(sp).parent.name
        src_dir = Path(sp).parent
        bak_dir = src_dir.parent / f"{name}.bak"

        if bak_dir.exists() and not force:
            skipped.append(name)
            backup_roots[name] = str(bak_dir)
            print(f"  ⏭️  跳过 {name}: .bak 已存在(信任旧备份)")
            continue

        if not src_dir.exists():
            raise FileNotFoundError(f"skill 目录不存在: {src_dir}")

        backup_skill_dir(src_dir, bak_dir)
        backup_roots[name] = str(bak_dir)
        backed_up.append(name)
        print(f"  📦 备份 {name} → {bak_dir}")

    return {"backup_roots": backup_roots, "backed_up": backed_up, "skipped": skipped}


def restore_skill_from_bak(
    skill_path_list: list,
    skill_registry: dict,
    *,
    cleanup: bool = False,
) -> dict:
    """从 {SkillName}.bak/ 恢复到原路径。

    Args:
        skill_path_list: 业务方传入的 SKILL.md 路径列表
        skill_registry: skill_name → workspace_skill_path 的映射
        cleanup: True= 同时删 .bak(任务成功结束用);False= 保留 .bak

    Returns:
        {"restored": [name...], "missing": [name...], "failed": [(name, err)...]}

    Raises:
        FileNotFoundError: cleanup=False 模式下任何 skill 缺 .bak(防"无备份覆盖后无法恢复")
    """
    restored: list[str] = []
    missing: list[str] = []
    failed: list[tuple[str, str]] = []

    for sp in skill_path_list:
        name = Path(sp).parent.name
        src_dir = Path(sp).parent
        bak_dir = src_dir.parent / f"{name}.bak"

        if not bak_dir.exists():
            missing.append(name)
            continue

        try:
            restore_skill_dir(src_dir, bak_dir, src_dir)
            restored.append(name)
            print(f"  🔙 恢复 {name} ← {bak_dir}")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  ⚠️ 恢复失败 {name}: {e}")
            continue

        if cleanup:
            shutil.rmtree(str(bak_dir), ignore_errors=True)
            print(f"  🧹 清理 .bak: {bak_dir}")

    if missing and not cleanup:
        raise FileNotFoundError(
            f"以下 skill 无 .bak 备份,无法恢复: {missing}。"
            f"如确认无需恢复,可传 cleanup=True 忽略。"
        )

    return {"restored": restored, "missing": missing, "failed": failed}


def replace_skill_with_optimized(
    skill_registry: dict,
    optimized_skill_dir: Path,
) -> dict:
    """覆盖式拷贝 optimized skill 到 user source。

    前置校验:.bak 必须存在(防止无备份覆盖)。否则 fail-fast。

    Args:
        skill_registry: skill_name → workspace_skill_path 的映射(用 skill_name 派生原路径)
        optimized_skill_dir: 优化后的 skill 根目录(应含以 skill_name 命名的子目录)

    Returns:
        {"replaced": [name...], "failed": [(name, err)...]}

    Raises:
        FileNotFoundError: 前置校验失败(.bak 不存在)
    """
    replaced: list[str] = []
    failed: list[tuple[str, str]] = []

    for name, orig_skill_path in skill_registry.items():
        orig_dir = Path(orig_skill_path).parent
        bak_dir = orig_dir.parent / f"{name}.bak"
        optimized_dir = Path(optimized_skill_dir) / name

        if not bak_dir.exists():
            raise FileNotFoundError(
                f"前置校验失败:{name} 无 .bak 备份({bak_dir} 不存在),"
                f"拒绝覆盖原路径。请先调 backup_skill_to_bak 创建 .bak。"
            )

        if not optimized_dir.exists():
            failed.append((name, f"optimized dir 不存在: {optimized_dir}"))
            print(f"  ⚠️ optimized 缺失 {name}: {optimized_dir}")
            continue

        try:
            if orig_dir.exists():
                shutil.rmtree(str(orig_dir))
            shutil.copytree(str(optimized_dir), str(orig_dir))
            replaced.append(name)
            print(f"  ✅ 覆盖 {name}: {optimized_dir} → {orig_dir}")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  ⚠️ 覆盖失败 {name}: {e}")

    return {"replaced": replaced, "failed": failed}


def cleanup_skill_bak(skill_path_list: list) -> dict:
    """任务成功结束时统一清 .bak(走决策 4:成功才清,异常保留)。

    Args:
        skill_path_list: 业务方传入的 SKILL.md 路径列表

    Returns:
        {"cleaned": [name...], "missing": [name...]}
    """
    cleaned: list[str] = []
    missing: list[str] = []

    for sp in skill_path_list:
        name = Path(sp).parent.name
        bak_dir = Path(sp).parent.parent / f"{name}.bak"
        if bak_dir.exists():
            shutil.rmtree(str(bak_dir), ignore_errors=True)
            cleaned.append(name)
            print(f"  🧹 清 .bak: {bak_dir}")
        else:
            missing.append(name)

    return {"cleaned": cleaned, "missing": missing}


# ── 旧 API(已 deprecated,保留仅供旧 import 兼容) ──────
# 2026-07 防御链改造:以下 3 个函数被 backup_skill_to_bak /
# restore_skill_from_bak / replace_skill_with_optimized 替代。
# 保留签名只为不破坏旧调用方 import,实际永远 early-return 不执行任何 shutil 操作。


def backup_user_source(skill_path_list: list, backup_root: Path) -> dict:
    """每轮开始前备份用户源(eval 时拷贝模式)。

    已 deprecated:由 backup_skill_to_bak 替代(自动派生 .bak 路径,支持 force)。
    保留签名只为不破坏旧调用方 import。
    """
    return {
        "backup_records": [],
        "backup_root": str(backup_root),
        "reason": "DEPRECATED, see backup_skill_to_bak",
    }


def restore_user_source_from_backup(backup_root: Path, skill_path_list: list) -> dict:
    """每个候选 eval 完后从备份恢复用户源。

    已 deprecated:由 restore_skill_from_bak 替代。
    """
    return {
        "restored": [],
        "failed": [],
        "reason": "DEPRECATED, see restore_skill_from_bak",
    }


def replace_candidate_to_user_source(candidate_skill_root: Path, skill_path_list: list) -> dict:
    """每个候选 eval 前覆盖到用户源(eval 实际读用户源)。

    已 deprecated:由 replace_skill_with_optimized 替代(前置校验 .bak 存在)。
    """
    return {
        "replaced": [],
        "skipped": skill_path_list,
        "reason": "DEPRECATED, see replace_skill_with_optimized",
    }


# ── 候选替换 ──────────────────────────────────────────────

def replace_skill_with_candidate(candidate_skill_root: Path, skill_registry: dict) -> bool:
    """将候选 skill 内容完全替换到所有 skill 的原始路径

    candidate_skill_root 结构：round_N/candidate_K/skill/{SkillName}/...

    Args:
        candidate_skill_root: 候选 skill 根目录
        skill_registry: skill 名称到原始路径的映射

    Returns:
        是否成功替换至少一个 skill
    """
    if not candidate_skill_root.exists():
        return False

    # 先统计候选 skill 实际包含哪些 Skill，避免漏覆盖
    cand_skill_names = {d.name for d in candidate_skill_root.iterdir() if d.is_dir()}
    expected_names = set(skill_registry.keys())

    missing = expected_names - cand_skill_names
    if missing:
        print(f"  ⚠️ 候选 skill 缺少部分 Skill: {sorted(missing)}（不覆盖这些的原始路径）")

    replaced_count = 0
    for cand_skill_dir in sorted(candidate_skill_root.iterdir()):
        if not cand_skill_dir.is_dir():
            continue
        name = cand_skill_dir.name
        if name not in skill_registry:
            print(f"  ⚠️ 候选中包含未知 Skill: {name}，跳过")
            continue
        dest_dir = Path(skill_registry[name]).parent
        if dest_dir.exists():
            shutil.rmtree(str(dest_dir))
        shutil.copytree(str(cand_skill_dir), str(dest_dir))
        print(f"  ✅ 覆盖 Skill: {name} -> {dest_dir}")
        replaced_count += 1

    return replaced_count > 0
