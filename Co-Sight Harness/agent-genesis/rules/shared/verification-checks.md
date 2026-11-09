# AgentGenesis 静态验证 — 7 项检查方法速查

> 适用范围: Phase 4 验证阶段 — 对 `$AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/`（默认 `../generated-agents/{name}/v1/`）执行静态检查
> 执行流程与轮次控制见 [phases/agent-creation/phase4-verify.md](../phase/agent-creation/phase4-verify.md)
> 规则来源: AgentGenesis 建设方案 3.5 节

---

## 目标产物结构

```
$AGENT_OUTPUT_ROOT/{agent-name}/$VERSION/
├── CLAUDE.md                 # 8 章完整 Agent Spec
├── .claude/
│   ├── agents/{name}/{name}.md
│   ├── rules/{name}-review-rule.md
│   └── settings.local.json
├── schemas/                  # 如有 Data Flow 声明（DF1）
├── knowledge/                # 如有知识依赖声明（K2/K3/K4）
└── evaluation/
    ├── fixtures/
    └── pass-criteria.md
```

---

## 检查 1: 完整性检查 (Completeness Check)

### 检查方法

**步骤 1.1 — 枚举必须存在的文件**

```bash
AGENT_NAME="<agent-name>"
AGENT_OUTPUT_ROOT="${AGENT_OUTPUT_ROOT:-../generated-agents}"
VERSION="${VERSION:-v1}"
OUTPUT_DIR="${AGENT_OUTPUT_ROOT}/${AGENT_NAME}/${VERSION}"

REQUIRED_FILES=(
  "${OUTPUT_DIR}/CLAUDE.md"
  "${OUTPUT_DIR}/agents/${AGENT_NAME}/${AGENT_NAME}.md"
  "${OUTPUT_DIR}/rules/${AGENT_NAME}-review-rule.md"
  "${OUTPUT_DIR}/evaluation/pass-criteria.md"
)

for f in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "MISSING: $f"
  fi
done
```

**步骤 1.2 — L2/L3 文件完整性**

```bash
# L2 规则文件: 从 CLAUDE.md Rules Index 提取所有 rules/*.md 引用
L2_FILES=$(grep -oP '\rules/[a-zA-Z0-9_-]+\.md' "${OUTPUT_DIR}/CLAUDE.md" | sort -u)
for f in $L2_FILES; do
  if [ ! -f "${OUTPUT_DIR}/$f" ]; then
    echo "MISSING: ${OUTPUT_DIR}/$f"
  fi
done

# L3 Skill 文件: 从 Frontmatter「所需 Skill 依赖」表提取
L3_SKILLS=$(sed -n '/### 所需 Skill 依赖/,/^###/p' "${OUTPUT_DIR}/CLAUDE.md" | \
  grep '^|' | grep -v '^|---' | grep -v '^| Skill' | \
  awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); if($2!="") print $2}')
for skill in $L3_SKILLS; do
  if echo "$skill" | grep -qE '^(Skill|用途|来源|无|—|-)+$'; then continue; fi
  SKILL_PATH="${OUTPUT_DIR}/skills/${skill}/SKILL.md"
  if [ ! -f "$SKILL_PATH" ]; then
    echo "MISSING: $SKILL_PATH"
  fi
done
```

**步骤 1.3 — Knowledge/Schemas 交叉校验**

```bash
# Knowledge 目录: 若声明了 K2/K3/K4 → knowledge/ 非空
if grep -q 'K2\|K3\|K4' "${OUTPUT_DIR}/CLAUDE.md"; then
  KNOWLEDGE_COUNT=$(find "${OUTPUT_DIR}/knowledge" -type f 2>/dev/null | wc -l)
  if [ "$KNOWLEDGE_COUNT" -eq 0 ]; then
    echo "FAIL: Knowledge Contract 声明了来源但 knowledge/ 为空"
  fi
fi

# Schemas 目录: 若声明了 DF1 → schemas/ 含 schema 文件
if grep -q 'DF1\|Schema-Enforced' "${OUTPUT_DIR}/CLAUDE.md"; then
  SCHEMA_COUNT=$(find "${OUTPUT_DIR}/schemas" -name "*.json" -o -name "*.yaml" -o -name "*.schema.*" 2>/dev/null | wc -l)
  if [ "$SCHEMA_COUNT" -eq 0 ]; then
    echo "FAIL: DF1 声明但 schemas/ 无 schema 文件"
  fi
fi
```

### 通过标准

| 项目 | 标准 |
|------|------|
| 核心文件 (4) | CLAUDE.md、agents/{name}/{name}.md、rules/{name}-review-rule.md、evaluation/pass-criteria.md 全部存在 |
| L2 规则文件 | Rules Index 中引用的所有 `rules/*.md` 均实际存在，每个 >= 200 字符 |
| L3 Skill 文件 | Frontmatter 声明的每个 Skill 均有 `skills/{name}/SKILL.md` |
| Knowledge 目录 | 声明 K2/K3/K4 → `knowledge/` 非空 |
| Schemas 目录 | 声明 DF1 → `schemas/` 含至少 1 个 schema 文件 |
| 4层结构 | `rules/` + `knowledge/` + `evaluation/` 均存在且含至少 1 个文件 |

