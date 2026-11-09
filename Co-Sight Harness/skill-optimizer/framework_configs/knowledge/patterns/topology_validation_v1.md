# 通用模式:5 项拓扑校验 v1 (topology_validation_v1)

> **模式 ID**:`topology_validation_v1`
> **创建日期**:2026-07-13
> **来源 bug**:`04_skill_dir/组件间流程设计/` step11 只实现 2/5 校验,导致变更组件漏掉、首末行流向错、anchor 超界等问题跑飞
> **适用场景**:任何"插入 N 条消息到时序表"操作后的合法性校验

---

## 1. 模式定义

**5 项强制校验**,任何"在时序表中插入/修改行"的操作后必须跑:

| 编号 | 校验 | 检查内容 | 失败退出码 |
|------|------|---------|-----------|
| **C1** | 变更组件完整性 | 所有声明的变更组件必须出现在 V3 任意行的 src/tgt | 18 |
| **C2** | anchor 范围 | 所有插入行 anchor ∈ [1, len(baseline)] | 19 |
| **C3** | 首末行流向 | 第一行 src 必须是外部触发者,末行 tgt 回流到外部 | 20 |
| **C4** | 重复消息对 | (src, tgt, biz_if) 三元组不重复 ≥2 次 | 15(已有) |
| **C5** | 兜底一致性 | 含"接口待定"或"待补充"的行,`flow_type` 必须 = "新增" | 21 |

**新增退出码**:18/19/20/21(沿用 `output-schema.md` 的 2-17 范围,需追加 18-21)。

---

## 2. 参数化

| 参数 | 含义 |
|------|------|
| `BASELINE_FILE` | 原始 V2 表 |
| `APPLIED_FILE` | 插入/修改后的 V3 表 |
| `CHANGE_FILE` | 变更组件记录 |
| `REPORT_FILE` | 校验错误报告输出 |
| `TRIGGER_COMPONENT` | 触发本流程的子系统名(用于 C3 首末行判断) |

---

## 3. 通用接口(bash + jq 实现)

