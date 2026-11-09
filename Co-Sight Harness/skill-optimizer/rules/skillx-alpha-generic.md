# skillx-alpha-agents 通用性准则（框架无业务耦合）

**目的**：约束 skillx-alpha-agents 框架层（`scripts/orchestrator.py`、`scripts/scorer/*`、`scripts/optimizer_gateway/*` 等）的通用性，确保它**不与任何具体业务强绑定**。

**触发**：用户 `@skillx-alpha-generic` 或调试时排查"框架是否被业务污染"。

---

## 1. 核心定位

skillx-alpha-agents = **通用 Skill 进化编排器**（Harness）。

```
业务方 eval-cmd（一次性命令） → orchestrator 包裹它做循环迭代
评测 → 提取分数和缺口 → 生成优化提案 → 应用 → 再评测 → 直到达标
```

**关键事实**：

- 业务方可能是 SDD 评测、组件变更分析、iMate Agent、文本用例生成等等 — 这些都是**使用方**，不是 skillx-alpha-agents 本身
- 业务差异通过 `config/user-config.yaml` 业务配置 + `framework_configs/*.yaml` framework 模板 + `agents/*.md` 子 Agent 契约注入
- 业务方更换评测场景时，**应零代码改动**（只换 YAML / 改契约）
- 框架的价值在于可复用，**通用性是核心资产**

---

## 1.5 子 Agent 的能力定位：让 LLM 探索，而非约束它的输出

子 Agent（如 `ExtractionAgent`、`ProposalAgent`、`ApplyAgent`）的核心能力是**自主探索 + 推理**，不是**按模板填 JSON**。调试时必须区分这两种用法：

### 1.5.1 推荐做法：让 LLM 自主挖掘

- **给方向，不给 schema**：契约里写任务方向（"扫描 data_dir 找评测分数"），**不**写"必须输出 `result_score_per_case: {RAN-xxx: score}`"
- **放手用工具**：子 Agent 应该被赋予 `Bash` / `Read` / `Grep` 工具，让它自己 `find`、`cat`、`jq`、读文件结构
- **多轮调用而非一次输出**：复杂提取应分步进行（先 ls 看结构 → 找评分文件 → 读 JSON → 汇总），而不是塞进一次性的 prompt
- **允许 LLM 自创结构**：如果 LLM 输出 `f1_breakdown` / `case_score_map` 等"非标"字段，框架应通过通用模式匹配（`*_per_case` / `*_breakdown` / RAN- 前缀）兼容，而不是逼它改字段名

### 1.5.2 避免做法：试图约束 LLM 输出固定 schema

- ❌ 在 prompt 里反复强调"必须输出字段 X"（LLM 训练数据里同业务 schema 容易幻觉，会**自己补**旧字段）
- ❌ 假设 LLM 一次输出就能稳定给出完整结果
- ❌ 框架强依赖某个 LLM 输出字段名（写死读取逻辑）
- ❌ 反复重试 LLM 直到它"听话"（耗时且不稳）

### 1.5.3 设计原则

| 原则 | 含义 |
|------|------|
| **任务驱动** | 子 Agent 接到的应是"做什么 + 为什么"，不是"输出字段 X、Y、Z" |
| **工具丰富** | 子 Agent 应当有 Bash/Read/Grep/Glob 自由组合，按需探索产物目录 |
| **框架兜底** | 框架用通用扫描器（`_scan_per_case_from_data_dir` 之类）兜底，**不**依赖 LLM 一次输出 |
| **模式匹配** | 读取 LLM 输出时用 `*_per_case` / `*_breakdown` / 通用前缀等模式，**不**写死字段名 |
| **可解释** | 子 Agent 输出应包含"我读了哪些文件、怎么聚合的"，便于框架校验 |

### 1.5.4 实际案例

**问题**：连续多轮让 LLM 一次输出 `result_score_per_case` 字段，LLM 始终不按契约（幻觉旧字段如 `case_count_per_node`）。

**根因**：试图约束 LLM 单次输出固定 JSON schema，违背 LLM 自主探索的本质能力。