### 修复指导

| 缺失项 | 修复步骤 |
|--------|---------|
| CLAUDE.md 缺失 | 重新执行 Phase 3 全部 12 步装配 |
| agents/{name}/{name}.md 缺失 | 执行 Phase 3 Step 12 构建输出子步骤 |
| rules/{name}-review-rule.md 缺失 | 执行 Phase 3 审查规则生成子步骤 |
| evaluation/pass-criteria.md 缺失 | 执行 Phase 3 Evaluation Contract 推导子步骤 |
| knowledge/ 为空 | 回到 Phase 1 确认知识来源分析；或回到 Phase 3 知识依赖写入子步骤 |
| schemas/ 为空 | 回到 Phase 3 Data Flow 建模子步骤 |

---

## 检查 2: 格式检查 (Format Check)

### 检查方法

**步骤 2.1 — YAML Frontmatter 可解析性**

```bash
python3 -c "
import sys, yaml
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
parts = content.split('---')
if len(parts) >= 3:
    try:
        fm = yaml.safe_load(parts[1])
        print('OK: YAML frontmatter 可解析')
        required = ['agent_name', 'agent_id', 'version', 'description', 'pattern_composition']
        for k in required:
            if k not in fm:
                print(f'MISSING_FIELD: {k}')
    except yaml.YAMLError as e:
        print(f'FAIL: YAML 解析错误: {e}')
else:
    print('FAIL: 无法提取 frontmatter')
"
```

**步骤 2.2 — 章节标题格式 + 残留占位符**

```bash
# 章节数检查
CHAPTER_COUNT=$(grep -c '^## ' "${OUTPUT_DIR}/CLAUDE.md")
echo "章节数: ${CHAPTER_COUNT}"

# 标题格式: 应全部匹配 ## 中文数字、 格式
NONSTANDARD=$(grep '^## ' "${OUTPUT_DIR}/CLAUDE.md" | grep -v '^## [一二三四五六七八九十]、')
if [ -n "$NONSTANDARD" ]; then
  echo "FAIL: 非标准格式章节标题: $NONSTANDARD"
fi

# 残留占位符
PLACEHOLDER_COUNT=$(grep -c '{{.*}}' "${OUTPUT_DIR}/CLAUDE.md")
if [ "$PLACEHOLDER_COUNT" -gt 0 ]; then
  echo "FAIL: ${PLACEHOLDER_COUNT} 个未填充占位符"
  grep -n '{{.*}}' "${OUTPUT_DIR}/CLAUDE.md"
fi

# TODO/TBD/待定
TODO_COUNT=$(grep -ci 'TODO\|TBD\|待定\|FIXME\|XXX' "${OUTPUT_DIR}/CLAUDE.md")
if [ "$TODO_COUNT" -gt 0 ]; then
  echo "WARN: ${TODO_COUNT} 个 TODO/TBD/待定 标记"
fi
```

**步骤 2.3 — 表格对齐检查**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    stripped = line.strip()
    if '---' in stripped and '|' in stripped:
        sep_cols = stripped.count('|') - 1
        if i > 0 and '|' in lines[i-1]:
            header_cols = lines[i-1].strip().count('|') - 1
            if header_cols != sep_cols and sep_cols > 0 and header_cols > 0:
                print(f'FAIL Line {i+1}: 表头 {header_cols} 列 vs 分隔行 {sep_cols} 列')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| YAML Frontmatter | 存在且可解析，含必填字段 |
| 章节标题 | 全部 `## 中文数字、` 格式（一 ~ 八） |
| 表格对齐 | 所有表格分隔行列数与表头一致 |
| 残留占位符 | `{{.*}}` 匹配数 == 0 |
| TODO 标记 | TODO/TBD/待定 匹配数 == 0 (CRITICAL)；FIXME/XXX 最多 2 处 (MEDIUM) |

### 修复指导

| 格式问题 | 修复步骤 |
|---------|---------|
| YAML 解析失败 | 检查缩进一致性、特殊字符转义 |
| 章节标题不一致 | 对照 spec-assembler.yaml assembly_order 修正编号和标题 |
| 表格列数不一致 | 检查 `{{#each}}` 循环内列数一致 |
| 残留占位符 | 回到 Phase 3 模板填充步骤，确保 `source: llm_generate` 变量已填充 |
| TODO/TBD 标记 | 填入实际内容或回到 Phase 1 补充信息 |

---

## 检查 3: 引用检查 (Reference Check)

### 检查方法

**步骤 3.1 — 工具引用校验**

