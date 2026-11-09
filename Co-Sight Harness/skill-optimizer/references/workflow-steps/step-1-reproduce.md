# Step 1: Reproduce(重现失败)— Read 全部 diff 报告

> **对应 debug-pro Step 1**:让失败 case 一致性重现。

## 目标
收集 Skill 全貌 + 失败证据,确保每个失败 case 都有"gold vs LLM 实际输出"的 3 列差异证据可读。

## 必做动作(1 个 message 内并发)

- `Bash`: `find {{ skill_root }} -type f | grep -v __pycache__`
- `Read`: 每个 SKILL.md / scripts/ / templates(提取 H2 章节)
- **`Read`: user prompt 顶部「📜 必读历史数据」清单中的全部文件**(每轮 改动 + 结果 两份)

每份 result_diff_report 含:
- F1 分数 / gold 答案 / LLM 实际产出 / diff_notes 五维评分
- 失败 case 必有「gold vs LLM 实际输出」3 列差异(用户/场景/问题)
- diff_notes 直接对应 M1-M7 失败模式标签

## ⚠️ 不要再读 `data/` 下任何文件

**铁律**:`data/`(含 `data/phase3-eval/*/results/*.json`、`data/phase4-diagnosis/findings.json`、`data/phase3-eval/*/inputs/agent/*.md` 等)是 framework 生成的中间产物,**gold / LLM / diff_notes 已经在 `result_diff_report_*.md` 里**,**不需要**绕路去 `data/` 重新打开。

**禁止**读取:
- ❌ `data/phase3-eval/*/results/*.json`(原始 eval_data.json / 5 维评分)
- ❌ `data/phase4-diagnosis/findings.json`(跨 case 聚合)
- ❌ `data/phase3-eval/*/inputs/gold/*.md`(gold 原文 — 已在 result_diff 的 `#### 1. gold 答案` 段)
- ❌ `data/phase3-eval/*/inputs/agent/*.md`(LLM 实际产出 — 已在 result_diff 的 `#### 2. Skill 实际产出` 段)
- ❌ `data/phase1-build/` / `data/phase2-exec/`(Skill 流水线的中间产物,LLM 优化不需要)
- ❌ `data/phase4-diagnosis/`(同上)

**正确做法**:全部依赖 user prompt 顶部注入的「📜 必读历史数据」清单(含 `result_diff_report_*.md` + `skill_diff_round_*.md`)。

**result_diff_report 每个 case 段的真实 4 段结构**(LLM 在清单里读到的内容):
1. `#### 1. gold 答案` — markdown 表格嵌入(完整呈现,不是路径引用)
2. `#### 2. Skill 实际产出(LLM 输出)` — markdown 表格嵌入
3. `#### 3. LLM-as-Judge diff_notes` — 5 维评分原文 + 总分判定
4. `#### 4. 资源消耗` — duration_ms + input_tokens + output_tokens

## 硬约束

- ❌ **禁止**读 `data/` 下任何文件(包括 phase1/2/3/4 全段)
- ✅ Read 完成后,**在 `_read_audit.json` 记录**所有 Read 过的路径(全在清单里,不包含 data/)

## 失败处理

如某份清单文件不存在 → 报错回退,不要凭印象继续,**更不要**去 `data/` 找替代源。