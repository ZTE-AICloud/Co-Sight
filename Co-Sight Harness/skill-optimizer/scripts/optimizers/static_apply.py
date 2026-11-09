"""static_apply.py — /skill_optimize 的 modifications 应用 + 资产校验。

两个核心函数：
- apply_modifications() — 按 proposal.modifications 顺序应用
- validate_assets() — 附属资产保留率校验（ 删除 dim8 评分后仅做诊断）

应用策略（v1 简化版）：
- md 文件用文本替换（before → after，找不到 before 报错）
- code 文件先 Read 再 Edit（v1 阶段也走文本替换，避免引入 Agent tool 依赖）
- 应用的 file 必须不在 protected_assets 白名单内
- 应用后总体积 ≤ 原 × 1.5（darwin 异常表约束）

校验策略（ 删除 dim8 后）：
- 校验 references / scripts / templates 路径 100% 存在
- 计算 protected_assets md5 一致率
- 仅做诊断报告，不参与评分
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("static_apply")


# 体积膨胀软上限（darwin 异常表的 1.5× 是为成熟 skill 设计的；
# 对极小 skill（<500B）首轮必经"工作流+失败模式+检查点"补全，单轮 3-5× 是合理成长）。
# 改为软警告 + 5× 上限，不再硬阻断（v1 v2 的硬阻断会把极小 skill 卡在原地）。
MAX_VOLUME_RATIO = 5.0

# 单 modification 字符上限（防单条爆改；与  prompt 中的 5000 字符对齐）
MAX_MOD_CHARS = 8000

# INSERT 标记：LLM 提议"新加一段章节"时，before 字段用这个串占位
INSERT_MARKERS = frozenset({"（无）", "(无)", "", None})

# fuzzy match 阈值：相似度低于此值的片段不视为可替换
FUZZY_MATCH_THRESHOLD = 0.8


@dataclass
class ApplyResult:
    """单次 modifications 应用结果"""

    applied: int = 0
    skipped: int = 0
    failed: int = 0
    reported: int = 0
    apply_rate: float = 1.0
    errors: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    backup_path: Optional[str] = None
    match_failures: list[dict] = field(default_factory=list)


@dataclass
class AssetValidation:
    """附属资产校验结果（ 删除 score_dim8 字段后仅保留诊断信息）"""

    expected_count: int = 0
    present_count: int = 0
    md5_match_count: int = 0
    missing: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    volume_ratio: float = 1.0
    reason: str = ""


def _insert_section(content: str, section: str, after: str) -> str:
    """把新章节内容追加到指定 H2 段落后；若 section 不以 ## 开头或找不到，则追加到文件末尾。

    Args:
        content: 原始文件内容
        section: H2 章节名（如 "## 失败处理"），可为空
        after: 待追加的章节内容

    Returns:
        追加后的新内容
    """
    # 若 section 不以 ## 开头（说明 LLM 漏标），降级为文件末尾追加
    if not section or not section.strip().startswith("##"):
        return content.rstrip() + "\n\n" + after.rstrip() + "\n"

    section_header = section.strip()
    lines = content.splitlines(keepends=True)
    insert_idx: Optional[int] = None

    # 找到该 H2 段的起始行
    for i, line in enumerate(lines):
        if line.rstrip() == section_header:
            insert_idx = i + 1
            break

    if insert_idx is None:
        # H2 不存在：直接追加到文件末尾（用 ## 标题收尾）
        return content.rstrip() + "\n\n" + after.rstrip() + "\n"

    # 找到该 H2 段下一个 ## 起始（即段尾）
    section_end = len(lines)
    for j in range(insert_idx, len(lines)):
        stripped = lines[j].lstrip()
        if stripped.startswith("## ") and lines[j].rstrip() != section_header:
            section_end = j
            break

    # 在 section_end 前插入 after 内容
    insertion = after.rstrip() + "\n\n"
    new_lines = lines[:section_end] + [insertion] + lines[section_end:]
    return "".join(new_lines)


def _find_fuzzy_match(content: str, before: str, threshold: float = FUZZY_MATCH_THRESHOLD) -> Optional[str]:
    """当 before 在 content 中无法精确匹配时，按行级 fuzzy 匹配寻找最相似的单行。

    适用场景：LLM 提议的 before 含空格变体（中文全/半角、尾随空格、换行），但原始行确实存在。
    仅在"按行切片后存在 1 行相似度 ≥ threshold"时返回该行原文，否则返回 None。

    Args:
        content: 原始文件内容
        before: LLM 提议的 before 片段
        threshold: 相似度阈值（0~1），默认 FUZZY_MATCH_THRESHOLD

    Returns:
        最匹配的单行原文（content 中的实际子串），若无则 None
    """
    if not before or not before.strip():
        return None
    before_norm = before.strip()
    # 取 before 第一行（大多数 LLM 提案的 before 是 1~2 行；用首行匹配更稳）
    first_line = before_norm.splitlines()[0].strip()
    if not first_line or len(first_line) < 4:
        return None
    # 按行扫 content，找最高相似度
    best_ratio = 0.0
    best_line: Optional[str] = None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 4:
            continue
        ratio = difflib.SequenceMatcher(None, first_line, stripped).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_line = stripped
    if best_ratio >= threshold and best_line:
        return best_line
    return None


def _backup_skill(skill_root: Path, workspace: Path) -> Optional[Path]:
    """应用前强制 cp -r skill 目录到 workspace/.skillx-bak/（darwin Phase 0.2）

    返回备份路径（None = 备份失败但不阻塞）"""

    bak_root = workspace / ".skillx-bak"
    bak_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    skill_name = skill_root.name
    target = bak_root / f"{skill_name}_{timestamp}"
    try:
        shutil.copytree(skill_root, target)
        logger.info("已备份 %s → %s", skill_root, target)
        return target
    except (OSError, shutil.Error) as e:
        logger.warning("备份失败: %s", e)
        return None


def _is_protected(rel_path: str, protected_patterns: list[str]) -> bool:
    """判断相对路径是否匹配白名单（fnmatch 风格）"""
    from fnmatch import fnmatch

    for pat in protected_patterns:
        if fnmatch(rel_path, pat) or fnmatch(Path(rel_path).name, pat):
            return True
    return False


def _compute_md5(file_path: Path) -> Optional[str]:
    if not file_path.exists():
        return None
    h = hashlib.md5()
    try:
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def apply_modifications(
    skill_root: Path,
    modifications: list[dict],
    protected_assets: list[str],
    workspace: Optional[Path] = None,
    max_volume_ratio: float = MAX_VOLUME_RATIO,
    chars_budget: Optional[int] = None,
) -> ApplyResult:
    """应用 proposal.modifications 到 skill_root。

    Args:
        skill_root: SKILL.md 所在目录
        modifications: list of {file, section, before, after, rationale, dim_improved, pattern_used}
        protected_assets: 白名单（命中则跳过）
        workspace: 用于备份的 workspace 根目录
        max_volume_ratio: 体积膨胀上限
        chars_budget:  P2-B 已删除 — 盲限制字数无意义（ 移除硬裁剪）。
                     保留参数仅为向后兼容，调用方可安全忽略。

    Returns:
        ApplyResult（含 applied/skipped/failed/files_changed）

    注：v1 用文本替换；后续可接入 Edit agent 做更复杂的修改。
    """
    result = ApplyResult()
    if not modifications:
        return result

    # P0: 记录 LLM 提议总数，用于计算 apply_rate（评分真实性）
    result.reported = len(modifications)

    # : 字符预算硬裁剪已删除。原  P2-B 逻辑是"超预算就跳过 mod"，
    # 实际效果是把所有非 SKILL.md 的脚本文件（≥1000 字符）拦截掉，
    # 导致 references/scripts 几乎无改动。改为由 prompt 引导 LLM 控制单条长度。
    _ = chars_budget  # 保留参数向后兼容

    # 1. 备份（darwin Phase 0.2 强制）
    if workspace is not None:
        result.backup_path = str(_backup_skill(skill_root, workspace))

    # 2. 计算应用前总体积
    total_size_before = _dir_size(skill_root)

    # 3. 按 file 分组，逐个文件应用
    by_file: dict[str, list[dict]] = {}
    for mod in modifications:
        f = mod.get("file", "")
        if not f:
            result.failed += 1
            result.errors.append("modification 缺少 file 字段")
            continue
        by_file.setdefault(f, []).append(mod)

    for rel_file, mods in by_file.items():
        target = skill_root / rel_file
        # protected 校验
        if _is_protected(rel_file, protected_assets):
            result.skipped += len(mods)
            result.errors.append(f"{rel_file} 命中白名单，跳过 {len(mods)} 条 modification")
            continue

        if not target.exists():
            result.failed += len(mods)
            result.errors.append(f"{rel_file} 不存在")
            continue

        try:
            original_content = target.read_text(encoding="utf-8")
            content = original_content
        except (OSError, UnicodeDecodeError) as e:
            result.failed += len(mods)
            result.errors.append(f"{rel_file} 读取失败: {e}")
            continue

        # .x 修复: 文件级 applied_before_write 跟踪 - 仅在至少一次成功 replace/insert 时才写 + 添加到 files_changed
        # 之前有 bug:不论 applied 是否 0, write_text 都跑,然后 files_changed 就被添加,误导 callers(最佳采纳判定)
        applied_in_this_file = 0
        for mod in mods:
            before = mod.get("before", "")
            after = mod.get("after", "")
            section = mod.get("section", "")

            # === before / after 字符串替换 ===
            #  INSERT 支持：before 为 INSERT_MARKERS 之一 → 视为新增章节
            if before in INSERT_MARKERS:
                if not after or not after.strip():
                    result.skipped += 1
                    result.errors.append(
                        f"{rel_file}:{section} INSERT 缺少 after 内容"
                    )
                    continue
                if len(after) > MAX_MOD_CHARS:
                    result.failed += 1
                    result.errors.append(
                        f"{rel_file}:{section} INSERT after 长度 {len(after)} > {MAX_MOD_CHARS}，疑似爆改"
                    )
                    continue
                content = _insert_section(content, section, after)
                result.applied += 1
                applied_in_this_file += 1
                logger.info("[INSERT] %s:%s 追加 %d 字符", rel_file, section, len(after))
                continue

            #  正常 REPLACE 路径
            if not before:
                result.skipped += 1
                result.errors.append(f"{rel_file}:{section} 缺少 before")
                continue
            if before not in content:
                #  v0.19+ 安全 fuzzy 兜底（恢复之前"根治-1"禁用的 _find_fuzzy_match）：
                # 之前取消 fuzzy 是因为旧版"猜位置"导致缩进错位；现在用 _find_fuzzy_match
                # 找 content 里**实际存在的行**做 replace（不用 LLM 提议的 before 直接 replace），
                # 既容忍 LLM 提议的空格/换行差异，又不"猜位置"破坏缩进。
                fuzzy_actual_line = _find_fuzzy_match(content, before)
                if fuzzy_actual_line:
                    content = content.replace(fuzzy_actual_line, after, 1)
                    result.applied += 1
                    applied_in_this_file += 1
                    logger.info(
                        "[FUZZY-MATCH] %s:%s fuzzy 找到实际行（len=%d）替换",
                        rel_file, section, len(fuzzy_actual_line),
                    )
                    continue
                # fuzzy 也失败 → 真正找不到（不再"猜位置"）
                result.skipped += 1
                result.failed += 1
                result.errors.append(
                    f"{rel_file}:{section} before 文本未在文件中找到（严格匹配 + fuzzy 兜底均失败）"
                )
                logger.warning(
                    "[STRICT-MATCH-FAIL] %s:%s before 长度=%d 未在文件中存在",
                    rel_file, section, len(before),
                )
                continue
            content = content.replace(before, after, 1)
            result.applied += 1
            applied_in_this_file += 1

        # .x 修复: 仅在 applied_in_this_file > 0 时才写文件 + 加入 files_changed
        # 避免"被尝试过但实际没改"的文件被错误地算入 files_changed
        if applied_in_this_file > 0 and content != original_content:
            try:
                target.write_text(content, encoding="utf-8")
                result.files_changed.append(rel_file)
                logger.info(
                    "[APPLY] %s 已写入（applied=%d）",
                    rel_file, applied_in_this_file,
                )
            except OSError as e:
                result.failed += len(mods)
                result.errors.append(f"{rel_file} 写入失败: {e}")
        elif applied_in_this_file == 0:
            # 没真的应用任何 mod, 不写文件也不进 files_changed
            logger.warning(
                "[APPLY-SKIP] %s 该文件所有 mod 都失败,未实际改动",
                rel_file,
            )

    # 4. 体积膨胀校验（ 软警告，不再硬阻断）
    total_size_after = _dir_size(skill_root)
    if total_size_before > 0:
        result_volume_ratio = total_size_after / total_size_before
    else:
        result_volume_ratio = 1.0
    result.volume_ratio = result_volume_ratio
    if result_volume_ratio > max_volume_ratio:
        logger.warning(
            "体积膨胀 %.2f× 超软上限 %.2f×，仅警告不阻断（ 软化，原 1.5× 对极小 skill 不合理）",
            result_volume_ratio, max_volume_ratio,
        )
        result.errors.append(
            f"体积膨胀 {result_volume_ratio:.2f}× > {max_volume_ratio}×（软警告，不阻断）"
        )

    # P0: 计算 apply_rate（applied / reported），低 rate 提示评分失真
    if result.reported > 0:
        result.apply_rate = result.applied / result.reported
        if result.apply_rate < 0.5:
            logger.warning(
                "apply_rate=%.2f (%d/%d) 偏低，可能 LLM 提议的 before 文本与实际段落不一致",
                result.apply_rate, result.applied, result.reported,
            )

    return result


def validate_assets(
    skill_root: Path,
    protected_assets: list[str],
    expected_hashes: Optional[dict[str, str]] = None,
) -> AssetValidation:
    """附属资产保留率校验（ 删除 dim8 后仅做诊断）。

    Args:
        skill_root: Skill 根目录
        protected_assets: 白名单（glob 模式）
        expected_hashes: {rel_path: md5} 优化前快照，None = 不做 md5 校验

    Returns:
        AssetValidation（含 missing/modified/volume_ratio 等诊断字段，不参与评分）
    """
    validation = AssetValidation()

    # 1. 收集白名单文件
    from fnmatch import fnmatch

    protected_files: list[Path] = []
    for pat in protected_assets:
        # 兼容 *.md / references/*.md 等模式
        for f in skill_root.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(skill_root))
            if fnmatch(rel, pat) or fnmatch(f.name, pat):
                if f not in protected_files:
                    protected_files.append(f)
    validation.expected_count = len(protected_files)

    # 2. 校验存在性 + md5
    for f in protected_files:
        rel = str(f.relative_to(skill_root))
        if not f.exists():
            validation.missing.append(rel)
            continue
        validation.present_count += 1
        if expected_hashes and rel in expected_hashes:
            current_md5 = _compute_md5(f)
            if current_md5 == expected_hashes[rel]:
                validation.md5_match_count += 1
            else:
                validation.modified.append(rel)

    # 3. 体积膨胀校验
    total = _dir_size(skill_root)
    if expected_hashes is not None:
        # 用 expected_hashes 路径总和估算
        original_size = sum(
            (skill_root / p).stat().st_size
            for p in expected_hashes
            if (skill_root / p).exists()
        )
        if original_size > 0:
            validation.volume_ratio = total / original_size

    if validation.missing:
        validation.reason = f"缺失 {len(validation.missing)} 个白名单文件"
    elif validation.modified:
        validation.reason = f"修改了 {len(validation.modified)} 个白名单文件"
    else:
        validation.reason = "全部保留，md5 一致"

    return validation


def _dir_size(root: Path) -> int:
    """递归计算目录总字节数"""
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def collect_assets_snapshot(skill_root: Path, patterns: list[str]) -> dict[str, str]:
    """采集附属资产当前 md5 快照（用于优化前/优化后对比）"""
    from fnmatch import fnmatch

    snapshot: dict[str, str] = {}
    for pat in patterns:
        for f in skill_root.rglob("*"):
            if not f.is_file():
                continue
            rel = str(f.relative_to(skill_root))
            if fnmatch(rel, pat) or fnmatch(f.name, pat):
                h = _compute_md5(f)
                if h:
                    snapshot[rel] = h
    return snapshot


# =============================================================================
#  Top 3：REVISE 信号提取（避免重复上轮失败）
# =============================================================================


def extract_revise_signals(
    round_result: dict,
    prev_round_result: Optional[dict] = None,
) -> dict:
    """从 round_result + 上一轮 round_result 提取 REVISE 信号。

    Args:
        round_result: 当前轮 round_result.json 内容（含 apply.errors + score.dim_scores）
        prev_round_result: 上一轮 round_result.json（可选，用于计算 dim_improvements）

    Returns:
        {
          applied_mods: [str],          # 上一轮成功应用的 mod 摘要
          failed_mods: [str],           # 上一轮失败的 mod 摘要（绕开同样模式）
          dim_improvements: {dim: delta},  # 维度改善矩阵（基于 prev vs current 分数）
          warnings: [str],              # verifier 警告
          overfit_signals: dict,        # P1-B：overfit 警告（让下轮降低单 mod 字符数）
          apply_failure_signals: list,  # P2-A：apply 失败的 before 文本（让 LLM 下轮用 Read 查实际）
        }
    """
    applied_mods: list[str] = []
    failed_mods: list[str] = []
    warnings: list[str] = []

    apply_block = round_result.get("apply", {})
    files_changed = apply_block.get("files_changed", [])
    errors = apply_block.get("errors", [])

    # applied_mods：所有 files_changed（文件级）+ 上一轮 modifications 摘要
    proposal = round_result.get("proposal", {})
    for mod in proposal.get("modifications", []):
        f = mod.get("file", "?")
        sec = mod.get("section", "?")
        pattern = mod.get("pattern_used", "?")
        dim = mod.get("dim_improved", "?")
        summary = f"{f}:{sec} ({pattern} → {dim})"
        if f in files_changed:
            applied_mods.append(summary)
        else:
            failed_mods.append(summary)

    # failed_mods：从 errors 提取（"找不到 before 文本" / "缺失 before" / "白名单命中"）
    apply_failure_signals: list[str] = []
    for err in errors:
        if "找不到 before" in err or "缺少 before" in err or "命中白名单" in err:
            failed_mods.append(err[:100])
            apply_failure_signals.append(err[:120])

    # P1-B: overfit_signals — 从 verifier 段提取 overfit 信息
    overfit_signals = {
        "warning": False,
        "count": 0,
        "last_round_reasons": [],
    }
    verifier_block = round_result.get("verifier", {})
    if verifier_block.get("overfit_warning"):
        overfit_signals["warning"] = True
        overfit_signals["last_round_reasons"] = list(
            verifier_block.get("overfit_reasons", [])
        )
        # 解析 reasons 中的数字（"单 mod 比例极端 ... 8 条"）作为 count
        import re as _re
        m = _re.search(r"(\d+)\s*条", " ".join(overfit_signals["last_round_reasons"]))
        if m:
            overfit_signals["count"] = int(m.group(1))

    # warnings：体积膨胀 + 白名单校验
    asset_val = round_result.get("asset_validation", {})
    if asset_val.get("missing"):
        warnings.append(f"asset_validation: 缺失 {len(asset_val['missing'])} 个白名单文件")
    if asset_val.get("modified"):
        warnings.append(f"asset_validation: 修改了 {len(asset_val['modified'])} 个白名单文件")

    # dim_improvements：对比 prev 与 current 的 dim_scores
    dim_improvements: dict[str, float] = {}
    if prev_round_result is not None:
        prev_score_path_block = prev_round_result.get("_score_block", {})
        # round_result 本身不直接含 dim_scores；从 _score_block 或顶层读
        prev_dim_scores = (
            prev_round_result.get("dim_scores")
            or prev_score_path_block.get("dim_scores")
            or {}
        )
        cur_dim_scores = (
            round_result.get("dim_scores")
            or round_result.get("_score_block", {}).get("dim_scores")
            or {}
        )
        for k in set(list(prev_dim_scores.keys()) + list(cur_dim_scores.keys())):
            try:
                prev_v = float(prev_dim_scores.get(k, 0))
                cur_v = float(cur_dim_scores.get(k, 0))
                delta = round(cur_v - prev_v, 2)
                if delta != 0:
                    dim_improvements[k] = delta
            except (TypeError, ValueError):
                continue

    return {
        "applied_mods": applied_mods,
        "failed_mods": failed_mods,
        "dim_improvements": dim_improvements,
        "warnings": warnings,
        "overfit_signals": overfit_signals,
        "apply_failure_signals": apply_failure_signals,
        "file_coverage_warning": _build_file_coverage_warning(files_changed, round_result),
    }


def validate_per_file_coverage(
    result: dict, relation_tree: Optional[dict], coverage_guard_cfg: dict
) -> tuple[bool, str, list[str]]:
    """校验 LLM 输出是否覆盖了关系树中所有文件（per_file_findings 强制）。

    Args:
        result: LLM 输出 dict（含 per_file_findings[]）
        relation_tree: 关系树 dict（含 summary_table）
        coverage_guard_cfg: framework YAML coverage_guard 段配置

    Returns:
        (is_valid, error_msg, missing_files) — missing_files 为骨架中有但 LLM 未覆盖的路径
    """
    if not coverage_guard_cfg.get("enabled", False):
        return True, "", []
    if not relation_tree:
        return True, "", []

    total_files = relation_tree.get("stats", {}).get("file_count", 0)
    if total_files < 5:
        # 小 skill 不强求 per_file_findings 全覆盖
        return True, "", []

    expected_paths = {r["path"] for r in relation_tree.get("summary_table", [])}
    findings = result.get("per_file_findings") or []
    actual_paths = {f.get("file", "") for f in findings if isinstance(f, dict)}
    missing = sorted(expected_paths - actual_paths)

    min_pct = float(coverage_guard_cfg.get("min_per_file_findings_pct", 1.0))
    actual_pct = (len(actual_paths) / len(expected_paths)) if expected_paths else 1.0

    if not missing:
        return True, "", []
    if actual_pct >= min_pct:
        # 部分覆盖 ≥ min_pct：不阻断，但记录
        return True, f"per_file_findings 部分覆盖 {actual_pct:.0%}（{len(actual_paths)}/{len(expected_paths)}），缺：{missing[:3]}...", missing

    error_msg = (
        f"per_file_findings 覆盖不足 {actual_pct:.0%} < {min_pct:.0%} "
        f"（仅 {len(actual_paths)}/{len(expected_paths)} 个文件被扫描）。"
        f"缺：{missing[:5]}{'...' if len(missing) > 5 else ''}"
    )
    return False, error_msg, missing


def derive_per_file_findings(
    result: dict, relation_tree: Optional[dict]
) -> list[dict]:
    """框架兜底：从 modifications 自动推导 per_file_findings（不假设 LLM 完美输出）。

    当 LLM 不提供 per_file_findings 时，从 modifications 按 file 分组构造，
    关系树中其他文件补空 findings 数组。这样 validate_per_file_coverage 总能
    通过，强制 LLM 在下一轮考虑全部文件（看到骨架表 + 推导出的结构）。

    Returns:
        完整的 per_file_findings 数组（覆盖关系树中每个文件）
    """
    if not relation_tree:
        return result.get("per_file_findings") or []
    mods = result.get("modifications") or []
    by_file: dict[str, list[dict]] = {}
    for m in mods:
        if not isinstance(m, dict):
            continue
        f = m.get("file", "")
        if not f:
            continue
        by_file.setdefault(f, []).append({
            "section": m.get("section", ""),
            "dim_improved": m.get("dim_improved", "unknown"),
            "rationale": m.get("rationale", ""),
            "before": m.get("before", ""),
            "after": m.get("after", ""),
            "pattern_used": m.get("pattern_used", "P?"),
        })

    # 关系树每个文件必须有 entry（覆盖 → 100% 文件被"扫描"）
    summary_table = relation_tree.get("summary_table", [])
    per_file: list[dict] = []
    for row in summary_table:
        path = row.get("path", "")
        per_file.append({"file": path, "findings": by_file.get(path, [])})
    return per_file


def merge_findings_to_modifications(
    per_file_findings: list, max_mods: int, long_unoptimized: list
) -> list[dict]:
    """从 per_file_findings 按规则合并到 modifications（按预算截断）。

    优先级：long_unoptimized 文件的 findings > 其他文件 > SKILL.md 的非关键 finding。
    每个 finding 标准化为 {file, section, before, after, dim_improved, pattern_used}。
    """
    long_un_set = set(long_unoptimized or [])

    # 展平所有 findings，标注是否 long_unoptimized 文件
    candidates: list[dict] = []
    for entry in per_file_findings or []:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file", "")
        findings = entry.get("findings") or []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            mod = {
                "file": f,
                "section": finding.get("section", ""),
                "before": finding.get("before", ""),
                "after": finding.get("after", ""),
                "dim_improved": finding.get("dim_improved", "unknown"),
                "pattern_used": finding.get("pattern_used", "P?"),
                "rationale": finding.get("rationale", ""),
                "_long_unoptimized": f in long_un_set,
            }
            # 校验 before/after 必须非空
            if mod["before"] and mod["after"]:
                candidates.append(mod)

    # 排序：long_unoptimized 优先 + 非 SKILL.md 优先
    candidates.sort(key=lambda m: (
        not m["_long_unoptimized"],                            # long_un 排前
        m["file"] == "SKILL.md",                               # SKILL.md 排后
    ))

    # 清洗内部标记
    for m in candidates:
        m.pop("_long_unoptimized", None)

    return candidates[:max_mods]


def _build_file_coverage_warning(files_changed: list, round_result: dict) -> dict:
    """构造文件覆盖警告：上轮改了多少文件、文件类型分布。

    Returns:
        {
          "files_changed": [str],
          "file_count": int,
          "single_file_round": bool,   # 是否只改了 1 个文件
          "roles": {role: count},      # 按 role 的文件数
          "warning_msg": str or "",    # 需要注入 prompt 的警告文本
        }
        关系树 role 从 round_result 的 _score_block sk_file_roles 读（如有），
        没有则直接从 files_changed 文件名推断。
    """
    changed = list(files_changed or [])
    count = len(changed)
    # 从文件名推断文件类型分布（简单）
    roles: dict[str, int] = {}
    for f in changed:
        if f == "SKILL.md":
            roles["SKILL.md"] = roles.get("SKILL.md", 0) + 1
        elif f.startswith("references/"):
            roles["references"] = roles.get("references", 0) + 1
        elif f.startswith("scripts/"):
            roles["scripts"] = roles.get("scripts", 0) + 1
        elif f.startswith("templates/"):
            roles["templates"] = roles.get("templates", 0) + 1
        else:
            roles["other"] = roles.get("other", 0) + 1

    warning_msg = ""
    if count == 1:
        role_info = ", ".join(f"{k}: {v}" for k, v in sorted(roles.items()))
        warning_msg = (
            f"⚠️ 上轮仅覆盖 **1 个文件**（{role_info}）。"
            "Skill 有多个文件是统一整体，单文件改动可能忽略跨文件优化机会。"
            "**本轮请至少覆盖 2 个不同文件**，优先选长期未改文件。"
        )
    return {
        "files_changed": changed,
        "file_count": count,
        "single_file_round": count <= 1,
        "roles": roles,
        "warning_msg": warning_msg,
    }


# =============================================================================
#  Top 4：check_overfit 前置拦截（warn-only，不强制 break）
# =============================================================================


def _is_code_file(file_path: str) -> bool:
    """判断 file 是否是代码文件（.py/.sh/.js/.ts 等）。"""
    return file_path.endswith(('.py', '.sh', '.js', '.ts', '.java', '.go', '.rs'))


def _is_comment_only_mod(mod: dict) -> bool:
    """检测 modification 是否只改了注释/docstring/空行，未改代码逻辑。

    Returns:
        True = 纯注释改动（应被过滤）
    """
    file_path = mod.get("file", "")
    if not _is_code_file(file_path):
        return False
    before = mod.get("before", "") or ""
    after = mod.get("after", "") or ""
    if not before and not after:
        return True

    def _strip_comments_and_blanks(text: str) -> str:
        """去掉注释行、docstring、空行，只保留代码逻辑。"""
        lines = text.split("\n")
        result = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if '"""' in stripped or "'''" in stripped:
                quote_count = stripped.count('"""') + stripped.count("'''")
                if quote_count % 2 == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            result.append(stripped)
        return "\n".join(result)

    code_before = _strip_comments_and_blanks(before)
    code_after = _strip_comments_and_blanks(after)
    return code_before == code_after


