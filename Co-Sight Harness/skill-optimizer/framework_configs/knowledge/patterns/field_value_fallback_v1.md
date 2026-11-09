# 通用模式:字段值兜底 v1 (field_value_fallback_v1)

> **模式 ID**:`field_value_fallback_v1`
> **创建日期**:2026-07-13
> **来源**:基于 `business_flow_fallback_v1.md`(业务场景示例)的**通用化抽象**。前者绑死"业务流/接口名"业务概念,本模式抽象为"任何 LLM 推理产生的关键字段"的通用兜底。
> **关系**:`business_flow_fallback_v1.md` 是本模式在"组件间流程设计"业务场景的具体示例。Skill 应优先引用本通用模式。
> **适用场景**:任何 LLM 推理产生的关键字段为空/缺失时,使用预定义兜底模板,避免系统崩溃。

---

## 1. 模式定义

**当 LLM 推理产生的关键字段为空或无法确定时,使用预定义兜底模板**:

| 缺失类型 | 兜底模板 | 关联标志字段强制值 |
|---------|---------|----------------|
| 完全缺失(整个字段空) | `"<待补充_{field_name}>"` | `<关联字段>` 强制值 |
| 复合字段局部缺失(已有 prefix) | `"{prefix}.<待补_{part_name}>"` | `<关联字段>` 强制值 |
| 完整兜底(无任何信息) | `"<pending_{field_name}>"` | `<关联字段>` 强制值 |

**核心原则**:
- 兜底值必须含 **"待补充" / "pending" / "待定"** 标识(可配置关键词)
- 兜底后 `<关联标志字段>` 必须 = `<兜底语义值>`(可配置映射)
- 下游校验根据"待补充"标识强制关联字段值

**与具体业务解耦**:
- `field_name` / `part_name` / `prefix` / `关联字段` / `关联值` **全是参数**,由 Skill 传入
- 默认标识关键词:`待补充` / `pending` / `待定`(可覆盖)
- 默认兜底语义映射:`"待补充" → "新增"`(可覆盖)

---

## 2. 参数化

| 参数 | 含义 | 默认值 | 业务示例(组件间流程设计) |
|------|------|--------|----------------------|
| `field_name` | 当前字段名 | 必填 | `biz_if`(业务接口) |
| `value` | 当前字段值 | 必填(可空) | `MCC_SPA.初始上下文建立` |
| `prefix` | 复合字段已确定的前缀 | 可选 | `MCC_SPA` |
| `part_name` | 复合字段缺失部分名 | 可选 | `业务流` |
| `flag_field` | 关联标志字段名 | 必填 | `flow_type` |
| `flag_value` | 关联标志字段值 | `"新增"` | `"新增"` |
| `fallback_keywords` | 兜底标识关键词列表 | `["待补充", "pending", "待定"]` | 同 |
| `complete_template` | 完整兜底模板 | `"<pending_{field_name}>"` | `"<pending_biz_if>"` |
| `partial_template` | 局部兜底模板 | `"{prefix}.<待补_{part_name}>"` | `"MCC_SPA.<待补_业务流>"` |

---

## 3. 通用接口(bash + jq 实现)

```bash
# === 通用模式:field_value_fallback_v1 ===
# 函数: apply_field_fallback value field_name flag_field flag_value [prefix] [part_name]
# 返回: {value, flag_value, is_fallback}

apply_field_fallback() {
  local value="$1"
  local field_name="$2"
  local flag_field="$3"
  local flag_value="$4"
  local prefix="${5:-}"
  local part_name="${6:-}"

  # 已有效:直接返回
  if [[ -n "$value" && "$value" != "null" && "$value" != *待补充* && "$value" != *pending* && "$value" != *待定* ]]; then
    jq -n --arg v "$value" --arg fv "$flag_value" '{value: $v, flag_value: $fv, is_fallback: false}'
    return 0
  fi

  # 复合字段局部缺失(有 prefix)
  if [[ -n "$prefix" && "$value" == *.* ]]; then
    local actual_prefix="${value%.*}"
    local fallback="${actual_prefix}.待补充_${part_name}"
    jq -n --arg v "$fallback" --arg fv "$flag_value" '{value: $v, flag_value: $fv, is_fallback: true}'
    return 0
  fi

  # 完全兜底
  local complete_fallback="<pending_${field_name}>"
  jq -n --arg v "$complete_fallback" --arg fv "$flag_value" '{value: $v, flag_value: $fv, is_fallback: true}'
}
```

---

## 4. 在 Skill 业务中使用(以"组件间流程设计"为例)

```bash
#!/usr/bin/env bash
# step_apply_mods.sh — 应用 mods + 字段值兜底
set -euo pipefail

for_each_mod() {
  local mod="$1"
  local biz_if flow_type
  biz_if=$(echo "$mod" | jq -r '.biz_if // ""')
  flow_type=$(echo "$mod" | jq -r '.flow_type // ""')

  # 触发字段值兜底
  local fallback
  fallback=$(apply_field_fallback "$biz_if" "biz_if" "flow_type" "新增")

  if [[ "$(echo "$fallback" | jq -r .is_fallback)" == "true" ]]; then
    biz_if=$(echo "$fallback" | jq -r .value)
    flow_type=$(echo "$fallback" | jq -r .flag_value)
    mod=$(echo "$mod" | jq --arg v "$biz_if" --arg ft "$flow_type" \
      '.biz_if = $v | .flow_type = $ft')
  fi
  # ... 应用 mod ...
}
```

