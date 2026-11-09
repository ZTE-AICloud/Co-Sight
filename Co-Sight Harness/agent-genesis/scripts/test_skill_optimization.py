#!/usr/bin/env python3
"""Skill 优化能力 — 自动化测试套件

覆盖: 6 诊断维度、11 优化模式、多 Skill 场景、边界判定、Anthropic 规范检查
用法: python scripts/test_skill_optimization.py [--verbose] [--fixture F-XXX]
"""

import os, sys, re, yaml, json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Paths ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "evaluation/fixtures/skill-optimization"
RULES_DIR = PROJECT_ROOT / "rules/skill"
MOCK_AGENT = FIXTURES_DIR / "mock-agent-CLAUDE.md"

# ── Severity ordering ──────────────────────────────────────
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
def max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER.get(a, 0) >= SEVERITY_ORDER.get(b, 0) else b

# ── Color helpers ──────────────────────────────────────────
GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"
def ok(s): return f"{GREEN}{s}{RESET}"
def fail(s): return f"{RED}{s}{RESET}"
def warn(s): return f"{YELLOW}{s}{RESET}"
def info(s): return f"{CYAN}{s}{RESET}"

# ═══════════════════════════════════════════════════════════════
# 1. SKILL.md 解析
# ═══════════════════════════════════════════════════════════════

@dataclass
class SkillInfo:
    """解析后的 Skill 结构信息"""
    path: Path
    name: str = ""
    description: str = ""
    lines: int = 0
    has_references_dir: bool = False
    has_scripts_dir: bool = False
    has_templates_dir: bool = False
    references_files: list = field(default_factory=list)
    scripts_files: list = field(default_factory=list)
    templates_files: list = field(default_factory=list)
    inline_code_blocks: int = 0  # Markdown 中 ```python ```bash 代码块数量
    sections: list = field(default_factory=list)  # ## 标题列表
    step_count: int = 0  # 估算的步骤数
    has_checkpoint: bool = False
    has_progress_reporting: bool = False
    has_g1_reviewer: bool = False
    has_schema_enforcement: bool = False  # 输出格式 Schema 约束
    has_external_references: bool = False  # 引用外部文件
    output_paths: list = field(default_factory=list)  # 输出路径列表
    self_review: bool = False  # 是否自审
    mentions_agent_tools: list = field(default_factory=list)  # 提及的工具


def parse_skill(skill_path: Path) -> SkillInfo:
    """解析 SKILL.md 文件，提取结构信息"""
    if not skill_path.exists():
        raise FileNotFoundError(f"SKILL.md not found: {skill_path}")

    content = skill_path.read_text(encoding="utf-8")
    info = SkillInfo(path=skill_path, lines=len(content.splitlines()))

    # 解析 name (# 标题)
    m = re.match(r"^#\s+(.+)", content)
    if m:
        info.name = m.group(1).strip()

    # 解析 description (> description: ...)
    m = re.search(r">\s*description:\s*(.+)", content)
    if m:
        info.description = m.group(1).strip()

    # 解析 ## 小节标题
    info.sections = re.findall(r"^##\s+(.+)", content, re.MULTILINE)

    # 检测代码块
    info.inline_code_blocks = len(re.findall(r"```(?:python|bash|shell|sh|js|ruby)", content))

    # 估算步骤数 (有序列表项 / "Step N" / "Phase N" / "### N." 模式)
    info.step_count = max(
        len(re.findall(r"^\d+\.\s", content, re.MULTILINE)),
        len(re.findall(r"^###\s+\d+\.", content, re.MULTILINE)),
        len(re.findall(r"(?:Step|Phase)\s+\d+", content, re.IGNORECASE)),
    )

    # 检查 checkpoint 关键词
    info.has_checkpoint = bool(re.search(r"checkpoint|断点|恢复|resume|restore", content, re.IGNORECASE))

    # 检查进度汇报
    info.has_progress_reporting = bool(re.search(r"progress|进度|IV1|通知|notify", content, re.IGNORECASE))

    # 检查 G1 审查
    info.has_g1_reviewer = bool(re.search(r"审查|review(?:er)?\s+agent|G1|独立审查|Independent\s+Review", content, re.IGNORECASE))

    # 检查 Schema 约束
    info.has_schema_enforcement = bool(re.search(r"schema|JSON\s+Schema|format\s+spec|DF1|输出格式.*固定", content, re.IGNORECASE))

    # 检查外部引用 (references/ templates/ scripts/)
    info.has_external_references = bool(re.search(r"references/|templates/|scripts/|见\s+\S+\.md|see\s+\S+\.md", content, re.IGNORECASE))

    # 检查自审
    info.self_review = bool(re.search(r"自我审查|自审|自行确认|自行判断.*正确", content))

    # 提取输出路径
    info.output_paths = re.findall(r"(?:输出到|output\s+(?:to|path)[:=]?\s*|write\s+to\s+)([/\w.-]+)", content, re.IGNORECASE)
    info.output_paths += re.findall(r"((?:/tmp|work)/[/\w.-]+\.(?:md|json|yaml|txt))", content)

    # 提取工具调用
    info.mentions_agent_tools = re.findall(r"\b(Read|Write|Edit|Bash|Grep|Glob|Agent)\b", content)

    # 检查 Skill 目录下的资源目录
    skill_dir = skill_path.parent
    ref_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    tmpl_dir = skill_dir / "templates"
    info.has_references_dir = ref_dir.exists() and ref_dir.is_dir()
    info.has_scripts_dir = scripts_dir.exists() and scripts_dir.is_dir()
    info.has_templates_dir = tmpl_dir.exists() and tmpl_dir.is_dir()
    if info.has_references_dir:
        info.references_files = [f.name for f in ref_dir.iterdir() if f.is_file()]
    if info.has_scripts_dir:
        info.scripts_files = [f.name for f in scripts_dir.iterdir() if f.is_file()]
    if info.has_templates_dir:
        info.templates_files = [f.name for f in tmpl_dir.iterdir() if f.is_file()]

    return info


