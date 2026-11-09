# Skill 设计指南

> 来源: Anthropic 官方 Skill 规范 + AgentGenesis 实战经验
> 加载者: Main Agent (Plan Mode), builder-agent (Phase 3)
> 用途: 为 Skill 优化方案设计提供设计原则参考，补充 skill-optimization-patterns.md 的机械模式

---

## 1. 核心设计哲学

### 1.1 Skill 是什么

Skill 是 Agent 的**可按需加载的能力模块**。它不是 Agent 本身，而是 Agent 在特定场景下加载的专项指令集。

关键设计约束:
- Skill 是**被调用的**，不是主动执行的 — Agent 根据用户输入匹配 description 后决定加载
- Skill 的指令是**注入到 Agent 上下文**的，不是独立进程
- Skill 的质量取决于**在正确的时间提供正确的信息量** — 太少则能力不足，太多则污染上下文

### 1.2 为什么分层很重要

一个 800 行的 SKILL.md 在每次匹配时全部注入 Agent 上下文，导致:
- 上下文窗口被大量不必要的信息占满
- Agent 在核心指令和参考细节之间"失焦"
- 后续步骤可用上下文空间减少，输出质量衰减

分层设计的目标: **在 Agent 需要时，以最小信息量提供最大决策支持**。

---

## 2. 渐进式加载架构 (L1/L2/L3)

```
L1 — 启动时加载 (name + description)
  ├── 成本: ~100 tokens / Skill
  ├── 所有 Skill 的 name+description 在 Agent 启动时注入
  └── 作用: Agent 判断"这个 Skill 能处理当前请求吗？"

L2 — 匹配时加载 (SKILL.md body)
  ├── 成本: ~2000-5000 tokens (取决于 body 长度)
  ├── 仅在 Agent 判定此 Skill 匹配用户意图时加载
  └── 作用: 提供核心执行指令，含对 L3 资源的引用

L3 — 按需深度加载 (references/ 下的文件)
  ├── 成本: 可变 (取决于具体文件大小)
  ├── 仅在 SKILL.md body 显式引用时才通过 Read 工具加载
  └── 作用: 提供详细参考文档、领域知识、规范说明
```

### 设计启发式

| 问题 | 决策 |
|------|------|
| 这个信息没有它 Agent 就无法执行核心任务吗？ | → L1 (description 暗示) 或 L2 (body 内联) |
| 这个信息在执行特定步骤时需要参考，但不是每步都要？ | → L3 (references/ 引用) |
| 这个信息仅在某些变体场景下需要？ | → L3 (references/ 条件引用) |
| 这个操作需要确定性结果（非 LLM 推理）？ | → L3 (scripts/ 独立脚本) |

---

## 3. 目录结构约定

```
my-skill/
├── SKILL.md          # 必须 — L1 name+description + L2 body
├── references/       # 可选 — L3 详细参考文档
│   ├── guide.md
│   ├── checklist.md
│   └── domain-knowledge.md
├── scripts/          # 可选 — 确定性可执行脚本
│   ├── validate.py
│   └── transform.py
└── templates/        # 可选 — 可复用的输入/输出模板
    ├── input-template.md
    └── output-template.md
```

### 何时需要 references/

- SKILL.md body 超过 300 行 → 提取详细说明到 references/
- 包含领域知识（规范、术语表、规则清单）→ references/
- 包含不同场景的变体指令 → references/
- 包含长篇示例或案例 → references/

### 何时需要 scripts/

- 需要精确比对（文件内容、数据校验）→ scripts/
- 需要格式转换（JSON↔YAML、Markdown 提取）→ scripts/
- 需要数学计算或正则匹配 → scripts/
- 需要调用外部工具或 API → scripts/

> **核心原则**: LLM 擅长推理、生成、判断。脚本擅长精确、重复、可验证。不要把 LLM 当作脚本引擎使用。

### 何时需要 templates/

- 输入格式复杂，需要结构化 → templates/input-template.md
- 输出有固定格式要求 → templates/output-template.md
- 用户每次需要从头构造输入 → 提供模板降低使用门槛

---

## 4. SKILL.md 内容分类指南

### 4.1 应保留在 SKILL.md body 中的内容 (L2)

- 核心执行流程（步骤顺序和关键决策点）
- 角色定义（此 Skill 执行时 Agent 扮演什么角色）
- I/O 契约（接收什么输入、产出什么输出、输出到哪里）
- 对 L3 资源的**引用**（"详见 references/xxx.md"）而非内容本身
- 工具调用指令（Read、Write、Bash、Agent 等）
- 关键约束和安全注意事项

### 4.2 应提取到 references/ 的内容 (L3)

- 超过 100 行的参考文档
- 领域知识（规范、标准、术语定义）
- 详细的检查清单
- 长篇示例和案例
- 不同场景下的变体指令
- 背景信息和上下文说明

### 4.3 应提取到 scripts/ 的内容 (L3)

- LLM 频繁出错的确定性操作
- 需要精确结果的比对和校验
- 格式转换（YAML→JSON、Markdown 解析）
- 数学计算、统计、数据聚合
- 文件内容的结构化提取

### 4.4 提取判断流程图

