---
name: bootstrap-data-completer
description: "Use when a user has partial drive inputs (existing subagents/skills/workflow but no complete manifest/taskRecord) and needs a deterministic bootstrap pass to diagnose gaps and prepare completion patches."
user-invocable: true
---

# Bootstrap Data Completer

## Workflow

1. Diagnose what already exists and what is missing.
2. Draft a completion spec using current drive field names.
3. Produce patch candidates only.
4. Validate structure and intent before any materialization.

## Rules

- Preserve user wording and field names.
- Do not invent business goals.
- Do not directly write baseline taskRecord files.
- 默认不修改用户原始 Agent/Skill/workflow。
- 默认不修改 baseline taskRecord。
- Do not treat inferred values as user-confirmed facts.
- Prefer `completion-spec.yaml` and patch files over free-form prose.

## Required Outputs

产物写到 `<work_dir>/.drive/<plan_dir>/inputs/proposal.md`（补全后的提案文档），**不要**用 `.drive/<plan_dir>/bootstrap/` 子目录。

`inputs/` 是用户输入文件的约定位置，planning_write_guard 的白名单放行它。`bootstrap/` 虽然也在白名单里，但它是按约定放行的子目录名，不应成为新 skill 的默认产物路径 —— 除非用户**明确要求**写到 `bootstrap/`，那时它是 first-class 异常路径，需用户在 workflow.yaml 或提案里声明并扩展白名单。

产物格式：
- 单个 markdown 文件，包含补全后的完整提案
- 保留用户原始措辞和字段名
- 标注推断的部分，区分已确认与待确认

## Field Coverage

Use the reference schema for mapping partial user input to current drive fields.

- Existing agent or skill entry shape -> `execution_entry`, `execution_type`, `subagent_type`, `skills`
- Existing workflow order and outputs -> `expected_outputs`, `read_first_path`, `steps`
- Existing artifact and review cues -> `files_owned`, `shared_files`, `output_schema`, `verify`, `acceptance_criteria`
- Existing override intent -> `.drive-overrides.yaml`

If the input is too weak to infer safely, stop at diagnosis and mark the gap for user confirmation.

See [bootstrap-schema.md](references/bootstrap-schema.md) for the machine-readable field mapping.
