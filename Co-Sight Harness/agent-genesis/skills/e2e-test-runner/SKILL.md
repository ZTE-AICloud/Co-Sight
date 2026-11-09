---
name: e2e-test-runner
description: >
  端到端测试。两种模式—
  自检(/selftest)：用 golden-cases/ 中的固定用例测试 AgentGenesis 自身。
  产物验证(Pipeline调用)：测试生成的 Agent/Skill，由 Pipeline 写入 task/suite.yaml。
---

# E2E-Test-Runner

**做什么**: 端到端测试 AgentGenesis 管线质量
**何时触发**: `/selftest` 命令（自检）或 Phase 5 Pipeline 调用（产物验证）
**输入**: golden-cases/ 中的固定用例 或 Pipeline 写入的 task/suite.yaml
**输出**:
- 测试报告（JSON + Markdown）→ `work/e2e-test-ci/latest/`
- **每个用例的完整会话数据**：stdout.txt / stderr.txt / result.json / timing.json / artifacts.json / phase.json

执行细节（suite 加载 / 过滤 / run_e2e 调用 / 报告生成 / 清理治理）见 `references/execution.md`。

## 三层数据模型

| 层 | 是什么 | 位置 | 谁写 | 谁读 |
|---|--------|------|------|------|
| **Golden Cases** | 固定测试用例定义（输入、预期行为、断言） | `golden-cases/` | 开发者维护 | 两种模式都读 |
| **Suite Config** | 运行时配置（选哪些用例、target指向哪、超时等） | `task/suite.yaml` | Mode A 预置 / Mode B Pipeline写 | scripts/run_e2e.py |
| **Reports** | 测试结果（阶段到达、产物质量、行为正确性） | `work/e2e-test-ci/` | scripts/run_e2e.py 生成 | 人 / Pipeline |

## 模式判定

读取 `task/suite.yaml` 中的 `target_path`：
- `target_path == "."` → Mode A（自检）
- `target_path` 指向产物路径 → Mode B（产物验证）

## Mode A: 自检

用户执行 `/selftest` 命令，测试 AgentGenesis 自身：

```
/selftest                  # 全量自检（跑 golden-cases/ 下全部用例）
/selftest --ids TC-DP-01   # 只跑指定用例
/selftest --domain C       # 只跑指定域
```

前置: V7 隔离约定——在专用空目录执行（副作用落 cwd，前置检查见 `commands/selftest.md`）。
执行: `bash run-e2e.sh` 或 `python3 scripts/run_e2e.py --config task/suite.yaml`
报告: `work/e2e-test-ci/latest/report.md`

## Mode B: 产物验证（Pipeline 嵌入）

> **已移交（product-tester-subagent, 2026-09-29）**: 各 Pipeline 的测试生成+执行由
> SubAgent `product-tester` 承担（黑盒: 测试设计仅来自验收标准）。本 Mode B 仅保留引擎级
> 契约说明；产物级重跑入口（Task 6b）下阶段再议。引擎 scripts/run_e2e.py 两路共用。

Phase 5 需要对生成的 Agent/Skill 做 E2E 测试时，Pipeline 负责：

1. 判定被测对象类型 → 从 golden-cases/ 匹配用例
2. 生成 `work/{name}/e2e/suite.yaml`（target 指向产物路径）
3. 调用 `python3 skills/e2e-test-runner/scripts/run_e2e.py --config work/{name}/e2e/suite.yaml`
4. 读取 `work/e2e-test-ci/latest/report.json` 消费结果

## 评测逻辑

每次测试从三个维度评测，阶段检测支持 orchestrator-state.yaml（v0.17 状态机）与
progress-state.yaml（legacy）及输出文本交叉验证：

| 维度 | 方法 | 数据来源 |
|------|------|---------|
| **阶段到达** | Pipeline 推进到哪个阶段 | 状态文件 → 输出文本升级 |
| **产物质量** | 生成了哪些文件 (diff 快照) | 扫描 `work/` + `.agent-genesis/work/` 对比前后快照 |
| **行为正确性** | 是否做了预期的事 | stdout 文本分析 + 行为规则（behavior-rules.yaml）+ 超时产物分析 |

**阶段检测优先级**：状态文件为基础，输出文本分析可**升级**阶段。

**超时处理**：Popen + 增量读取，超时时仍能捕获已写入的 stdout 和产物文件。

## 目录结构

```
E2E-Test-Runner/
├── SKILL.md                  # Skill 入口
├── references/
│   └── execution.md          # 执行契约（suite 加载/过滤/run_e2e/报告/清理治理）
├── run-e2e.sh                # Shell 入口
├── scripts/
│   ├── run_e2e.py            # 核心引擎（加载用例 → spawn CLI → 检测阶段 → 出报告）
│   ├── behavior-rules.yaml   # 用例行为规则（按 case_id）
│   └── check_diagnosis.py    # 诊断评测 checker
├── golden-cases/             # 金色用例定义（歌单库）
│   ├── domain-a-intent-detection.yaml
│   ├── domain-b-independent-commands.yaml
│   ├── domain-c-pattern-matching.yaml
│   ├── domain-d-agent-creation.yaml
│   ├── domain-e-skill-creation.yaml
│   ├── domain-f-skill-optimization.yaml
│   ├── domain-g-state-machine.yaml
│   ├── domain-h-safety-constraints.yaml
│   ├── domain-i-self-evolution.yaml
│   ├── domain-j-integration-scenarios.yaml
│   └── domain-k-multi-agent.yaml
└── task/
    ├── suite.yaml            # 运行时配置（播放列表）
    └── data/                 # 本次任务专用数据（可选）
```

## 产出目录结构

```
work/e2e-test-ci/
├── run-{timestamp}/        # 每次运行独立，历史可追溯（--keep-runs 轮转，默认留 5）
│   ├── suite.yaml          # 本次运行配置快照
│   ├── report.json         # 机器可读报告
│   ├── report.md           # 人类可读报告（含副作用清单 V6c）
│   └── sessions/
│       └── {case_id}/
│           ├── stdout.txt    # CLI 完整标准输出
│           ├── stderr.txt    # CLI 完整错误输出
│           ├── result.json   # claude -p --output-format json 解析结果
│           ├── timing.json   # {elapsed_seconds, exit_code, timed_out}
│           ├── artifacts.json # work/ 目录下的产物清单
│           └── phase.json    # 到达的 Pipeline 阶段
└── latest -> run-{timestamp}/  # 符号链接指向最新运行
```

## 按 Pipeline 类型匹配 Golden Cases

| Pipeline | 被测产物 | 从 golden-cases 中匹配 |
|----------|---------|---------------------|
| agent-creation (单Agent) | CLAUDE.md + rules/ + skills/ | domain-d-agent-creation + domain-h-safety |
| agent-creation (Multi-Agent) | Main + SubAgent + global-rules + schemas | domain-k-multi-agent + domain-d-agent-creation |
| skill-foundry (create mode) | SKILL.md + references/ + scripts/ | domain-e-skill-creation |
| skill-foundry (optimize mode) | 优化后的 Skill | domain-f-skill-optimization |
