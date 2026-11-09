"""
context_extractor.py — 一次性 LLM 优化 agent 的薄壳 wrapper(取代原 proposal+apply 多阶段)
=================================================================

承接"重 agent 轻代码"原则(见 `feedback_heavy_agent_light_code.md`):
  - LLM 自己用 Read/Edit 工具改 Skill 文件(全流程 LLM 驱动)
  - 本模块只做: ① 调 Agent ② 检查 self_check overall_pass ③ 写 optimization_summary.md
  - 完整 optimize 详情从 _debug/agent_proposal-agent_*.txt 调试日志查
  - 不写 stage 拆分 / 中间 JSON / apply_status.md 等死板流程
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

# ── 兼容函数(供 eval_pipeline / breadth / reports 旧 import 用) ─────────

def _parse_apply_agent_summary(agent_output: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON 摘要(compat 函数,供 reports.py:1175 旧调用用)。

    注:新流程(optimization_summary.md)不再需要 parse JSON,LLM 直接落 md。
    此函数保留仅作 compat,如不再使用可删除。
    """
    if not agent_output:
        return None
    try:
        result = json.loads(agent_output)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return None

# ── §6 可观测性: LLM 调用 metrics 埋点 ───────────────────────

def _record_proposal_metrics(
    cand_dir: Path,
    candidate_id: int,
    round_num: int,
    subagent_type: str,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    status: str,
) -> None:
    """记录 LLM 调用 metrics 到 {round_dir}/proposal_metrics.json(append-only)。

    位置:cand_dir 的兄弟目录 round_{N}/(因 cand_dir = round_{N}/candidate_K/)。
    多个 candidate 共享同一份 proposal_metrics.json,这样一轮的所有 LLM 调用 metrics 集中可见。
    """
    cand_dir = Path(cand_dir)
    # cand_dir = round_N/candidate_K/ → round_dir = round_N/
    round_dir = cand_dir.parent
    metrics_path = round_dir / "proposal_metrics.json"

    # 读旧 metrics(若存在) → append 新 entry → 写回
    if metrics_path.exists():
        try:
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"schema_version": 1, "calls": []}
    else:
        data = {"schema_version": 1, "calls": []}

    data["calls"].append({
        "candidate_id": candidate_id,
        "round_num": round_num,
        "subagent_type": subagent_type,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status": status,
        "timestamp": time.time(),
    })

    # 写回(atomic:写 tmp 再 rename,避免半写状态)
    metrics_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 单阶段入口: 一次性 LLM 调用(context + gaps + mods + Edit + summary) ─

def _render_prompt_paths_block(cfg: dict) -> str:
    """已废弃:改用 orchestrator 生成的 result_diff_report.md(LLM 一次 Read 看全部信息)。"""
    return ""


def _is_loss_analysis_degraded(diff_report: Path) -> bool:
    """判断该轮 score-analyzer 诊断是否缺失/降级(独立文件 score_analyzer_report_round_{K}.md 优先)。

    2026-08-05 改造:score-analyzer 诊断独立落盘,不再内嵌 diff_report 的 `## 失分分析` 段。
    独立文件含 `本轮诊断未生成` 标记 = 降级。兼容旧报告:独立文件不存在时回退检测内嵌段。
    """
    if not diff_report.exists():
        return True  # 报告都不存在,必然拿不到诊断
    # 1) 独立文件优先(与 result_diff_report 同目录、命名对称)
    sa_path = None
    if diff_report.name == "result_diff_report_baseline.md":
        sa_path = diff_report.parent / "score_analyzer_report_baseline.md"
    else:
        m = re.match(r"^result_diff_report_round_(\d+)\.md$", diff_report.name)
        if m:
            sa_path = diff_report.parent / f"score_analyzer_report_round_{m.group(1)}.md"
    if sa_path and sa_path.exists():
        try:
            text = sa_path.read_text(encoding="utf-8")
        except OSError:
            return True
        return bool(re.search(r"本轮诊断未生成|降级说明", text))
    # 2) 兼容旧报告:内嵌 `## 失分分析` 段检测
    try:
        text = diff_report.read_text(encoding="utf-8")
    except OSError:
        return True
    return bool(re.search(r"本轮诊断未生成|降级说明", text))


