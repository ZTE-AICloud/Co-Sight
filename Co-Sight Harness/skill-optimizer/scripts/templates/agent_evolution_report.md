# {{agent_name}} Skill 进化报告

> **生成时间**: {{timestamp}}
> **工作空间**: {{workspace}}
> **报告类型**: Agent 级别联合 Skill 进化报告（多 Skill 联合优化）

---

## 1. 总体结果

| 指标 | 值 |
|------|-----|
| Agent 名称 | {{agent_name}} |
| Skill 列表 | {{skill_list}} |
| 基线聚合分 | {{baseline_score}} |
| 最佳聚合分 | {{best_score}} (Round {{best_round}}) |
| 最终聚合分 | {{final_score}} |
| 目标分数 | {{target_score}} |
| 达标状态 | {{achieved_status}} |
| 进化方向 | {{evolution_direction}} |

**一句话总结**: {{summary}}

---

## 2. 分数历史

### 2.1 分数趋势

| 阶段 | 聚合分 | 较基线 | 较上轮 |
| :--- | :---: | :---: | :---: |
{{score_trend_rows}}

### 2.2 各轮次最佳候选

| 轮次 | 最佳候选 | 综合分 | 结果分 | 评测次数 |
| :--- | :--- | :---: | :---: | :---: |
{{round_best_rows}}

---

## 3. Skill 级别差异分析

### 3.1 Skill 间协同 / 冲突

{{skill_synergy_analysis}}

---

## 4. 候选间对比

### 4.1 候选详情

{{candidate_table}}

### 4.2 候选稳定性

{{candidate_stability_analysis}}

---

## 5. 进化路径

### 5.1 关键修改

{{key_modifications}}

### 5.2 修改覆盖的 Skill 和章节

{{modification_coverage}}

---

## 6. 未达标原因分析（若未达标）

{{failure_analysis}}

---

## 7. 产物索引

{{artifact_index_table}}

---

## 8. 下一步建议

{{next_steps}}