**正解**：
1. 子 Agent 契约只说"扫描 data_dir 找分数"，给工具让它自己 ls/grep/jq
2. 框架用通用扫描器（`total_score` / `score` / `f1` 字段通用匹配）兜底填充
3. 模板用 `*_per_case` / `*_breakdown` / RAN- 前缀 通用模式读取
4. 一次 LLM 调用 + 一次框架扫描 = 稳定结果

---

## 2. 硬编码禁令（强制）

框架代码**严禁**出现以下任何与业务相关的字符或模式。

### 2.1 路径类（最常见违例）

- ❌ `phase1` / `phase2` / `phase3` / `phase4`（具体阶段名）
- ❌ `phase1-build` / `phase2-exec` / `phase3-eval` / `phase4-diagnosis`（具体子目录）
- ❌ `RAN-` / `CASE-` / `TC-` / `REQ-` / `TEST-`（具体 case_id 前缀）
- ❌ `iMate` / `SDD` / `RanOss` / `特性域变更分析` 等业务专属名词
- ❌ 业务方约定的具体子目录名（如 `gold/` / `r_result/` / `sub-activity-sets/`）

### 2.2 字段类（LLM 输出 schema）

- ❌ `total_score` / `parent_node_score` / `children[].f1` / `recall.score` / `precision.score`
- ❌ `result_score_per_case` / `result_score_raw` / `result_score_source`（契约字段名）
- ❌ 任何具体业务 schema 的字段路径（如 `data.scores[].metric`）
- ❌ 业务方专用的 JSON key（如 `e2e-sets` / `execution_log`）

### 2.3 数据类

- ❌ 硬编码的 `data_dir` 默认路径
- ❌ 硬编码的 `output_dir` / `workspace` 默认路径
- ❌ 业务方专属的环境变量名（除非有 `SKILLX_` 统一前缀）

### 2.4 关键词与分类字典类（Stage 2 failure_layer 等场景）

- ❌ Python 代码中出现业务分类关键词（如 "phase3-eval 缺失"、"iSpace 权重接口"）
- ❌ 兜底分类逻辑写死阈值字符串 / 错误消息模板
- ✅ 分类关键词集合必须放 YAML（`failure_layer_keywords` 等段），Python 只读不写
- ✅ 兜底匹配顺序、阈值、枚举值放 YAML，Python 走 `cfg.get(...)` 读
- ✅ 业务方更换评测场景时，只改 YAML 一处即可，不需要改 Python

**设计依据**：分类关键词与具体业务评测管道强耦合（如"phase3-eval 缺失"只在 SDD 评测中表示产物缺失），放 Python 代码会污染框架通用性。YAML 配置驱动是统一入口。

---

## 3. 通用化设计原则

### 3.1 模式匹配代替硬编码

需要从 LLM 输出中提取字段时，使用**通用命名模式**（优先级逐级降低）：

| 模式 | 示例 |
|------|------|
| `<metric>_<suffix>` 形式 | `result_score_per_case` / `f1_per_case` / `accuracy_breakdown` |
| `*_per_case` / `*_breakdown` / `*_per_source` | 任意业务指标都可加这些后缀 |
| dict key 以 `RAN-` / `CASE-` / `TC-` / `REQ-` / `TEST-` 开头 | 通用 case_id 前缀 |

框架实现只识别**模式**，不识别**具体业务名**。

### 3.2 通用扫描器兜底

当 LLM 子 Agent 不按契约输出时（事实：LLM 经常不按契约输出），框架应通过**通用扫描器**兜底：

- glob 业务方产物目录 `**/*.json`
- 读每份 JSON，匹配**通用 score 字段**候选集（`total_score` / `score` / `f1` / `aggregate_score` / `value` / `metric`）
  - 优先读顶层；顶层没有则尝试 `children[].<field>` 求均值
- 用**通用 id 字段**（`req_id` / `case_id` / `id` / `name`）或文件名 stem 作为 case_id
- 不写死 `phase3-eval` 路径或 `children[].f1` 字段

