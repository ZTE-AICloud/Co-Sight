# pr-security-reviewer — Build Workflow

> 本文件由 build-planner 生成，记录 Agent 构建步骤与 knowledge 依赖。
> 格式遵循 design/workflow-md-schema.md；运行时使用见 CLAUDE.md。

## Phase 1: 身份与规则

### 步骤 1: 生成 CLAUDE.md
- knowledge: agent-genesis::knowledge/agent-creation/spec-assembler.yaml, clarified-agent-requirements.yaml, phase1-matching-decision.md
- 意图: 8 章 Spec，锁定 Role/边界/K4 知识契约/CD3 边界/Safety/Data Flow

### 步骤 2: 生成 OWASP 规则库
- knowledge: agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml
- 意图: `.claude/rules/owasp-top10.md`，裁剪为 diff 可判定视角（K4 权威源 + CD3 边界依据）

## Phase 2: 审查维度

### 步骤 3: 生成三维检查清单与报告格式规则
- knowledge: .claude/rules/owasp-top10.md
- 意图: review-checklist.md（G1 审查项）+ report-format.md（DF1 字段语义）

### 步骤 4: 生成三个审查 SubAgent
- knowledge: .claude/rules/owasp-top10.md, .claude/rules/report-format.md, adapted-assets.yaml
- 意图: security/perf/maintainability-reviewer，独立 context + forbidden_inputs（G018）+ Write（G020）

## Phase 3: 输出规范

### 步骤 5: 生成 DF1 Schema 与 diff 解析 Skill
- knowledge: .claude/rules/report-format.md
- 意图: review-report.schema.json（CI 消费契约）+ parse-git-diff SKILL.md（DT1 数据传递基础）

## Phase 4: 验证

### 步骤 6: 生成测试资产与权限配置
- knowledge: .claude/schemas/review-report.schema.json
- 意图: 含真实漏洞模式的样例 diff + pass-criteria.md + settings.local.json（CD2 权限收敛）
