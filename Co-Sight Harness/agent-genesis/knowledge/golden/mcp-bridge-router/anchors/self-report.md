---
mode: create
skill_or_agent_name: mcp-bridge-router
anchored_mode: W2-Router
summary:
  verdict: PASS
  file_counts:
    generated: 3
revision_rounds: 0
---

# self-report（mcp-bridge-router 过程锚, derived）

> derived: true——外部启发过程锚（策展人按改造后资产撰写）, 非真实构建
> 产物。本报告对应 v1.2 批 2 外部集成实例包七步抽取全程（REFLUX.md §3）。

## 七步留痕

1. **选件**：外部参照库 oh-my-claudecode（多 agent 编排层, MIT）。取其
   路由分发切片——关键词触发/委派编目/模型分层/外部工具桥接——作为
   W2-Router 的"带工具桥接"变体样例。
2. **重映射**：旧词汇 → 现行词汇——路由分发 = W2-Router; 查表/确定性
   分发 = MN-Deterministic; 委派规则集 = K4-Rule-Driven; 单线交接 =
   DT1-Linear-Pass-Through。源仓团队流水线/钩子/技能市场等超集维度
   不属于本切片, 不映射入包。
3. **挂靠**：mode_id=W2-Router（货架位）, anchor_fit=real——源仓为编排
   超集, 本包只蒸馏其路由分发+工具桥切片, 切片本身为 W2 纯正实现
   （查表分发, 不含业务逻辑）。
4. **重塑**：agent 线形态（CLAUDE.md 入口 + prompts/ 指令文件 ×2）;
   身份消毒——源仓名/作者名/品牌技能名（autopilot/ralph 等）/专用 CLI
   （/team、omc ask）全部移除或通用化; `.omc` 状态目录通用化为
   `state/`; 外部 AI 供应方（多供应方 CLI 桥）改写为"用户自备接口位"
   抽象, 包内零绑定。源 CLAUDE.md 约 118 行蒸馏为含 When to Use /
   核心机制四件 / 文件状态交接 / 执行协议 / Not for 的 1 入口 2 通道形态。
5. **补过程锚**：build-plan 三文件如实计数（agent_entry 1 + prompt_files 2
   + scripts 0 + templates 0）; invariants 按改造后资产实际字面量书写。
6. **manifest**：derived: true + provenance 如实（origin_repo / MIT /
   snapshot_date 2026-10-17 / reshaped: true）。
7. **G028 准入**：agent-exit 档直调, output_dir=包内 output-snapshot,
   skills/rules 走 .gitkeep 诚实占位。结果与 concerns 如实回填 manifest。

## 与 command-router（W2 既有包）的差位

command-router = 纯路由最简形（4 指令文件, 零外部依赖）;
mcp-bridge-router = 路由 + 外部工具桥接变体（2 通道 + 用户自备工具
接口位 + 文件状态降级交接）。同货架位双样例, 命中时由 multi_hit_rule
裁决, 不构成重复（形态差异真实）。
