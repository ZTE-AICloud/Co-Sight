---
name: pr-security-reviewer
produced_by: build-planner
spec_version: "1.0"
---

# 构建方案 — pr-security-reviewer

## 概述

一个 CLI 批处理安全审查 Agent：给定 PR 的 git diff，自动完成密钥硬编码与注入漏洞扫描，经独立复核后输出 critical 问题快报。提交即出结果，全程无人工交互。

## 核心能力

- **密钥硬编码扫描**：识别 AWS 访问密钥、Slack token、PEM 私钥头、数据库连接串口令等硬编码敏感信息，命中即 critical。
- **注入漏洞扫描**：识别 SQL 字符串拼接、exec/eval/system 危险调用、用户输入直插命令，命中即 critical。
- **独立复核**：独立 Reviewer 逐条复核 critical 判定——验证证据片段真实存在于 diff 对应位置、判定成立、修复建议可行；误判打回来源扫描器修正，重审不超过 2 轮，超限阻断。
- **结构化快报**：按统一结构输出（维度/位置/证据/修复建议五项必填）；无 critical 时输出明确「无 critical 问题」结论。

## 交付计划

| 批次 | 内容 |
|------|------|
| 编排层 | CLAUDE.md 主调度器、phase-1-security-scan.md 运行时编排、settings.json 写权限收窄 |
| 执行层 | 三个 SubAgent（密钥扫描、注入扫描、独立复核）+ findings 结构契约 |
| 流程与门禁 | 四步扫描工作流、输入门禁、就绪度/占位符默认门禁、gate 触发映射 |
| 质量层 | 通过标准（三条验收判据的可执行化 + 三个 planted fixture）、6 通用规则、hook 配置、匹配审查规则 |

## 文件清单

共 17 项：9 项 LLM 生成（编排/执行/流程/质量），8 项确定性直拷（6 通用规则 + hook 配置 + 匹配审查规则）。

## 已知风险

1. **无 Skill 层**：本 Agent 不生成 Skill 目录，能力全部内聚于 SubAgent；如需复用扫描能力到其他 Agent，后续增量补充。
2. **critical-only 漏报面**：仅报告 critical 级问题，medium/low 风险不输出，用户可能误以为"无 critical = 全面安全"。报告尾部固定声明覆盖范围。
3. **静态分析误报**：模式清单对混淆代码可能误报/漏报，由独立复核的证据校验环节兜底。
4. **危险配置维度靠复核兜底**：未建独立危险配置扫描器，该维度问题由复核者顺带识别，覆盖面弱于密钥/注入两维。

## 验收标准

1. **planted 密钥 diff → critical**：diff 中含硬编码 AWS API key（AKIA 开头）时，输出 critical 级 findings，含维度、位置、证据、修复建议。
2. **planted 注入 diff → critical**：diff 中含字符串拼接 SQL 时，输出 critical 级 findings（维度 injection）。
3. **干净 diff → 零误报**：无安全问题的 diff，输出明确「无 critical 问题」结论，不得有任何 critical 条目。

## 架构决策

- **为何拆三个角色而非一个**：复核者必须看不到扫描器的推理过程，只有独立上下文隔离才能保证复核独立性；扫描两维度并行可缩短单 PR 延迟。
- **为何只报 critical**：用户显式选择"仅 critical 问题快报"，避免噪音。
- **为何固定四步**：输入检查 → 并行扫描 → 独立复核 → 结构化报告；PR 审查场景流程固定，无需动态路由。
- **为何输入问题直接阻断**：CLI 批处理场景无法交互追问，diff 缺失/不可解析时明确报错退出优于产出部分报告。
