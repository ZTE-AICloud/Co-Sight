# Data Flow Rules — AgentGenesis 数据流详则

> 来源: CLAUDE.md 五、Data Flow — 经 Phase 3 架构分层重构提取
> 提取日期: 2026-05-03
> 适用对象: AgentGenesis 自身及所有生成的 Agent
> 关联模式: DT1-Linear-Pass-Through, DT2-Shared-State, DF1-Schema-Enforced, DP1-Lineage

---

## 数据实体定义

AgentGenesis 的数据实体按类型分为四类：

| 类型 | 说明 |
|------|------|
| 流转 | 在 Phase 之间传递的中间产物，有明确的生产者和消费者 |
| 共享 | 多个 Phase 共用的状态或配置，可覆盖更新 |
| 持久 | 最终输出产物，生命周期贯穿 Agent 使用期 |
| 临时 | 内存中或拼装完成后可清理的中间片段 |

### 实体表

| 实体名称 | 类型 | 生产者 | 消费者 | 路径 | 生命周期 | 来源标注 |
|---------|------|--------|--------|------|---------|---------|
| user_requirement | 流转 | 外部输入 | Phase 0 (澄清), Phase 1 (匹配) | 自然语言文本 | 贯穿全流程 | user_input |
| phase0_question_queue | 流转 | Phase 0 (Main Agent) | Phase 0 (交互循环) | AgentGenesis-Code/work/{name}/phase0-question-queue.yaml | Phase 0 内部 | agent-requirement-clarifier |
| clarified_requirement | 流转(最终) | Phase 0 (Main Agent) | Phase 1 (匹配) | AgentGenesis-Code/work/{name}/phase0-clarified-requirements.yaml | 贯穿后续 Phase | agent-requirement-clarifier, IH2 |
| design_docs | 流转 | K2 Read | Phase 1 (匹配), Phase 3 (诊断) | design/ | 按需加载 | K2 |
| matching_decision | 流转 | Phase 1 (匹配) | Phase 2 (拼装), Phase G1 (审查) | AgentGenesis-Code/work/{name}/agent-creation/phase1-matching-decision.md | 贯穿后续Phase | W1 |
| filled_fragments[] | 流转 | Phase 2 (模板填充) | Phase 2 (拼装) | 内存/Markdown片段 | 拼装完成后可清理 | W1, K3 |
| agent_spec | 流转(最终) | Phase 3 (拼装) | Phase G1 (审查), 用户 | $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/CLAUDE.md | 持久，用户可直接启动 | ALL |
| agent_supporting_files | 流转 | Phase 3 (构建输出) | 用户 | $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/.claude/ + evaluation/ + schemas/ + knowledge/ | 持久 | DF1, G1 |
| review_report | 流转 | Phase G1 (审查) | Phase 2 (修正), 用户 | AgentGenesis-Code/work/{name}/agent-creation/phase2-review.md | 贯穿后续修正 | G1 |
| verification_report | 流转 | Phase V (验证) | AUTO_FIX, 用户 | $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/verification-report.md | 持久 | DF1, G1 |
| diagnosis_report | 流转 | DIAGNOSE | DIAGNOSE (修正), 用户 | AgentGenesis-Code/work/{id}/optimize-skill/phase1-diagnosis-report.md | 最终输出 | CD3 |
| progress_state | 共享 | Main Agent (Phase 边界写入) | 所有 Phase, Main Agent 恢复 | AgentGenesis-Code/work/{target-name}/progress-state.yaml | 覆盖更新 | DT2, SM1 |
| knowledge_files_manifest | 共享 | 系统初始化 | 所有Phase | AgentGenesis-Code/knowledge/shared/knowledge-sources.yaml | 持久 | K2, K3, K4 |

---

## 数据流转图

```
用户需求
    │
    ▼
[Phase 0: 需求澄清]  ◄── skills/requirement-clarifier/SKILL.md (L3, v0.18 起; 旧名 agent-requirement-clarifier, 双 mode 派发)
    │
    ├── confidence≥80 且无模糊词汇 → SKIP ──┐
    ├── 否则: 需求澄清决策树遍历              │
    ├── 逐题交互 (AskUserQuestion)          │
    │                                       │
    ▼  AgentGenesis-Code/work/{name}/phase0-question-queue.yaml  │
    │                                       │
    ▼  AgentGenesis-Code/work/{name}/phase0-clarified-requirements.yaml
    │                                       │
    ▼  clarified_requirement (增强需求)      │
    │                                       │
    ├───────────────────────────────────────┘
    ▼
[Phase 1: 需求分析+模式匹配]
    │
    ├── Read pattern-matcher.yaml (K3)
    ├── Read 设计文档 (K2)  
    │
    ▼  AgentGenesis-Code/work/{name}/agent-creation/phase1-matching-decision.md
    │
[Phase G1: 审查门禁(匹配决策)]  ◄── progress_state (DT2)
    │
    ├── Read matching_decision.md
    ├── Read K4 rules
    │
    ▼  AgentGenesis-Code/work/{name}/agent-creation/phase2-review.md ──▶ [不通过] → REWORK → 重新审查
    │
    ▼  [通过]
    │
[Phase 2: 模板填充+Spec拼装+构建输出]
    │
    ├── Read matching_decision (DT1)
    ├── Read pattern-catalog.yaml → template_files (K3)
    ├── Read .template.md × N (K3)
    │
    ▼  $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/
       ├── CLAUDE.md (8章)
       ├── .claude/ (agents, rules, settings)
       ├── schemas/
       ├── knowledge/
       └── evaluation/
    │
[Phase V: 自动验证与修复]  ◄── phases/agent-creation/phase4-verify.md + rules/shared/verification-checks.md
    │
    ├── 执行7项静态验证
    ├── 生成 verification-report.md
    │
    ▼  [不通过] → AUTO_FIX → 修复 → 重验证 (默认1轮)
    │
    ▼  [通过 或 轮次耗尽]
    │
[最终输出: $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/ — 独立可启动的 Claude Code 项目，含 verification-report.md]
    │
    ▼ (诊断模式)
[Phase 3: 问题诊断]
    │
    ├── Read problem-diagnoser.yaml (K3)
    ├── Read 现有 $AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/CLAUDE.md
    │
    ▼  AgentGenesis-Code/work/{id}/optimize-skill/phase1-diagnosis-report.md
```

