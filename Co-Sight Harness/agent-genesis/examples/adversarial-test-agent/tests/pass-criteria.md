# Pass Criteria — adversarial-test-agent v1

## 验收用例（对应 tests/fixtures/src/pricing.py）

| # | 场景 | 通过标准 |
|---|------|---------|
| AC-1 | 完整对抗循环 | verdict=converged，final_score.kill_rate=1.0，streak≥2 |
| AC-2 | 每轮可审计 | mutation-report.json 的 rounds[] 含每变异体 id/op/rule_ref/line/verdict |
| AC-3 | 源码零改动 | 循环前后 `git diff --stat src/pricing.py` 为空（fixture 演示：比对 sha256） |
| AC-4 | 弱测试必被击穿 | 仅断言"函数可调用"的测试 draft 在 round 1 存活率 ≥50%（证明对抗有效） |
| AC-5 | PARTIAL 语义 | 强制 max_rounds=1 运行：verdict=partial 且 unresolved_mutants 非空 |
| AC-6 | DF1 校验 | 报告通过 .claude/schemas/mutation-report.schema.json 校验 |
| AC-7 | 断点恢复 | round 2 后 kill 进程，重跑从 round 2 恢复（history 不重复） |

## 快速演示

```bash
cd adversarial-test-agent/v1 && claude
> 对 tests/fixtures/src/pricing.py 运行对抗测试
# 观察 IV1 进度行：[round N] kill X/Y (streak=Z)
# 收敛后 IH3 审批 → tests/ 落盘 + mutation-report.json
```
