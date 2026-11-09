# 通用模式:三分流 v1 (three_bucket_split_v1)

> **模式 ID**:`three_bucket_split_v1`
> **创建日期**:2026-07-13
> **来源 bug**:`04_skill_dir/组件间流程设计/` step4 不解析业务流,所有行"一锅煮",导致 11 个 bug 中 #1/#2/#3
> **适用场景**:对 N 条记录,按"已知/待 LLM 推理/未知"三分流处理,Skill 可在 step4 步骤复用

---

## 1. 模式定义

将 N 条记录按"是否能本地确定"分到 3 个桶:

| 桶 | 含义 | 处理方式 |
|----|------|---------|
| **A:已知** | 知识库有充分数据可确定映射 | **纯代码**完成,无 LLM 介入 |
| **B:待 LLM** | 知识库有数据但需语义推理 | 写 LLM 任务,等响应,`exit 100` |
| **C:未知** | 知识库无覆盖(如 本地知识库规则缺失) | 走兜底规则(如默认第一个变更组件) |

**核心优势**:
- A 桶纯代码,确定性最强,不出错
- B 桶只 LLM 介入必要行,降低 LLM 调用成本
- C 桶兜底规则保证系统鲁棒性

---

## 2. 参数化

| 参数 | 含义 | 示例(组件间流程设计场景) |
|------|------|----------------------|
| `BUCKET_KEYS` | 用来判断 A/B/C 的关键字段 | `src_sys`, `tgt_sys`, `biz_if` |
| `CACHE` | 本地知识库缓存(可读) | 本地知识库规则解析后的 `<local_cache_file>.json` |
| `RULES_PARSER` | 解析知识库规则的函数 | `parse_rule_file(path)` 提取 component + judgment_method |
| `FALLBACK_TEMPLATE` | C 桶兜底模板 | `"${src}_${tgt}.接口待定.消息交互"` |
| `BIZ_IF_PARSER` | 解析业务流名称的函数 | `"{src}_{tgt}.<flow_name>"` → `src=MCC, tgt=SPA, flow=初始上下文建立` |

---

## 3. 通用接口(bash + jq 实现)

```bash
# === 通用模式:three_bucket_split_v1 ===
# 函数: bucket_split rows_file cache_file out_file
# 输入: rows_file: [{seq, src_sys, tgt_sys, biz_if, ...}]
#       cache_file: { (src_sys, tgt_sys) → {handler_component, judgment_method, confidence} }
# 输出: out_file: {bucket_a: [...], bucket_b: [...], bucket_c: [...]}

bucket_split() {
  local rows_file="$1"
  local cache_file="$2"
  local out_file="$3"

  jq -s '.[0] as $rows | .[1] as $cache | {
    bucket_a: [
      $rows[] | select(
        (.src_sys + "|" + .tgt_sys) as $k |
        $cache[$k] != null and ($cache[$k].confidence // 1) >= 0.7
      )
    ],
    bucket_b: [
      $rows[] | select(
        ((.src_sys + "|" + .tgt_sys) as $k |
         $cache[$k] != null and ($cache[$k].confidence // 1) < 0.7)
      )
    ],
    bucket_c: [
      $rows[] | select(
        ((.src_sys + "|" + .tgt_sys) as $k |
         $cache[$k] == null)
      )
    ]
  }' "$rows_file" "$cache_file" > "$out_file"
}
```

---

## 4. 在 step 脚本中使用

```bash
#!/usr/bin/env bash
# step${N}_map_handlers.sh — 三分流 + 本地知识库真读 + 写回
set -euo pipefail

IN_ROWS="${WORK_DIR}/03_filtered_rows.json"
CACHE_FILE="${WORK_DIR}/<local_cache_file>.json"
OUT_ROWS="${WORK_DIR}/04_mapped_rows.json"
TASK="${WORK_DIR}/llm_task_A_iface_mapping.json"
RESP="${WORK_DIR}/llm_response_4.json"

# 1. 真读 本地知识库规则(参考通用工具 scripts/common/parse_rules.sh)
bash "${SCRIPT_DIR}/../common/parse_rules.sh" \
  "${SKILL_ROOT}/references/<local_rules_dir>" \
  "$CACHE_FILE"

# 2. 三分流
BUCKETS="${WORK_DIR}/_buckets.json"
bucket_split "$IN_ROWS" "$CACHE_FILE" "$BUCKETS"

# 3. A 桶(已知)直接写回 OUT
# 4. B 桶(待 LLM)写 task → exit 100
# 5. C 桶(未知)走兜底规则

# === LLM 断点哨兵(参考 llm_checkpoint_sentinel_v1.md) ===
B_BUCKET=$(jq '.bucket_b | length' "$BUCKETS")
if [[ "$B_BUCKET" -gt 0 ]]; then
  jq -n --slurpfile buckets "$BUCKETS" --slurpfile cache "$CACHE_FILE" \
    '{task: "iface_mapping", rows_pending: $buckets[0].bucket_b, local_cache: $cache[0], ...}' \
    > "$TASK"
  exit 100    # ← 关键
else
  # 全部 A/C 桶处理完,直接写回
  jq ... > "$OUT_ROWS"
  exit 0
fi
```