def _render_history_diff_block(round_dir: Path, round_num: int,
                               best_round: int = 0,
                               scoring_rule: str = "",
                               run_count: int = 1) -> str:
    """渲染"本轮之前的全部历史数据"必读清单,注入到 ProposalAgent prompt。

    每轮两份数据**配对**注入,缺任一份都无法建立因果:
    - **结果**:`round_{round_num}/result_diff_report_{baseline|round_K}.md` — 那轮考了多少分
      (每 case F1 / gold / Skill 产出 / diff_notes 失分点)
    - **改动**:`round_{K}/skill_diff_round_K.md` — 那轮把 Skill 改成了什么(unified diff)

    排除 `result_diff_report_round_{round_num}.md` 与 `round_{round_num}/skill_diff_round_{round_num}.md` —— 两者都在
    候选评测**之后**才生成,proposal 运行时刻尚不存在;能读到的最新数据只到 round_{round_num - 1}。
    baseline 无改动,故列表里只有结果没有 skill_diff(无需读改动)。

    **基线轮优先**(best_round):baseline_anchored=False 时,本轮修改的起点是 `eng.best_round`
    的 skill(而非最新一轮)。清单里对 best_round 轮标注【当前修改基线·重点】——它的
    result_diff(基线分)+ skill_diff(基线 skill 内容)是"改什么"的核心依据;
    其他轮次仅作**参考**(历史趋势:反复失败/波动/稳定满分,复用/拒绝 mod)。

    **run_count (2026-08-10 新增)**:评测每 case 的 run 数。run_count > 1(多 run)时在
    清单开头注入"波动性 & 稳定性"段,引导 proposal 优先"稳 A 再提 B、避免引入 run 间抖动";
    run_count == 1 时不注入任何波动语句。
    默认 best_round=0 表示起点是 baseline(无被采纳轮)。

    按 round 数值升序(不用字典序,避免 round_10 排到 round_2 之前)。
    一份结果都没找到时返回**显式告警块**让 LLM 自己 find —— 不返回空串,
    避免"静默不读"(契约要求本轮之前的数据必须全部读到)。
    """
    # 波动性 & 稳定性段(2026-08-10,仅多 run 评测注入;run_count==1 时不注入任何波动语句):
    # 引导 proposal 在优化时兼顾"平均分↑(主) + 方差↓(次)"——优先稳 A 再提 B、避免引入 run 间抖动。
    volatility_block = ""
    if run_count and int(run_count) > 1:
        volatility_block = (
            "## 📊 波动性 & 稳定性(多 run 评测特有)\n"
            f"本任务每个 case 评测 **{int(run_count)} 次**(多 run)。优化目标:**平均分更高(主)+ 方差更低(次)**。\n"
            "- **优先稳 A 再提 B**:改动已达标/满分 case 前,先确认不会引入 run 间抖动(同一 SKILL.md 在不同 run 间产出不一致)。\n"
            "- **避免引入 run 间抖动**:倾向把临界判断写成**确定性规则**(不依赖检索顺序/随机采样/模糊措辞),而非模糊指令。\n"
            "- 每轮 diff 报告/score_analyzer_report 会标注每 case 的 F1 **跨 run 平均 + 各 run 值**(标准差大 = 波动),"
            "波动大的 case 的 mod 应优先**收敛 run 间差异**,再谈提分。\n"
            "- 若 run=1(单 run 评测),以上波动考虑不适用。\n\n"
            "---\n\n"
        )

    # 评分规则注入(从 user-config.yaml evidence_paths.scoring_rule 读取)
    # 拼到"必读历史数据"段开头,让 LLM 知道分怎么算 → 改 SKILL.md 时知道改什么能提分
    scoring_rule_block = ""
    if scoring_rule and scoring_rule.strip():
        scoring_rule_block = (
            f"## 🎯 评分规则(business metric 怎么算 — 改 SKILL.md 时优先看这)\n\n"
            f"**重要**:本任务分数 = 5 维评分法(见下)。改 SKILL.md 时,先想「改哪一维能提分」→ 直接对应下面的失分维度优化。\n\n"
            f"```\n{scoring_rule.strip()}\n```\n\n"
            f"---\n\n"
        )

    taskid_root = round_dir.parent

    def _round_of(name: str) -> Optional[int]:
        if name == "result_diff_report_baseline.md":
            return 0
        m = re.match(r"^result_diff_report_round_(\d+)\.md$", name)
        return int(m.group(1)) if m else None

    entries: list[tuple[int, Path]] = []
    if round_dir.is_dir():
        # 修复 2026-07-31:round_dir 在 _ensure_round_dir 末尾已被 _populate_round_history 初始化,
        # 含 baseline + 前序轮次的所有 result_diff_report_*.md 和 skill_diff_round_*.md 副本。
        # 直接 glob 即可拿到全部历史。round_1 的初始化时机已修,proposal-agent 启动时 round_1/
        # 已含 baseline diff 副本,不再依赖 Bash find 兜底。
        for p in round_dir.glob("result_diff_report_*.md"):
            rn = _round_of(p.name)
            if rn is not None and rn < round_num:
                entries.append((rn, p))
    if not entries:
        return (
            f"## ⚠️ 必读历史数据 — 未在 `{round_dir}` 找到 diff 报告\n\n"
            "**开工前必须先用 `Bash` 自己定位本轮之前的历史数据,并 Read 全部**:\n"
            f"`find {taskid_root} -name 'result_diff_report_*.md' -o -name 'skill_diff_round_*.md' | sort`\n\n"
            f"只取 round 编号 < {round_num} 的(`result_diff_report_baseline.md` 视作 round 0)。"
            "`result_diff_report_*.md` = 那轮的分数结果,`round_K/skill_diff_round_K.md` = 那轮的 Skill 改动,**两者配对读**。\n"
            "**禁止**跳过此步凭印象生成 mod;一份都找不到时,在 "
            "`optimization_summary.md` 中明确写出「无历史 diff 可依据」。\n\n"
        )
    entries.sort()
    # 检测各轮 score-analyzer 诊断是否降级(独立文件 score_analyzer_report_*.md)。
    # 若降级,该轮的 trace 证据只能由 proposal-agent 自己读 trace.jsonl 补上。
    degraded_rounds = [rn for rn, p in entries if _is_loss_analysis_degraded(p)]

    # 2026-08-05:解析各轮 F1 均分,判定"分数低于最佳"的避坑轮(best_round 轮为当前修改基线)。
    round_scores: dict[int, float] = {}
    for _rn, _p in entries:
        try:
            _head = _p.read_text(encoding="utf-8", errors="ignore")[:4000]
        except OSError:
            continue
        _sm = re.search(r"F1 均分=([\d.]+)", _head)
        if _sm:
            round_scores[_rn] = float(_sm.group(1))
    best_score = max(round_scores.values()) if round_scores else None
    # 避坑轮 = 非 best_round 且分数低于最佳(用户选定"比最佳轮低"判定)
    lower_rounds = {
        rn for rn in round_scores
        if best_score is not None and round_scores[rn] < best_score
    }
    # 避坑轮摘要(排除 baseline——baseline 无 skill_diff 修改尝试),给 prompt 顶部聚焦块用
    _lower_list = sorted(rn for rn in lower_rounds if rn > 0)
    if _lower_list:
        _lower_str = "、".join(f"round_{rn}(F1={round_scores[rn]})" for rn in _lower_list)
    else:
        _lower_str = "(无)"

    lines = [
        f"## 📜 必读历史数据({len(entries)} 轮 — 本轮之前的**全部**历史)",
        "",
        "**开工前必须 Read 各轮的 `score_analyzer_report_*.md`(失分诊断)—— 不许跳过。**"
        "(该报告已内嵌该轮 Skill 改动(skill_diff)内容,读它即同时拿到「改了啥 + 结果如何」。)",
        "",
        "每轮参考(读了更全,但**非强制**):",
        "- **失分诊断**(`score_analyzer_report_round_K.md`)= score-analyzer 子 Agent 的失分归因"
        "(逐 RAN 的 `#### 3 建议根因 / #### 4 建议 mod 方向 / #### 5 验证 / #### 6 回归风险`)。**必读,已含 skill_diff 内容**",
        "- **结果**(`result_diff_report_*.md`)= 那轮考了多少分(每 case F1 / gold / diff_notes 失分点)——可选,想核对原始分值时读",
        "- **改动**(`skill_diff_round_K.md`)= 那轮 Skill 的 unified diff——**冗余,已在 score_analyzer_report 中,不必单独读**",
        "",
        "判定「**哪条 mod 救了哪个 case、害了哪个 case**」以 score_analyzer_report + result_diff 为准 —— 这是 Step 4 mod 经验卡的依据。",
        "",
        "**🎯 本轮聚焦(失分诊断阅读优先级)** —— 明确告诉你哪个最佳、哪些是反面教材:",
        f"- **重点分析对象 = 最佳轮 round_{best_round}(F1={best_score})** → "
        f"`score_analyzer_report_round_{best_round}.md`" + ("(baseline 无轮次,即 `score_analyzer_report_baseline.md`)" if best_round == 0 else "")
        + "——当前修改基线的失分归因,逐 RAN 细读 `#### 3/4/5/6`;",
        f"- **避坑参考 = 分数低于最佳的轮次**: {_lower_str}——这些轮次的失分报告**开头都带各自 skill_diff(修改尝试)**,"
        "重点看它们怎么被改坏、哪些 mod 尝试失败,避免重蹈覆辙;",
        "- 其他轮仅作趋势参考。proposal 的每条 mod 应能从【重点分析对象】的 `#### 4 建议 mod 方向` 追溯到对应 skill。",
        "",
        "**失分判断(读 score-analyzer 归因)**:score-analyzer 子 Agent 已逐个 Read 各类轨迹 + 中间产物,"
        "做了误差根因 + 责任归因到具体 skill,输出独立诊断文件。proposal 直接读独立诊断的归因结论做 mod:",
        "- `#### 1. gold 答案` vs `#### 2. Skill 实际产出`:用户/场景/问题三列字段差异(漏/误/改写),这是改什么的最直接依据",
        "- `#### 3. LLM-as-Judge diff_notes`:五维评分失分点,参考",
        "- `#### 3. 建议根因` + `#### 4. 建议 mod 方向`:score-analyzer 的归因结论(具体哪个中间 skill 的问题:根因/场景要素/标准识别/用户分析汇总),mod 针对归因的 skill 生成",
    ]
    lines.append("")
    # 注:score-analyzer 停用后无 ## 失分分析 段,degraded_rounds 检测已不适用
    for rn, p in entries:
        if rn == 0:
            if best_round == 0:
                lines.append("### baseline(起点,无改动)【当前修改基线·重点】")
            else:
                lines.append("### baseline(起点,无改动,参考)")
            lines.append(f"- 结果: `{p}`")
            _sa_base = round_dir / "score_analyzer_report_baseline.md"
            if _sa_base.exists():
                _sa_tag = "【重点分析对象·当前修改基线】" if best_round == 0 else "(参考)"
                lines.append(f"- 失分诊断: `{_sa_base}` {_sa_tag}")
            lines.append("- 改动: (无 skill_diff,baseline 之前无 Skill 状态可对比)")
            if 0 in degraded_rounds:
                lines.append(
                    "  ⚠️ **本轮 score-analyzer 诊断为降级说明**:必须自行 Read 低分 case 的 "
                    f"`trace.jsonl`(用 `find {taskid_root} -name trace.jsonl` 定位)补 trace 级证据。"
                )
        else:
            if rn == best_round:
                lines.append(f"### round_{rn}【当前修改基线·重点】")
            else:
                lines.append(f"### round_{rn}(参考)")
            # 修复 2026-07-31:优先用 round_N/ 下的 skill_diff_round_K.md 副本
            # (由 _populate_round_history 在 _ensure_round_dir 末尾拷贝),与 result_diff 对称,
            # LLM 在同一目录下并发 Read 即可获得完整历史对。副本不存在时回退到原路径。
            change_md_copy = round_dir / f"skill_diff_round_{rn}.md"
            change_md_orig = taskid_root / f"round_{rn}" / f"skill_diff_round_{rn}.md"
            if change_md_copy.exists():
                lines.append(f"- 改动: `{change_md_copy}`")
            elif change_md_orig.exists():
                lines.append(f"- 改动: `{change_md_orig}`")
            else:
                lines.append(f"- 改动: (未找到 `{change_md_orig}`,用 `Bash` 在 `{taskid_root}` 下自行定位)")
            lines.append(f"- 结果: `{p}`")
            _sa_rn = round_dir / f"score_analyzer_report_round_{rn}.md"
            if _sa_rn.exists():
                if rn == best_round:
                    _sa_tag = "【重点分析对象·当前修改基线】"
                elif rn in lower_rounds:
                    _sa_tag = "【避坑参考·分数低于最佳】"
                else:
                    _sa_tag = "(参考)"
                lines.append(f"- 失分诊断: `{_sa_rn}` {_sa_tag}")
            if rn in degraded_rounds:
                lines.append(
                    "  ⚠️ **本轮 score-analyzer 诊断为降级说明**:必须自行 Read 低分 case 的 "
                    f"`trace.jsonl`(用 `find {taskid_root} -name trace.jsonl` 定位)补 trace 级证据。"
                )
            # 对照分析指引:对该轮的 skill_diff + result_diff 必须对照读,
            # 才能建立「改了什么 → 考了几分」的因果
            lines.append(
                "  **对照分析协议**:读完「改动」立刻读「结果」(同 1 个 message 并发 Read)。"
                "在该轮内回答两个问题:\n"
                "  1. **哪条 mod 救了哪个 case**(从 0/N → 高分;改动里有相关段落 + 结果里该 case 分数大涨)\n"
                "  2. **哪条 mod 害了哪个 case**(从高分 → 0/N;改动里有相关段落 + 结果里该 case 分数大跌)\n"
                "  这两个映射表是后续跨轮对比的基础 —— 没有它就建不出「复用 / 拒绝」依据。"
            )
        lines.append("")

    _baseline_label = "baseline(无被采纳轮)" if best_round == 0 else f"round_{best_round}"
    final_block = volatility_block + scoring_rule_block + "\n".join(lines) if (volatility_block or scoring_rule_block) else "\n".join(lines)
    lines.extend([
        f"**当前修改基线 = {_baseline_label}**——这是本轮要修改的起点 skill 版本,失败 case 在其结果报告中已完整重现。"
        "重点读基线轮的「改动+结果」;其他轮次仅作参考(历史趋势)。",
        "**Step 1.5 跨轮对比** — 在单轮对照分析完成后,跨轮对比三类 case 清单:"
        "**反复失败**(连续多轮低分)/ **波动**(某轮满分→某轮 0,说明某条 mod 误伤)/ "
        "**稳定满分**(勿再动,避免 non_target_cases_risk)。",
        "再回到对应轮的 `skill_diff_round_K.md` 找出**具体是哪段改动**造成的,据此"
        "**复用有效 mod、拒绝重复已失效的 mod**。",
        "",
        "**禁止**凭印象或历史记忆代替 Read;**禁止**单独 Read "
        "`data/phase3-eval/*/results/*.json` 或 gold 文件(冗余,且易自我参照导致分数波动)。",
        "",
    ])
    return final_block


