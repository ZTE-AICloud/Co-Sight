# 安全规则、反硬编码与 REWORK 机制

> **由 proposal-agent.md 引用。生成 modifications 时必读。**

## 🚨 反硬编码原则(绝对过拟合屏障)

**每条 modification 应用前必查**:

- ❌ **`extract_to_script` 的 `extract_code` 绝对禁止含 case_id / RAN-xxx** —— 必须用通用占位符(`{req_id}` / `{case_id}` / `{work_dir}` / 通配符 / 循环)
- ❌ **禁止 `if RAN-xxx == "...": pass` 类的硬编码特判** —— 必须从 phase3-eval 抽取的字段动态判断
- ❌ **禁止在 `reason` 字段里引用具体 case_id** —— reason 必须泛化到所有同类需求
- ✅ **`scripts/validate_*.py` 必须是可重用的通用校验函数**

**反模式**:
```python
# ❌ 硬编码
if req_id == "RAN-3404224":
    scenario_type = "TBoMS 寻呼"

# ✅ 通用占位
scenario_type = extract_from_file(work_dir + "/06-标准场景名称识别.md")
```

## 量化边界硬约束(违反 REWORK)

- **每条 `new_content` ≤ 800 字符**(违反 → 应该拆到 `references/_common.md` 或 `scripts/X.py`)
- **总 modifications ≤ 6 条**(违反 → 砍低 cost_benefit 的)
- **`total_after_chars ≤ 1.3 × orig_skill_md_chars`**(违反 → 优先用 `extract_to_script` / `condense` / `delete_redense` 替代 `edit_exact`)
- **每轮至少 1 条 `extract_to_script`**(违反 → 显式声明"本 Skill 无可抽脚本"且 `self_check.files_outside_skill_md.scripts_count: 0` + reason 说明)
- **SKILL.md 行数 ≤ 500 才不触发 split_skill**(`> 500 行必须用 split_skill 拆 references/`)

## 真文件落地硬验证(借鉴 skill-optimizer-agent Phase 3 末尾)

每条 modification 应用后**必须**真实验证:

```bash
# 1. 验证 extract_to_script 创建的脚本文件存在
ls -la {{ skill_root }}/scripts/

# 2. 验证 Python 语法
python3 -c "import ast; ast.parse(open('{{ script_path }}').read())"

# 3. 验证 SKILL.md Edit 成功(FOUND/MISSING 自检)
python3 -c "
import sys
src = open('{{ skill_md_path }}').read()
cur = '''{{ current_content }}'''
print('FOUND' if cur not in src else 'MISSING')
"

# 4. 验证 references/_common.md 字符数(多 Skill 模式)
wc -c {{ skill_root }}/references/_common.md
```

**如果 MISSING** → 重新 Read + Edit(典型错误:H2 空格 / 列表缩进 / 中英文标点差异)。

## 当前内容读取校验链(避免 Edit 不匹配)

```python
# Step A:用 Read 工具读出文件完整字符串
# Step B:把 Read 输出**逐字符**复制到 current_content
# Step C(自检):用 Bash 跑
python3 -c "import sys; src=open('<file>').read(); cur='''<current_content>'''; print('FOUND' if cur in src else 'MISSING')"
#  MISSING → 重新 Read,补全差异
#  FOUND → 继续
```

**禁止凭印象写 current_content**。

## 红线汇总

| 想做的事 | 实际在犯的错 | 应改成的做法 |
|---------|------------|------------|
| "分步生成 context → gaps → modifications" | **破坏一次性硬约束** | 一次 LLM 调用全部完成 |
| "只输出 JSON 不动手 Edit" | **框架无法应用修改** | 用 Edit/Write 工具真实修改 |
| "只改 SKILL.md 不动 scripts/" | **违反修改覆盖硬约束** | 优先 `extract_to_script` 抽到 scripts/ |
| "`edit_exact add` 加新规则段" | **纯加规则反模式(实测 baseline→R3 +6.8% 反模式)** | 优先 `extract_to_script` / `condense` / `delete_redundant` |
| "current_content 凭印象写" | **Edit 匹配失败** | Read + Step A/B/C 自检到 FOUND |
| "evidence 写成'评测数据显示分数低'" | **不可定位** | 写具体 `phase3-eval/RAN-xxx/results/*.json: differences[0].diff_notes=...` |
| "root_cause 引用具体业务名" | **过拟合** | 改通用术语(如"特定协议特性"、"通信大类") |

## 失败 REWORK 重调机制

**caller 责任**(`context_extractor.run_optimize_agent`):

1. 解析 `optimization_summary.md` 头部 `self_check.overall_pass`
2. 若 `false` → 重调一次(`max_attempts=2`)
3. 若仍 `false` → 落盘 `optimization_summary.failed.md`(含两次尝试的 self_check + reason)
4. 保留 baseline(**不**回滚,因为 baseline 本身没改)

**优化 agent 自身的失败降级**:

- 5 维度预检信息不足 → self_check 全部填 `pass: false` + reason: "信息不足"
- 没有任何 gap 可修复 → `modifications: []`、`uncovered_gaps: []`、`overall_pass: true`(空修复算通过)