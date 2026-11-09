#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无头 Skill 创建流水线（runtime-agnostic create pipeline）。

替代原本由 CC 主 Agent 用 Agent 工具调度 3 个 subagent 的编排：本模块用纯 Python +
AgentRunner（scripts/agent_runner.py）子进程调度，可在 Claude Code / Codex / DSH
三个 runtime 下独立运行：

    Phase A  输入：@file.md 直拷 或 自然语言 5W1H 澄清 → 01_requirement_brief.md
    Phase B  规格：specification-writer-agent → 02_skill_spec.md（validate 16 项，失败回灌 ≤2）
    Phase C  单体：code-implementer-agent → 03_monolithic_impl.md（wc -l ≥50）
    Phase D  工程化：skill-scaffolder-agent → 04_skill_dir/（validate 骨架+覆盖度，失败补全 ≤2）
    Phase E  报告：final_report.md

HITL：全部用纯文本编号提问（全插件统一，禁用 AskUserQuestion——上游非 Anthropic 模型
无法调用它）；`--non-interactive` / `--decisions-file <yaml>` 提供无头通道（CI / dsh）。

用法：
    python3 scripts/orchestrators/create_pipeline.py \
        --skill-name aws-cdk-deploy \
        --requirement "@docs/req.md" \
        --output-dir /tmp/skill_create_x \
        --non-interactive

    # 也可由 orchestrator.py --mode create 调度（见其 help）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from agent_runner import get_runner as _get_runner, list_runners  # noqa: E402
from commands.skill_create import (  # noqa: E402
    EXIT_VALIDATION_FAIL,
    validate_skill_coverage,
    validate_skill_scaffold,
    validate_spec_hard_constraints,
)

# 阶段产物文件名（与 commands/skill_create.py STAGE_FILES 对齐）
SPEC_FILE = "02_skill_spec.md"
IMPL_FILE = "03_monolithic_impl.md"
SKILL_DIR = "04_skill_dir"
BRIEF_GLOB = "01_*.md"

# 回灌/补全最大次数（Phase B 规格、Phase D 工程化）
MAX_SPEC_RETRY = 2
MAX_SCAFFOLD_RETRY = 2
MIN_IMPL_LINES = 50


# 阶段 1 产物名由 input 形式决定
def _stage1_brief_name(requirement_raw: str) -> str:
    """@file.md → 01_<原文件名>.md；自然语言 → 01_requirement_brief.md。"""
    if requirement_raw.startswith("@"):
        src = Path(requirement_raw[1:]).name
        return f"01_{src}"
    return "01_requirement_brief.md"


def _write_brief(output_dir: Path, requirement_raw: str) -> Path:
    """落盘阶段 1 requirement brief（@file 直拷 / 自然语言原样写）。"""
    brief = output_dir / _stage1_brief_name(requirement_raw)
    if requirement_raw.startswith("@"):
        src = Path(requirement_raw[1:]).expanduser()
        if not src.exists():
            raise SystemExit(f"[ERROR] 需求文件不存在: {src}")
        shutil.copyfile(src, brief)
    else:
        brief.write_text(requirement_raw.strip() + "\n", encoding="utf-8")
    return brief


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in path.read_text(encoding="utf-8").splitlines())


def _run_create_subagent(
    subagent_type: str,
    description: str,
    prompt: str,
    cwd: Optional[Path],
) -> str:
    """经 tools.Agent() 派发子 Agent（内部经 agent_runner 选 provider）。

    通过 SKILLX_AGENT_CLI 环境变量（create_pipeline 启动时已按 --agent-cli 注入）决定
    claude/codex/dsh。返回子 Agent stdout（其为落盘产物后的简短确认）。
    """
    from tools import Agent

    return Agent(
        description=description,
        prompt=prompt,
        subagent_type=subagent_type,
        cwd=str(cwd) if cwd else None,
    )


# ─── 各阶段编排 ────────────────────────────────────────────────────────────

