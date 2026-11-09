#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_create.py - /skill_create 命令的薄壳 Python 工具

不参与业务流程编排(由 CC 主 Agent 通过 Agent 工具调度 3 个 subagent 完成),
仅做工作区初始化、state.json 读写、产物校验 3 件事。

子命令:
  init     创建工作区 + 初始化 state.json
  status   读取 state.json,展示当前进度
  validate 校验 16 项硬约束清单(spec) + 8 项目录骨架(skill 目录)
  summary  汇总所有阶段产物路径 + 大小

用法:
  python3 scripts/commands/skill_create.py init \
    --output-dir "${OUTPUT_DIR}" \
    --skill-name "${SKILL_NAME}" \
    --start-stage 1

  python3 scripts/commands/skill_create.py status \
    --output-dir "${OUTPUT_DIR}"

  python3 scripts/commands/skill_create.py validate \
    --output-dir "${OUTPUT_DIR}" \
    --skill-name "${SKILL_NAME}"

  python3 scripts/commands/skill_create.py summary \
    --output-dir "${OUTPUT_DIR}"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - 容错:PyYAML 不可用时 config 退化为无效
    yaml = None  # type: ignore

# === 常量 ===
SKILL_CREATE_VERSION = "1.0.0"

# 工作区根目录派生优先级链(v5,2026-08-13 治理 env 废弃 + config 单一来源):
#   1. CLI 参数 --output-dir(用户显式输入,最高优先级)
#   2. config/create-user-config.yaml 的 paths.root 派生
#      `${paths.root}/${paths.evolution_subdir}`(业务方唯一配置入口)
#   3. 全部未配置 → 报错,严禁硬编码 fallback 路径(避免与具体部署耦合)
#
# 设计依据:严禁相对 cwd 创建 evolution_workspace/,否则不同 cwd 落点漂移
# (本项目原本在 skillx-alpha-agents/ 下 mkdir 落到项目根,导致污染且与
# orchestrator 落点漂移;根治方案 = 强制走 config,不依赖环境变量)。
#
# v5 变更(2026-08-13):移除 SKILLX_WORKSPACE / SKILLX_ROOT 环境变量依赖,
# --output-dir 仅由用户显式输入或 config/create-user-config.yaml 派生。
# v4 变更:.env 文件已废弃,改读 config/create-user-config.yaml,
# 与 config/optimize-user-config.yaml / config/evolve-user-config.yaml 风格一致,
# 三个 user-config 文件命名空间完全分离。
#
# 实现注意:解析是 lazy 的(只在 cmd_init 用到时才解析),不要在模块级 sys.exit,
# 否则 `python3 scripts/commands/skill_create.py --help` 在 config 未配时会失败。
_EVOLUTION_SUBDIR = "evolution_workspace"
_CREATE_USER_CONFIG_REL = Path("config") / "create-user-config.yaml"


def _resolve_from_create_user_config() -> Optional[Path]:
    """从 config/create-user-config.yaml 读 paths.root + evolution_subdir 派生 workspace。

    Returns:
        解析成功返回绝对路径;文件不存在 / 字段缺失 / PyYAML 不可用 返回 None。
    """
    if yaml is None:  # PyYAML 不可用时静默退化
        return None
    # config 相对项目根(skillx-alpha-agents/),脚本位于 scripts/commands/,
    # parents[2] = 项目根,与 _DEFAULT_GUIDELINES_PATH 同款相对路径解析。
    project_root = Path(__file__).resolve().parents[2]
    cfg_path = project_root / _CREATE_USER_CONFIG_REL
    if not cfg_path.exists():
        return None
    try:
        data: Dict[str, Any] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - YAML 解析失败静默退化,优先用 env
        return None
    paths = data.get("paths") or {}
    root_raw = str(paths.get("root") or "").strip()
    if not root_raw:
        return None
    subdir = str(paths.get("evolution_subdir") or _EVOLUTION_SUBDIR).strip() or _EVOLUTION_SUBDIR
    return (Path(root_raw).expanduser().resolve() / subdir).resolve()


def _resolve_default_workspace_root() -> Optional[Path]:
    """解析默认 workspace 根目录(config/create-user-config.yaml 单一来源)。

    不依赖 SKILLX_WORKSPACE / SKILLX_ROOT 环境变量;
    --output-dir 只由用户显式输入或本 config 派生。

    Returns:
        解析成功返回绝对路径;config 未配置返回 None(调用方应报错退出)。
    """
    return _resolve_from_create_user_config()


def _require_default_workspace_root() -> Path:
    """同 _resolve_default_workspace_root,但未配置时直接 sys.exit 报错。

    仅在 cmd_init 的"自动派生 output_dir"分支调用(不应用于模块级)。
    """
    resolved = _resolve_default_workspace_root()
    if resolved is None:
        print(
            "[ERROR] 未指定 --output-dir 且 config/create-user-config.yaml 未配置 paths.root。\n"
            "  请任选其一:\n"
            "  1) 显式传入 --output-dir <绝对路径>(用户输入,最高优先级)\n"
            "  2) 编辑 config/create-user-config.yaml 的 paths.root 字段(config 派生)\n"
            "  (详见 framework_configs/skill-create-guidelines.md)",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE_ERROR)
    return resolved

# 内置默认规范路径(3 个 subagent 默认 Load 此文件)
# 规范内容:代码化精神、LLM 断点协议、异常处理规范、16 章节模板、质量门槛等
#
# 解析优先级(根治硬编码绝对路径,2026-07-14 治理):
#   1. 环境变量 SKILLX_GUIDELINES_PATH(显式注入,绝对路径)
#   2. 相对 Path(__file__) 解析:skill_create.py 在 scripts/commands/ 下,
#      parents[2] = skillx-alpha-agents 项目根,故相对路径为
#      `<project_root>/framework_configs/skill-create-guidelines.md`
_DEFAULT_GUIDELINES_PATH: Optional[Path] = (
    Path(os.environ["SKILLX_GUIDELINES_PATH"]).expanduser().resolve()
    if os.environ.get("SKILLX_GUIDELINES_PATH", "").strip()
    else None
) or (
    Path(__file__).resolve().parents[2]
    / "framework_configs"
    / "skill-create-guidelines.md"
)


def get_default_guidelines_path() -> Path:
    """解析内置默认规范路径(供 subagent 与 docs 引用)。"""
    assert _DEFAULT_GUIDELINES_PATH is not None  # module-load time 已解析
    return _DEFAULT_GUIDELINES_PATH

# 阶段产物文件名约定
# 阶段产物文件名约定
# 阶段 1 产物名由 input 形式决定,不在此硬编码:
#   --requirement @file.md → "01_<原文件名>.md"(直接复制)
#   --requirement "<自然语言>" → "01_requirement_brief.md"(CC 走 5W1H 生成)
# init 时不预创建阶段 1 占位(避免 @file.md 场景下产生死占位)
# 阶段 1.5 已删除(2026-07-14 根治):原"02_requirement_brief.md"是死代码
#   ——STAGE_FILES 的 1.5 key 是 float,range() 不遍历,init 从未创建过。
#   删除后,阶段 2/3/4 实际产物编号 02/03/04,与阶段 1 产物 01_<...>.md 连续编号。
# 阶段 3:2026-07-11 从 .py 改为 .md(载体选择哲学见 code-implementer-agent 契约)
STAGE_FILES = {
    1: None,                          # 占位名由 input 形式决定,init 跳过
    2: "02_skill_spec.md",
    3: "03_monolithic_impl.md",
    4: "04_skill_dir",
}


