# Critic Check 输出格式

写入 `plan-N.yaml` 的 `critic_check` 字段：

```yaml
critic_check:
  executed: true
  executed_at: 2026-06-18T14:50:00
  perspective_executor:
    status: PASS | FAIL
    notes: |
      - ✅ 所有 task 字段齐全
      - ⚠️ T007 步骤略模糊（MAJOR，已自动补充）
    issues_count:
      critical: 0
      major: 1
      minor: 0
  perspective_stakeholder:
    status: PASS | FAIL
    notes: |
      - ✅ User stories 全覆盖
      - ⚠️ Milestone 1 gate 不明确（MAJOR，已补充）
    issues_count: {...}
  perspective_skeptic:
    status: PASS | FAIL
    notes: |
      - ✅ 识别 4 个失败点 + mitigation
      - ⚠️ Wave 2 假设过乐观（MINOR，记 self-decision）
    issues_count: {...}
  overall: PASS | FAIL
  critical_issues: 0
  major_issues: 2
  minor_issues: 1
```
