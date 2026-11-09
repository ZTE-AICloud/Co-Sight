---
name: cosightbot-soc-respond
description: >
  标书需求 JSON 的批量历史范式应答：对提取出的需求列表逐条检索本地知识库的
  历史应答范式，自动继承合规度（FC/PC/NC）、备注与参考文件，快速生成批量初步应答。
  在用户要求"批量应答/对需求 JSON 做初步应答/跑一遍历史范式匹配"时触发。
  输入为需求 JSON（cosightbot-soc-extract 的产物），输出 `<stem>-已应答.json`。
---

# cosightbot-soc-respond —— 批量历史范式应答器

## When to Activate

- 用户说"批量应答这份需求 JSON / 跑一遍历史范式匹配 / 初步应答"
- 位于 SOC 流水线：extract（需求提取）→ **respond** → review → fill

**Not for**：单条需求深度应答（→ cosightbot-soc-answer）；标书整体通读分析（→ cosightbot-soc-analyze）；Excel 需求提取（→ cosightbot-soc-extract）。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-respond/scripts/respond.py "<待应答JSON路径>" \
    [--req_field requirement] [--comp_field compliance] \
    [--remarks_field remarks] [--ref_field reference_document]
```

- `in_json`（必填）：待应答 JSON。支持两种结构：标准 `{"source_file": ..., "items": [...]}`或裸数组/单对象；输出保持原结构。
- 产物：**`<stem>-已应答.json`，写入与输入同目录**（禁止在文件名中间插入其他后缀——下游 cosightbot-soc-review / soc-fill 依赖该命名约定）。
- 字段映射参数仅在用户的 JSON 键名非标准时才传。

## 行为契约

- **只检索历史范式**（`historical_paradigms`），不检索产品规范——保证回填 Excel 时排版清爽；需要产品规范深度分析时用 cosightbot-soc-answer。
- 相似度 < 0.45 视为未命中：该条 compliance **留空**、confidence=0，`review_notes` 写「未命中知识库（相似度阈值 0.45），需人工应答」，`matched_req` 为空（下游 review 跳过未命中项的复核；fill 阶段合规列留空， validate 强制列出未命中清单——红线：未命中不得带默认 FC 直达回填）。
- **知识库未就绪 → exit 1 且不写任何产物**（零兜底：不允许"看起来已应答"的占位 JSON 进入下游）。未就绪时按报错引导用户先用 cosightbot-soc-kb-build 构建知识库。
- Embedding 服务失败/返回不完整 → exit 1（部分向量缺失 = 检索结果不可信）。

## 环境自检（preflight）

脚本返回 **exit 3** + `{"hint": "please_run_install", ...}` 时：执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`（幂等、非交互），并按 `数据根目录下的 .env` 引导配置`COSIGHTBOT_EMBEDDING_API_URL/KEY`（本技能必需）。**不得绕过**（S-05）。

## 执行方式与汇报

- 条目较多时是分钟级任务：后台执行（run_in_background），启动后告知用户「已开始批量应答，完成后我会汇报」。
- 完成后按脚本统计输出汇报：「应答完成：共 N 条，高置信 X / 中置信 Y / 低置信 Z，产物 `<stem>-已应答.json`」，并提示下一步做 LLM 复核（cosightbot-soc-review）。

## 检查清单

- [ ] 输入 JSON 是 extract 产物或同构 JSON（含 requirement 字段）
- [ ] 产物文件名严格为 `<stem>-已应答.json`，与输入同目录
- [ ] 知识库未就绪/embedding 失败时如实报错，未产出占位文件
- [ ] preflight 失败时执行了 install.py 而非绕过