```bash
# 已知 Claude Code 内置工具白名单
echo "=== 工具引用检查 ==="
grep -A 20 '### 所需工具' "${OUTPUT_DIR}/CLAUDE.md" | \
  grep '^|' | grep -v '^|---' | grep -v '^| 工具' | \
  awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}' | \
while read -r tool; do
  if [ -z "$tool" ]; then continue; fi
  case ",Read,Write,Edit,Bash,Grep,Glob,WebFetch,WebSearch,AskUserQuestion,TodoWrite,Task,Skill,NotebookEdit," in
    *",$tool,"*)
      echo "OK: $tool"
      ;;
    *)
      echo "UNKNOWN: $tool"
      ;;
  esac
done
```

**步骤 3.2 — 文件路径引用校验**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
path_candidates = re.findall(r'\`([^\`]+)\`', content)
file_paths = []
for p in path_candidates:
    if ('/' in p or '.' in p) and ' ' not in p and not p.startswith('http'):
        if not p.startswith('{{') and not re.match(r'^[A-Z]+[0-9]+$', p):
            file_paths.append(p)
if file_paths:
    print(f'共 {len(file_paths)} 个疑似文件路径引用')
    for fp in file_paths[:30]:
        print(f'  - {fp}')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| 工具引用 | 「所需工具」表中所有工具名均在已知列表中，未知 == 0 |
| Skill 引用 | 「所需 Skill 依赖」表中每个 Skill 可追溯到定义文件 |
| 文件路径 | I/O Contract 和 Data Flow 中引用的路径在实体表中有声明 |
| 知识来源路径 | Knowledge Contract 中路径格式合法 |

### 修复指导

| 引用问题 | 修复步骤 |
|---------|---------|
| 未知工具名 | 替换为已知等效工具，或标注「需用户提供」 |
| 未知 Skill 名 | 确认来自合法 Skill catalog；自定义 Skill 添加到 skills/ |
| 文件路径不可追溯 | 在 Data Flow 实体表中添加对应实体 |
| 知识来源路径非法 | 修正为相对路径，含文件扩展名 |

---

## 检查 4: Schema 合法性检查 (Schema Validity)

### 检查方法

**步骤 4.1 — JSON/YAML Schema 语法验证**

```bash
echo "=== Schema 语法检查 ==="
for schema_file in "${OUTPUT_DIR}/schemas"/*.json "${OUTPUT_DIR}/schemas"/*.yaml; do
  if [ ! -f "$schema_file" ]; then continue; fi
  if [[ "$schema_file" == *.json ]]; then
    python3 -c "
import json
try:
    with open('$schema_file') as f:
        schema = json.load(f)
    if 'type' in schema or 'properties' in schema:
        print(f'OK: $schema_file')
    else:
        print(f'WARN: $schema_file 非标准 JSON Schema 结构')
except json.JSONDecodeError as e:
    print(f'FAIL: $schema_file JSON 解析失败: {e}')
"
  elif [[ "$schema_file" == *.yaml || "$schema_file" == *.yml ]]; then
    python3 -c "
import yaml
try:
    with open('$schema_file') as f:
        schema = yaml.safe_load(f)
    if schema:
        print(f'OK: $schema_file')
    else:
        print(f'FAIL: $schema_file YAML 为空')
except yaml.YAMLError as e:
    print(f'FAIL: $schema_file YAML 解析失败: {e}')
"
  fi
done
```

**步骤 4.2 — 实体与 Schema 交叉校验**

```bash
python3 -c "
import re, json, os, yaml
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
# 提取数据实体表实体名
entity_pattern = re.findall(r'^\|\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\|', content, re.MULTILINE)
entities = [e for e in entity_pattern if e not in ('实体名称','---','') and not re.search(r'[\\u4e00-\\u9fff]', e)]
print(f'Data Flow 声明的实体: {entities}')
schema_dir = '${OUTPUT_DIR}/schemas'
if os.path.isdir(schema_dir):
    for fname in os.listdir(schema_dir):
        if fname.endswith('.json') or fname.endswith('.yaml'):
            fpath = os.path.join(schema_dir, fname)
            try:
                if fname.endswith('.json'):
                    with open(fpath) as sf: schema = json.load(sf)
                else:
                    with open(fpath) as sf: schema = yaml.safe_load(sf)
                if 'properties' in schema:
                    print(f'  {fname} 定义属性: {list(schema[\"properties\"].keys())}')
                if 'required' in schema:
                    print(f'  {fname} required: {schema[\"required\"]}')
            except Exception as e:
                print(f'  FAIL: {fname} 解析失败: {e}')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| JSON Schema 语法 | schemas/ 下所有 `.json` 可被 `json.load()` 解析；`.yaml` 可被 `yaml.safe_load()` 解析 |
| 实体-Schema 对应 | 实体的 required 字段均在 Data Flow 实体表中有体现 |
| Schema 引用一致性 | `$ref` 引用指向合法路径 |

### 修复指导

| Schema 问题 | 修复步骤 |
|-------------|---------|
| JSON 解析失败 | 检查引号配对、逗号、无尾部逗号 |
| 实体字段与 Schema 不匹配 | 以 schema 为准修正实体表，或修正 schema properties |
| required 字段缺失 | 在 Data Flow 实体表中补充 |
| $ref 不可达 | 修正为相对路径或确认目标文件存在 |

---

## 检查 5: 流转闭合检查 (Flow Closure Check)

### 检查方法

**步骤 5.1 — 提取实体表并构建生产者/消费者图**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
df_section = re.search(r'### 数据实体表\n\n((?:\|.+\|\n)+)', content)
if not df_section:
    print('FAIL: 未找到数据实体表')
    exit(1)
lines = df_section.group(1).strip().split('\n')
entities = []
for line in lines[2:]:
    cells = [c.strip() for c in line.split('|') if c.strip()]
    if len(cells) >= 4:
        entities.append({'name': cells[0], 'producer': cells[2], 'consumer': cells[3]})
print(f'共 {len(entities)} 个数据实体')
for e in entities:
    print(f'  {e[\"name\"]}: producer={e[\"producer\"]}, consumer={e[\"consumer\"]}')
"
```

