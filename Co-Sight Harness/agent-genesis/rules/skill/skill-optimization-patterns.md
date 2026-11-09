# Skill 优化模式

> **权威声明**: skill 粒度/拆分判定以 `knowledge/skill/skill-creation-guide.yaml` §2 G1/G2 为唯一权威;
> 本文件只管**优化手法**（已存在的 skill 如何改好），不做粒度裁决——双源冲突时以 creation-guide 为准。
> 适用: Skill Foundry step-s1 (optimize 模式诊断参考) + step-s4 (optimize 模式执行)
> 加载者: skill-planner（optimize 模式）, skill-builder（optimize 模式）
> 参考: 5GNR-Analyst410 "用户需求分析 Skill 改造" 实战案例（12 步单体 → Orchestrator + 3 SubAgent + 4 Command + 4 Hook）

---

## 模式速查

| # | 模式 | 适用诊断维度 | 核心操作 | 风险级别 |
|:--:|------|:---:|---------|:---:|
| 1 | 单体拆解 (Pipeline Decomposition) | Decomposition | 提取步骤为 SubAgent，Orchestrator 调度 | HIGH |
| 2 | 文档系统 (Document System) | Information | 文件系统替代 context 传数据 | MEDIUM |
| 3 | 确定性命令 (Deterministic Commands) | Verification | Python/Bash 脚本做 LLM 不擅长的事 | LOW |
| 4 | Hook 门禁 (Hook Gates) | Verification | 步骤间插 Hook 检查，阻断错误传播 | MEDIUM |
| 5 | 状态追踪 (State Tracking) | State | 任务状态文件 + checkpoint | LOW |
| 6 | Review Agent (Independent Review) | Verification | 独立审查 Agent，game mechanism 反馈 | MEDIUM |
| 7 | 形态重构 (Design Form Restructure) | Design Form | 按 Anthropic 规范重建目录分层和渐进加载 | MEDIUM |
| 8 | 全局对齐 (Global Alignment) | Global Context | 修正与 Agent 设计原则的偏离 | MEDIUM |
| 9 | Skill 拆分 (Skill Splitting) | Decomposition + Global Context | 大型 Skill 拆为多个独立 Skill + Agent 调用流更新 | HIGH |
| 10 | 跨 Skill 重组 (Cross-Skill Reorganization) | Design Form + Global Context | 多 Skill 合并/重分配/职责矩阵 | HIGH |
| 11 | 批量优化 (Batch Optimization) | 多维度（跨 Skill） | 多个 Skill 同时诊断、协调优化、冲突检测 | HIGH |

---

## 模式 1: 单体拆解 (Pipeline Decomposition)

### 适用场景

- Skill 包含 8+ 个有依赖关系的步骤
- 整体执行质量随步骤推进明显衰减
- 不同步骤需要不同的工具权限或知识域
- 修改一个步骤需要重新执行全部

### 实施步骤

1. 划分阶段 — 将步骤按职责聚类为 2-5 个阶段（如 分析 / 构建 / 审查 / 验证）
2. 定义 I/O 契约 — 每个阶段明确输入文件、输出文件、校验规则
3. 提取 SubAgent — 每个阶段创建一个 SubAgent 定义（agents/）
4. 创建 Orchestrator — 主 Agent 负责调度，按 I/O 契约串联
5. 文件落盘传数据 — 阶段间用文件传递数据（而非 context），避免上下文膨胀

### 参考案例

> 5GNR-Analyst410: 用户需求分析 Skill 改造方案将 12 步单体 Skill 拆为：
> - SubAgent 1: 需求解析（读取原始文档 → 结构化需求条目）
> - SubAgent 2: 方案设计（需求条目 → 设计文档 + Mermaid 图）
> - SubAgent 3: 审查验证（审查设计文档，回压修正）
> - Orchestrator: 调度 3 个 SubAgent，管理状态文件，处理 Escalation

### Before/After