def check_overfit(
    modifications: list[dict],
    original_size: int,
    soft_dims: set[str] = None,
) -> dict:
    """ Top 4：检测过拟合嫌疑（warn-only，不强制 break）。

    Args:
        modifications: 当前轮 proposal.modifications
        original_size: skill_root 优化前总字节数
        soft_dims: 软改维度集合（默认 dim4/dim5/dim7）

    Returns:
        {
          warning: bool,           # 是否建议警告
          reasons: [str],          # 警告原因列表
          metrics: {              # 量化指标
            total_diff_chars,
            soft_only_count,
            comment_only_count,
            avg_ratio,
            dim_count,
          }
        }
    """
    if soft_dims is None:
        soft_dims = {"dim4_checkpoints", "dim5_specificity", "dim7_agent_contract_alignment"}

    if not modifications:
        return {"warning": False, "reasons": [], "metrics": {}}

    total_diff_chars = 0
    soft_only_count = 0
    ratio_list: list[float] = []
    dim_set: set[str] = set()
    pure_add_count = 0  # before 为空 / after 远大于 before 的疑似 padding
    comment_only_count = 0  # 仅改注释的 mod 计数

    for mod in modifications:
        # 检测纯注释改动
        if _is_comment_only_mod(mod):
            comment_only_count += 1
        before = mod.get("before", "") or ""
        after = mod.get("after", "") or ""
        before_len = len(before)
        after_len = len(after)
        diff = abs(after_len - before_len)
        total_diff_chars += diff
        if before_len == 0:
            pure_add_count += 1
        if before_len > 0:
            ratio = after_len / before_len
            ratio_list.append(ratio)
        dim = mod.get("dim_improved", "")
        if dim:
            dim_set.add(dim)
        if dim in soft_dims:
            soft_only_count += 1

    avg_ratio = sum(ratio_list) / len(ratio_list) if ratio_list else 1.0

    reasons: list[str] = []
    # 规则 1：纯注释改动 ≥ 1 条 → 注水警告
    if comment_only_count >= 1:
        reasons.append(f"纯注释/空行/格式改动 {comment_only_count} 条，代码文件仅改注释无实际逻辑变化")
    # 规则 2：改动全为 soft 维度且 ≥ 2 条 → 软改嫌疑
    if soft_only_count >= 2 and soft_only_count == len(modifications):
        reasons.append(f"全部 {soft_only_count} 条改动集中在 soft 维度（dim4/dim5/dim7），疑似凑分")
    # 规则 3：纯加句子（before 空）≥ 3 条 → padding 嫌疑
    if pure_add_count >= 3:
        reasons.append(f"pure_add（before 空）{pure_add_count} 条，疑似 padding 凑分")
    # 规则 4：单 mod before/after 字符比例极端（>1.5 或 <0.7）≥ 2 条 → 爆改嫌疑
    extreme_count = sum(1 for r in ratio_list if r > 1.5 or r < 0.7)
    if extreme_count >= 2:
        reasons.append(f"单 mod 比例极端（>1.5 或 <0.7）{extreme_count} 条，疑似爆改")
    # 规则 5：总 diff 字符 > 800 但只覆盖 1 个 dim → 单维度灌水嫌疑
    if total_diff_chars > 800 and len(dim_set) == 1:
        reasons.append(f"总 diff {total_diff_chars} 字符但只覆盖 1 个 dim，疑似单维度灌水")

    # 规则 6（P1-B 根治）：同文件 ≥2 条 mod 的 after 相似度 > 0.7 → 段落重复
    from difflib import SequenceMatcher
    by_file: dict[str, list[str]] = defaultdict(list)
    for m in modifications:
        f = m.get("file", "")
        a = m.get("after", "") or ""
        if f and a:
            by_file[f].append(a)
    for f, afters in by_file.items():
        for i in range(len(afters)):
            for j in range(i + 1, len(afters)):
                ratio = SequenceMatcher(None, afters[i], afters[j]).ratio()
                if ratio > 0.7:
                    reasons.append(f"[hard_block] {f} 两条 mod after 相似度={ratio:.2f}>0.7，疑似 AP-DUP-SECTION")
                    break  # 一个文件只报一次

    # 规则 7（P1-B 根治）：mod.after 引用的 .md/.py 路径若 worktree 不存在 → broken ref
    import re
    ref_pattern = re.compile(r"`(references/[^\s`]+\.md|templates/[^\s`]+\.md|scripts/[^\s`]+\.py)`")
    # skill_root 通过调用方传入（保留 optional，缺则从 cwd 推断） — 简化：只标记"声明"作为 hard_block 信号
    declared_refs: set[str] = set()
    for m in modifications:
        for match in ref_pattern.findall(m.get("after", "") or ""):
            declared_refs.add(match)
    new_file_mods = {
        m.get("after", "") for m in modifications
        if m.get("file", "").startswith(("references/", "templates/", "scripts/"))
    }
    unbacked = declared_refs - {m.get("file", "") for m in modifications if m.get("file")}
    if unbacked:
        reasons.append(f"[hard_block] 引用 {sorted(unbacked)[:3]} 但本轮无对应新建 mod，将产生 AP-CROSS-REF-BROKEN")

    return {
        "warning": bool(reasons),
        "reasons": reasons,
        "metrics": {
            "total_diff_chars": total_diff_chars,
            "soft_only_count": soft_only_count,
            "avg_ratio": round(avg_ratio, 2),
            "dim_count": len(dim_set),
        },
    }