---

## 5. 通用性验证

其他 Skill 可复用此模式的场景:

- **文档分类**:已知类别 / 待 LLM 分类 / 未知类别 → 兜底到"未分类"
- **字段映射**:已知 schema / 待 LLM 推断 / 未知字段 → 兜底"待补充"
- **接口协议**:已知协议 / 待 LLM 匹配 / 未知协议 → 兜底"待人工"

**抽象条件**:只要任务可表述为"对 N 条记录,每条需要确定一个值,值可能由本地知识库/语义推理/兜底规则决定",即可套用此模式。

---

## 6. 验证清单

```bash
# 1. 函数存在
grep -q "^bucket_split()" scripts/step${N}_map_handlers.sh

# 2. A 桶行直接落 OUT,无需 LLM
jq '.bucket_a | length' $BUCKETS  # > 0 表示分流成功

# 3. B 桶数 = 0 时不退 100
B=$(jq '.bucket_b | length' $BUCKETS)
[[ "$B" -eq 0 ]] || bash scripts/run.sh  # 应该 exit 100

# 4. C 桶有兜底规则
jq '.bucket_c[0]' $BUCKETS  # 应有兜底字段
```

---

## 7. 关联模式

| 模式 | 关系 |
|------|------|
| `topology_validation_v1` | 后续:5 项校验,确保三分流结果合法 |
| `tri_segment_desc_v1` | 后续:LLM 推理结果用三段式描述 |
| `business_flow_fallback_v1` | 关联:C 桶兜底规则(本通用模式在"组件间流程设计"业务的具体应用) |
| `field_value_fallback_v1` | 通用兜底(优先用此通用模式,业务示例可保留为参考) |
| `mod_application_v1` | 后续:LLM 推理出的 mods 应用到基线表 |

---

## 8. 通用性边界(2026-07-13 增)

### 8.1 适用场景

任何满足以下条件的 Skill 任务:
- 输入: N 条记录,每条需确定一个值(可能由本地知识库/语义推理/兜底规则决定)
- 输出: 三组 — 已知(代码确定) / 待LLM(语义推理) / 未知(兜底规则)
- 不绑死任何具体业务字段名(BUCKET_KEYS 是参数)

### 8.2 不适用场景

- 业务流程**只有 1 步**直接落地(没有"是否需要 LLM"的分流判断)
- 数据源**没有本地知识库**(所有 N 条都需 LLM 推理,本模式退化为普通 LLM 调用)
- 兜底规则**不能表达**(如需保留人工审核空位,应改用 `pending`/`tbd` 等通用占位)

### 8.3 与业务解耦点

| 耦合点 | 解耦方式 |
|--------|---------|
| 例子用"子系统.组件" | `BUCKET_KEYS` 参数化;Skill 传入业务字段名 |
| 例子用"接口待定" | 兜底模板由 Skill 在 `apply_biz_if_fallback` 自定义 |
| 例子用"{src}_{tgt}.<flow_name>" | `BIZ_IF_PARSER` 是参数,Skill 替换业务解析函数 |

### 8.4 实施清单

新 Skill 引用本模式时:
- [ ] 定义自己的 `BUCKET_KEYS`(通常 2-3 个,标识"已知性")
- [ ] 实现 `BIZ_IF_PARSER` 或类似的字段解析函数
- [ ] 配置 `CACHE`(本地知识库解析结果)
- [ ] 准备 `FALLBACK_TEMPLATE`(兜底字符串模板)
- [ ] 跑 `bucket_split` 函数,验证 A/B/C 三桶分布合理

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-13 | 初版,基于 04_skill_dir/组件间流程设计/ 的 bug #1/#2/#3 制定 |
| v1.1 | 2026-07-13 | 加"通用性边界"段,显式声明不适用场景与解耦点 |
