## 📊 整体分析(所有低分 case 共性)

### 失分点矩阵

{{ overall.matrix }}

### 共性根因聚类

{{ overall.common_root_causes }}

### 满分 case 风险 ⚠️

{{ overall.full_mark_risk }}

### 推荐整体方向

{{ overall.recommendation }}
{% if volatility and volatility.get('run_count', 1) > 1 %}
## 📊 波动性分析(多 run 评测,共 {{ volatility.run_count }} 次 run)

{% set vcases = volatility.get('cases') or {} %}
| case | 平均 F1 | 标准差 | 各 run F1 |
|------|--------|--------|----------|
{% for vcid, vc in vcases.items() %}
{% if vc.get('avg_f1') is not none %}
| {{ vcid }} | {{ '%.2f'|format(vc.avg_f1) }} | {{ '%.2f'|format(vc.stddev) }} | {{ vc.per_run_str }} |
{% endif %}
{% endfor %}

> **波动 ≠ 稳定低分**:标准差 ≥ 5 的 case 是"run 间不稳定",同一 SKILL.md 在不同 run 间产出不一致。
> mod 需**收敛 run 间差异**(把临界判断写成确定性规则),不只提升单次分数;
> 稳定低分 case 按常规根因(数量/内容/链路)优化。目标:**平均分更高(主) + 方差更低(次)**。
{% endif %}
{% for c in cases %}
## {{ c.case_id }} 失分诊断
{% if volatility and volatility.get('cases', {}).get(c.case_id) and volatility['cases'][c.case_id].get('avg_f1') is not none %}
{% set vc = volatility['cases'][c.case_id] %}
**F1(跨 run 平均)**: {{ vc.f1_display }}
{% if vc.get('stddev') is not none and vc.stddev >= 5 %}
⚠️ **波动大**:各 run F1 差异明显(run 间不稳定),mod 需收敛 run 间差异。
{% endif %}
{% else %}
**F1**: {{ c.f1 }}
{% endif %}
**核心失分模式**: {{ c.core_loss_mode }}
**deepthink 总结**: {{ c.deepthink_summary }}

#### 1. gold/llm_output 对比(Step 1: Reproduce)

- **R(gold)**: {{ c.reproduce.gold }}
- **C(LLM 输出)**: {{ c.reproduce.llm }}
- **命中**: {{ c.reproduce.hit }}
- **漏召回**: {{ c.reproduce.miss }}
- **误召**: {{ c.reproduce.wrong }}

#### 2. trace 工具调用链路(Step 2: Isolate)

{{ c.trace_evidence }}

#### 3. 建议根因(Step 3: Hypothesize)
{% for rc in c.root_causes %}
- **根因**({{ rc.type }}, `{{ rc.skill_layer }}`): {{ rc.detail }}
{% endfor %}
#### 4. 建议 mod 方向(Step 4: Instrument)
{% for md in c.mod_directions %}
- **{{ md.skill }}**: {{ md.direction }}
{% endfor %}
#### 5. 验证(Step 5: Verify)

{{ c.verify }}

#### 6. 回归风险(Step 7: Regression)

- **non_target_cases_risk**: {{ c.regression_risk.level }}
- **影响的满分 case**: {{ c.regression_risk.affected_cases }}
- **缓解措施**: {{ c.regression_risk.mitigation }}
{% endfor %}