**步骤 5.2 — 悬空实体检测**

```bash
python3 -c "
# ... 同上解析逻辑 ...
dangling = []
for e in entities:
    producer, consumer = e['producer'], e['consumer']
    if producer in ('None','','无'):
        dangling.append(f'{e[\"name\"]}: 无生产者')
    elif consumer in ('None','','无') and e.get('type','') not in ('流转(最终)','最终输出'):
        dangling.append(f'{e[\"name\"]}: 非最终输出无消费者')
if dangling:
    print(f'FAIL: {len(dangling)} 个悬空实体')
    for d in dangling: print(f'  - {d}')
else:
    print('OK: 无悬空实体')
"
```

**步骤 5.3 — 数据流转图与实体表一致性**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
# 实体表名集合
df_section = re.search(r'### 数据实体表\n\n((?:\|.+\|\n)+)', content)
table_names = set()
if df_section:
    for line in df_section.group(1).split('\n')[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if cells: table_names.add(cells[0])
# 流程图中引用的标识符
flow_section = re.search(r'### 数据流转图\n\n(.*?)(?=\n###|\n---|\Z)', content, re.DOTALL)
if flow_section:
    flow_text = flow_section.group(1)
    flow_refs = set(re.findall(r'\[([a-zA-Z_][a-zA-Z0-9_]*)\]', flow_text))
    missing_in_flow = table_names - flow_refs
    missing_in_table = flow_refs - table_names
    if missing_in_flow:
        print(f'WARN: 实体表有但流程图未引用: {missing_in_flow}')
    if missing_in_table:
        print(f'FAIL: 流程图引用但实体表未声明: {missing_in_table}')
    if not missing_in_flow and not missing_in_table:
        print('OK: 实体表与流程图一致')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| 悬空实体 | 0 个（非最终输出都有 producer 和 consumer） |
| 生产者合法性 | 所有 producer 指向已声明的 Phase/Step 或"外部输入" |
| 消费者合法性 | 所有非最终输出的 consumer 指向已声明的 Phase/Step 或"用户" |
| 步骤依赖闭合 | Execution Workflow 所有 Step 输入可追溯到前置输出或外部输入 |
| 流程图一致 | 数据流转图中引用的命名实体均在实体表中有声明 |

### 修复指导

| 闭合问题 | 修复步骤 |
|---------|---------|
| 悬空实体 (无 producer) | 指定生产者，或标记为"外部输入"并在 I/O Contract 添加声明 |
| 悬空实体 (无 consumer) | 指定消费者，或改类型为"流转(最终)" |
| 步骤输入无来源 | 添加前置步骤产出该依赖，或加入 I/O Contract 输入清单 |
| 流程图与实体表不一致 | 以实体表为准修正流程图；或以流程图为参照补全实体表 |

---

## 检查 6: 约束自洽检查 (Constraint Self-Consistency)

### 检查方法

**步骤 6.1 — CD3 知识边界与 K2/K3/K4 交叉校验**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()

# 提取 CD3 知识边界表
cd3_section = re.search(r'### 知识边界.*?\n\n((?:\|.+\|\n)+)', content)
boundary_domains = []
if cd3_section:
    for line in cd3_section.group(1).split('\n')[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if len(cells) >= 4:
            boundary_domains.append({'domain': cells[0], 'trust': cells[1], 'source': cells[2]})

# 提取 K 来源
k_section = re.search(r'### 知识依赖总览\n\n((?:\|.+\|\n)+)', content)
k_sources = set()
if k_section:
    for line in k_section.group(1).split('\n')[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if cells: k_sources.add(cells[0])

violations = []
for d in boundary_domains:
    if d['trust'] in ('权威', 'authoritative'):
        if d['source'] not in k_sources and not any(k in d['source'] for k in k_sources):
            violations.append(f'CD3「{d[\"domain\"]}」标记权威但无对应 K 来源')
    if d['trust'] in ('禁止', 'forbidden'):
        if d.get('source','') in k_sources:
            violations.append(f'CD3「{d[\"domain\"]}」标记禁止但 Knowledge Contract 声明了来源')

if violations:
    print(f'FAIL: {len(violations)} 个 CD3-K 不一致')
    for v in violations: print(f'  - {v}')
else:
    print('OK: CD3 与 Knowledge Contract 一致')
"
```

**步骤 6.2 — Safety Constraints 与 Role & Boundaries 一致性**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()

# 提取 Safety 禁止操作和 Role 不越权声明
forbidden_section = re.search(r'### 禁止操作清单\n\n((?:\|.+\|\n)+)', content)
safety_forbidden = set()
if forbidden_section:
    for line in forbidden_section.group(1).split('\n')[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if cells: safety_forbidden.add(cells[0])

nolist_section = re.search(r'### 不越权声明\n\n((?:[-*] .+\n)+)', content)
role_nolist = set()
if nolist_section:
    for line in nolist_section.group(1).split('\n'):
        line = line.strip().lstrip('-*').strip()
        if line and line.startswith('禁止'): role_nolist.add(line)

# 关键词重叠检查 (语义一致性近似)
fk = set()
for f in safety_forbidden: fk.update(re.findall(r'[\\u4e00-\\u9fff]+', f))
rk = set()
for r in role_nolist: rk.update(re.findall(r'[\\u4e00-\\u9fff]+', r))
overlap = fk & rk
if len(overlap) < max(len(fk), len(rk)) * 0.3:
    print('WARN: Safety 与 Role 关键词重叠度低，建议人工审查')
else:
    print('OK: Safety 与 Role 语义一致 (关键词重叠)')
"
```

**步骤 6.3 — 工具声明与 Safety Constraints 冲突检测**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
tools_section = re.search(r'### 所需工具\n\n((?:\|.+\|\n)+)', content)
declared_tools = set()
if tools_section:
    for line in tools_section.group(1).split('\n')[2:]:
        cells = [c.strip() for c in line.split('|') if c.strip()]
        if cells: declared_tools.add(cells[0])

safety_rules = re.findall(r'\| S-\d+ \| ([^|]+) \|', content)
if 'Bash' in declared_tools:
    bash_constraints = [r for r in safety_rules if '命令' in r or 'bash' in r.lower() or '执行' in r]
    if not bash_constraints:
        print('WARN: 声明 Bash 但 Safety Constraints 无对应执行约束')
if 'Write' in declared_tools or 'Edit' in declared_tools:
    write_constraints = [r for r in safety_rules if '修改' in r or '删除' in r or '覆盖' in r]
    if write_constraints:
        print('OK: Write/Edit 有 Safety 约束限制范围')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| CD3-K 一致性 | CD3「权威」领域均有对应 K 来源；「禁止」领域无 K 来源 |
| Safety-Role 一致性 | 禁止操作清单与不越权声明无矛盾 |
| Tool-Safety 冲突 | 声明工具不在 Safety 中被绝对禁止（条件限制可通过） |
| K4 引用完整性 | 声明 K4 → `rules/` 至少 1 个 .md 文件 |
| Hard 约束完备性 | 每个 Hard 约束在 Execution Workflow 或 Evaluation 中有 enforcement |

### 修复指导

| 约束问题 | 修复步骤 |
|---------|---------|
| CD3 权威领域无 K 来源 | 添加 K 来源声明，或降信任级别为「参考」/「受限」 |
| Safety 与 Role 矛盾 | 统一措辞：Safety 侧重执行层禁止，Role 侧重职责边界 |
| 工具被绝对禁止 | 改为有条件限制（限制路径范围），或移除工具 |
| K4 缺少文件引用 | 生成 Agent 专属审查规则文件 |
| Hard 约束无 enforcement | 在 Execution Workflow 或 Evaluation 中添加校验步骤 |

---

## 检查 7: 加载策略一致性检查 (Loading Strategy Consistency)

### 检查方法

**步骤 7.1 — L2 决策与 rules/ 文件存在性**

```bash
python3 -c "
import re, os
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
l2_refs = re.findall(r'\rules/([a-zA-Z0-9_-]+\.md)', content)
print(f'CLAUDE.md 中 L2 规则引用: {len(l2_refs)} 个')
for ref in l2_refs:
    filepath = f'${OUTPUT_DIR}/rules/{ref}'
    if os.path.isfile(filepath):
        print(f'  OK: rules/{ref}')
    else:
        print(f'  FAIL: rules/{ref} 文件不存在')
"
```

**步骤 7.2 — L3 决策与 Skill 声明交叉验证**

```bash
python3 -c "
import re
with open('${OUTPUT_DIR}/CLAUDE.md') as f:
    content = f.read()
skill_section = re.search(r'### 所需 Skill 依赖\n\n((?:\|.+\|\n)+)', content)
if skill_section:
    lines = skill_section.group(1).strip().split('\n')
    skill_count = len([l for l in lines[2:] if '|' in l])
    if skill_count > 0:
        it1_count = len(re.findall(r'IT1.*Enforced|Enforced.*IT1|强制.*Skill|必须通过.*Skill', content))
        if it1_count == 0:
            print('WARN: 声明 Skill 依赖但无 IT1-Enforced 约束')
        else:
            print(f'OK: {it1_count} 处 IT1-Enforced 约束')
"
```

**步骤 7.3 — L2 规则文件内容质量**

```bash
python3 -c "
import os, re, glob
rules_dir = os.path.join('${OUTPUT_DIR}', '.claude', 'rules')
if not os.path.isdir(rules_dir):
    exit(0)
for rf in glob.glob(os.path.join(rules_dir, '*.md')):
    fname = os.path.basename(rf)
    with open(rf) as f: content = f.read()
    chars = len(content)
    issues = []
    if not re.search(r'## .*[规R]则|## .*Rules', content):
        issues.append('缺少规则列表章节')
    if not re.search(r'## .*[Cc]hecklist|## .*检查清单|^\- \[ \]', content, re.MULTILINE):
        issues.append('缺少检查清单')
    if not re.search(r'## .*通过标准|## .*Pass Criteria', content):
        issues.append('缺少通过标准')
    if chars < 200:
        issues.append(f'内容不足 ({chars} < 200)')
    if 'CLAUDE.md' not in content:
        issues.append('缺少指向CLAUDE.md的交叉引用')
    if issues:
        print(f'WARN: {fname}: {issues}')
    else:
        print(f'OK: {fname} ({chars}字符, 结构完整)')
"
```

**步骤 7.4 — L3 SKILL.md 内容质量**

```bash
python3 -c "
import os, re
skills_dir = os.path.join('${OUTPUT_DIR}', 'skills')
if not os.path.isdir(skills_dir):
    exit(0)
for sd in [d for d in os.listdir(skills_dir) if os.path.isdir(os.path.join(skills_dir, d))]:
    skill_file = os.path.join(skills_dir, sd, 'SKILL.md')
    if not os.path.isfile(skill_file):
        print(f'MISSING: skills/{sd}/SKILL.md')
        continue
    with open(skill_file) as f: content = f.read()
    chars = len(content)
    issues = []
    if not content.startswith('---'): issues.append('缺少YAML frontmatter')
    if not re.search(r'^name:\s*\S+', content, re.MULTILINE): issues.append('缺少name字段')
    if not re.search(r'^description:\s*\S+', content, re.MULTILINE): issues.append('缺少description字段')
    if not re.search(r'When to Activate|When to Use|激活条件|使用场景', content):
        issues.append('缺少When to Activate章节')
    if not re.search(r'Execution Steps|执行步骤|## .*[Ss]tep', content):
        issues.append('缺少执行步骤章节')
    if not re.search(r'^\- \[ \]', content, re.MULTILINE) and not re.search(r'## .*[Cc]hecklist|## .*检查清单', content):
        issues.append('缺少检查清单')
    if chars < 500: issues.append(f'内容不足 ({chars} < 500)')
    if issues:
        print(f'WARN: skills/{sd}/SKILL.md: {issues}')
    else:
        print(f'OK: skills/{sd}/SKILL.md ({chars}字符, ECC格式完整)')
"
```

### 通过标准

| 项目 | 标准 |
|------|------|
| L2 文件存在性 | CLAUDE.md 中所有 `rules/*.md` 引用指向的文件均实际存在 |
| L2 决策全覆盖 | architectural_intent 中 L2 模块数 == `rules/` 下 .md 文件数 |
| L3 Skill 声明 | architectural_intent 中 L3 模块在 Frontmatter 中有对应声明 |
| L3 IT1 约束 | 每个 L3 Skill 有对应的 IT1-Enforced 约束 |
| L1 完整性 | CLAUDE.md 各章节含充分实质性内容，非仅引用链接 |
| L2 内容质量 | 每个 L2 规则文件含规则列表 + 检查清单 + 通过标准 + CLAUDE.md 交叉引用，>= 200 字符 |
| L3 内容质量 | 每个 SKILL.md 含 YAML frontmatter + When to Activate + 执行步骤 + Checklist，>= 500 字符 |

### 修复指导

| 加载策略问题 | 修复步骤 |
|-------------|---------|
| L2 rules/ 文件缺失 | 回到 Phase 3 Step 12，填充 L2-*.template.md → 写入 rules/ |
| L3 Skill 声明缺失 | 填充 L3-skill-SKILL.template.md → 写入 skills/{name}/SKILL.md |
| L3 缺少 IT1 约束 | 在 CLAUDE.md 添加 IT1-Enforced 约束文本 |
| L3 缺少禁止操作 | 在 Safety Constraints 添加对应条目 |
| L1 内容空洞 | 回到模板填充步骤，补充实质性内联内容 |
| L2 质量不达标 | 补充缺失章节（规则列表/检查清单/通过标准/交叉引用） |
| L3 质量不达标 | 补充 YAML frontmatter + When to Activate + 执行步骤 + Checklist |

---

## 验证报告格式

### 标准模板

```markdown
# 验证报告

| 字段 | 值 |
|------|-----|
| agent_name | {agent-name} |
| agent_type | 分析型 / 交互型 / Skill调用型 |
| timestamp | {ISO8601-UTC} |
| overall_verdict | PASS / FAIL |
| pass_count | {N}/7 |
| fail_count | {N}/7 |

## 检查结果

| 序号 | 检查名称 | 状态 | 详情 | 修复指导 |
|:----:|---------|:----:|------|---------|
| 1 | 完整性检查 | PASS/FAIL | {描述} | {如失败} |
| 2 | 格式检查 | PASS/FAIL | {描述} | {如失败} |
| 3 | 引用检查 | PASS/FAIL | {描述} | {如失败} |
| 4 | Schema合法性 | PASS/FAIL | {描述} | {如失败} |
| 5 | 流转闭合 | PASS/FAIL | {描述} | {如失败} |
| 6 | 约束自洽 | PASS/FAIL | {描述} | {如失败} |
| 7 | 加载策略一致性 | PASS/FAIL | {描述} | {如失败} |

## 失败详情 (如有)

### {检查名称} — FAIL

- **发现**: {具体发现，含文件名、行号}
- **严重级别**: CRITICAL / HIGH / MEDIUM
- **修复指导**: {具体可执行的修复步骤}
- **修复后验证**: {确认修复的检查方法}

## 签名

| 字段 | 值 |
|------|-----|
| 验证引擎 | AgentGenesis Phase 4 静态验证器 |
| 规则文件 | AgentGenesis-Code/rules/shared/verification-checks.md |
```

---

## 附录: 7 项检查速查表

| 序号 | 检查名称 | 核心方法 | 关键工具 | 阻断级别 |
|:----:|---------|---------|---------|:------:|
| 1 | 完整性 | `find` 枚举文件, CLAUDE.md 声明交叉校验 | bash, grep, wc | CRITICAL |
| 2 | 格式 | 章节标题 grep, YAML 解析, 占位符检测, 表格对齐 | python3 (yaml), grep | CRITICAL |
| 3 | 引用 | 工具/Skill 白名单匹配, 路径提取 | grep, python3 (re) | HIGH |
| 4 | Schema合法性 | JSON/YAML 解析, 实体-Schema 属性比对 | python3 (json, yaml) | CRITICAL |
| 5 | 流转闭合 | 实体表解析, Producer/Consumer 图, 悬空检测 | python3 (re) | CRITICAL |
| 6 | 约束自洽 | CD3-K 交叉, Safety-Role 关键词重叠, K4 存在性 | python3 (re), grep | HIGH |
| 7 | 加载策略一致性 | L2 决策→rules/ 文件, L3 决策→Skill 声明, 内容质量 | bash (find, grep), python3 (re) | HIGH |

---

> 最后更新: 2026-05-03
> 对应 Phase 4 验证阶段
> 上游: phases/agent-creation/phase4-verify.md (执行流程与轮次控制)

---

## Skill 验证 (pipeline_mode == "optimize-skill")

> 当 `pipeline_mode == "optimize-skill"` 时，verifier-agent 执行以下 Skill 适配验证，替代 Agent 的 7 项检查。
>
> **执行面变更（确定性收敛重构 2.1/2.2, 2026-10-14）**: SK-S1/SK-S2 已脚本化为
> G028 `module.skill.static`、SK-S3 由 g005 承担（模式集超集）——verifier LLM
> **采信机检 verdicts 不重跑**（fail-closed 见 agents/skill-verifier.md §Step 1）。
> 下表为行为定义（机检实现以其为准）；SK-S2 口径以 verifier 内联版为基线（用户裁定:
> references/*.md 存在性 + scripts/*.sh `bash -n` + 禁绝对路径）。

### SK-S1: SKILL.md 结构完整性（执行面: G028 module.skill.static）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| SKILL.md 文件存在 | `test -f "{target}/SKILL.md"` | CRITICAL |
| YAML frontmatter 含 name/description/version | grep 三项 | CRITICAL |
| 内容 ≥ 50 行（非空壳） | `wc -l` | HIGH |

### SK-S2: 引用闭合性（执行面: G028 module.skill.static；口径=verifier 内联版）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| SKILL.md 引用的 references/*.md 全部存在 | 逐引用 `test -f` | CRITICAL |
| SKILL.md 引用的 scripts/*.sh 全部存在且语法合法（仅当交付物存在 scripts/ 目录时启用——无则 scripts/ 提及按外部仓库路径处理, 如资产表引用仓库机检脚本; references/ 无此歧义保持无条件） | 逐引用 `test -f` + `bash -n` | CRITICAL |
| 路径为相对路径（无 `/home/` 等绝对路径） | grep 绝对路径模式 | HIGH |

### SK-S3: 无占位符残留（执行面: g005——其模式集为本表超集, 不另实现）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| 无 `TODO` / `TBD` / `FIXME` | grep 三项 | CRITICAL |
| 无 `{{PLACEHOLDER}}` 模板变量 | grep `{{` | CRITICAL |
| 无 `...待补充` / `...待定` | grep | HIGH |

### SK-S4: Logic Consistency 逻辑一致性（内容级验证）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| 步骤间 I/O 闭合：每个步骤的输入有来源 | 逐步骤检查：输入 = 前序步骤输出 或 外部输入 | HIGH |
| 步骤间 I/O 闭合：每个步骤的输出有消费 | 逐步骤检查：输出被后续步骤消费 或 为最终产出 | HIGH |
| 无矛盾指令：SKILL.md 中无互斥声明 | grep 互斥关键词对（"必须"/"不"、"自动"/"等待"），人工审查 | CRITICAL |
| 步骤顺序合理：无先消费后生产的依赖倒置 | 按执行顺序标注依赖图，检查是否有后向依赖 | HIGH |
| 条件分支可判定：分支条件有明确判定标准 | grep "如果"/"if"/"否则"/"else"，检查条件是否有量化标准 | MEDIUM |
| 输入输出支撑：声明的输入足以支撑声明的输出 | 人工审查 I/O 契约 + 知识加载策略 | HIGH |

### SK-S5: Spec 一致性（优化模式）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| 实际变更与 optimization-spec.md 一致 | 对比变更清单与实际文件 diff | HIGH |
| 无清单外的额外修改 | diff 比对 | MEDIUM |

### SK-S6: Delta 可追溯性

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| 每次修改有 Before/After/Reason 记录 | 检查 delta-diff.md | HIGH |

### SK-S8: Design Form 质量（内容级验证）

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| DF-M1: 目录分层 | 有需分层内容时检查对应目录；无则 PASS | HIGH |
| DF-M2: 渐进式加载 | SKILL.md 不内联 >100 行参考文档或代码块 | CRITICAL |
| DF-M3: 描述公式 | description 包含「做什么」+「何时触发」+「输入」+「输出」 | HIGH |
| DF-M4: 脚本独立 | 有确定性操作时检查 scripts/；无则 PASS | HIGH |
| SF-1~SF-8: Anthropic 规范清单 | 逐项对照 skill-diagnosis-rules.md §6.0 | HIGH |

### SK-S9: Global Context 对齐

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| GC-1: Role 一致性 | 比对 Skill 职责与 CLAUDE.md Role & Boundaries | HIGH |
| GC-2: Tool 权限对齐 | 对比 Skill 调用工具与 Agent tools: 白名单 | HIGH |
| GC-3: I/O Contract 对齐 | 检查输入/输出格式是否匹配下游期望 | MEDIUM |
| GC-4: Safety 一致性 | 对比 Skill 安全策略与 Agent Safety Constraints | HIGH |
| GC-5: 文件路径约定 | 检查路径是否符合 Agent work/ 约定 | HIGH |
| GC-6: 状态机同步 | 检查 Skill 状态标记是否兼容 Agent Phase | MEDIUM |
| GC-7: Review 策略对齐 | 确认不自审代替 G1 | HIGH |
| GC-8: 临时文件管理 | 确认有清理策略 | MEDIUM |

### SK-S10: Anthropic 规范合规

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| references/ 加载链闭合 | 如存在 references/，每个文件被 SKILL.md 显式引用 | HIGH |
| scripts/ 脚本独立可运行 | 如存在 scripts/，脚本不依赖 LLM 上下文 | MEDIUM |
| L1/L2/L3 渐进式加载完整 | name+description → 核心指令 → 按需引用 | HIGH |

### SK-S11: 模式应用验证

| 检查项 | 方法 | 严重级别 |
|--------|------|:---:|
| 诊断推荐的模式已应用 | 对比 diagnosis-report 推荐 vs 实际 Skill 内容 | MEDIUM |
| 未应用模式有合理说明 | 标注原因（不适用/超出范围） | LOW |

### 执行流程

```
Phase 4 (optimize-skill):
  1. 执行 SK-S1 结构完整性 → FAIL → 阻断
  2. 执行 SK-S2 引用闭合性 → FAIL → 记录缺失文件列表
  3. 执行 SK-S3 占位符检查 → FAIL → 阻断（禁止含占位符的 Skill 上线）
  4. 执行 SK-S4 Logic Consistency 逻辑一致性 → FAIL → 记录矛盾项，报告
  5. 执行 SK-S5 语法检查 → FAIL → 记录具体错误位置
  6. 执行 SK-S6 Spec 一致性 → FAIL → 报告 Main Agent
  7. 执行 SK-S7 Delta 可追溯性 → FAIL → 自动补录
  8. 执行 SK-S8 Design Form 质量 → FAIL → AUTO_FIX (≤3轮)
  9. 执行 SK-S9 Global Context 对齐 → FAIL → 记录偏离，报告
  10. 执行 SK-S10 Anthropic 规范合规 → FAIL → AUTO_FIX (≤3轮)
  11. 执行 SK-S11 模式应用验证 → FAIL → 标注原因
  AUTO_FIX: 仅限 SK-S1~S5/SK-S8/SK-S10，最多 3 次
  超限 → REPORT_TO_USER
```