```
Before (单体):
  SKILL.md (800+ 行)
    ├── Step 1-12 全部内联
    └── 所有知识在一个 context 中加载

After (Pipeline):
  SKILL.md (150 行, Orchestrator)
    ├── SubAgent: analyzer-agent (需求解析)
    ├── SubAgent: designer-agent (方案设计)
    └── SubAgent: reviewer-agent (审查验证)
```

### 风险

- 文件 I/O 开销增加（每次 SubAgent spawn 需要读取输入文件）
- Orchestrator 调度逻辑复杂度上升
- 需确保 SubAgent 独立可测试

---

## 模式 2: 文档系统建立 (Document System)

### 适用场景

- Skill 需要加载大量上下文知识（>500 行）
- 步骤间需要传递大块结构化数据
- 不同执行间需要参考相同的权威文档
- 上下文窗口压力大，影响输出质量

### 实施步骤

1. 建立输入区 — `input/` 或 `knowledge/` 目录，放权威参考文档
2. 建立中间产物区 — `work/` 目录，每个步骤输出独立文件
3. 建立状态文件 — 记录执行进度、阶段、checkpoint
4. Skill 中引用文件路径，不内联内容 — `Read knowledge/xxx.md` 替代大段内联文本
5. 加载策略分层 — L2 独立文件 + L3 按需 Skill

### 参考案例

> 5GNR-Analyst410 使用 `knowledge/` 目录存放 3GPP 规范摘要、术语表、格式模板。
> 中间产物以独立文件存在（01-raw-requirements.md → 02-structured-requirements.md → ... → 12-final-output.md），
> 每步只加载上一步的输出文件，而非全量 context。

### 风险

- 文件数量增多，需维护文件引用闭合性
- 磁盘 I/O 增加（LLM 需多次 Read 调用）

---

## 模式 3: 确定性命令引入 (Deterministic Commands)

### 适用场景

- LLM 在精确比对、语法校验、格式转换上出错
- 某些操作需要确定性结果（如 JSON Schema 校验、Mermaid 语法检查）
- 操作涉及数学计算、正则匹配、文件格式转换等 LLM 不擅长的领域

### 实施步骤

1. 识别非确定性步骤 — 找 LLM 频繁出错的具体操作
2. 写成确定性脚本 — Python/Bash 脚本，单一职责
3. 注册为 Command — `commands/` 或 Hook
4. Skill 中改为调用脚本 — 用 Bash 工具调用脚本替代 LLM 推理
5. 脚本返回结构化结果 — JSON 或明确的 exit code，便于后续步骤消费

### Before/After

```
Before:
  LLM: "检查 Mermaid 语法是否正确" → 输出: "看起来没问题" (不准确)

After:
  Bash: python scripts/verify_mermaid.py work/design.md
  → exit code 1, 报: "Line 42: C --> D 缺少箭头方向"
```

### 风险

- 脚本需要维护（语言、依赖、跨平台兼容）
- 适用范围限于确定性任务

---

## 模式 4: Hook 门禁织入 (Hook Gates)

### 适用场景

- 步骤间缺少质量关卡，错误向下传播
- 某个步骤的输出是后续步骤的关键依赖
- 需要在特定操作后自动触发校验

### 实施步骤

1. 选择 Hook 类型 — PostToolUse（工具执行后）最常用；PreToolUse（工具执行前）用于门禁
2. 定义门禁规则 — 什么条件下阻断 / 什么条件下放行
3. 定义失败行为 — 重试（≤3 次）/ 阻断等待人工 / 自动降级
4. 绑定到关键步骤 — 在 SKILL.md 中声明 Hook 触发点
5. Hook 输出结构化 — 便于调用方判断 PASS/FAIL

### 参考案例

> 5GNR-Analyst410: SubAgent1（需求解析）输出后 → PostToolUse Hook 自动校验 Mermaid 语法。
> 失败: 重试 3 次 → 仍失败则阻断，通知用户手动修复。

### 风险

