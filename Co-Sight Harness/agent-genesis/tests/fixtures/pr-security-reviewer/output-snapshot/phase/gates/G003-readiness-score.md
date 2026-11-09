# G003 — 就绪度评分门禁（默认）

gate_id: G003-readiness-score
type: condition_check
blocking: true
retry_count: 3

## 判定条件

`readiness_score >= 58`

## 四维评分

- **正确性** (40%): 输出与 planted fixture 期望一致（密钥 critical / 注入 critical / 干净 diff 无 critical）
- **完整性** (30%): findings 含 schema 五字段；复核环节存在；空发现时输出「无 critical 问题」
- **格式** (15%): 报告输出符合 schema；产物文件齐全
- **可操作性** (15%): 修复建议具体可执行；location 指向行号

## 失败回退

重试评分改进（重提交评分）≤3 轮；超限 → circuit_breaker 阻断。