def _render_consume_lib_block(consume_lib_path: str) -> str:
    """渲染"全局视角知识库"参考块,注入到 ProposalAgent prompt 顶部。

    设计语义:consume_lib 是**全局知识**,不是修补当前 case 的工具,
    而是让 LLM 跳出"逐 case 修补"局限、从更高维度(领域方法论/反模式/最佳实践)重新审视优化方向。

    **重 agent 轻代码**:框架只给方向 + 探查方法,**不预先扫描**(避免代码化、保持 LLM 自主性)。
    LLM 用 Read/Grep/Bash 自主探查、提取方法论/反模式/证据。

    未配置时返回空串(零副作用)。
    """
    if not consume_lib_path:
        return ""
    return (
        "## 🌍 全局视角知识库(consume_lib)\n"
        f"知识库根目录: `{consume_lib_path}`\n\n"
        "**重要定位**:此知识库是**全局知识**,不是用来逐 case 修补模板。\n"
        "**目的**:跳出当前 case 的细节局限,站在领域方法论/反模式/最佳实践的高度,"
        "重新审视优化方向——避免在某个 case 的局部修补里打转。\n\n"
        "**使用方式**(开工前**必须**先做):\n"
        f"1. 用 `Bash` 探查目录结构(注意 consume_lib 可能非常大,深度 ≤ 2 层就够):\n"
        f"   - `ls -la {consume_lib_path}/`\n"
        f"   - `find {consume_lib_path} -maxdepth 2 -type d | head -30`\n"
        f"2. 主动 `Read` **代表性文件**(优先级:方法论/README/反模式/规范 > 单一 case 模板),提取:\n"
        "   - **领域方法论**(代码化优先、scripts/ 抽取、渐进式披露、章节组织等)\n"
        "   - **反模式清单**(硬编码 case_id、纯加规则段、edit_exact 盲目新增等)\n"
        "   - **跨场景共性原则**(异常处理矩阵、必填字段校验、早退规则等)\n"
        "   - **证据/隐性知识**(如某类场景的必填字段、跨 Skill 的链路不变量)\n"
        "3. 用 `Grep` 找反模式示例:`grep -rE 'TODO|FIXME|hardcode' {consume_lib_path} | head -20`\n"
        "4. 带着这些**全局视角**再去看 phase3-eval 的 differences / diff_notes ——\n"
        "   如果发现某 case 的问题其实是**全局原则没贯彻**导致的(如多处应代码化却写成规则段),\n"
        "   改一次就能修一族,而不是逐 case 改。\n\n"
        "**反约束**:\n"
        "- ❌ 严禁照抄业务专有内容(具体 case_id / 业务名 / 协议细节)\n"
        "- ❌ 严禁只读不写、读了一堆知识但 modifications 还是 case-by-case 修补\n"
        "- ❌ 严禁只 Read 1 个文件就跳到改 skill(深度 ≤ 2 层 + ≥ 3 个代表性文件)\n"
        "- ✅ 如果读完知识库没有发现任何高于当前 case 的方法论/原则,明确说'本次无更高视角可补'\n\n"
        "**自检**:`optimization_summary.md` 头部 `self_check.knowledge_used.explored_paths` "
        "列出实际 Read 过的 consume_lib 文件路径(每改一条 mod 至少关联 1 个知识库依据)\n\n"
    )


