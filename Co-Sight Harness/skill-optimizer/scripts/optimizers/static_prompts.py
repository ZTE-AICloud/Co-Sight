"""static_prompts.py — /skill_optimize 的 prompt 模板。

两个核心 prompt 构造函数：
- build_evaluator_prompt() → 注入到 evaluator 子 agent
- build_optimizer_prompt() → 注入到 optimizer 子 agent

设计原则：
- 注入用户指引（最高优先级）
- 注入 dim_scores rubric（v3：每 dim 含 criteria + anti_criteria + scoring_rubric）
- 注入 HL-1~4 实战经验（杠杆点）
- 注入具体 SKILL.md 内容
- 要求严格 JSON 输出（dim_scores 必须是 0~10 数字）

v3 改造：v2 的 skill_anti_patterns / optimizer_anti_patterns / optimizer_patterns 三段
已融合进 12 dim 的 criteria / anti_criteria 段，外部模板无需再注入独立反例段。

具体维度数与名称由 framework_configs/static-eval-config.yaml 的 rubric 段定义，
本文件不再硬编码。
"""
from __future__ import annotations

from typing import Optional


def _format_rubric(rubric: dict) -> str:
    """把 framework YAML 的 rubric 段格式化为可读文本（v3：含 criteria + anti_criteria + scoring_rubric）。

    每个 dim 输出 4 段：
    - 标题：dim_key + name + weight
    - criteria：什么是好（5-7 条）
    - anti_criteria：什么是坏（AP1~AP15 + 扣分）
    - scoring_rubric：评分档位（10/8/6/4/2）
    """
    lines: list[str] = []
    for key, dim in rubric.items():
        if not key.startswith("dim"):
            continue
        lines.append(f"### {key} — {dim['name']}（weight={dim['weight']}）")
        if dim.get("leverage_note"):
            lines.append(f"**杠杆点**：{dim['leverage_note']}")
        lines.append("**评分标准（什么是好）**：")
        lines.append(dim["criteria"].strip())
        anti = dim.get("anti_criteria", "").strip()
        if anti:
            lines.append("")
            lines.append("**反例（什么是坏，命中扣分）**：")
            lines.append(anti)
        rubric_block = dim.get("scoring_rubric", "").strip()
        if rubric_block:
            lines.append("")
            lines.append("**评分档位**：")
            lines.append(rubric_block)
        lines.append("")
    return "\n".join(lines)


# role → 适用 dim 映射（与 skill-unified-agent.md 一致）
ROLE_TO_DIMS: dict[str, list[str]] = {
    "entrypoint": ["dim1_metadata_trigger", "dim2_step_executability",
                   "dim6_cross_section_consistency", "dim7_agent_contract_alignment",
                   "dim8_anthropic_sf", "dim12_structure_purity"],
    "implementation": ["dim2_step_executability", "dim3_failure_recovery",
                       "dim4_checkpoints", "dim5_specificity",
                       "dim7_agent_contract_alignment", "dim10_safety_auto",
                       "dim11_efficiency_auto"],
    "knowledge": ["dim5_specificity", "dim6_cross_section_consistency",
                  "dim7_agent_contract_alignment", "dim9_coverage_auto",
                  "dim12_structure_purity"],
    "template": ["dim5_specificity", "dim6_cross_section_consistency",
                 "dim8_anthropic_sf", "dim9_coverage_auto"],
    "asset": [],
    "doc": ["dim5_specificity", "dim12_structure_purity"],
    "data": ["dim10_safety_auto"],
    "aux_code": ["dim2_step_executability", "dim3_failure_recovery"],
    "other": [],
}