> **设计依据**：大部分 Skill 评测产物（不论具体业务）都会落到结构化 JSON，且至少有一个数值型 score 字段。通用扫描器从结构形态出发，不假设业务语义。

### 3.3 业务方配置入口（唯一允许注入业务的地方）

业务差异通过以下两个配置文件 + 一个契约文件注入，**严禁**改代码：

1. **`.env`**（工具级固定配置）
   - 模型、API 认证（`ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY` 等）
   - 统一根目录（`SKILLX_ROOT`）及由其派生的子路径
   - 评测过滤（`SKILLX_CASE_IDS` 等业务无关前缀的过滤列表）
   - **命名规范**：统一使用 `SKILLX_*` 前缀，禁止 `SDD_*` / `IMATE_*` 等业务前缀

2. **`config/user-config.yaml`**（业务方唯一编辑入口）
   - 产物结构声明（`execution_traces.structure`、`score_extraction.structure`）
   - 解析规则声明（`parsing`、`extraction`、`handling`）
   - 所有字段都是自然语言描述，给 LLM 子 Agent 看，Python 端不读取结构化字段
   - **业务方更换评测场景时，只改这个文件**

3. **`agents/<name>.md`**（子 Agent 契约）
   - 子 Agent 系统提示（`ExtractionAgent` / `ProposalAgent` / `ApplyAgent` 等）
   - 契约只写"做什么 + 为什么"，不写"必须输出字段 X、Y、Z"

### 3.4 配置优先，代码不推断（强制）

框架代码**不应**通过路径拼接、目录 glob、文件名模式等方式"推断"业务配置。所有业务相关的路径、前缀、活动名都必须从 `.env` 或 `user-config.yaml` 读取。

**禁止的推断模式**：

| 禁止写法 | 正确做法 |
|---------|---------|
| `workspace.parent.parent / "ran_sdd"` | 从 `.env` 的 `SKILLX_EVAL_DIR` 读取 |
| `workspace.glob("RAN-*")` | 从 `.env` 的 `SKILLX_CASE_IDS` 读取，或从 `user-config.yaml` 读 case_id 前缀模式 |
| `workspace.parent / "r_result"` | 从 `.env` 的 `SKILLX_GOLD_DIR` 读取 |
| `os.environ.get("SDD_EVAL_DIR")` | 统一为 `SKILLX_EVAL_DIR` |
| `return "特性域变更分析"` | 从 `user-config.yaml` 的 activity 字段读取 |
| 函数名含业务名（如 `_find_sdd_eval_dir`） | 改为通用名（如 `_resolve_eval_dir`）或直接删除，让调用方从配置读取 |

**设计原则**：

1. **配置单一来源**：业务路径只在 `.env` 或 `user-config.yaml` 定义一次，框架代码只读取不推断
2. **删除优于兜底**：如果一个函数的所有调用方都能从配置拿到值，直接删除这个推断函数（如 `_find_sdd_eval_dir`）
3. **环境变量统一前缀**：所有业务相关 env 都用 `SKILLX_*` 前缀，旧名（`SDD_EVAL_DIR` 等）在 `.env` 加载时做兼容映射，框架代码不直接读旧名
4. **user-config.yaml 是业务方唯一编辑入口**：框架代码不读取其结构化字段（Python 端不 `yaml.safe_load` 它），只把文件路径传给子 Agent，让 LLM 自主解析自然语言描述

**反例**：

```python
# ❌ 错误：从 workspace 路径推断业务目录
def _find_sdd_eval_dir(workspace: Path) -> Optional[Path]:
    env_dir = os.environ.get("SDD_EVAL_DIR", "")
    if env_dir:
        return Path(env_dir)
    root = os.environ.get("SKILLX_ROOT", "")
    if root:
        p = Path(root) / "ran_sdd"  # 业务目录名硬编码
        if p.exists():
            return p
    inferred = workspace.parent.parent / "ran_sdd"  # 路径推断
    if inferred.exists():
        return inferred
    return None

# ✅ 正确：直接从 .env 读取，不做推断
def _resolve_eval_dir() -> Optional[Path]:
    """从 SKILLX_EVAL_DIR 读取评测产物目录，未配置返回 None"""
    env_dir = os.environ.get("SKILLX_EVAL_DIR", "").strip()
    return Path(env_dir) if env_dir else None
```