- Hook 过多影响执行效率
- 需要定义清晰的阻断升级策略

---

## 模式 5: 状态追踪 (State Tracking)

### 适用场景

- Skill 执行链路长（6+ 步骤）
- 中断后不知道从哪里恢复
- 需要知道"当前做到哪步了""哪些已完成"
- 多 Agent 协作时需要协调状态

### 实施步骤

1. 创建状态文件 — `work/task-status.md`（用户可读）+ `work/task-state.json`（机器可读）
2. 定义 checkpoint — 每个步骤开始前更新状态为 IN_PROGRESS，完成后更新为 DONE
3. 启动时检查状态 — Skill 启动时读取状态文件，跳过 DONE 步骤
4. 失败标记 — 步骤失败时记录 FAILED + 错误信息
5. 恢复逻辑 — 支持从指定 checkpoint 恢复执行

### Before/After

```
Before:
  中断 → 重新从头执行全部步骤

After:
  中断 → 读取 work/task-status.md
  ├── Step 1-3: DONE → 跳过
  ├── Step 4: FAILED → 从 Step 4 恢复
  └── Step 5-12: PENDING
```

### 风险

- 状态文件格式需要严格定义，避免解析错误
- 并发执行时需考虑锁机制

---

## 模式 6: Review Agent 引入 (Independent Review)

### 适用场景

- 最终输出全靠人工检查，成本高
- 输出质量不稳定，缺少自动化质量评估
- 自审不可靠（LLM 难以发现自身错误）

### 实施步骤

1. 定义审查维度 — 如：完整性、准确性、格式合规、安全性
2. 创建 Review Agent — 独立 Agent 定义（agents/），内存隔离
3. 建立审查规则库 — 每项维度的具体检查标准和示例
4. 定义回压机制 — Review FAIL → 返回生成 Agent 修正 → 重审（≤2 轮）
5. Game mechanism — Review Agent 不知道生成 Agent 的内部决策，保持独立视角

### Before/After

```
Before:
  Creator → 输出 → 用户人工检查 → 发现问题 → 手动返回修改

After:
  Creator → 输出 → Review Agent (自动)
    ├── PASS → 交付用户
    └── FAIL → 回压 Creator → 修正 → Review Agent (重审)
```

### 风险

- 增加执行时间和 token 消耗
- Review Agent 自身也需要规则维护

---

## 模式 7: 形态重构 (Design Form Restructure) — 基础性前置模式

> **FOUNDATIONAL**: 此模式通常是其他优化的**前置条件**。当 Skill 存在参考文档/脚本/模板等内容时，应先建立符合 Anthropic 规范的目录分层骨架（references/ + scripts/ + templates/ + 渐进式加载）。精简 Skill（无此类内容）可跳过分层。

### 适用场景

- SKILL.md 过长（>500 行），所有内容内联在单个文件
- 有参考文档/脚本/模板等内容但未分层到对应目录
- description 模糊，无法准确触发
- 代码示例或脚本嵌入在 Markdown 中，难以独立测试
- 文件组织混乱，引用路径依赖硬编码

### 实施步骤

1. 审计现有结构 — 列出 SKILL.md 中所有内容块，按类型分类（核心指令 / 详细文档 / 可执行脚本 / 输入输出模板）
2. 按 Anthropic 规范分层:
   - L1: SKILL.md — 保留 name + description（含触发条件）+ 核心指令（≤300 行）
   - L2: references/ — 提取详细文档、规范说明、领域知识
   - L3: scripts/ — 提取可执行脚本，确保可独立运行和测试
   - 辅助: templates/ — 创建可复用的输入/输出模板
3. 优化 description — 使用公式: `「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」`
4. 校验引用链 — 确保 references/ 和 templates/ 中的每个文件都被 SKILL.md 引用
5. 清理孤立文件 — 删除未被任何入口引用的文件

### Before/After