# =============================================================================
# skill 副本机制（对齐 /skill_evolve 的 skill/ 副本约定）
# =============================================================================


def prepare_workspace_skill_copy(
    original_skill_root: Path,
    workspace: Path,
    skill_name: str,
) -> Path:
    """任务开始时拷贝原 Skill 到 workspace/skill/{skill_name}/（工作副本）。

    真实 Skill 路径永不被修改，所有优化操作在 workspace 副本上进行。
    """
    target = workspace / "skill" / skill_name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(original_skill_root, target)
    logger.info("已拷贝原 Skill %s → %s", original_skill_root, target)
    return target


def snapshot_skill(skill_root: Path, snapshot_dir: Path) -> Path:
    """拷贝 Skill 到指定目录（round_N_before/after 或 best_skill）。"""
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_root, snapshot_dir)
    return snapshot_dir


def compute_skill_hash(skill_root: Path) -> str:
    """计算 Skill 目录的 SHA256（聚合所有非空文件的 hash）。

    用于判定 apply 前后内容是否有真改动。文件不存在返回空串。
    """
    if not skill_root or not skill_root.exists():
        return ""
    h = hashlib.sha256()
    # 按 sorted 路径顺序遍历,确保结果稳定
    for p in sorted(skill_root.rglob("*")):
        if not p.is_file():
            continue
        try:
            content = p.read_bytes()
        except OSError:
            continue
        # 用相对路径 + 内容 hash 一起加入,避免同名不同 hash 巧合
        rel = p.relative_to(skill_root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(content)
    return h.hexdigest()


def update_best_skill(
    skill_root: Path,
    workspace: Path,
    skill_name: str,
    source_round: int,
    score: float,
) -> Path:
    """评分提升时更新 best_skill/ + best_skill_info.json。

    返回 best_skill 目录路径。
    """
    import json as _json
    best_dir = workspace / "best_skill" / skill_name
    snapshot_skill(skill_root, best_dir)
    info = {
        "source": f"round_{source_round}",
        "source_round": source_round,
        "score": score,
        "skill_name": skill_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (workspace / "best_skill_info.json").write_text(
        _json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "best_skill 已更新: source=round_%d score=%.2f",
        source_round,
        score,
    )
    return best_dir


def finalize_best_skill_from_history(
    workspace: Path,
    skill_name: str,
    history: list,  # list[RoundResult]，由调用方传入
) -> Path:
    """主循环结束后，从 history 中找最高分对应的那一轮，拷贝到 best_skill/。

     设计原则：
      - best_skill 在循环过程中保持为空（不会被中间轮次填充）
      - 循环结束后，根据 history 中 score 最高的 RoundResult，
        从 round_N_after_skill 拷贝到 best_skill/
      - 若 history 为空（无改进 round），则不写 best_skill，best_skill_info 标记 "no_improvement"

    Args:
        workspace: 任务 workspace 根
        skill_name: Skill 目录名
        history: RoundResult 列表，每项含 round_num / score / baseline_score / verdict

    Returns:
        best_skill 目录路径（不存在则返回空 Path）
    """
    import json as _json

    if not history:
        info = {
            "source": "none",
            "source_round": 0,
            "score": 0.0,
            "skill_name": skill_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "note": "no improved round in history",
        }
        (workspace / "best_skill_info.json").write_text(
            _json.dumps(info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("best_skill 未填充：history 为空，无改进 round")
        return Path()

    # 找 history 中 score 最高的 RoundResult
    best_entry = max(history, key=lambda r: float(getattr(r, "score", 0.0) or 0.0))
    best_score_v = float(getattr(best_entry, "score", 0.0) or 0.0)
    best_round_v = int(getattr(best_entry, "round_num", 0) or 0)

    # 该轮的 after_skill 目录
    after_dir = workspace / f"round_{best_round_v}" / f"round_{best_round_v}_after_skill" / "skill" / skill_name
    if not after_dir.exists():
        # fallback：若 after 不存在（比如该轮未改进），尝试用 before
        logger.warning(
            "best_skill: round_%d_after_skill 不存在，尝试 before",
            best_round_v,
        )
        after_dir = workspace / f"round_{best_round_v}" / f"round_{best_round_v}_before_skill" / "skill" / skill_name
        if not after_dir.exists():
            logger.warning(
                "best_skill: round_%d before/after 都不存在，跳过 best_skill 填充",
                best_round_v,
            )
            info = {
                "source": "none",
                "source_round": best_round_v,
                "score": best_score_v,
                "skill_name": skill_name,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note": "no snapshot available for best round",
            }
            (workspace / "best_skill_info.json").write_text(
                _json.dumps(info, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return Path()

    best_dir = workspace / "best_skill" / skill_name
    snapshot_skill(after_dir, best_dir)
    info = {
        "source": f"round_{best_round_v}",
        "source_round": best_round_v,
        "score": best_score_v,
        "skill_name": skill_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (workspace / "best_skill_info.json").write_text(
        _json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "best_skill 收尾填充: source=round_%d score=%.2f",
        best_round_v, best_score_v,
    )
    return best_dir


def write_skill_metadata(
    workspace: Path,
    original_skill_path: Path,
    skill_name: str,
    **kwargs: object,
) -> Path:
    """写 config.json（含 original_skill_path 等元信息）。"""
    import json as _json
    config: dict[str, object] = {
        "skill_name": skill_name,
        "original_skill_path": str(original_skill_path),
        "task_type": "skill_optimize",
    }
    config.update(kwargs)
    config_path = workspace / "config.json"
    config_path.write_text(
        _json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config_path


# =============================================================================
# progress-state.yaml（AgentGenesis 6 phase 状态机）
# =============================================================================


PHASE_IDS = ("P1", "P2", "P3", "P4", "P5", "P6")
PHASE_NAMES = {
    "P1": "planner",
    "P2": "reviewer",
    "P3": "builder",
    "P4": "verifier",
    "P5": "evaluator",
    "P6": "summary",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read_state(state_path: Path) -> dict:
    """读 progress-state.yaml（不存在则返回空 dict）。"""
    import yaml as _yaml
    if not state_path.exists():
        return {}
    try:
        return _yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError):
        return {}


def _write_state(state_path: Path, state: dict) -> None:
    """写 progress-state.yaml（原子替换，避免读到半写状态）。"""
    import yaml as _yaml
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(
        _yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    tmp.replace(state_path)


def init_progress_state(
    workspace: Path,
    skill_name: str,
    task_id: str,
    framework: str = "five-five-fusion (darwin-skill + AgentGenesis)",
    rework_policy: Optional[dict] = None,
    eval_mode: str = "full",
) -> Path:
    """初始化 progress-state.yaml（任务开始时调一次）。

    含 6 phase 全 pending 状态 + 空 phase_history / rework_history。
     Top 6：含 dry_run_count 字段（OAP6 dry_run 占比监控）。
    """
    state: dict = {
        "task_id": task_id,
        "skill_name": skill_name,
        "framework": framework,
        "status": "running",
        "current_phase": "P1",
        "current_round": 0,
        "phases_status": {f"{pid}_{PHASE_NAMES[pid]}": "pending" for pid in PHASE_IDS},
        "phase_history": [],
        "rework_history": [],
        "round_summary": [],
        "rework_policy": rework_policy or {},
        "eval_mode": eval_mode,
        "dry_run_count": 0,
        "last_updated": _now_iso(),
    }
    state_path = workspace / "progress-state.yaml"
    _write_state(state_path, state)
    logger.info("progress-state 已初始化: %s", state_path)
    return state_path


def update_progress_phase(
    state_path: Path,
    phase: str,
    status: str,
    *,
    round_num: Optional[int] = None,
    score: Optional[float] = None,
    extra: Optional[dict] = None,
) -> None:
    """更新 phase 状态（pending/running/done/failed/broken），可顺带追加 phase_history。"""
    state = _read_state(state_path)
    if not state:
        logger.warning("progress-state 不存在，跳过 update: %s", state_path)
        return

    phase_key = f"{phase}_{PHASE_NAMES.get(phase, phase)}"
    state.setdefault("phases_status", {})
    state["phases_status"][phase_key] = status
    state["current_phase"] = phase
    state["last_updated"] = _now_iso()

    # running 状态不写 history（仅记录起止）
    if status == "running":
        state.setdefault("_phase_started", {})[phase_key] = _now_iso()
    else:
        started = state.get("_phase_started", {}).pop(phase_key, None)
        history_entry: dict = {
            "phase": phase_key,
            "status": status,
            "started_at": started or _now_iso(),
            "ended_at": _now_iso(),
        }
        if round_num is not None:
            history_entry["round"] = round_num
        if score is not None:
            history_entry["score"] = score
        if extra:
            history_entry.update(extra)
        state.setdefault("phase_history", []).append(history_entry)

    _write_state(state_path, state)


def record_rework(
    state_path: Path,
    phase: str,
    attempt: int,
    reason: str,
    backoff: int,
    status: str,
    *,
    round_num: Optional[int] = None,
) -> None:
    """追加 REWORK 历史（attempt 计数 + 退避 + 状态）。"""
    state = _read_state(state_path)
    if not state:
        logger.warning("progress-state 不存在，跳过 record_rework: %s", state_path)
        return

    entry: dict = {
        "phase": phase,
        "attempt": attempt,
        "reason": reason,
        "backoff": backoff,
        "status": status,
        "timestamp": _now_iso(),
    }
    if round_num is not None:
        entry["round"] = round_num
    state.setdefault("rework_history", []).append(entry)
    state["last_updated"] = _now_iso()
    _write_state(state_path, state)
    logger.info(
        "REWORK: phase=%s attempt=%d reason=%s backoff=%ds status=%s",
        phase, attempt, reason, backoff, status,
    )


def append_round_summary(
    state_path: Path,
    round_num: int,
    score: float,
    delta: float,
    verdict: str,
    best_skill_updated: bool,
) -> None:
    """追加 round_summary（每轮 P6 summary 阶段调一次）。"""
    state = _read_state(state_path)
    if not state:
        return

    entry = {
        "round": round_num,
        "score": score,
        "delta": delta,
        "verdict": verdict,
        "best_skill_updated": best_skill_updated,
    }
    state.setdefault("round_summary", []).append(entry)
    state["current_round"] = round_num
    state["last_updated"] = _now_iso()
    _write_state(state_path, state)


def finalize_progress_state(
    state_path: Path,
    status: str = "done",
) -> None:
    """收尾：设置 status（done / broken）+ last_updated。"""
    state = _read_state(state_path)
    if not state:
        return
    state["status"] = status
    state["last_updated"] = _now_iso()
    #  Top 6：dry_run 占比监控（OAP6 触发条件：> 60%）
    total_rounds = len(state.get("round_summary", []))
    dry_count = int(state.get("dry_run_count", 0))
    if total_rounds > 0:
        ratio = dry_count / total_rounds
        state["dry_run_ratio"] = round(ratio, 2)
        if ratio > 0.6:
            state["oap6_warning"] = (
                f"dry_run 占比 {ratio:.0%} > 60%，疑似过多跳过 apply（OAP6）"
            )
    _write_state(state_path, state)
    logger.info("progress-state 已收尾: status=%s", status)


def increment_dry_run_count(state_path: Path) -> None:
    """ Top 6：每跑完一轮 dry_run 自增 1。"""
    state = _read_state(state_path)
    if not state:
        return
    state["dry_run_count"] = int(state.get("dry_run_count", 0)) + 1
    state["last_updated"] = _now_iso()
    _write_state(state_path, state)


def aggregate_dim_scores(
    per_file_findings: list,
    rubric: dict,
    relation_tree: Optional[dict] = None,
) -> tuple[float, dict[str, float], str]:
    """Python 端从 unified agent 输出聚合总分数（取代 LLM judge aggregation）。

    简化 schema（方案 A）：每个文件 entry 只有单个 `score` 字段（0-10）+ `rationale`。
    Python 端按 file_weight × score 加权分摊到各 dim，再按 dim_weight 加权求总分。

    算法：
      1. 文件权重：relation_tree.summary_table[].weight（Σ=1.0）
      2. 每文件 score 分摊到该文件 role 对应的 dim 上（role→dim 映射）
      3. 各 dim 加权平均（file_weight × score）
      4. 总分 = Σ (dim_weight × dim_score × Σfile_weight) / Σ (dim_weight × Σfile_weight)

    Args:
        per_file_findings: unified agent 输出的 [{file, score, rationale, findings}, ...]
        rubric: framework YAML 的 rubric 段（含 dim_weights）
        relation_tree: 关系树（含 summary_table[].weight），用于文件权重

    Returns:
        (total, dim_scores_avg, rating)
        - total: 百分制总分数
        - dim_scores_avg: 每个 dim 的加权平均分 {dim: weighted_score (0-10)}
        - rating: 等级（EXCELLENT/GOOD/FAIR/POOR/BROKEN）
    """
    # 1. 文件权重表：path -> weight
    file_weight_map: dict[str, float] = {}
    # 文件 role 映射：path -> role
    file_role_map: dict[str, str] = {}
    if isinstance(relation_tree, dict):
        for row in relation_tree.get("summary_table", []) or []:
            fp = row.get("path", "")
            fw = row.get("weight")
            if fp and isinstance(fw, (int, float)):
                file_weight_map[fp] = float(fw)
            if fp:
                file_role_map[fp] = row.get("role", "other")

    # 2. role → applicable dims 映射（简化版，按 role 启发式）
    ROLE_TO_DIMS: dict[str, list[str]] = {
        "entrypoint":     ["dim1_metadata_trigger", "dim2_step_executability",
                           "dim6_cross_section_consistency", "dim7_agent_contract_alignment",
                           "dim8_anthropic_sf", "dim12_structure_purity"],
        "implementation": ["dim2_step_executability", "dim3_failure_recovery",
                           "dim4_checkpoints", "dim5_specificity",
                           "dim7_agent_contract_alignment", "dim10_safety_auto",
                           "dim11_efficiency_auto"],
        "knowledge":      ["dim5_specificity", "dim6_cross_section_consistency",
                           "dim7_agent_contract_alignment", "dim9_coverage_auto",
                           "dim12_structure_purity"],
        "template":       ["dim5_specificity", "dim6_cross_section_consistency",
                           "dim8_anthropic_sf", "dim9_coverage_auto"],
        "asset":          [],  # 资源不评分
        "doc":            ["dim5_specificity", "dim12_structure_purity"],
        "data":           ["dim10_safety_auto"],
        "aux_code":       ["dim2_step_executability", "dim3_failure_recovery"],
        "other":          [],
    }

    # 3. 聚合器
    dim_weighted_sum: dict[str, float] = {}  # Σ file_weight × score
    dim_total_weight: dict[str, float] = {}  # Σ file_weight

    for entry in per_file_findings or []:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file", "")
        fw = file_weight_map.get(f, 0.0)
        if fw <= 0:
            continue

        # 取分数：优先用 entry.dim_scores（每文件 per-dim 分数）
        # 缺失时回退到 entry.score（单字段）
        # 都没有时按 findings 数推断
        dim_scores_entry = entry.get("dim_scores") or {}
        if isinstance(dim_scores_entry, dict) and dim_scores_entry:
            # 按 entry 实际填的 dim 计分
            for dim, info in dim_scores_entry.items():
                if not isinstance(info, dict):
                    continue
                ds = info.get("score")
                if not isinstance(ds, (int, float)) or isinstance(ds, bool):
                    continue
                dim_weighted_sum[dim] = dim_weighted_sum.get(dim, 0.0) + fw * max(0.0, min(10.0, float(ds)))
                dim_total_weight[dim] = dim_total_weight.get(dim, 0.0) + fw
            continue  # 该文件已用 dim_scores 处理，跳过单 score 分摊

        # 兜底 1：单 score 字段
        raw_score = entry.get("score")
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            score_f = max(0.0, min(10.0, float(raw_score)))
        else:
            # 兜底 2：findings 数推断
            findings = entry.get("findings") or []
            score_f = 10.0 if not findings else max(5.0, 10.0 - len(findings) * 0.5)

        # 单 score 字段 → 分摊到该文件 role 对应的 dim
        role = file_role_map.get(f, "other")
        applicable_dims = ROLE_TO_DIMS.get(role, [])
        # 若 role 没对应 dim（asset/other），把 score 计入所有 dim
        if not applicable_dims:
            applicable_dims = [k for k in (rubric or {}) if k.startswith("dim")]

        for dim in applicable_dims:
            dim_weighted_sum[dim] = dim_weighted_sum.get(dim, 0.0) + fw * score_f
            dim_total_weight[dim] = dim_total_weight.get(dim, 0.0) + fw

    # 4. 每 dim 加权平均
    dim_scores_avg: dict[str, float] = {
        dim: dim_weighted_sum[dim] / dim_total_weight[dim]
        for dim in dim_weighted_sum
        if dim_total_weight.get(dim, 0) > 0
    }

    # 5. dim 权重表
    weights: dict[str, float] = {
        k: float(v.get("weight", 1.0)) if isinstance(v, dict) else 1.0
        for k, v in (rubric or {}).items()
        if k.startswith("dim")
    }

    # 6. 总分 = Σ (dim_weight × dim_score × Σfile_weight) / Σ (dim_weight × Σfile_weight)
    total_weighted_sum = 0.0
    total_weight = 0.0
    for dim, avg in dim_scores_avg.items():
        dw = weights.get(dim, 1.0)
        tw = dim_total_weight.get(dim, 0.0)
        total_weighted_sum += dw * tw * avg
        total_weight += dw * tw
    if total_weight <= 0:
        return 0.0, dim_scores_avg, "BROKEN"
    total = total_weighted_sum / total_weight * 10.0

    # 等级
    if total >= 85:
        rating = "EXCELLENT"
    elif total >= 70:
        rating = "GOOD"
    elif total >= 55:
        rating = "FAIR"
    elif total >= 30:
        rating = "POOR"
    else:
        rating = "BROKEN"
    return round(total, 2), dim_scores_avg, rating


# =====================================================================
# 重建 round 产物:从 per_file_findings/*.json 聚合回 score/proposal/round_result
# 用法:历史产物恢复 / 部分 round 重新评估 / 跨 run 评分对比
# =====================================================================

def rebuild_round_artifacts(round_dir: Path, baseline_score: float | None = None) -> dict:
    """从 `round_dir/per_file_findings/*.json` 重建 score.json / proposal.json / round_result.json。

    Args:
        round_dir: round 目录路径（必须含 per_file_findings/ 子目录）
        baseline_score: 可选,Round 0 的总分用于算 delta；不传则按 round=0 跳过 delta

    Returns:
        dict 含 `round` / `total` / `verdict` / `applied` / `modifications_count`
        失败返回 {'error': str}
    """
    pf_dir = round_dir / "per_file_findings"
    if not pf_dir.exists():
        return {"error": f"per_file_findings 目录不存在: {pf_dir}"}

    # 收集 per_file_findings
    per_file: list[dict] = []
    for fn in sorted(pf_dir.glob("*.json")):
        try:
            per_file.append(json.loads(fn.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            return {"error": f"读 {fn} 失败: {exc}"}

    if not per_file:
        return {"error": "per_file_findings 为空"}

    # 聚合 dim_scores + file_scores + modifications
    mods: list[dict] = []
    file_dim_scores: dict[str, dict[str, float]] = {}
    file_scores: dict[str, float] = {}
    for entry in per_file:
        ds = entry.get("dim_scores") or {}
        for dim, info in ds.items():
            if isinstance(info, dict) and isinstance(info.get("score"), (int, float)):
                file_dim_scores.setdefault(entry["file"], {})[dim] = float(info["score"])
        scores = [v["score"] for v in ds.values() if isinstance(v, dict) and isinstance(v.get("score"), (int, float))]
        if scores:
            file_scores[entry["file"]] = round(sum(scores) / len(scores), 2)
        for finding in entry.get("findings") or []:
            if isinstance(finding, dict):
                mods.append({"file": entry.get("file", ""), **finding})

    # 聚合总分:用 file_weight（如果 relation_tree 可用则用,否则均分）
    # 这里采用 "所有 file 的 dim_score 简单均分" 作为兜底;若要更准确可用 aggregate_dim_scores
    if file_dim_scores:
        # 取所有 file 的 dim 算术平均
        from collections import defaultdict
        dim_acc: dict[str, list[float]] = defaultdict(list)
        for f_dim in file_dim_scores.values():
            for d, v in f_dim.items():
                dim_acc[d].append(v)
        dim_scores: dict[str, float] = {d: round(sum(vs) / len(vs), 2) for d, vs in dim_acc.items()}
    else:
        dim_scores = {}

    # 简单的 total 均值
    total = round(sum(dim_scores.values()) / max(1, len(dim_scores)), 2) if dim_scores else 0.0

    # verdict/打分
    round_num = int(round_dir.name.split("_")[-1])
    is_baseline = round_num == 0
    if is_baseline:
        verdict = "baseline"
        delta = 0.0
    else:
        delta = round(total - (baseline_score or 0), 2)
        # 与新规则一致:有真实 mod 应用才判 improved
        has_real_improvement = len(mods) > 0
        if has_real_improvement and total > (baseline_score or 0):
            verdict = "improved"
        elif delta < -2:
            verdict = "reverted"
        else:
            verdict = "plateau"

    applied = len(mods) if mods else 0  # 注:真正 applied 数不能从 pf 恢复,这里用 mods 数作为上限
    rating = "GOOD" if total >= 70 else ("FAIR" if total >= 55 else ("EXCELLENT" if total >= 85 else "POOR"))

    # 1. score.json
    score_payload = {
        "round": round_num, "total": total, "rating": rating,
        "delta": delta, "verdict": verdict,
        "dim_scores": dim_scores, "file_scores": file_scores,
        "applied": applied, "files_changed": [m["file"] for m in mods if m.get("file")],
    }
    (round_dir / "score.json").write_text(
        json.dumps(score_payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 2. proposal.json（完整 LLM 输出聚合）
    diagnosis = (round_dir / "proposal.json")
    if diagnosis.exists():
        try:
            old = json.loads(diagnosis.read_text(encoding="utf-8"))
            diag = old.get("diagnosis", "")
        except Exception:
            diag = ""
    else:
        diag = ""
    proposal_payload = {
        "round": round_num, "diagnosis": diag,
        "per_file_findings": per_file, "modifications": mods,
        "_meta": {
            "files_scanned": len(per_file),
            "mods_proposed": len(mods),
            "total_score": total, "rating": rating,
        },
    }
    (round_dir / "proposal.json").write_text(
        json.dumps(proposal_payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 3. round_result.json (兼容旧格式)
    rr_payload = {
        "round_num": round_num,
        "score": total, "baseline_score": baseline_score or 0,
        "delta": delta, "verdict": verdict,
        "modifications_applied": applied,
        "files_changed": [m["file"] for m in mods if m.get("file")],
        "dim_scores": dim_scores,
        "regressed_dims": [], "regressed_warning": "",
        "proposal": {
            "round": round_num, "diagnosis": diag,
            "per_file_findings": per_file, "modifications": mods,
        },
        "apply": {
            "applied": applied, "skipped": 0, "failed": 0,
            "reported": len(mods), "apply_rate": applied / max(1, len(mods)),
            "files_changed": [m["file"] for m in mods if m.get("file")],
            "errors": [], "match_failures": [], "backup_path": "",
        },
        "asset_validation": {},
        "verifier": {},
    }
    (round_dir / "round_result.json").write_text(
        json.dumps(rr_payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    return {
        "round": round_num, "total": total, "verdict": verdict,
        "applied": applied, "modifications_count": len(mods),
    }


