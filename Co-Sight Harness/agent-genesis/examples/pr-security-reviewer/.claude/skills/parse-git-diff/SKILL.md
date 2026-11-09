---
name: parse-git-diff
description: 将统一格式 git diff 解析为结构化 changes[]（file/hunks/added_lines）。当 PR 审查流程需要消费 diff 内容时触发。输入为 diff 文本或 git diff 命令输出，输出为结构化 JSON。
---

# Parse Git Diff — 结构化解析 Skill

## 触发条件
- PR 审查流程的步骤 2（解析）
- 任何需要按文件/行分析 diff 变更的场景

## 输入
- `$ARGUMENTS` 为以下之一：
  - `cmd:<git 命令>`（如 `cmd:git diff main...HEAD`）——执行并解析其输出
  - `file:<path>` —— 读取 diff 文件
  - 直接粘贴的 diff 文本（以 `diff --git` 开头）

## 执行步骤

1. **获取 diff 文本**：cmd 模式执行后校验首行含 `diff --git`；否则报 `INVALID_INPUT`（CD1）
2. **解析**（优先 Bash + python3，不依赖 LLM 逐行推理）：
   ```bash
   python3 <SKILL_DIR>/scripts/parse_diff.py <raw.diff>
   ```
   输出结构：
   ```json
   {
     "files": [
       {
         "path": "src/api/user.py",
         "lang": "python",
         "hunks": [{ "start": 42, "added": ["+    query = ..."], "removed": [] }],
         "added_lines": ["..."],
         "is_new": false,
         "is_binary": false
       }
     ],
     "stats": { "files_changed": 1, "additions": 12, "deletions": 3 }
   }
   ```
3. **大 diff 分块**：>500 行时按文件切分为 chunks，逐块交给审查方（避免单次超长 context）

## 失败处理
- 空 diff（无文件变更）→ 返回 `{"files": [], "stats": {...}}`，调用方直接出 `verdict: pass`
- 非统一格式 patch → `UNSUPPORTED_FORMAT`，提示使用 `git diff` 标准输出

## 禁止
- 禁止在本 Skill 内做任何审查判断（只解析，不评价 — 单一职责）
