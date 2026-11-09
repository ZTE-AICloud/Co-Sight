# Skill 优化方案: {skill-name}

> 生成时间: {ISO8601-timestamp}
> 状态: WAITING FOR CONFIRMATION
> Spec ID: opt-{skill-name}-{timestamp}
> pipeline_mode: optimize-skill
> 生成者: Main Agent (Plan Mode)

---

## 1. 诊断摘要

**来源**: phase1-diagnosis-report.md + phase2-review.md

| 维度 | 诊断状态 | 审查确认 | 严重级别 | 关键发现（一句话） |
|------|:--------:|:--------:|:------:|-------------------|
| Decomposition | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| Information | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| State | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| Verification | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| Logic Consistency | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| Design Form | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |
| Global Context | {PASS/FAIL} | {PASS/FAIL/WARN} | {—/CRIT/HIGH/MED/LOW} | {描述} |

### Top 3 问题（按严重级别排序）

1. **{问题标题}** — 严重级别: {CRITICAL/HIGH}
   - 根因: {从诊断报告引用}
   - 影响: {对 Skill 执行质量的具体影响}

2. **{问题标题}** — 严重级别: {CRITICAL/HIGH}
   - 根因: {从诊断报告引用}
   - 影响: {对 Skill 执行质量的具体影响}

3. **{问题标题}** — 严重级别: {HIGH/MEDIUM}
   - 根因: {从诊断报告引用}
   - 影响: {对 Skill 执行质量的具体影响}

---

## 2. Design Form 基础评估（优先）

> Design Form 是基础性维度。结构分层建立之前，不执行功能层面的优化。

| 强制检查 | 通过标准 | 当前状态 | 目标状态 | 证据 |
|---------|---------|---------|---------|------|
| DF-M1 目录分层 | 有需分层内容时应有 references/scripts/templates 目录 | {现状描述} | {目标描述} | {SKILL.md 行号} |
| DF-M2 渐进式加载 | SKILL.md 不内联 >100 行的参考文档或代码块 | {现状描述} | {目标描述} | {SKILL.md 行号} |
| DF-M3 描述公式 | description 含「做什么」+「何时触发」+「输入」+「输出」 | {当前 description 原文} | {目标 description 草案} | {SKILL.md 行号} |
| DF-M4 脚本独立 | 有确定性操作时应通过 Bash 调用 scripts/ 脚本 | {现状描述} | {目标描述} | {SKILL.md 行号} |

---

## 3. 优化模式选择

### 3.1 选中模式

| 层级 | 模式 | 编号 | 适用理由（为什么选这个） |
|------|------|:----:|------------------------|
| 基础层 | 形态重构 | Pattern 7 | {为什么需要 — 如 SKILL.md 过长/无分层} |
| 功能层 | {模式名称} | Pattern {N} | {对应诊断维度 + 根因} |
| 协调层 | {模式名称} | Pattern {N} | {如适用} |
| 对齐层 | {模式名称} | Pattern {N} | {如适用} |

### 3.2 模式组合策略

```
{描述模式执行顺序和依赖关系，如:}
Pattern 7 (形态重构) → 建立目录分层
  → Pattern 3 (确定性命令): 提取脚本到 scripts/
  → Pattern 2 (文档系统): 外置知识到 references/
  → Pattern 8 (全局对齐): 修正 description 和 GC 偏离
```

### 3.3 未选模式及理由

| 模式 | 未选理由 |
|------|---------|
| Pattern 1 (单体拆解) | {如: 步骤数 < 8，不需要拆 SubAgent} |
| Pattern 9 (Skill 拆分) | {如: 行数 < 800，无独立功能域} |

---

## 4. Before/After 对比

### 4.1 当前结构 (Before)

```
{skill-dir}/
└── SKILL.md ({N} 行)
    ├── {当前内容块 1} ({M} 行)
    ├── {当前内容块 2} ({M} 行)
    └── {当前内容块 3} ({M} 行)
```

### 4.2 优化后结构 (After)

```
{skill-dir}/
├── SKILL.md ({N} 行, 仅核心指令)
│   ├── L1: name + description (公式化)
│   └── L2: 核心执行步骤 + L3 引用
├── references/
│   └── {引用文档}
├── scripts/
│   └── {确定性脚本}
└── templates/
    └── {输入/输出模板}
```

### 4.3 关键差异

