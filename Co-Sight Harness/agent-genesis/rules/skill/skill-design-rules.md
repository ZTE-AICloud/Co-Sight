# Skill 设计规则（薄封装）

> **唯一权威**: 粒度 / 拆分 / 操作模式 Q1-Q4 / G1-G2 阈值 = `knowledge/skill/skill-creation-guide.yaml` §1-§2
> 本文件只管**阶段1契约 + 去重 + SF-6 公式**, 不复制 guide.yaml 的判定逻辑
> 适用: Skill Foundry step-s1（create 模式）— skill-planner + skill-builder 共享
> 加载者: skill-planner（阶段1）, skill-builder（阶段4）
> 防止 guide.yaml → rules/skill → agents/prompt 的三重拷贝（v3 §6.5 反模式）

---

## 阶段1 产出契约（planner 必填）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| mode | string | ✓ | 固定 `"create"` |
| skill_name | kebab-case | ✓ | 目标 Skill 名（kebab-case, 与目录名一致） |
| operation_mode | enum | ✓ | iterates_and_judges \| fetch_filter_rank \| transform \| record_report（**权威: guide.yaml Q1**） |
| knowledge_assets | object | ✓ | references / scripts / templates 三个数组, 每项含 path + role + 必要性论证 |
| granularity_decision | object | ✓ | {verdict: split\|single, evidence: guide.yaml G1/G2 条目, rationale: ≥40字} |
| dedup_check | object | ✓ | {candidates: [{name, similarity}], verdict: pass\|warn\|block} |
| frontmatter_draft | object | ✓ | {name, description, version} — description 必须含 SF-6 四要素（做什么+何时+输入+输出） |
| acceptance_criteria | array | ✓ | ≥3 条, Given/When/Then 格式, 用于 Step 6 product-tester 黑盒测试设计 |
| open_questions | array | – | 任何决策点无证据时记入, 不阻塞, 标 `status: pending` |
| confidence | enum | ✓ | high \| medium \| low |

## 去重检查（planner 必做）

1. Glob `skills/*/SKILL.md`（含本项目 skill-foundry/harness-create 等）
2. 解析每个 SKILL.md frontmatter.description
3. 字符串相似度（jaccard on words）≥ 80% → 警告, 60-80% → 提示, <60% → 通过
4. 结果写入 `dedup_check` 字段, 与阶段1产出同文件落盘

## SF-6 描述公式（builder 必遵）

`description` 必须包含四要素, 缺一 FAIL（builder Step 4 阶段1 阶段4 自检）:
- 做什么（一句话主语谓语宾语）
- 何时触发（"当...时" 或 "请求 X 时"）
- 接收什么输入（输入类型 + 路径/格式）
- 产出什么输出（输出类型 + 路径/格式）

模板: `"<做什么>。<何时触发>。输入为 <X>，输出为 <Y>。"`

## 阶段4 必做（builder 消费）

1. Read `work_root/phase1-skill-design.md`
2. 按 operation_mode / knowledge_assets / granularity_decision 落盘
3. 按 frontmatter_draft 写 SKILL.md frontmatter
4. 按 acceptance_criteria 落 e2e 测试种子到 `output_root/tests/acceptance.md`（非 Step 6 接管前的前置, 防断链）
5. 增量修改模式（optimize）: 读 diagnosis-report → 按推荐模式落修改 + 三段式 Diff

## 粒度裁决（planner 唯一职责）

**必须 Read** `knowledge/skill/skill-creation-guide.yaml` §2 G1-G2, 不得凭经验判定。
G2 阈值 400 行（公式 N×80~150+40, N=输入参数典型数）由 guide.yaml 维护, 本文件不拷贝数值。
