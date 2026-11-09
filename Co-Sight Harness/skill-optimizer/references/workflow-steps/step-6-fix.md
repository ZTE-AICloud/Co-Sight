# Step 6: Fix(修复)— 生成 modifications + 立即 Edit/Write 应用

> **对应 debug-pro Step 6**:最小正确修复。**禁止**趁机 refactor。

## 目标
按 Step 5 通过的 mod 假设,生成完整字段 + 立即 Edit/Write 应用 + FOUND 校验。

## 必做动作

### 每条 mod 必填字段

- `action` / `file` / `section` / `current_content`(Step 5.1 自检到 FOUND)
- `new_content`(≤ 800 字符)
- `estimated_token_impact`(int) / `score_impact`(float)
- `cost_benefit`(= net_impact / token)
- `reason`(含"通用" / "系统" / "一致" / "共同" / "大多数" / "通常")
- `non_target_cases_risk`: 0/1/2
- **`risk_evidence`**(**必带 result_diff_report.md 第 N 段引用**):"{case_id} 的 {column} 列:gold='{gold}', LLM='{llm}', 失分={delta}(来源:result_diff_report.md 第 N 段)"

### 修改策略优先级

1. `edit_exact` > 2. `condense` > 3. `delete_redundant` > 4. `split_skill` > 5. `extract_to_script`

### 🆕 重新 Read 相关 diff 报告(避免凭印象写 current_content)

**强制**:每次 Edit 前必须 Read 目标文件对应章节,禁止凭印象写 current_content。

```python
Edit(file_path=full_path, old_string=current_content, new_string=new_content)
# extract_to_script: Write 创建脚本 + Edit SKILL.md 加引用
```

### 当前内容读取校验链(强制三步)

1. `Read` 目标文件对应章节
2. **逐字符复制** current_content
3. Bash `python3 -c "src=open('...').read(); print('FOUND' if cur in src else 'MISSING')"` — MISSING 则重新 Read 补差异

## 硬约束

- ❌ **禁止** `edit_exact add` 无脑加规则段(baseline→R3 涨 +6.8% 反模式)
- ❌ **禁止** 跳过 FOUND 校验直接 Edit
- ❌ **禁止** 趁机 refactor(只修需要改的 H2 章节)
- ✅ `extract_to_script_count` 每轮 ≥ 1 条

## 失败处理

FOUND 校验不过 → 重新 Read 目标文件 → 重新复制 current_content → 再 Edit。**最多重试 3 次**,3 次仍不过 → 在 `_plan_summary.md` 标记 `failed_at_step6: <reason>`。