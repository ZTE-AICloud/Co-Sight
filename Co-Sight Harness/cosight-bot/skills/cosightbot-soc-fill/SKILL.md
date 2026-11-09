---
name: cosightbot-soc-fill
description: >
  把应答 JSON 回填到标书 Excel：复制原标书另存 `<stem>-应答后.xlsx`（严禁覆盖原件），
  用 Python（openpyxl）按需求文本匹配把 FC/PC/NC、备注、参考文件与 8 个溯源新列
  写入对应行，冲突行红色高亮，最后经 validate.py 硬性自检。
  在用户拿到已应答/已复核 JSON 并要求"回填 Excel/生成应答后标书"时触发。
---

# cosightbot-soc-fill —— 标书应答回填器（CC 原生）

## When to Activate

- 用户拿着 `*-已应答.json` 或 `*-已大模型复核.json`，说"回填到 Excel /生成应答后的标书 / 写回原件"
- SOC 流水线收尾：extract → respond → review → **fill**

**Not for**：需求提取（→ cosightbot-soc-extract）；批量应答（→ cosightbot-soc-respond）。

## 执行方式（CC 原生：你亲自写 Python 回填）

由**你（Claude）直接用 openpyxl 写回填代码**。输入 = 原标书 Excel + 应答 JSON（优先用 `*-已大模型复核.json`，用户只跑了 respond 时用 `*-已应答.json`）。流程固定五步：

### Step 1 — 另存副本（S-06 红线）

**先复制** 原 Excel 为 **同目录 `<原stem>-应答后.xlsx`**，后续所有写入只动副本。严禁写回原文件。已存在旧 `-应答后` 文件时先删除再复制（避免新旧内容叠加）。

### Step 2 — 定位表头与真实需求行

- **表头行 header_row**：从前几行扫描，含 编号/No/序号/ID/Item/Ref 类关键词的最浅一行（不要假设 row 1；取最靠上的候选行）。
- **真实需求行**：沿编号列扫到 `max_row`，编号列非空（允许 `B1`、`A-3` 等字母数字编号）且需求列非空；中间空行跳过。
- **排除章节标题行**（充要条件，只看编号结构不看文本）：(i) 编号为纯正整数 n；(ii) 数据范围内存在以 `n.` 开头的编号。含字母的编号不参与标题行判定，一律视为真实需求行。标题行**绝对不能写入任何内容**（原列+新列都不行），原格式原样保留。
- 写数据前先把识别结果打印出来：`标题行集合: {...}` 和 `真实数据行: N 行`。

### Step 3 — 按需求文本匹配写入（不按位置索引）

- 对每条 JSON：`requirement` 归一化（去首尾空白 + `\n`/`\r` 折叠为单空格），在真实需求行范围内找**完全相同**（归一化后）的行写入；写完从候选中移除该行。
- 找不到匹配行：打印 `[文本匹配失败] JSON[k] requirement=...` 并跳过，不得写到任何"差不多"的位置。
- **合规列两种格式**：
  - 三列式（Complied / Partial Complied / Not Complied）：按 FC/PC/NC 在对应列填 `Y`，其余两列留空；
  - 单列 Compliance：直接填 `FC` / `PC` / `NC`。
- **未命中条目（JSON `compliance` 为空）**：合规列**必须留空**，严禁自行补 FC/PC/NC；【其他说明】列写入 `review_notes`（含「未命中知识库」标记）。回填完成后必须向用户报告未命中清单，提示人工应答。
- 备注、参考文件列保持原格式填写。

#### 重复 requirement 文本（Edge Case）

当 Excel 表内存在 ≥2 条**requirement 文本完全相同**的真实需求行时（例如同一规格在不同章节被重复罗列），按以下流程处理：

1. **extract 阶段**：保留全部 N 条原始条目（忠实于源数据）。
2. **fill 阶段**：对归一化后 `requirement` 字段相同的 JSON 条目，**按 JSON 顺序依次匹配到 Excel 中不同的行**：
   - 维护 `text_to_row`：按归一化文本索引真实需求行，并保留每行的 `sheet`、`row` 和编号；
   - 优先用 JSON 条目的 `sheet` / `row` 找对应候选，确认该行文本完全匹配后回填；这些字段来自 extract 阶段；
   - 只有输入 JSON 确实不含来源行字段时，才可按同文本候选行顺序分配；若文本在 Excel 中重复且无法唯一对应，停止并报告歧义，不要猜测。
   - 保留 extract 产物中的 `sheet` 和 `row`，用它们确定每条需求的原始行，不要只凭重复文本推断行。
