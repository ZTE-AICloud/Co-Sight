# G003 readiness-score 门禁

## 元数据

```yaml
gate:
  id: G003
  type: condition_check
  condition: "readiness_score >= {{readiness_threshold}}"
  blocking: true
  retry_count: 3
```

## 判定条件

`readiness_score >= {{readiness_threshold}}` —— readiness 评分达到门槛即通过，低于门槛阻断并回退。

## 评分四维

| 维度 | 说明 |
|------|------|
| 正确性 | 产出内容与需求契约一致，无事实性错误 |
| 完整性 | 必填文件/字段/章节齐全，无缺漏 |
| 格式 | frontmatter/结构/schema 符合产出标准 |
| 可操作性 | 用户拿到即可运行/使用，无需二次加工 |

## 失败回退协同

- `retry_count: 3` —— 门禁未过时回退重试上限 3 次
- 回退跳转目标 = workflow 对应步骤的「失败回退」字段
- 超过上限 → circuit_breaker.escalate_to 升级处理