```
这个内容块...
├── 是核心执行指令吗？
│   └── 是 → 保留在 SKILL.md body (L2)
│
├── 是领域参考/规范/长篇说明吗？
│   └── 是 → references/ (L3)，SKILL.md 中用 "详见 references/xxx.md" 引用
│
├── 是确定性操作（校验/比对/计算/转换）吗？
│   └── 是 → scripts/ (L3)，SKILL.md 中用 Bash 工具调用
│
├── 是可复用的输入/输出格式吗？
│   └── 是 → templates/ (L3)，SKILL.md 中引用模板路径
│
└── 是背景信息/上下文说明吗？
    └── 是 → references/ (L3) 或删除（如果不需要）
```

---

## 5. Description 公式

### 标准公式

```
「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」
```

### 好的 Description 示例

```
代码安全审查：检查 Python/JavaScript 代码中的安全漏洞（SQL 注入、XSS、硬编码密钥）。
当用户请求代码安全检查、安全审查或提交代码前审查时触发。
输入为文件路径或代码 diff，输出包含严重级别（CRITICAL/HIGH/MEDIUM/LOW）的 Markdown 审查报告。
```

### 差的 Description 示例

```
帮助处理代码
```
→ 太宽泛，Agent 无法判断何时触发

```
代码审查
```
→ 缺少输入/输出说明，Agent 不知道能接收什么、产出什么

---

## 6. 脚本设计原则

### 6.1 脚本的独立性

每个 scripts/ 下的脚本必须:
- 可独立运行（`python script.py input` 即可执行）
- 不依赖 LLM 上下文（不读取对话历史）
- 通过文件或 stdin/stdout 传递数据
- 有明确的退出码（0=成功, 非0=失败+错误信息）
- 输出结构化结果（JSON 或明确的文本格式）

### 6.2 脚本 vs LLM 决策框架

| 操作类型 | 推荐方式 | 理由 |
|---------|:------:|------|
| YAML/JSON 语法校验 | 脚本 | 确定性操作，LLM 容易漏报 |
| Mermaid 语法检查 | 脚本 | 精确语法规则，LLM 难以逐字校验 |
| 代码风格检查 (PEP8, ESLint) | 脚本 | 已有成熟工具，无需 LLM |
| 文件内容是否匹配模式 | 脚本 (grep/regex) | 精确匹配优于 LLM "看起来像" |
| 格式转换 (JSON→YAML) | 脚本 | 确定性转换，不应有变体 |
| 生成审查意见 | LLM | 需要理解和判断 |
| 判断代码意图 | LLM | 需要语义理解 |
| 评估输出质量 | LLM | 需要综合判断 |
| 决定修复策略 | LLM | 需要权衡和推理 |

---

## 7. 命名约定

### Skill 目录命名

- 使用 kebab-case
- 包含领域关键词（如 `python-`、`security-`、`code-review-`）
- 具象化 — `python-pep8-checker` 优于 `code-checker`
- 不超过 4 个词 — `deploy-staging-health-check` 优于 `deploy-to-staging-and-check-health`

### references/ 文件命名

- 描述性命名 — `pep8-rules.md` 优于 `rules.md`
- 与 SKILL.md 中的引用一致

### scripts/ 文件命名

- 动词开头 — `validate_syntax.py`、`extract_imports.py`
- 反映具体操作，而非泛化名称

---

## 8. 常见设计反模式

| 反模式 | 问题 | 正确做法 |
|--------|------|---------|
| **内联一切** | SKILL.md 800+ 行，参考/脚本/模板全在一个文件 | 按 §4 分类提取到 references/scripts/templates/ |
| **LLM 做脚本的事** | 用 LLM 做 JSON 校验、代码风格检查 | 写成独立脚本，LLM 调用脚本 |
| **过早拆分** | 3 个步骤的简单 Skill 拆成 5 个 SubAgent | 单体先做到 300 行以内 + 分层清晰，再考虑拆分 |
| **描述模糊** | "帮助处理代码" | 使用 §5 公式重写 |
| **幽灵引用** | references/ 下文件未被 SKILL.md 引用 | 确保每个 L3 文件在 SKILL.md 中有明确引用 |
| **引用断链** | SKILL.md 引用了 references/xxx.md 但文件不存在 | 建立引用后验证文件存在 |
| **脚本依赖上下文** | 脚本假设 LLM 会提供某些变量的值 | 脚本通过命令行参数或 stdin 接收所有输入 |
| **模板不可用** | 模板包含大量 "请填入..." 但无结构指导 | 模板应可直接复制，含占位符和填写说明 |

---

## 9. 设计审查清单

生成优化方案时，逐项确认:

- [ ] SKILL.md body ≤ 300 行
- [ ] description 含「做什么」+「何时触发」+「输入」+「输出」
- [ ] 超过 100 行的参考内容已提取到 references/
- [ ] 确定性操作（校验/比对/计算/转换）通过 scripts/ 脚本执行
- [ ] 每个 references/ 文件在 SKILL.md 中被明确引用
- [ ] 每个 scripts/ 脚本可独立运行
- [ ] templates/ 中的模板可直接复制使用
- [ ] 目录名 kebab-case + 领域关键词
- [ ] 无 LLM 执行确定性操作的步骤
- [ ] 分层后的引用链完整（无断链、无幽灵引用）