# === 阶段 1 产物动态扫描 ===
def _resolve_stage1_artifact(output_dir: Path) -> Optional[Path]:
    """扫描 01_*.md,按时间顺序返回最新文件(@file.md 直接复制 + 自然语言 brief 并存时取最新)

    通用化:不绑定特定产物名,适配规范 §1.5 规定的两种 input 形式。
    """
    if not output_dir.exists():
        return None
    candidates = sorted(output_dir.glob("01_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None

# === Exit code ===
EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_FILE_NOT_FOUND = 2
EXIT_VALIDATION_FAIL = 3


# === 数据模型 ===
@dataclass
class StageStatus:
    """单个阶段的状态"""
    stage_num: int
    stage_name: str
    artifact_path: Path
    exists: bool
    size_bytes: int = 0
    passed_validation: bool = False
    validation_notes: List[str] = field(default_factory=list)


@dataclass
class WorkspaceState:
    """工作区状态(对应 state.json)"""
    output_dir: Path
    skill_name: str
    start_stage: int
    end_stage: int
    skip_stage_3: bool
    created_at: str
    completed_stages: List[int] = field(default_factory=list)
    expert_guidance: str = ""


# === 工具函数 ===
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_taskid() -> str:
    return "skill_create_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def write_state(state: WorkspaceState, state_path: Path) -> None:
    """Write state.json"""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_dict = {
        "output_dir": str(state.output_dir),
        "skill_name": state.skill_name,
        "start_stage": state.start_stage,
        "end_stage": state.end_stage,
        "skip_stage_3": state.skip_stage_3,
        "created_at": state.created_at,
        "completed_stages": state.completed_stages,
        "expert_guidance": state.expert_guidance,
    }
    state_path.write_text(
        json.dumps(state_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_state(state_path: Path) -> Optional[WorkspaceState]:
    """Read state.json,不存在返回 None"""
    if not state_path.exists():
        return None
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return WorkspaceState(
        output_dir=Path(data["output_dir"]),
        skill_name=data["skill_name"],
        start_stage=data["start_stage"],
        end_stage=data["end_stage"],
        skip_stage_3=data.get("skip_stage_3", False),
        created_at=data["created_at"],
        completed_stages=data.get("completed_stages", []),
        expert_guidance=data.get("expert_guidance", ""),
    )


# === 子命令:init ===
def cmd_init(args: argparse.Namespace) -> int:
    """创建工作区 + 初始化 state.json

    output_dir 优先级链(根治 v5):
      1. CLI --output-dir(用户显式输入,最高优先级)
      2. 未传时自动生成 ${DEFAULT_WORKSPACE_ROOT}/skill_create_<ts>/
         其中 DEFAULT_WORKSPACE_ROOT 由 _require_default_workspace_root()
         从 config/create-user-config.yaml 的 paths.root 派生(未配置则报错)

    严禁相对 cwd 创建,避免落点漂移。
    """
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        # 自动派生(lazy:首次用到时才解析,避免 --help 在 env 未设时崩)
        default_root = _require_default_workspace_root()
        output_dir = (default_root / make_taskid()).resolve()
        print(f"[INFO] --output-dir 未指定,自动派生: {output_dir}")

    # 显式指定 taskid(根治时间戳漂移,允许复用已有工作区)
    # 支持两种形式:完整名(skill_create_20260713_150041)或裸时间戳(20260713_150041)
    if args.taskid:
        taskid_name = (
            args.taskid
            if args.taskid.startswith("skill_create_")
            else f"skill_create_{args.taskid}"
        )
        # 边界:若 user 传的 --output-dir 已经是完整 taskid 路径,避免再拼一次漂到 parent 下
        if output_dir.name != taskid_name:
            output_dir = output_dir / taskid_name
        print(f"[INFO] --taskid 指定,使用: {output_dir}")

    # 边界(根治 v4):不传 --taskid 且 output_dir 恰好是 default_root 本身,
    # 自动派生 taskid 子目录;否则 init 会在 evolution_workspace 根散落 state.json / 占位文件,
    # 污染 skillx-alpha-generic.md §3.4 严禁的"配置单一来源"目录。
    default_root = _require_default_workspace_root()
    if not args.taskid and output_dir == default_root:
        auto_taskid = make_taskid()
        output_dir = default_root / auto_taskid
        print(
            f"[INFO] --taskid 未指定 + --output-dir 是 workspace 根,自动派生 taskid 子目录: {output_dir}"
        )

    # 强制落在解析出的 workspace root 下(防止 cwd 漂移污染)
    if not output_dir.is_relative_to(default_root):
        print(
            f"[ERROR] workspace({output_dir})漂出了 evolution_workspace({default_root});\n"
            f"       请检查 --output-dir / --taskid 拼出的路径是否还在 {default_root} 下。",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    output_dir.mkdir(parents=True, exist_ok=True)

    state = WorkspaceState(
        output_dir=output_dir,
        skill_name=args.skill_name,
        start_stage=args.start_stage,
        end_stage=args.end_stage,
        skip_stage_3=args.skip_stage_3,
        created_at=now_iso(),
        completed_stages=[],
        expert_guidance=args.expert_guidance or "",
    )
    state_path = output_dir / "state.json"
    write_state(state, state_path)

    # 创建阶段产物的占位文件(0 字节)
    for stage_num in range(args.start_stage, args.end_stage + 1):
        if args.skip_stage_3 and stage_num == 3:
            continue
        artifact = STAGE_FILES.get(stage_num)
        if artifact is None:
            continue
        if stage_num == 4:
            # 阶段 4 是目录
            (output_dir / artifact).mkdir(parents=True, exist_ok=True)
        else:
            # 阶段 1~3 是文件
            (output_dir / artifact).touch()

    print(f"[OK] 工作区已创建: {output_dir}")
    print(f"  - state.json: {state_path}")
    print(
        f"  - 起始阶段: {args.start_stage}, 结束阶段: {args.end_stage}"
        + (", 跳过阶段 3" if args.skip_stage_3 else "")
    )
    return EXIT_OK


# === 子命令:status ===
def cmd_status(args: argparse.Namespace) -> int:
    """读取 state.json,展示当前进度"""
    output_dir = Path(args.output_dir).expanduser().resolve()
    state_path = output_dir / "state.json"
    state = read_state(state_path)
    if state is None:
        print(f"[ERROR] state.json 不存在: {state_path}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND

    print(f"工作区: {state.output_dir}")
    print(f"Skill 名: {state.skill_name}")
    print(f"创建时间: {state.created_at}")
    print(
        f"阶段范围: {state.start_stage} → {state.end_stage}"
        + (", 跳过阶段 3" if state.skip_stage_3 else "")
    )
    print(f"已完成阶段: {state.completed_stages or '(无)'}")

    # 检查每个阶段产物是否存在
    print()
    print("阶段产物状态:")
    for stage_num in range(state.start_stage, state.end_stage + 1):
        if state.skip_stage_3 and stage_num == 3:
            print(f"  阶段 {stage_num}: [SKIP]")
            continue
        artifact_name = STAGE_FILES.get(stage_num)
        if artifact_name is None:
            # 阶段 1:动态扫描 01_*.md(由 input 形式决定)
            stage1 = _resolve_stage1_artifact(state.output_dir)
            if stage1:
                size = stage1.stat().st_size
                print(
                    f"  阶段 {stage_num}: [OK] {stage1.name} ({size} bytes,按 input 形式动态命名)"
                )
            else:
                print(f"  阶段 {stage_num}: [PENDING] 01_*.md(input 决定产物名)")
            continue
        artifact_path = state.output_dir / artifact_name
        if artifact_path.exists():
            if artifact_path.is_file():
                size = artifact_path.stat().st_size
                print(
                    f"  阶段 {stage_num}: [OK] {artifact_name} ({size} bytes)"
                )
            else:
                # 目录(阶段 4)
                file_count = sum(1 for _ in artifact_path.rglob("*") if _.is_file())
                print(
                    f"  阶段 {stage_num}: [OK] {artifact_name}/ ({file_count} files)"
                )
        else:
            print(f"  阶段 {stage_num}: [PENDING] {artifact_name}")

    return EXIT_OK


# === 校验函数 ===
def validate_spec_hard_constraints(spec_path: Path) -> StageStatus:
    """16 项硬约束清单(对标 plan §自检清单)"""
    notes: List[str] = []
    if not spec_path.exists():
        return StageStatus(
            stage_num=2,
            stage_name="规格说明书",
            artifact_path=spec_path,
            exists=False,
            passed_validation=False,
            validation_notes=["文件不存在"],
        )

    content = spec_path.read_text(encoding="utf-8")
    checks = [
        (r"^## §?1\. 输入与输出", "含 §1 输入与输出"),
        (r"^## §?2\. 核心概念", "含 §2 核心概念"),
        (r"^## §?3\. 执行流程总览", "含 §3 执行流程总览"),
        (r"^## §?4\.", "含 §4 步骤 1"),
        (r"^## §?附录 A", "含附录 A"),
        (r"^## §?附录 B", "含附录 B"),
        (r"^## §?附录 C", "含附录 C"),
        (r"🟢|🟡|🔴", "含代码化属性标注(🟢/🟡/🔴)"),
        (r"🧠", "含 LLM 断点标记(🧠)"),
    ]

    passed = 0
    total = len(checks)
    for pattern, desc in checks:
        if re.search(pattern, content, re.MULTILINE):
            passed += 1
        else:
            notes.append(f"[FAIL] 缺: {desc}")

    # 软化措辞检查
    soft_patterns = ["建议灵活", "根据情况", "可能需要", "灵活处理"]
    for sp in soft_patterns:
        if sp in content:
            notes.append(f"[FAIL] 含软化措辞: '{sp}'")

    # 绝对路径检查
    if re.search(r"/media/vdb/[^\s]+", content):
        notes.append("[FAIL] 含绝对路径硬编码(/media/vdb/...)")

    # 🟢 占比统计
    codeable_count = len(re.findall(r"🟢", content))
    total_steps = len(re.findall(r"^## \d+\.\s+步骤", content, re.MULTILINE))
    if total_steps > 0:
        green_pct = codeable_count / total_steps * 100
        if green_pct < 50:
            notes.append(
                f"[FAIL] 🟢 步骤占比 {green_pct:.0f}% < 50% 阈值"
            )

    passed_validation = len(notes) == 0
    return StageStatus(
        stage_num=2,
        stage_name="规格说明书",
        artifact_path=spec_path,
        exists=True,
        size_bytes=spec_path.stat().st_size,
        passed_validation=passed_validation,
        validation_notes=notes,
    )


def _read_script_extension(skill_md: Path) -> Optional[str]:
    """从 SKILL.md frontmatter 读 `script_extension` 字段(2026-07-14 治理)。

    Returns:
        "py" / "sh" / 等;若 frontmatter 未声明返回 None(由调用方决定兼容策略)。
    """
    if not skill_md.exists():
        return None
    try:
        in_frontmatter = False
        for line in skill_md.read_text(encoding="utf-8").splitlines():
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                return None  # 已读到 frontmatter 结尾
            if not in_frontmatter:
                continue
            m = re.match(r"^script_extension:\s*[\"']?(\w+)[\"']?\s*$", line)
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def _read_main_script_text(skill_dir: Path, ext: Optional[str] = None) -> str:
    """读取主控脚本(scripts/run.{py,sh},由 ext 决定或自动探测)文本。

    用于 cmd_check_completeness 中读取主控内容做关键词校验。
    找不到时返回空串(调用方检查字符串为空即视为该检查不适用)。
    """
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return ""
    if ext:
        p = scripts_dir / f"run.{ext}"
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    for cand in ("run.py", "run.sh"):
        p = scripts_dir / cand
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def validate_skill_scaffold(skill_dir: Path) -> StageStatus:
    """8 项目录骨架自检(对标 plan §自检清单)"""
    notes: List[str] = []
    if not skill_dir.exists():
        return StageStatus(
            stage_num=4,
            stage_name="工程化 Skill",
            artifact_path=skill_dir,
            exists=False,
            passed_validation=False,
            validation_notes=["目录不存在"],
        )

    # 必填文件/目录
    # 注(2026-07-14 治理):scripts/run.{py,sh} 二选一,由 SKILL.md frontmatter 的
    # `script_extension` 声明决定(默认读 SKILL.md,缺则兼容任意后缀)。
    # 旧版本硬要求 `scripts/run.py`,违反通用化(scripts 语言可由 expert-guidance 指定)。
    skill_md = skill_dir / "SKILL.md"
    declared_ext = _read_script_extension(skill_md)
    required = [
        ("SKILL.md", "file"),
        ("scripts", "dir"),
        ("scripts/run" + (f".{declared_ext}" if declared_ext else ".*"), "file_or_any"),
        ("references", "dir"),
        ("references/output-schema.md", "file"),
        ("templates", "dir"),
        ("templates/output-template.md", "file"),
    ]
    for rel_path, kind in required:
        if kind == "file_or_any":
            # scripts/run.<ext> 或 scripts/run.* 二选一
            matches = list(skill_dir.glob(rel_path))
            if not matches:
                notes.append(
                    f"[FAIL] 缺主控脚本:{rel_path}(spec 若声明 script_extension,必须提供对应文件)"
                )
            continue
        full_path = skill_dir / rel_path
        if not full_path.exists():
            notes.append(f"[FAIL] 缺 {kind}: {rel_path}")
        elif kind == "file" and full_path.stat().st_size == 0:
            notes.append(f"[FAIL] {rel_path} 为空")

    # 至少 1 个 LLM 断点契约(v2:支持 stepN-rules.md 与 llm_*.md 两种命名,后者是推荐)
    refs_dir = skill_dir / "references"
    legacy_rules = list(refs_dir.glob("step*-rules.md")) if refs_dir.exists() else []
    new_rules = list(refs_dir.glob("llm_*.md")) if refs_dir.exists() else []
    # 过滤掉 llm_fallbacks.md / llm-rules.md 等元数据(只看契约特征:含 JSON Schema)
    new_rules = [
        p for p in new_rules
        if p.is_file() and re.search(r"```json", p.read_text(encoding="utf-8"))
    ]
    step_rules = legacy_rules + new_rules
    if not step_rules:
        notes.append(
            "[FAIL] 缺 LLM 断点契约:需在 references/ 下生成至少 1 个 "
            "`llm_{task_id}_{business_meaning}.md`(v2 推荐) 或兼容旧版 `stepN-rules.md`"
        )
    # v2 命名违例检测:LLM 断点契约不应再叫 stepN-rules.md(已废止)
    if legacy_rules and not new_rules:
        notes.append(
            "[WARN-v2-naming] LLM 断点契约文件使用旧命名 `stepN-rules.md`。"
            "v2 起推荐改为 `llm_{task_id}_{business_meaning}.md`(业务含义自解释),"
            "如 `llm_a_component_dependency_analysis.md`。"
            "本次作 WARN 不阻断,但下次 skill_create 启动 v2 严格模式时会 FAIL"
        )

    # SKILL.md frontmatter 检查
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
        if not re.search(r"^name:\s*\S+", content, re.MULTILINE):
            notes.append("[FAIL] SKILL.md 缺 name 字段")
        if not re.search(r"^description:\s*", content, re.MULTILINE):
            notes.append("[FAIL] SKILL.md 缺 description 字段")

    # P0-7 防呆(2026-07-13 v3 新增,根治 GB 级知识库被全量复制):
    # references/ 任意单目录 > 1 MB 或单文件 > 200 KB → FAIL
    references_dir = skill_dir / "references"
    if references_dir.exists():
        # 单文件大小检查
        big_files = []
        for p in references_dir.rglob("*"):
            if p.is_file():
                size = p.stat().st_size
                if size > 200 * 1024:  # 200 KB
                    big_files.append((p.relative_to(skill_dir), size))
        if big_files:
            top3 = ", ".join(f"{r}({s // 1024}KB)" for r, s in big_files[:3])
            notes.append(
                f"[FAIL-P0-7] references/ 含 {len(big_files)} 个超大文件 (>200KB):{top3}"
                f"——这通常是 'cp -r 整个知识库' 造成的污染;正确做法:在 SKILL.md 写绝对路径,"
                f"由 run.py --consume-lib 参数运行时引用"
            )
        # 单目录大小检查(直接子目录累计 > 1 MB)
        big_dirs = []
        for p in references_dir.iterdir():
            if p.is_dir():
                total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                if total > 1024 * 1024:  # 1 MB
                    big_dirs.append((p.relative_to(skill_dir), total))
        if big_dirs:
            top3 = ", ".join(f"{r}({t // 1024 // 1024}MB)" for r, t in big_dirs[:3])
            notes.append(
                f"[FAIL-P0-7] references/ 含 {len(big_dirs)} 个超大目录 (>1MB):{top3}"
                f"——禁止 'cp -r' 复制整个知识库到 Skill 包"
            )

    passed_validation = len(notes) == 0
    file_count = sum(1 for _ in skill_dir.rglob("*") if _.is_file())
    return StageStatus(
        stage_num=4,
        stage_name="工程化 Skill",
        artifact_path=skill_dir,
        exists=True,
        size_bytes=file_count,
        passed_validation=passed_validation,
        validation_notes=notes,
    )


# === P0-4 覆盖度统计辅助函数 ===

def _count_spec_steps(spec_path: Path) -> int:
    """统计 spec 中 §4~§N 的步骤数(以 '### 步骤 N' 形式)

    通用化:不绑定特定 spec 模板,识别"### 步骤 N"或"### §4.N~§9.N"两种格式
    (排除 §1/§2/§3 子章节,因为这些是输入/概念/流程图而非步骤详述)。
    """
    if not spec_path.exists():
        return 0
    content = spec_path.read_text(encoding="utf-8")
    # 匹配 "### 步骤 N" 或 "### §[4-9].N"(排除 §1/§2/§3 子章节)
    patterns = [
        r"^### 步骤\s*\d+",       # ### 步骤 1 / ### 步骤 2
        r"^### §[4-9]\.\d+",      # ### §4.1(排除 §1.1/§2.1/§3.1)
    ]
    count = 0
    for line in content.split("\n"):
        for pat in patterns:
            if re.match(pat, line):
                count += 1
                break
    return count


def _count_spec_llm_breakpoints(spec_path: Path) -> int:
    """统计 spec 中 LLM 断点数量(🧠 LLM- 标记)

    通用化:不绑定特定命名(LLM-A/B/C 或 step6-insert 等都可识别)。
    """
    if not spec_path.exists():
        return 0
    content = spec_path.read_text(encoding="utf-8")
    return len(re.findall(r"🧠\s*LLM-", content))


def _count_spec_concepts(spec_path: Path) -> int:
    """统计 spec §2 中概念(子章节)数量

    通用化:不绑定特定概念命名,识别 spec §2 的子章节数(每类对应一个 dataclass)。
    """
    if not spec_path.exists():
        return 0
    content = spec_path.read_text(encoding="utf-8")
    # 匹配 §2.x 子章节(如 "### §2.1", "### 2.1 SubsystemChangeRow" 等)
    patterns = [
        r"^### §2\.\d+",       # ### §2.1
        r"^### 2\.\d+\s+\w+",  # ### 2.1 SubsystemChangeRow
    ]
    count = 0
    for line in content.split("\n"):
        for pat in patterns:
            if re.match(pat, line):
                count += 1
                break
    return count


def _count_impl_dataclasses(impl_path: Path) -> int:
    """统计 impl 中 @dataclass 装饰器出现次数

    通用化:不绑定 dataclass 命名,直接匹配 @dataclass 装饰器。
    """
    if not impl_path.exists():
        return 0
    content = impl_path.read_text(encoding="utf-8")
    return len(re.findall(r"^@dataclass", content, re.MULTILINE))


def _extract_output_files_from_spec(spec_path: Path) -> List[str]:
    """从 spec §1.3 输出产物表提取声明的文件名/路径关键词

    通用化:不绑定产物格式,从表格第三列(输出文件/路径/名称)抽取。
    """
    if not spec_path.exists():
        return []
    content = spec_path.read_text(encoding="utf-8")
    files = re.findall(r"[a-zA-Z0-9_\-一-鿿]+\.(?:md|json|txt|yaml|yml)", content)
    return list(set(files))


def _count_skill_step_scripts(skill_dir: Path) -> int:
    """统计 skill/scripts/ 下 step*.py 脚本数"""
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return 0
    return len(list(scripts_dir.glob("step*.py")))


def _count_skill_llm_rules(skill_dir: Path) -> int:
    """统计 skill/references/ 下 stepN-rules.md 契约文档数"""
    refs_dir = skill_dir / "references"
    if not refs_dir.exists():
        return 0
    return len(list(refs_dir.glob("step*-rules.md")))


def _count_skill_actual_files(skill_dir: Path) -> List[str]:
    """统计 skill 目录实际存在的文件清单(用于产物覆盖度对比)"""
    if not skill_dir.exists():
        return []
    return [p.name for p in skill_dir.rglob("*") if p.is_file()]


# === P0-5/6 业务模式强制映射辅助函数(v3 新增,根治"漏写产物"问题) ===

# 业务模式配置文件路径(framework 层固定;环境变量可覆盖,严禁硬编码具体业务名)
def _resolve_business_patterns_path() -> Optional[Path]:
    """解析 business_patterns.yaml 路径。

    优先级:
      1. 环境变量 SKILLX_BUSINESS_PATTERNS(显式注入)
      2. framework_configs/knowledge/business_patterns.yaml(相对 cwd 解析)
    """
    env_path = os.environ.get("SKILLX_BUSINESS_PATTERNS", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        return p if p.exists() else None
    # 相对 cwd 解析(项目根目录)
    default = Path("framework_configs/knowledge/business_patterns.yaml")
    return default if default.exists() else None


def _load_business_patterns() -> Optional[Dict[str, Any]]:
    """加载业务模式 YAML 配置(轻量解析,避免依赖 PyYAML)。

    通用化:不绑定具体业务名,完全由 YAML 驱动。
    返回 None 表示配置不可用,跳过 P0-5/6 检查。
    """
    path = _resolve_business_patterns_path()
    if path is None:
        return None
    try:
        import yaml  # type: ignore
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        # 极简正则回退:仅解析 flow_design.required_part_ids 这类扁平结构
        try:
            text = path.read_text(encoding="utf-8")
            result: Dict[str, Any] = {"patterns": {}, "product_part_completeness": {}}
            current_pattern = None
            current_part = None
            for line in text.splitlines():
                stripped = line.rstrip()
                if not stripped or stripped.lstrip().startswith("#"):
                    continue
                if stripped.startswith("patterns:"):
                    continue
                # 进入某个 mode 块
                m = re.match(r"^  (\w+):\s*$", stripped)
                if m and not stripped.startswith("    "):
                    current_pattern = m.group(1)
                    result["patterns"][current_pattern] = {
                        "triggers": {"keywords": []},
                        "typical_product_parts": [],
                        "has_revision_loop": False,
                    }
                    current_part = None
                    continue
                if current_pattern is None:
                    continue
                # keywords 行
                m_kw = re.match(r"^      keywords:\s*\[(.*)\]\s*$", stripped)
                if m_kw:
                    kws = [k.strip().strip('"').strip("'") for k in m_kw.group(1).split(",") if k.strip()]
                    result["patterns"][current_pattern]["triggers"]["keywords"] = kws
                    continue
                # file_signals 行(2026-07-13 新增 — 用于 SKILL.md description/file_signals 命中)
                m_fs = re.match(r"^      file_signals:\s*\[(.*)\]\s*$", stripped)
                if m_fs:
                    fs = [s.strip().strip('"').strip("'") for s in m_fs.group(1).split(",") if s.strip()]
                    result["patterns"][current_pattern]["triggers"]["file_signals"] = fs
                    continue
                # script_signals 行(2026-07-13 新增 — 用于 run.{py,sh} 字符串匹配,如 render_diagram)
                m_ss = re.match(r"^      script_signals:\s*\[(.*)\]\s*$", stripped)
                if m_ss:
                    ss = [s.strip().strip('"').strip("'") for s in m_ss.group(1).split(",") if s.strip()]
                    result["patterns"][current_pattern]["triggers"]["script_signals"] = ss
                    continue
                # part_id 行(part_id 块顶层)
                m_part = re.match(r"^      - part_id:\s*\"(\w+)\"\s*$", stripped)
                if m_part:
                    current_part = m_part.group(1)
                    result["patterns"][current_pattern]["typical_product_parts"].append(
                        {"part_id": current_part, "required": True}
                    )
                    continue
                # required: false 行(仅记录,不强制)
                m_req = re.match(r"^        required:\s*(\w+)\s*$", stripped)
                if m_req and current_part:
                    is_required = m_req.group(1).lower() == "true"
                    # 更新最后一个 part 的 required
                    parts = result["patterns"][current_pattern]["typical_product_parts"]
                    if parts and parts[-1]["part_id"] == current_part:
                        parts[-1]["required"] = is_required
                    continue
                # has_revision_loop
                m_rev = re.match(r"^    has_revision_loop:\s*(\w+)\s*$", stripped)
                if m_rev:
                    result["patterns"][current_pattern]["has_revision_loop"] = (
                        m_rev.group(1).lower() == "true"
                    )
                    continue
                # product_part_completeness 块
                m_comp = re.match(r"^  (\w+):\s*$", stripped)
                if m_comp and stripped.startswith("    ") is False:
                    mode = m_comp.group(1)
                    if mode in ("matching_rules", "product_part_completeness"):
                        current_pattern = None
                    continue
                m_min = re.match(r"^    min_parts:\s*(\d+)\s*$", stripped)
                if m_min:
                    # 推断当前 mode(从 product_part_completeness 上下文)
                    last_mode = None
                    for line2 in text.splitlines():
                        m2 = re.match(r"^  (\w+):\s*$", line2)
                        if m2 and m2.group(1) in result["patterns"]:
                            last_mode = m2.group(1)
                    if last_mode and last_mode not in result["product_part_completeness"]:
                        result["product_part_completeness"][last_mode] = {}
                    if last_mode:
                        result["product_part_completeness"][last_mode]["min_parts"] = int(m_min.group(1))
            return result
        except Exception:
            return None


def _match_business_mode(spec_path: Path, patterns: Dict[str, Any]) -> Optional[str]:
    """从 spec 内容推断业务模式(通用:基于关键词 + specificity_order 优先)。

    优先级:
      1. **specificity_order 第一个有命中的模式直接胜出**(specificity_order
         是 YAML 中明确定义的"优先级列表",最具体的业务模式排前面)
      2. specificity_order 缺失或全部未命中时,按 patterns dict 声明顺序找第一个有命中的

    设计依据:中文 spec 里 "生成/文档/报告" 等通用词普遍存在,会让通用模式
    (document_generation) 分数虚高;specificity_order 是业务专家明确定义的
    "模式优先级",应该作为权威信号而不是 tie-breaker。
    """
    if not spec_path.exists() or not patterns:
        return None
    content = spec_path.read_text(encoding="utf-8").lower()
    pattern_defs = patterns.get("patterns", {})
    # 优先级列表(YAML 权威,缺则用 patterns dict 顺序)
    priority_list = (patterns.get("matching_rules") or {}).get("specificity_order") or list(pattern_defs.keys())
    # 按优先级遍历,第一个有任一关键词命中的模式胜出
    for mode in priority_list:
        if mode not in pattern_defs:
            continue
        cfg = pattern_defs[mode]
        kws = (cfg.get("triggers") or {}).get("keywords") or []
        if any(kw.lower() in content for kw in kws):
            return mode
    return None


def _extract_spec_product_part_ids(spec_path: Path) -> List[str]:
    """从 spec §1.3 输出产物表提取 part_id 列表(通用:基于 part_id 关键词识别)。

    通用化:不绑定具体业务,只识别"§1.3 行内含哪些 part_id 关键词"。
    part_id 来源 = business_patterns.yaml 的所有 typical_product_parts.part_id。
    """
    if not spec_path.exists():
        return []
    # 提取 §1.3 章节内容(简化:从 "§1.3" 到下一个 § 章节)
    content = spec_path.read_text(encoding="utf-8")
    m = re.search(r"§1\.3[^\n]*\n(.*?)(?=^##|\Z)", content, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    section_text = m.group(1).lower()
    # 收集所有可能的 part_id 关键词(从 patterns.yaml)
    patterns = _load_business_patterns()
    if patterns is None:
        return []
    candidate_ids = set()
    for cfg in (patterns.get("patterns") or {}).values():
        for part in (cfg.get("typical_product_parts") or []):
            pid = part.get("part_id")
            if pid:
                candidate_ids.add(pid.lower())
    # 在 §1.3 文本里搜 part_id 关键词命中
    matched = []
    for pid in candidate_ids:
        if pid in section_text:
            matched.append(pid)
    return matched


def _count_spec_section13_rows(spec_path: Path) -> int:
    """统计 spec §1.3 输出产物表的行数(通用:基于 Markdown 表格行统计)。

    用于 COVERAGE-E 检查,避免依赖 part_id 字符串匹配(spec 用中文描述时字符串搜不到)。
    规则:§1.3 章节内,以 `|` 开头的非空行数(剔除表头和分隔行)。
    """
    if not spec_path.exists():
        return 0
    content = spec_path.read_text(encoding="utf-8")
    m = re.search(r"§1\.3[^\n]*\n(.*?)(?=^##|\Z)", content, re.MULTILINE | re.DOTALL)
    if not m:
        return 0
    section_text = m.group(1)
    data_rows = 0
    for line in section_text.splitlines():
        s = line.strip()
        # 数据行:以 | 开头且含中英文字符(排除表头 part_id 类英文/分隔行 --- 类纯符号)
        if s.startswith("|") and re.search(r"[a-zA-Z一-鿿]", s):
            data_rows += 1
    # 减 1 表头(数据行第一行通常是表头 part_id)
    return max(0, data_rows - 1)


def validate_skill_coverage(
    skill_dir: Path,
    spec_path: Path,
    impl_path: Path,
) -> StageStatus:
    """P0-6 覆盖度统计:spec 声明 vs skill 实际产出的 6 组交叉对比

    通用化:不绑定特定业务领域,纯结构化对比,适用于任意 Skill 制作场景。

    6 组统计(v3 新增 E/F):
      (a) spec 步骤数 vs scripts/step*.py 实际数
      (b) spec 中 🟡🔴 标注数 vs references/stepN-rules.md 实际数
      (c) spec §2 dataclass 字段数 vs impl 中字段定义数
      (d) spec §1.3 输出产物表声明 vs skill 目录实际文件
      (e) 业务模式匹配 + spec §1.3 产物行数 vs 模式 min_parts(v3 新增)
      (f) 模式 required_part_ids vs spec §1.3 实际 part_id 覆盖(v3 新增)

    任一组 gap > 0 → 校验不通过。
    """
    notes: List[str] = []

    if not skill_dir.exists():
        return StageStatus(
            stage_num=4,
            stage_name="覆盖度统计(P0-6)",
            artifact_path=skill_dir,
            exists=False,
            passed_validation=False,
            validation_notes=["skill 目录不存在,无法做覆盖度对比"],
        )

    # (a) spec 步骤数 vs scripts/step*.py 实际数
    spec_steps = _count_spec_steps(spec_path)
    actual_scripts = _count_skill_step_scripts(skill_dir)
    gap_a = spec_steps - actual_scripts
    if gap_a > 0:
        notes.append(
            f"[COVERAGE-A] spec 声明 {spec_steps} 步骤,但 scripts/step*.py 仅 {actual_scripts} 个"
            f"(差 {gap_a} 个,spec 步骤未 1:1 拆分到独立脚本)"
        )
    elif gap_a < 0:
        notes.append(
            f"[COVERAGE-A] scripts/step*.py 共 {actual_scripts} 个,超过 spec 步骤数 {spec_steps}"
            f"(多 {abs(gap_a)} 个,可能是步骤拆分过细或重复实现)"
        )

    # (b) spec 中 🟡🔴 标注数 vs references/stepN-rules.md 实际数
    spec_llm = _count_spec_llm_breakpoints(spec_path)
    actual_rules = _count_skill_llm_rules(skill_dir)
    gap_b = spec_llm - actual_rules
    if gap_b > 0:
        notes.append(
            f"[COVERAGE-B] spec 声明 {spec_llm} 个 LLM 断点,但 references/step*-rules.md 仅 {actual_rules} 个"
            f"(差 {gap_b} 个,LLM 断点契约文档缺失)"
        )

    # (c) spec §2 概念数 vs impl @dataclass 装饰器数
    spec_concepts = _count_spec_concepts(spec_path)
    impl_dataclasses = _count_impl_dataclasses(impl_path)
    if spec_concepts > 0 and impl_dataclasses > 0:
        gap_c = spec_concepts - impl_dataclasses
        if gap_c > 0:
            notes.append(
                f"[COVERAGE-C] spec §2 声明 {spec_concepts} 个核心概念,"
                f"impl 实际定义 {impl_dataclasses} 个 @dataclass"
                f"(spec 多 {gap_c} 个,可能概念未全部落地为 dataclass)"
            )
        elif gap_c < -3:  # 容忍 impl 多 3 个 dataclass(LLMCheckpoint / ValidationReport / StepResult 等通用框架辅助类)
            notes.append(
                f"[COVERAGE-C] impl 定义 {impl_dataclasses} 个 @dataclass,"
                f"spec §2 声明 {spec_concepts} 个核心概念"
                f"(impl 多 {abs(gap_c)} 个,可能是过度抽象)"
            )

    # (d) spec §1.3 输出产物表声明 vs skill 目录实际文件
    declared_outputs = _extract_output_files_from_spec(spec_path)
    actual_files = _count_skill_actual_files(skill_dir)
    # 仅警告:声明了 X 个产物文件,实际 skill 目录中匹配 Y 个
    if declared_outputs:
        matched = sum(1 for f in declared_outputs if any(f in af for af in actual_files))
        if matched == 0:
            notes.append(
                f"[COVERAGE-D] spec §1.3 声明的产物文件 {declared_outputs[:3]}"
                f"在 skill 目录中未找到匹配(可能产物写到了 workspace 而非 skill 目录)"
            )

    # (e) 业务模式匹配 + spec §1.3 产物行数 vs 模式 min_parts(v3 新增)
    # (f) 模式 required_part_ids vs spec §1.3 实际 part_id 覆盖(v3 新增,WARN 不阻断)
    patterns = _load_business_patterns()
    if patterns is not None:
        matched_mode = _match_business_mode(spec_path, patterns)
        if matched_mode:
            completeness = (patterns.get("product_part_completeness") or {}).get(matched_mode) or {}
            min_parts = completeness.get("min_parts")
            # 通用:用 §1.3 表格行数统计(避免 part_id 字符串依赖)
            actual_rows = _count_spec_section13_rows(spec_path)
            if min_parts is not None and actual_rows < min_parts:
                notes.append(
                    f"[COVERAGE-E] 匹配业务模式 '{matched_mode}',spec §1.3 产物行数 "
                    f"{actual_rows} < 模式 min_parts={min_parts}"
                    f"(典型 required 产物:表格 + 可视化图 + 详细描述,各占独立一行)"
                )
            # (f) 软检查:required_part_ids 与 spec §1.3 part_id 字符串匹配
            # 仅 WARN 不阻断(spec 可能用中文描述,而 part_id 是英文;信号已通过 (e) 覆盖)
            required_ids = (completeness.get("required_part_ids")) or []
            actual_part_ids = _extract_spec_product_part_ids(spec_path)
            if required_ids and actual_part_ids:
                missing = [r for r in required_ids if r.lower() not in actual_part_ids]
                if missing:
                    notes.append(
                        f"[COVERAGE-F-WARN] 业务模式 '{matched_mode}' 期望 part_id 关键词:"
                        f"{required_ids},spec §1.3 命中:{actual_part_ids}"
                        f"(差异:{missing};spec 若用中文描述产物名则字符串匹配会失败,"
                        f"数量检查已由 COVERAGE-E 覆盖)"
                    )
        else:
            notes.append(
                "[COVERAGE-E] 无法匹配业务模式(检查 spec 是否含流程/文档/数据/工具关键词,"
                "或检查 framework_configs/knowledge/business_patterns.yaml 是否可读)"
            )

    # P0-6 设计要求:任一组 gap > 0 → 校验不通过(根治缩水需要硬阻断)
    # 包含 [COVERAGE-X] 标记的 notes 都视为覆盖度问题,均触发 FAIL
    passed_validation = not any(
        "[FAIL]" in n or "[COVERAGE-" in n for n in notes
    )
    file_count = len(actual_files)
    return StageStatus(
        stage_num=4,
        stage_name="覆盖度统计(P0-6)",
        artifact_path=skill_dir,
        exists=True,
        size_bytes=file_count,
        passed_validation=passed_validation,
        validation_notes=notes if notes else ["[OK] 6 组覆盖度统计全部通过(spec 声明与 skill 产物一致)"],
    )


# === 子命令:validate ===
def cmd_validate(args: argparse.Namespace) -> int:
    """校验 spec + skill 目录(集成 P0-4 覆盖度统计)"""
    output_dir = Path(args.output_dir).expanduser().resolve()
    spec_path = output_dir / "02_skill_spec.md"
    skill_dir = output_dir / "04_skill_dir" / args.skill_name
    # 阶段 3 产物 2026-07-11 起为 .md;兼容旧任务用 .py
    impl_md = output_dir / "03_monolithic_impl.md"
    impl_py = output_dir / "03_monolithic_impl.py"
    impl_path = impl_md if impl_md.exists() else (impl_py if impl_py.exists() else impl_md)

    spec_status = validate_spec_hard_constraints(spec_path)
    skill_status = validate_skill_scaffold(skill_dir)
    coverage_status = validate_skill_coverage(skill_dir, spec_path, impl_path)

    all_statuses = [spec_status, skill_status, coverage_status]
    has_fail = False

    for status in all_statuses:
        marker = "[OK]" if status.passed_validation else "[FAIL]"
        print(
            f"{marker} 阶段 {status.stage_num} {status.stage_name}: "
            f"{status.artifact_path}"
        )
        if not status.passed_validation:
            for note in status.validation_notes:
                print(f"    {note}")
            has_fail = True
        else:
            # 即使 PASS,也打印覆盖度统计的详细 notes(便于人工审视)
            for note in status.validation_notes:
                print(f"    {note}")

    if has_fail:
        print()
        print("[RESULT] 校验不通过")
        return EXIT_VALIDATION_FAIL
    print()
    print("[RESULT] 全部校验通过")
    return EXIT_OK


# === 子命令:summary ===
def cmd_summary(args: argparse.Namespace) -> int:
    """汇总所有阶段产物路径 + 大小"""
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not output_dir.exists():
        print(f"[ERROR] 工作区不存在: {output_dir}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND

    print(f"# {output_dir.name}\n")
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            rel = path.relative_to(output_dir)
            print(f"  {rel}  ({size} bytes)")
        elif path.is_dir():
            file_count = sum(1 for _ in path.rglob("*") if _.is_file())
            rel = path.relative_to(output_dir)
            print(f"  {rel}/  ({file_count} files)")
    return EXIT_OK


# === 通用产物完整性检查(不读 reference,只查通用业务规则) ===
def cmd_check_completeness(args: argparse.Namespace) -> int:
    """基于通用业务完整性 checklist 检查 Skill 产物。

    不读外部 reference 实现,只检查通用业务规则:
      - 目录骨架 4 个(SKILL.md + scripts/ + references/ + templates/)
      - scripts/run.py 主控 + --resume 协议
      - references/step*-rules.md LLM 断点契约(含 JSON Schema)
      - templates/output-template.md
      - SKILL.md frontmatter 三要素
      - 流程类必含 validate_*.py 校验脚本(自动检测 business_patterns.yaml)

    返回:
      - 0 = 全部通过
      - 1 = 有不通过项(报告错误位置)
      - 2 = Skill 目录不存在
    """
    skill_dir = Path(args.skill_dir)
    if not skill_dir.exists():
        print(f"[ERROR] Skill 目录不存在: {skill_dir}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND

    # 自动检测业务模式(从 SKILL.md description / scripts 命名推断)
    # 简化:只检测是否含流程类特征(如 run.py 中含 "render_diagram" 等)
    is_flow_design = _detect_flow_design(skill_dir)

    checks = [
        # 1. 目录骨架(4 个必需)
        ("SKILL.md 文件存在", lambda d: (d / "SKILL.md").is_file()),
        ("scripts/ 目录存在", lambda d: (d / "scripts").is_dir()),
        ("references/ 目录存在", lambda d: (d / "references").is_dir()),
        ("templates/ 目录存在", lambda d: (d / "templates").is_dir()),
        # 2. 主控脚本(2026-07-14 治理:支持 .py / .sh 二选一,由 SKILL.md frontmatter 声明)
        (
            "scripts/run.{py,sh} 主控脚本存在",
            lambda d: (d / "scripts" / "run.py").is_file() or (d / "scripts" / "run.sh").is_file(),
        ),
        (
            "run.{py,sh} 支持 --resume",
            lambda d: "--resume" in _read_main_script_text(d),
        ),
        # 3. LLM 断点契约(2026-07-14 治理:支持旧 stepN-rules + 新 llm_*.md 两种命名)
        (
            "references/[step*-rules.md | llm_*.md] 至少 1 个",
            lambda d: (
                any(d.glob("references/step*-rules.md"))
                or any(
                    f.is_file()
                    for f in d.glob("references/llm_*.md")
                    if re.search(r"```json", f.read_text(encoding="utf-8"))
                )
            ),
        ),
        (
            "LLM 契约文件含 JSON Schema",
            lambda d: any(
                '"$schema":' in f.read_text(encoding="utf-8")
                for f in (
                    list(d.glob("references/step*-rules.md"))
                    + list(d.glob("references/llm_*.md"))
                )
            ),
        ),
        # 4. 产物模板
        (
            "templates/output-template.md 存在",
            lambda d: (d / "templates" / "output-template.md").is_file(),
        ),
        # 5. SKILL.md frontmatter 三要素
        (
            "SKILL.md frontmatter 含 name/version/description/allowed-tools",
            lambda d: all(
                field in (d / "SKILL.md").read_text(encoding="utf-8")
                for field in ["name:", "version:", "description:", "allowed-tools:"]
            ),
        ),
        # 6. 状态机持久化(通用,参考 state_machine_norms.md)
        #    检测主控脚本含 checkpoint / run_state 关键字
        (
            "run.{py,sh} 含状态机持久化(checkpoint / run_state 字段)",
            lambda d: any(
                kw in _read_main_script_text(d)
                for kw in ["checkpoint", "run_state.json", "phase_history"]
            ),
        ),
        # 7. LLM 断点 --resume 协议完整性
        (
            "run.{py,sh} 支持 --llm-response 参数",
            lambda d: "--llm-response" in _read_main_script_text(d),
        ),
        (
            "[流程类] LLM 断点步骤脚本支持 --resume(--llm-response)",
            lambda d: any(
                "--llm-response" in f.read_text(encoding="utf-8")
                for ext in ("py", "sh")
                for f in d.glob(f"scripts/step*.{ext}")
            ),
        ),
        # 8. v2 LLM 契约 schema 字段名白名单 + flow_design 多模板组合(2026-07-13 新增)
        (
            "[LLM-B 多模板组合] flow_design 综合 LLM 断点必含 ≥ 3 类操作(insertions/row_updates/linkage_changes)",
            _check_llm_breakpoint_multi_op,
        ),
    ]

    # 6. 流程类必含校验脚本(从骨架推断)
    if is_flow_design:
        checks.append(
            (
                "[流程类] scripts/validate_*.py 至少 3 个(拓扑/内容/产物)",
                lambda d: sum(
                    1 for f in d.glob("scripts/validate_*.py")
                ) >= 3,
            )
        )

    passed = []
    failed = []
    for name, check_fn in checks:
        try:
            if check_fn(skill_dir):
                passed.append(name)
            else:
                failed.append(name)
        except Exception as e:
            failed.append(f"{name}(异常: {e})")

    # 输出报告
    print(f"\n=== 完整性检查: {skill_dir} ===\n")
    print(f"业务模式: {'flow_design(流程类)' if is_flow_design else '通用'}\n")
    print(f"✅ 通过 ({len(passed)} 项):")
    for name in passed:
        print(f"  - {name}")
    if failed:
        print(f"\n❌ 不通过 ({len(failed)} 项):")
        for name in failed:
            print(f"  - {name}")
        print(
            "\n修复建议: 详见 framework_configs/anti_patterns/skill_anti_patterns.md"
        )
        return EXIT_VALIDATION_FAIL

    print(f"\n全部 {len(passed)} 项通过 ✅")
    return EXIT_OK


def _load_llm_template_id_whitelist() -> Optional[list]:
    """从 framework_configs/knowledge/llm_breakpoint_templates.json 加载字段白名单。

    返回 `['insertions', 'row_updates', 'linkage_changes', 'naming_decisions',
            'fixes', 'fallback_markers']` 或 None(加载失败/文件缺失时)。

    框架校验脚本用:任何 LLM 契约 schema 的 `properties` keys 必须 ∈ 此集合,
    否则框架视为自创字段名,FAIL(反模式 #3)。
    """
    p = Path(__file__).resolve().parents[2] / "framework_configs" / "knowledge" / "llm_breakpoint_templates.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # 优先取顶层 template_id_whitelist,fallback 取 templates keys
        wl = data.get("template_id_whitelist")
        if wl:
            return [k for k in wl if not k.startswith("_")]
        tpl = data.get("templates", {})
        return list(tpl.keys())
    except Exception:
        return None


def _extract_schema_property_keys(schema_text: str) -> List[str]:
    """从 LLM 契约文档的 markdown 中提取 JSON Schema `properties` 顶层 keys。

    提取策略:找所有 ```json 代码块,逐个解析 JSON,取 `properties` 的 keys 去重。
    """
    keys: set = set()
    for match in re.finditer(r"```json\s*\n(.*?)\n```", schema_text, re.DOTALL):
        try:
            j = json.loads(match.group(1))
        except Exception:
            continue
        props = j.get("properties", {})
        if isinstance(props, dict):
            for k in props.keys():
                if not k.startswith("_"):
                    keys.add(k)
    return list(keys)


def _check_llm_breakpoint_multi_op(skill_dir: Path) -> bool:
    """校验所有 LLM 契约 schema 的多模板组合(2026-07-13 通用化 v2)。

    **通用化设计**(不依赖任何业务关键词):
      - 不再基于 `flow_design` / "流程"/"时序" 等业务特定关键词判断
      - 默认对所有 `references/llm_*.md` 与 `references/step*-rules.md` 校验
      - 触发条件改为**schema 字段语义**(通用 LLM 模板):
        - 含 `insertions`(综合类,默认必含)→ 校验 ≥3 类操作
        - 不含 `insertions` → 视为规则匹配类(`fixes`-only),跳过

    **为何这样比"按关键词判断"更通用**:
      - 适用于任何语言的 SKILL.md description(中文/英文/混排)
      - 适用于任何业务模式(不只 flow_design)
      - schema 字段语义是 LLM 契约的稳定接口,业务术语不稳定

    返回 True=PASS, False=FAIL。FAIL 时通过 stderr 输出 [WARN-multi_op] 警告
    (本次作 WARN 不阻断;v3 严格模式将 FAIL 阻断)。
    """
    whitelist = _load_llm_template_id_whitelist()
    if whitelist is None:
        return True  # 白名单不可用,跳过校验

    refs_dir = skill_dir / "references"
    if not refs_dir.exists():
        return True

    llm_files = list(refs_dir.glob("llm_*.md")) + list(refs_dir.glob("step*-rules.md"))
    if not llm_files:
        return True

    required_ops = {"insertions", "row_updates", "linkage_changes"}
    for f in llm_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        props = _extract_schema_property_keys(text)
        if not props:
            continue
        # 通用语义判断:
        #   - 含 `insertions` = 综合 LLM 断点 → 必含 ≥3 类操作
        #   - 不含 `insertions` = 规则匹配类(`fixes`-only)→ 跳过
        if "insertions" not in props:
            continue
        intersection = required_ops & set(props)
        if len(intersection) < 3:
            print(
                f"    [WARN-multi_op] {f.name} 综合 LLM 断点只含 "
                f"{sorted(intersection)}({len(intersection)}/3 类操作),"
                f"按 framework 通用规则推荐含 insertions + row_updates + linkage_changes"
                f"(或 {sorted(whitelist)} 中至少 3 个)。"
                f"如仅采用单模板,请在契约顶部明确说明;否则请补齐缺失字段。"
                f"(本次作 WARN 不阻断;v3 严格模式将 FAIL)",
                file=sys.stderr,
            )
            return False
    return True


def _detect_flow_design(skill_dir: Path) -> bool:
    """自动检测 Skill 是否属于流程类(启发式)。

    **通用化设计**(2026-07-13 v2,根治硬编码业务关键词):
      - **不**在 Python 代码中硬编码业务术语("流程"/"时序"/"组件" 等均不出现)
      - 改为读 `framework_configs/knowledge/business_patterns.yaml` 的模式触发关键词
      - YAML 是配置唯一来源,Python 只读不写

    触发判定(优先级由高到低,任一命中即视为流程类):
      1. SKILL.md description 命中 YAML 中某个 pattern 的 `keywords` ∪ `file_signals`
      2. scripts/run.{py,sh} 命中 YAML 中某个 pattern 的 `script_signals`(如 render_diagram)
      3. references/ LLM 断点数量 ≥ 2(隐性启发,作为兜底,与具体业务无关)

    返回 True=流程类(需启用 3 类校验),False=其他模式。
    """
    patterns = _load_business_patterns()
    if patterns is not None:
        priority_list = (
            (patterns.get("matching_rules") or {}).get("specificity_order")
            or list((patterns.get("patterns") or {}).keys())
        )
        for mode in priority_list:
            cfg = (patterns.get("patterns") or {}).get(mode, {})
            triggers = cfg.get("triggers") or {}
            keywords = list(triggers.get("keywords") or [])
            file_signals = list(triggers.get("file_signals") or [])
            script_signals = list(triggers.get("script_signals") or ["render_diagram", "render_detail"])

            try:
                skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                if any(kw in skill_md for kw in keywords + file_signals):
                    return True
            except (FileNotFoundError, UnicodeDecodeError):
                pass

            for ext in ("py", "sh"):
                run_path = skill_dir / "scripts" / f"run.{ext}"
                if run_path.exists():
                    try:
                        run_text = run_path.read_text(encoding="utf-8")
                        if any(sig in run_text for sig in script_signals):
                            return True
                    except (FileNotFoundError, UnicodeDecodeError):
                        pass
                    break

    # 兜底:references/ LLM 断点 ≥ 2 个视为流程类(与业务术语无关)
    llm_breakpoints = (
        list(skill_dir.glob("references/llm_*.md"))
        + list(skill_dir.glob("references/step*-rules.md"))
    )
    if len(llm_breakpoints) >= 2:
        return True

    return False



# === CLI 入口 ===
def main():
    parser = argparse.ArgumentParser(
        description=f"skill_create 薄壳 v{SKILL_CREATE_VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # init
    p_init = subparsers.add_parser("init", help="创建工作区 + 初始化 state.json")
    p_init.add_argument(
        "--output-dir",
        required=False,
        default=None,
        help=(
            "工作区根目录绝对路径;未传则由 config/create-user-config.yaml "
            "的 paths.root 自动派生(严禁相对 cwd,避免落点漂移)"
        ),
    )
    p_init.add_argument("--skill-name", required=True, help="Skill 名(英文短横线)")
    p_init.add_argument(
        "--start-stage", type=int, default=1, choices=[1, 2, 3, 4], help="起始阶段"
    )
    p_init.add_argument(
        "--end-stage", type=int, default=4, choices=[1, 2, 3, 4], help="结束阶段"
    )
    p_init.add_argument(
        "--skip-stage-3", action="store_true", help="跳过阶段 3(单体 Python)"
    )
    p_init.add_argument(
        "--expert-guidance", default="", help="专家指引文本"
    )
    p_init.add_argument(
        "--taskid",
        default=None,
        help=(
            "taskid 名称;支持完整名(skill_create_20260713_150041)"
            "或裸时间戳(20260713_150041)。未传则按当前时间生成"
            "skill_create_<YYYYMMDD_HHMMSS>。"
        ),
    )

    # status
    p_status = subparsers.add_parser("status", help="展示当前进度")
    p_status.add_argument("--output-dir", required=True, help="工作区根目录")

    # validate
    p_validate = subparsers.add_parser("validate", help="校验产物")
    p_validate.add_argument("--output-dir", required=True, help="工作区根目录")
    p_validate.add_argument("--skill-name", required=True, help="Skill 名")

    # summary
    p_summary = subparsers.add_parser("summary", help="汇总所有产物")
    p_summary.add_argument("--output-dir", required=True, help="工作区根目录")

    # check-completeness(基于通用业务完整性 checklist,不读 reference)
    p_check = subparsers.add_parser(
        "check-completeness",
        help="检查产物完整性(基于通用业务规则,不读 reference)",
    )
    p_check.add_argument("--skill-dir", required=True, help="Skill 目录绝对路径")

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "status": cmd_status,
        "validate": cmd_validate,
        "summary": cmd_summary,
        "check-completeness": cmd_check_completeness,
    }
    handler = dispatch.get(args.cmd)
    if handler is None:
        print(f"[ERROR] 未知子命令: {args.cmd}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