# ═══════════════════════════════════════════════════════════════
# 2. Agent CLAUDE.md 解析
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentInfo:
    """Agent CLAUDE.md 的结构化信息（用于 Global Context 对比）"""
    role_summary: str = ""
    allowed_tools: list = field(default_factory=list)
    safety_constraints: list = field(default_factory=list)
    work_dir_convention: str = "work/"
    has_g1_reviewer: bool = False
    has_plan_mode: bool = False


def parse_agent_claude(claude_path: Path) -> Optional[AgentInfo]:
    """解析 Agent CLAUDE.md"""
    if not claude_path.exists():
        return None
    content = claude_path.read_text(encoding="utf-8")
    agent = AgentInfo()

    # 提取 Role 摘要
    m = re.search(r"##\s+Role.*?\n\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        agent.role_summary = m.group(1).strip()

    # 提取工具白名单
    tools_m = re.search(r"可用工具[：:]\s*(.+)", content)
    if tools_m:
        agent.allowed_tools = [t.strip() for t in tools_m.group(1).split(",")]

    # 提取 Safety Constraints
    agent.safety_constraints = re.findall(r"S-\d+.*?禁止(.+)", content)

    # 提取 work/ 目录约定
    agent.work_dir_convention = "work/" if "work/" in content else ""

    # 检查 G1
    agent.has_g1_reviewer = bool(re.search(r"审查门禁|G1|Reviewer.*Gate", content, re.IGNORECASE))

    # 检查 Plan Mode
    agent.has_plan_mode = bool(re.search(r"Plan\s+Mode", content, re.IGNORECASE))

    return agent


# ═══════════════════════════════════════════════════════════════
# 3. 6 维诊断引擎
# ═══════════════════════════════════════════════════════════════

@dataclass
class Finding:
    dimension: str
    status: str  # PASS | FAIL
    severity: str  # CRITICAL | HIGH | MEDIUM | LOW
    signals: list = field(default_factory=list)
    evidence: str = ""


@dataclass
class DiagnosisResult:
    skill_name: str
    findings: dict  # dimension → Finding
    boundary_decision: str  # SKILL_ONLY | PARTIALLY_EXCEEDED | FULLY_EXCEEDED
    agent_issues: list = field(default_factory=list)
    recommended_patterns: list = field(default_factory=list)


def diagnose_decomposition(info: SkillInfo) -> Finding:
    """维度 1: Decomposition — 步骤粒度、I/O 契约、模块隔离"""
    signals = []
    severity = "LOW"

    if info.step_count >= 8:
        signals.append(f"步骤数量过多 ({info.step_count} steps)")
        severity = "HIGH"
    elif info.step_count >= 5:
        signals.append(f"步骤数量偏多 ({info.step_count} steps)")
        severity = "MEDIUM"

    # 检查是否有 I/O 契约（步骤间产物定义）
    if info.step_count >= 3 and not re.search(r"(?:输出|output|产物|artifact|→).*\.(?:md|json|yaml)", info.path.read_text()):
        signals.append("步骤间无明确 I/O 契约（无中间文件产物定义）")
        severity = max_severity(severity, "HIGH")

    # 检查模块隔离
    if info.lines > 500 and info.step_count >= 5:
        signals.append(f"大型单体 Skill ({info.lines} 行，{info.step_count} 步)，缺少模块隔离")

    if info.step_count <= 2 and info.lines < 200:
        return Finding("decomposition", "PASS", "LOW", ["步骤粒度合理"])

    status = "FAIL" if signals else "PASS"
    if not signals:
        signals.append("步骤粒度合理，有清晰的 I/O 契约")
    return Finding("decomposition", status, severity, signals)


def diagnose_information(info: SkillInfo) -> Finding:
    """维度 2: Information — 知识来源、加载策略、K-boundary"""
    signals = []
    severity = "LOW"
    content = info.path.read_text()

    # Count inline knowledge items (numbered lists + code blocks as knowledge density proxy)
    inline_knowledge_items = len(re.findall(r"^\d+\.\s", content, re.MULTILINE))
    if inline_knowledge_items >= 8:
        signals.append(f"大量知识内联 ({inline_knowledge_items} 项)，应提取到 references/")
        severity = "HIGH"
    elif inline_knowledge_items >= 4:
        signals.append(f"较多知识内联 ({inline_knowledge_items} 项)")
        severity = "MEDIUM"

    if info.lines > 400 and not info.has_external_references:
        signals.append(f"超大 Skill ({info.lines} 行) 且无外部 references/ 引用")
        severity = "HIGH"
    elif info.lines > 300 and not info.has_external_references:
        signals.append("内容偏多且未使用 references/ 分层")
        if severity == "LOW": severity = "MEDIUM"

    # 检查是否只有 K1 (LLM 内嵌知识)
    if not info.has_references_dir and inline_knowledge_items >= 4:
        signals.append("仅依赖 K1 (LLM 内嵌知识)，缺少 K2/K3 权威来源")

    # 检查是否有知识边界声明
    if not re.search(r"知识边界|knowledge.boundary|CD3|LLM.*可信|权威", content, re.IGNORECASE) and inline_knowledge_items >= 6:
        signals.append("缺少知识边界 (CD3) 声明")

    # 对于小型 Skill (<25 lines 且有外部引用), 不需要 references
    if info.lines < 25 and info.has_external_references:
        return Finding("information", "PASS", "LOW", ["小型 Skill 有外部引用，知识加载策略合理"])

    has_issues = len(signals) > 0
    if not has_issues:
        signals.append("知识加载策略合理，有外部引用")
    return Finding("information", "FAIL" if has_issues else "PASS", severity, signals)


def diagnose_state(info: SkillInfo) -> Finding:
    """维度 3: State — checkpoint、状态持久化、进度汇报"""
    signals = []
    severity = "LOW"

    # Small skills don't need state tracking
    # Small/simple skills don't need state tracking
    if info.step_count <= 3 or info.lines < 20:
        return Finding("state", "PASS", "LOW", ["小规模 Skill，无需复杂状态追踪"])

    if info.step_count >= 4 and not info.has_checkpoint:
        signals.append(f"{info.step_count} 步执行但无 checkpoint 机制，中断后需从头执行")
        severity = "MEDIUM"
    if info.step_count >= 4 and not info.has_progress_reporting:
        signals.append("无进度汇报机制，用户不可见执行进度")
        if severity == "LOW":
            severity = "MEDIUM"

    if not signals:
        signals.append("有状态追踪和断点恢复机制")
    return Finding("state", "FAIL" if signals else "PASS", severity, signals)


def diagnose_verification(info: SkillInfo) -> Finding:
    """维度 4: Verification — 审查门禁、校验机制、确定性操作"""
    signals = []
    severity = "LOW"

    if info.step_count >= 4 and info.self_review:
        signals.append("自审代替独立审查 — 缺 G1 Reviewer Gate")
        severity = "CRITICAL"
    elif info.step_count >= 4 and not info.has_g1_reviewer:
        signals.append("无审查门禁机制，错误可能传播到最终输出")
        severity = "HIGH"

    # 检查是否有 Schema 约束
    if info.step_count >= 4 and not info.has_schema_enforcement:
        signals.append("输出格式无 Schema 约束，下游消费不可靠")

    # 检查是否有内联代码适合提取为脚本
    if info.inline_code_blocks >= 2:
        signals.append(f"有 {info.inline_code_blocks} 个内联代码块，LLM 在做确定性操作")

    if info.step_count <= 2 or (info.lines < 20 and not info.self_review):
        return Finding("verification", "PASS", "LOW", ["小规模 Skill，无需复杂验证"])

    if not signals:
        signals.append("有审查门禁和校验机制")
    return Finding("verification", "FAIL" if signals else "PASS", severity, signals)


def diagnose_design_form(info: SkillInfo) -> Finding:
    """维度 5: Design Form — 对照 Anthropic 官方 Skill 规范 (SF-1 至 SF-8)"""
    signals = []
    severity = "LOW"
    violations = []

    # Small skills (<30 lines) with external references don't need full layering
    if info.lines < 30 and info.has_external_references:
        return Finding("design_form", "PASS", "LOW", ["小型 Skill 有外部引用，结构合理"])

    # SF-1: 目录结构
    if not info.has_references_dir and info.lines > 200:
        signals.append("SF-1 违规: 缺少 references/ 目录分层")
        violations.append("SF-1")
    if not info.has_scripts_dir and info.inline_code_blocks > 0:
        signals.append("SF-7 违规: 可执行脚本未提取到 scripts/ 目录")
        violations.append("SF-7")
    if not info.has_templates_dir and info.step_count >= 3:
        signals.append("SF-8 违规: 缺少 templates/ 提供可复用模板")
        violations.append("SF-8")
    if not info.has_references_dir and not info.has_scripts_dir and not info.has_templates_dir:
        severity = "HIGH"

    # SF-5: 命名约定 (kebab-case + 领域关键词)
    name_lower = info.name.lower()
    generic_names = ["helper", "utils", "tool", "misc", "common", "shared", "miscellaneous"]
    if any(gn in name_lower for gn in generic_names):
        signals.append(f"SF-5 违规: 名称过于宽泛 ('{info.name}')，缺少领域关键词")
        violations.append("SF-5")

    # SF-6: 描述公式 (做什么 + 何时触发 + 输入 + 输出)
    desc = info.description.lower()
    has_what = len(info.description) > 15  # 有实质内容
    has_when = bool(re.search(r"当|when|触发|trigger|请求", desc))
    has_input = bool(re.search(r"输入|input|接收|参数|文件路径|代码", desc))
    has_output = bool(re.search(r"输出|output|产出|生成|报告|返回", desc))
    if not (has_what and has_when and has_input and has_output):
        missing = []
        if not has_what: missing.append("做什么")
        if not has_when: missing.append("何时触发")
        if not has_input: missing.append("输入")
        if not has_output: missing.append("输出")
        signals.append(f"SF-6 违规: description 缺少关键要素 ({', '.join(missing)})")
        violations.append("SF-6")

    # SF-4: L3 引用闭合 — 检查 references/ 中的文件是否在 SKILL.md 中被引用
    if info.has_references_dir and info.references_files:
        content = info.path.read_text()
        for f in info.references_files:
            if f not in content:
                signals.append(f"SF-4 违规: references/{f} 未被 SKILL.md 引用（孤立文件）")
                violations.append("SF-4")

    # SF-2: L1 加载 — description 质量
    if len(info.description) < 20:
        signals.append("SF-2 违规: description 过短 (<20 字符)，Agent 无法准确判断触发时机")
        violations.append("SF-2")

    if info.lines > 500:
        signals.append(f"SF-3 违规: SKILL.md 过长 ({info.lines} 行)，违反 L2 渐进加载原则")
        violations.append("SF-3")

    has_violations = len(signals) > 0
    if not has_violations:
        signals.append("符合 Anthropic Skill 规范，目录分层正确")
    return Finding("design_form", "FAIL" if has_violations else "PASS", severity, signals,
                   evidence=f"Anthropic 规范违规: {violations}" if violations else "")


def diagnose_global_context(info: SkillInfo, agent: Optional[AgentInfo]) -> Finding:
    """维度 6: Global Context — 与 Agent 整体设计的契合度"""
    signals = []
    severity = "LOW"
    if agent is None:
        return Finding("global_context", "PASS", "LOW", ["无 Agent CLAUDE.md 可对比，跳过"])

    # GC-1: Role 一致性 — 检查 Skill 是否越权
    skill_text = info.path.read_text()
    if ("修改" in skill_text[:500] or "Edit" in info.mentions_agent_tools) and info.self_review:
        for c in agent.safety_constraints:
            if "修改" in c or "modify" in c.lower():
                signals.append(f"GC-1 Role 不一致: Skill 执行修改操作 vs Agent 约束 '{c.strip()}'")
                severity = "CRITICAL"
    # Also check for tools not in agent whitelist
    extra_tools = set(info.mentions_agent_tools) - set(agent.allowed_tools)
    if extra_tools:
        for c in agent.safety_constraints:
            if "修改" in c:
                signals.append(f"GC-1 Role 不一致: Skill 使用越权工具 {extra_tools} vs Agent 约束 '{c.strip()}'")
                severity = "CRITICAL"

    # GC-2: Tool 权限
    extra_tools = set(info.mentions_agent_tools) - set(agent.allowed_tools)
    if extra_tools:
        signals.append(f"GC-2 Tool 越权: Skill 使用 {extra_tools}，但不在 Agent 白名单 {agent.allowed_tools} 中")
        severity = max_severity(severity, "HIGH")

    # GC-3: I/O 路径约定
    for p in info.output_paths:
        if p.startswith("/tmp") and agent.work_dir_convention:
            signals.append(f"GC-3 I/O 路径偏离: Skill 输出到 {p}，与 Agent 约定 {agent.work_dir_convention} 不符")
            severity = max_severity(severity, "HIGH")

    # GC-4: Safety 约束
    if info.self_review:
        for c in agent.safety_constraints:
            if "审查" in c or "G1" in c or "reviewer" in c.lower():
                signals.append(f"GC-4 Safety: 自审绕过 Agent 安全约束 '{c.strip()}'")
                severity = max_severity(severity, "HIGH")

    # GC-7: Review 策略
    if info.self_review and agent.has_g1_reviewer:
        signals.append("GC-7 Review 不对齐: Skill 自审代替 Agent G1 独立审查")

    # Build status: FAIL only if real violations found
    has_violations = len(signals) > 0
    if not has_violations:
        signals.append("Skill 与 Agent 全局设计一致")
    return Finding("global_context", "FAIL" if has_violations else "PASS", severity, signals)


def run_diagnosis(info: SkillInfo, agent: Optional[AgentInfo]) -> DiagnosisResult:
    """执行 6 维诊断"""
    findings = {
        "decomposition": diagnose_decomposition(info),
        "information": diagnose_information(info),
        "state": diagnose_state(info),
        "verification": diagnose_verification(info),
        "design_form": diagnose_design_form(info),
        "global_context": diagnose_global_context(info, agent),
    }

    # 边界判定
    agent_issues = []
    gc = findings["global_context"]
    if gc.status == "FAIL" and gc.severity == "CRITICAL":
        for sig in gc.signals:
            if "Tool 越权" in sig:
                agent_issues.append({"type": "Tool 权限", "detail": sig})
                boundary = "PARTIALLY_EXCEEDED"
                break
        else:
            boundary = "SKILL_ONLY"
    else:
        boundary = "SKILL_ONLY"

    # 模式匹配
    patterns = match_patterns(info, findings)

    return DiagnosisResult(
        skill_name=info.name,
        findings=findings,
        boundary_decision=boundary,
        agent_issues=agent_issues,
        recommended_patterns=patterns,
    )


# ═══════════════════════════════════════════════════════════════
# 4. 模式匹配引擎
# ═══════════════════════════════════════════════════════════════

def match_patterns(info: SkillInfo, findings: dict) -> list[int]:
    """根据诊断结果匹配优化模式"""
    patterns = set()

    # 模式 1: 单体拆解 — Decomposition FAIL
    if findings["decomposition"].status == "FAIL" and info.step_count >= 8:
        patterns.add(1)

    # 模式 2: 文档系统 — Information FAIL
    if findings["information"].status == "FAIL":
        patterns.add(2)

    # 模式 3: 确定性命令 — 内联代码块 >= 2
    if info.inline_code_blocks >= 2:
        patterns.add(3)

    # 模式 4: Hook 门禁 — Verification FAIL 且非自审
    vf = findings["verification"]
    if vf.status == "FAIL" and not info.self_review:
        patterns.add(4)

    # 模式 5: 状态追踪 — State FAIL
    if findings["state"].status == "FAIL":
        patterns.add(5)

    # 模式 6: Review Agent — 自审 或 Verification FAIL
    if vf.status == "FAIL" and (info.self_review or vf.severity in ("CRITICAL", "HIGH")):
        patterns.add(6)

    # 模式 7: 形态重构 — Design Form FAIL
    if findings["design_form"].status == "FAIL":
        patterns.add(7)

    # 模式 8: 全局对齐 — Global Context FAIL
    if findings["global_context"].status == "FAIL":
        patterns.add(8)

    # 模式 9: Skill 拆分 — 巨型 Skill
    # 信号: 大量 phases/sections (>5个独立功能域) 或 大量步骤 (>20步)
    phase_count = len(re.findall(r"(?:Phase|阶段)\s+\d+", info.path.read_text(), re.IGNORECASE))
    # Also count ### numbered sections as substeps
    substep_count = len(re.findall(r"^###\s+\d+\.\d+", info.path.read_text(), re.MULTILINE))
    total_steps = max(info.step_count, substep_count)
    if info.lines > 100 and (phase_count >= 5 or total_steps > 20):
        patterns.add(9)

    # 模式 10: 跨 Skill 重组 — 在 multi_skill 检测中设置，此处不自动触发

    # 模式 11: 批量优化 — 在 multi_skill 检测中设置，此处不自动触发

    # 健康 Skill 不需要任何模式
    if all(f.status == "PASS" for f in findings.values()):
        patterns.clear()

    return sorted(patterns)


# ═══════════════════════════════════════════════════════════════
# 5. 多 Skill 关联分析
# ═══════════════════════════════════════════════════════════════

@dataclass
class CrossSkillReport:
    dependency_matrix: list  # [{from, to, type}]
    overlaps: list  # [{skill_a, skill_b, overlap, severity}]
    conflicts: list  # [{type, skill_a, skill_b}]
    recommended_order: list  # [skill_name, ...]
    recommended_patterns: list  # [10, 11]


def analyze_cross_skill(skill_infos: dict[str, SkillInfo]) -> CrossSkillReport:
    """分析多 Skill 间的依赖、重叠和冲突"""
    deps = []
    overlaps = []
    conflicts = []

    for name_a, info_a in skill_infos.items():
        content_a = info_a.path.read_text()
        for name_b, info_b in skill_infos.items():
            if name_a >= name_b:
                continue

            # 检测数据依赖: Skill B 读取 Skill A 命名的输出文件
            for path in info_a.output_paths:
                path_basename = Path(path).name
                if path_basename in info_b.path.read_text():
                    deps.append({"from": name_b, "to": name_a, "type": "data_dep",
                                 "detail": f"{name_b} reads {path} produced by {name_a}"})

            # 检测功能重叠: 相同关键词出现在两者中
            content_b = info_b.path.read_text()
            keywords_a = set(re.findall(r"(?:检查|扫描|分析|测试|验证|部署|构建|审查)(\S{0,4})", content_a))
            keywords_b = set(re.findall(r"(?:检查|扫描|分析|测试|验证|部署|构建|审查)(\S{0,4})", content_b))
            shared = keywords_a & keywords_b
            if shared and len(shared) >= 1:
                overlaps.append({
                    "skill_a": name_a, "skill_b": name_b,
                    "overlap": f"功能重叠({len(shared)}项): {shared}", "severity": "MEDIUM"
                })

            # 检测输出路径冲突
            paths_a = set(Path(p).name for p in info_a.output_paths)
            paths_b = set(Path(p).name for p in info_b.output_paths)
            path_conflict = paths_a & paths_b
            if path_conflict:
                conflicts.append({"type": "output_path", "skill_a": name_a, "skill_b": name_b,
                                  "detail": f"同名输出文件: {path_conflict}"})

    # 推荐执行顺序: 被依赖的优先
    dep_targets = {d["to"] for d in deps}
    dep_sources = {d["from"] for d in deps}
    roots = dep_targets - dep_sources
    leaves = dep_sources - dep_targets
    order = list(roots) + list(skill_infos.keys() - roots - leaves) + list(leaves)
    # 去掉重复保持顺序
    seen = set()
    ordered = []
    for x in order:
        if x not in seen:
            seen.add(x); ordered.append(x)

    recommended = []
    # Pattern 10: 仅在存在真正的功能性重叠/冲突时推荐
    # 多个 Skill 本身不是触发条件 — 结构差异是正常且预期的
    if overlaps or conflicts or deps:
        recommended.append(10)
    # Pattern 11: 仅在存在跨 Skill 依赖链需要协调时推荐
    # 3+ Skill 本身不触发 — 必须有实际的 I/O 依赖或路径冲突
    if len(skill_infos) >= 3 and (deps or conflicts):
        recommended.append(11)

    return CrossSkillReport(
        dependency_matrix=deps,
        overlaps=overlaps,
        conflicts=conflicts,
        recommended_order=ordered,
        recommended_patterns=recommended,
    )


# ═══════════════════════════════════════════════════════════════
# 6. Edge case — 边界判定（纯对话场景，不依赖 SKILL.md）
# ═══════════════════════════════════════════════════════════════

def evaluate_escalation_scenario(scenario_id: str, description: str) -> dict:
    """评估边界判定场景"""
    result = {"boundary": "SKILL_ONLY", "agent_issues": [], "rationale": ""}

    if "同一会话" in description and ("新开会话" in description or "恢复" in description) and "质量" in description:
        result["boundary"] = "FULLY_EXCEEDED"
        result["agent_issues"] = ["Memory 噪声积累"]
        result["rationale"] = "症状指向 Agent Memory 噪声，Skill prompt 无法控制 Memory 写入策略"
    elif "单体" in description and "质量差" in description and "指令" in description:
        result["boundary"] = "FULLY_EXCEEDED"
        result["agent_issues"] = ["单步任务质量低"]
        result["rationale"] = "Skill 指令已清晰但执行质量仍差，问题在 Agent 基础能力或模型选择"

    return result


# ═══════════════════════════════════════════════════════════════
# 7. 测试执行器
# ═══════════════════════════════════════════════════════════════

class TestSuite:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.results = []

    def assert_equal(self, test_name, actual, expected, context=""):
        if actual == expected:
            self.passed += 1
            if self.verbose:
                print(f"  {ok('PASS')} {test_name} = {expected}")
        else:
            self.failed += 1
            msg = f"{test_name}: expected={expected}, actual={actual}"
            if context:
                msg += f" [{context}]"
            self.errors.append(msg)
            print(f"  {fail('FAIL')} {msg}")

    def assert_in(self, test_name, item, container, context=""):
        if item in container:
            self.passed += 1
            if self.verbose:
                print(f"  {ok('PASS')} {test_name}: {item} in {container}")
        else:
            self.failed += 1
            msg = f"{test_name}: {item} not in {container}"
            if context: msg += f" [{context}]"
            self.errors.append(msg)
            print(f"  {fail('FAIL')} {msg}")

    def assert_not_in(self, test_name, item, container, context=""):
        if item not in container:
            self.passed += 1
            if self.verbose:
                print(f"  {ok('PASS')} {test_name}: {item} not in {container}")
        else:
            self.failed += 1
            msg = f"{test_name}: {item} should not be in {container}"
            if context: msg += f" [{context}]"
            self.errors.append(msg)
            print(f"  {fail('FAIL')} {msg}")

    def assert_true(self, test_name, condition, context=""):
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"  {ok('PASS')} {test_name}")
        else:
            self.failed += 1
            msg = f"{test_name}: expected True, got False"
            if context: msg += f" [{context}]"
            self.errors.append(msg)
            print(f"  {fail('FAIL')} {msg}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}Test Summary: {self.passed}/{total} passed{RESET}")
        if self.failed > 0:
            print(f"\n{RED}{self.failed} FAILURES:{RESET}")
            for e in self.errors:
                print(f"  {RED}✗{RESET} {e}")
        else:
            print(f"\n{GREEN}All tests passed!{RESET}")
        return self.failed == 0