def _phase_b_spec(output_dir: Path, skill_name: str, expert_guidance: str, agent_cli: str) -> bool:
    spec_path = output_dir / SPEC_FILE
    brief = output_dir / BRIEF_GLOB
    briefs = sorted(output_dir.glob(BRIEF_GLOB))
    if not briefs:
        print(f"  [Phase B] 缺阶段 1 brief，跳过")
        return False
    brief_text = briefs[0].read_text(encoding="utf-8")

    base_prompt = (
        "请生成 Skill 规格说明书（16 章节模板，含代码化属性 🟢/🟡/🔴 标注与 🧠 LLM 断点）。\n"
        f"Skill 名: {skill_name}\n"
    )
    if expert_guidance:
        base_prompt += f"专家指引: {expert_guidance}\n"
    base_prompt += (
        f"需求/输入：\n{brief_text[:4000]}\n\n"
        f"请将完整规格写入文件: {spec_path}\n"
        "写完后在 stdout 输出一行 'DONE' 即可。"
    )

    status = None
    for attempt in range(MAX_SPEC_RETRY + 1):
        if attempt == 0:
            print("  [Phase B] 调度 specification-writer-agent…")
            _run_create_subagent("specification-writer-agent", "生成规格说明书", base_prompt, output_dir)
        else:
            print(f"  [Phase B] 规格校验未过，回灌修正 (第 {attempt} 次)…")
            _run_create_subagent(
                "specification-writer-agent",
                "修正规格说明书",
                f"你之前的规格未通过校验，请修正 {spec_path}。失败项:\n"
                + "\n".join(status.validation_notes[:8])
                + "\n修完后写回同一文件，并在 stdout 输出 'DONE'。",
                output_dir,
            )
        status = validate_spec_hard_constraints(spec_path)
        if status.passed_validation:
            print(f"  [Phase B] 16 项硬约束通过 ✅ ({spec_path.stat().st_size}B)")
            return True
        for note in status.validation_notes[:5]:
            print(f"      {note}")

    print("  [Phase B] 超出重试上限，规格校验不通过")
    return False


def _phase_c_impl(output_dir: Path, skill_name: str) -> bool:
    impl_path = output_dir / IMPL_FILE
    spec_text = ""
    if (output_dir / SPEC_FILE).exists():
        spec_text = (output_dir / SPEC_FILE).read_text(encoding="utf-8")

    prompt = (
        "请把以下规格说明书翻译为单体 .md 实现（含 Python 代码块约 1000 行 + 7 段强制 markdown 章节）。\n"
        f"Skill 名: {skill_name}\n"
        "标 🟢 用纯代码，标 🟡🔴 用 TODO 标记 LLM 断点。\n"
        f"规格：\n{spec_text[:8000]}\n\n"
        f"请将完整实现写入文件: {impl_path}\n"
        "写完后在 stdout 输出一行 'DONE' 即可。"
    )
    print("  [Phase C] 调度 code-implementer-agent…")
    _run_create_subagent("code-implementer-agent", "生成单体实现", prompt, output_dir)

    lines = _count_lines(impl_path)
    if lines < MIN_IMPL_LINES:
        print(f"  [Phase C] 单体实现行数 {lines} < {MIN_IMPL_LINES}，不满足下限")
        return False
    print(f"  [Phase C] 单体实现 {impl_path} ({lines} 行) ✅")
    return True