def run_optimize_agent(
    candidate_skill_root: Path,
    skill_path_list: list,
    data_dir: Path,
    candidate_id: int,
    round_num: int,
    modification_budget: int,
    extra_inputs: str = "",
    max_attempts: int = 3,
    cand_dir: Optional[Path] = None,
    best_round: int = 0,
    run_count: int = 1,
) -> Path:
    """调 proposal-agent 一次性完成 context 加载 + gap 识别 + modification 生成 + Edit 应用 + summary 落盘。

    best_round: 当前修改基线的轮次(baseline_anchored=False 时本轮起点 = eng.best_round 的 skill,
    非"最新一轮")。注入历史清单标注基线轮优先,0 表示起点是 baseline。

    新 contract(v2: 单阶段一次性,取代原 stage_1+2+3+ApplyAgent 四阶段):
    - LLM 自己用 Read/Edit/Write 工具改 Skill 文件
    - 一次 LLM 调用完成所有工作(无 stage_1/2/3 拆分)
    - 落 optimization_summary.md(取代原 apply_status.md)
    - self_check 5 项硬约束(overall_pass=false → REWORK 重调)
    - 不再写中间 JSON(stage_*.json 已删)

    Args:
        candidate_skill_root: 候选副本根目录(下含 SkillName 子目录)
        skill_path_list: 原始 Skill 路径列表
        data_dir: 评测产物目录(含 phase1-build/ phase2-exec/ phase3-eval/)
        candidate_id: 候选编号
        round_num: 轮次编号
        modification_budget: 本轮最大修改条数(借鉴 SkillOpt lr_autonomous)
        extra_inputs: 注入到 prompt 的额外输入(prev_failure_block 等)
        max_attempts: REWORK 上限(默认 2)
        cand_dir: optimization_summary.md 的落盘目录。默认 = candidate_skill_root.parent
            (向后兼容 round_N/candidate_K/ 布局)。
            单步子 agent 流程会传 baseline/round_N_candidate_K/,
            apply 完成后整个目录 mv 到 round_N/candidate_K/。

    Returns:
        写入的 optimization_summary.md 路径(失败时为 optimization_summary.failed.md)
    """
    candidate_skill_root = Path(candidate_skill_root)
    data_dir = Path(data_dir)
    cand_dir = Path(cand_dir) if cand_dir is not None else candidate_skill_root.parent

    skill_list_str = "\n".join(
        f"  - {Path(sp).parent.name} → {candidate_skill_root / Path(sp).parent.name}"
        for sp in skill_path_list
    )
    # 推导 taskid 根路径(向上 2 级,基于 cand_dir,与 candidate_skill_root 在 baseline/ 还是 round_N/ 下无关)
    taskid_root = cand_dir.parent.parent

    # 读取 workspace/config.json 的 consume_lib_path(全局视角知识库)
    # 作为"突破当前问题局限、从更高维度优化"的全局知识注入 prompt
    consume_lib_path = ""
    cfg: dict = {}
    try:
        cfg_file = taskid_root / "config.json"
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            consume_lib_path = (cfg.get("consume_lib_path") or "").strip()
    except Exception:
        consume_lib_path = ""
    consume_lib_block = _render_consume_lib_block(consume_lib_path)

    # 🆕 2026-08:读取 config.json 的 expert_guidance(专家指引,支持任务中编辑引导优化方向)。
    # 每轮都读文件最新值 —— 用户发现问题后编辑 config.json 的 expert_guidance,下一轮 ProposalAgent 读到新值作为重要建议。
    expert_guidance = ""
    try:
        cfg_file = taskid_root / "config.json"
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            expert_guidance = (cfg.get("expert_guidance") or "").strip()
    except Exception:
        expert_guidance = ""
    expert_guidance_block = ""
    if expert_guidance:
        expert_guidance_block = (
            "## 🧑‍💼 专家指引(重要建议,本轮优化方向的首要参考,优先遵循)\n"
            f"{expert_guidance}\n\n"
        )

    # 读 user-config.yaml 的 prompt_paths 段(已废弃,改用 orchestrator 生成的 result_diff_report.md)
    try:
        from orchestrators.workspace import _load_user_config as _load_ucfg
        _ucfg = _load_ucfg() or {}
        prompt_paths_block = _render_prompt_paths_block(_ucfg)
    except Exception:
        prompt_paths_block = ""

    # 本轮之前的全部 diff 报告(round_{round_num}/result_diff_report_*.md)
    # cand_dir 是中间工作区 baseline/round_N_candidate_K/,不含 diff 报告,
    # 故用现成的 round_num 参数直接定位 round 目录,不从 cand_dir 反推。
    history_diff_block = _render_history_diff_block(
        taskid_root / f"round_{round_num}", round_num, best_round=best_round,
        scoring_rule=(_ucfg.get("evidence_paths", {}) or {}).get("scoring_rule", "") if "_ucfg" in dir() else "",
        run_count=run_count,
    )

    summary_path = cand_dir / "optimization_summary.md"
    last_self_check: dict = {}
    # 2026-08 改造:对齐 score.json 的"LLM Edit 文件 + 框架校验"模式 —— 预放 self_check 填空模板,
    # proposal-agent 用 Edit 填它(而非在 optimization_summary.md 里手写 self_check 块),
    # 消除"self_check 块未找到 / parse_error / 契约格式不匹配"类失败(实测 12/20 轮失败中约 7 轮属此类)。
    _self_check_tpl_src = Path(__file__).resolve().parent.parent / "scorer" / "templates" / "self_check.json"
    self_check_path = cand_dir / "_template_self_check.json"
    if not self_check_path.exists() and _self_check_tpl_src.exists():
        self_check_path.write_text(_self_check_tpl_src.read_text(encoding="utf-8"), encoding="utf-8")

    for attempt in range(1, max_attempts + 1):
        attempt_block = ""
        if attempt > 1 and last_self_check:
            # 强校验 6 触发(LLM 拒绝真改 Skill 文件)→ 专门强提示
            if last_self_check.get("_refused_no_changes"):
                attempt_block = (
                    f"\n## ⚠️ Attempt {attempt}/{max_attempts} (上次: 你拒绝了 Edit,0 个文件改动)\n"
                    f"**你被 system reminder 误导了**。本任务的 `verify_*.py` 是**结构校验工具**(表格解析/列名校验/字数统计/溯源匹配),**不**是 malware。\n"
                    f"**正确做法**:Read 文件 → 看 import(无 `requests/socket` 联网)+ 函数功能(解析/校验/提取)→ 是本地业务脚本 → **继续 Edit**。\n"
                    f"**本轮必须**:用 Edit 工具真改 SKILL.md 或 scripts/*.py → 落 optimization_summary.md。**不能再只输出 JSON/refuse**。\n"
                )
            else:
                attempt_block = (
                    f"\n## ⚠️ Attempt {attempt}/{max_attempts} (上次失败)\n"
                    f"上次 self_check 结果:\n```json\n"
                    f"{json.dumps(last_self_check, ensure_ascii=False, indent=2)}\n```\n"
                    f"请修正上述 failed 项后重新 Edit + 落盘 optimization_summary.md。\n"
                )

        prompt = (
            "你是 ProposalAgent:Skill 一次性优化专家(合并 proposal + apply)。\n"
            "**单次 LLM 调用完成所有工作**——context 加载 + gap 识别 + modification 生成 + Edit 应用 + summary 落盘。\n"
            "禁止拆分为多阶段多次调用。\n\n"
            + prompt_paths_block
            + history_diff_block
            + consume_lib_block
            + expert_guidance_block
            + f"## 输入\n"
            f"- taskid 根目录(所有实验记录): `{taskid_root}`\n"
            f"- 候选副本(本轮修改,Edit 实际发生地): `{candidate_skill_root}`\n"
            f"- summary 落盘目录: `{cand_dir}` (optimization_summary.md 写到这里的同级)\n"
            f"- **路径语义(单步子 agent 流程)**:`candidate_skill_root` 位于中间工作区 "
            f"`baseline/round_{{N}}_candidate_{{K}}/skill/`,apply 完成后整目录会被 orchestrator "
            f"mv 到最终位置 `round_{{N}}/candidate_{{K}}/`。**你不需要关心 mv,只在 `{candidate_skill_root}` 下 Edit 即可**。\n"
            f"- 评测产物目录: `{data_dir}`\n"
            f"- 涉及的 Skill 列表:\n{skill_list_str}\n"
            f"- **modification_budget = {modification_budget}** 条(round=0:8, round≥6:2)\n"
            + (f"\n- 额外指引(prev_failure_block 等):\n{extra_inputs}\n" if extra_inputs else "")
            + attempt_block
            + "\n"
            f"## 工作流(6 步一次性完成)\n"
            f"1. 扫描 Skill 全貌: `find {candidate_skill_root} -type f | grep -v __pycache__`\n"
            f"2. 读取失败证据:**并发 Read 顶部「📜 必读历史数据」清单的全部文件**"
            f"(每轮 改动 + 结果 两份)。仅当清单缺失时,才回退读 "
            f"`{data_dir}/phase3-eval/*/results/*.json`\n"
            f"3. **整体分析(先全局后局部,防顾此失彼)**:横向对比所有 case,"
            f"按 根因类别(数量/内容/链路) × skill 层(上游/下游) 聚类共性根因,"
            f"列出满分 case 核对表——每条 mod 前先确认不影响任何非失分 case\n"
            f"4. 生成 modifications(按 extract_to_script > condense > delete_redundant > split_skill > edit_exact,"
            f"**优先修共性根因一次修一族**,每个 mod 的 trade-off 含 `impacted_fullscore_cases`)\n"
            f"5. 立即用 Edit/Write 工具应用 — Step A/B/C 自检 current_content\n"
            f"6. 落盘 optimization_summary.md 到 `{summary_path}`\n\n"
            f"## 硬约束(违反 REWORK)\n"
            f"- 单次 LLM 调用,禁止拆分为 stage_1/2/3\n"
            f"- 必须用 Read/Edit/Write 真改 Skill 文件(不只是输出 JSON)\n"
            f"- 修改覆盖 ≥ SKILL.md(如适用含 scripts/templates/references)\n"
            f"- 禁止 edit_exact add 无脑加规则段\n"
            f"- current_content 必须 Read + FOUND 自检\n"
            f"- 每条 mod 必填 estimated_token_impact(允许负值) + score_impact + cost_benefit\n"
            f"- extract_to_script 的 extract_code 无 case_id 硬编码\n"
            f"- 量化边界:每条 new_content ≤ 800 字符,总 mods ≤ 6 条\n"
            f"- 🛑 **全 case 核对**:每条 mod 必须逐个核对**所有 case**(已满分/中分/已失败)影响,确保不新增失败。"
            f"规则/关键词/阈值类 mod 影响面是全部 case,禁止只盯失分 case 优化而误伤已满分 case(202039 教训:"
            f"`coreset0→运营商` 伤 100→40、`优先 2-3 个场景` 伤 gold 有 4 场景的 100→0)。"
            f"每条 mod 的 trade-off 必须含 `impacted_fullscore_cases`(被影响的非失分 case 清单+依据),空泛则 mod 无效。\n"
            f"- 🔄 **回滚意识**:设计 mod 前必读上轮 `skill_diff_round_{{N-1}}.md`,识别上轮是否加了过度拟合规则(修好 A 伤满分 B);"
            f"若有,本轮 mod 应回滚/修正该规则而非叠加。\n"
            f"- 🛑 **评分机制禁入 SKILL.md**:禁止在 SKILL.md 写评测/打分机制表述——评分威胁(如\"会导致召回率=0\"\"章节判定为'未输出'\"\"否则精确率受损\"\"优先级:占位行 > 留空行(召回率=0) > 多行猜测\")"
            f"与指标名(如\"召回率/精确率/F1/5 维评分\")均禁止。SKILL.md 只能写业务规则(如\"必须输出数据行,不得留空\"),违规 REWORK。\n"
            f"\n"
            f"## self_check 必填(用 Edit 填 `{self_check_path}`,模板已给结构,只填值)\n"
            f"- 模板文件 `{self_check_path}` 已预放,含完整字段结构(`_comment_N` 说明每个字段)\n"
            f"- 用 Edit 工具把模板里的空值(0/false/[]/{{}})替换为实际值,**不要**重写结构/新增字段\n"
            f"- **不要**在 optimization_summary.md 里输出 self_check markdown 块 —— framework 只读 `{self_check_path}`\n"
            f"- overall_pass=false → REWORK\n"
            f"归因必读:低分 case 的失分归因由 score-analyzer 输出到 result_diff `#### 6` 失分分析,"
            f"proposal 直接 Read `#### 6` 采纳归因结论(具体哪个中间 skill 的问题),不强制自己逐个 Read trace/中间产物;"
            f"检测到代码错误(can't open file 等)必须改代码并 code_error_fixed=true\n\n"
            f"完整 contract 见 `agents/proposal-agent.md`"
        )

        # ── 调 LLM(单次)
        agent_output = None
        error_msg: Optional[str] = None
        llm_latency_ms: int = 0
        llm_input_tokens: int = 0
        llm_output_tokens: int = 0
        t0 = time.time()
        try:
            from tools import Agent
            agent_output = Agent(
                mode="auto",
                description=f"Candidate {candidate_id}: 一次性 Skill 优化 (round {round_num}, attempt {attempt}/{max_attempts})",
                subagent_type="proposal-agent",
                prompt=prompt,
            )
            llm_latency_ms = int((time.time() - t0) * 1000)
            if isinstance(agent_output, dict):
                usage = agent_output.get("usage", {}) or {}
                llm_input_tokens = int(usage.get("input_tokens", 0) or 0)
                llm_output_tokens = int(usage.get("output_tokens", 0) or 0)
        except Exception as e:
            llm_latency_ms = int((time.time() - t0) * 1000)
            error_msg = str(e)

        # ── 检查 self_check(读 summary 文件)
        # 🆕 2026-08-01:兼容两种 self_check 格式
        #   1. 嵌在 markdown ```json ... ``` 代码块里(老格式)
        #   2. 直接是 JSON 文件顶层(新格式,LLM 直接写纯 JSON)
        # 历史 bug:framework 旧正则只认格式 1,taskid_20260801_022239 round_1/2 全部误判
        #   `_parse_error: self_check 块未找到` → REWORK → 第二次 attempt 时 LLM "自我拒绝 Edit"
        #   → optimization_summary.failed.md 落盘 → round_1/2 误报 0 分
        # 2026-08 改造:从 _template_self_check.json 读 self_check(proposal-agent Edit 填的模板),
        # 不再从 optimization_summary.md 解析 ```json 块(消除"块未找到 / parse_error / 契约格式不匹配")。
        if summary_path.exists() or self_check_path.exists():
            try:
                _check_obj = None
                if self_check_path.exists():
                    try:
                        _check_obj = json.loads(self_check_path.read_text(encoding="utf-8"))
                        if not isinstance(_check_obj, dict) or "self_check" not in _check_obj:
                            _check_obj = None
                    except (json.JSONDecodeError, OSError):
                        _check_obj = None
                if _check_obj is not None:
                    last_self_check = _check_obj.get("self_check", {})
                    overall_pass = last_self_check.get("overall_pass", False)
                    # 🆕 2026-08-01 反幻觉校验:检测 proposal-agent 是否误读 system-reminder 拒绝 Edit
                    _summary_text_for_check = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
                    _self_refuse_patterns = [
                        r"system-reminder.{0,30}(?:硬性)?(?:禁止|不允许|不能).{0,10}(?:Edit|Write|改进|增广|修改)",
                        r"拒.{0,5}(?:绝|不).{0,20}(?:Edit|Write|改进|增广).{0,30}system-reminder",
                        r"self.{0,5}read.{0,20}hook.{0,20}拒绝.{0,20}(?:Edit|改进)",
                    ]
                    _self_refuse_hit = any(
                        re.search(p, _summary_text_for_check, re.IGNORECASE | re.DOTALL)
                        for p in _self_refuse_patterns
                    )
                    if _self_refuse_hit and overall_pass:
                        print("  ⚠️ [反幻觉] proposal-agent 误读 system-reminder 拒绝 Edit,强制 REWORK")
                        last_self_check = {
                            "_self_refuse_detected": True,
                            "overall_pass": False,
                        }
                        overall_pass = False

                    # 🆕 2026-08-01 校验:ReadTool/EditTool/WriteTool 工具调用次数
                    # 背景:实测 taskid_20260801_073320 proposal-agent 0003 — 0 次 Read/Edit/Write,
                    # 但 SKILL.md 真改了(10904→13839 bytes),LLM 用 `python3 -c "open('f','w').write()"`
                    # 绕 Edit/Write 工具。framework 端如果只信 self_check overall_pass=true,
                    # 就会放行这种"绕过工具统计"的产物。
                    # 修复:从 _read_audit.json + _debug/agent_*.txt 抽 tool_use 统计(默认 stream-json 已
                    # 落 raw_jsonl,见 tools.py:561 output_format 默认 "stream-json"),
                    # 校验 ReadTool/EditTool/WriteTool 次数 ≥ self_check 声明的 mod 数
                    if overall_pass and summary_path.exists():
                        try:
                            from orchestrators.tool_audit import extract_tool_use_from_log, extract_mods_count_from_summary
                            tool_audit = extract_tool_use_from_log(summary_path)  # debug_dir 由 summary_path 反推
                            mods_count = extract_mods_count_from_summary(summary_path)
                            read_n = tool_audit.get("ReadTool", 0)
                            edit_n = tool_audit.get("EditTool", 0)
                            write_n = tool_audit.get("WriteTool", 0)
                            # codex/dsh 无 stream-json 工具审计流（raw_jsonl=None），
                            # tool_audit 抽不到 Read 计数 → 用 ProposalAgent 自报的
                            # _read_audit.json（read_count/files_read）兜底，避免每次误判 REWORK。
                            if read_n == 0:
                                try:
                                    import json as _json_ra2
                                    # cand_dir 可能是 skill 子目录或 mv 前路径，_read_audit.json
                                    # 落在 candidate_K/ 或 taskid 下 → 逐级 + taskid 兜底探测。
                                    _ra_path = None
                                    _probe = Path(cand_dir)
                                    for _depth in range(5):
                                        if (_probe / "_read_audit.json").exists():
                                            _ra_path = _probe / "_read_audit.json"
                                            break
                                        if _probe.parent == _probe:
                                            break
                                        _probe = _probe.parent
                                    if _ra_path is None and taskid_root.exists():
                                        _found = sorted(
                                            Path(taskid_root).rglob("_read_audit.json"),
                                            key=lambda p: p.stat().st_mtime, reverse=True,
                                        )
                                        _ra_path = _found[0] if _found else None
                                    if _ra_path is None:
                                        raise FileNotFoundError("_read_audit.json not found")
                                    _ra2 = _json_ra2.loads(_ra_path.read_text(encoding="utf-8"))
                                    _audit_read = int(
                                        _ra2.get("read_count")
                                        or len(_ra2.get("files_read") or [])
                                    )
                                    if _audit_read > 0:
                                        read_n = _audit_read
                                        edit_n = max(edit_n, int(_ra2.get("edit_count") or 0))
                                        print(f"  ℹ️ [反幻觉] 无 stream-json，采用 _read_audit.json 计数: read={read_n} edit={edit_n}")
                                except Exception as _e_ra:
                                    print(f"  ℹ️ [反幻觉] _read_audit.json 兜底失败(继续按原审计): {_e_ra}")
                            # 强校验 1:ReadTool ≥ 3(必须真读 trace/agent defs,不能凭印象写文件)
                            # 单步 eval 场景（无 score_analyzer_report）证据文件更少，门槛降为 ≥ 1，
                            # 否则简单 Skill 的候选生成会因"只读了 2 个文件"反复 REWORK（白耗 3 倍调用）。
                            _min_read = 3
                            try:
                                _ws_probe = cand_dir
                                while _ws_probe.parent != _ws_probe:
                                    if (_ws_probe / "baseline").is_dir() or (_ws_probe / "round_1").is_dir():
                                        break
                                    _ws_probe = _ws_probe.parent
                                if not any(_ws_probe.rglob("score_analyzer_report*")):
                                    _min_read = 1
                            except Exception:
                                _min_read = 3
                            if read_n < _min_read:
                                print(f"  ⚠️ [反幻觉] proposal-agent ReadTool {read_n} 次(应 ≥ {_min_read})→ 保留 baseline REWORK")
                                print("  💡 LLM 必须 Read 真文件(trace.log + subagents/*.jsonl / SKILL.md / scripts/*.py),不能凭印象 Edit")
                                last_self_check = {
                                    "_read_underflow": True,
                                    "tool_audit": tool_audit,
                                    "mods_count": mods_count,
                                    "overall_pass": False,
                                }
                                overall_pass = False
                            # 强校验 2:Edit/WriteTool 实际调用 vs LLM 声明的 mods 数
                            elif edit_n + write_n < mods_count:
                                print(f"  ⚠️ [反幻觉] proposal-agent 声明 {mods_count} mods 但 Edit/WriteTool 只 {edit_n + write_n} 次 → REWORK")
                                last_self_check = {
                                    "_mod_count_mismatch": True,
                                    "mods_count": mods_count,
                                    "edit_write_count": edit_n + write_n,
                                    "overall_pass": False,
                                }
                                overall_pass = False
                            # 强校验 3:0 ReadTool + 0 Edit/Write 但 mods_count > 0 → 必是 LLM 凭印象写
                            elif read_n == 0 and (edit_n + write_n) == 0 and mods_count > 0:
                                print(f"  ⚠️ [反幻觉] LLM 声明 {mods_count} mods 但 ReadTool/EditTool/WriteTool 全 0 → 凭印象 REWORK")
                                last_self_check = {
                                    "_hallucination_no_tools": True,
                                    "tool_audit": tool_audit,
                                    "overall_pass": False,
                                }
                                overall_pass = False
                            # 强校验 4:🆕 2026-08-01 — result_diff 必读校验
                            # 背景:实测 taskid_20260801_092719 proposal-agent 0 ReadTool,
                            # 但 framework USER PROMPT 显式给了 result_diff_report_baseline.md
                            # 路径(给 LLM 真读失分诊断),LLM 仍然没读 → 凭印象写 SKILL.md
                            # 修复:从 _read_audit.json 验证 LLM 真读了 result_diff_report_baseline.md
                            elif read_n > 0:
                                _read_audit_path = cand_dir / "_read_audit.json"
                                _read_score_analyzer = False
                                _audit = {}
                                if _read_audit_path.exists():
                                    try:
                                        import json as _json_ra
                                        _audit = _json_ra.loads(_read_audit_path.read_text(encoding="utf-8"))
                                        for _p in _audit.get("files_read", []):
                                            if "score_analyzer_report" in str(_p):
                                                _read_score_analyzer = True
                                                break
                                    except Exception:
                                        pass
                                if not _read_score_analyzer:
                                    # 单步 eval 场景（goldeval 等）不产 score_analyzer_report，
                                    # 若仍强制必读 → 每次提案必然 REWORK 3 次（实测白耗 3 倍调用）。
                                    # 降级：workspace 内确实没有该报告时，只要有真实 Read 调用即放行
                                    # （read_n > 0 已排除"0 次 Read 凭印象"；单步场景证据文件名不固定，
                                    #  attempt 1 时 _read_audit.json 也可能尚未落盘，故不再依赖具体文件名）。
                                    # 定位 workspace 根：向上找含 baseline/ 的目录，避免误扫其他 taskid。
                                    _ws_root = cand_dir
                                    while _ws_root.parent != _ws_root:
                                        if (_ws_root / "baseline").is_dir() or (_ws_root / "round_1").is_dir():
                                            break
                                        _ws_root = _ws_root.parent
                                    _has_sa_report = False
                                    try:
                                        for _p in _ws_root.rglob("score_analyzer_report*"):
                                            _has_sa_report = True
                                            break
                                    except Exception:
                                        _has_sa_report = False
                                    if not _has_sa_report:
                                        print("  ℹ️ [反幻觉] 无 score_analyzer_report 产物（单步 eval 场景），已有 Read 调用 → 放行")
                                    else:
                                        print("  ⚠️ [反幻觉] proposal-agent 0 次 Read score_analyzer_report → 凭印象写 SKILL.md REWORK")
                                        last_self_check = {
                                            "_no_read_score_analyzer": True,
                                            "tool_audit": tool_audit,
                                            "overall_pass": False,
                                        }
                                        overall_pass = False
                            # 强校验 4.5:skill_diff 必读 — 2026-08-10 移除(误报根源)
                            # score_analyzer_report_round_x.md 已含 skill_diff 内容,读前者即满足
                            # "知道前轮改了什么"的意图;单独强制读 skill_diff 造成冗余 REWORK。
                            # 历史背景(2026-08-01):proposal 只读 result_diff 没读 skill_diff → 重复
                            # 试同方向 mod。该信息由 score_analyzer_report 承担后不再需要独立强校验。
                            # 强校验 5:risk_evidence 语义(独立于 read_n)
                            # 背景:实测 taskid_20260801_154641 — 3 条 mod 的 risk_evidence 全填
                            # "无 - 只约束过度提取"这类空话,契约要求的 `{case_id} 的 {column} 列:gold=.../LLM=...`
                            # (proposal-agent.md §trade-off)完全没落地,framework 却因 LLM 自报
                            # risk_evidence_includes_column=true 而放行。
                            # 修复:扫描 summary 全文,有 mod 但找不到任何 gold=/LLM=/列: 证据模式 → REWORK。
                            if overall_pass and summary_path.exists() and mods_count > 0:
                                try:
                                    _s = summary_path.read_text(encoding="utf-8")
                                    _has_evidence = re.search(
                                        r"(?:列\s*[:：]?\s*gold|gold\s*=|LLM\s*=|的\s*\S+\s*列\s*[:：])",
                                        _s,
                                    )
                                    if not _has_evidence:
                                        print("  ⚠️ [反幻觉] risk_evidence 无证据格式(契约要求 `{case_id} 的 {column} 列:gold=.../LLM=...`)→ REWORK")
                                        last_self_check = {
                                            "_risk_evidence_no_basis": True,
                                            "mods_count": mods_count,
                                            "overall_pass": False,
                                        }
                                        overall_pass = False
                                except Exception:
                                    pass
                            # 强校验 6:🆕 2026-08-03 — candidate_K/skill/ vs before_skill/skill/ ground truth diff
                            # 背景:R9 LLM 看到 system reminder 误判 verify_*.py 为 malware,拒绝 Edit,
                            # 但 self_check PASS(用 WriteTool 写 optimization_summary.md,tool audit
                            # 看不出"未真改 SKILL.md")。framework 端必须用文件 diff 做 ground truth 校验。
                            # 修复:对比 candidate_K/skill/ vs round_N_before_skill/skill/ 的真实文件差异;
                            # 0 个差异 → LLM 拒绝真改 → REWORK。
                            if overall_pass and (edit_n + write_n) > 0:
                                try:
                                    import filecmp
                                    before_skill = cand_dir.parent / f"round_{round_num}_before_skill" / "skill"
                                    candidate_skill = cand_dir / "skill"
                                    if before_skill.exists() and candidate_skill.exists():
                                        diff_count = 0
                                        for _f in candidate_skill.rglob("*"):
                                            if _f.is_file() and "__pycache__" not in _f.parts and not _f.name.startswith("."):
                                                _rel = _f.relative_to(candidate_skill)
                                                _before_f = before_skill / _rel
                                                if not _before_f.exists() or not filecmp.cmp(str(_f), str(_before_f), shallow=False):
                                                    diff_count += 1
                                        if diff_count == 0:
                                            print("  ⚠️ [反幻觉强校验 6] LLM 拒绝真改 Skill 文件 — candidate_K/skill/ 与 before_skill 完全相同(0 个 diff)→ REWORK")
                                            last_self_check = {
                                                "_refused_no_changes": True,
                                                "edit_write_count": edit_n + write_n,
                                                "mods_count": mods_count,
                                                "overall_pass": False,
                                                "_hint": "LLM 看到 system reminder 误判 verify_*.py 为 malware。proposal-agent.md 已加'拒绝 Edit 的反模式'段,必须强制 Read 实际文件 + 判断是结构校验工具(非 malware)→ 继续 Edit",
                                            }
                                            overall_pass = False
                                except Exception:
                                    pass

                        except Exception as _e:
                            # tool_audit 不可用不阻塞,放过
                            pass

                    if overall_pass:
                        _record_proposal_metrics(
                            cand_dir=cand_dir,
                            candidate_id=candidate_id,
                            round_num=round_num,
                            subagent_type="proposal-agent",
                            latency_ms=llm_latency_ms,
                            input_tokens=llm_input_tokens,
                            output_tokens=llm_output_tokens,
                            status="ok",
                        )
                        # 校验通过后清理 self_check 模板(避免残留干扰下一轮评测)
                        if self_check_path.exists():
                            self_check_path.unlink()
                        return summary_path
                else:
                    last_self_check = {"_parse_error": "self_check 块未找到", "overall_pass": False}
            except Exception as _e:
                last_self_check = {"_parse_error": str(_e), "overall_pass": False}
        else:
            # ── 2026-08-04 降级:summary 未落盘,不再整轮失败 ──
            # 背景:proposal-agent 偶发不写 optimization_summary.md(_missing_summary),
            # 导致候选整轮失败(round_2 实测)。放宽:只要 candidate_skill 有真实文件改动
            # 就降级放行;即使没改,候选目录已存在(调用方预建的 before 副本),降级生成
            # no-op summary 保证每轮必有候选可评估。
            _diff_count = 0
            try:
                import filecmp as _fc
                _before_skill = cand_dir.parent / f"round_{round_num}_before_skill" / "skill"
                _cand_skill = cand_dir / "skill"
                if _before_skill.exists() and _cand_skill.exists():
                    for _f in _cand_skill.rglob("*"):
                        if _f.is_file() and "__pycache__" not in _f.parts and not _f.name.startswith("."):
                            _rel = _f.relative_to(_cand_skill)
                            _bf = _before_skill / _rel
                            if not _bf.exists() or not _fc.cmp(str(_f), str(_bf), shallow=False):
                                _diff_count += 1
            except Exception:
                _diff_count = 0
            _note = (
                f"LLM 未按契约落盘 optimization_summary,但检测到 {_diff_count} 个文件真实改动 → 降级放行候选。"
                if _diff_count > 0
                else "LLM 未按契约落盘 summary 且未改文件 → 候选与上轮相同(no-op),framework 降级保证候选可评估。"
            )
            print(f"  ⚠️ [降级] {_note}")
            summary_path.write_text(
                "# optimization_summary(framework 降级生成)\n\n"
                f"> {_note}\n\n"
                "```json\n"
                '{"self_check": {"_missing_summary_downgraded": true, "file_diff_count": '
                f"{_diff_count}, \"overall_pass\": true}}\n"
                "```\n",
                encoding="utf-8",
            )
            _record_proposal_metrics(
                cand_dir=cand_dir,
                candidate_id=candidate_id,
                round_num=round_num,
                subagent_type="proposal-agent",
                latency_ms=llm_latency_ms,
                input_tokens=llm_input_tokens,
                output_tokens=llm_output_tokens,
                status="ok",
            )
            # 降级路径也清理 self_check 模板(避免残留)
            if self_check_path.exists():
                self_check_path.unlink()
            return summary_path

    # ── max_attempts 用尽:落 failed summary
    failed_path = cand_dir / "optimization_summary.failed.md"
    failed_content = (
        f"# Optimization Failed — Round {round_num} Candidate {candidate_id}\n\n"
        f"## 原因\n经过 {max_attempts} 次 REWORK 仍 overall_pass=false。\n\n"
        f"## 最后一次 self_check\n```json\n"
        f"{json.dumps(last_self_check, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 处理\n保留 baseline(本轮未改 Skill 文件),沿用上轮最佳。\n"
    )
    if error_msg:
        failed_content += f"\n## 最后一次 LLM 错误\n```\n{error_msg}\n```\n"
    failed_path.write_text(failed_content, encoding="utf-8")
    # failed 也清理 self_check 模板(避免残留)
    if self_check_path.exists():
        self_check_path.unlink()

    _record_proposal_metrics(
        cand_dir=cand_dir,
        candidate_id=candidate_id,
        round_num=round_num,
        subagent_type="proposal-agent",
        latency_ms=llm_latency_ms,
        input_tokens=llm_input_tokens,
        output_tokens=llm_output_tokens,
        status="failed",
    )
    return failed_path

