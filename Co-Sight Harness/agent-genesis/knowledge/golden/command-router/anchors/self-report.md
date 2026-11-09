---
mode: create
skill_or_agent_name: command-router
anchored_mode: W2-Router
summary:
  verdict: PASS
  file_counts:
    generated: 4
revision_rounds: 0
---

# self-report（command-router 过程锚, derived）

> derived: true——外部启发过程锚（策展人按改造后资产撰写）, 非真实构建
> 产物。本报告对应 G2 批次 gacui-claude 包六步全程（§3.5）。

## 六步留痕

1. 选件：源库 complete 档 gacui-claude（G2 批 4 包之一, 方案 §4 G2 步骤 1）。
2. 重映射：pattern_mapping 旧词汇 → 现行词汇——W2-Router 照收; MN-Deterministic
   → MN-Deterministic 无漂移; K4-Rule-Driven / DT1-Linear-Pass-Through /
   IH1-Fire-and-Forget / CD1-Input-Gating 均为现行 id 照收。无拓扑模式维度。
3. 挂靠：mode_id=W2-Router（货架位）, anchor_fit=real——源 CLAUDE.md 即
   W2-Router 的纯正最简实现（首词路由 + 启发式回退, 不含业务逻辑）,
   非强制贴合。
4. 重塑：agent 线形态（CLAUDE.md 入口 + prompts/ 指令文件 ×3, 对应
   build-planner 产 agent 线的 required_files 骨架）; 清洗标识——源项目
   名（GacUI/vczh）/语音输入个性化署名/项目内文件名（ask/investigate/
   kb/refine 重构为 *.instruction.md 自有命名）全部移除或通用化; 源 67 行
   CLAUDE.md 扩充为含 When to Use / 核心机制 / 维护约定 / Not for 的
   完整 Agent 入口件（对齐 agent-output-standard.yaml 入口件形态）。
5. 补锚：本 build-plan + 本 report, derived: true。
6. 准入：§3.4 流程, G028 agent-exit 档 failures=0。

## 粒度与范围裁定

源项目为 65 行 CLAUDE.md + 4 个 prompt 文件, 本就不是多能力清单型源,
粒度裁定不触发（区别于 skill-router 的 8-Skill 插件集先例）。范围裁定:
只取路由协议与 3 个代表性指令文件（ask/investigate/kb）, refine 指令
（源项目特定学习备份工作流）不进池——池教的是路由机制, 不是源项目的
业务指令内容。

## 交付描述

Agent 线金包：CLAUDE.md 入口（首词路由表 / 启发式回退 / 指令分离协议 /
语音输入可选适配 / Not for）+ prompts/ 三件自包含指令文件。全部内容为
重塑后自有表述, 无源项目标识残留。