| 方面 | Before | After | 变更原因 |
|------|--------|-------|---------|
| SKILL.md 行数 | {N} 行 | ~{N} 行 | {原因} |
| description | "{原文}" | "{新草案}" | {DF-M3} |
| 内联参考 | {M} 行内联 | references/ 外置 | {DF-M2} |
| 确定性操作 | LLM 推理 | scripts/ 脚本 | {DF-M4} |

---

## 5. 文件级变更清单

> 每个变更精确到文件 + 行号范围，供 skill-builder-agent 逐条执行。

### 5.1 SKILL.md 修改

| # | 文件 | 操作 | 变更范围 | 具体内容 | 对应诊断发现 |
|:--:|------|------|---------|---------|-------------|
| 1 | SKILL.md | 修改 | L{N}-{M} ({章节名}) | {从什么改为什么，或新增什么内容} | {诊断报告中的发现 ID} |
| 2 | SKILL.md | 修改 | L{N}-{M} ({章节名}) | {具体变更描述} | {诊断报告中的发现 ID} |
| 3 | SKILL.md | 删除 | L{N}-{M} ({章节名}) | {删除原因，内容迁移到何处} | {诊断报告中的发现 ID} |
| 4 | SKILL.md | 追加 | L{N} 之后 | {新增内容摘要} | {诊断报告中的发现 ID} |

### 5.2 新增文件

| # | 文件路径 | 类型 | 内容摘要 | 来源 |
|:--:|---------|------|---------|------|
| 1 | references/{name}.md | L3 参考 | {文件包含什么内容} | {从 SKILL.md 哪部分提取} |
| 2 | scripts/{name}.{ext} | L3 脚本 | {脚本做什么、输入输出} | {诊断发现 + 对应模式} |
| 3 | templates/{name}.md | L3 模板 | {模板用途、占位符说明} | {从 SKILL.md 哪部分提取} |

### 5.3 引用关系图

```
SKILL.md (L2)
  ├── Read references/{name}.md          ← {引用位置: L{N}}
  ├── Bash scripts/{name}.{ext}           ← {引用位置: L{N}}
  └── 模板引用 templates/{name}.md        ← {引用位置: L{N}}
```

### 5.4 多 Skill 场景（如适用）

| Skill | 变更摘要 | 与其他 Skill 关系 |
|-------|---------|-----------------|
| {Skill A} | {N} 项变更 | {被 Skill B 依赖 / 独立} |
| {Skill B} | {M} 项变更 | {依赖 Skill A 的输出} |

---

## 6. 实施步骤与依赖

> 本章节指导 skill-builder-agent 按正确顺序执行变更。

### 6.1 执行顺序

```
Step 1: 新建基础设施文件（无依赖）
  ├── {新增文件 1}
  ├── {新增文件 2}
  └── {新增文件 3}

Step 2: 修改 SKILL.md（依赖 Step 1 完成）
  ├── {变更 1} — 要求 Step 1 中的 {文件} 已存在
  ├── {变更 2} — 要求 Step 1 中的 {文件} 已存在
  └── {变更 3}

Step 3: 清理/删除（依赖 Step 2 完成）
  └── {删除内联内容 — 要求内容已迁移到 L3 文件}

Step 4: 引用链验证（依赖 Step 3 完成）
  └── 验证所有 references/scripts/templates 引用可达
```

### 6.2 依赖矩阵

| 步骤 | 前置依赖 | 阻塞条件（不满足则不可执行） |
|------|---------|---------------------------|
| Step 1 | 无 | — |
| Step 2 | Step 1 完成 | 所有新增文件存在且内容合法 |
| Step 3 | Step 2 完成 | SKILL.md 中内联内容已完全迁移 |
| Step 4 | Step 3 完成 | 所有 grep 引用 test -f 通过 |

### 6.3 增量修改约束

- 每次修改范围 ≤ 2 个 Spec 章节
- 禁止全量重写 SKILL.md
- 每次修改输出三段式 Diff（修改前 → 修改后 + 原因）

---

## 7. 变更验证标准

> 每个变更至少 2 个验证项（1 自动化 + 1 人工）。

### 7.1 自动化验证项