**关键**:Skill 只传 `field_name=biz_if` / `flag_field=flow_type` / `flag_value=新增`,通用工具处理兜底逻辑。

---

## 5. 通用性验证

其他 Skill 可复用此模式的场景:

- **代码补全**:无法补全的代码 → `// TODO: 待补充`(`field_name=code_block`)
- **分类标签**:无法分类 → `"未分类"`(`field_name=category`,`flag_value=manual_review`)
- **API 响应**:缺失字段 → `{"field": "<pending_field>", "_status": "missing"}`(`flag_value=missing`)
- **测试断言**:无预期结果 → `"<pending_expected_result>"`(`flag_value=tbd`)
- **业务流名**(组件间流程设计):缺失 → `"<pending_biz_if>"`(`flag_value=新增`)

**抽象条件**:任何"LLM 推理产生关键字段"的场景,缺失时使用预定义兜底模板。

---

## 6. 与 topology_validation_v1 联动

兜底值含"待补充"标识,topology C5 校验强制 `flow_type=新增`:

```bash
# C5: 含"待补充"或"pending"或"待定"的行,<flag_field> 必须 = <flag_value>
c5_errors=$(jq -r --arg ff "$flag_field" --arg fv "$flag_value" '
  [.rows[] |
   select((.[$ff] // "") | test("待补充|pending|待定")) |
   select(.[$ff == "flow_type" ? "flow_type" : $ff] // "" != $fv) |
   "C5: 行 " + (.seq|tostring) + " 字段 \($ff) 含兜底标识但 " + $ff + " != " + $fv] | .[]
' "$applied_file")
```

**通用化**:C5 校验也参数化,接受任意 `flag_field` 和 `flag_value`。

---

## 7. 与原 `business_flow_fallback_v1.md` 关系

| 文档 | 角色 | 何时用 |
|------|------|--------|
| **`field_value_fallback_v1.md`(本文件)** | **通用模式** | **新 Skill 优先引用** |
| `business_flow_fallback_v1.md` | 业务场景示例 | 历史示例,可保留为"业务场景如何应用通用模式"的参考 |

**迁移路径**:新 Skill 直接引用本模式;旧 Skill 可保留 `business_flow_fallback_v1.md` 作为具体业务示例,但应**最终统一到本通用模式**。

---

## 8. 验证清单

```bash
# 1. 通用接口存在
grep -q "apply_field_fallback" scripts/step*.sh

# 2. 兜底值标识完整
grep -E "<待补充|pending|待定" references/ scripts/

# 3. flag_value 强制
grep "flag_value.*新增\|flow_type.*=.*新增" references/ scripts/
```

---

## 9. 关联模式

| 模式 | 关系 |
|------|------|
| `three_bucket_split_v1` | 前置:产生需要兜底的 LLM 输出 |
| `topology_validation_v1` | 关联:C5 校验依赖本模式兜底标识 |
| `multi_segment_desc_v1`(原 tri_segment_desc) | 关联:三段式 change_desc 也可应用本模式兜底 |
| `business_flow_fallback_v1`(业务场景示例) | 前身:本模式的业务实例 |

---

## 10. 通用性边界(2026-07-13 增)

### 10.1 模式抽象

**核心抽象**:任何"LLM 推理产生关键字段"的场景,缺失时使用预定义兜底模板,而非让系统崩溃。

`field_name` / `flag_field` / `flag_value` / `fallback_keywords` / `complete_template` / `partial_template` **全部参数化**。

### 10.2 与业务解耦点

| 耦合点 | 解耦方式 |
|--------|---------|
| 例子 `biz_if` / `flow_type` | `field_name` / `flag_field` 是参数,Skill 传入业务字段名 |
| 例子"接口待定" | 兜底模板由 Skill 自定义,只需含"待补充"标识 |
| 默认 `flag_value="新增"` | 参数可覆盖(`flag_value=manual_review` 等) |
| 默认 `fallback_keywords` | 参数可覆盖(`fallback_keywords=["tbd", "TODO"]`) |

### 10.3 适用场景

任何满足以下条件的 Skill:
- LLM 推理产生至少 1 个关键字段
- 字段缺失时,不希望系统直接 fail
- 缺失时需要可识别的"占位符"以便后续处理(人工审核 / 兜底语义)

### 10.4 不适用场景

- 字段值**必填且不能缺失**(业务强校验,缺失必须报错)
- 兜底后**不应**自动走任何流程(应留人工审核空位,但**没有**占位符机制 → 用 `pending` 标志)
- LLM 输出**整体质量差**(本模式只解决"字段缺失",不解决"语义错误")

### 10.5 实施清单

新 Skill 引用本模式时:
- [ ] 定义自己的 `field_name`(要兜底的关键字段)
- [ ] 定义 `flag_field` 和 `flag_value`(兜底后强制值)
- [ ] 自定义 `complete_template` / `partial_template`(可包含业务占位符)
- [ ] 调 `apply_field_fallback` 通用函数
- [ ] 在 topology C5 校验块检查兜底标识 + 关联字段值

---

## 11. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-13 | 初版,基于 `business_flow_fallback_v1` 通用化抽象 |
| v1.1 | 2026-07-13 | 加"通用性边界"段,显式声明不适用场景与解耦点 |
