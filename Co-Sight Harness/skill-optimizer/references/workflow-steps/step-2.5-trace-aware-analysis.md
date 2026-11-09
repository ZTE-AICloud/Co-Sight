# Step 2.5: Trace-aware per-case analysis(失分 RAN 的轨迹分析)

> **位置**:Step 2 (Isolate) 之后,Step 3 (Hypothesize) 之前。
>
> **触发条件**:**仅对 f1 < baseline_score 的 RAN 做分析**(满分跳过,满分说明已 OK)。
>
> **目的**:在形成"根因假设"前,先用 trace 数据**观测 Agent 实际执行路径**,避免假设脱离真实执行。

---

## 🔍 为什么需要这一步

**典型反模式**(已观测到的 R1 案例):
- LLM 看到 `result_diff_report` 说"R3 字段错配"
- LLM 直接假设"L1 user 字段判定错了" → 提 M1 改"用户角色判定"
- **但 trace 显示**:LLM 实际是因为 Agent 在 09 步骤执行了 Write → verify_user_field.py → verify 通过(只检查标题/格式,不检查内容) → 没有触发重写 → 输出空表
- **真实根因**:不是"判定错",是"verify 校验不严 + 无自愈"

**结论**:**没有 trace 看执行路径,根因假设常跑偏**。

---

## 📥 输入(已在本轮文件夹就绪)

result_diff_report_round_{N-1}.md 已经被 framework 复制到本轮目录,无需跨路径 Read:
- **路径**:`{round_dir}/result_diff_report_round_{N-1}.md`(本轮 folder 内的副本)
- 或 baseline:`{round_dir}/result_diff_report_baseline.md`(N=1 时)

每个 case 段已含 5 段:
- `#### 1. gold 答案`
- `#### 2. Skill 实际产出(LLM 输出)`
- `#### 3. LLM-as-Judge diff_notes`
- `#### 4. 资源消耗`
- **`#### 5. Trace 路径(Agent 执行轨迹)`** ← 低分 case 还带 ⚠️ 必读标记

**trace 路径**:
- 主诊断源:`phase2-exec/{req_id}_*/trace/trace.jsonl`(详细,每行一个 tool_call)
- 辅助:`phase2-exec/{req_id}_*/trace/trace.log`(简化版)

---

## 🎯 分析维度(每失分 RAN 必填 5 段)

每个失分 RAN(f1 < baseline)在 `trace_per_case_analysis.md` 写 1 段,结构:

### 段 a. 现象(diff 已说明)
- gold 期望什么
- LLM 实际产出什么
- diff_notes 失分点
- **当前假设**(LLM 第一印象)

### 段 b. Trace 观测
- **总 turn 数 / tool_call 数 / error 数**
  ```bash
  python3 -c "import json; rows=[json.loads(line) for line in open('trace.jsonl') if line.strip()]; print(len(rows))"  # jsonl:每行一个 JSON
  ```
  或更简单:Read `trace_summary.json` 看 `conversation_stats`
- **关键转折点**:
  - 哪一步 Write/Edit 09 文件? 写入字符数(空表 / 1 行 / 多行)?
  - 哪一步 verify_user_field.py 调用? exit code?
  - 哪一步 Bash mkdir / mv / cp? 文件系统状态变化?
- **异常**:`error_count > 0` 时,哪几个 tool_call 报错?

### 段 c. 执行模式归类
LLM 自主判断,可选标签:
- `verify_failed_no_recovery`:verify 报错但没自愈
- `agent_bypass_validation`:verify 通过但内容空(校验脚本不严)
- `output_truncated`:LLM 输出超过上下文被截断
- `wrong_tool_choice`:LLM 用错工具(Bash 替代 Read 等)
- `cascade_failure`:前一步失败导致后续步骤错乱
- `extraction_miss`:LLM 没找到关键文件

### 段 d. 真实根因(基于 trace 证据)
- **不是**"用户列错配"这种表层假设
- **是**"verify_user_field.py 第 137-141 行只查标题存在,不查表行数"这种可验证结论