| # | 验证项 | 关联变更 | 验证方法 | 通过标准 |
|:--:|------|---------|---------|---------|
| V-01 | description 含 4 要素 | 5.1 #1 | `grep` 检查 description 字段 | 含「做什么」「何时触发」「输入」「输出」 |
| V-02 | SKILL.md ≤ 300 行 | 5.1 全部 | `wc -l SKILL.md` | ≤ 300 |
| V-03 | 引用链闭合 | 5.2, 5.3 | `grep references/` 路径 + `test -f` | 所有引用文件存在 |
| V-04 | 脚本可独立运行 | 5.2 #2 | `python scripts/{name}.py --help` | exit 0 |
| V-05 | YAML frontmatter 合法 | 5.1 | python yaml.safe_load | 可解析 + 含 name/description |
| V-06 | 无占位符残留 | 5.1 全部 | `grep -c 'TODO\|TBD\|{{'` | == 0 |
| V-07 | 无 LLM 执行确定性操作 | 5.1 | grep 检查精确比对/校验/转换步骤 | 无 |

### 7.2 人工验证项

| # | 验证项 | 关联变更 | 验证方法 | 通过标准 |
|:--:|------|---------|---------|---------|
| M-01 | description 可读性 | 5.1 #1 | 人工阅读 | 非领域专家能理解用途 |
| M-02 | 脚本逻辑正确 | 5.2 #2 | 人工审查代码 | 无逻辑错误，输入输出明确 |
| M-03 | 知识内容准确性 | 5.2 #1 | 对照权威来源 | 无编造或过时信息 |

### 7.3 Phase 4 静态验证映射

| 验证检查 | 对应自动化项 | 对应人工项 |
|---------|-------------|-----------|
| SK-S1 结构完整性 | V-02, V-05 | — |
| SK-S2 引用闭合性 | V-03 | — |
| SK-S3 无占位符 | V-06 | — |
| SK-S7 Design Form | V-01, V-04, V-07 | M-01, M-02 |

---

## 8. 测试场景设计

> 指导 Phase 5 运行时评估的测试用例设计。

### 8.1 E2E 测试用例

| # | 场景名称 | 输入 | 期望输出 | 验证点 | 对应模式 |
|:--:|---------|------|---------|-------|---------|
| E-01 | 正常流程 | {典型输入描述} | {期望输出描述} | {具体验证方法} | Pattern {N} |
| E-02 | 边界情况 | {边界输入描述} | {期望输出描述} | {具体验证方法} | Pattern {N} |
| E-03 | 错误处理 | {错误输入描述} | {期望错误处理} | {不崩溃，返回清晰错误} | — |

### 8.2 回归检测

> 对比优化前后的行为差异，确保优化不引入退化。

| # | 场景 | 优化前行为（问题） | 优化后期望行为 | 检测方法 |
|:--:|------|-------------------|---------------|---------|
| R-01 | {复现诊断中的问题} | {具体的错误表现} | {正确的行为} | {用测试用例复现} |
| R-02 | {另一个退化场景} | {具体表现} | {正确行为} | {检测方法} |

### 8.3  Golden Case 匹配

| golden case ID | 是否匹配 | 匹配/不匹配理由 |
|---------------|:--------:|----------------|
| {从 golden-cases/ 匹配} | {是/否} | {理由} |

---

## 9. 风险评估

| 风险 | 级别 | 影响 | 缓解措施 | 责任人 |
|------|:----:|------|---------|--------|
| {风险描述} | {LOW/MED/HIGH} | {如果发生会怎样} | {如何预防/回退} | {skill-builder / 用户} |

### 9.1 兼容性

- 旧调用方式是否仍可用？{是/否}
- 如不可用，过渡期方案：{描述}
- Skill 名称是否变更？{是/否}
- Agent 调用流是否需要同步更新？{是/否，如是见 §5.4}

---

## 10. 用户补充

> 以下由用户在审批时填写或确认。

- [ ] 方案整体认可
- [ ] 变更范围是否有遗漏
- [ ] 是否有额外约束（如 "不能新增脚本"、"必须保持向后兼容"）
- [ ] 是否需要在特定 Skill 上先行试点

**用户补充约束**:

{用户输入的额外约束，如无则写"无"}

---

## 签名

| 字段 | 值 |
|------|-----|
| Spec 生成引擎 | AgentGenesis Plan Mode |
| 诊断依据 | phase1-diagnosis-report.md + phase2-review.md |
| 设计参考 | skill-design-guide.md, skill-optimization-patterns.md |
| 审查依据 | skill-diagnosis-rules.md, escalation-decision-rules.md |