```bash
# === 通用模式:topology_validation_v1 ===
# 函数: validate_topology baseline applied changes report subsystem
# 退出码: 0 全部通过 / 18/19/20/21/15 对应失败项

validate_topology() {
  local baseline_file="$1"
  local applied_file="$2"
  local changes_file="$3"
  local report_file="$4"
  local subsystem="$5"

  local errors="[]"

  # C1: 变更组件完整性
  local c1_errors
  c1_errors=$(jq -r --slurpfile chg "$changes_file" '
    [$chg[0][] | .component_name as $comp |
     $comp as $full |
     "变更组件 " + $full + " 未出现在 V3 表中"]
    | tostring
  ' "$applied_file" 2>/dev/null | jq -r '.[]' | grep "未出现" || true)
  [[ -n "$c1_errors" ]] && errors=$(echo "$errors" | jq --arg e "$c1_errors" '. + [$e]')

  # C2: anchor 范围
  local c2_errors
  c2_errors=$(jq -r --slurpfile base "$baseline_file" '
    [.[] | select(._is_inserted == true) |
     select(._anchor_row < 0 or ._anchor_row >= ($base[0].rows | length)) |
     "插入行 anchor=" + (._anchor_row|tostring) + " 超出 baseline 范围"]
    | .[]
  ' "$applied_file" 2>/dev/null || true)
  [[ -n "$c2_errors" ]] && errors=$(echo "$errors" | jq --arg e "$c2_errors" '. + [$e]')

  # C3: 首末行流向
  local first_src last_tgt
  first_src=$(jq -r '.rows[0].源子系统.发送组件 // ""' "$applied_file")
  last_tgt=$(jq -r '.rows[-1].目标子系统.接收组件 // ""' "$applied_file")
  if [[ "$first_src" == "${subsystem}."* ]]; then
    errors=$(echo "$errors" | jq '. + ["首行源组件 \(.rows[0].源子系统.发送组件) 属于当前子系统,消息链应从外部子系统进入"]')
  fi
  if [[ "$last_tgt" == "${subsystem}."* ]]; then
    errors=$(echo "$errors" | jq '. + ["末行目标组件 \(.rows[-1].目标子系统.接收组件) 属于当前子系统,消息链应发出到外部子系统"]')
  fi

  # C4: 重复消息对(已有)
  local c4_errors
  c4_errors=$(jq -r '
    [.rows | to_entries | .[] |
     {key: (.value.源子系统.发送组件 + "|" + .value.目标子系统.接收组件 + "|" + .value.业务接口\(业务流))} |
     .key] as $keys |
    $keys | group_by(.) | map(select(length > 1)) | map("重复消息对: " + .[0]) | .[]
  ' "$applied_file" 2>/dev/null || true)
  [[ -n "$c4_errors" ]] && errors=$(echo "$errors" | jq --arg e "$c4_errors" '. + [$e]')

  # C5: 接口待定一致性
  local c5_errors
  c5_errors=$(jq -r '
    [.rows[] |
     select((.业务接口\(业务流) // "") | test("接口待定|待补充")) |
     select((.业务流变更类型 // "") != "新增") |
     "行 " + (.seq|tostring) + ": biz_if 含'接口待定' 但 flow_type=" + .业务流变更类型] | .[]
  ' "$applied_file" 2>/dev/null || true)
  [[ -n "$c5_errors" ]] && errors=$(echo "$errors" | jq --arg e "$c5_errors" '. + [$e]')

  # 写报告
  local passed="true"
  local count
  count=$(echo "$errors" | jq 'length')
  [[ "$count" -gt 0 ]] && passed="false"

  jq -n --arg p "$passed" --argjson e "$errors" \
    '{passed: ($p == "true"), errors: $e}' > "$report_file"

  # 退出码
  if [[ "$passed" == "false" ]]; then
    if echo "$errors" | jq -e '.[0] | test("C1|变更组件.*未出现")' >/dev/null 2>&1; then exit 18; fi
    if echo "$errors" | jq -e '.[0] | test("anchor.*超出")' >/dev/null 2>&1; then exit 19; fi
    if echo "$errors" | jq -e '.[0] | test("首行源组件|末行目标组件")' >/dev/null 2>&1; then exit 20; fi
    if echo "$errors" | jq -e '.[0] | test("重复消息对")' >/dev/null 2>&1; then exit 15; fi
    if echo "$errors" | jq -e '.[0] | test("接口待定")' >/dev/null 2>&1; then exit 21; fi
    exit 22  # 兜底
  fi
  exit 0
}
```

---

## 4. 在 step 脚本中使用

```bash
#!/usr/bin/env bash
# step11_validate.sh — 5 项拓扑校验
set -euo pipefail

# 调用通用工具
bash "${SCRIPT_DIR}/../common/validate_topology.sh" \
  "${WORK_DIR}/05b_baseline.json" \
  "${WORK_DIR}/05b_applied_rows.json" \
  "${WORK_DIR}/01_change_rows.json" \
  "${WORK_DIR}/11_validation.json" \
  "$SUBSYS_NAME"
```

**优势**:
- Skill 不需自己实现 5 项校验
- 5 项校验逻辑统一,新 Skill 立即可用
- 失败退出码标准化,主控 if-else 正确处理

---

## 5. 通用性验证

其他 Skill 可复用此模式的场景:

- **数据库表结构校验**:主键存在 / 外键范围 / 索引覆盖 / 字段非空 / 唯一约束
- **API 请求参数校验**:必填字段 / 字段类型 / 字段长度 / 枚举值 / 唯一性
- **配置文件校验**:必填项 / 路径存在 / 格式合法 / 引用闭环 / 默认值兜底

**抽象条件**:只要是"N 条数据 + N 项约束"的关系,即可套用此 5 项校验框架。

---

## 6. 退出码表更新

各 Skill `references/output-schema.md` 应追加:

