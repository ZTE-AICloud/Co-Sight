# adversarial-test-agent — Build Workflow

> 本文件由 build-planner 生成，记录 Agent 构建步骤与 knowledge 依赖。

## Phase 1: 身份与状态机

### 步骤 1: 生成 CLAUDE.md
- knowledge: agent-genesis::knowledge/agent-creation/spec-assembler.yaml, clarified-agent-requirements.yaml, phase1-matching-decision.md
- 意图: 8 章 Spec；核心为 W2 FSM 状态表 + G1 博弈隔离线 + SM1 checkpoint 协议

### 步骤 2: 生成规则与知识资产
- knowledge: agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml
- 意图: mutation-operators.md（K4 算子目录）+ convergence-policy.md（收敛判定）+ pytest-api-notes.md（K2）

## Phase 2: 博弈双 Agent

### 步骤 3: 生成 test-writer 与 mutation-critic
- knowledge: .claude/rules/mutation-operators.md, .claude/rules/convergence-policy.md, adapted-assets.yaml
- 意图: 双向 forbidden_inputs（G1 落地）；critic 带 Bash（跑脚本）而 writer 不带（最小权限）

## Phase 3: 确定性引擎

### 步骤 4: 生成变异与测试运行脚本
- knowledge: .claude/rules/mutation-operators.md
- 意图: mutate.py（AST 变换 + 沙箱路径强制）+ run_tests.py（逐变异体裁决 killed/survived/equivalent-suspect）

### 步骤 5: 生成 DF1 Schema
- knowledge: .claude/rules/convergence-policy.md
- 意图: mutation-report.schema.json（轮次明细 + 击杀率 + partial 语义）

## Phase 4: 验证

### 步骤 6: 生成测试资产与权限配置
- knowledge: .claude/schemas/mutation-report.schema.json
- 意图: 含边界缺陷的 pricing.py fixture + pass-criteria.md + settings.local.json（CD2 deny）
