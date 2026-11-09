# dispatch — 委派执行通道指令

> 由 mcp-bridge-router 关键词路由表分发进入。执行类任务的完整步骤序列。

## 入口判定

确认任务类型，选择编目角色（CLAUDE.md 机制 3）：

- 编码/重构/调试 → executor（标准层）；多文件架构改动 → executor 深层请求
- 评审 → code-reviewer；测试 → test-engineer；文档 → document-specialist
- 库内定位/影响面调查 → explore（快速层）

## 执行步骤

1. **状态登记**：state_write（或 state/status.yaml）记录任务 id、目标、所选角色
2. **证据优先**：实现前查证官方文档/SDK 签名，不凭假设写调用
3. **并行**：两个以上独立子任务同时派发，不串行等待
4. **便签流转**：中间结论写 notepad 工作槽；长任务定期落状态，中断可续
5. **自证禁区**：本通道只产出"声称完成"，完成声明权在 verify 通道

## 产出

- 改动/研究产物本体
- 状态文件更新（status.yaml 记 done + 待核验标记）
- 给 verify 通道的交接摘要：声称完成了什么、证据在哪里、未覆盖什么
