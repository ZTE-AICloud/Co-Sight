---
name: cosightbot-soc-analyze
description: >
  Excel 标书通读与方案提炼：把标书 Excel 转 Markdown 后按 Sheet 切分，
  Map-Reduce 并发调用大模型，输出 8 段结构化分析报告（标书概况/客户需求/
  硬件/软件/外购/厂商锁定/技术架构/综合结论）。在用户提供标书 Excel 并希望
  "快速通读/分析这份标书/提炼客户需求与方案"时触发。仅打印报告，不修改 Excel。
---

# cosightbot-soc-analyze —— 标书通读分析与方案提炼器

## When to Activate

- 用户给出一份标书 Excel（绝对路径），说"帮我看看这份标书 / 通读分析 /提炼客户需求 / 客户想要什么"
- 标书尚未进入「提取 → 应答 → 复核 → 回填」流水线，仅做总览分析

**Not for**：提取待应答需求列表（→ cosightbot-soc-extract）；单条需求应答（→ cosightbot-soc-answer）；批量应答（→ cosightbot-soc-respond）。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-analyze/scripts/analyze.py "<Excel标书绝对路径>"

# 自定义分析要求（可选）：
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-analyze/scripts/analyze.py "<Excel路径>" \
  --requirement "重点关注安全合规与厂商锁定条款"
```

- 中间产物：`<stem>.md`（Excel 同目录，每次覆盖重写）+ `<stem>.intermediate.json`（Map 阶段中间结果，`--no-intermediate-file` 可关）。
- 报告仅打印到 stdout，不修改原 Excel。

## 输出契约（硬性要求）

向用户汇报时，**必须把脚本输出的 8 段报告原封不动完整呈现**（`<!--ANALYSIS-REPORT-START-->` 与 `<!--ANALYSIS-REPORT-END-->` 之间）：

1. `## 📊 标书概况` 2. `## 🎯 客户主要需求` 3. `## 🖥️ 硬件方案` 4. `## 💻 软件方案`
5. `## 🛒 外购方案` 6. `## 🏷️ 厂商与专有技术分析` 7. `## 🔧 技术架构倾向` 8. `## 💡 综合结论`

- **严禁**合并段落、改标题 emoji/文字、抽取单段展示、重排顺序。
- **可以**追加上下文（如"以下是分析结果："、中间产物路径），但不得修改报告任何字符。
- 报告中的统计数字是 LLM 粗略估算（非精确计数）；精确统计走 cosightbot-soc-extract。

## 行为契约

- **任何 chunk 失败 → exit 1**（不允许"看似完整但缺 sheet"的假报告）；如实报告失败 sheet 列表，排查后重跑。
- 超大 sheet（>60K 字符）会被二次切分，脚本会显式警告；此时汇报给用户并建议调大 `--max-chunk-chars` 或先拆分 sheet。
- Excel 转 md 为空 → exit 1（不基于空材料编造报告）。

## 依赖

- LLM 配置：`数据根目录下的 .env` 中 `OPENAI_*`（主配置；未配时回退继承 Claude Code 会话的 `ANTHROPIC_*`）。
- Python 依赖 `aiohttp` / `openpyxl`（"${CLAUDE_PLUGIN_ROOT}"/scripts/install.py 安装）。

## 环境自检（preflight）

脚本返回 **exit 3** + `{"hint": "please_run_install", ...}` 时：执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`。**不得绕过**（S-05）。

## 执行方式与汇报

- 分钟级任务（Map 并发 + Reduce 汇总）：后台执行，启动后告知用户「已开始分析标书，完成后我会汇报」；不要中断脚本。
- 完成后原样呈现 8 段报告，并附上中间 md / intermediate.json 路径。

## 检查清单

- [ ] 报告 8 段齐全、顺序固定、未被改写
- [ ] 有 chunk 失败时如实报告失败，未呈现残缺报告
- [ ] 超大 sheet 切分警告已转达用户
- [ ] preflight 失败时执行了 install.py 而非绕过