def _format_dim_definitions_per_role(rubric: dict) -> str:
    """构造每个 role 的 dim 完整评分定义段，注入到 unified/optimizer prompt。

    与 role→dim 映射配套，每条 dim 附加 criteria / anti_criteria / scoring_rubric，
    让 LLM 打分时有据可依（取代只靠 dim name 猜测）。

    Args:
        rubric: framework YAML 的 rubric 段

    Returns:
        Markdown 段文本；rubric 为空时返回空字符串
    """
    if not rubric:
        return ""
    lines = ["## 各 role 对应 dim 的完整评分定义", "",
             "下方按 role 列出每个 dim 的评分标准、反例和档位。"
             "打分时必须依据定义，不能凭印象随意给分。", ""]
    for role, dims in ROLE_TO_DIMS.items():
        if not dims:
            continue
        role_label = {
            "entrypoint": "entrypoint（SKILL.md）",
            "implementation": "implementation（scripts/*）",
            "knowledge": "knowledge（references/*）",
            "template": "template（templates/*）",
            "doc": "doc（文档类）",
            "aux_code": "aux_code（辅助代码）",
            "data": "data（数据文件）",
        }.get(role, role)
        lines.append(f"### {role_label}")
        for dim_key in dims:
            dim = rubric.get(dim_key)
            if not dim:
                continue
            lines.append(f"**{dim_key} — {dim.get('name', '')}（weight={dim.get('weight', 1.0)}）**")
            crit = dim.get("criteria", "").strip()
            if crit:
                lines.append(f"评分标准：{crit}")
            anti = dim.get("anti_criteria", "").strip()
            if anti:
                lines.append(f"反例：{anti}")
            sr = dim.get("scoring_rubric", "").strip()
            if sr:
                lines.append(f"档位：\n{sr}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def _format_hl_rules(rules: list[dict]) -> str:
    """把 HL-1~4 实战经验格式化为可读文本。"""
    lines: list[str] = ["## HL-1~4 实战经验（darwin 高杠杆点）", ""]
    for r in rules:
        lines.append(f"### {r['id']} — {r['name']}")
        lines.append(f"**杠杆维度**：{r['lever']}（预期 +{r['expected_delta']}）")
        lines.append(f"**规则**：{r['rule'].strip()}")
        lines.append("")
    return "\n".join(lines)


def _format_eval_view(
    rubric: dict,
    eval_view: dict,
    overrides: dict,
) -> str:
    """构造「评估视角」段注入 evaluator prompt。

    渐进式披露：只输出"看哪些文件 + 注意事项"，不重复 criteria 文本。
    浅合并：framework 默认 + 业务方覆盖。

    Args:
        rubric: framework YAML 的 rubric 段（用于按 dim_keys 顺序遍历）
        eval_view: framework YAML 的 eval_view 段（含默认视角配置）
        overrides: optimize-user-config.yaml 的 dim_view_overrides 段

    Returns:
        Markdown 段文本；eval_view 和 overrides 都为空时返回空字符串
    """
    if not eval_view and not overrides:
        return ""

    lines = [
        "## 评估视角（评分时按 dim 配置跨文件找证据）",
        "",
        "**不要默认只看 SKILL.md** — 按下方配置，"
        "dim3 主要看 scripts/* 实际错误处理，dim5 看脚本+文档共同评分。",
        "**less is more** — SKILL.md 简短的技能只要 scripts/* 实现质量高，"
        "仍应得高分；反之 SKILL.md 罗列大量细节但 scripts/* 没实现，应当扣分。",
        "",
    ]

    dim_keys = sorted(k for k in rubric if k.startswith("dim"))
    for dim in dim_keys:
        cfg = {**(eval_view.get(dim) or {}), **(overrides.get(dim) or {})}
        if not cfg:
            continue
        dim_name = rubric[dim].get("name", dim)
        primary = cfg.get("primary_files", [])
        secondary = cfg.get("secondary_files", [])
        note = cfg.get("note", "")

        parts = [f"- **{dim}（{dim_name}）**"]
        parts.append(f"主看: {' + '.join(primary) or '（无）'}")
        if secondary:
            parts.append(f"次看: {' + '.join(secondary)}")
        if note:
            parts.append(f"注意: {note}")
        lines.append(" | ".join(parts))

    return "\n".join(lines) + "\n"


def _format_design_principles(
    framework_principles: list[dict],
    user_principles: list[dict],
) -> str:
    """构造「Skill 设计原则」段注入 optimizer prompt。

    框架默认 + 业务方追加合并。注入后作为"严格约束"级的硬规则。

    Args:
        framework_principles: framework YAML 的 optimizer_design_principles 段
        user_principles: optimize-user-config.yaml 的 design_principles_overrides 段

    Returns:
        Markdown 段文本；都为空时返回空字符串
    """
    all_principles = list(framework_principles or []) + list(user_principles or [])
    if not all_principles:
        return ""

    lines = [
        "## 🎯 Skill 设计原则（必须遵守，违反则提案无效）",
        "",
        "**核心哲学**：懒加载——不需要时不要加载，加载时只加载够用的。",
        "SKILL.md 是**契约层**，scripts/* 是**实现层**，references/* 是**知识层**，三者分层协同。",
        "",
    ]

    for p in all_principles:
        lines.append(f"### {p.get('id', '?')} — {p.get('name', '?')}")
        rule = p.get("rule", "").strip()
        if rule:
            lines.append(rule)
        lines.append("")

    return "\n".join(lines)


def build_evaluator_prompt(
    skill_content: str,
    target_files_content: list[tuple[str, str]],
    expert_guidance: str,
    rubric: dict,
    hl_rules: list[dict],
    test_prompts: Optional[list[dict]] = None,
    *,
    round_num: int = 1,
    nonce: str = "",
    eval_view: Optional[dict] = None,
    eval_view_overrides: Optional[dict] = None,
    relation_tree: Optional[dict] = None,
    applied_modifications: Optional[list] = None,
) -> tuple[str, str]:
    """构造 evaluator 子 agent 的 prompt。

    Args:
        skill_content: SKILL.md 全文
        target_files_content: [(file_path, content), ...] 附属文件
        expert_guidance: 用户自然语言指引（最高优先级）
        rubric: framework YAML 的 rubric 段（v3：每 dim 含 criteria + anti_criteria + scoring_rubric）
        hl_rules: framework YAML 的 hl_rules 段
        test_prompts:  Top 5 — test-prompts.json fixture 内容
                      [{prompt, expected, source}, ...]（None = 无 fixture）
        round_num: 当前评估轮次（ B 方案：JSON 模板 round 字段写对）
        nonce: 唯一标识（ B 方案：防止 LLM API 端跨 call 缓存命中）

    Returns:
        (system, user_prompt) 元组
    """
    rubric_text = _format_rubric(rubric)
    hl_text = _format_hl_rules(hl_rules)

    # 文件内容（附属资产）：正文由 _read_skill_and_files 截为首尾摘要，此处不再二次截断
    files_text = "\n\n".join(
        f"### 附属文件: {path}\n```\n{content}\n```"
        for path, content in target_files_content
    ) or "（无附属文件）"

    files_section = f"## 附属文件（首尾摘要，非全文）\n{files_text}" if files_text != "（无附属文件）" else ""

    # 关系树骨架：给 evaluator 全部文件的统一视角，评分时综合判断而非只看 SKILL.md
    relation_section = _format_relation_tree(relation_tree)
    if relation_section:
        files_section = relation_section + "\n\n" + files_section

    # 跨文件一致性视图：本轮实际应用的 mods（让 evaluator 能验证联动）
    consistency_section = _format_cross_file_consistency(
        relation_tree, applied_modifications,
    )
    if consistency_section:
        files_section = consistency_section + "\n\n" + files_section

    # -E：test-prompts 段已删除（dim9_test_prompts 移除）

    # 评分维度列表（动态生成）
    rubric_keys = sorted(k for k in rubric if k.startswith("dim"))
    dim_scores_template = ", ".join(f'"{k}": <0-10>' for k in rubric_keys)
    # 治本（.11+）：硬契约 — dim_scores 必须是 0~10 范围的数字（整数或一位小数），
    # 禁止 0~1（百分率小数）或 0~100（百分制），违反视为无效输出由 invoke_evaluator 丢弃。
    dim_score_range_constraint = (
        "每个 dim_scores 字段值必须严格在 [0, 10] 区间内,推荐整数或 1 位小数。"
        "禁止 0~1 范围(如 0.78)、禁止 0~100 范围(如 78.3)、禁止 null/字符串。"
        "任意 dim 违反契约 → invoke_evaluator 拒绝该次 run 并触发 REWORK 重试。"
    )

    #  B 方案：system 段加"独立评估"显式声明 + nonce 防 LLM API 端跨 call 缓存
    system = (
        "你是 skill 静态评估专家，按下方 rubric（dim1~dimN + total + gaps）严格评分，"
        "不编造事实，所有引用必须来自**实际文件**（SKILL.md / scripts/* / references/*）。\n\n"
        "【整体视角】技能是 SKILL.md（契约）+ scripts/*（实现）+ references/*（知识）的整体。"
        "**不要默认只看 SKILL.md 一个文件** — 按下方「评估视角」配置，"
        "dim3 主要看 scripts/* 实际错误处理。\n\n"
        "【less is more】SKILL.md 简短的技能只要 scripts/* 实现质量高，仍应得高分。"
        "SKILL.md 罗列大量细节但 scripts/* 没有实现，应当扣分。\n\n"
        "【独立性约束】本评估是独立调用，与该 skill 的任何历史评估轮次完全无关。"
        "不要尝试参考或推断之前轮次的分数、gaps、改动趋势。"
        "仅根据下方实际文件内容独立打分；若有不确定，宁可保守给中位分（如 5-7），"
        "也不要因'这是第 N 轮了'而给过高或过低分。"
    )

    # nonce 段（防 LLM API 端缓存命中；不影响 LLM 评分内容）
    nonce_section = f"\n## 本轮唯一标识（用于追踪，独立于评分内容）\n{nonce}\n" if nonce else ""

    user_prompt = f"""## 用户指引（最高优先级）
{expert_guidance or "（无）"}
{nonce_section}
## 任务
对以下**技能包**（SKILL.md + scripts/* + references/*）进行静态评估，输出严格 JSON 格式评分。
技能是一个整体——SKILL.md 是契约层、scripts/* 是实现层、references/* 是知识层，三者协同满足用户需求。

{_format_eval_view(rubric, eval_view or {}, eval_view_overrides or {})}

## 评分 rubric
{rubric_text}

{hl_text}

## SKILL.md 内容（{len(skill_content)} 字符，已完整注入，无截断）
```
{skill_content}
```

{files_section}

## 评分协议
- 每维度 0~10 分（0 = 完全缺失，10 = 完美）
- 评分依据必须引用**实际文件**（行号、章节名、原文片段）
- **evidence 字段必须包含文件路径**：`SKILL.md:45` 或 `scripts/upload.mjs:67`（不要省略文件路径）
- **🔴 真实凭据不要扣分**：`config.json` / `.env` / 代码文件中的真实 `api_key` / `token` 等敏感字段是**运行时有效配置**，不是示例代码，**不得标记为"硬编码密钥"反例**、不得扣 dim11/反例分。darwin 反例"硬编码密钥"仅适用于示例/教程代码。
- 反例命中：列出命中条目 ID（如 "SAP3"），不命中则为空数组
- gaps[]：≤5 条最严重缺口，每条含 dimension/severity/fix_suggestion
- expert_guidance_ref：标注本次评分是否参考了用户指引
- {dim_score_range_constraint}

## 输出 JSON
{{
  "round": {round_num},
  "dim_scores": {{
    {dim_scores_template}
  }},
  "total": 67.5,
  "rating": "FAIR",
  "anti_pattern_hits": ["SAP3"],
  "gaps": [
    {{
      "dimension": "dim3",
      "section": "## 失败处理",
      "severity": "high",
      "message": "失败处理段只写'重试'，未含三段式（触发条件/一线修复/仍失败兜底）",
      "fix_suggestion": "按 HL-2 改写为三段式：触发条件 + sleep N + 重试；仍失败则退出并打印 trace"
    }}
  ],
  "expert_guidance_ref": "已参考用户指引: ...",
  "_test_prompt_results": [],
  "_evidence": "dim3 评分依据：SKILL.md 第 45 行 '如遇错误请重试'，未含三段式..."
}}
"""
    return system, user_prompt


def _format_test_prompts(test_prompts: Optional[list[dict]]) -> str:
    """-E：dim9_test_prompts 已删除，此函数保留为 no-op 兼容旧调用。

    Returns: 始终空字符串（不再注入 test-prompts 段）。
    """
    return ""


def _format_revision_strategy(revision_strategy: Optional[dict]) -> str:
    """R2+ 注入：把 StaticRevisionAgent 生成的 revision_strategy 段渲染为 system prompt 顶部约束。

    Args:
        revision_strategy: StaticRevisionAgent 产出 dict,含 absorbed_rounds / cross_round_trends /
            prev_round_summary / prev_failures / baseline_anchor / dim_balance_plan / modification_intent

    Returns:
        Markdown 段文本(R2+ 才非空),空字符串表示 R1(不注入)。
    """
    if not revision_strategy:
        return ""
    lines: list[str] = ["", "## 接续优化策略(R2+ StaticRevisionAgent 产出)", ""]
    absorbed = revision_strategy.get("absorbed_rounds") or []
    if absorbed:
        lines.append(f"- **已吸收轮次**: {', '.join(str(r) for r in absorbed)}")
    summary = revision_strategy.get("prev_round_summary") or ""
    if summary:
        lines.append(f"- **上轮一句话总结**: {summary}")
    trends = revision_strategy.get("cross_round_trends") or {}
    if trends:
        lines.append("- **跨轮 dim 趋势**:")
        for dim, trend in trends.items():
            lines.append(f"  - {dim}: {trend}")
    failures = revision_strategy.get("prev_failures") or []
    if failures:
        lines.append("- **上轮失败继承(本轮规避)** :")
        for f in failures[:5]:
            lines.append(f"  - {f}")
    anchor = revision_strategy.get("baseline_anchor") or ""
    if anchor:
        lines.append(f"- **基线锚点(R0 vs 当前漂移)**: {anchor}")
    balance = revision_strategy.get("dim_balance_plan") or {}
    if balance:
        lines.append("- **本轮 dim 预算分配**:")
        for dim, n in balance.items():
            lines.append(f"  - {dim}: {n} 条 mod")
    intent = revision_strategy.get("modification_intent") or []
    if intent:
        lines.append("- **modification 目标维度分布**:")
        for i, item in enumerate(intent[:5], 1):
            lines.append(f"  - M{i}: {item}")
    return "\n".join(lines) + "\n"


def build_optimizer_prompt(
    score_json: dict,
    skill_content: str,
    target_files_content: list[tuple[str, str]],
    expert_guidance: str,
    hl_rules: list[dict],
    round_num: int,
    max_modifications: int,
    relation_tree: Optional[dict] = None,
    revise_signals: Optional[dict] = None,
    overfit_signals: Optional[dict] = None,
    apply_failure_signals: Optional[list] = None,
    chars_budget: Optional[int] = None,
    revision_strategy: Optional[dict] = None,
    design_principles: Optional[list[dict]] = None,
    design_principles_overrides: Optional[list[dict]] = None,
) -> tuple[str, str]:
    """构造 optimizer 子 agent 的 prompt。

    Args:
        score_json: 上轮 evaluator 的输出
        skill_content: SKILL.md 全文
        target_files_content: [(file_path, content), ...] 附属文件
        expert_guidance: 用户自然语言指引（最高优先级）
        hl_rules: framework YAML 的 hl_rules 段
        round_num: 当前轮次（从 1 开始）
        max_modifications: 单轮最大修改条数
        relation_tree: build_relation_tree() 产出的关系树 dict（骨架 + 引用关系 +
                       long_unoptimized / orphans），注入后引导优化覆盖全部文件
        revise_signals: 上一轮 REVISE 信号 {applied_mods, failed_mods, dim_improvements}
        overfit_signals:  P1-B：上轮 overfit 检测反馈 {warning, count, last_round_reasons}
        apply_failure_signals:  P2-A：上轮 apply 失败根因列表
        chars_budget:  P2-B：单轮 modifications 总字符预算（before+after 之和）
        revision_strategy: R2+ 接续优化策略(StaticRevisionAgent 产出,R1=None)

    Returns:
        (system, user_prompt) 元组
    """
    hl_text = _format_hl_rules(hl_rules)

    # 当前评分摘要
    dim_scores = score_json.get("dim_scores", {})
    lowest_dims = sorted(dim_scores.items(), key=lambda x: x[1])[:3]
    # v3：每个 dim 自带 anti_criteria 段，optimizer 看 dim 分数低的项 → 查对应 dim 的 anti_criteria
    lowest_text = "\n".join(
        f"  - {k}: {v}（参考该 dim 的 anti_criteria 反向推改法）"
        for k, v in lowest_dims
    )

    # .12:dim12 长度控制反馈 — 如果上一轮 dim12 = 0,LLM 必须明确知道根因
    # 公式:.10 token 效率(默认基线 8,微变 +50% 内 8,精简 9,每+50%减 1)
    dim12_score = dim_scores.get("dim12_efficiency", None)
    dim12_warning = ""
    if dim12_score is not None and dim12_score < 5:
        dim12_warning = (
            "\n\n## 🔴 长度控制警告(.12)\n"
            f"- dim12_efficiency = **{dim12_score}**(< 5 表示 token 增长过多)\n"
            "- **根因**:SKILL.md 被大幅扩写,token 数相对 baseline 增长过多\n"
            "- **.10 评分规则**:token 不变 → 8 分|减少 → 9 分|+0%~+50% → 8 分|+50~100% → 7|+100~150% → 6|每多 +50% 减 1 分\n"
            "- **本轮目标**:\n"
            "  1. **本轮 token 增长控制在 +50% 以内**(保证 dim12 ≥ 7)\n"
            "  2. 优先用压缩方式改写(精炼长段、删冗余),而非扩写\n"
            "  3. **必要时允许同时压缩 token + 提升其他维度**(覆盖原有'每条只改 1 个维度'约束)\n"
            "  4. 如果上一轮 R 整体增长 > 200%,**优先回退部分内容**而非继续添加\n"
        )

    # 反例命中
    anti_hits = score_json.get("anti_pattern_hits", [])
    hits_text = (
        "\n".join(f"  - {h}" for h in anti_hits) if anti_hits else "  （无）"
    )

    # :gaps + 自检约束 — 内联渲染（避免新增 helper 函数，见 plan P0-A）
    gaps = score_json.get("gaps", [])
    if gaps:
        gaps_section = (
            "\n## 上轮 evaluator 识别的缺口（必须本轮针对性修复）\n"
            "以下缺口按严重度排序，本轮 modifications 至少 1 条针对 top-3 gap：\n"
            + "\n".join(
                f"  {i}. {g.get('text', str(g)) if isinstance(g, dict) else str(g)}"
                for i, g in enumerate(gaps[:7], 1)
            )
        )
    else:
        gaps_section = ""

    top_patterns = [
        h["pattern_id"] for h in (anti_hits or [])[:5]
        if isinstance(h, dict) and h.get("pattern_id")
    ][:3]
    patterns_text = (
        f"\n**本轮必消除反例**: {', '.join(f'`{p}`' for p in top_patterns)}"
        if top_patterns else ""
    )
    self_check_section = (
        "\n\n## 🔴 自检约束（违反会被 P4 硬阻断）\n"
        "1. **引用闭合**: 引用的 .md/.py 路径若非现有文件，必须本轮 mod 之一新建它\n"
        "2. **段落去重**: 同文件 ≥2 条 mod 的 after 相似度 > 0.7 会被阻断\n"
        "3. **代码语法**: 改 .py 后用 `python3 -c \"import ast; ast.parse(open('f').read())\"` 自检\n"
        f"{patterns_text}\n"
        "4. **gaps top 3 必须覆盖**: 见上方缺口段，rationale 显式标注「修复 gap X」或「消除反例 Y」"
    )

    files_text = "\n\n".join(
        f"### 附属文件: {path}\n```\n{content}\n```"  # 内容已由 _read_skill_and_files 截为首尾摘要
        for path, content in target_files_content
    ) or "（无附属文件）"
    files_section = f"## 附属文件（首尾摘要，非全文；改前按需 Read 真实文件）\n{files_text}" if files_text != "（无附属文件）" else ""
    dispatch_section = _format_relation_tree(relation_tree)

    #  Top 3：REVISE 信号注入
    revise_section = _format_revise_signals(revise_signals)

    #  P1-B：overfit 信号注入（warn-only 反馈闭环）
    overfit_section = _format_overfit_signals(overfit_signals)

    #  P2-A：apply 失败根因注入（让 LLM 知道为什么上轮 mods 没生效）
    apply_failure_section = _format_apply_failure_signals(apply_failure_signals)

    system = (
        "你是 skill 优化专家。基于上轮评分生成精准修改方案，"
        "避开 8 条 darwin 自操作反例，每条 modification 必须标注 dim_improved 和 pattern_used。"
    ) + _format_revision_strategy(revision_strategy)

    user_prompt = f"""## 用户指引（最高优先级）
{expert_guidance or "（无）"}

{_format_design_principles(design_principles or [], design_principles_overrides or [])}

## 任务
基于上轮评分，生成第 {round_num} 轮的修改方案。
- 严格约束：每轮 ≤{max_modifications} 条 modifications，每条只改 1 个维度
- 单条长度：每条 modification 的 before+after 总和 ≤ 5000 字符（ 替代总字符预算）
- 目标：把最低 3 个维度的评分拉高
- **🔴 责任边界**：SKILL.md 是契约层，scripts/* 是实现层，references/* 是知识层
  - **不要**把 scripts/*.mjs 已实现的逻辑翻译成文字写到 SKILL.md（scripts 自己改就好）
  - **不要**把 references/*.md 的内容内联到 SKILL.md（references 按需读取）
  - **不要**把全部场景堆在一个 references/*.md（按场景分割）
  - **可以**让 scripts/*.mjs 自己加错误处理/参数校验（这才是 dim3 提分点）
  - **可以**新建 references/*/*.md 沉淀业务知识（按场景分割）
  {_format_file_coverage_constraint(relation_tree)}
- md 和代码文件必须统一优化，它们是同一技能的不同表现层
- **🔴 簇内硬联动（避免孤岛修改触发 dim6 扣分）**：
  - **改 SKILL.md 时**：必须找出 SKILL.md 引用的所有 references/、templates/ 文件。**如果 SKILL.md 某个章节描述了 X 流程、而 references/Y.md 是 X 的详细规则**，则**必须同时给 references/Y.md 至少 1 条 mod**（同步更新规则细节），否则触发 dim6 跨章节一致性扣分。
  - **改 scripts/x.sh 时**：必须找出调用 scripts/x.sh 的所有其他 scripts/ 文件（如 `source x.sh` 或 `bash x.sh`）。**被调用方接口变化时，调用方必须同步更新调用语句**。
  - **改 references/Y.md 时**：回看 SKILL.md 是否引用 Y → 同步检查 SKILL.md 的引用描述是否还准确。
  - **每条 mod 必须真实应用到目标文件**（不是描述要联动，必须真的产出 before/after 文本）。
- **🔴 真实凭据禁止修改**：不管在任何文件内（包括 `scripts/config.json`、`.env`、`.mjs`/`.py`/`.json`/`.yaml`/`.toml`/`.sh`），**真实 API Key、Token、密码、Secret、Private Key 等敏感字段一律不得修改、不得替换成占位符、不得加引号或转义**。这些是运行时有效配置，不是示例代码——替换会破坏原功能。darwin 反例"硬编码密钥"仅适用于示例/教程/文档代码，不适用于业务配置文件。
- 避坑：不命中 8 条 darwin 自操作反例

## 上轮评分（round {round_num - 1}）
- total: {score_json.get("total", 0)}（{score_json.get("rating", "UNSCORED")}）
- dim_scores: {dim_scores}
- 最低 3 个维度：
{lowest_text}
- 反例命中：
{hits_text}
{dim12_warning}
{gaps_section}
{self_check_section}

## 严格约束（违反则提案无效）
1. 每轮 ≤{max_modifications} 条 modifications
2. 每条 modification 的 before+after 总和 ≤ 5000 字符（防单条过长， 替代原字符预算）
3. 每条 modification 只改 1 个维度（dim_improved 标注唯一维度）
4. dim2/3/4 是相关簇，可同步改但每条仍要标注 dim_improved
5. 不命中 8 条 darwin 自操作反例（OAP1~OAP8）+ 3 条代码修改反例（OAP9~OAP11）
6. 可新建附属文件（references/*.md / scripts/*），需在 dim_improved 中解释改动理由
7. 不删除 SKILL 已有的附属资产（仅 references/scripts/templates 等已存在文件）
8. 优化后体积 ≤ 原 × 1.5
9. **🔴 真实凭据禁止修改**：不得修改 `api_key` / `token` / `password` / `secret` / `private_key` 等敏感字段的真实值。这些是运行时配置，**不允许替换为占位符**（`<YOUR_*>` / `***` 等）。darwin 反例"硬编码密钥"仅适用于示例/教程代码，不适用于业务配置文件。
10. **🔴 OAP9 禁止插入完整方法/类定义**：modification.after 不得包含完整的方法定义（async/function + body + 闭花括号）或类定义。**代码修改应"局部"**——在已存在的方法/函数内部做小改（如加 try/catch、加 if 校验），**禁止把整段方法从一处搬到另一处**，禁止重复插入已存在的方法。**改代码前必须先 Read 原文件**，确认目标方法在原文件中是否已存在。
11. **🔴 before/after 最小锁定**：`before` 必须是原文件中**唯一匹配的 1~2 行内容**（≤ 120 字符），足以精确定位。**禁止**把整段函数/章节作为 before。`after` 可以是 1 行或多行新内容。**before 文本必须完全来自原文件**（逐字符复制，不能自己编造）。生成后用 Read 确认 before 在文件中真实存在。

## 🔧 代码文件修改指引

对 `scripts/*` 等代码文件（.py/.sh/.json/.yaml/.mjs 等）的修改要求：

### ✅ 可以改的内容（有实际价值的代码修改）
- **错误处理增强**：添加 try/except、重试逻辑、超时处理、HTTP 状态码判断
- **参数校验**：添加空值检查、类型校验、边界条件处理
- **安全加固**：token 脱敏、路径校验（防 path traversal）、SSL 校验开关
- **可观测性**：添加结构化日志（含上下文信息，不含敏感字段）
- **健壮性提升**：处理边缘情况（空列表、None、格式异常）
- **性能优化**：减少冗余 IO、添加缓存、合并请求

### ❌ 不建议改的内容
- 仅改注释/docstring/空行/缩进/格式化——这些不被算作有效修改

### 检查清单（每条 mod 应满足至少 1 条 ✅）
- ✅ 改动了代码逻辑（if/for/try/def 等关键字）
- ✅ 新增了函数或方法
- ✅ 添加了错误处理或安全防护

{dispatch_section}

{_format_per_file_schema_instruction(relation_tree, max_modifications)}

{revise_section}

{overfit_section}

{apply_failure_section}

{hl_text}

## SKILL.md 当前内容（{len(skill_content)} 字符，已完整注入，无截断）
```
{skill_content}
```

{files_section}

## 输出 proposal JSON

🔴 **示例仅展示 JSON 格式与字段语义，禁止沿用示例中的字面字符串**（如 `## 失败处理`、`如遇错误请重试` 等均为占位示意）。下方的 `section` / `evidence` / `before` **必须从上方"SKILL.md 当前内容"里逐字符摘取真实片段**，找不出来的就跳过该条 mod，不要伪造。

```json
{{
  "round": {round_num},
  "diagnosis": {{
    "weakest_dims": ["<从上方 dim_scores 实际挑最低 3 个>"],
    "weakest_sections": [
      {{
        "dim": "<对应 dim 名称>",
        "file": "SKILL.md",
        "section": "<上方 SKILL.md 实际存在的 H2 标题，如 '## 3. 硬约束'>",
        "line_range": [<从 SKILL.md 内容读到的真实行号>],
        "evidence": "<从上方 SKILL.md 内容逐字符复制的真实片段，1~2 行>",
        "root_cause": "<基于真实 evidence 归纳的根因>"
      }}
    ],
    "priority_actions": [
      {{
        "dim": "<对应 dim>",
        "section": "<同上，真实 H2 标题>",
        "pattern_ref": "<对应 P1~P11 或 HL-1~4>",
        "expected_delta": "<+1~+5 整数>"
      }}
    ]
  }},
  "gradient_analysis": {{
    "weakest_dim": "<dim 名>",
    "weakest_section": "<真实 H2 标题>",
    "learning_rate": "<本轮改动幅度定性描述>",
    "momentum": "<与前几轮方向对比>",
    "signal_decomposition": {{
      "<dim 名>": <整数>
    }}
  }},
  "modifications": [
    {{
      "file": "<实际文件名>",
      "section": "<真实 H2 标题或空字符串>",
      "before": "<从 SKILL.md 实际内容逐字符复制的 1~2 行原文，≤ 120 字符，必须在文件中存在>",
      "after": "<新的 1 行或多行内容>",
      "rationale": "<引用 pattern + HL + 真实 evidence>",
      "dim_improved": "<唯一维度>",
      "pattern_used": "<P1~P11 或 HL-1~4>"
    }}
  ],
  "expert_guidance_ref": "已参考用户指引: ...",
  "_checklist": {{
    "no_anti_pattern_hit": true,
    "single_dim_per_mod": true,
    "asset_safe": true,
    "max_mods_respected": true,
    "file_dispatch_respected": true
  }}
}}
"""
    return system, user_prompt


def _format_cross_file_consistency(
    relation_tree: Optional[dict],
    applied_modifications: Optional[list],
) -> str:
    """构造跨文件一致性视图：给 evaluator 列出本轮修改 + 关系树的联动缺口。

    让 evaluator 在 dim6（跨章节一致性）/ dim7（反例）/ dim9（SF）等维度评分时，
    能验证 SKILL.md 的描述是否与 references/scripts/templates 同步。

    Args:
        relation_tree: 关系树（含 edges + reverse_index + clusters）
        applied_modifications: 本轮实际应用的 mods 列表

    Returns:
        注入到 evaluator prompt 的跨文件一致性段（无内容时返回空串）
    """
    if not relation_tree or not applied_modifications:
        return ""

    mod_files = {m.get("file", "") for m in applied_modifications if isinstance(m, dict)}
    mod_files.discard("")
    if not mod_files:
        return ""

    edges = relation_tree.get("edges", []) or []
    reverse_index = relation_tree.get("reverse_index", {}) or []

    # 找出"修改 X 后应当联动改 Y 但 Y 没改"的潜在缺口
    gaps: list[dict] = []
    for e in edges:
        src, dst = e.get("src"), e.get("dst")
        if src in mod_files and dst not in mod_files and dst in {
            f.get("path") for f in relation_tree.get("files", [])
        }:
            gaps.append({
                "src_modified": src,
                "dst_should_check": dst,
                "edge_type": e.get("type"),
                "loc": e.get("loc_src"),
            })
        elif dst in mod_files and src not in mod_files and src in {
            f.get("path") for f in relation_tree.get("files", [])
        }:
            gaps.append({
                "src_should_check": src,
                "dst_modified": dst,
                "edge_type": e.get("type"),
                "loc": e.get("loc_src"),
            })

    lines = [
        "## 跨文件一致性视图（本轮实际修改 + 关系树联动缺口）",
        "",
        f"**本轮修改文件**（{len(mod_files)} 个）：{', '.join(sorted(mod_files))}",
        "",
        "**关系树联动缺口**（修改了 X 但未修改 Y，Y 是 X 的被引用/引用方）：",
    ]
    if not gaps:
        lines.append("  ✅ 无明显联动缺口（修改的文件涵盖了所有相关引用）。")
    else:
        for g in gaps[:10]:
            if "src_modified" in g:
                lines.append(
                    f"  - ⚠️ 改 `{g['src_modified']}` → 应同步检查 `{g['dst_should_check']}`"
                    f"（{g['edge_type']} at line {g['loc']}）"
                )
            else:
                lines.append(
                    f"  - ⚠️ 改 `{g['dst_modified']}` → 应同步检查 `{g['src_should_check']}`"
                    f"（{g['edge_type']} at line {g['loc']}）"
                )

    # 簇内联动缺失
    clusters = relation_tree.get("clusters", []) or []
    lines.append("\n**簇内联动检查**（按引用拓扑聚类）：")
    for c in clusters:
        ctype = c.get("type")
        if ctype in ("contract", "implementation"):
            cluster_files = [f for f in c["files"] if f in mod_files]
            cluster_total = len(c["files"])
            lines.append(
                f"  - {c['name']}: 改了 {len(cluster_files)}/{cluster_total} 个文件"
            )
            uncovered = [f for f in c["files"] if f not in mod_files]
            for u in uncovered[:5]:
                lines.append(
                    f"    - 未改： `{u}`（同簇其他文件改了，请检查是否需要联动）"
                )

    lines.append(
        "\n💡 **评分指引**：dim6/dim7/dim9 等维度评分时，**结合上述联动缺口判断**。"
        "如果 SKILL.md 引用的 references/X 本轮被改、但 SKILL.md 的描述段未同步更新 →"
        "应在 dim6 扣分；如果发现引用闭合不一致、则在 evidence 中标注 file:line。"
    )
    return "\n".join(lines)


def _format_file_coverage_constraint(relation_tree: Optional[dict]) -> str:
    """根据文件数量动态生成文件覆盖约束。

    <5 个文件 → 不激活（太小的 skill 强制覆盖无意义）。
    ≥5 个文件 → 目标导向：每轮至少覆盖 2 个不同文件。
    """
    if not relation_tree:
        return ""
    total = relation_tree.get("stats", {}).get("file_count", 0)
    if total < 5:
        return ""
    return (
        "**🔴 每轮至少覆盖 2 个不同文件**：所有文件（SKILL.md / scripts/* / references/* / templates/*）"
        "都是技能的组成部分。**连续 2 轮只改 1 个文件 → 本轮必须至少覆盖 3 个不同文件**。"
        "参考下方「文件关系树」的 `long_unoptimized` / `orphans` 段优先选取从未改过的文件。"
    )


def _format_per_file_schema_instruction(relation_tree: Optional[dict], max_modifications: int) -> str:
    """强制 LLM 逐文件扫描并输出 per_file_findings 段（≥5 文件激活）。

    强制：LLM 必须为骨架表每个文件输出 findings 数组（即使空 []）。
    缺一个文件 → 框架 REWORK。
    """
    if not relation_tree:
        return ""
    total = relation_tree.get("stats", {}).get("file_count", 0)
    if total < 5:
        return ""
    rows = relation_tree.get("summary_table", [])
    file_list = "\n".join(f"  - F{i+1:02d} `{r['path']}` ({r['role']})" for i, r in enumerate(rows[:max_modifications + 50]))
    return f"""
## 🔴 逐文件扫描契约（per_file_findings，硬约束）

**禁止凭印象决策**——必须为下方 **每个文件** 单独扫描并输出 `findings`（潜在修改点）。
即使没找到任何问题也必须输出 `"findings": []`（空数组），否则本轮 REWORK。

**JSON 输出 schema 新增字段**：
```json
{{
  "round": {max_modifications},
  "diagnosis": {{...}},
  "per_file_findings": [
    {{"file": "SKILL.md", "findings": [
      {{"section": "## 1. 引言", "dim_improved": "dim1", "rationale": "...",
       "before": "...", "after": "...", "pattern_used": "P1"}}
    ]}},
    {{"file": "scripts/insert_flow_content.sh", "findings": [...]}},
    ... // 下方文件列表中每个文件都必须出现
  ],
  "modifications": [...] // 从 per_file_findings 按优先级合并、截断到 ≤ {max_modifications} 条
}}
```

**必须覆盖的文件**（共 {total} 个，与上方骨架表一致；不可遗漏任何一项）：
{file_list}

**合并规则**：从所有 findings 中按 `dim_improved` 优先级（最低 3 维度优先）+ `long_unoptimized` 文件优先合并到 `modifications`，总数 ≤ {max_modifications}。
"""


def _format_relation_tree(relation_tree: Optional[dict], max_rows: int = 50) -> str:
    """构造「文件关系树」注入段：骨架表格 + 关键依赖 + 长期未优化/孤立提示。

    替代原 _format_dispatch_info：给 LLM 全部文件的统一认知（role/大小/引用关系），
    引导优化覆盖到非 SKILL.md 文件，而非只盯着 SKILL.md。

    Args:
        relation_tree: build_relation_tree() 产出的关系树 dict（None/空 → 返回空串）
        max_rows: 骨架表格最多渲染的行数（防 prompt 过长）
    """
    if not relation_tree or not relation_tree.get("summary_table"):
        return ""
    stats = relation_tree.get("stats", {})
    rows = relation_tree["summary_table"]
    lines = [
        f"## 文件关系树（{stats.get('file_count', len(rows))} 个文件，"
        f"{stats.get('edge_count', 0)} 条引用边）",
        "",
        "骨架（每文件 1 行，role 由路径+扩展名推断；这是全部文件的统一视角，"
        "**不要默认只盯 SKILL.md**）：",
        "",
        "| path | role | size | lines | refs_in | refs_out | protected |",
        "|------|------|------|-------|---------|----------|-----------|",
    ]
    for r in rows[:max_rows]:
        lines.append(
            f"| {r['path']} | {r['role']} | {r['size']} | {r['lines']} | "
            f"{r['refs_in']} | {r['refs_out']} | {str(r['protected']).lower()} |"
        )
    if stats.get("truncated"):
        lines.append(
            f"| ...（另有 {stats.get('total_files_scanned', 0) - len(rows)} 个文件未列入，"
            "按 size 取 top）... |"
        )

    # 关键依赖：按 refs_in 降序取 top 5
    rev = relation_tree.get("reverse_index", {})
    hot = sorted(rev.items(), key=lambda kv: -len(kv[1]))[:5]
    if hot:
        lines.append("\n关键依赖（被引用最多的文件）：")
        for dst, srcs in hot:
            locs = ", ".join(f"{s['src']}:{s.get('loc_src', '?')}" for s in srcs[:4])
            lines.append(f"- `{dst}` 被 {len(srcs)} 处引用（{locs}）")

    long_un = relation_tree.get("long_unoptimized", [])
    if long_un:
        lines.append("\n长期未优化（过去各轮从未被改过，本轮请评估是否纳入）：")
        for p in long_un[:10]:
            lines.append(f"- `{p}`")

    orphans = relation_tree.get("orphans", [])
    if orphans:
        lines.append("\n孤立文件（无人引用也不引用他人，检查是否应被 SKILL.md 引用）：")
        for p in orphans[:8]:
            lines.append(f"- `{p}`")

    # 关系簇分组（按引用拓扑聚类，引导 LLM 跨文件联动考虑）
    clusters = relation_tree.get("clusters") or []
    if clusters:
        lines.append(
            "\n## 关系簇分组（按引用拓扑聚类，引导跨文件联动修改）"
        )
        for c in clusters:
            ctype = c.get("type", "mixed")
            emoji = {
                "contract": "📜", "implementation": "⚙️",
                "orphan": "🟡", "mixed": "📦",
            }.get(ctype, "📦")
            lines.append(
                f"\n### {emoji} {c['name']}（{len(c['files'])} 文件，{c.get('edge_count', 0)} 条内部边）"
            )
            for f in c["files"]:
                lines.append(f"  - `{f}`")
        # 簇联动指令（关键）
        lines.append(
            "\n**🔴 簇内联动规则**：\n"
            "- **契约簇**内文件高度耦合：SKILL.md 改了流程描述 → references/ 必须同步更新，"
            "否则触发 dim6 跨章节一致性扣分。\n"
            "- **实现簇**内脚本相互调用：scripts/x.sh 加了参数 → 调它的 scripts/y.sh 也要同步检查。\n"
            "- 修改任一文件时，**主动检查同簇其他文件是否需要同步 mod**，避免孤岛修改。"
        )

    lines.append(
        "\n🔴 **注意**：上表是骨架，附属文件正文仅注入首尾摘要（非全文）。"
        "对 `line_count > 50` 或大文件，改动前**必须先用 Read 工具读真实文件**，"
        "确认目标段落存在且 `before` 是文件中唯一匹配片段（否则 apply 阶段匹配失败，本轮 mod 作废）。"
    )
    return "\n".join(lines)


def _format_revise_signals(revise_signals: Optional[dict]) -> str:
    """ Top 3：构造 REVISE 信号注入段（避免重复上轮失败）。

    Args:
        revise_signals: {applied_mods, failed_mods, dim_improvements, warnings}
    """
    if not revise_signals:
        return ""
    applied = revise_signals.get("applied_mods") or []
    failed = revise_signals.get("failed_mods") or []
    dim_improvements = revise_signals.get("dim_improvements") or {}
    warnings = revise_signals.get("warnings") or []
    file_coverage = revise_signals.get("file_coverage_warning", {}) or {}

    lines = ["## 上一轮 REVISE 信号（避开重复错误）", ""]

    # 文件覆盖警告（如仅改 1 个文件）
    coverage_msg = file_coverage.get("warning_msg", "") if isinstance(file_coverage, dict) else ""
    if coverage_msg:
        lines.append(f"### 文件覆盖提示\n{coverage_msg}\n")
    if applied:
        lines.append("**已成功应用的改动**（不要重复，可叠加扩展）：")
        for m in applied[:5]:
            lines.append(f"  - {m}")
        lines.append("")
    if failed:
        lines.append("**失败的改动**（不要重蹈覆辙，绕开同样模式）：")
        for f in failed[:5]:
            lines.append(f"  - {f}")
        lines.append("")
    if dim_improvements:
        #  v15+：regressed 按 |delta| 分级(严重/中度/轻度),严重退化用醒目强引导
        regressed = {k: v for k, v in dim_improvements.items() if v < 0}
        improved = {k: v for k, v in dim_improvements.items() if v > 0}
        if regressed:
            severe = {k: v for k, v in regressed.items() if v <= -2.0}
            moderate = {k: v for k, v in regressed.items() if -2.0 < v <= -1.0}
            mild = {k: v for k, v in regressed.items() if -1.0 < v < 0}
            # 顶部强引导:严重退化必须本轮修复
            if severe:
                lines.append(
                    f"**🚨 严重退化预警**：上一轮有 {len(severe)} 个维度大幅下滑 "
                    f"(|Δ| ≥ 2.0),这些维度是上轮总分的最大扣分源。**本轮必须用至少 1 条 mod "
                    f"专门修复,目标本轮 dim_score ≥ baseline+1.0**。忽略此预警会导致下轮 "
                    f"P6 评分回退触发 snapshot 恢复。"
                )
                lines.append("")
                lines.append("**🔴🔴 严重退化(|Δ| ≥ 2.0,本轮必修复)**")
                for k, v in sorted(severe.items(), key=lambda x: x[1]):
                    lines.append(
                        f"  - {k}: {v:+.2f}  ← **必须修复,目标本轮 ≥ baseline+1.0**"
                    )
                lines.append("")
            if moderate:
                lines.append("**🔴 中度退化(1.0 ≤ |Δ| < 2.0,本轮建议修复)**")
                for k, v in sorted(moderate.items(), key=lambda x: x[1]):
                    lines.append(f"  - {k}: {v:+.2f}  ← 至少 1 条 mod 覆盖")
                lines.append("")
            if mild:
                lines.append("**🟡 轻微退化(|Δ| < 1.0,可选)**")
                for k, v in sorted(mild.items(), key=lambda x: x[1]):
                    lines.append(f"  - {k}: {v:+.2f}")
                lines.append("")
        if improved:
            lines.append("**已提升维度(可继续扩展,非必须)**")
            for k, v in improved.items():
                lines.append(f"  - {k}: +{v:.2f}")
            lines.append("")
        if regressed:
            lines.append(
                f"**本轮 soft target**:`{', '.join(regressed.keys())}` "
                f"—— 每轮优先恢复这 {len(regressed)} 个 regressed 维度。"
            )
            lines.append("")
    if warnings:
        lines.append("**警告**（来自 P4 verifier）：")
        for w in warnings[:5]:
            lines.append(f"  - {w}")
        lines.append("")
    return "\n".join(lines)


def _format_overfit_signals(overfit_signals: Optional[dict]) -> str:
    """ P1-B：构造 overfit 反馈闭环段（warn-only 注入）。

    Args:
        overfit_signals: {warning: bool, count: int, last_round_reasons: list[str]}
                         来自 P4 verifier 的 check_overfit 检测结果
    """
    if not overfit_signals or not overfit_signals.get("warning"):
        return ""
    count = overfit_signals.get("count", 0)
    reasons = overfit_signals.get("last_round_reasons") or []

    lines = [
        "## 上一轮 overfit 警告（ 新增，warn-only 反馈）",
        "",
        f"⚠️ 上轮检测到 **{count} 条 overfit 特征**（软改/比例极端/单 dim 冗余），"
        "本次必须避开以下模式：",
    ]
    for r in reasons[:5]:
        lines.append(f"  - {r}")
    lines.append("")
    lines.append(
        "**应对策略**：把改动做成有信息增量的硬改（具体 step / 数字阈值 / "
        "完整失败分支），避免纯加句子的 dim 提升；减少单 dim 的改动数；"
        "确保 before/after 字符比例在 [0.5, 1.5] 区间。"
    )
    return "\n".join(lines)


def _format_apply_failure_signals(apply_failure_signals: Optional[list]) -> str:
    """ P2-A：构造 apply 失败根因注入段。

    Args:
        apply_failure_signals: list[str] 上轮 apply 失败的根因列表
                               (如 "找不到 before 文本"、"命中白名单"等)
    """
    if not apply_failure_signals:
        return ""
    lines = [
        "## 上一轮 apply 失败根因（ 新增，让 LLM 知道为什么 mods 没生效）",
        "",
        f"⚠️ 上轮有 **{len(apply_failure_signals)} 条 mod 应用失败**，原因如下：",
    ]
    for err in apply_failure_signals[:5]:
        lines.append(f"  - {err}")
    lines.append("")
    lines.append(
        "**应对策略**：本次生成 modifications 时，必须确保 before 字段"
        "是目标文件中完整逐字存在的段落（可短不可长）；"
        "如果不确定原文，应先用 Read 工具确认，避免再次失败。"
    )
    return "\n".join(lines)


def _build_syntax_fix_prompt(
    file_path: str,
    file_content: str,
    errors: list[str],
    original_rationale: str = "",
) -> str:
    """fix_attempt 专用 prompt：只修复单文件 Python 语法错误，不动其他逻辑。

    Args:
        file_path: 出错文件相对路径（如 "script/interface_translate.py"）
        file_content: 文件完整内容（含语法错误）
        errors: 错误列表，每条 "{file}:L{lineno} {msg}"
        original_rationale: 上轮该文件的 modification 意图（保留语义用）
    """
    errors_text = "\n".join(f"  - {e}" for e in errors[:5])
    rationale_text = (
        f"\n## 原 modification 意图（请在修复时保留语义）\n{original_rationale}\n"
        if original_rationale else ""
    )
    err_summary = errors[0] if errors else "unknown"
    return f"""## 任务
修复 {file_path} 的 Python 语法错误（**只修语法，不动其他逻辑**）。

## 错误详情
{errors_text}

## 当前文件内容（含语法错误，逐字符复制为 before）
```python
{file_content}
```
{rationale_text}
## 硬约束（违反则修复失败）
1. **只修复语法错误**：不要修改其他逻辑、不要新增功能、不要删除非错误行
2. **before 必须是文件完整内容**：把 `before` 字段设为上述"当前文件内容"全文（逐字符复制）
3. **after 必须是修复后的完整文件内容**：保持所有原有 import / 函数 / 注释 / 空行
4. **保留原 modification 意图**：修复后文件应仍能实现原 rationale 描述的功能
5. **after 必须是合法 Python**：用 `python3 -c "import ast; ast.parse(after)"` 自检，必须通过

## 输出 JSON schema（严格，无 markdown 包裹）
```json
{{
  "file": "{file_path}",
  "before": "<文件完整原文，逐字符复制>",
  "after": "<修复后文件完整内容>",
  "rationale": "修复 SyntaxError: {err_summary}"
}}
"""


def build_unified_prompt(
    skill_content: str,
    target_files_content: list[tuple[str, str]],
    expert_guidance: str,
    rubric: dict,
    relation_tree: Optional[dict],
    round_num: int = 1,
) -> tuple[str, str]:
    """构造 unified agent 的 prompt（融合评分 + 优化）。

    替代原 build_optimizer_prompt + build_evaluator_prompt。
    单次 LLM 调用 = 同时输出每个文件的 dim_scores（带 rationale） + findings（mods）。

    Args:
        skill_content: SKILL.md 全文
        target_files_content: [(path, content), ...] 附属文件首尾摘要
        expert_guidance: 用户自然语言指引
        rubric: framework YAML 的 rubric 段（含 dim_weights）
        relation_tree: 关系树（含 files / edges / clusters / long_unoptimized）
        round_num: 当前轮次

    Returns:
        (system, user_prompt) 元组
    """
    rubric_text = _format_rubric(rubric)
    # 每个 role 适用 dim 的完整评分定义（含 criteria/anti_criteria/scoring_rubric）
    dim_definitions = _format_dim_definitions_per_role(rubric)
    files_text = "\n\n".join(
        f"### 附属文件: {path}\n```\n{content}\n```"
        for path, content in target_files_content
    ) or "（无附属文件）"
    relation_section = _format_relation_tree(relation_tree)
    file_list_text = ""
    if relation_tree:
        rows = relation_tree.get("summary_table", [])
        file_list_text = "\n".join(
            f"  - F{i+1:02d} `{r['path']}` ({r['role']}, size={r['size']}, lines={r['lines']})"
            for i, r in enumerate(rows)
        )

    system = (
        "你是 skill 评分与优化融合的统一 agent。"
        "对每个文件给一个 0-10 综合分 + 理由，并给出本轮要改的 mods。"
        "Python 端按文件权重做分数聚合 + mod 应用 + 触顶 break。"
    )

    user_prompt = f"""## 用户指引（最高优先级）
{expert_guidance or "（无）"}

## 任务
基于 round={round_num} 的评分上下文，**对骨架表每个文件输出完整 12 个 dim 分数**：
- **每个 entry 必须含全部 12 个 dim_scores**（与旧版只填 role 适用 dim 的规则相反——dim 适用映射仅作"分数倾向"参考,所有 dim 都要打）。
  不全 → 框架触发 REWORK 重试。
- **禁止同质化**：12 个 dim 中至少 4 个分数互不相同（避免"全部 8 分"扁平化）。
  差异化依据:
  - 该 dim 的 criteria 是否在文件中得到满足
  - 该 dim 的 anti_criteria 是否被命中
  - 不同 dim 评分侧重点不同（dim1 frontmatter, dim3 错误处理, dim5 措辞...）
- 每个 dim 评分参考下方「各 role 对应 dim 的完整评分定义」中的标准/反例/档位
- **role 适用映射参考**（用于决定哪个 dim 应该给高分,而非筛选哪些 dim 输出）:
  - entrypoint（SKILL.md）→ 推荐高分:dim1/dim2/dim6/dim7/dim8/dim12
  - implementation（scripts/*）→ 推荐高分:dim2/dim3/dim4/dim5/dim7/dim10/dim11
  - knowledge（references/*）→ 推荐高分:dim5/dim6/dim7/dim9/dim12
  - template（templates/*）→ 推荐高分:dim5/dim6/dim8/dim9
  - non-适用 dim 给 8~10 分并在 rationale 中标注"不涉及"
- **dim_scores 输出要求**：每个 dim 的 rationale 中必须引用评分标准中的具体条目
  （如"依据 criteria：5-7 条标准满足 xx；未命中反例 AP1；符合档位 8 分"）
- `findings`：本轮要改的 mods（无问题可空 `[]`）

⚠️ **每 entry 必须含完整 12 维 dim_scores**。不全 → 框架触发 REWORK。

## 各 role 对应 dim 的完整评分定义（打分必读）
{dim_definitions or "（无）"}

## 关系树骨架表（必须覆盖每个文件）
{file_list_text or "（无）"}

## 关系树详情（簇内联动 + long_unoptimized + orphans）
{relation_section or "（无）"}

## 评分 rubric 定义（每 dim 适用映射+评分标准+反例+档位，按下面映射给 dim_scores 打分）
{rubric_text or "（无）"}

## SKILL.md 当前内容（{len(skill_content)} 字符）
```
{skill_content}
```

## 附属文件（首尾摘要，非全文；改前按需 Read 真实文件）
{files_text}

## 输出 JSON schema（严格，第一字符 {{，最后字符 }}）

**dim_scores 内每个 dim 的 rationale 必须引用评分标准中的具体条目**，
如「依据 criteria：5-7 条标准满足 X 条；未命中反例 AP1/AP2；符合档位 8 分」。
这样 per_file_findings JSON 独立可查阅，无需回看 rubric 原文。

```json
{{
  "round": {round_num},
  "diagnosis": "<高层面观察：本轮重点改什么>",
  "per_file_findings": [
    {{
      "file": "SKILL.md",
      "dim_scores": {{
        "dim1_metadata_trigger": {{"score": 8, "rationale": "依据 criteria：name+description 有但缺触发词；未命中 AP1/AP2；档位 8 分（大部分 criteria + ≤1 处 anti）"}},
        "dim2_step_executability": {{"score": 9, "rationale": "依据 criteria：步骤清晰、命令含完整参数、流程闭环；无 AP4/AP5；档位 8 分"}},
        "dim6_cross_section_consistency": {{"score": 7, "rationale": "依据 criteria：引用基本闭合但有一个模板路径不匹配；无 AP10；档位 6 分"}}
      }},
      "findings": [
        {{"section": "## 3. 硬约束", "before": "...", "after": "...",
         "dim_improved": "dim3", "pattern_used": "HL-2", "rationale": "..."}}
      ]
    }},
    {{
      "file": "scripts/x.sh",
      "dim_scores": {{
        "dim3_failure_recovery": {{"score": 10, "rationale": "依据 criteria：含 3 类失败处理+三段式+STOP 标记；无 AP6；档位 10 分"}},
        "dim5_specificity": {{"score": 9, "rationale": "依据 criteria：参数明确无软化词；挡位 8 分"}}
      }},
      "findings": []
    }},
    {{
      "file": "references/yyy.md",
      "dim_scores": {{
        "dim5_specificity": {{"score": 10, "rationale": "依据档位 10：不涉及——本 skill 不引用此文件，自动 10 分"}}
      }}
    }}
  ]
}}
```

## dim 适用映射（每个 entry 只填该文件 role 适用的 dim，不要全填 12 个）
- entrypoint（SKILL.md）→ dim1/dim2/dim6/dim7/dim8/dim12
- implementation（scripts/）→ dim2/dim3/dim4/dim5/dim7/dim10/dim11
- knowledge（references/）→ dim5/dim6/dim7/dim9/dim12
- template（templates/）→ dim5/dim6/dim8/dim9

## 硬约束（违反 REWORK）
1. per_file_findings 数量 = 骨架表文件数（缺一个 → REWORK）
2. **每个 entry 必须含完整 12 个 dim_scores**（不全 → REWORK）
3. **禁止同质化**：12 个 dim 中至少 4 个分数互不相同
4. dim_scores 内每个 dim: score (0-10) + rationale（**必须引用评分标准中的 criteria/anti_criteria/档位**）
5. findings 中的 before 必须真实存在于目标文件（按需 Read）
6. after/before 长度比 ∈ [0.2, 5.0]
7. 单条 modification 不超过 5000 字符
8. 不命中 8 条 darwin 自操作反例

## 簇内联动
- 改 SKILL.md 时检查 references/ 是否需要同步（避免 dim6 扣分）
- 改 scripts/x.sh 时检查调用它的 scripts/y.sh 是否需要同步

**严格遵守**：第一字符 `{{`，最后字符 `}}`，中间无 markdown 包裹。
"""
    return system, user_prompt