### 3.5 重构整合优先于堆叠新增（强制）

**核心原则**：开发或修改代码时，**必须**优先考虑重构、整合、合并现有逻辑，而不是一味"再加一段"、"再开一个分支"、"再添一个 if"。框架的熵增比功能缺失更致命——前者让后续所有改动都更贵，后者只是少一个特性。

#### 3.5.1 常见症状（出现任一立即警觉）

- ❌ 同一个概念在 3 个以上地方用不同方式实现（如"基线分"散落在 `config["baseline_score"]` / `cur["baseline_score"]` / `eng.baseline_score` 三处）
- ❌ 函数超过 3 层 if/elif 分支做"差不多的事"，每个分支只差几个参数
- ❌ 新加的兼容代码前写着"为了兼容旧 X"，但旧 X 实际已无人使用
- ❌ 同一份数据被同时写到 2+ 个文件（双写），其中一份是"以防万一"
- ❌ 函数参数列表越来越长，新增参数只对 1/3 的调用方有意义
- ❌ 写新代码时先 grep 一下"是否已有类似实现"，答案是"有但不太一样"，于是另写一份

#### 3.5.2 决策启发式

| 场景 | 错误做法 | 正确做法 |
|------|---------|---------|
| 旧字段还可能被外部脚本读 | "保留双写过渡"无限期挂着 | 给定截止日期或下一个里程碑必清；过渡期也要在 TODO 里写明 |
| 两种实现都"差不多能用" | 同时保留，加 if 分流 | 选一种彻底替换另一种；老路径在 PR 里同步删 |
| 现有函数再加 2 个参数也能凑合 | 继续堆参数 | 拆成两个职责单一的函数，或用 dataclass 收参数 |
| 新业务场景和老场景有 80% 重合 | 复制粘贴后改 20% | 抽公共函数/模板/配置驱动，差异点用参数注入 |
| 某个分支永远不被命中 | 注释"预留扩展"留着 | 直接删；如果未来需要，从 git history 找回比留死代码便宜 |
| 同一份逻辑在 3 个文件各写一遍 | "每处都改一点更安全" | 抽到单一模块，所有调用方 import；让单点改动生效 |
| 兜底逻辑 + 兜底的兜底 | "再加一层 try/except 更稳" | 找到根因，删掉多层兜底；只在最外层留一道 |

#### 3.5.3 重构触发条件（满足任一即应重构）

1. **同一段代码出现 2 次**：立即抽函数
2. **同一段代码出现 3 次**：必须抽函数 + 审视设计是否有问题
3. **新增需求要改 5+ 文件**：大概率是抽象错了，重构后再加
4. **某个 PR 同时含"加新逻辑"和"保留旧逻辑"**：拆成两个 PR——一个删旧的、一个加新的
5. **看到 `if X: do_old_thing() else: do_new_thing()` 且 do_old_thing 没人测**：删 do_old_thing
6. **函数/文件 >50 行 / >800 行**：先拆，再看是否还合理

#### 3.5.4 实证案例（来自本项目历史）

**问题 1：双写 config.json ↔ task_state.json**
- 症状：分数/状态同时写到 `config["current_score"]` 和 `task_state.current.score`，监控/外部脚本读到的两份数据偶发不一致
- 错误做法：在 orchestrator 里加更多 `if X: write_to_a else: write_to_b` 分流
- 正确做法：把实时分/状态全部迁到 `task_state.json`（单一权威源），config 只保留配置项；in-memory 状态由 `StateEngine` 维护，每次变更只写一处

**问题 2：广度/深度模式重复的候选生成代码**
- 症状：`breadth.py` 和 `single.py` 各有一份"生成候选 → 评测 → 选最优"，只是参数不同
- 错误做法：第三种模式出现时再复制一份
- 正确做法：抽 `ApplyAgent`（`orchestrators/apply_agent.py`）统一处理，所有模式 import 同一份

