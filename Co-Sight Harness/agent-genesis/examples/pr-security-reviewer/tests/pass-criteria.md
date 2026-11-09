# Pass Criteria — pr-security-reviewer v1

## 验收用例（对应 tests/fixtures/sample-vulnerable.diff）

| # | 场景 | 通过标准 |
|---|------|---------|
| AC-1 | SQL 注入（user.py 拼接查询） | findings 含 severity=critical、dimension=security、cwe_id=CWE-89、rule_ref=R-A03-1，evidence 引用拼接行 |
| AC-2 | 硬编码密钥（settings.py） | 两条 critical finding：CWE-798（R-A02-2）+ CWE-321（R-A02-3），密钥样本已脱敏 |
| AC-3 | XSS（dashboard.js innerHTML） | high finding：CWE-79（R-A03-2） |
| AC-4 | N+1 嫌疑（report.py 循环内序列化） | performance 维度 medium+ finding，evidence 定位循环行 |
| AC-5 | IH3 触发 | critical 存在时主 Agent 暂停并 AskUserQuestion；用户驳回的 finding 标 dismissed + reason |
| AC-6 | DF1 校验 | 最终 review-report.json 通过 .claude/schemas/review-report.schema.json 校验 |
| AC-7 | 无 CWE 编造 | 报告中所有 cwe_id 均可于 .claude/rules/owasp-top10.md 中找到；unverified 项独立标注 |

## 运行方式

```bash
cd pr-security-reviewer/v1 && claude
> "审查 tests/fixtures/sample-vulnerable.diff"
```

## 质量门槛

- G1（Schema 校验）：报告必须通过 review-report.schema.json
- G2（证据完整性）：每个 finding 有 evidence + fix_suggestion，无空字段
- G3（边界合规）：抽查 3 个 cwe_id 全部来自规则库
