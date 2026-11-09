# 报告格式规则（DF1 配套）

> severity 定义 + evidence 规范 + approval 语义。
> 本规则是 .claude/schemas/review-report.schema.json 的人类可读版，字段以 Schema 为准。

## Severity 定义

| 级别 | 定义 | CI 建议 |
|------|------|--------|
| critical | 可直接导致数据泄露/远程代码执行/资金损失（注入、硬编码生产密钥、SSRF 无防护） | 阻断合并 |
| high | 高概率安全问题或热路径性能退化（缺授权、弱加密、N+1 于热路径） | 阻断或 TL 豁免 |
| medium | 明确应修复但不紧急（日志泄敏、缺分页） | 警告 |
| low | 风格级建议 | 不阻塞 |
| info | 提示性观察 | 不阻塞 |

## Evidence 规范

- 必须包含 diff 原文中的行（`+` 开头的真实新增行），前后各带 1 行上下文
- 密钥样本脱敏：仅保留前 4 字符 + 标注长度（CD2 S-2）
- 引用安全规则时必须附条款号（如 `R-A03-1`）与规则文件内行号

## Approval 语义（IH3）

- `not_required`：无 critical/high finding，直接出报告
- `approved`：用户确认采纳高危 finding
- `dismissed`：用户驳回；`dismissed_reason` 必填（供审计）
- `approval.required=true` 且 status 仍为 `pending` 时，报告不得视为最终版（verdict 字段无效）

## verdict 映射（CI 消费）

- `fail`：存在 approved 的 critical finding
- `pass_with_warnings`：存在 high/medium 或 dismissed 的 critical
- `pass`：仅 low/info
