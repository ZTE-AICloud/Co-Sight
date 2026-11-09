#!/usr/bin/env python3
"""
static_optimizer.py — /skill_optimize 静态优化器
==================================================

不依赖业务方 eval-cmd，使用 LLM judge 做 7 维评分 + 多轮 hill-climb + 触顶 break。

v2 架构（融合 darwin-skill + AgentGenesis）：
  - 7 维评分 rubric（darwin + AgentGenesis S-05 融合， 删 dim8_assets）
  - 8 条 darwin 自操作反例 + 8 条 SKILL 自身反例
  - 11 个 AgentGenesis 优化 patterns
  - HL-1~4 实战经验（杠杆点）
  - LLM 走本地 ccr HTTP（MiniMax-M3）→ static_llm.call_llm_json
  - prompt 构造走 static_prompts.build_evaluator/optimizer_prompt
  - modifications 应用 + 资产校验走 static_apply（ 删除 dim8 评分）

4 层安全网：
  1. git snapshot — 每轮首步 commit baseline
  2. protected_assets 白名单 — frontmatter + CLI + defaults 三层合并
  3. git revert HEAD — 评分回退自动回滚
  4. 触顶 break — 连续 2 轮 Δ < threshold 即停（HL-4）

所有文件类型统一由 optimizer-agent 处理，不区分 md/代码。

调用入口：
  python3 scripts/orchestrator.py --mode static [args...]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 文件类型常量：用于 dispatch_files 提示 LLM 区分 md vs code
MD_EXTENSIONS = {".md"}
CODE_EXTENSIONS = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".mjs", ".js", ".ts"}
SKIP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", ".bin"}

# 默认 protected_assets 模式（3 层合并的最低保证）
# 2026-06-26 临时禁用：本次 /skill_optimize 多 Skill 任务要求无白名单限制
# TODO: 任务结束后恢复为 ["references/standard-*.md", "templates/*.md", "CHANGELOG.md"]
DEFAULT_PROTECTED_PATTERNS = []

# expert_guidance 最大长度（超出截断）
EXPERT_GUIDANCE_MAX_LEN = 2000

#  P0-1: HITL 三层守关默认值（与 optimize-user-config.yaml.hitl 段对齐）
HITL_DEFAULT_PASS_THRESHOLD = 3.0       # delta ≥ +3 → auto_pass
HITL_DEFAULT_REVERT_THRESHOLD = -3.0    # delta ≤ -3 → auto_revert
HITL_DEFAULT_ON_HUMAN_REVIEW = "auto_accept"  # auto_accept / interactive / log_only
HITL_DEFAULT_INTERACTIVE_TIMEOUT = 60   # 仅 interactive 模式生效


def _load_user_config_full() -> dict:
    """:加载 config/optimize-user-config.yaml 完整 dict,供 hitl / eval_runs / enabled_dimensions / dim_weights 等段读取。
    多次复用同一个 dict,避免重复 yaml.safe_load。
    """
    candidates = [
        Path(__file__).parent.parent.parent / "config" / "optimize-user-config.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
        except (OSError, ImportError):
            continue
    return {}


@dataclass
class StaticConfig:
    """静态优化器配置（from CLI args）"""

    skill_path: Path
    workspace: Path
    max_rounds: int = 3
    max_files: int = 20  # .12+：从 10 提升到 20,适配大 Skill(含 scripts/ + references/)
    protected_assets: list[str] = field(default_factory=list)
    break_threshold: float = 1.0  # .07+：用户要求降低接受门限（原 2.0 → 1.0，Δ<1.0 连续 2 轮才停）
    expert_guidance: str = ""
    no_revert: bool = False
    eval_mode: str = "full"  #  Top 6: "dry_run" / "partial" / "full"
    eval_runs: int = 3  # ：每轮 evaluator 并发跑 N 次取均值（消除 LLM judge 抽样噪声）
    # .18+：评分执行路径选择，cosight 同步兼容
    #   "llm_direct"（默认）：拼 prompt 直接调大模型（老路径，与 skillx-alpha-agents-old 一致）
    #   "subagent"          ：cc tools.Agent 真子 Agent + 编码 skill 注入（cosight .17+）
    score_mode: str = "llm_direct"
    # v_next+：是否使用 unified agent（融合评分+优化）。True=单阶段 fusion；False=旧 6 phase。
    use_unified_agent: bool = True
    #  P0-1：HITL 三层守关阈值（YAML 优先，CLI 覆盖，默认值兜底）
    hitl_pass_threshold: float = HITL_DEFAULT_PASS_THRESHOLD
    hitl_revert_threshold: float = HITL_DEFAULT_REVERT_THRESHOLD
    hitl_on_human_review: str = HITL_DEFAULT_ON_HUMAN_REVIEW
    hitl_interactive_timeout_seconds: int = HITL_DEFAULT_INTERACTIVE_TIMEOUT

    @classmethod
    def from_args(cls, args: argparse.Namespace, workspace: Path) -> "StaticConfig":
        """从 CLI 参数构造配置（优先级链：CLI > YAML > 默认值）"""
        skill_path = Path(args.skill_path).resolve()
        protected = []
        if getattr(args, "protected_assets", ""):
            protected = [p.strip() for p in args.protected_assets.split(",") if p.strip()]
        protected.extend(DEFAULT_PROTECTED_PATTERNS)
        eg = getattr(args, "expert_guidance", "") or ""
        if len(eg) > EXPERT_GUIDANCE_MAX_LEN:
            logger.warning(
                "expert_guidance 长度 %d 超过 %d，已截断",
                len(eg),
                EXPERT_GUIDANCE_MAX_LEN,
            )
            eg = eg[:EXPERT_GUIDANCE_MAX_LEN]
        #  Top 6：--dry-run → eval_mode="dry_run"
        eval_mode = "dry_run" if getattr(args, "dry_run", False) else "full"

        # .18+：score_mode（评分执行路径），优先级：CLI > env SKILLX_SCORE_MODE > "llm_direct"
        score_mode_raw = getattr(args, "score_mode", None) or os.environ.get(
            "SKILLX_SCORE_MODE", "llm_direct"
        )
        score_mode = str(score_mode_raw).strip().lower()
        if score_mode not in {"llm_direct", "subagent"}:
            logger.warning(
                "score_mode=%s 不在白名单 {llm_direct, subagent}，回退到 llm_direct",
                score_mode,
            )
            score_mode = "llm_direct"

        # ：读 config/optimize-user-config.yaml 的 hitl / eval_runs 段
        user_cfg = _load_user_config_full()
        hitl_cfg = user_cfg.get("hitl", {}) if isinstance(user_cfg.get("hitl"), dict) else {}
        yaml_eval_runs = user_cfg.get("eval_runs", None)
        try:
            yaml_eval_runs = int(yaml_eval_runs) if yaml_eval_runs is not None else None
        except (TypeError, ValueError):
            yaml_eval_runs = None

        # 优先级：CLI > YAML > dataclass 默认值
        cli_pass = getattr(args, "hitl_pass_threshold", None)
        cli_revert = getattr(args, "hitl_revert_threshold", None)
        cli_on_human = getattr(args, "hitl_on_human_review", None)
        cli_eval_runs = getattr(args, "eval_runs", None)

        hitl_pass = float(cli_pass) if cli_pass is not None else float(
            hitl_cfg.get("pass_threshold", HITL_DEFAULT_PASS_THRESHOLD)
        )
        hitl_revert = float(cli_revert) if cli_revert is not None else float(
            hitl_cfg.get("revert_threshold", HITL_DEFAULT_REVERT_THRESHOLD)
        )
        on_human_review = (
            str(cli_on_human).strip()
            if cli_on_human not in (None, "")
            else str(hitl_cfg.get("on_human_review", HITL_DEFAULT_ON_HUMAN_REVIEW)).strip()
        )
        if on_human_review not in {"auto_accept", "interactive", "log_only"}:
            logger.warning(
                "hitl_on_human_review=%s 不在白名单,回退到 auto_accept", on_human_review,
            )
            on_human_review = "auto_accept"
        try:
            hitl_timeout = int(hitl_cfg.get("interactive_timeout_seconds",
                                            HITL_DEFAULT_INTERACTIVE_TIMEOUT))
        except (TypeError, ValueError):
            hitl_timeout = HITL_DEFAULT_INTERACTIVE_TIMEOUT

        eval_runs_val = cli_eval_runs if cli_eval_runs is not None else (
            yaml_eval_runs if yaml_eval_runs is not None else 3
        )

        return cls(
            skill_path=skill_path,
            workspace=workspace,
            max_rounds=getattr(args, "max_rounds", 3),
            max_files=getattr(args, "max_files", 10),
            protected_assets=protected,
            break_threshold=float(getattr(args, "break_threshold", 1.0)),
            expert_guidance=eg,
            no_revert=getattr(args, "no_revert", False),
            eval_mode=eval_mode,
            score_mode=score_mode,  # .18+：评分路径选择
            eval_runs=max(1, int(eval_runs_val)),  #  + ：YAML/CLI 优先级
            use_unified_agent=(getattr(args, "use_unified_agent", "true") != "false"),
            hitl_pass_threshold=hitl_pass,
            hitl_revert_threshold=hitl_revert,
            hitl_on_human_review=on_human_review,
            hitl_interactive_timeout_seconds=hitl_timeout,
        )


@dataclass
class RoundResult:
    """单轮结果"""

    round_num: int
    score: float
    baseline_score: float
    delta: float
    verdict: str  # "improved" / "reverted" / "plateau" / "broken"
    modifications_applied: int
    files_changed: list[str] = field(default_factory=list)
    sha_before: str = ""
    sha_after: str = ""
    dim_scores: dict[str, float] = field(default_factory=dict)  # ：雷达图数据源
    #  A 方案:per-dim 健康度,推动"尽量每 dim 都提升"目标
    regressed_dims: list[str] = field(default_factory=list)  # 相对上一轮 regressed 的 dim
    regressed_warning: list[str] = field(default_factory=list)  # 未被 mod 覆盖的 regressed dim


def classify_file(path: Path) -> str:
    """根据后缀分类：'md' / 'code' / 'skip'"""
    ext = path.suffix.lower()
    if ext in MD_EXTENSIONS:
        return "md"
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in SKIP_EXTENSIONS:
        return "skip"
    # 其他文本文件（如 .txt）按 md 处理
    return "md"


def merge_protected_assets(
    cli_arg: list[str],
    frontmatter_declared: list[str],
    defaults: list[str] = None,
) -> list[str]:
    """3 层合并：CLI → frontmatter → defaults（取并集）

    实际为 4 层（CLI 优先级最高）：
      1. CLI 参数 --protected-assets
      2. SKILL.md frontmatter 声明
      3. config/optimize-user-config.yaml 的 protected_assets 段
      4. framework defaults（DEFAULT_PROTECTED_PATTERNS）
    """
    if defaults is None:
        defaults = DEFAULT_PROTECTED_PATTERNS
    user_config_assets = _load_user_config_protected_assets()
    seen = set()
    merged = []
    for src in (cli_arg, frontmatter_declared, user_config_assets, defaults):
        for pat in src:
            if pat not in seen:
                seen.add(pat)
                merged.append(pat)
    return merged


def _load_user_config_protected_assets() -> list[str]:
    """从 config/optimize-user-config.yaml 加载业务方 per-skill protected_assets"""
    candidates = [
        Path(__file__).parent.parent.parent / "config" / "optimize-user-config.yaml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            assets = data.get("protected_assets", []) or []
            if isinstance(assets, str):
                assets = [assets]
            return [str(a) for a in assets if a]
        except (OSError, ImportError):
            continue
    return []


def is_protected(rel_path: str, protected_patterns: list[str]) -> bool:
    """判断相对路径是否匹配白名单（glob 风格）"""
    from fnmatch import fnmatch

    for pat in protected_patterns:
        if fnmatch(rel_path, pat) or fnmatch(Path(rel_path).name, pat):
            return True
    return False


def parse_frontmatter(skill_path: Path) -> tuple[dict, list[str]]:
    """从 SKILL.md frontmatter 解析 protected_assets 字段"""
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError:
        return {}, []
    if not text.startswith("---"):
        return {}, []
    end = text.find("\n---", 3)
    if end < 0:
        return {}, []
    fm_text = text[3:end].strip()
    fm: dict = {}
    protected: list[str] = []
    current_key: Optional[str] = None
    current_list: Optional[list[str]] = None
    for line in fm_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        if ":" in stripped and not stripped.startswith("-"):
            if current_list is not None and current_key:
                fm[current_key] = current_list
                current_list = None
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current_key = key
                current_list = []
            else:
                fm[key] = value.strip('"').strip("'")
                current_key = None
    if current_list is not None and current_key:
        fm[current_key] = current_list
    protected = fm.get("protected_assets", [])
    if isinstance(protected, str):
        protected = [protected]
    return fm, protected


def git_snapshot(workspace: Path, message: str) -> Optional[str]:
    """ 禁用：评分回退已改用文件系统快照恢复（restore_skill_from_snapshot），
    无需 git 历史。保留函数签名仅供旧调用点兼容，直接返回 None。
    """
    logger.debug("git_snapshot 已禁用（ 无 git 路径），message=%s", message)
    return None


def restore_skill_from_snapshot(skill_root: Path, snapshot: Path) -> bool:
    """从 before snapshot 恢复 skill_root（评分回退时调用）。

    完全用文件系统操作替代 git revert：
      1. 删除当前 skill_root
      2. 从 snapshot 拷贝回来

    比 git revert 更直接：无 git 历史污染、无 commit 副作用、不被元数据修改阻断。
    """
    if not snapshot.exists():
        logger.error("snapshot 不存在: %s", snapshot)
        return False
    try:
        if skill_root.exists():
            shutil.rmtree(skill_root)
        shutil.copytree(snapshot, skill_root)
        logger.info("已从 snapshot 恢复 skill: %s → %s", snapshot, skill_root)
        return True
    except (OSError, shutil.Error) as e:
        logger.error("snapshot 恢复失败: %s", e)
        return False


def compute_md5(file_path: Path) -> Optional[str]:
    """计算文件 md5（缺失返回 None）"""
    import hashlib
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


def collect_target_files(skill_root: Path, max_files: int = 0) -> list[Path]:
    """扫描 Skill 根目录下要优化的文件（按 dispatch 过滤）。

    根治 B：max_files 不再限制扫描（之前误用作扫描上限，致 references/ templates 被截断）。
    现仅在 optimizer 生成 modifications 时限制 mod 数量（每轮 mod ≤ max_files）。
    这里 max_files 参数保留向后兼容，但不再截断扫描。
    """
    if not skill_root.exists():
        return []
    files: list[Path] = []
    for p in skill_root.rglob("*"):
        if not p.is_file():
            continue
        kind = classify_file(p)
        if kind == "skip":
            continue
        files.append(p)
    return files


def dispatch_files(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """按 dispatch 规则分组：md 文件 / code 文件"""
    md_files, code_files = [], []
    for f in files:
        kind = classify_file(f)
        if kind == "md":
            md_files.append(f)
        elif kind == "code":
            code_files.append(f)
    return md_files, code_files


def _check_consecutive_single_file(
    history: list["RoundResult"],
    workspace: Path,
) -> Optional[str]:
    """检查最近 2 轮是否都只改了 1 个文件，返回警告文本（无警告返回 None）。

    从 workspace/round_{N}/round_result.json 读取 files_changed 判断。
    只针对 ≥5 个文件的 skill 激活。
    """
    try:
        from .static_relations import RELATION_TREE_FILENAME
        rp = workspace / RELATION_TREE_FILENAME
        if rp.exists():
            import json as _j
            tree = _j.loads(rp.read_text(encoding="utf-8"))
            if tree.get("stats", {}).get("file_count", 0) < 5:
                return None
    except Exception:
        pass

    recent: list[list[str]] = []
    for r in (history or [])[-2:]:
        if not isinstance(r, dict) and not hasattr(r, "round_num"):
            break
        rn = r["round_num"] if isinstance(r, dict) else r.round_num
        rr_path = workspace / f"round_{rn}" / "round_result.json"
        if not rr_path.exists():
            break
        try:
            import json as _j
            rr = _j.loads(rr_path.read_text(encoding="utf-8"))
            changed = rr.get("apply", {}).get("files_changed", []) or []
            changed = [c if isinstance(c, str) else str(c) for c in changed]
            recent.append(sorted(set(changed)))
        except Exception:
            break

    if len(recent) >= 2 and all(len(f) <= 1 for f in recent):
        return (
            "⚠️ **过去连续 2 轮都只改了 1 个文件**（"
            f"{', '.join(', '.join(f) for f in recent)}）。"
            "多文件是统一整体，单文件改动可能遗漏跨文件优化。"
            "**本轮必须至少覆盖 3 个不同文件**，优先选长期未改文件。"
        )
    return None


def _skill_latest_mtime(skill_root: Path) -> float:
    """返回 skill_root 下所有文件的最晚 mtime（用于判断关系树是否需重建）。"""
    latest = 0.0
    try:
        for p in skill_root.rglob("*"):
            if p.is_file():
                latest = max(latest, p.stat().st_mtime)
    except OSError:
        pass
    return latest


def _ensure_relation_tree(
    config: "StaticConfig",
    skill_root: Path,
    target_files: list[Path],
) -> dict:
    """确保 workspace 顶层有最新的关系树文件，返回关系树 dict。

    mtime 检查：关系树文件比 skill_root 所有文件都新 → 复用（不重扫）；
    否则重建并原子写。异常时返回空树（不阻断主链路）。
    """
    from .static_relations import (RELATION_TREE_FILENAME, build_relation_tree,
                                   write_relation_tree)

    out_path = config.workspace / RELATION_TREE_FILENAME
    history_path = config.workspace / "static_history.json"

    # mtime 复用：关系树已存在且比 skill 所有文件都新
    if out_path.exists():
        try:
            if out_path.stat().st_mtime >= _skill_latest_mtime(skill_root):
                return json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    # scanner.max_files（framework YAML 优先，默认 50）
    try:
        fw = load_framework_config()
        max_files = int(
            (fw.get("relation_tree", {}).get("scanner", {}) or {}).get("max_files", 50)
        )
    except Exception:
        max_files = 50

    tree = build_relation_tree(
        skill_root, target_files, config.protected_assets,
        history_path=history_path if history_path.exists() else None,
        max_files=max_files,
    )
    try:
        write_relation_tree(tree, out_path)
    except OSError as e:
        logger.warning("关系树写盘失败(继续用内存版): %s", e)
    return tree


def invoke_evaluator(
    skill_root: Path,
    target_files: list[Path],
    config: StaticConfig,
    output_path: Path,
    framework_cfg: dict,
    round_num: int = 1,
    attempt: int = 0,
    *,
    score_mode: str | None = None,  # .18+：None 表示从 config.score_mode 取
) -> dict:
    """委托给 static_agents.invoke_evaluator（v2 真实 LLM 调用，支持 score_mode 分支）。"""
    from .static_agents import invoke_evaluator as _impl
    return _impl(
        skill_root=skill_root,
        target_files=target_files,
        config=config,
        output_path=output_path,
        framework_cfg=framework_cfg,
        round_num=round_num,
        attempt=attempt,
        score_mode=score_mode if score_mode is not None else config.score_mode,
    )


def invoke_optimizer(
    skill_root: Path,
    target_files: list[Path],
    config: StaticConfig,
    round_num: int,
    score_json: dict,
    output_path: Path,
    framework_cfg: dict,
    attempt: int = 0,
    relation_tree: Optional[dict] = None,
    revise_signals: Optional[dict] = None,
    overfit_signals: Optional[dict] = None,
    apply_failure_signals: Optional[list] = None,
    chars_budget: Optional[int] = None,
    revision_strategy: Optional[dict] = None,
    score_mode: Optional[str] = None,
    custom_user_prompt: Optional[str] = None,
) -> dict:
    """委托给 static_agents.invoke_optimizer（v2 真实 LLM 调用）。

     新增：
      - relation_tree: 文件关系树骨架（破 SKILL.md 偏向，None → 底层从磁盘读）
      - revise_signals: 上一轮 REVISE 信号
     新增：
      - overfit_signals: P1-B overfit 反馈闭环
      - apply_failure_signals: P2-A apply 失败根因注入
      - chars_budget: P2-B 单轮字符预算（ 已删除硬限制，参数保留向后兼容）
    v_next 新增：
      - revision_strategy: R2+ 接续优化策略(StaticRevisionAgent 产出,R1=None)
      - custom_user_prompt: 非 None 时跳过 build_optimizer_prompt，直接用此 prompt 调 LLM（fix_attempt 专用）
    """
    from .static_agents import invoke_optimizer as _impl
    _ = chars_budget  # : 不再传给底层 invoke_optimizer（已无意义）
    return _impl(
        skill_root=skill_root,
        target_files=target_files,
        config=config,
        round_num=round_num,
        score_json=score_json,
        output_path=output_path,
        framework_cfg=framework_cfg,
        attempt=attempt,
        relation_tree=relation_tree,
        revise_signals=revise_signals,
        overfit_signals=overfit_signals,
        apply_failure_signals=apply_failure_signals,
        revision_strategy=revision_strategy,
        score_mode=config.score_mode,
        custom_user_prompt=custom_user_prompt,
    )


def load_framework_config() -> dict:
    """加载 framework YAML（rubric / anti_patterns / patterns / hl_rules / safety）"""
    import yaml

    config_path = (
        Path(__file__).resolve().parents[2]
        / "framework_configs"
        / "static-eval-config.yaml"
    )
    if not config_path.exists():
        logger.warning("framework config 不存在: %s", config_path)
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.error("framework config 加载失败: %s", e)
        return {}


def apply_dim_overrides(framework_cfg: dict, dim_overrides: dict | None) -> dict:
    """.1:把 optimize-user-config.yaml 的 dim_overrides 段合并到 framework_cfg.rubric。

    设计动机:framework YAML 是 framework 维护者管的"通用定义",但业务方个性化(
    比如换关键词、调整权重、改阈值)只想改一个文件(optimize-user-config.yaml)。
    此函数让业务方**完全在 optimize-user-config.yaml 里覆盖任意 dim 字段**,
    不必动 framework YAML。

    合并策略:浅合并每个 dim dict。framework 默认字段全保留,override 字段覆盖。
    未来新增字段(framework YAML 加新 key)时,业务方只需在 dim_overrides 里加同名 key 即可。

    Args:
        framework_cfg: load_framework_config() 返回的 dict
        dim_overrides: optimize-user-config.yaml.dim_overrides 段,
                       形如 {dim9_coverage_auto: {weight: 1.5, high_score_threshold: 8}, ...}

    Returns:
        合并后的 framework_cfg(rubric 段被改写,其他段原样)
    """
    if not dim_overrides or not isinstance(dim_overrides, dict):
        return framework_cfg
    if not framework_cfg:
        return framework_cfg

    rubric = framework_cfg.get("rubric", {})
    if not isinstance(rubric, dict):
        return framework_cfg

    overridden_count = 0
    for dim_key, override_cfg in dim_overrides.items():
        if not isinstance(override_cfg, dict):
            continue
        if not dim_key.startswith("dim"):
            logger.warning(
                "[dim_overrides] 跳过非 dim 键: %s(只允许 dim* 维度名)", dim_key,
            )
            continue
        if dim_key not in rubric:
            logger.warning(
                "[dim_overrides] %s 不在 framework rubric 中(可能 framework YAML 未定义),跳过",
                dim_key,
            )
            continue
        # 浅合并:framework 默认字段保留,override 字段覆盖
        merged = dict(rubric[dim_key])  # 拷贝避免原地修改
        merged.update(override_cfg)
        rubric[dim_key] = merged
        overridden_count += 1

    if overridden_count:
        logger.info(
            "[dim_overrides] 合并 %d 个维度覆盖(来源:optimize-user-config.yaml)",
            overridden_count,
        )
    return framework_cfg


def expand_dim_weights(dim_weights: dict | None,
                       dim_overrides: dict | None) -> dict[str, dict]:
    """.2:把 dim_weights 段展开成 dim_overrides 兼容的 {dim_key: {weight: ...}}。

    业务方习惯用 dim_weights: {dim3_failure_modes: 1.8} 这种扁平写法,
    内部统一转成 dim_overrides: {dim3_failure_modes: {weight: 1.8}} 走同一 merge 路径,
    避免两处读 weight 不一致。

    优先级:dim_overrides 显式给的 weight 优先(dim_overrides 更具体,视为最终配置),
           dim_weights 仅在 dim_overrides 未指定 weight 时填入。

    Returns:
        可直接传给 apply_dim_overrides 的 dict。
    """
    out: dict[str, dict] = {}
    if dim_weights and isinstance(dim_weights, dict):
        for dim_key, w in dim_weights.items():
            if not dim_key.startswith("dim"):
                continue
            try:
                wv = float(w)
            except (TypeError, ValueError):
                logger.warning("[dim_weights] %s=%r 不是合法数字,跳过", dim_key, w)
                continue
            out.setdefault(dim_key, {})["weight"] = wv
    if dim_overrides and isinstance(dim_overrides, dict):
        for dim_key, cfg in dim_overrides.items():
            if not dim_key.startswith("dim"):
                continue
            if not isinstance(cfg, dict):
                continue
            out.setdefault(dim_key, {}).update(cfg)
    return out


def check_break(
    history: list[RoundResult],
    threshold: float,
    consecutive_rounds: int = 2,
) -> bool:
    """检测是否触顶（HL-4：连续 N 轮 Δ < threshold）"""
    if len(history) < consecutive_rounds:
        return False
    recent = history[-consecutive_rounds:]
    return all(r.delta < threshold for r in recent)


def check_regressed_dim_coverage(
    proposal: dict,
    regressed_dims: list[str],
) -> dict:
    """ A 方案：pre-flight 检查 regressed 维度是否被 mod 覆盖（warn-only）。

    Args:
        proposal: 当前轮 proposal {modifications: [{dim_improved, ...}, ...]}
        regressed_dims: 上一轮 regressed 的 dim 列表

    Returns:
        {
          warning: bool,         # 是否有 regressed dim 未被覆盖
          covered: list[str],    # 已被 mod 覆盖的 regressed dim
          missing: list[str],    # regressed 但没被任何 mod 覆盖的 dim
        }
    """
    if not regressed_dims:
        return {"warning": False, "covered": [], "missing": []}

    covered: set[str] = set()
    for mod in proposal.get("modifications") or []:
        dim = mod.get("dim_improved", "")
        if dim in regressed_dims:
            covered.add(dim)

    missing = [d for d in regressed_dims if d not in covered]
    return {
        "warning": bool(missing),
        "covered": sorted(covered),
        "missing": missing,
    }


def _run_phase_with_rework(
    state_path: Path,
    phase: str,
    max_attempts: int,
    backoff_seq: list[int],
    round_num: int,
    fn: object,
    validate_fn: object,
) -> object:
    """REWORK 包裹：调用 fn(attempt)，失败时按 max_attempts + 指数退避重试。

    fn 应接受 1 个位置参数 attempt: int（0-indexed 重试计数），
    首次调用 attempt=0，失败时 attempt=1/2/...。

    Returns:
        fn() 的成功结果；超限返回 None。
    """
    from .static_apply import record_rework  # 局部 import 避免循环引用

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn(attempt - 1)
            if validate_fn is not None and not validate_fn(result):
                raise ValueError(f"{phase} validation failed")
            if attempt > 1:
                record_rework(
                    state_path, phase, attempt, "success after retry",
                    0, "done", round_num=round_num,
                )
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            backoff = backoff_seq[min(attempt - 1, len(backoff_seq) - 1)]
            record_rework(
                state_path, phase, attempt, str(e)[:200],
                backoff, "failed", round_num=round_num,
            )
            if attempt < max_attempts:
                import time as _t
                _t.sleep(backoff)
    logger.error("REWORK 超限: phase=%s reason=%s", phase, last_err)
    return None


def _compute_modification_budget(round_num: int) -> int:
    """P1 planner 算 modification_budget：返回 0 表示不限制 mod 总数。

    之前逻辑：8 → 7 → 6 ... floor=2（每轮 mod 数收敛）。
    根治：用户要求"不限制 mod 总数"——涉及这么多文件应允许 optimizer 自由生成。
    返回 0 → score_analyzer._enforce_modification_budget 看到 0 跳过截断。
    """
    return 0


# : 删除 chars_budget 硬限制（ P2-B 移除）。原逻辑:
#   TOTAL_CHARS_BUDGET_BASE = 5000, TOTAL_CHARS_BUDGET_DECAY = 2000, TOTAL_CHARS_BUDGET_FLOOR = 600
# 实际效果是拦截了所有非 SKILL.md 的脚本文件（≥1000 字符），导致 references/scripts 几乎无改动。
# 现改为由 prompt 引导 LLM 控制单条 mod 长度（≤ 5000 字符），不再做硬裁剪。
# 函数 _compute_chars_budget 也已删除（line ~470-480 区域），调用点不再需要。


# P1-A: ceiling 检测阈值。current_best >= 70 时 R3 走保守模式（budget ≤ 2）
CEILING_THRESHOLD = 70.0
CEILING_MAX_BUDGET = 2  # 高分 baseline R3 最多 2 条 mod


def _is_ceiling_mode(round_num: int, current_best: float) -> bool:
    """P1-A: 不再使用 ceiling 模式（之前 R3 max_mods=2 保守模式导致分数无提升）。

    现状：返回 0 = 不限制 mod 总数。用户最新决策："不要限制 5/8/5 条 mods 个数"。
    让 optimizer 自由生成任意条数 mod（按 36 个文件逐个评估后输出所有可改进点）。

    Args:
        round_num: 当前轮次（1-indexed）
        current_best: 当前最高分（max(baseline, 此前 best_score)）

    Returns:
        True = 进入 ceiling 保守模式
    """
    return round_num >= 3 and current_best >= CEILING_THRESHOLD


def _format_mod_diff_summary(
    proposal: dict,
    delta: float,
    prev_score: float,
    current_score: float,
    round_num: int,
) -> str:
    """ P0-1：human_review 时给用户看的 diff 摘要。"""
    lines: list[str] = [
        f"=== Round {round_num} HITL 三层守关：human_review ===",
        f"delta: {delta:+.2f}  (prev_accepted={prev_score:.2f}, current={current_score:.2f})",
        "",
        "本轮 modifications:",
    ]
    mods = proposal.get("modifications", []) or []
    if not mods:
        lines.append("  （无 modifications）")
    for i, mod in enumerate(mods, 1):
        file = mod.get("file", "?")
        section = mod.get("section", "?")
        dim = mod.get("dim_improved", "?")
        pattern = mod.get("pattern_used", "?")
        reason = mod.get("reason", "")[:120]
        lines.append(
            f"  M{i}: {file} :: {section}  dim={dim} pattern={pattern}\n"
            f"      reason: {reason}"
        )
    return "\n".join(lines)


def _resolve_human_review(
    config: "StaticConfig",
    round_num: int,
    delta: float,
    prev_accepted_score: float,
    current_score: float,
    proposal: dict,
) -> tuple[bool, str]:
    """ P0-1:解析 human_review 三种 on_human_review 模式。

    Returns:
        (accept, detail): accept=True 采纳,False 拒绝;detail 为日志摘要。
    """
    mode = config.hitl_on_human_review
    diff_summary = _format_mod_diff_summary(
        proposal=proposal,
        delta=delta,
        prev_score=prev_accepted_score,
        current_score=current_score,
        round_num=round_num,
    )

    if mode == "log_only":
        logger.info("[Round %d] HITL log_only 模式：自动采纳,仅打印 diff 摘要\n%s",
                    round_num, diff_summary)
        return True, "log_only"

    if mode == "interactive":
        # stdin 阻塞等待用户输入
        import sys

        timeout = max(1, int(config.hitl_interactive_timeout_seconds))
        try:
            print(diff_summary)
            print(f"\n请输入 y/yes 采纳,n/no 拒绝(超时 {timeout}s 默认 y):", flush=True)
            sys.stdout.flush()
            try:
                import select

                ready, _, _ = select.select([sys.stdin], [], [], timeout)
                if not ready:
                    logger.info("[Round %d] HITL interactive 超时 %ds,默认采纳",
                                round_num, timeout)
                    return True, "interactive_timeout_default_accept"
                user_input = sys.stdin.readline().strip().lower()
            except (ImportError, OSError):
                user_input = sys.stdin.readline().strip().lower()
            if user_input in ("n", "no"):
                logger.info("[Round %d] HITL interactive 用户拒绝", round_num)
                return False, "interactive_user_rejected"
            logger.info("[Round %d] HITL interactive 用户采纳", round_num)
            return True, "interactive_user_accepted"
        except (EOFError, KeyboardInterrupt):
            logger.info("[Round %d] HITL interactive EOF/中断,默认采纳", round_num)
            return True, "interactive_eof_default_accept"

    # 默认 auto_accept（与原行为兼容）
    logger.info("[Round %d] HITL auto_accept 模式：自动采纳\n%s",
                round_num, diff_summary)
    return True, "auto_accept"


def _debug_log(workspace: Path, content: str) -> None:
    """写一行到 _debug/runtime.log（追加模式）。"""
    debug_dir = workspace / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_path = debug_dir / "runtime.log"
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(content + "\n")
    except OSError as e:
        logger.warning("写 _debug/runtime.log 失败: %s", e)


def _debug_log_phase(
    workspace: Path,
    phase: str,
    round_num: int,
    status: str,
    **extras: object,
) -> None:
    """记录 phase 完成到 _debug/runtime.log。"""
    parts = [
        f"phase={phase}",
        f"round={round_num}",
        f"status={status}",
    ]
    for k, v in extras.items():
        if v is None:
            continue
        if isinstance(v, float):
            parts.append(f"{k}={v:.2f}")
        else:
            parts.append(f"{k}={v}")
    _debug_log(workspace, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {' '.join(parts)}")


def _print_round_scores(
    round_num: int,
    score_json: dict,
    current_score: float,
    delta: float,
    baseline_score: float,
) -> None:
    """控制台打印：每轮总分 + dim_scores 维度（人类可读，10 分制）。"""
    dim_scores = score_json.get("dim_scores", {})
    rating = score_json.get("rating", "?")
    print(f"\n{'=' * 64}")
    print(f"[Round {round_num}] P5 evaluator 完成")
    print(f"  total    = {current_score:6.2f} / 100  ({rating})")
    print(f"  baseline = {baseline_score:6.2f}        Δ = {delta:+6.2f}")
    print(f"  {len(dim_scores)} 维评分（0~10）：")
    for k in sorted(dim_scores.keys()):
        v = dim_scores[k]
        bar = "█" * int(float(v)) + "░" * (10 - int(float(v)))
        print(f"    {k:20s} {v:5.2f}  {bar}")
    gaps = score_json.get("gaps", [])
    if gaps:
        print(f"  缺口（{len(gaps)} 个）：")
        for g in gaps[:3]:
            if isinstance(g, dict):
                print(f"    - {g.get('type', '?')}: {g.get('message', '')[:60]}")
            else:
                print(f"    - {str(g)[:80]}")
    print(f"{'=' * 64}")


def _print_round_verdict(
    round_num: int,
    verdict: str,
    delta: float,
    best_updated: bool,
    apply_result: object,
) -> None:
    """控制台打印：单轮 verdict + best_skill_updated + apply 摘要。"""
    icon = {
        "improved": "✅",
        "reverted": "⏪",
        "plateau": "⏸",
        "broken": "❌",
    }.get(verdict, "❓")
    # P0: 显示 apply_rate（applied / reported），低 rate 提示评分失真
    rate_str = f"apply_rate={apply_result.apply_rate:.2f}" if hasattr(apply_result, "apply_rate") else ""
    rate_warn = " ⚠️" if getattr(apply_result, "apply_rate", 1.0) < 0.5 else ""
    print(f"[Round {round_num}] P6 summary {icon} verdict={verdict} Δ={delta:+.2f} "
          f"best_updated={best_updated} applied={apply_result.applied}/"
          f"{getattr(apply_result, 'reported', apply_result.applied)} "
          f"({rate_str}) skipped={apply_result.skipped} failed={apply_result.failed}{rate_warn}")


def _print_final_summary(
    history: list[RoundResult],
    best_score: float,
    final_status: str,
) -> None:
    """控制台打印：所有轮总结 + best score。"""
    print(f"\n{'#' * 64}")
    print(f"# 静态优化完成 status={final_status}")
    print(f"# 轮数：{len(history)}    best_score={best_score:.2f}")
    for r in history:
        print(f"#   Round {r.round_num}: score={r.score:6.2f}  "
              f"Δ={r.delta:+6.2f}  verdict={r.verdict}  applied={r.modifications_applied}")
    print(f"{'#' * 64}\n")


def run_static_optimization(config: StaticConfig) -> list[RoundResult]:
    """主循环（ 五五开融合）：6 phase 状态机 + REWORK retry + 触顶 break。

    产物约定（对齐 /skill_evolve + AgentGenesis progress-state.yaml）：
      workspace/
        config.json                  — 任务元信息
        progress-state.yaml          — ⭐ 6 phase 状态机 + REWORK 历史
        skill/{Name}/                 — 工作副本
        round_{N}_before_skill/skill/{Name}/
        round_{N}_after_skill/skill/{Name}/
        round_{N}/score.json
        round_{N}/round_result.json   — 合并 proposal + apply + validation
        best_skill/{Name}/ + best_skill_info.json
        static_history.json
    """
    import time as _t

    from .static_apply import (append_round_summary, apply_modifications,
                               collect_assets_snapshot,
                               finalize_progress_state, init_progress_state,
                               prepare_workspace_skill_copy, snapshot_skill,
                               update_progress_phase, validate_assets,
                               write_skill_metadata)

    logger.info(
        "启动静态优化 : skill=%s rounds=%d break=%.1f",
        config.skill_path,
        config.max_rounds,
        config.break_threshold,
    )

    # 0. 加载 framework YAML（rubric / anti_patterns / patterns / hl_rules / rework_policy）
    framework_cfg = load_framework_config()
    logger.info("framework config 已加载: %d 个段", len(framework_cfg))

    # .1:合并业务方 dim_overrides(让业务方在 optimize-user-config.yaml 直接覆盖
    # framework YAML 里的任意 dim 字段,如 weight / criteria / detection_keywords 等,
    # 不必动 framework YAML)。
    # .2:同时合并 dim_weights(扁平写法,展开为 dim_overrides.dim{N}.weight,
    # 保证 weight 单一来源,避免 invoke_evaluator 读 framework_yaml.weight 与 dim_weights 不一致)。
    user_cfg = _load_user_config_full()
    dim_weights = user_cfg.get("dim_weights", {}) if isinstance(user_cfg, dict) else {}
    dim_overrides = user_cfg.get("dim_overrides", {}) if isinstance(user_cfg, dict) else {}
    merged_overrides = expand_dim_weights(dim_weights, dim_overrides)
    framework_cfg = apply_dim_overrides(framework_cfg, merged_overrides)

    rework_policy = framework_cfg.get("rework_policy", {})
    max_attempts = int(rework_policy.get("max_attempts", 3))
    backoff_seq = list(rework_policy.get("backoff_seconds", [2, 4, 8]))
    trigger_phases = set(rework_policy.get("trigger_phases", ["P3", "P5"]))
    logger.info(
        "rework_policy: max_attempts=%d backoff=%s trigger_phases=%s",
        max_attempts, backoff_seq, trigger_phases,
    )

    # 0.5 准备 skill 工作副本
    original_skill_root = config.skill_path.parent
    skill_name = original_skill_root.name
    skill_root = prepare_workspace_skill_copy(
        original_skill_root, config.workspace, skill_name,
    )
    write_skill_metadata(
        config.workspace, original_skill_root, skill_name,
        framework_loaded=bool(framework_cfg),
        # .12+：把 StaticConfig 的所有参数都写入 config.json,完整呈现本轮配置
        # （用户可见,便于审计;改默认值不影响后续运行——config.json 是 state 而非 config）
        max_rounds=config.max_rounds,
        max_files=config.max_files,
        protected_assets=list(config.protected_assets),
        break_threshold=config.break_threshold,
        expert_guidance=config.expert_guidance,
        no_revert=config.no_revert,
        eval_mode=config.eval_mode,
        eval_runs=config.eval_runs,
        hitl_pass_threshold=config.hitl_pass_threshold,
        hitl_revert_threshold=config.hitl_revert_threshold,
        hitl_on_human_review=config.hitl_on_human_review,
        hitl_interactive_timeout_seconds=config.hitl_interactive_timeout_seconds,
    )
    workspace_skill_path = skill_root / config.skill_path.name

    # 0.6 初始化 progress-state.yaml（AgentGenesis 6 phase）
    task_id = f"skill_optimize_taskid_{_t.strftime('%Y%m%d_%H%M%S')}"
    state_path = init_progress_state(
        config.workspace, skill_name, task_id,
        rework_policy=rework_policy,
        eval_mode=config.eval_mode,
    )

    frontmatter, fm_protected = parse_frontmatter(workspace_skill_path)
    protected_assets = merge_protected_assets(
        cli_arg=config.protected_assets,
        frontmatter_declared=fm_protected,
    )
    logger.info("protected_assets 白名单: %s", protected_assets)

    target_files = collect_target_files(skill_root, config.max_files)
    logger.info("扫描到 %d 个待优化文件", len(target_files))

    history: list[RoundResult] = []
    baseline_score: Optional[float] = None
    best_score: float = -1.0
    best_round: int = 0  # -D：记录最高分对应的轮次（用于跨轮继承源 = best_round 而非 round_num-1）
    final_status: str = "done"

    # ：当前"采纳状态"指针。初始 = skill_root（基线）。
    # 每轮 P6 根据分数判断是否采纳 worktree；采纳后 current_skill_root = worktree_root，
    # 下一轮 P2 从 current_skill_root snapshot before，避免 skill_root 被改写。
    current_skill_root = skill_root

    # 在 baseline 评估前先构造关系树，供 baseline evaluator 与后续各轮 optimizer 共用
    _ensure_relation_tree(config, skill_root, target_files)

    #  B 方案:在所有 R1 评估之前先做一次 baseline 评估(round_num=0)
    # baseline 折线作为雷达图的"原始锚点";不应用任何 modifications,只评估 SKILL.md 现状
    # baseline 评估结果不入 history(避免污染 best_score 比较),但 dim_scores 单独保存
    baseline_dim_scores: dict[str, float] = {}
    baseline_token_count: int | None = None
    try:
        from .static_agents import evaluate_with_runs
        baseline_score_path = config.workspace / "round_0" / "score.json"
        baseline_score_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_result = evaluate_with_runs(
            skill_root=skill_root,
            target_files=target_files,
            config=config,
            framework_cfg=framework_cfg,
            output_path=baseline_score_path,
            round_num=0,  # round_num=0 标记为 baseline
            n_runs=config.eval_runs,
        )
        baseline_dim_scores = dict(baseline_result.get("dim_scores") or {})
        baseline_score = float(baseline_result.get("total", 0.0))  # 同时作为 R1 的 baseline
        #  D:保存原始 baseline_score,后续 R1 改进后 baseline_score 会被更新
        # 写 static_history 的 baseline entry 必须用原始值,避免 baseline 也被 R1 后的高分污染
        original_baseline_score = baseline_score
        #  P1-6:记录 baseline token 数,供 efficiency 维度跨轮对比
        try:
            baseline_skill_md = skill_root / "SKILL.md"
            baseline_token_count = (
                len(baseline_skill_md.read_text(encoding="utf-8")) // 4
                if baseline_skill_md.exists()
                else None
            )
        except (OSError, UnicodeDecodeError):
            baseline_token_count = None
        logger.info(
            "[baseline] 评估完成: total=%.2f, dims=%d, tokens=%s",
            baseline_score, len(baseline_dim_scores), baseline_token_count,
        )
    except Exception as e:  # noqa: BLE001
        # .13+ 治本：baseline 失败不能只 logger.warning 静默吞错。
        # 必须留 3 个痕迹：1)progress-state 记 P0 broken；2)round_0/score.json 写 _error；
        # 3)logger.error（不静默）。否则用户看到 round_0 空目录无法排障。
        import sys
        import traceback
        err_msg = str(e) or repr(e)
        err_tb = "".join(traceback.format_exception(*sys.exc_info()))[-2000:]

        # 1) logger.error（替代原 logger.warning，让失败进 stderr/日志系统）
        logger.error(
            "[baseline] 评估失败（异常已记录到 round_0/score.json + progress-state）: %s",
            err_msg,
        )

        # 2) 写 round_0/score.json（含 _error），让 round_0 不再是空目录
        # 不阻塞主流程（ 容错），但留产物可审计
        try:
            import json as _json
            baseline_error_payload = {
                "round": 0,
                "total": 0.0,
                "rating": "UNSCORED",
                "dim_scores": {},
                "gaps": [],
                "anti_pattern_hits": [],
                "expert_guidance_ref": "",
                "_error": err_msg[:500],
                "_traceback": err_tb,
                "_note": "baseline 评估失败,主流程已 fallback 到空 baseline_dim_scores 继续。详见 _debug/runtime.log + agent_*.txt",
            }
            (config.workspace / "round_0" / "score.json").write_text(
                _json.dumps(baseline_error_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as write_err:
            logger.error("[baseline] 写 round_0/score.json 也失败: %s", write_err)

        # 3) 写 progress-state 记 P0 阶段 broken（让 runtime.log 有痕迹）
        try:
            update_progress_phase(
                state_path, "P0_baseline", "broken", round_num=0,
                extra={"error": err_msg[:500]},
            )
        except Exception as prog_err:
            logger.error("[baseline] 写 progress-state 也失败: %s", prog_err)

        #  容错:不阻塞主流程,fallback 到空 baseline 让后续 round 继续
        baseline_dim_scores = {}
        baseline_token_count = None

    for round_num in range(1, config.max_rounds + 1):
        round_dir = config.workspace / f"round_{round_num}"
        round_dir.mkdir(parents=True, exist_ok=True)

        # ========== P1 planner（pure 计算）==========
        update_progress_phase(state_path, "P1", "running", round_num=round_num)
        budget = _compute_modification_budget(round_num)
        # : 删除 chars_budget 硬限制。盲限制字数无意义，会拦截所有非 SKILL.md 改动。
        # 改为由 prompt 引导 LLM 控制单条 mod 长度（≤ 5000 字符）。
        # P1-A: ceiling 检测 - 高分 baseline 走保守模式，避免 R3 爆改触发 revert
        current_best_p1 = max(baseline_score if baseline_score is not None else 0.0, best_score)
        ceiling_mode = _is_ceiling_mode(round_num, current_best_p1)
        if ceiling_mode:
            budget = min(budget, CEILING_MAX_BUDGET)
            logger.info(
                "[Round %d] ceiling_mode 触发: current_best=%.2f >= %.0f, budget=%d",
                round_num, current_best_p1, CEILING_THRESHOLD, budget,
            )
        update_progress_phase(
            state_path, "P1", "done", round_num=round_num,
            extra={
                "modification_budget": budget,
                "ceiling_mode": ceiling_mode,
            },
        )
        _debug_log_phase(config.workspace, "P1", round_num, "done",
                         budget=budget, ceiling_mode=ceiling_mode)
        logger.info("[Round %d] P1 planner: budget=%d ceiling_mode=%s",
                    round_num, budget, ceiling_mode)

        # ========== P2 reviewer（darwin 内部动作）==========
        update_progress_phase(state_path, "P2", "running", round_num=round_num)
        before_snap = (
            round_dir / f"round_{round_num}_before_skill" / "skill" / skill_name
        )
        # ：snapshot 当前"采纳状态"（上一轮 after 或初始基线），
        # 不再 snapshot skill_root —— skill_root 是只读基线，全程不变。
        snapshot_skill(current_skill_root, before_snap)
        sha_before = git_snapshot(
            config.workspace, f"round_{round_num}_before_auto",
        )
        assets_snapshot = collect_assets_snapshot(current_skill_root, protected_assets)

        # ：创建本轮 worktree（从 current_skill_root 拷贝），所有 apply/evaluate
        # 在 worktree 上做；不污染 skill_root 基线。
        worktree_root = round_dir / "worktree" / skill_name
        if worktree_root.exists():
            shutil.rmtree(worktree_root)
        worktree_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(current_skill_root, worktree_root)

        # .x 加固：scrub worktree 内 evaluator artifact（防上轮残留 + 防 sub-agent 写错位置）
        # 严格按 basename regex 匹配，其他文件不动；误删风险为零
        import re as _re_optimizer_scrub
        _OPTIMIZER_SCRUB_RE = _re_optimizer_scrub.compile(
            r"^(score\.sub\d+(?:\.retry\d+)?\.json|backup_score[^/]*\.json)$"
        )
        _scrubbed = 0
        for stray in worktree_root.rglob("*.json"):
            if _OPTIMIZER_SCRUB_RE.match(stray.name):
                try:
                    stray.unlink(missing_ok=True)
                    _scrubbed += 1
                except OSError:
                    pass
        if _scrubbed:
            logger.info(
                "[Round %d] P2 worktree scrub: 清理 %d 个 evaluator artifact",
                round_num, _scrubbed,
            )

        update_progress_phase(state_path, "P2", "done", round_num=round_num)
        _debug_log_phase(config.workspace, "P2", round_num, "done",
                         protected=len(protected_assets))
        logger.info("[Round %d] P2 reviewer: before snapshot done", round_num)

        # ========== P3 builder（REWORK 包裹）==========
        update_progress_phase(state_path, "P3", "running", round_num=round_num)
        # 用上一轮 score_json（首轮 history 为空，从 baseline_score.json 读完整 dim_scores/gaps/anti_patterns）
        prev_score = history[-1] if history else None
        if prev_score is not None:
            score_for_p3 = {"total": prev_score.score, "round": prev_score.round_num}
        else:
            # Round 1 根治：baseline 不在 history 里 → 从 round_0/score.json 读完整 score_json
            # 否则 optimizer 看不到真实 dim_scores（看到 total=0），默认按 HL-1/HL-2 杠杆点
            # 全改 SKILL.md（不会触碰 scripts/templates 等附属文件）
            baseline_score_path = config.workspace / "round_0" / "score.json"
            if baseline_score_path.is_file():
                try:
                    baseline_data = json.loads(
                        baseline_score_path.read_text(encoding="utf-8"),
                    )
                    score_for_p3 = {
                        "total": baseline_data.get("total", 0.0),
                        "round": 0,
                        "dim_scores": baseline_data.get("dim_scores", {}),
                        "gaps": baseline_data.get("gaps", []),
                        "anti_pattern_hits": baseline_data.get("anti_pattern_hits", []),
                    }
                except (OSError, json.JSONDecodeError):
                    score_for_p3 = {"total": 0.0, "round": 0}
            else:
                score_for_p3 = {"total": 0.0, "round": 0}

        # 构造/刷新文件关系树（破 SKILL.md 偏向），写 workspace 顶层供 optimizer 读
        p3_relation_tree = _ensure_relation_tree(config, skill_root, target_files)

        #  Top 3：构造 revise_signals（避免重复上轮失败）
        p3_revise_signals = None
        p3_overfit_signals = None
        p3_apply_failure_signals = None
        # 连续单文件覆盖警告（不依赖 extract_revise_signals，直接读 history）
        p3_coverage_warning = _check_consecutive_single_file(history, config.workspace)
        if prev_score is not None and round_num > 1:
            from .static_apply import extract_revise_signals as _ers

            #  v15+ 修复：dim_improvements 语义 = 上一轮相对上上轮的 regressed
            # 原代码 bug:cur_rr_stub.dim_scores 来自 score_for_p3(只有 total/round),
            #   缺失 dim_scores → extract_revise_signals 把缺失当作 0,
            #   delta = 0 - prev = -prev_value,所有 dim 都被误标 regressed 且值错。
            # 新语义:cur = history[-1].dim_scores(已跑完的最近一轮),
            #         prev = history[-2].dim_scores(更早一轮)。
            #   仅在 history 长度 ≥ 2 时计算,否则 dim_improvements 留空(无 regressed 信号)
            cur_dim_for_compare: dict[str, float] = {}
            prev_dim_for_compare: dict[str, float] = {}
            prev_rr = None  # 默认值:覆盖"history 不足 2 轮"和"文件不存在/解析失败"两条路径
            if history and len(history) >= 1:
                cur_dim_for_compare = dict(history[-1].dim_scores or {})
            #  v15+ 修复:prev 来源两条路径
            # 路径 A(history ≥ 2):prev = history[-2].round_num 对应的 round_result.json
            # 路径 B(history == 1):prev = round_0/score.json 的 baseline_dim_scores(baseline 不在 history 里)
            if history and len(history) >= 2:
                prev_round_num = history[-1].round_num - 1
                prev_round_result_path = (
                    config.workspace / f"round_{prev_round_num}" / "round_result.json"
                )
                if prev_round_result_path.is_file():
                    try:
                        prev_rr = json.loads(
                            prev_round_result_path.read_text(encoding="utf-8"),
                        )
                        prev_dim_for_compare = dict(
                            prev_rr.get("dim_scores")
                            or prev_rr.get("_score_block", {}).get("dim_scores")
                            or {}
                        )
                    except (OSError, json.JSONDecodeError):
                        prev_dim_for_compare = {}
            elif history and len(history) == 1:
                # 路径 B:baseline 在 round_0/score.json(不是 round_result.json)
                baseline_score_path = config.workspace / "round_0" / "score.json"
                if baseline_score_path.is_file():
                    try:
                        prev_rr = json.loads(
                            baseline_score_path.read_text(encoding="utf-8"),
                        )
                        prev_dim_for_compare = dict(
                            prev_rr.get("dim_scores") or {}
                        )
                    except (OSError, json.JSONDecodeError):
                        prev_dim_for_compare = {}
            cur_rr_stub = {"dim_scores": cur_dim_for_compare}
            # 仅当 prev 真实存在(且有 dim_scores)时才调 _ers
            if prev_rr is not None and prev_dim_for_compare:
                try:
                    p3_revise_signals = _ers(cur_rr_stub, prev_rr)
                    #  P1-B：提取 overfit 反馈闭环
                    p3_overfit_signals = p3_revise_signals.get("overfit_signals") or None
                    #  P2-A：提取 apply 失败根因列表
                    p3_apply_failure_signals = p3_revise_signals.get("apply_failure_signals") or None
                except (OSError, json.JSONDecodeError):
                    p3_revise_signals = None

            # 合并连续单文件覆盖警告（如有）
            if p3_coverage_warning and p3_revise_signals:
                existing = p3_revise_signals.get("file_coverage_warning", {}) or {}
                if isinstance(existing, dict):
                    existing["warning_msg"] = (
                        existing.get("warning_msg", "")
                        + ("\n" + p3_coverage_warning if existing.get("warning_msg") else p3_coverage_warning)
                    )
                    p3_revise_signals["file_coverage_warning"] = existing
            elif p3_coverage_warning and not p3_revise_signals:
                # 没有其他 revise_signals 但需要注入覆盖警告
                p3_revise_signals = {
                    "applied_mods": [], "failed_mods": [],
                    "dim_improvements": {}, "warnings": [],
                    "overfit_signals": None, "apply_failure_signals": None,
                    "file_coverage_warning": {"warning_msg": p3_coverage_warning},
                }

        # R2+ 接续优化：调起 StaticRevisionAgent 全量吸收 round_0 ~ round_{N-1} 产物，
        # 生成 revision_strategy 段注入 P3 prompt 顶部（R2+ 接续优化策略）。
        p3_revision_strategy: Optional[dict] = None
        if round_num >= 2:
            try:
                from .static_agents import invoke_revision_agent as _ira
                p3_revision_strategy = _ira(
                    workspace=config.workspace,
                    config=config,
                    round_num=round_num,
                    framework_cfg=framework_cfg,
                )
            except Exception as _e:
                logger.warning(
                    "[Round %d] revision agent 失败,继续走无 strategy 路径: %s",
                    round_num, _e,
                )
                p3_revision_strategy = None

        def _p3_call(attempt: int = 0) -> dict:
            # ：把 target_files 从 skill_root 锚定重新锚定到 worktree_root，
            # 保证 _read_skill_and_files 的 f.relative_to(skill_root) 不抛 ValueError
            worktree_target_files = [
                worktree_root / f.relative_to(skill_root)
                for f in target_files
                if f.is_relative_to(skill_root)
            ]
            # 写 proposal.md 到 round_{N}/(默认 .md, 同步写 .json 备份便于机器读)
            round_dir = config.workspace / f"round_{round_num}"
            proposal_md_path = round_dir / "proposal.md"
            import time as _t_p3
            _t_p3_0 = _t_p3.monotonic()
            logger.info(
                "[P3 builder 启动调用 optimizer-agent] round=%d attempt=%d target_files=%d",
                round_num, attempt, len(worktree_target_files),
            )

            _p3_result = invoke_optimizer(
                worktree_root, worktree_target_files, config, round_num,
                score_for_p3, proposal_md_path, framework_cfg=framework_cfg,
                attempt=attempt,
                relation_tree=p3_relation_tree,
                revise_signals=p3_revise_signals,
                overfit_signals=p3_overfit_signals,
                apply_failure_signals=p3_apply_failure_signals,
                revision_strategy=p3_revision_strategy,
                score_mode=config.score_mode,
            )

            _p3_dur = _t_p3.monotonic() - _t_p3_0
            logger.info(
                "[P3 builder 完成] round=%d attempt=%d duration=%.1fs mods=%d",
                round_num, attempt, _p3_dur, len(_p3_result.get("modifications", [])),
            )
            # 根治 P3 0 次 Read 硬约束已删除（之前导致 123242 任务 REWORK 失败 3 次 → no-op → 分数无提升）
            # 现在的策略：C 方案 prompt 中"按逻辑从 SKILL.md 触发全读 5 步指令"已足够引导 optimizer 主动 Read
            # framework 端不再强行 REWORK（这是过度工程——LLM 可能合理生成 mods 而不 Read）
            return _p3_result

        def _p3_validate(r: dict) -> bool:
            return isinstance(r.get("modifications"), list)

        def _p3_check_read_called(attempt: int) -> bool:
            """根治：检查 optimizer-agent 实际是否用 Read 工具读取了文件。

            之前问题：optimizer 看到 35 个文件清单 + "按逻辑全读"指令后**仍 0 次 Read**，
            导致凭 prompt 已有信息做决策（broken cross-ref 误判 + 没考虑全部文件）。
            根治：framework 端**强制** Read 工具调用 > 0（不读则 REWORK）。
            """
            debug_dir = config.workspace / "_debug"
            if not debug_dir.is_dir():
                return True  # 无 _debug 目录（异常情况）→ 跳过校验
            # 找本次 attempt 的 optimizer log（最新）
            opt_logs = sorted(
                debug_dir.glob("agent_optimizer-agent_*.txt"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not opt_logs:
                return True
            latest_log = opt_logs[0]
            try:
                content = latest_log.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return True
            # 统计 Read 工具调用（"Read(" 出现次数 + "[tool_use] Read" 标记）
            read_count = content.count('"name": "Read"') + content.count("[tool_use] Read(")
            if read_count == 0:
                logger.warning(
                    "[Round %d attempt=%d] optimizer-agent 0 次 Read 工具调用 → 强制 REWORK "
                    "(C 方案指令不足，framework 必须硬约束)",
                    round_num, attempt,
                )
                return False
            logger.info(
                "[Round %d attempt=%d] optimizer-agent Read 工具调用 %d 次 ✓",
                round_num, attempt, read_count,
            )
            return True

        if "P3" in trigger_phases:
            proposal = _run_phase_with_rework(
                state_path, "P3", max_attempts, backoff_seq, round_num,
                _p3_call, _p3_validate,
            )
        else:
            proposal = _p3_call(0)

        # 前后双防护·前端：P3 proposal 拿到后立即校验 .py after 内容（避免坏 mod 进入 P4 apply）
        # 与后端 P1-D（P4 apply 后 ast.parse）形成前后双保险；前端只诊断+日志，阻断交给后端
        import ast as _ast_p3
        p3_syntax_errors: list[str] = []
        for mod in (proposal or {}).get("modifications", []):
            if mod.get("file", "").endswith(".py") and mod.get("after"):
                try:
                    _ast_p3.parse(mod["after"])
                except SyntaxError as e:
                    p3_syntax_errors.append(
                        f"{mod['file']}: mod.after L{e.lineno} {e.msg} (before 长度={len(mod.get('before',''))})"
                    )
        if p3_syntax_errors:
            debug_dir = config.workspace / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"p3_syntax_warnings_round_{round_num}.log").write_text(
                f"# P3 提案语法预检警告（round={round_num}）\n"
                f"# 说明：optimizer 生成的 mod.after 存在 Python 语法错误\n"
                f"# 处理：仅诊断+记录，P4 apply 后端硬阻断（ast.parse）兜底\n"
                f"# 改进方向：要求 optimizer 提交前用 `python3 -c \"import ast; ast.parse(...)\"` 自检\n\n"
                + "\n".join(p3_syntax_errors),
                encoding="utf-8",
            )
            logger.warning(
                "[Round %d] P3 提案含 %d 条 .py 语法错误，详情见 _debug/p3_syntax_warnings_round_%d.log",
                round_num, len(p3_syntax_errors), round_num,
            )

        if proposal is None:
            # .7 兜底：P3 REWORK 全部失败时不再 break R2，降级到 no-op
            # 让 P4-P6 继续评估当前 best_skill（不应用任何修改但保持 best_score）
            update_progress_phase(
                state_path, "P3", "broken", round_num=round_num,
                extra={"reason": "max_attempts exceeded, fallback to no-op"},
            )
            logger.warning(
                "[Round %d] P3 REWORK 全部失败,降级为 no-op（评估当前 best_skill）",
                round_num,
            )
            proposal = {
                "modifications": [],
                "diagnosis": {"error": "REWORK 超限", "fallback": "no_change"},
                "_error": "P3 REWORK failed after max_attempts; 降级 no-op",
                "_fallback": True,
            }
            # final_status 保留 broken（让用户知道 R 失败），但不 continue 走后续 P4-P6

        update_progress_phase(
            state_path, "P3", "done", round_num=round_num,
            extra={"modifications_count": len(proposal.get("modifications", []))},
        )
        _debug_log_phase(config.workspace, "P3", round_num, "done",
                         mods=len(proposal.get("modifications", [])))

        # ========== P4 verifier（darwin 内部动作，无 REWORK）==========
        update_progress_phase(state_path, "P4", "running", round_num=round_num)
        #  Top 6：dry_run 模式跳过 apply_modifications
        if config.eval_mode == "dry_run":
            logger.info("[Round %d] dry_run 模式：跳过 apply_modifications", round_num)
            from dataclasses import replace as _dc_replace
            apply_result = _dc_replace(
                apply_modifications(
                    skill_root=worktree_root, modifications=[],
                    protected_assets=protected_assets, workspace=config.workspace,
                ),
                applied=0, files_changed=[], errors=["dry_run: skipped"],
            )
            from .static_apply import increment_dry_run_count as _idrc
            _idrc(state_path)
        else:
            apply_result = apply_modifications(
                skill_root=worktree_root,
                modifications=proposal.get("modifications", []),
                protected_assets=protected_assets,
                workspace=config.workspace,
            )
        if apply_result.errors:
            for err in apply_result.errors:
                logger.warning("[Round %d] apply: %s", round_num, err)
        asset_validation = validate_assets(
            skill_root=worktree_root,
            protected_assets=protected_assets,
            expected_hashes=assets_snapshot,
        )
        sha_after = git_snapshot(
            config.workspace, f"round_{round_num}_after_auto",
        )
        # ：after_snap 不再立即 snapshot，由 P6 根据分数判断是否采纳。
        # 路径变量保留，P6 会用到。
        after_snap = (
            round_dir / f"round_{round_num}_after_skill" / "skill" / skill_name
        )

        #  Top 4：check_overfit（warn-only，不强制 break）
        from .static_apply import check_overfit as _cof
        total_size_before_apply = sum(
            p.stat().st_size for p in worktree_root.rglob("*") if p.is_file()
        ) - sum(
            (worktree_root / f).stat().st_size if (worktree_root / f).exists() else 0
            for f in apply_result.files_changed
        )
        overfit_report = _cof(
            modifications=proposal.get("modifications", []),
            original_size=max(total_size_before_apply, 1),
        )
        if overfit_report.get("warning"):
            for reason in overfit_report["reasons"]:
                logger.warning("[Round %d] overfit warning: %s", round_num, reason)
            # P1-B 根治：硬阻断信号升级（段落重复 / 引用闭合）→ 直接进 apply_result.errors 触发 P4 重做
            hard_blocks = [r for r in overfit_report["reasons"] if r.startswith("[hard_block]")]
            if hard_blocks:
                apply_result.errors.extend(hard_blocks)
                logger.error("[Round %d] P4 硬阻断 %d 条，本轮不进入 P5", round_num, len(hard_blocks))
                from .static_apply import record_rework as _rr
                _rr(state_path, "P4", 0, "hard_block: " + "; ".join(hard_blocks), 0, "blocked", round_num=round_num)
        overfit_warning = bool(overfit_report.get("warning"))

        # P1-D 根治：apply 后立即校验所有 .py 语法，失败则进 _debug + 跳过 P5 触发回退
        import ast as _ast
        syntax_errors: list[str] = []
        for py_file in worktree_root.rglob("*.py"):
            try:
                _ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                syntax_errors.append(f"{py_file.relative_to(worktree_root)}:L{e.lineno} {e.msg}")
        if syntax_errors:
            debug_dir = config.workspace / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"p4_syntax_errors_round_{round_num}.log").write_text(
                f"# P4 syntax check failed (round={round_num})\n"
                f"# 触发：optimizer 生成/apply 后存在 Python 语法错误\n"
                f"# 影响：本轮不进入 P5，触发回退到 before_snap\n\n"
                + "\n".join(syntax_errors),
                encoding="utf-8",
            )
            logger.error("[Round %d] P4 语法校验失败 %d 条，已写入 _debug/p4_syntax_errors_round_%d.log，跳过 P5",
                         round_num, len(syntax_errors), round_num)
            from .static_apply import record_rework as _rr_syn
            _rr_syn(state_path, "P4", 0, "syntax_error: " + "; ".join(syntax_errors[:3]), 0, "blocked", round_num=round_num)
            apply_result.errors.extend([f"[hard_block] {e}" for e in syntax_errors])
            overfit_warning = True  # 阻断 P5 推进

        update_progress_phase(
            state_path, "P4", "done", round_num=round_num,
            extra={
                "applied": apply_result.applied,
                "overfit_warning": overfit_warning,
                "overfit_reasons": overfit_report.get("reasons", []),
            },
        )
        _debug_log_phase(config.workspace, "P4", round_num, "done",
                         applied=apply_result.applied)

        # ========== P5 evaluator（REWORK 包裹）==========
        # P1-D 根治：P4 语法错误时仍走 P5（evaluator 会扣 dim10/dim12），但 errors 已含语法错 → P6 触发回退
        update_progress_phase(state_path, "P5", "running", round_num=round_num)
        score_path = round_dir / "score.json"

        def _p5_call(attempt: int = 0) -> dict:
            """：P5 evaluator 子调用，并发跑 N 次取均值"""
            from .static_agents import evaluate_with_runs

            # ：target_files 重新锚定到 worktree_root（与 _p3_call 同源）
            worktree_target_files = [
                worktree_root / f.relative_to(skill_root)
                for f in target_files
                if f.is_relative_to(skill_root)
            ]
            return evaluate_with_runs(
                skill_root=worktree_root,
                target_files=worktree_target_files,
                config=config,
                framework_cfg=framework_cfg,
                output_path=score_path,
                round_num=round_num,
                n_runs=config.eval_runs,
                baseline_token_count=baseline_token_count,  # .5:让 efficiency 维度能算 token 增量
            )

        def _p5_validate(r: dict) -> bool:
            ds = r.get("dim_scores")
            # .3:从 framework_cfg.rubric 动态算最小 dim 数,不再硬编码 9
            # 业务方启用多少个 auto 维度(rubric 中 compute_mode=auto 且 enabled_dimensions=true)
            # 加 LLM 评的 dim,共同决定最小期望。
            rubric = framework_cfg.get("rubric", {}) or {}
            enabled_auto_keys = [
                k for k, v in rubric.items()
                if k.startswith("dim") and (v or {}).get("compute_mode") == "auto"
            ]
            try:
                from .static_agents import _load_enabled_dimensions as _led
                enabled_flags = _led()
            except (ImportError, AttributeError):
                enabled_flags = {}
            active_auto = [k for k in enabled_auto_keys if enabled_flags.get(k, False)]
            llm_dims = [
                k for k, v in rubric.items()
                if k.startswith("dim") and (v or {}).get("compute_mode") != "auto"
            ]
            expected_min = len(llm_dims) + len(active_auto)
            if expected_min <= 0:
                expected_min = 1  # 兜底:至少 1 维
            return isinstance(ds, dict) and len(ds) >= expected_min

        if "P5" in trigger_phases:
            score_json = _run_phase_with_rework(
                state_path, "P5", max_attempts, backoff_seq, round_num,
                _p5_call, _p5_validate,
            )
        else:
            score_json = _p5_call(0)

        if score_json is None:
            update_progress_phase(
                state_path, "P5", "broken", round_num=round_num,
                extra={"reason": "max_attempts exceeded"},
            )
            logger.error("[Round %d] P5 BROKEN，超限继续下一 round", round_num)
            final_status = "broken"
            continue

        current_score = float(score_json.get("total", 0.0))
        if baseline_score is None:
            baseline_score = current_score
        delta = current_score - baseline_score
        # ：把多评测元数据也写入 progress-state，便于外部观察评估稳定性
        eval_runs_meta = score_json.get("_eval_runs", {})
        update_progress_phase(
            state_path, "P5", "done", round_num=round_num, score=current_score,
            extra={
                "delta": delta,
                "rating": score_json.get("rating", "?"),
                "eval_runs": {
                    "n_requested": eval_runs_meta.get("n_requested", 1),
                    "n_succeeded": eval_runs_meta.get("n_succeeded", 1),
                    "total_stdev": eval_runs_meta.get("total_stdev", 0.0),
                    "aggregation": eval_runs_meta.get("aggregation_method", "single"),
                },
            },
        )
        _debug_log_phase(config.workspace, "P5", round_num, "done",
                         score=current_score, delta=delta,
                         rating=score_json.get("rating", "?"))
        logger.info(
            "[Round %d] P5 evaluator: score=%.2f Δ=%.2f baseline=%.2f",
            round_num, current_score, delta, baseline_score,
        )
        # 控制台打印：每轮分数 + dim_scores 维度 + rating
        _print_round_scores(round_num, score_json, current_score, delta, baseline_score)

        # 评分回退检测（：用文件快照恢复替代 git revert）
        verdict = "improved"
        if delta < 0 and not config.no_revert:
            logger.warning(
                "[Round %d] 评分回退（Δ=%.2f），从 before snapshot 恢复 worktree",
                round_num, delta,
            )
            # ：恢复到 worktree_root（不是 skill_root）
            if restore_skill_from_snapshot(worktree_root, before_snap):
                verdict = "reverted"
                current_score = baseline_score
                delta = 0.0

        # ========== P6 summary ==========
        update_progress_phase(state_path, "P6", "running", round_num=round_num)

        # ：采纳判定 + best_score 跟踪
        # 规则：本轮分数严格 > 前一轮采纳分数（前一轮改进后 baseline_score 被更新）才采纳：
        #   - snapshot worktree → round_N_after_skill
        #   - current_skill_root = worktree_root（成为下轮 before 的源）
        # 否则 after_snap 内容 = before_snap（等价无变化），current_skill_root 不变。
        # best_skill 不在本阶段写入，由循环结束后 finalize_best_skill_from_history 统一拷贝。
        prev_accepted_score = baseline_score if baseline_score is not None else 0.0
        best_updated = False
        accepted_verdicts = {"improved", "auto_pass", "human_review"}
        if verdict in accepted_verdicts and current_score > prev_accepted_score:
            #  P0-1：HITL 三层守关（auto_pass / auto_revert / human_review）
            # 1025-1036 段已处理绝对 delta<0（reverted）；此处处理相对 delta 的中间地带
            if verdict == "improved":
                if delta >= config.hitl_pass_threshold:
                    verdict = "auto_pass"
                elif delta > config.hitl_revert_threshold:
                    # 中间地带：交给 human_review 决议
                    hr_accept, hr_detail = _resolve_human_review(
                        config=config,
                        round_num=round_num,
                        delta=delta,
                        prev_accepted_score=prev_accepted_score,
                        current_score=current_score,
                        proposal=proposal,
                    )
                    verdict = "human_review"
                    if not hr_accept:
                        # 用户/auto_accept=reject 拒绝:把 worktree 恢复到 before
                        if restore_skill_from_snapshot(worktree_root, before_snap):
                            verdict = "human_review_rejected"
                            current_score = prev_accepted_score
                            delta = 0.0
                            logger.info(
                                "[Round %d] human_review 拒绝(hitl_detail=%s),worktree 已恢复",
                                round_num, hr_detail,
                            )
                else:
                    # delta ≤ hitl_revert_threshold(理论上 1025 段已接 reverted,这里兜底)
                    verdict = "auto_revert"
                    if restore_skill_from_snapshot(worktree_root, before_snap):
                        current_score = prev_accepted_score
                        delta = 0.0
                        logger.info(
                            "[Round %d] auto_revert(Δ=%.2f ≤ %.2f),worktree 已恢复",
                            round_num, delta, config.hitl_revert_threshold,
                        )

            # 采纳（verdict ∈ {auto_pass, human_review}且 current_score > prev_accepted）
            if current_score > prev_accepted_score:
                snapshot_skill(worktree_root, after_snap)
                current_skill_root = worktree_root
                best_score = current_score
                best_round = round_num
                best_updated = True
                logger.info(
                    "[Round %d] 采纳（verdict=%s, score=%.2f > prev=%.2f）：worktree → after_snap",
                    round_num, verdict, current_score, prev_accepted_score,
                )
            else:
                # 未采纳：after_snap 内容 = before_snap（等价无变化）
                snapshot_skill(before_snap, after_snap)
                logger.info(
                    "[Round %d] 未采纳（verdict=%s, score=%.2f ≤ prev=%.2f），after_snap = before_snap",
                    round_num, verdict, current_score, prev_accepted_score,
                )
        else:
            # 未采纳：after_snap 内容 = before_snap（等价无变化）
            snapshot_skill(before_snap, after_snap)
            logger.info(
                "[Round %d] 未采纳（verdict=%s, score=%.2f ≤ prev=%.2f），after_snap = before_snap",
                round_num, verdict, current_score, prev_accepted_score,
            )

        # 写 round_result.json（合并 proposal + apply + validation + score）
        #  A 方案:计算 regressed_dims(相对上一轮 regressed 的 dim)
        cur_dim_scores = dict(score_json.get("dim_scores") or {})
        prev_dim_scores = history[-1].dim_scores if history else {}
        regressed_dims: list[str] = []
        for k, v in cur_dim_scores.items():
            prev_v = prev_dim_scores.get(k)
            if prev_v is not None and v < prev_v:
                regressed_dims.append(k)
        #  A 方案:regressed_warning = 上轮 regressed 但本轮 mod 未覆盖的 dim
        regressed_warning: list[str] = []
        if history and history[-1].regressed_dims:
            covered_by_mods = {
                mod.get("dim_improved", "")
                for mod in (proposal.get("modifications") or [])
            }
            regressed_warning = [
                d for d in history[-1].regressed_dims
                if d and d not in covered_by_mods
            ]
        result = RoundResult(
            round_num=round_num,
            score=current_score,
            baseline_score=baseline_score,
            delta=delta,
            verdict=verdict,
            modifications_applied=apply_result.applied,
            files_changed=apply_result.files_changed,
            sha_before=sha_before or "",
            sha_after=sha_after or "",
            dim_scores=cur_dim_scores,  # 
            regressed_dims=regressed_dims,  #  A 方案
            regressed_warning=regressed_warning,  #  A 方案
        )
        #  A 方案:regressed soft target 命中情况(纯日志,warn-only 不阻断)
        if regressed_warning:
            logger.warning(
                "[Round %d] regressed soft target missed: %s (上轮 regressed 但本轮 mod 未覆盖)",
                round_num, regressed_warning,
            )
        if regressed_dims:
            logger.info(
                "[Round %d] 本轮 regressed dims: %s (下轮将作为 soft target 提示)",
                round_num, regressed_dims,
            )
        history.append(result)
        merged = {
            **result.__dict__,
            "proposal": proposal,
            "apply": {
                "applied": apply_result.applied,
                "skipped": apply_result.skipped,
                "failed": apply_result.failed,
                "reported": getattr(apply_result, "reported", apply_result.applied),
                "apply_rate": getattr(apply_result, "apply_rate", 1.0),
                "files_changed": apply_result.files_changed,
                "errors": apply_result.errors,
                "match_failures": getattr(apply_result, "match_failures", []),
                "backup_path": apply_result.backup_path,
            },
            "asset_validation": asset_validation.__dict__,
            "verifier": {
                "overfit_warning": overfit_warning,
                "overfit_reasons": overfit_report.get("reasons", []),
                "apply_rate": getattr(apply_result, "apply_rate", 1.0),
            },
        }
        (round_dir / "round_result.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        append_round_summary(
            state_path, round_num, current_score, delta, verdict, best_updated,
        )
        update_progress_phase(
            state_path, "P6", "done", round_num=round_num, score=current_score,
            extra={"verdict": verdict, "delta": delta, "best_skill_updated": best_updated},
        )
        _debug_log_phase(config.workspace, "P6", round_num, "done",
                         score=current_score, delta=delta, verdict=verdict,
                         best_updated=best_updated)
        # 控制台打印：verdict + best_skill_updated
        _print_round_verdict(round_num, verdict, delta, best_updated, apply_result)

        # 触顶 break（HL-4）
        if check_break(history, config.break_threshold):
            logger.info("连续 %d 轮 Δ < %.1f，触顶 break", 2, config.break_threshold)
            break

        if best_updated:
            baseline_score = current_score

    # 收尾
    finalize_progress_state(state_path, status=final_status)

    # ：best_skill 收尾填充（之前每轮 P6 都在填充，现统一到结束后从 history 拷贝）
    from .static_apply import finalize_best_skill_from_history as _fb
    best_skill_path = _fb(config.workspace, skill_name, history)

    # 控制台打印：所有轮总结
    _print_final_summary(history, best_score, final_status)

    # ：-C 的 _maybe_seed_references 已删除。原逻辑是 references/ 缺失时
    # 自动创建一个 examples.md 模板，但该文件对评分/产物都无贡献（不计
    # modifications、不影响分数），纯框架噪音。删除后 LLM 仍可正常在
    # references/ 中提议/新建文件，但不会被框架兜底 seed。

    # 写历史
    history_path = config.workspace / "static_history.json"
    #  B 方案:把 baseline 也写入 static_history.json（round_num=0 作为锚点）
    history_to_persist = list(history)
    if baseline_dim_scores:
        from dataclasses import replace as _dc_replace
        baseline_entry = RoundResult(
            round_num=0,
            score=original_baseline_score or 0.0,  # 用原始 baseline(不被 R1 更新污染)
            baseline_score=original_baseline_score or 0.0,
            delta=0.0,
            verdict="baseline",
            modifications_applied=0,
            files_changed=[],
            dim_scores=baseline_dim_scores,
        )
        history_to_persist = [baseline_entry] + history_to_persist

    # .11: 把每轮 score.json 的 _eval_runs 合并到 RoundResult(否则 static_history.json
    # 缺 per_run_dim_scores / per_run_totals / total_stdev,HTML 折叠块渲染失败)
    enriched_history = []
    for r in history_to_persist:
        round_dir = (
            config.workspace / "round_0" if r.round_num == 0
            else config.workspace / f"round_{r.round_num}"
        )
        score_path = round_dir / "score.json"
        eval_runs = {}
        if score_path.exists():
            try:
                score_data = json.loads(score_path.read_text(encoding="utf-8"))
                eval_runs = score_data.get("_eval_runs", {}) or {}
            except (OSError, json.JSONDecodeError):
                pass
        # dataclass 转 dict,合并 _eval_runs
        r_dict = dict(r.__dict__)
        r_dict["_eval_runs"] = eval_runs
        enriched_history.append(r_dict)

    history_path.write_text(
        json.dumps(
            enriched_history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    try:
        import matplotlib
        logger.info("matplotlib 已安装，尝试生成雷达图")
    except ImportError:
        logger.warning("matplotlib 未安装，跳过雷达图生成")
    except Exception as e:  # noqa: BLE001
        logger.warning("雷达图生成失败（非致命）: %s", e)

    #  P1-7：HTML 可视化报告（与 PNG 雷达图并存，互补）
    # 不阻塞主流程,失败仅 warn 日志
    try:
        from .static_html_history import generate_score_history_html

        # .10+: 传 baseline（修改前）vs best_skill 路径，HTML 生成文件 diff 章节
        html_result = generate_score_history_html(
            workspace=config.workspace,
            framework_cfg=framework_cfg,
            workspace_name=skill_name,
            old_skill_path=skill_root,  # 原始 skill_root（修改前）
            new_skill_path=best_skill_path,  # best_skill_path 已定义在上面
        )
        if html_result.skipped:
            logger.warning("HTML 报告跳过：%s", html_result.reason)
        else:
            logger.info(
                "HTML 报告已生成: %s (rounds=%d dims=%d)",
                html_result.output_path, html_result.rounds_plotted, html_result.dims_plotted,
            )
    except ImportError:
        logger.warning("static_html_history 模块导入失败,跳过 HTML 报告")
        if "final_status" in dir() and final_status == "done":
            final_status = "partial_html_failed"  # .10+ 不再静默 skip，标 partial
    except Exception as e:  # noqa: BLE001
        logger.warning("HTML 报告生成失败（非致命）: %s", e)
        if "final_status" in dir() and final_status == "done":
            final_status = "partial_html_failed"  # .10+ 标 partial 让用户知道 HTML 缺失

    return history


def main() -> int:
    parser = argparse.ArgumentParser(description="/skill_optimize 静态优化器")
    parser.add_argument("--skill-path", required=True, help="SKILL.md 路径")
    parser.add_argument("--workspace", required=True, help="工作目录")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=10)
    parser.add_argument("--protected-assets", default="")
    parser.add_argument("--break-threshold", type=float, default=2.0)
    parser.add_argument("--expert-guidance", default="")
    parser.add_argument("--no-revert", action="store_true")
    #  Top 6：--dry-run 开关（仅生成 proposal，不应用）
    parser.add_argument("--dry-run", action="store_true",
                        help=": 只生成 proposal 不应用 modifications（调试用）")
    # ：每轮 evaluator 并发跑 N 次取均值（消除 LLM judge 抽样噪声）
    parser.add_argument("--eval-runs", type=int, default=3,
                        help=": 每轮 evaluator 并发跑 N 次取均值（默认 3，1=单次）")
    # .18+：评分执行路径选择（cosight 同步兼容）
    parser.add_argument("--score-mode",
                        choices=["llm_direct", "subagent"],
                        default=None,  # None → env SKILLX_SCORE_MODE → "llm_direct"
                        help=".18+: 评分路径。"
                              "llm_direct=拼 prompt 直连大模型（默认，老路径）；"
                              "subagent=cc tools.Agent 真子 Agent + 编码 skill 注入（cosight .17+ 移植）。"
                              "优先级: CLI > env SKILLX_SCORE_MODE > llm_direct。")
    parser.add_argument("--use-unified-agent",
                        choices=["true", "false"],
                        default="true",
                        help="v_next+：是否使用 unified agent（单阶段融合评分+优化）。true=新路径（默认）；false=旧 6 phase 状态机。")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    config = StaticConfig.from_args(args, workspace)

    # v_next+：dispatch 到 unified agent（单阶段）或旧 6 phase
    if getattr(config, "use_unified_agent", True):
        from .static_agents import run_unified_static_optimization
        from .static_optimizer import load_framework_config
        framework_cfg = load_framework_config()
        history_raw = run_unified_static_optimization(config, framework_cfg)
        # 转换 UnifiedRoundResult -> RoundResult 以兼容 print
        from dataclasses import asdict
        history_dicts = [asdict(h) for h in history_raw]
    else:
        history_raw = run_static_optimization(config)
        history_dicts = [r.__dict__ for r in history_raw]

    print(json.dumps(history_dicts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())