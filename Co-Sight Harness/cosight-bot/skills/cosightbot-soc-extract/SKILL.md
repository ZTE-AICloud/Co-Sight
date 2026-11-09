---
name: cosightbot-soc-extract
description: >
  从 Excel 标书中提取待应答需求条目：甄别需求 sheet、剥离填表指南等非需求页，
  用 Python（openpyxl）把需求编号/描述/合规列/备注/参考文件抽取为结构化 JSON，
  产物 `<stem>-需求提取.json` 经 validate.py 硬性自检后进入应答流水线。
  在用户提供标书 Excel 并要求"提取需求/开始应答流程"时触发。零兜底：
  解析不了就报错，严禁编造条目。
---

# cosightbot-soc-extract —— 标书需求提取器（CC 原生）

## When to Activate

- 用户提供标书 Excel，说"提取需求 / 开始应答流程 / 把待应答项抽出来"
- SOC 流水线入口：extract → respond → review → fill

**Not for**：标书整体通读分析（→ cosightbot-soc-analyze）；单条需求应答（→ cosightbot-soc-answer）。

## 执行方式（CC 原生：你亲自写 Python 提取）

由**你（Claude）直接用 openpyxl 写提取代码**，格式千差万别时按本文件的规则适配。流程固定四步：

### Step 1 — 勘察结构

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-extract/scripts/inspect_excel.py "<Excel路径>"
```

> preflight：`inspect_excel.py` 依赖 `.venv-soc` 中的 openpyxl——环境未首装时退出码 3 且输出 `{"hint": "please_run_install"}`，先执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py` 再重试（`validate.py` 为纯 stdlib，不受此限）。

输出每个 sheet 的表头候选行、前列样例、合并单元格概况。据此判断：

- **哪些 sheet 是应答列表**：含"需求/要求/Requirement"类列且行内容像需求条目的 sheet；填表指南、封面、目录、说明、资质要求类 sheet 一律跳过（不确定时在提取结果中如实说明跳过了哪些 sheet 及原因）。
- **表头行**：不一定是第 1 行（可能在 2/3 行）；以含"需求/要求"列名的行为准。
- **列映射**：编号列（No/编号/序号/ID/Item/Ref/#）、需求列（需求/要求/Requirement/Description）、合规列（Compliance 单列 或 Complied/Partial Complied/Not Complied 三列）、备注列（备注/说明/Remarks）、参考文件列（参考文档/Reference）。

### Step 2 — 写提取代码并执行

用 `.venv-soc/bin/python` + openpyxl 写一段提取脚本（在 `数据根/` 下建临时脚本，如 `数据根/tmp_extract_<stem>.py`），规则：

- **逐真实需求行提取**：沿编号列从上往下扫到 `max_row`；中间空行跳过；编号列非空（允许 `B1`、`A-3` 等字母数字编号）且需求列非空的行才是候选。
- **排除章节标题行**：编号为**纯正整数 n** 且范围内存在以 `n.` 开头的编号（如 n=1 存在 1.1/1.2）→ 该行是章节占位行，**不提取**；纯整数但无子编号的（如只有 10 没有 10.x）是顶层真实需求，**保留**；含字母的编号（B1 等）不参与标题行判定，一律保留。
- **compliance 归一**（仅当标书本身已填了合规列时；未填写 null）：
  - `Complied` / `Y` / `Yes` / `满足` → `"FC"`
  - `Partial Complied` / `P` / `部分满足` → `"PC"`
  - `Not Complied` / `N` / `No` / `不满足` → `"NC"`
  - 无明确合规信息 → `null`
  - 三列式（Complied/Partial/Not Complied 各一列）：哪列打了 Y/✓/√ 取哪个。
- **零兜底**：需求列整列读不到、表头识别失败、条目数为 0 → 直接报错给用户（附上 inspect 输出与失败原因），**严禁编造条目或凭猜测补内容**。

### Step 3 — 写产物 JSON

产物路径：**与原 Excel 同目录，命名 `<原stem>-需求提取.json`**（例：`标书.xlsx` → `标书-需求提取.json`）。命名不可改——下游 cosightbot-soc-respond 的产物名基于它派生。结构：

```json
{
  "source_file": "<原 Excel 文件名>",
  "total_demand_items": 6,
  "items": [
    {
      "sheet": "技术需求",
      "row": 2,
      "no": "1.1",
      "requirement": "路由器须支持 Wi-Fi 6",
      "compliance": null,
      "remarks": "",
      "reference_document": ""
    }
  ]
}
```

### Step 4 — 硬性自检（不过不得进入下游）

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-extract/scripts/validate.py "<stem>-需求提取.json"
```

exit 0 才算提取完成；exit 1 时按违规明细修提取代码重跑（S-05：禁止绕过自检直接把 JSON 交给下游）。

## 汇报话术

- 完成：「需求提取完成：共 N 条（覆盖 X 个 sheet），产物 `<stem>-需求提取.json`，可以开始批量应答」；如有跳过的 sheet 或无法归一的合规值，如实列出。
- 失败：如实报告失败点（哪个 sheet、哪一行、什么原因），不得输出部分产物声称完成。

## 检查清单

- [ ] inspect_excel 勘察过全部 sheet，跳过决策有依据
- [ ] 章节标题行已排除，条目数与 Excel 实际需求行数一致
- [ ] compliance 只用 FC/PC/NC/null
- [ ] 产物命名 `<stem>-需求提取.json`，与原 Excel 同目录
- [ ] validate.py exit 0 后才进入 cosightbot-soc-respond