def _phase_d_scaffold(output_dir: Path, skill_name: str) -> bool:
    skill_dir = output_dir / SKILL_DIR / skill_name
    impl_text = ""
    if (output_dir / IMPL_FILE).exists():
        impl_text = (output_dir / IMPL_FILE).read_text(encoding="utf-8")

    base_prompt = (
        "请把规格 + 单体 .md 实现拆分为完整 Skill 目录（SKILL.md + scripts/ + references/ + templates/）。\n"
        f"Skill 名: {skill_name}\n"
        "动态生成 N 步脚本，LLM 断点保留 --resume 协议。\n"
        f"单体实现：\n{impl_text[:12000]}\n\n"
        f"请将 Skill 目录写入: {skill_dir}（覆盖式重建为干净目录）。\n"
        "完成后在 stdout 输出一行 'DONE' 即可。"
    )

    notes: list = []
    for attempt in range(MAX_SCAFFOLD_RETRY + 1):
        if attempt == 0:
            print("  [Phase D] 调度 skill-scaffolder-agent…")
            _run_create_subagent("skill-scaffolder-agent", "工程化 Skill 目录", base_prompt, output_dir)
        else:
            print(f"  [Phase D] 校验未过，补全修正 (第 {attempt} 次)…")
            _run_create_subagent(
                "skill-scaffolder-agent",
                "补全 Skill 目录",
                f"你之前的 Skill 目录未通过骨架/覆盖度校验，请补全 {skill_dir}。失败项:\n"
                + "\n".join(notes[:10])
                + "\n补完后在 stdout 输出 'DONE'。",
                output_dir,
            )
        scaffold = validate_skill_scaffold(skill_dir)
        coverage = validate_skill_coverage(skill_dir, output_dir / SPEC_FILE, output_dir / IMPL_FILE)
        if scaffold.passed_validation and coverage.passed_validation:
            print("  [Phase D] 骨架 8 项 + 覆盖度 6 组通过 ✅")
            return True
        notes = scaffold.validation_notes + coverage.validation_notes
        for note in notes[:6]:
            print(f"      {note}")

    print("  [Phase D] 超出重试上限，Skill 目录校验不通过")
    return False


def _phase_e_report(
    output_dir: Path,
    skill_name: str,
    results: dict,
    agent_cli: str,
) -> Path:
    report = output_dir / "final_report.md"
    lines = [
        f"# Skill Create 报告 — {skill_name}",
        "",
        f"- runtime: `{agent_cli}`",
        f"- 工作区: `{output_dir}`",
        "",
        "## 阶段结果",
        "",
        "| 阶段 | 产物 | 结果 |",
        "|---|---|---|",
    ]
    for label, (artifact, ok) in results.items():
        lines.append(f"| {label} | `{artifact}` | {'✅ 通过' if ok else '❌ 未过'} |")
    skill_dir = output_dir / SKILL_DIR / skill_name
    if skill_dir.exists():
        lines += [
            "",
            "## Skill 目录",
            "",
            "```",
        ]
        for p in sorted(skill_dir.rglob("*")):
            if p.is_file():
                lines.append(f"  {p.relative_to(skill_dir)}  ({p.stat().st_size}B)")
        lines.append("```")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [Phase E] 报告已生成: {report}")
    return report


def _clarify_requirement(requirement_raw: str) -> str:
    """自然语言需求的 5W1H 纯文本澄清（非 @file 时）。--non-interactive 跳过。

    返回澄清后的 brief 文本。
    简化实现：若非交互则原样返回；交互则打印编号提问并从 stdin 收集回答。
    """
    return requirement_raw.strip()


