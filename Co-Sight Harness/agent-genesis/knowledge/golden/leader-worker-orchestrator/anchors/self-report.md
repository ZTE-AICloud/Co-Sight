---
mode: create
skill_or_agent_name: leader-worker-orchestrator
anchored_mode: WF5-Contract-Lock
summary:
  verdict: PASS
  file_counts:
    generated: 4
revision_rounds: 0
---

# self-report（leader-worker-orchestrator 过程锚, derived）

> derived: true——外部启发过程锚（策展人按改造后资产撰写）, 非真实构建
> 产物。本报告对应 v1.2 批 2 外部集成实例包抽取全程（REFLUX.md §3 七步）。

## 七步留痕

1. 选件：源库 claude-orchestrator（golden-examples 外部参照库, 8 包
   TypeScript monorepo, 约 231 文件）——形态完整（Leader/Worker 模型 +
   责任链 + 判定协议 + 工作者八步流水线）, 可蒸馏出契约锁定编排骨架。
2. 重映射：旧词汇 → 现行词汇——责任链 Plan→Build→Verify→Review→Accept
   → WF5-Contract-Lock 五节契约；EvalDecision 五变体 → 判定协议五变体
   （pass/pass_with_notes/needs_rework/blocked/escalate 语义照收, 表述
   自有化）; Worker 8-step pipeline → 工作者执行序列八步；
   TaskQueue/MessageRouter/InstanceRegistry → 协调后端外部件位三抽象。
3. 挂靠：mode_id=WF5-Contract-Lock（货架位）, anchor_fit=real——源
   责任链 + EvalDecision JSON 契约 + 协议版本号即契约锁定编排的纯正
   实现（机械路由不重评）, 非强制贴合。
4. 重塑：agent 线形态（CLAUDE.md 入口 + prompts/ 三件指令文件
   plan/execute/verify, 对应责任链前三节; review/accept 节由 CLAUDE.md
   责任链表覆盖, 不单列指令——池教的是编排契约, 不是源项目全部链节
   实现）; 身份消毒——源项目名/作者名/npm 包名/工作者化名清单
   （Tom/Jerry/Lucy…）/包名空间（@co/*）全部移除或通用化
   （worker-01 式命名）; 协调后端去具体实现绑定（ZooKeeper 降为
   "分布式锁一族"可选件位）。
5. 补锚：本 build-plan + 本 report, derived: true。
6. manifest：按 golden-manifest schema 全字段; acceptance 恰好 4 条。
7. 准入：REFLUX.md §3 第 7 步, G028 agent-exit 档, concerns 如实回填
   known_concerns。

## 粒度与范围裁定

源为 8 包 monorepo + TUI 仪表盘 + 模板/skill 全套, 本就不是最简源。
范围裁定：只取编排契约层（责任链/判定协议/执行序列/协调后端抽象）与
三个代表性链节指令; TUI 实现、React 面板、npm 发布工程、magic mode
探索链森林不进池——池教的是"链节契约锁定"机制, 不是源项目的终端
产品工程。

## 交付描述

Agent 线金包：CLAUDE.md 入口（五节责任链契约 / 判定协议五变体 /
工作者八步序列 / 协调后端外部件位 / 目录记忆规则 / Not for）+
prompts/ 三件自包含链节指令（plan 拆链定契约 / execute 追溯留证 /
verify 重放分级）。全部内容为重塑后自有表述, 无源项目标识残留。
