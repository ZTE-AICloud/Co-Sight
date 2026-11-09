# Pass Criteria — pr-security-reviewer

> Step 5 readiness-verifier 与 Step 6 product-tester 的判据唯一来源。

## AC1: planted 密钥 diff → critical 报告

**given** 输入 PR diff 含新增行 `+ AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE`
**when** 运行 pr-security-reviewer
**then** 报告含至少 1 条 critical finding：
- dimension=secrets
- location 指向命中文件与行号
- evidence=原始 `+` 行原文
- fix 为具体修复建议（如"移至环境变量 AWS_ACCESS_KEY_ID 引用"）

## AC2: planted 注入 diff → critical 报告

**given** 输入 PR diff 含新增行 `+ query = "SELECT * FROM users WHERE id=" + user_id`
**when** 运行 pr-security-reviewer
**then** 报告含至少 1 条 critical finding：
- dimension=injection
- location 指向命中文件与行号
- evidence=原始 `+` 行原文
- fix 为"使用参数化查询 `cursor.execute('SELECT ... WHERE id=?', (user_id,))`"

## AC3: 干净 diff → 「无 critical 问题」零误报

**given** 输入 PR diff 为空白或仅含文档/注释修改、类型注解、变量重命名（无任何密钥/注入模式命中）
**when** 运行 pr-security-reviewer
**then** 报告输出「无 critical 问题」明确结论，**不得**含任何 critical finding 条目（反例：测试 fixture 的模式命中若 diff 中已标注为测试代码，可被复核识别为误报打回，最终输出空）

## 端到端 fixture 描述

| fixture | 输入 | 期望输出 |
|---------|------|----------|
| fixture-secret | diff 含 `AKIAIOSFODNN7EXAMPLE` 新增行 | ≥1 secrets critical |
| fixture-injection | diff 含 `query = "SELECT * FROM " + var +` 新增行 | ≥1 injection critical |
| fixture-clean | diff 为 README 修改 | 「无 critical 问题」+ 0 条 critical finding |

## 通过阈值

- 三个 fixture 全部通过
- G003 readiness_score ≥ 58
- G005 placeholder_count == 0