**问题 3：phase 状态机 9 个粒度过细**
- 症状：`task_state.json` 每轮 9 个 phase 记录，大部分是 `pending` 空记录或纯机械节点（`sandbox_setup`/`sandbox_cleanup` 只记毫秒级时间戳）
- 错误做法：再加 phase 区分更多细节
- 正确做法：砍到 5 个核心节点（baseline_evaluation / candidate_evaluation / gap_analysis / proposal / apply），机械节点不进状态机

#### 3.5.5 验证清单

每次提 PR 自查：

- [ ] 新增代码行数 vs 删除/重构代码行数，新代码应该 ≤ 重构后总行数 1.3 倍（说明有净简化）
- [ ] 新增的概念/字段/函数，未来是否还会用？如果只用一次且能 inline，直接 inline
- [ ] 是否有"双写"或"双源真相"？是否能在本次 PR 收敛到单源？
- [ ] 是否有"为了兼容而保留"的死代码？能删则删，或在 TODO 里写明删除条件
- [ ] 改完一个文件，是否应该顺带清理相邻的同类问题（"路过即打扫"）？

> **设计哲学**：框架代码的价值不取决于"支持多少业务"，而取决于"加新业务要改多少代码"。越简洁、越收敛，框架越长寿。**每一次"加分支"都应该是"删旧代码"的同义词**。

---

## 4. 调试检查清单

发现违例**立即修复**，不要等下次：

```bash
# 1) 路径类违例
grep -rEn "phase[1-4]|phase1-build|phase2-exec|phase3-eval|phase4-diagnosis" scripts/
grep -rEn "RAN-|CASE-[0-9]+|TC-[0-9]+" scripts/ 2>/dev/null | grep -v test_

# 2) 字段类违例
grep -rEn "total_score|parent_node_score|children\[|recall\.score|precision\.score" scripts/ \
  | grep -v "_scan_per_case_from_data_dir\|comments" | head

# 3) 业务专属名词
grep -rEn "iMate|RanOss|特性域变更分析|SDD评测|e2e-sets" scripts/ \
  | grep -v "test_\|comment\|TODO" | head

# 4) 框架臃肿（§3.5）
#    a) 同一字段被多个状态文件双写
grep -rEn 'config\["current_score"\]|config\["best_score"\]|config\["baseline_score"\]|config\["history"\]' scripts/ \
  | grep -v "已弃用\|fallback\|旧任务兼容"
#    b) 单文件 > 800 行（按 800 行原则）
find scripts/ -name "*.py" -exec wc -l {} \; | awk '$1 > 800 {print}'
#    c) 函数 > 50 行（按 50 行原则）
grep -rEn "^def |^    def " scripts/ -A 60 | python3 -c "
import sys, re
current = []
for line in sys.stdin:
    if re.match(r'.*def \w+', line) and not line.startswith(' '):
        if current and len(current) > 50:
            print(f'{current[0].strip()}: {len(current)} 行')
        current = [line]
    elif current and (line.startswith(' ') or line.strip() == ''):
        current.append(line)
    else:
        if current and len(current) > 50:
            print(f'{current[0].strip()}: {len(current)} 行')
        current = []
"
```

| 检查项 | 判定 |
|--------|------|
| 框架代码 grep `phase[1-4]` | 0 命中（注释中可保留，需说明） |
| 框架代码 grep `RAN-` / `CASE-` | 0 命中 |
| 框架代码 grep `total_score` / `children\[` | 0 命中（除通用扫描器内部） |
| 框架代码 grep 业务专属名词 | 0 命中 |
| 业务方只换 YAML + 改 Agent 契约 | 必须能跑（无代码改动） |
| 实时分/状态双写 | 0 命中（已弃用兼容路径除外，需 TODO 标明清理条件） |
| 单文件 > 800 行 | 0 命中 |
| 单函数 > 50 行 | 0 命中（需拆函数） |

---

## 5. 例外（允许保留相关字符）

