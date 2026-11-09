# Pattern Constraints — 模式组合硬约束

> 来源: cascading-matcher.yaml hard_constraints

## HC-01: CD3 要求知识来源
CD3-Knowledge-Boundary 必须与至少一个 K2/K3/K4 配对。
禁止: 纯 LLM 内嵌知识却声称有知识边界。

## HC-02: E 链依赖
E1→E2→E3 不可跳跃。不能直接选 E3 而不选 E1/E2。

## HC-03: MN 互斥
MN-Deterministic 不能选 W4-LeaderWorker / W5-Adaptive / SM1-FSM。

## HC-04: E2-IH1 互斥
E2-Controlled-Evolution（会自我修改）与 IH1-Fire-and-Forget（无人类交互）互斥。

## HC-05: W5 必须声明 base_topology
W5-Adaptive 是叠加层，必须指定底层拓扑（W1/W2/W3/W4 之一）。

## HC-06: 无互斥冲突
pattern_relationships 中 incompatible_with 无一命中。

## 检查清单
- [ ] HC-01: CD3 有 K2/K3/K4 配对
- [ ] HC-02: E 链不跳跃
- [ ] HC-03: MN 不与动态模式互斥
- [ ] HC-04: E2 不与 IH1 互斥
- [ ] HC-05: W5 声明 base_topology
- [ ] HC-06: 无互斥冲突
