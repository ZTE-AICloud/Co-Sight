# 业务场景示例:组件间流程设计 字段值兜底(business_flow_fallback_v1)

> **状态(2026-07-13 降级)**:本文件是 `field_value_fallback_v1`(通用模式)在"组件间流程设计"业务的具体应用示例。**新 Skill 优先引用通用模式**。
> **关系**:本文件的具体兜底模板可被通用模式 `apply_field_fallback` 函数直接覆盖,见 §8。

---

## 0. 业务场景定义

本文件只针对"组件间流程设计"业务:
- `field_name` = `biz_if`(业务接口,如 `MCC_SPA.初始上下文建立`)
- `flag_field` = `flow_type`(业务流变更类型:`新增` / `修改` / `继承`)
- `flag_value` = `新增`(兜底时强制)
- 兜底关键词 = `待定` / `待补充` / `接口待定`

**通用场景**(非本业务):参考 `field_value_fallback_v1.md`。

---

## 1. 模式定义(本业务)

**当 LLM 无法确定业务流/接口名时,使用预定义兜底模板**:

| 缺失类型 | 兜底模板 | flow_type 强制值 |
|---------|---------|----------------|
| 业务流名缺失(但接口名可定) | `"{接口名}.接口待定"` | "新增" |
| 接口名也缺失 | `"接口待定.业务流"` | "新增" |
| 完整兜底 | `"接口待定.${src}_${tgt}.消息交互"` | "新增" |

**核心原则**:
- 兜底值必须含"待定"/"待补充"标识(下游 topology C5 据此强制 flow_type=新增)
- 兜底后 `flow_type` 必须 = "新增"(语义自洽:接口待定 = 新增)

---

## 1. 模式定义

**当 LLM 无法确定业务流/接口名时,使用预定义兜底模板**:

| 缺失类型 | 兜底模板 | flow_type 强制值 |
|---------|---------|----------------|
| 业务流名缺失(但接口名可定) | `"{接口名}.接口待定"` | "新增" |
| 接口名也缺失 | `"接口待定.业务流"` | "新增" |
| 完整兜底 | `"接口待定.${src}_${tgt}.消息交互"` | "新增" |

**核心原则**:
- 兜底值必须含"待定"/"待补充"标识(下游 topology 校验 C5 据此强制 flow_type=新增)
- 兜底后 `flow_type` 必须 = "新增"(语义自洽:接口待定 = 新增)

---

## 2. 参数化

| 参数 | 含义 |
|------|------|
| `src` | 源子系统名 |
| `tgt` | 目标子系统名 |
| `interface_name` | 已确定的接口名(可空) |
| `flow_name` | 已确定的业务流名(可空) |

---

## 3. 通用接口(bash + jq 实现)

```bash
# === 通用模式:business_flow_fallback_v1 ===
# 函数: apply_biz_if_fallback biz_if src tgt
# 返回: {biz_if, flow_type}

apply_biz_if_fallback() {
  local biz_if="$1"
  local src="$2"
  local tgt="$3"

  # 已有效:直接返回
  if [[ -n "$biz_if" && "$biz_if" != "null" && "$biz_if" != *待定* && "$biz_if" != *待补充* ]]; then
    echo "{\"biz_if\":\"$biz_if\",\"flow_type\":\"修改\"}"
    return 0
  fi

  # 业务流缺失(接口名有)
  if [[ -n "$biz_if" && "$biz_if" == *.* ]]; then
    local iface="${biz_if%.*}"
    echo "{\"biz_if\":\"${iface}.接口待定\",\"flow_type\":\"新增\"}"
    return 0
  fi

  # 完整兜底
  echo "{\"biz_if\":\"接口待定.${src}_${tgt}.消息交互\",\"flow_type\":\"新增\"}"
}
```

---

## 4. 在 step_apply_mods.sh 中使用

```bash
#!/usr/bin/env bash
# step_apply_mods.sh — 应用 mods 到基线表 + 兜底
set -euo pipefail

# ... 合并 mods ...

# 对每个 mod 应用兜底
for_each_mod() {
  local mod="$1"
  local biz_if flow_type
  biz_if=$(echo "$mod" | jq -r '.biz_if // ""')
  flow_type=$(echo "$mod" | jq -r '.flow_type // ""')

  # 触发兜底
  local fallback
  fallback=$(apply_biz_if_fallback "$biz_if" "$(echo "$mod" | jq -r .src)" "$(echo "$mod" | jq -r .tgt)")

  if [[ "$flow_type" != "新增" ]] && [[ "$biz_if" == *待定* || "$biz_if" == *待补充* || -z "$biz_if" ]]; then
    # 强制 flow_type = 新增
    mod=$(echo "$mod" | jq --arg ft "新增" '.flow_type = $ft')
  fi

  # 应用到基线表
  # ...
}
```