3. **validate 阶段**：校验器以 JSON 的 `sheet` / `row` 对应原 Excel 行为准，确认产物同一行仍含原需求文本，且回填合规值与该 JSON 条目一致；多条 JSON 指向同一来源行或行信息无效时拒绝通过。

参考实现片段：

```python
# 按文本归一化建索引，保留来源 sheet/row（key -> [(sheet, row, no), ...]）
text_to_row = {}
for sheet, r, no, req in real_data_rows:
    text_to_row.setdefault(norm(req), []).append((sheet, r, no))

# 按 JSON 来源行匹配，重复文本因此能稳定落到各自的原始行
used_rows = set()
for it in items:
    key = norm(it["requirement"])
    candidates = text_to_row.get(key, [])
    source = (it.get("sheet"), it.get("row"))
    match = next(
        (candidate for candidate in candidates
         if candidate[:2] == source and candidate[:2] not in used_rows),
        None,
    )
    if match:
        sheet, r, no = match
        used_rows.add((sheet, r))
        matched.append((it, r, no))
    else:
        unmatched.append(it)
```

不要改写或合并原 Excel 中的重复需求来规避歧义。若 JSON 含重复文本但缺少 `sheet` / `row` 来源信息，validate.py 无法安全判断条目对应哪一行，应报告歧义并拒绝通过；应从 extract 阶段保留准确的来源行信息后重新处理。

### Step 4 — 新增 8 列溯源信息 + 冲突高亮

在原表**最右一列的右侧连续**（`last_header_col + 1` 起，不留空列）、**与主表头同一行**（header_row，不一定是 row 1）新增 8 列表头：

| 新列表头 | JSON 字段 |
|---------|-----------|
| 检索来源 | `source_type` |
| 检索来源文件 | `source_file` |
| 资料入库时间 | `source_time`（兼容 `created_at`） |
| 匹配到的需求描述 | `matched_reqs`（复数；兼容单数 `matched_req`） |
| 置信度 | `confidence` |
| 是否冲突 | `conflict`（写 是/否） |
| 大模型复核 | `llm_review_result` 的判定词——**只写 符合/部分符合/不符合 之一** |
| 其他说明 | `review_notes`（详细理由/冲突说明） |

- 【大模型复核】列严禁附加"原因:""警告:"等后缀；【其他说明】才放详细文本，两列严禁雷同。
- **红色高亮**：遍历【是否冲突】列，值为"是"的单元格设置纯红填充：`PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")`。
- **内容纯净**：单元格只写纯业务内容——严禁把 `<think>` 块、```json``` 标记、"JSON解析失败:" 等调试前缀写进单元格；判定词用纯中文，不加 emoji。
- **不动既有格式**：不修改原有合并单元格、字体、颜色。

### Step 5 — 硬性自检（不过不得交付）

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-fill/scripts/validate.py \
  "<原Excel路径>" "<应答JSON路径>"
```

exit 0 才算回填完成（若输出含「⚠️ 未命中知识库」清单，必须原文转达用户并提示人工应答）； exit 1 按违规明细修复重跑（S-05：禁止绕过自检交付）； exit 3 + `{"hint": "please_run_install"}` 表示环境未首装（validate.py 依赖 .venv-soc 中的 openpyxl）——先执行 `python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py` 再重试。

## 汇报话术

- 完成：「回填完成：共 N 条已写入（M 条冲突已标红），产物 `<stem>-应答后.xlsx`（原文件未改动）」；有文本匹配失败的条目必须逐条列出。
- 失败：如实报告（哪条 JSON、什么原因），不得交付部分回填的产物声称完成。

## 检查清单

- [ ] 原 Excel 未被修改，产物为另存的 `-应答后.xlsx`
- [ ] 标题行识别结果已打印，标题行零写入
- [ ] 8 个新列紧贴原表最右列、与主表头同行
- [ ] 冲突单元格已红色填充；单元格无调试文本/思考块
- [ ] validate.py exit 0 后才交付