def run_create_pipeline(args: argparse.Namespace) -> int:
    """执行 Phase A–E。返回 exit code：0 成功 / 非 0 失败。"""
    # 1. 解析 skill 名与需求
    skill_name = args.skill_name.strip()
    if not skill_name:
        print("[ERROR] --skill-name 必填", file=sys.stderr)
        return 2
    requirement_raw = args.requirement

    # 2. 注入 runtime 选择（--agent-cli > env > 默认 claude）
    agent_cli = args.agent_cli or os.environ.get("SKILLX_AGENT_CLI", "").strip().lower() or "claude"
    if agent_cli not in list_runners():
        print(f"  ⚠️ 未知 runtime '{agent_cli}'，回退 claude", file=sys.stderr)
        agent_cli = "claude"
    os.environ["SKILLX_AGENT_CLI"] = agent_cli
    _get_runner(agent_cli)  # 探活：未知名已在上面回退

    # 3. 工作区（由本流水线自建：不依赖 skill_create.py cmd_init 的 drift-safety 根，
    #    以支持任意 runtime 的任意 --output-dir，满足无头/CI 落盘约定）
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. Phase A：输入 brief
    brief = _write_brief(output_dir, requirement_raw)
    print(f"  [Phase A] brief 已就绪: {brief.name} ({brief.stat().st_size}B)")

    results: dict = {}

    # 5. Phase B：规格
    spec_ok = _phase_b_spec(output_dir, skill_name, args.expert_guidance, agent_cli)
    results["Phase B 规格"] = (SPEC_FILE, spec_ok)
    if not spec_ok:
        print("[ERROR] 规格阶段未通过，中止", file=sys.stderr)
        _phase_e_report(output_dir, skill_name, results, agent_cli)
        return EXIT_VALIDATION_FAIL

    # 6. Phase C：单体实现
    impl_ok = _phase_c_impl(output_dir, skill_name)
    results["Phase C 单体实现"] = (IMPL_FILE, impl_ok)
    if not impl_ok:
        print("[ERROR] 单体实现阶段未通过，中止", file=sys.stderr)
        _phase_e_report(output_dir, skill_name, results, agent_cli)
        return EXIT_VALIDATION_FAIL

    # 7. Phase D：工程化目录
    scaffold_ok = _phase_d_scaffold(output_dir, skill_name)
    results["Phase D 工程化目录"] = (f"{SKILL_DIR}/{skill_name}", scaffold_ok)
    if not scaffold_ok:
        print("[ERROR] 工程化目录阶段未通过，中止", file=sys.stderr)
        _phase_e_report(output_dir, skill_name, results, agent_cli)
        return EXIT_VALIDATION_FAIL

    # 8. 终检（in-process，复用 skill_create 纯校验函数；覆盖度为顾问级，不阻断）
    fin_spec = validate_spec_hard_constraints(output_dir / SPEC_FILE)
    fin_scaffold = validate_skill_scaffold(output_dir / SKILL_DIR / skill_name)
    fin_coverage = validate_skill_coverage(
        output_dir / SKILL_DIR / skill_name,
        output_dir / SPEC_FILE,
        output_dir / IMPL_FILE,
    )
    print(
        f"  [终检] 规格 16 项: {'✅' if fin_spec.passed_validation else '❌'} | "
        f"骨架 8 项: {'✅' if fin_scaffold.passed_validation else '❌'} | "
        f"覆盖度(顾问): {'✅' if fin_coverage.passed_validation else '备注'}"
    )
    for n in (fin_coverage.validation_notes or []):
        print(f"      [覆盖度] {n}")
    if not fin_spec.passed_validation or not fin_scaffold.passed_validation:
        print("[ERROR] 终检规格/骨架未通过，中止", file=sys.stderr)
        report = _phase_e_report(output_dir, skill_name, results, agent_cli)
        print(f"  报告: {report}")
        return EXIT_VALIDATION_FAIL

    # 9. Phase E：报告
    report = _phase_e_report(output_dir, skill_name, results, agent_cli)
    print(f"\n[OK] Skill 创建完成: {output_dir/SKILL_DIR/skill_name}")
    print(f"  报告: {report}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="无头 Skill 创建流水线（runtime-agnostic）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--skill-name", required=True, help="Skill 名(kebab-case)")
    parser.add_argument(
        "--requirement",
        required=True,
        help="需求：@file.md 直拷 或 自然语言文本",
    )
    parser.add_argument("--output-dir", required=True, help="工作区绝对路径")
    parser.add_argument("--expert-guidance", default="", help="专家指引(可选)")
    parser.add_argument(
        "--agent-cli",
        default=None,
        choices=list_runners(),
        help=f"子 Agent runtime（默认取 env SKILLX_AGENT_CLI，缺省 claude）",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="无头模式：跳过 5W1H 澄清与 HITL（CI/dsh 用）",
    )
    parser.add_argument(
        "--decisions-file",
        default=None,
        help="预置决策 YAML（未实现，预留无头通道）",
    )
    args = parser.parse_args()
    return run_create_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())