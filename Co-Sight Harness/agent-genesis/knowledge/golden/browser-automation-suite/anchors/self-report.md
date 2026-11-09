---
mode: create
skill_or_agent_name: browser-automation-suite
anchored_mode: W3-MapReduce
summary:
  verdict: PASS
  file_counts:
    generated: 3
revision_rounds: 0
---

# self-report（browser-automation-suite 过程锚）

> 外部启发锚——本包从外部参照库蒸馏重塑（anchors 标 derived: true）,
> 非本仓库构建产物; 过程按 REFLUX.md 档 1 七步执行。

## 抽取留痕（REFLUX.md §3 七步）

1. **选件**：源库中并行研究类技能（发现→逐目标深研→打分报告+CSV）,
   形态完整、过程锚可补。
2. **旧词汇重映射**：源术语（品牌 CLI 名/品牌 API 名）→ 通用词汇（托管浏览器
   CLI / 搜索 API）; 模式词汇统一为 W3-MapReduce。
3. **挂靠核心**：mode_id=W3-MapReduce（扇出 map + 汇聚 reduce 的纯正结构:
   每目标子代理 = map, compile-report = reduce）。
4. **重塑改造**：SKILL.md 重写为通用模板（流水线/反幻觉/工具约束/失败处理）;
   汇聚脚本按契约重写为零依赖最小实现（禁搬运源实现）; 身份消毒——全包零
   品牌名残留（已 grep 核验）。
5. **补锚**：本 build-plan（3 文件根相对路径 + 字面量 invariants）+ 本 report。
6. **manifest**：derived/reshaped/provenance 如实。
7. **准入**：G028 skill-build 档（见 manifest.known_concerns 回填）。

## 交付描述

蒸馏 skill 包（skill 线）: SKILL.md（并行研究套件模板）+
scripts/compile-report.mjs（汇聚脚本）+ references/research-file-format.md
（单目标文件格式契约）。
