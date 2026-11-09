---
description: 执行标书应答全流程：需求提取 → 批量应答 → LLM 复核 → 回填 Excel（另存新文件）
argument-hint: [标书 Excel 路径]
---

# CoSightBot 标书应答流水线

对指定标书 Excel 执行完整应答流水线：**extract → respond → review → fill**。先读取 `"${CLAUDE_PLUGIN_ROOT}"/rules/soc/response-orchestration.md` 与 `"${CLAUDE_PLUGIN_ROOT}"/rules/soc/safety-constraints.md`，然后依次执行：

1. **cosightbot-soc-extract**：勘察 Excel → 提取需求条目 → `validate.py` 自检（exit 0 才继续）；
2. **cosightbot-soc-respond**：批量应答（向量匹配历史范式）；知识库未构建时先走 `cosightbot-soc-kb-build`；
3. **cosightbot-soc-review**：LLM 复核（冲突标记，失败率 >30% 终止）；
4. **cosightbot-soc-fill**：回填 Excel，**另存 `<stem>-应答后.xlsx`**，不覆盖原件（S-06）。

红线：构建必须实际执行（S-02）；脚本失败阻断报告（S-05）；零兜底话术，知识库未命中如实呈现。

若环境未首装（`exit 3` + `please_run_install`），先执行 `python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`。

---

$ARGUMENTS