```
Before (单体扁平):
  SKILL.md (800+ 行)
    ├── description: "帮助处理代码"（过于宽泛）
    ├── 大量代码示例内联
    ├── 冗长的参考文档
    └── 无分层

After (Anthropic 规范):
  SKILL.md (200 行)
    ├── description: "Python 代码审查：检查 PEP8、安全问题、性能模式。当用户请求代码审查时触发。输入为文件路径或 diff，输出 Markdown 审查报告。"
    ├── 核心审查指令
    └── 引用: 见 references/pep8-guide.md，见 scripts/verify_pep8.py
  references/
    ├── pep8-guide.md
    ├── security-checklist.md
    └── performance-patterns.md
  scripts/
    └── verify_pep8.py（可独立运行）
  templates/
    └── review-report-template.md
```

### 风险

- 分层后文件数量增加，需维护引用闭合性
- 提取到 scripts/ 的脚本需同步维护测试
- 渐进式加载需要 Agent 支持 L2/L3 策略

---

## 模式 8: 全局对齐 (Global Alignment)

### 适用场景

- Skill 的行为与 **Agent Role 定义**不一致
- 工具调用超出 **Agent 权限白名单**
- 中间文件路径与 **Agent 约定**冲突
- Skill 自审代替 **Agent G1 审查**
- 状态管理与 **Agent 全局状态机**不同步

