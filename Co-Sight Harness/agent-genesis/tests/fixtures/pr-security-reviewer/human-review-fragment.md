# human-review 判断段 fragment — pr-security-reviewer

> 判断段基线（D3）：判断槽位内容转写自仓内唯一 LLM 转写版样本 tests/fixtures/pr-security-reviewer/human-review.md
> 的对应节（§1/§2/§3/§5/§6/§8/§9/§10），并按 C9-6 洁化（去插件内部编号/置信度/版本修饰词）。
> 机械段（文件清单/风险透传/验收转写/拓扑图）不在 fragment 内——由 runner.review.assemble 机械组装。

## 概述

从 PR 的 git diff 出发，按固定四步流程完成安全审查并输出 critical 问题快报的 CLI 批处理 Agent。提交即出结果，全程无人工交互。

## 核心能力

- 密钥硬编码扫描：AWS AKIA / Slack xoxb / PEM 私钥头 / 连接串口令等模式清单命中即 critical
- 注入漏洞扫描：SQL 字符串拼接、exec/eval/system 调用、用户输入直插命令
- 独立复核：独立 Reviewer 对每条 critical 判定做证据复核，误判打回修正（重审 ≤2 轮，超限阻断）
- 结构化快报：按统一 schema 输出（维度/位置/证据/修复建议）；无 critical 时输出明确「无 critical 问题」结论

## 交付计划

| 批次 | 内容 | 数量 |
|------|------|:---:|
| 编排层 | CLAUDE.md、proposal-spec.md、settings.json | 3 |
| 执行层 | secret-scanner、injection-scanner、security-reviewer 三个 SubAgent + findings schema | 4 |
| 工作流/门禁 | phase-1-security-scan.md、G001-input-check 输入门禁、默认质量门禁两件、gates.yaml | 4 |
| 质量与资产 | pass-criteria、matching-decision-review 审查规则、6 通用规则、hooks.json | 8（6 拷贝+2 生成） |

共 16 项；其中确定性直拷 7 项（零 LLM 生成），LLM 生成 8 项，存在性校验 1 项。

## 已知风险（判断条目）

- [重大] skills=0 偏差：结构决策为 0 skill（YAGNI），与输出标准默认「≥1 复用 skill」冲突。缓解：结构约束优先，偏差在此显式声明；若后续需要可增量补 skill。
- [重大] critical-only 可能漏报：只报 critical 级别，medium/low 风险不输出，用户可能误以为"审查通过=无问题"。缓解：报告尾部固定说明"仅覆盖 critical 级判定"；独立复核环节校验证据真实性降低误报。
- [重大] LLM 静态分析误报：密钥/注入特征清单基于模式匹配，对混淆代码可能误报或漏报。缓解：独立复核必须验证证据片段真实存在于 diff 对应位置。
- [轻微] 三维扫描覆盖面：危险配置维度未建独立扫描器（仅两扫描器+复核），依赖复核兜底。缓解：接受——首批聚焦密钥/注入最高危维度。

## spot-check 锚点

| # | 锚点 | 执行方式 |
|---|------|---------|
| 1 | security-reviewer 的 forbidden_inputs 是否含扫描器中间推理文件 | grep -A5 forbidden_inputs output/agents/pr-security-reviewer/v1/.claude/agents/security-reviewer.md → 应见 secret-scanner/injection-scanner 产物路径 |
| 2 | 回压协议是否闭环 | grep "重审≤2轮" phase/02-workflows/phase-1-security-scan.md → 命中且含超限阻断语义 |
| 3 | schema required 字段 | python3 -c "import json;s=json.load(open('.claude/schemas/security-findings.schema.json'));assert set(s['required'])>={'dimension','severity','location','evidence','fix'}" → exit 0 |
| 4 | 干净 diff 不误报路径 | grep "无 critical 问题" phase/02-workflows/phase-1-security-scan.md → 命中 |

## 架构决策摘要

- **三 Agent 编排（multi_agent 三维拆分）**：两专职扫描器（并行）+ 一独立复核者，而非单 Agent 全包——复核独立性（复核博弈机制）要求复核者看不到扫描器推理，只有独立上下文隔离能做到。
- **critical-only 快报**：用户显式选择"仅 critical 问题快报"（需求澄清确认结果），medium/low 不进报告。
- **固定四步流程**：输入检查 → 并行扫描 → 独立复核 → 结构化报告；无路由、无动态派生。
- **无人工交互**：提交即出结果，输入问题直接阻断报错而非询问。

## 决策物化摘要

| 决策 | 物化位置 |
|------|---------|
| 固定四步流程 | phase-1-security-scan.md 步骤表 |
| 复核独立性 | security-reviewer forbidden_inputs 双向隔离 |
| 回压重审 ≤2 轮 | phase-1-security-scan.md 复核步 + reviewer 执行流程 |
| 结构化输出契约 | .claude/schemas/security-findings.schema.json（五字段必填） |
| 输入前置阻断 | phase/gates/G001-input-check.md |
| 只读审查隔离 | CLAUDE.md 禁止操作清单 + settings.json 写权限收窄 |
| 无外部知识 | CLAUDE.md 知识节声明 |
| 默认质量门禁 | 产物内默认 gate 文档两件（readiness≥58 / placeholder==0） |

## 判断题清单

1. 复核者与扫描者的上下文是否双向隔离？【机检 ✓ 结构机检 + spot-check #1】
2. 回压重审是否有上限且超限阻断？【机检 ✓ 内容锚定「重审≤2轮」】
3. schema 是否五字段全必填且 JSON 合法？【机检 ✓ spot-check #3】
4. 产物是否含插件内部裸路径？【机检 ✓ 交付核对】
5. 干净 diff 路径是否有明确「无 critical 问题」输出？【机检 ✓ 内容锚定 + spot-check #4】
6. 输入异常是否阻断而非猜测续跑？【需人判】输入门禁 blocking 语义是否认可
7. 7 个直拷文件是否与源逐字一致？【机检 ✓ 确定性直拷核对】
