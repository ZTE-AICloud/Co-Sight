---
mode: create
skill_or_agent_name: lineage-context-skill
anchored_mode: DP1-Traceable-Lineage
summary:
  verdict: PASS
  file_counts:
    generated: 2
revision_rounds: 0
---

# self-report（lineage-context-skill 过程锚）

> 外部启发锚（derived: true）——本包按 `knowledge/golden/REFLUX.md` §3 七步
> 流程从外部参照库 zilliztech/claude-context（MIT, 快照 2026-10-17）抽取
> 重塑。源库本体不入池, 入池的是按本仓库规则重塑后的模板资产（R8: 池成员
> 一律本仓库模板资产, provenance 只作溯源注记）。

## 七步留痕（REFLUX.md §3）

1. **选件**: 源库是"整个代码库作为上下文"的语义检索管线, 形状完整
   （切分/嵌入/入库存取/检索组装全链路）, 具备过程锚素材。
2. **旧词汇重映射**: 源库面向"语义代码搜索 MCP 插件"表述 → 重映射为
   本仓库模式词汇 DP1-Traceable-Lineage（数据管线+逐产物 lineage）与
   K3-KB-Backed（向量库支撑检索）; 检索结果五元组
   `{content, relativePath, startLine, endLine, score}` 即 lineage 纪律的
   原生证据。
3. **挂靠核心**: mode_id=DP1-Traceable-Lineage（货架位, R9 非身份声明）,
   anchor_fit=real——每块切分产物强制携带路径+行区间注记、检索结果
   100% 可回溯源码位置, 是"可溯源数据管线"的纯正实现。
4. **重塑改造**: ①源仓 monorepo（core/mcp/vscode/chrome 四包）蒸馏为
   单 SKILL 五段管线; ②凭据契约（源 .env.example 的 OpenAI/VoyageAI/
   Gemini/Ollama + 云向量库端点）重塑为环境变量模板 + 启动校验清单,
   服务商名保留（通用协议级词汇, 非品牌绑定）, 端点/令牌一律占位;
   ③MCP/编辑器外壳剥离, 留纯管线语义; ④身份消毒: 交付物内零源仓名/
   品牌名/真实端点。
5. **补过程锚**: 本 build-plan（invariants 按重塑产物实际字面量书写）+
   本 report; shape 计数如实 generate: 2。
6. **manifest**: 按 schemas/golden-manifest.schema.yaml 全字段,
   anchors.derived=true, provenance 如实（reshaped: true）。
7. **准入**: G028 skill-build 档（见 manifest known_concerns 回填）。

## 交付描述

单 Skill 包（skill 线）: SKILL.md（五段管线 + lineage 纪律 + fail-closed
启动校验 + Merkle 增量同步）+ templates/env.example（用户自备凭据环境
变量契约模板）。
