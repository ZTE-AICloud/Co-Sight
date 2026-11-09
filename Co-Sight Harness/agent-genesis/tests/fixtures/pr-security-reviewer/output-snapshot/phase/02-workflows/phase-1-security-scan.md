# Phase 1: 安全扫描工作流 — pr-security-reviewer

> 核心执行流程：输入检查 → 并行扫描 → 独立复核 → 结构化报告。
> 每步声明输入/输出/失败回退；数据流转无悬空实体。

## Step 1: 输入检查（CD1 前置阻断）

- **输入**：diff 文件路径（外部输入）
- **输出**：校验通过的 diff 句柄
- **检查清单**（详见 `phase/gates/G001-input-check.md`）：
  1. 文件存在
  2. 非空
  3. ≤ 5MB
  4. git diff 格式可解析（含 `+++`/`---` 头与 hunk 头 `@@`）
- **失败回退**：任一不满足 → 明确报错（说明哪项失败、期望值、实际值）+ 非零退出。**不产出部分报告，不猜测续跑**（retry_count: 0——输入问题重试无意义）。

## Step 2: 并行扫描（两维独立）

- **输入**：校验通过的 diff
- **输出**：`secret-findings.json`（secret-scanner）、`injection-findings.json`（injection-scanner）
- **执行**：secret-scanner 与 injection-scanner **同阶段并行**调度，各自只读 diff，互不读取对方产物，各自产出符合 `.claude/schemas/security-findings.schema.json` 的 findings。
- **失败回退**：单扫描器失败 → 该扫描器局部重试 ≤2 轮；双失败或超限 → circuit_breaker 阻断，报错退出。

## Step 3: 独立复核（G1 回压协议）

- **输入**：两份 findings（**不读** diff 之外的扫描器中间推理文件）
- **输出**：`reviewed-findings.json`
- **执行**：security-reviewer 逐条复核——
  1. 证据片段是否真实存在于 diff 声明位置
  2. critical 判定是否成立（对照各维度判定规则）
  3. 修复建议是否可行
- **回压循环**：误判 → 标注打回原因 → 退回来源扫描器修正 → 重审。**重审≤2轮**，超限 → 阻断上报 Leader，不交付未经复核的报告。
- **复核者约束**：不得修改 diff；不得读取扫描器中间推理文件；空 findings 时确认「无 critical 问题」结论合规输出。

## Step 4: 结构化报告

- **输入**：`reviewed-findings.json`
- **输出**：critical 快报（stdout，可选写 `./security-report/`）
- **执行**：
  1. 每条按 schema 五字段渲染：dimension / severity / location / evidence / fix
  2. 空发现 → 输出明确结论「无 critical 问题」（不得留空、不得含糊）
  3. 报告尾部固定声明："本报告仅覆盖 critical 级判定（密钥硬编码、注入漏洞）；medium/low 级风险未输出。"
- **失败回退**：写出失败重试 ≤3 轮；仍失败 → stdout 直出，退出码非零并说明。

## 数据流转闭合校验

| 实体 | 生产者 | 消费者 | 状态 |
|------|--------|--------|:----:|
| diff | 外部输入 | Step1/Step2 | ✓ |
| secret-findings.json | secret-scanner | security-reviewer | ✓ |
| injection-findings.json | injection-scanner | security-reviewer | ✓ |
| reviewed-findings.json | security-reviewer | Step4/用户 | ✓(最终) |

无悬空实体；扫描器与复核者之间仅经 findings 文件传递，无隐含依赖。
