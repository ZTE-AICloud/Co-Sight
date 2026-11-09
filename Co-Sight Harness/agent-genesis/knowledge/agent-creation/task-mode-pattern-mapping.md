# 12 类任务模式 → 设计模式映射速查

> 来源: design/AgentGenesis-6月/Agent设计模式完整参考.md

## 研发场景

| 任务模式 | 推荐模式组合 | 核心模式 |
|---------|------------|---------|
| 探索与定义 | W1 + WF4 + K2 + DT1 + IH2 + CD3 | WF4-Multi-Agent-Debate |
| 实施与构建 | W1 + G1 + WF5 + K4 + CD2 + IT1(Enforced) | WF5-Contract-Lock |
| 验证与校验 | G1 + WF6 + DF1 + CD1 | WF6-Circuit-Breaker |
| 效能与基建 | W1 + WF6 + WF7 + K4 + CD1 | WF7-Knowledge-Reflux |
| 共识与传达 | IH3 + IV1 | IH3-Plan-Approval |
| 路由与分发 | W2 + K4 + CD1 | W2-Router |

## 运维场景

| 任务模式 | 推荐模式组合 | 核心模式 |
|---------|------------|---------|
| 监测与响应 | W1 + G1 + CD1 + IV1 | IV1-Progress-Streaming |
| 故障诊断与恢复 | W2 + K3 + CD3 | K3-KB-Backed |
| 变更执行 | W1 + G1 + WF5 + CD2 | WF5-Contract-Lock |

## 个人办公场景

| 任务模式 | 推荐模式组合 | 核心模式 |
|---------|------------|---------|
| 信息处理与摘要 | W3 + K1 + IH1 | W3-MapReduce |
| 安排与协调 | IH2 + IV1 | IH2-Interactive-Clarify |
| 检索与整合 | K3 + DP1 + IH1 | DP1-Traceable-Lineage |

## 预置范式速查

| 范式 | 模式组合 | 适用 |
|------|---------|------|
| pipeline | W1+G1+K4+DT1+DF1+IH3+IT1(Enforced)+IV1+CD1+CD3 | 实施构建/变更执行 |
| exploration | W1+WF4+K2+DT1+IH2+CD3 | 探索与定义 |
| quality | G1+DF1+WF6+CD1+K4 | 验证校验/监测响应 |
| infra | W1+WF6+WF7+K4+CD1 | 效能基建 |
| diagnosis | W2+K3+CD3 | 故障诊断与恢复 |
| swarm | W3+K1+IH1 | 信息处理与摘要 |
| research | K3+DP1+IH1 | 检索与整合 |
| coordination | IH2+IV1 | 安排协调/共识传达 |
| router | W2+K4+CD1 | 路由与分发 |
| minimal | W1+K1+DT1+IH1+CD1 | 通用最小集 |

## 维护规则（v1.2 批 3 入档）

### 数量纪律
- 本表"核心模式"列去重即核心模式全集——现 11 唯一 id（12 场景行, WF5 跨行重复计 1）。
- 数量硬顶与维护责任见 `knowledge/golden/REFLUX.md` §5（单源, 本文不复制）。

### 新增核心模式
- 新增 = 档 2 重沉淀流程（REFLUX.md §2 四要件 + 两前提, 单源）, 通过后本表才加场景行。
- **禁先加表行再走沉淀**——表行是四要件齐全的结果, 不是起点。

### 键域一致性
- golden 池检索键域（`knowledge/golden/INDEX.yaml` key_domain）⊆ 本列去重集,
  机检 = `tests/flow/golden-lookup-verify.sh` 键域断言（参数化, 数据驱动本表）。
