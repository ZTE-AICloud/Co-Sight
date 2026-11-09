---
description: 直接对已绑定的个人资料目录做知识检索问答（三步法：章节树→读全文→综合答案）
argument-hint: [要检索的问题]
---

# CoSightBot 个人知识检索

对个人知识库执行一次检索问答。先读取 `"${CLAUDE_PLUGIN_ROOT}"/rules/pkm/retrieval-discipline.md` 与 `"${CLAUDE_PLUGIN_ROOT}"/rules/pkm/safety-constraints.md`，然后按 `cosightbot-retrieve` 技能的检索三步法完整执行：

1. **Step 1**：调 `cosightbot-retrieve` 主命令（或大库用 `resolve`）拿 `merged_overview` 章节树；
2. **Step 2**：按 `[F###]` 选最小充分集（通常 3–10 篇），read-doc 逐篇精读全文；
3. **Step 3**：组织答案，全部结论来自实读文档，引文附来源（S-03/S-04）。

红线：检索纯只读（S-01）；索引未构建时引导用户走 `cosightbot-material`，不得裸答；脚本失败必须阻断报告（S-05）。

若环境未首装（`exit 3` + `please_run_install`），先执行 `python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`。

---

$ARGUMENTS