> **对齐目标**: Agent 的 CLAUDE.md 中定义的 Role & Boundaries、I/O Contract、Safety Constraints、State Machine、文件系统约定。**不是**同目录下其他 Skill 的结构或风格。详见 [skill-diagnosis-rules.md §6.5](../skill-optimization/skill-diagnosis-rules.md#65-反模式-姐妹-skill-结构对齐禁止)。

### 实施步骤

1. 读取 Agent CLAUDE.md — 提取 Role & Boundaries、Safety Constraints、I/O Contract、State Machine
2. 逐项对照检查 — 使用 Global Context 检查清单（GC-1 至 GC-8）
3. 标记偏离点 — 每项偏离记录偏离类型 + 影响 + 修正建议
4. 修正 Skill 定义:
   - Role 不一致 → 调整职责描述，确保不越权
   - Tool 超权 → 移除未授权工具调用，或建议 Agent 扩展白名单
   - 路径冲突 → 统一为 Agent work/ 约定路径
   - 审查绕过 → 移除 Skill 内自审，标记为需经 G1
   - 状态不同步 → 对齐 checkpoint 命名和位置
5. 输出对齐报告 — 修正项列表 + Before/After 对比

### Before/After

```
Before (偏离):
  Skill: code-reviewer/SKILL.md
    ├── 自称 "最终审查权威" → 与 Agent Reviewer Gate (G1) 冲突
    ├── 输出到 /tmp/review/ → 与 Agent work/ 约定不符
    └── 自行判断 PASS/FAIL → 绕过 Agent Plan Mode 审批

After (对齐):
  Skill: code-reviewer/SKILL.md
    ├── 定位为 "辅助审查工具，结果供 G1 Reviewer 消费"
    ├── 输出到 work/{agent-name}/review-draft.md
    └── 标注置信度，由 G1 做最终 PASS/FAIL 判定
```

### 禁止行为

| 反模式 | 说明 |
|--------|------|
| 对齐姐妹 Skill 的行数 | 每个 Skill 的行数由其功能复杂度决定 |
| 对齐姐妹 Skill 的目录结构 | references/ 是否需要取决于 Skill 自身知识量 |
| 对齐姐妹 Skill 的步骤格式 | 步骤描述格式由 Skill 自身语义决定 |
| 对齐姐妹 Skill 的分解粒度 | 是否拆分取决于单 Skill 的复杂度和耦合度 |

### 风险

- 对齐可能导致 Skill 功能缩减（需与 Agent 扩展白名单配合）
- 多 Skill 同时对齐时需协调修改顺序 — **仅限功能性冲突，不含结构对齐**

---

## 模式 9: Skill 拆分 (Skill Splitting)

### 适用场景

- 单个 SKILL.md 超过 800 行，内容涵盖 2+ 个独立功能域
- 不同触发条件下执行完全不同的步骤分支
- 用户反馈 "这个 Skill 太大，不知道什么时候该用它"
- 不同步骤依赖不同的工具权限或知识域
- 诊断维度 Decomposition + Global Context 同时 FAIL

### 实施步骤

1. 功能域识别 — 分析 SKILL.md 中的功能聚类，列出候选子 Skill 及其职责边界
2. 职责矩阵定义 — 明确拆分后各 Skill 的独占职责，确保无重叠
3. 依赖分析 — 标注 Skill 间调用关系（A 的输出是 B 的输入？独立？）
4. 命名每个子 Skill — 使用 kebab-case + 领域关键词，确保具象化
5. 生成各子 Skill 的 SKILL.md — 各自包含 name + description + 核心指令 + 分层资源
6. **生成 Agent 调用流更新提示** — 标注原 Agent CLAUDE.md 或 Skill 引用中需要修改的调用点:
   - 原 `/skill original-skill` → 新调用流（顺序/并行/条件）
   - 如有 Orchestrator → 更新 SubAgent 调度表
   - 如触发条件变更 → 更新 description 中的触发词
7. 输出拆分报告 — 含职责矩阵 + 调用流变更提示 + 迁移步骤

### Before/After

```
Before (巨型单体):
  deploy-manager/SKILL.md (950 行)
    ├── 构建检查
    ├── 测试执行
    ├── 部署到各环境
    ├── 健康检查
    └── 回滚操作

After (拆分):
  deploy-manager/
    ├── deploy-build/SKILL.md          # 构建 + 构建检查
    ├── deploy-test/SKILL.md           # 测试执行 + 结果分析
    ├── deploy-release/SKILL.md        # 部署 + 健康检查
    └── deploy-rollback/SKILL.md       # 回滚操作

  调用流变更提示:
    原: /deploy-manager（一个命令执行全部）
    新: Orchestrator 调度:
      1. /deploy-build → 产出构建产物
      2. /deploy-test → 测试构建产物
      3. /deploy-release → 部署（依赖 1+2 PASS）
      4. /deploy-rollback → 仅失败时触发
```

### 风险

- 拆分后调用复杂度上升（需 Orchestrator 或调用流协调）
- 子 Skill 间的 I/O Contract 需严格定义
- 版本管理：需决定子 Skill 是独立版本还是共同版本
- Agent 调用流需同步更新（提供提示但需用户确认修改）

---

## 模式 10: 跨 Skill 重组 (Cross-Skill Reorganization)

> **WARNING**: 此模式仅处理 Skill 间的 **功能性冲突**（输出路径碰撞、依赖循环、触发词歧义、共享资源提取）。**不得**用于对齐 Skill 间的结构、风格、行数、分解粒度或命名约定。Skill 是独立功能单元，结构差异是正常且预期的。详见 [skill-diagnosis-rules.md §6.5](../skill-optimization/skill-diagnosis-rules.md#65-反模式-姐妹-skill-结构对齐禁止)。

### 适用场景

- 多 Skill 间存在**功能重叠**（相同逻辑出现在 2+ 个 Skill 中导致 DRY 违反）
- 某个 Skill 的一部分步骤**更适合归属到另一个 Skill**（功能性错位）
- 多个 Skill 共享**相同的 references/ 或 scripts/** 但各自维护副本，提取到 Agent 级共享位置
- 两个 Skill 写入**同一输出路径**产生文件冲突

### 实施步骤

1. 多 Skill 联合诊断 — 读取所有相关 SKILL.md，建立功能×Skill 覆盖矩阵
2. 识别重叠/冗余 — 标注相同功能出现在哪些 Skill 中，评估 DRY 违反程度
3. 确定重组策略:
   - **合并**: 功能高度重叠 → 合并为一个 Skill，区分配置参数
   - **重分配**: 步骤放错 Skill → 将步骤迁移到更合适的 Skill
   - **提取共享**: 相同 references/scripts → 提取到公共位置（如 Agent 级 knowledge/ 或 scripts/）
   - **职责矩阵**: 输出新的 Skill×Function 矩阵，明确每个 Skill 的独占职责
4. 逐 Skill 执行修改 — 按依赖顺序修改各 SKILL.md
5. 更新交叉引用 — 确保各 Skill 间的引用（如"由 X Skill 产出"）更新为最新
6. **生成 Agent 调用流更新提示** — 标注触发条件变化、调用顺序变化

### Before/After

```
Before (功能重叠):
  security-scanner/SKILL.md  ── 包含「依赖扫描」功能
  dependency-checker/SKILL.md ── 也包含「依赖扫描」功能（重复！）

After (重组):
  方案 A — 合并:
    dependency-security/SKILL.md
      ├── 依赖扫描（合并去重）
      ├── 安全漏洞扫描
      └── 通过配置决定执行哪些检查

  方案 B — 重分配:
    security-scanner/SKILL.md     → 移除「依赖扫描」，专注「代码安全检查」
    dependency-checker/SKILL.md   → 保留「依赖扫描」，增强为唯一入口
    → 安全扫描中如需依赖信息，引用 dependency-checker 的输出

  方案 C — 提取共享:
    shared/references/dependency-scan-guide.md  ← 公共参考
    security-scanner/SKILL.md    → Read shared/references/...
    dependency-checker/SKILL.md  → Read shared/references/...
```

### 风险

- 合并可能产生新的巨型 Skill（需评估合并后行数）
- 重分配需要同步更新所有引用该 Skill 的调用方
- 提取共享资源需要约定公共目录位置（Agent 级决策）

---

## 模式 11: 批量优化 (Batch Optimization)

> **WARNING**: 批量优化协调的是 **I/O Contract 变更、输出路径冲突、依赖链完整性**，不是 Skill 间的结构或风格统一。每个 Skill 独立诊断、独立优化，仅在功能性交叉点协调。不得将姐妹 Skill 的结构作为优化的目标模板。

### 适用场景

- 用户一次提交 2+ 个 Skill 需要优化
- 多 Skill 间存在**隐含的调用依赖或数据流关系**（非结构相似性）
- 单个 Skill 的 I/O 变更可能影响其他 Skill 的输入
- 需要在全局视角下检测输出路径冲突和依赖断裂

### 实施步骤

1. 批量诊断 — 对每个目标 Skill 执行 6 维诊断，生成独立诊断报告
2. 跨 Skill 影响分析:
   - 建立 Skill×Skill 依赖矩阵（调用/数据/文件依赖）
   - 标注每个 Skill 优化的变更范围和可能影响的 Skill
   - 检测冲突（如 Skill A 的输出路径恰好是 Skill B 的输入路径）
3. 全局优化优先级排序:
   - 被依赖最多的 Skill 优先优化（底层变更影响面大）
   - 独立 Skill 可并行优化
   - 有冲突的 Skill 编组优化
4. 协调优化方案:
   - 制定全局 I/O Contract 更新计划（如有变更）
   - 确保中间文件路径一致
   - 确保优化后调用链不断裂
5. 分批执行 — 按优先级顺序执行优化，每组完成后验证跨 Skill 引用
6. **输出批量优化报告** — 含每个 Skill 的优化摘要 + 跨 Skill 影响矩阵 + 调用流变更汇总

### Before/After

```
Before (3 个 Skill 独立优化):
  Skill A 优化 → 输出路径从 /tmp/ 改为 work/
  Skill B 优化 → 仍读 /tmp/（断裂！）
  Skill C 优化 → 独立修改，无感知

After (批量优化, 全局协调):
  1. 诊断 3 个 Skill → 发现依赖链: A 输出 → B 消费 → C 汇总
  2. 优先级: B 先优化（输出格式定义）→ A 适配新格式 → C 最后（汇总两端）
  3. 全局 I/O Contract:
     - A: 输出 work/analysis-result.md（格式由 B 定义）
     - B: 读 work/analysis-result.md，输出 work/review-report.md
     - C: 读 work/analysis-result.md + work/review-report.md，输出 work/summary.md
  4. 每步验证引用闭合 → 3 个 Skill 全部通过
```

### 风险

- 批量修改范围大，需更谨慎的版本管理和回滚策略
- 跨 Skill 依赖分析可能遗漏隐式依赖（如通过文件系统而非显式引用）
- 执行时间长，需 Checkpoint 支持中断恢复

---

## 模式组合指南

### 基础层: Design Form 优先

> **原则**: Pattern 7（形态重构）是大多数优化的前置步骤。在有需分层内容时，应先建立目录分层骨架，再执行功能层面的模式组合。精简 Skill 可跳过此步。

| 前置 | 后续组合 | 说明 |
|:----:|---------|------|
| **7** | → 1+2 | 先建立分层骨架 → 再拆解为 SubAgent + 文档系统 |
| **7** | → 3+4 | 先建立 scripts/ 目录 → 再引入确定性脚本 + Hook 门禁 |
| **7** | → 2+5 | 先建立 references/ + work/ 约定 → 再搭建文档系统 + 状态追踪 |
| **7** | → 6 | 先规范化 Skill 形态 → 再引入独立 Review Agent |
| **7** | → 9 | 先分层 → 再决定是否拆分（分层后职责边界更清晰） |

### 功能层: 模式组合

常配对使用的模式：

| 组合 | 适用场景 | 说明 |
|------|---------|------|
| 1+2 | 大单体 Skill 拆分 | 拆解为 SubAgent + 文档系统传递数据 |
| 1+6 | Multi-Agent Pipeline | 拆解后引入独立审查 Agent |
| 3+4 | 确定性质量门禁 | 脚本做检查 + Hook 自动化触发 |
| 2+5 | 长链路执行 | 文档系统存中间产物 + 状态追踪记录进度 |
| 7+8 | Skill 规范化 + Agent 对齐 | 先按 Anthropic 规范重构形态，再对齐 Agent 全局设计 |
| 2+7 | 文档系统化 + 形态重构 | 提取知识到 references/ + 建立渐进加载 |
| 9+10 | 拆分 + 跨 Skill 重组 | 拆分大型 Skill 后协调新旧 Skill 的关系 |
| 9+8 | 拆分 + 全局对齐 | 拆分后逐个子 Skill 对齐 Agent 设计原则 |
| 10+11 | 批量重组 | 多 Skill 提交时先重组后批量验证 |
| 1+2+5+6 | 完整 Multi-Agent 改造 | 拆解 + 文档 + 状态 + 审查 四位一体 |
| 7+8+9+11 | 全面 Skill 优化 | 形态重构 + 全局对齐 + 拆分 + 批量协调 |

## 禁止模式

- **禁止全量重写** — 不论问题多严重，不重写整个 SKILL.md。应增量修改（参考 rules/shared/delta-modification-rules.md）
- **禁止过度拆解** — 3 步能完成的不要拆成 5 个 SubAgent
- **禁止无审查拆解** — 拆解为 Multi-Agent 必须配套 Reviewer（G1），防止引入新问题
- **禁止无调用流更新的拆分** — 拆分 Skill 必须提供 Agent 调用流变更提示（模式 9/10），否则下游断裂
- **禁止忽略跨 Skill 影响的孤立优化** — 当输入涉及多个 Skill 时，必须检查 Skill 间依赖（模式 10/11），不能逐个孤立处理
- **禁止姐妹 Skill 结构对齐** — 不得以同目录下其他 Skill 的行数、目录结构、步骤格式、分解粒度作为优化目标。Skill 是独立功能单元，结构差异正常且预期。对齐目标只能是 Agent CLAUDE.md（详见 skill-diagnosis-rules.md §6.5）