```yaml
| 18 | 变更组件完整性失败 | 步骤 11/通用校验 | 进入 revision loop |
| 19 | anchor 范围超界 | 步骤 11/通用校验 | 进入 revision loop |
| 20 | 首末行流向错 | 步骤 11/通用校验 | 进入 revision loop |
| 21 | 接口待定/补充未配 flow_type=新增 | 步骤 11/通用校验 | 进入 revision loop |
| 22 | 校验失败但错误类型不明 | 步骤 11/通用校验 | 兜底报错 |
```

---

## 7. 关联模式

| 模式 | 关系 |
|------|------|
| `three_bucket_split_v1` | 前置:产生 baseline + applied 差异 |
| `mod_application_v1` | 前置:产生 mods,本模式校验 mods 应用结果 |
| `tri_segment_desc_v1` | 关联:C5 校验依赖 LLM 输出描述 |
| `business_flow_fallback_v1` | 关联:C5 校验依赖兜底规则(本通用模式在"组件间流程设计"业务的具体应用) |
| `field_value_fallback_v1` | 通用兜底(优先用此通用模式) |

---

## 8. 通用性边界(2026-07-13 增)

### 8.1 退出码通用化(关键)

**之前**:`validate_topology.sh` 退出码 18/19/20/21 绑死业务(变更组件/anchor/首末行/兜底)。
**现在**:工具退出码仅 **0(通过)/ 1(失败)**;具体失败类型在 JSON `error_code` 字段(取值 `C1`/`C2`/`C3`/`C4`/`C5`)。
**Skill 端映射**:Skill 自己的 `references/output-schema.md` 映射 `error_code` → 业务退出码(18/19/20/21/15)。

例:
```bash
# Skill 的 step11_validate.sh
bash $SCRIPT_DIR/../common/validate_topology.sh \
  $BASELINE $APPLIED $CHANGES $REPORT $SUBSYS
if [[ $? -ne 0 ]]; then
  error_code=$(jq -r .error_code $REPORT)
  case "$error_code" in
    C1) exit 18 ;;  # 业务:变更组件完整性
    C2) exit 19 ;;  # 业务:anchor 范围
    C3) exit 20 ;;  # 业务:首末行流向
    C4) exit 15 ;;  # 业务:重复消息对
    C5) exit 21 ;;  # 业务:兜底一致性
  esac
fi
```

### 8.2 字段名参数化

- 之前:C5 校验写死字段名 `业务接口(业务流)` / `业务流变更类型`
- 现在:`validate_topology.sh` 接受 CLI 参数 `BIZ_IF_FIELD` / `FLOW_TYPE_FIELD` / `FAILBACK_KEYWORDS`
- 默认值兼容旧调用,但新 Skill 可传入业务自己的字段名

### 8.3 适用场景

任何满足以下条件的 Skill:
- 输入: N 条记录组成的时序表(任何字段名)
- 操作: 在表上插入 / 修改 / 删除行
- 输出: 应用后的表 + 校验报告
- 不绑死任何具体业务字段名(BIZ_IF_FIELD/FLOW_TYPE_FIELD 是参数)

### 8.4 不适用场景

- 没有"插入/修改"操作的纯查询任务
- 数据结构非表格(如纯树状/图状)
- 校验规则**不能参数化**(如业务强相关的复杂约束)→ 应在 Skill 自己的 stepN 中实现,不要硬塞到本模式

### 8.5 实施清单

新 Skill 引用本模式时:
- [ ] 准备 baseline / applied / changes 三个 JSON 文件
- [ ] 调用 `validate_topology.sh`(5 个必填参数 + 可选字段名参数)
- [ ] 解析 `$REPORT.error_code` 映射到业务退出码
- [ ] 在 `references/output-schema.md` 中说明 error_code → 退出码映射

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-13 | 初版,基于 04_skill_dir/组件间流程设计/ 校验覆盖度 0/5 |
| v1.1 | 2026-07-13 | 退出码通用化(error_code 字段);字段名参数化;加"通用性边界"段 |