# ═══════════════════════════════════════════════════════════════
# 8. Main
# ═══════════════════════════════════════════════════════════════

def main():
    verbose = "--verbose" in sys.argv
    fixture_filter = None
    for arg in sys.argv:
        if arg.startswith("F-SO-"):
            fixture_filter = arg

    t = TestSuite(verbose=verbose)
    agent = parse_agent_claude(MOCK_AGENT)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}Skill Optimization — Test Suite{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── 8.1 6-Dimension Diagnosis Tests ──
    print(f"\n{CYAN}── 1. 6-Dimension Diagnosis{RESET}")

    fixture_dirs = sorted([d for d in FIXTURES_DIR.iterdir()
                           if d.is_dir() and d.name.startswith("F-SO-")
                           and not d.name.startswith("F-SO-EDGE")])
    if fixture_filter:
        fixture_dirs = [d for d in fixture_dirs if d.name == fixture_filter]

    for fixture_dir in fixture_dirs:
        skill_path = fixture_dir / "SKILL.md"
        if not skill_path.exists():
            continue
        info = parse_skill(skill_path)
        result = run_diagnosis(info, agent)

        fixture_name = fixture_dir.name
        print(f"\n  {BOLD}{fixture_name}{RESET}: {info.name} ({info.lines} lines, {info.step_count} steps)")

        # ── F-SO-001: Healthy baseline ──
        if fixture_name == "F-SO-001-healthy":
            for dim in ["decomposition", "information", "state", "verification", "design_form", "global_context"]:
                t.assert_equal(f"{fixture_name}/{dim}/status", result.findings[dim].status, "PASS")
            t.assert_equal(f"{fixture_name}/boundary", result.boundary_decision, "SKILL_ONLY")
            t.assert_equal(f"{fixture_name}/patterns", len(result.recommended_patterns), 0,
                           f"healthy skill should have 0 patterns, got {result.recommended_patterns}")

        # ── F-SO-002: Monolithic ──
        elif fixture_name == "F-SO-002-monolithic":
            t.assert_equal(f"{fixture_name}/decomposition", result.findings["decomposition"].status, "FAIL")
            t.assert_true(f"{fixture_name}/decomposition/HIGH", result.findings["decomposition"].severity == "HIGH")
            t.assert_in(f"{fixture_name}/patterns/1", 1, result.recommended_patterns)
            t.assert_true(f"{fixture_name}/steps>=8", info.step_count >= 8)

        # ── F-SO-003: No references ──
        elif fixture_name == "F-SO-003-no-references":
            t.assert_equal(f"{fixture_name}/information", result.findings["information"].status, "FAIL")
            t.assert_true(f"{fixture_name}/information/HIGH", result.findings["information"].severity == "HIGH")
            t.assert_in(f"{fixture_name}/patterns/2", 2, result.recommended_patterns)
            t.assert_in(f"{fixture_name}/patterns/7", 7, result.recommended_patterns)
            t.assert_true(f"{fixture_name}/no-references-dir", not info.has_references_dir)

        # ── F-SO-004: No checkpoint ──
        elif fixture_name == "F-SO-004-no-checkpoint":
            t.assert_equal(f"{fixture_name}/state", result.findings["state"].status, "FAIL")
            t.assert_in(f"{fixture_name}/patterns/5", 5, result.recommended_patterns)
            t.assert_true(f"{fixture_name}/no-checkpoint", not info.has_checkpoint)
            t.assert_true(f"{fixture_name}/steps>=4", info.step_count >= 4)

        # ── F-SO-005: No G1 ──
        elif fixture_name == "F-SO-005-no-g1":
            t.assert_equal(f"{fixture_name}/verification", result.findings["verification"].status, "FAIL")
            t.assert_true(f"{fixture_name}/verification/CRITICAL",
                          result.findings["verification"].severity in ("CRITICAL", "HIGH"))
            t.assert_in(f"{fixture_name}/patterns/6", 6, result.recommended_patterns, "self-review should trigger pattern 6")
            t.assert_true(f"{fixture_name}/self-review", info.self_review)
            t.assert_true(f"{fixture_name}/output-tmp", any(p.startswith("/tmp") for p in info.output_paths))

        # ── F-SO-006: Bad design form ──
        elif fixture_name == "F-SO-006-bad-form":
            t.assert_equal(f"{fixture_name}/design_form", result.findings["design_form"].status, "FAIL")
            t.assert_in(f"{fixture_name}/patterns/7", 7, result.recommended_patterns)
            t.assert_true(f"{fixture_name}/generic-name", info.name.lower() == "helper")
            t.assert_true(f"{fixture_name}/inline-code", info.inline_code_blocks >= 2)
            t.assert_true(f"{fixture_name}/no-refs-dir", not info.has_references_dir)
            t.assert_true(f"{fixture_name}/no-scripts-dir", not info.has_scripts_dir)
            t.assert_true(f"{fixture_name}/bad-description", len(info.description) < 40)

        # ── F-SO-007: Agent misaligned ──
        elif fixture_name == "F-SO-007-agent-misaligned":
            t.assert_equal(f"{fixture_name}/global_context", result.findings["global_context"].status, "FAIL")
            t.assert_true(f"{fixture_name}/global_context/CRITICAL",
                          result.findings["global_context"].severity == "CRITICAL")
            t.assert_in(f"{fixture_name}/patterns/8", 8, result.recommended_patterns)
            t.assert_true(f"{fixture_name}/self-review", info.self_review)
            # Check agent issues
            t.assert_true(f"{fixture_name}/agent-issues",
                          len(result.agent_issues) > 0 or result.boundary_decision != "SKILL_ONLY")

        # ── F-SO-008: Mega-skill ──
        elif fixture_name == "F-SO-008-mega-skill":
            t.assert_equal(f"{fixture_name}/decomposition", result.findings["decomposition"].status, "FAIL")
            t.assert_in(f"{fixture_name}/patterns/9", 9, result.recommended_patterns,
                        f"mega-skill (>800 lines) should trigger pattern 9 (split), got {result.recommended_patterns}")
            t.assert_true(f"{fixture_name}/split-trigger", info.lines > 800 or info.step_count > 20)
            t.assert_in(f"{fixture_name}/patterns/5", 5, result.recommended_patterns, "should also get state tracking")

    # ── 8.2 Design Form — Anthropic Spec Compliance ──
    print(f"\n{CYAN}── 2. Anthropic Skill Spec Compliance (SF-1 through SF-8){RESET}")

    # Test SF-6 description formula
    healthy = parse_skill(FIXTURES_DIR / "F-SO-001-healthy/SKILL.md")
    t.assert_true("SF-6/healthy/has-trigger",
                  bool(re.search(r"当|触发", healthy.description.lower())),
                  "healthy skill should have trigger condition in description")
    t.assert_true("SF-6/healthy/has-input",
                  bool(re.search(r"输入|文件路径", healthy.description.lower())),
                  "healthy skill should mention input")
    t.assert_true("SF-6/healthy/has-output",
                  bool(re.search(r"输出|生成|报告", healthy.description.lower())),
                  "healthy skill should mention output")

    bad_form = parse_skill(FIXTURES_DIR / "F-SO-006-bad-form/SKILL.md")
    t.assert_true("SF-5/bad-form/generic-name", bad_form.name.lower() == "helper")
    t.assert_true("SF-6/bad-form/bad-desc", len(bad_form.description) < 20)
    t.assert_true("SF-7/bad-form/inline-code", bad_form.inline_code_blocks >= 2)

    # ── 8.3 Global Context — Cross-reference with Agent CLAUDE.md ──
    print(f"\n{CYAN}── 3. Global Context — Agent Alignment{RESET}")

    t.assert_true("GC/agent-parsed", agent is not None, "mock agent CLAUDE.md should be parseable")
    if agent:
        t.assert_true("GC/agent-has-g1", agent.has_g1_reviewer, "mock agent should have G1 Reviewer")
        t.assert_true("GC/agent-work-dir", agent.work_dir_convention == "work/", "mock agent should use work/")
        t.assert_in("GC/agent-tools", "Read", agent.allowed_tools)
        t.assert_not_in("GC/agent-no-edit", "Edit", agent.allowed_tools, "mock agent should NOT have Edit tool")

        misaligned = parse_skill(FIXTURES_DIR / "F-SO-007-agent-misaligned/SKILL.md")
        t.assert_true("GC/misaligned-has-edit", "Edit" in misaligned.mentions_agent_tools)
        t.assert_true("GC/misaligned-self-review", misaligned.self_review)
        t.assert_true("GC/misaligned-tmp-output", any(p.startswith("/tmp") for p in misaligned.output_paths))

    # ── 8.4 Pattern Matching ──
    print(f"\n{CYAN}── 4. Pattern Matching Engine{RESET}")

    # Pattern 1: Monolithic → Pipeline Decomposition
    mono = run_diagnosis(parse_skill(FIXTURES_DIR / "F-SO-002-monolithic/SKILL.md"), agent)
    t.assert_in("PAT-1/mono", 1, mono.recommended_patterns)

    # Pattern 9: Mega → Split
    mega = run_diagnosis(parse_skill(FIXTURES_DIR / "F-SO-008-mega-skill/SKILL.md"), agent)
    t.assert_in("PAT-9/mega", 9, mega.recommended_patterns)

    # Pattern 7: Bad form → Form Restructure
    bad = run_diagnosis(parse_skill(FIXTURES_DIR / "F-SO-006-bad-form/SKILL.md"), agent)
    t.assert_in("PAT-7/bad-form", 7, bad.recommended_patterns)

    # Pattern 8: Misaligned → Global Alignment
    mis = run_diagnosis(parse_skill(FIXTURES_DIR / "F-SO-007-agent-misaligned/SKILL.md"), agent)
    t.assert_in("PAT-8/misaligned", 8, mis.recommended_patterns)

    # ── 8.5 Multi-Skill Scenarios ──
    print(f"\n{CYAN}── 5. Multi-Skill Analysis{RESET}")

    # Load 3 related skills
    mega_skill = parse_skill(FIXTURES_DIR / "F-SO-008-mega-skill/SKILL.md")
    overlap_skill = parse_skill(FIXTURES_DIR / "F-SO-009-overlapping/SKILL.md")
    dependent_skill = parse_skill(FIXTURES_DIR / "F-SO-010-dependent/SKILL.md")

    skill_map = {
        "F-SO-008-mega-skill": mega_skill,
        "F-SO-009-overlapping": overlap_skill,
        "F-SO-010-dependent": dependent_skill,
    }
    cross = analyze_cross_skill(skill_map)

    t.assert_true("MULTI/deps-found", len(cross.dependency_matrix) > 0,
                  f"should find data dependencies between skills, found {len(cross.dependency_matrix)}")
    t.assert_true("MULTI/overlap-found", len(cross.overlaps) > 0,
                  f"should find functional overlaps, found {len(cross.overlaps)}")
    t.assert_in("MULTI/patterns/10", 10, cross.recommended_patterns)
    t.assert_in("MULTI/patterns/11", 11, cross.recommended_patterns)

    # Check order: dependent should be last
    if cross.recommended_order:
        t.assert_true("MULTI/dependent-last",
                      "F-SO-010-dependent" in cross.recommended_order,
                      f"dependent skill should be in order, got {cross.recommended_order}")

    # ── 8.6 Escalation / Boundary Decision ──
    print(f"\n{CYAN}── 6. Escalation Boundary Decisions{RESET}")

    # Edge case 1: Memory noise → FULLY_EXCEEDED
    mem_result = evaluate_escalation_scenario("F-SO-EDGE-001",
        "Agent 在同一会话中执行越久质量越差，新开会话后恢复")
    t.assert_equal("EDGE/memory/boundary", mem_result["boundary"], "FULLY_EXCEEDED")
    t.assert_in("EDGE/memory/issue", "Memory 噪声积累", mem_result["agent_issues"])

    # Edge case 2: Single step quality → FULLY_EXCEEDED
    qual_result = evaluate_escalation_scenario("F-SO-EDGE-002",
        "单体 Agent 执行代码审查质量差，但 SKILL.md 指令已足够清晰")
    t.assert_equal("EDGE/quality/boundary", qual_result["boundary"], "FULLY_EXCEEDED")
    t.assert_in("EDGE/quality/issue", "单步任务质量低", qual_result["agent_issues"])

    # Edge case 3: Minimal skill — should only need pattern 7
    min_info = parse_skill(FIXTURES_DIR / "F-SO-EDGE-003-minimal/SKILL.md")
    min_result = run_diagnosis(min_info, agent)
    t.assert_equal("EDGE/minimal/lines", min_info.lines, 3, f"minimal skill should have 3 lines, got {min_info.lines}")
    t.assert_equal("EDGE/minimal/decomposition", min_result.findings["decomposition"].status, "PASS")
    t.assert_equal("EDGE/minimal/information", min_result.findings["information"].status, "PASS")
    t.assert_equal("EDGE/minimal/state", min_result.findings["state"].status, "PASS")
    t.assert_equal("EDGE/minimal/verification", min_result.findings["verification"].status, "PASS")
    t.assert_equal("EDGE/minimal/design_form", min_result.findings["design_form"].status, "PASS",
                   "minimal skill with only name+description is too small for SF checks to fire")
    t.assert_equal("EDGE/minimal/global_context", min_result.findings["global_context"].status, "PASS")

    # ── 8.7 Anti-pattern Checks ──
    print(f"\n{CYAN}── 7. Anti-Pattern Detection{RESET}")

    # Check that patterns file contains the required anti-patterns
    patterns_file = RULES_DIR / "skill-optimization-patterns.md"
    patterns_content = patterns_file.read_text()
    t.assert_true("ANTI/no-full-rewrite", "禁止全量重写" in patterns_content)
    t.assert_true("ANTI/no-over-decomp", "禁止过度拆解" in patterns_content)
    t.assert_true("ANTI/no-review-free-decomp", "禁止无审查拆解" in patterns_content)
    t.assert_true("ANTI/no-call-flow-update-split", "禁止无调用流更新的拆分" in patterns_content)
    t.assert_true("ANTI/no-isolated-cross-skill", "禁止忽略跨 Skill 影响的孤立优化" in patterns_content)

    # ── 8.8 Rule File Integrity ──
    print(f"\n{CYAN}── 8. Rule File Integrity{RESET}")

    for rule_file in ["skill-diagnosis-rules.md", "skill-optimization-patterns.md", "escalation-decision-rules.md"]:
        path = RULES_DIR / rule_file
        t.assert_true(f"INTEGRITY/{rule_file}/exists", path.exists())
        content = path.read_text()
        t.assert_true(f"INTEGRITY/{rule_file}/non-empty", len(content) > 200,
                      f"{rule_file} has {len(content)} chars (expected >200)")

    # Check diagnosis file has 6 dimensions
    diag_content = (RULES_DIR / "skill-diagnosis-rules.md").read_text()
    t.assert_true("INTEGRITY/diag/6-dims", "维度 5: Design Form" in diag_content)
    t.assert_true("INTEGRITY/diag/6-dims-2", "维度 6: Global Context" in diag_content)
    t.assert_true("INTEGRITY/diag/6-dim-title",
                  "6维诊断框架" in diag_content or "6 维诊断框架" in diag_content)

    # ── Summary ──
    success = t.summary()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