- **注释中说明历史背景**：如 `# 旧版 SDD 评测的 f1 字段，新业务已不再使用` — 仅文档
- **错误信息中给出业务示例**：如 `# 当 JSON 形如 {"total_score": ...} 时` — 仅文档/日志
- **通用扫描器内部**：`_scan_per_case_from_data_dir` 之类的通用兜底逻辑，**可以**枚举 score 字段候选（这是模式匹配，不是业务耦合）
- **测试用例**：模拟业务输入的 fixture 字段名（mock 数据可以）

任何**参与实际判断的代码路径**都不允许有业务硬编码。

---

## 6. 违反通用性的常见症状

| 症状 | 根因 | 修法 |
|------|------|------|
| 换一个业务要改 N 个 Python 文件 | 框架硬编码了业务路径 / 字段 | 搬到 YAML 适配器 |
| LLM 输出变了框架就崩 / 渲染空白 | 框架过度依赖 LLM 输出 schema | 加通用模式匹配兜底 |
| 新业务接入要重写 `score_analyzer` 的 `_build_*` | 函数耦合了具体业务字段 | 改成 dict key 模式匹配 |
| 调试日志里有 `phase3-eval` 字样 | 框架在硬编码路径 | 改成从配置读 `data_dir` 子结构 |
| 模板里出现 `RAN-` 字段名 | 模板硬编码业务 case_id | 用通用占位符 + 通用扫描结果 |
| 改 orchestrator 后旧业务跑不通 | 改动扩散到非业务代码 | 改动隔离到 `config/` 和 `framework_configs/` |
| **同一份数据双写到 2+ 文件，且两份偶发不一致** | 缺单一权威源 | 收敛到 task_state.json（实时分/状态）或 config.json（配置项） |
| **单文件 > 800 行 / 单函数 > 50 行** | 缺抽象或责任未拆分 | 拆模块 / 抽函数 / 提 dataclass |
| **同一概念在 3+ 地方以 3 种方式实现** | 抽象不足 + 历史兼容残留 | 选 1 种彻底替换其他；老路径在 PR 同步删 |
| **"为了兼容旧 X" 注释出现 3+ 次，X 实际已无人用** | 死代码清理推迟 | 删 X 及其兼容代码；如需找回，git history 更便宜 |
| **新增功能要改 5+ 文件** | 抽象方向错了 | 先重构再加新功能，不要在错的方向上堆 |
| **过 if/elif 链 3+ 层做"差不多的事"** | 缺多态/配置驱动 | 抽公共逻辑 + 差异点参数化 |

---

## 7. 调试步骤（发现疑似违例时）

```
1. 在框架代码里 grep 业务关键字（见 §4 检查清单）
2. 找到违例点：判断是注释/日志/逻辑
3. 逻辑代码里的违例 → 立即标记为 bug → 改造成配置注入或通用模式
4. 注释/日志里的违例 → 评估是否需要清理（不影响功能，但易误导）
5. 写最小复现：换一份 YAML + Agent 契约，确认框架无代码改动也能跑
6. 把"换业务不需改代码"作为持续回归测试项
```

---

## 8. 关联文档

- `COSIGHT.md` — 项目主入口（强调"通用 Harness，不绑定任何具体业务"）
- `rules/skillx-alpha-debug.md` — 调试规范（持续测试-修改循环）
- `config/user-config.yaml` — 业务方唯一配置入口（业务方主入口）
- `framework_configs/pipeline-config.schema.yaml` — 管道配置 schema 约束
- `scripts/scorer/score_analyzer.py` — 主要检查对象（最容易堆积业务代码）
- `scripts/scorer/artifact_scanner.py` — 通用兜底扫描器（应保持极简 + 通用）

**核心准则回顾**：
1. **不与业务耦合**（§2）— 配置/契约驱动，零代码改动换业务
2. **不堆叠**（§3.5）— 重构整合优先于加分支，每加一段必删一段
3. **可读优先**（§3.1-3.4）— 模式匹配、通用扫描、配置优先、代码不推断
