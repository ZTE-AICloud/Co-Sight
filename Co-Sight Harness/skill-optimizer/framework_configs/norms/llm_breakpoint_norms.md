# LLM 断点契约规范

> 适用于所有 `/skill_create` 工作流生成的 `references/stepN-rules.md`。

## 每个 LLM 断点必须包含

### 1. 响应 JSON Schema(必填,顶部)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": [...],
  "properties": {...}
}
```

### 2. Schema 必填字段(≥3 个)

反例:Schema 只定义 1 个 output 字段(LLM 输出维度不够)。

### 3. 至少 1 个输出示例

反例:Schema 只定义字段类型,没有示例,LLM 输出难以对齐。

## LLM 断点输出维度(从 `knowledge/llm_breakpoint_templates.json` 选取)

| 模板 ID | 用途 | 适用场景 |
|--------|------|---------|
| `insertions` | 插入新行 | 流程类 Skill 的多变更分析(综合类断点**必含**) |
| `row_updates` | 存量行更新 | 流程类 Skill 的存量行字段补充(flow_design 必含) |
| `linkage_changes` | 联动变更 | 流程类 Skill 识别非变更组件的适配(flow_design 必含) |
| `fixes` | 规则匹配结果 | 流程类 Skill 的规则文件匹配(规则匹配场景) |
| `naming_decisions` | 命名决策 | 流程类 Skill 的接口/业务流命名 |

**严禁自创 Schema 字段名**(应从模板库选取或基于模板组合)。

## 多模板组合硬约束(2026-07-13 新增,根治"LLM 响应字段不全")

任意 LLM 断点的 JSON Schema `properties` 字段名**必须在** `knowledge/llm_breakpoint_templates.json` 的模板 ID 集合内,严禁自创。

| 业务模式 | 必含最小模板集合 | 理由 |
|---------|----------------|------|
| `flow_design`(综合 LLM 断点) | `insertions` + `row_updates` + `linkage_changes`(3 类必含) | 流程类需要"插新 + 回填存量 + 识别联动"三类操作 |
| `flow_design`(规则匹配 LLM 断点) | `fixes` 单模板即可 | 仅做组件规则匹配,无需 row/linkage |
| `document_generation` | 自由文本(`content` / `sections[]`) | 文档生成非流程类 |
| `data_extraction` | 自由文本(`entities[]`) | 抽取类非流程类 |
| 其他 | 自由文本 | 不限制 |

**反模式**:
- ❌ flow_design 综合 LLM 断点只声明 `insertions` 单模板 → 缺 `row_updates` 与 `linkage_changes` → revision loop 上 LLM 无法回填存量 + 联动变更
- ❌ 自创字段名如 `messages[]` / `entries[]` 而非 `insertions[]` → 校验脚本无法识别 + 通用模式匹配失败

**校验**: `scripts/commands/skill_create.py check-completeness` 强制比对 JSON Schema `properties` keys ∈ 模板 ID 白名单,违规 FAIL。

## 反例(禁止)

- ❌ LLM 断点只定义 1 个输出维度
- ❌ JSON Schema 中 required 字段过少
- ❌ 未提供输出示例
- ❌ 字段命名随意(未基于模板库)

## 校验

`scripts/commands/skill_create.py` 的 `check-completeness` 子命令会校验:

- 每个 LLM 断点的 JSON Schema 是否含 `$schema` 字段
- Schema `required` 字段数 ≥ 3
- Schema 是否含至少 1 个 example