---

## 5. topology 校验联动(C5)

兜底后,topology validation C5 必须强制检查:

```bash
# C5: 含"接口待定"或"待补充"的行,flow_type 必须 = "新增"
c5_errors=$(jq -r '
  [.rows[] |
   select((.业务接口\(业务流) // "") | test("接口待定|待补充")) |
   select((.业务流变更类型 // "") != "新增") |
   "行 " + (.seq|tostring) + ": biz_if 含'接口待定' 但 flow_type=" + .业务流变更类型] | .[]
' "$applied_file")
```

兜底 + C5 校验形成闭环:兜底值标识"待定",C5 强制后续处理方式为"新增"。

---

## 6. 通用性验证

其他 Skill 可复用此模式的场景:

- **代码补全**:无法补全的代码 → `// TODO: 待人工补全`
- **分类标签**:无法分类 → `"未分类"`
- **API 响应**:缺失字段 → `{"field": null, "_status": "missing"}`
- **测试断言**:无预期结果 → `"待确认"`

**抽象条件**:任何"LLM 推理产生关键字段"的场景,缺失时应使用预定义兜底模板,而非让系统崩溃。

---

## 7. 关联模式

| 模式 | 关系 |
|------|------|
| `field_value_fallback_v1` | **优先引用**:本文件是该通用模式在"组件间流程设计"业务的具体应用 |
| `three_bucket_split_v1` | 关联:C 桶(未知)走兜底规则 |
| `topology_validation_v1` | 关联:C5 校验依赖兜底值标识"待定" |
| `tri_segment_desc_v1` | 关联:change_desc 兜底也用"待补充"标识 |

---

## 8. 迁移到通用模式(2026-07-13 增)

### 8.1 迁移路径

新 Skill 引用本模式时,应**直接调用 `apply_field_fallback` 通用函数**(在 `field_value_fallback_v1.md` 中定义),传业务参数:

```bash
# 旧写法(本文件内):硬编码"业务流/接口名"
if [[ -z "$biz_if" ]]; then
  biz_if="接口待定.${src}_${tgt}.消息交互"
  flow_type="新增"
fi

# 新写法(通用模式):参数化
fallback=$(apply_field_fallback \
  "$biz_if" "biz_if" "flow_type" "新增")
biz_if=$(echo "$fallback" | jq -r .value)
flow_type=$(echo "$fallback" | jq -r .flag_value)
```

### 8.2 业务参数映射

| 通用参数(field_value_fallback_v1) | 本业务对应值 |
|------------------------------------|--------------|
| `field_name` | `biz_if` |
| `flag_field` | `flow_type` |
| `flag_value`(默认 `"新增"`) | `"新增"` |
| `fallback_keywords`(默认 `待定/待补充/pending`) | `待定/接口待定/待补充` |
| `complete_template` | `<pending_biz_if>` |
| `partial_template` | `"{prefix}.待补充_业务流"` |

### 8.3 适用场景(本业务)

- `04_skill_dir/组件间流程设计/` Skill
- 任何需要为消息流生成 `biz_if` + `flow_type` 的流程类 Skill
- 任何对消息/接口类业务流做变更的 Skill

### 8.4 不适用场景

- 不需要 LLM 推理产生字段的任务
- 字段值固定从结构化数据(非 LLM 推理)
- 兜底后**不应**走 `新增` 而应走其他流程(如"待人工审核")

### 8.5 实施清单

新 Skill 在"组件间流程设计"业务中使用本模式:
- [ ] 调用 `apply_field_fallback` 通用函数
- [ ] 业务参数:`field_name=biz_if` / `flag_field=flow_type` / `flag_value=新增`
- [ ] 在 LLM 响应校验块检查兜底值标识(包含"待定"或"待补充")
- [ ] 在 step_apply_mods.sh 中合并兜底值到 baseline

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-13 | 初版,基于 04_skill_dir/组件间流程设计/ 业务流兜底缺失 |
| v1.1 | 2026-07-13 | **降级为业务场景示例**;指向通用模式 `field_value_fallback_v1`;加迁移路径 |