### 段 e. 对 mod 的指导(本轮该改什么)
- SKILL.md 字段约束?**NO**(如果根因是 verify 校验不严)
- scripts/verify_user_field.py 加空表检测?**YES**(如果根因是 verify 不严)
- consume_lib 加新知识?**视情况**
- 提哪个 mod(M1/M2/...)?

---

## 📤 产出物

**文件路径**:`{cand_dir}/trace_per_case_analysis.md`
**结构**:
```markdown
# Trace-aware per-case analysis (round N, candidate K)

> 仅分析 f1 < baseline_score 的 RAN(满分跳过)
> 数据源:trace.jsonl(主) + trace.log(辅助)

## 分析输入
- 上轮 result_diff_report: `result_diff_report_round_{N-1}.md`
- baseline_score: 72.52
- 失分 RAN 列表:[RAN-xxx, RAN-yyy]

---

### RAN-xxx(f1=X / baseline=72.52)

#### a. 现象(diff 已说明)
- gold: <gold 摘要>
- LLM 实际产出: <llm_output 摘要>
- diff_notes 失分点: <失分描述>
- 当前假设: <LLM 第一印象>

#### b. Trace 观测
- 总 turn=127 / tool_call=108 / error=6 / 总文本=6283 chars
- 关键转折:
  - Step 41 Write 09 文件:253 字符(仅"#用户需求分析\n")
  - Step 42 verify_user_field.py 调用:exit code=0
  - Step 43-50 没重写 09 文件
- 异常:verify_user_field 通过但实际输出空表

#### c. 执行模式
`agent_bypass_validation` + `verify_failed_no_recovery` 复合

#### d. 真实根因
verify_user_field.py validate_file_structure() 第 137-141 行只检查 `found_title` 与 `found_table`,
但不要求 `table_line_count > 0`。空表(只有标题 + 分隔行 + 表头)被误判为"合规"。

#### e. 对 mod 的指导
**改 verify_user_field.py**(不是 SKILL.md):
- 加 `assert table_line_count >= 1, "09 文件表格无数据行"`
- exit code=1 触发 Agent 自动重写
- **不动 SKILL.md 字段约束**(避免 R3 矫枉过正)

---

### RAN-yyy(f1=Y / baseline=72.52)
[同上结构]
```

---

## ✅ 落盘前必跑自检 bash

```bash
python3 -c "
import os
md_path = '{cand_dir}/trace_per_case_analysis.md'
assert os.path.exists(md_path), 'Step 2.5 产物缺失'
md = open(md_path).read()
for case_id in {low_score_cases}:
    assert case_id in md, f'失分 case {case_id} 未分析'
    assert '现象' in md, '缺现象段'
    assert 'Trace 观测' in md, '缺 trace 段'
    assert '根因' in md, '缺根因段'
    assert '对 mod' in md, '缺 mod 指导段'
print('FOUND: trace_per_case_analysis.md 合规')
"
```

---

## 🚨 反模式

- ❌ **跳过满分 case**:不要分析 f1=100 的 case(无意义,浪费时长)
- ❌ **没读 trace 直接假设**:违反本步骤目的
- ❌ **trace 段只列 JSON 字段不解释**:Read trace 后必须**用人类语言总结**关键转折点
- ❌ **根因段写得太浅**:"字段判定错了"不算根因,必须可追溯到 trace 的具体步骤
- ❌ **mod 指导段写"加约束"**:若根因在 verify 脚本,应该改 verify,不是 SKILL.md

---

## 🔗 与下游 step 的关系

- **Step 3 (Hypothesize)** 必读 `trace_per_case_analysis.md` 作为根因卡输入(不再只靠 diff_notes 猜测)
- **Step 6 (Fix) 必读本文件**确认 mod 方向(避免提"加 SKILL.md 约束"但根因在 verify 脚本的反模式)
- **Step 7 (Regression Test) 必读**确认 mod 真解决了 trace 暴露的问题,而不是改了无关字段