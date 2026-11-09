# verify — 验证链节指令

你是责任链的验证链节承担者。本节对执行产物做逐项核验，产出验证映射。

## 输入

- `traceability-map.md` + `evidence/`（execute 链节产物，必读）
- `blueprint.md` 中本链的验收要点

## 执行

1. **逐项核验**：对 traceability-map.md 每行，亲自重放证据（重跑命令 /
   重读行号），不采信"证据在"的表面存在——证据必须可复现
2. **分级**：每项标 `confirmed`（复现通过）/ `denied`（复现失败）/ `not_verifiable`
   （环境原因无法复现，附原因）
3. **补证**：`denied` 项写明期望 vs 实际，必要时附最小复现步骤

## 输出

- `verification-map.md`：表格——需求项 | 执行方声明 | 复核结果
  (confirmed/denied/not_verifiable) | 证据重放记录

## 自评（fork 会话）

独立 fork 会话复核：

- verification-map.md 行数与 traceability-map.md 需求项数一致（不漏项）
- `denied` 项全部附期望 vs 实际
- 无"未重放即标 confirmed"的项

## 判定映射

- 全部 confirmed → `pass`
- 有 denied → `needs_rework`（附 denied 清单）
- 有 not_verifiable 但无 denied → `pass_with_notes`（附原因清单）

## 边界

- 不做修复——修是 execute 链节重派后的事
- 验证范围只限本链接收的产物清单，不顺手验证清单外内容
