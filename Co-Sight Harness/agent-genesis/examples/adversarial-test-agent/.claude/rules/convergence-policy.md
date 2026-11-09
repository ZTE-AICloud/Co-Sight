# 收敛策略（W2 迁移条件 + SM1 checkpoint）

> Leader 的判定依据。收敛不是"感觉差不多了"，是可判定条件。

## 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| max_rounds | 5 | 超过即 PARTIAL，不静默截断 |
| converge_streak | 2 | survivor==0 连续轮数 |
| mutants_per_round | ≤8 | 每轮变异点数 |
| equivalent_tolerance | 每轮 ≤2 | 等价嫌疑超限 → 该批评家本轮选题无效，重选 |

## 判定规则

1. **streak 语义**：EVALUATE 后 survivor==0 → streak+1；survivor>0 → streak=0
2. **CONVERGED**：streak ≥ 2 → 进入交付（IH3）
3. **PARTIAL**：round == max_rounds 且 streak < 2 → verdict=partial，附 `unresolved_mutants[]`
4. **新位置强制**：critic 选题必须与 round-state.yaml 的 `history[]` 无 (file, line, operator) 三元组重复

## round-state.yaml（SM1 checkpoint）

每轮 EVALUATE 后立即写出：

```yaml
target: "src/pricing.py"
round: 3
streak: 1
history:
  - {round: 1, mutants: 8, killed: 5, survived: [M1-2, M1-4, M1-7], equivalent: [M1-5]}
  - {round: 2, mutants: 6, killed: 6, survived: [], equivalent: []}
updated_at: "..."
```

**恢复语义**：重启后读 state → round 与 streak 载入 → history 用于新位置强制 → 从 WRITE 继续当前轮。已完成轮永不重放。

## Leader 裁决纪律

- Leader 不修改任何测试或变异体（它不是选手，是裁判）
- Leader 的每一次状态迁移写入 round-state（审计链完整）