---

## 数据校验规则 DF1

### 输出文件 Schema 校验

每个输出文件必须满足以下 Schema 要求：

**matching_decision.md**
- 必须包含 `decision_id`, `timestamp`, `pattern_decisions[]`（非空数组）
- `pattern_decisions` 中每个元素含: `pattern_id`（匹配 `^[A-Z]+[0-9]+$`）, `confidence`（high|medium|low）, `rationale`（非空字符串）

**agent-spec.md (CLAUDE.md)**
- 必须包含全部 8 个章节（按 spec-assembler.yaml 的 spec_sections）
- 章节标题格式: 匹配 `^## [一二三四五六七八]、` 格式
- 每章节 >= 100 字符

**review_report.md**
- 必须包含 `reviewer_id`, `timestamp`, `verdict` (PASS|FAIL), `findings[]`（非空数组）
- `findings` 中每个元素含: `severity`（必须是 CRITICAL|HIGH|MEDIUM|LOW 之一）, `chapter`, `description`

**verification-report.md**
- 必须包含 `verdict` (PASS|FAIL), `pass_count` (N/7), `fail_count` (M/7), `failed_checks[]`, `details[]`
- `pass_count + fail_count` 必须等于 7
- `details` 中每个元素含: `check_name`, `status`, `issue_description`, `fix_target`

**diagnosis_report.md**
- 必须包含 `diagnosis_id`, `timestamp`, `symptom`, `failed_pattern`（必须在27个模式名中）, `root_cause`, `fix_direction`, `confidence`

**progress_state.yaml**
- 必须包含 `current_state`（枚举：IDLE/PHASE_1~PHASE_5/PLAN_MODE/DONE）, `phase_history`（非空数组）, `active_target`
- 每条 phase_history 记录含: `phase`, `pipeline`, `target`, `verdict`, `artifact`, `artifact_sha256`, `timestamp`, `retry_count`

### 字段级校验规则汇总

| 文件 | 关键字段 | 校验规则 |
|------|---------|---------|
| matching_decision.md | pattern_id | `^[A-Z]+[0-9]+$` |
| matching_decision.md | confidence | `high\|medium\|low` |
| matching_decision.md | rationale | 非空字符串 |
| agent-spec.md | 章节标题 | `^## [一二三四五六七八九十]、` |
| agent-spec.md | 章节数 | 8章齐全 |
| review_report.md | severity | `CRITICAL\|HIGH\|MEDIUM\|LOW` |
| review_report.md | verdict | `PASS\|FAIL` |
| verification-report.md | verdict | `PASS\|FAIL` |
| verification-report.md | pass_count | `[0-7]/7` |
| verification-report.md | fail_count | `[0-7]/7` |
| diagnosis_report.md | failed_pattern | 在27个catalog模式名中 |

### 通用规则

- 所有输出使用 UTF-8 编码的 Markdown
- 禁止残留 `{{placeholder}}` 或 TODO/TBD 占位符
- 禁止空章节或空字段

---

## 可追溯性要求 DP1

每个 Spec 字段必须标注来源模式，确保审计者可以：
- 从 Spec 字段反向查找生成它的**模板变量**
- 从模板变量反向查找填充值的来源（`user_input` / `derived` / `llm_generate` / `decision_table`）

具体追溯链路：

```
Spec字段 [来源: W1]
  → W1.template.md → {{variable_name}}
    → spec-assembler.yaml → fill_strategy: user_input|derived|llm_generate|decision_table
      → 原始来源（用户需求 / 推导 / LLM生成 / 决策表）
```

其他追溯要求：
- `matching_decision.md` 中的每个模式决策标注触发的 **indicators**（从 pattern-matcher.yaml 来）
- `diagnosis_report.md` 标注诊断依据（从 problem-diagnoser.yaml 的 **causal_chain** 来）

---

## 数据一致性约束

以下跨文件/跨章节的一致性约束必须满足：

1. **I/O ↔ Data Flow 闭合**：I/O Contract 中声明的输出文件必须在 Data Flow 实体表中有对应数据实体
2. **Flow ↔ Entity 一致**：数据流转图中引用的每个文件路径必须在数据实体表中声明，且生产者和消费者一致
3. **Checksum 一致**：`verification-report.md` 中的 `pass_count + fail_count == 7`
4. **Verdict 一致**：`verification-report.md` 的 `verdict` 必须与实际检查结果一致（全 PASS → PASS，否则 → FAIL）
5. **模式引用闭合**：`matching_decision.md` 中的所有 `pattern_id` 必须在 `pattern-catalog.yaml` 的27个模式中可查找
6. **无悬空实体**：数据实体表中的每个实体必须至少有一个生产者和一个消费者
