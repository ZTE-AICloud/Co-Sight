# 重构原则 ② — Skill 重构模式库(Before / After)

> **来源**:AgentGenesis 实战案例库(`skill-examples.md`)
> **用途**:重构阶段提供**具体可复制的重构模板** — 拿到一段内容,直接套用对应模式
> **适用**:所有被 skillx-alpha-agents 处理的目标 Skill 的 body 拆分、references 提取、脚本提取

---

## 0. 模式速查表

| 模式 | 核心问题 | 关键修复 | 适用场景 |
|------|---------|---------|----------|
| **A. 内联代码 → scripts/ 提取** | 代码嵌入 Markdown,LLM 当脚本用 | 提到 scripts/,LLM 只做语义判断 | SKILL.md 含 >20 行代码块 |
| **B. 内联规范 → references/ 提取** | 参考文档内联占满上下文 | 按类别拆分 references/,SKILL.md 加引用 | SKILL.md 含大量规范/规则/示例 |
| **C. 单体长链 → 分层 + 脚本 + 状态** | 12 步全内联,无脚本无状态 | 拆分层 + scripts + task-state.json | SKILL.md 含 8+ 步骤 |

---

## 模式 A:内联代码 → scripts/ 提取

### 适用场景

- SKILL.md 中存在 >20 行的 Python/Shell/JS 代码块
- 代码段在做确定性操作(校验、比对、格式转换、统计)
- LLM 用自然语言"模拟执行"这类代码(易出错)

### Before(反模式)

```markdown
# helper
> description: 帮助处理事情

## 代码风格检查
检查代码是否符合 pep8 规范。下面是一些常见规则:

​```python
def check_line_length(file_path):
    violations = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f, 1):
            if len(line.rstrip('\n')) > 79:
                violations.append({'line': i, 'code': 'E501'})
    return violations
# ...(40+ 行代码省略)

## 依赖检查
检查项目的 Python 依赖是否有已知的安全漏洞。
```

**问题**:代码嵌入 Markdown 阅读困难;无法独立测试脚本逻辑;每次 Skill 触发都要把代码注入上下文;description 无法准确触发。

### After(Anthropic 规范)

```
pep8-helper/
├── SKILL.md              # 核心指令 + 引用 L3
├── scripts/
│   └── check_pep8.py     # 独立可运行的 PEP8 检查脚本
└── references/
    └── pep8-rules.md     # PEP8 规则详细说明
```

**SKILL.md**(重构后):
```markdown
# PEP8 Code Checker

> description: 检查 Python 代码的 PEP8 合规性。当用户请求代码风格检查、
> PEP8 检查或提交前质量检查时触发。输入为文件路径,
> 输出 Markdown 违规报告到 work/ 目录。

## 核心指令

1. 读取目标 Python 文件
2. 执行 PEP8 合规检查:
   - **确定性检查**(行长度、尾随空格、空行数量):
     `Bash python scripts/check_pep8.py <file_path>`
   - **语义检查**(命名规范、注释质量、代码结构):LLM 判断
3. 汇总脚本输出和 LLM 语义判断,生成统一报告
4. 输出到 `work/pep8-report.md`

## 详细规范

PEP8 规则详细说明见 `references/pep8-rules.md`
```

### 重构步骤

1. **识别内联代码块**:扫描 SKILL.md,提取 >10 行的 Python/Shell 代码段
2. **判断确定性**:代码是否在做精确比对/计算/校验?(是 → 提取)
3. **提取到 scripts/**:`scripts/<verb>_<noun>.py`,遵循 §6 命名约定
4. **脚本独立化**:通过命令行参数/stdin 接收所有输入,退出码明确
5. **SKILL.md 替换代码块**:用 `Bash python scripts/xxx.py <args>` 一行引用
6. **语义部分保留**:LLM 做的判断(命名/注释/结构)仍写在 body

### 验证清单

- [ ] 原代码段已删除,改为单行 Bash 调用
- [ ] 脚本可独立运行(`python scripts/check_pep8.py file.py` → exit 0/非0)
- [ ] 脚本不读取 LLM 对话历史(纯命令行)
- [ ] SKILL.md body 行数下降 ≥ 30 行
- [ ] 描述(description)用「做什么+何时触发+输入+输出」完整公式重写

---

## 模式 B:内联规范 → references/ 提取

### 适用场景

- SKILL.md 含大量规则、规范、漏洞详解(每条 >5 行说明)
- 每条规则只在对应场景才需要参考
- 新增规则类型频繁(SKILL.md 频繁修改)

### Before(反模式)

```markdown
# Security Scanner
> description: 扫描代码安全漏洞

1. SQL 注入 — 检查是否有字符串拼接构建 SQL 查询的情况。使用参数化查询替代字符串拼接。
   Python 中使用 cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,)) 而非 f"SELECT..."。
2. XSS 漏洞 — 检查是否有未转义的用户输入直接渲染到 HTML。使用 html.escape(user_input) 进行转义。
3. 命令注入 — 检查是否有用户输入直接拼接到系统命令。使用 subprocess.run([cmd, arg]) 替代 os.system(f"cmd {user_arg}")。
...(9 种漏洞类型 + 代码示例省略,约 80 行)
```

**问题**:12 种漏洞详解占用大量上下文,但只在检查到对应类型时才需要;Agent 在核心指令和安全知识之间失焦;新增漏洞类型需改 SKILL.md body。

### After(Anthropic 规范)

```
security-scanner/
├── SKILL.md                    # 核心扫描指令 + 分类引用
├── references/
│   ├── injection-attacks.md    # SQL 注入、命令注入、XXE
│   ├── xss-and-web.md          # XSS、CORS、Cookie 安全、CSP
│   ├── crypto-and-deserialization.md  # 弱加密、不安全反序列化
│   └── file-and-path.md        # 路径遍历、SSRF
├── scripts/
│   └── detect_hardcoded_keys.py  # 检测硬编码密钥(正则确定性)
└── templates/
    └── security-report.md      # 标准化输出模板
```

**SKILL.md**(核心指令部分):
```markdown
# Security Scanner

> description: 扫描代码安全漏洞,覆盖 SQL 注入、XSS、命令注入、硬编码密钥等
> 12 种常见漏洞类型。当用户请求安全检查、安全审查或提交前安全扫描时触发。
> 输入为文件路径,输出分级安全报告到 work/ 目录。

## 核心指令

1. 读取目标代码文件
2. 逐类型检查:
   - 硬编码密钥(确定性):`Bash python scripts/detect_hardcoded_keys.py <file>`
   - 注入类漏洞(SQL/Command/XXE):见 `references/injection-attacks.md`
   - Web 安全(XSS/CORS/Cookie/CSP):见 `references/xss-and-web.md`
   - 加密与序列化:见 `references/crypto-and-deserialization.md`
   - 文件与路径安全:见 `references/file-and-path.md`
3. 每个发现标注:漏洞类型 + 严重级别 + 证据行号 + 修复建议
4. 按 `templates/security-report.md` 格式输出报告到 `work/security-report.md`
```

### 重构步骤

1. **识别内联规范块**:扫描 SKILL.md,提取 "类型化" 的规则列表(每条 >5 行说明)
2. **按类别分组**:按主题聚合(注入类/Web 类/加密类/路径类),每组一个 references/ 文件
3. **提取到 references/**:文件名用 `<category>-<topic>.md`(如 `injection-attacks.md`)
4. **SKILL.md 替换为引用**:每条规则改为一行 "见 references/xxx.md"(只保留必要的入口提示)
5. **建立模板**(若有标准化输出):`templates/<report-name>.md`
6. **校验引用链**:每个 references/ 文件都被 SKILL.md 引用,且文件存在

### 验证清单

- [ ] 原规范块已删除,改为单行 "见 references/xxx.md" 引用
- [ ] references/ 文件数 ≥ 3(原内联内容被拆分到多文件)
- [ ] 单个 references/ 文件 ≤ 150 行
- [ ] 每个 references/ 文件在 SKILL.md 中有明确引用
- [ ] SKILL.md body 行数下降 ≥ 50 行
- [ ] 无幽灵引用(文件存在但未引用)或断链(引用但文件不存在)

---

## 模式 C:单体长链 → 分层 + 脚本 + 状态

### 适用场景

- SKILL.md 含 8+ 步骤,全部内联
- 多步骤涉及确定性操作(健康检查、配置校验、冒烟测试)
- 流程可能中断或失败,需要 resume 能力
- 不同环境有差异(Staging/Production)

### Before(反模式)

12 步部署管理全部内联,52 行但无分层、无脚本、无状态追踪:

```markdown
# Deploy Manager
> description: 部署管理

## Step 1: 读取配置文件
## Step 2: 验证环境
...(12 步全内联)
## Step 12: 回滚检查
```

**问题**:description 太宽泛;12 步全内联但很多步骤实际是 Bash 调用外部工具;无状态追踪,中断后不知道做到哪步;无 references/ 分离环境配置;无 scripts/ 提取健康检查、冒烟测试等确定性操作。

### After(Anthropic 规范)

```
deploy-manager/
├── SKILL.md                     # 核心部署流程 + checkpoint
├── references/
│   ├── environments.md          # Staging/Production 环境配置
│   ├── rollback-procedures.md   # 回滚详细流程
│   └── notification-templates.md # 通知消息模板
├── scripts/
│   ├── health_check.sh          # 健康检查(curl + 超时 + 重试)
│   ├── smoke_test.sh            # 冒烟测试
│   └── validate_config.py       # 配置文件校验
├── templates/
│   └── deploy-config.yaml       # 部署配置模板
└── work/                        # 运行时产生
    └── task-state.json          # checkpoint 状态
```

**SKILL.md**(重构后):
```markdown
# Deploy Manager

> description: 执行应用的多环境部署流程(构建→测试→Staging→Production),
> 包含冒烟测试、健康检查和自动回滚。当用户请求部署、发布或上线时触发。
> 输入为 deploy-config.yaml,输出部署报告到 work/ 目录。

## 核心流程

1. 配置校验:`Bash python scripts/validate_config.py deploy-config.yaml`
2. 构建:`Bash docker build ...`(参数从 deploy-config.yaml 读取)
3. 测试:执行单元测试 + 集成测试
4. Staging 部署:`Bash kubectl apply -f staging/`
5. 冒烟测试:`Bash scripts/smoke_test.sh <staging-url>`
6. Production 部署:`Bash kubectl rollout restart deployment/<name>`
7. 健康检查:`Bash scripts/health_check.sh <production-url> --retry 3`
   - 失败 → 执行回滚,详见 `references/rollback-procedures.md`
8. 通知:按 `references/notification-templates.md` 发送 Slack 通知

## 状态追踪

每步执行前更新 `work/task-state.json`:
- 读取 → 跳过 DONE 步骤
- 开始 → IN_PROGRESS
- 完成 → DONE
- 失败 → FAILED + 错误信息

## 环境配置

Staging/Production 环境差异详见 `references/environments.md`
```

### 重构步骤

1. **识别长流程**:SKILL.md 含 8+ 编号步骤(Step 1 / 1. / 步骤 N)
2. **步骤分类**:每个步骤归入三类之一
   - **LLM 判断**(理解用户意图、决策分支)→ 保留在 SKILL.md
   - **确定性操作**(校验、构建、测试、部署命令)→ 提取到 scripts/
   - **环境/规则/变体说明**→ 提取到 references/
3. **提取确定性步骤到 scripts/**:每个 Bash 命令若可复用,改为 scripts/ 中的 .sh/.py
4. **提取变体说明到 references/**:环境配置、回滚流程、通知模板
5. **建立 task-state.json**:每步写入 {step, status, ts, error?};失败时恢复
6. **SKILL.md 瘦身**:body 只保留主流程 + checkpoint + 引用

### 验证清单

- [ ] SKILL.md body 行数从原 > 50 降到 ≤ 300,且 H2 章节从「12 步清单」改为「核心流程 + 状态追踪 + 环境配置」3 类
- [ ] scripts/ 含 ≥ 3 个确定性操作脚本,每个可独立运行
- [ ] references/ 含环境/回滚/通知等变体说明文件
- [ ] 存在 `work/task-state.json` 模板或初始化逻辑
- [ ] description 用「做什么+何时触发+输入+输出」完整公式重写
- [ ] 流程中断后可从 task-state.json 恢复(resume 友好)

---

## 3. 模式选择的决策树

```
拿到一段 SKILL.md body...
│
├── 包含 >20 行 Python/Shell 代码?
│   └── 是 → 模式 A(代码 → scripts/)
│
├── 包含类型化的规则列表(每条 >5 行说明)?
│   └── 是 → 模式 B(规范 → references/)
│
├── 包含 8+ 步骤的线性流程?
│   └── 是 → 模式 C(单体 → 分层 + 脚本 + 状态)
│
└── 三者混合?
    └── 多个模式并行应用(分别提取到对应目录)
```

---

## 4. 重构后必跑的验证

无论套用哪个模式,完成后必跑:

| 验证项 | 方法 | 通过条件 |
|--------|------|----------|
| body 行数 | `wc -l SKILL.md` | ≤ 300 |
| description 完整性 | 人工对照公式 | 「做什么+何时+输入+输出」齐全 |
| 引用链完整 | `grep -E "references/" SKILL.md` 与 `ls references/` 对照 | 每个引用对应文件存在,每个文件被引用 |
| scripts 可独立运行 | 每个脚本单跑 `python scripts/xxx.py input` | 退出码 0 或明确错误码 |
| LLM 仍能完成任务 | 用重构后 SKILL.md 跑一次样例任务 | 输出与重构前等价或更好 |
| Token 节省(可选) | 重构前 vs 重构后 SKILL.md body 的 token 数 | 重构后 token 数下降 ≥ 30% |

---

## 5. 与 skillx-alpha-agents 工作的衔接

skillx-alpha-agents 在以下场景应用本模式库:

| 场景 | 应用模式 |
|------|---------|
| `/skill_optimize` 静态评估 | 命中反模式 → 直接套用对应模式 |
| `/skill_evolve` 优化提案 | mod 字段建议「提取到 scripts/references/scripts」时,引用本模式名 |
| OptimizerGateway 生成 mod | 修改 H2 章节时优先 move,而非 rewrite |
| EvaluatorAgent 评分 | dim10_coverage 等维度按本模式打分(覆盖度高的应拆分充分) |

> **核心约束**(参见 COSIGHT.md §10):优化器**禁止全量重写 SKILL.md**,只能修改需要改动的 H2 章节。模式 A/B/C 的本质是「把内容从 body 移出去」,而非「重写 body」— 完全契合这一约束。

---

## 6. 实战案例:三类典型重构 + 实际数据(2026-07 组件间流程设计 Skill)

> 实际跑过的重构案例,展示 A/B/C 模式在真实 Skill 上的应用与代价。

### 6.1 案例背景

| 字段 | 值 |
| --- | --- |
| 目标 Skill | 组件间流程设计(SDD 子系统设计 Agent 子技能) |
| 重构前 SKILL.md | 243 行, 6363 字符 |
| 重构后 SKILL.md | 108 行, 2863 字符(-55%) |
| 测试需求 | 6 个(RAN-5741646/6165989/6822598/6640009/5678762/6166005) |
| 重构后耗时 | 8.83h → 6.22h(-29.6%) |
| 重构后工具调用 | 1218 → 1862(+52.9%) |
| 平均 F1 | 17.22 → 18.90(+1.68) |

### 6.2 应用的模式

- **模式 A** 部分应用:`scripts/md_table_to_json.sh` / `process_subsystem_table.sh` 等 15 个脚本原本就在,只合并了 4 个 util → `lib.sh`
- **模式 B** 大量应用:13 项过程产物路径外移到 `references/io-contract.md`、ASCII 流程图外移到 `references/router.md`、13 个 scripts 路由外移到 `scripts/README.md`
- **模式 C** 部分应用:从单 SKILL.md 主体拆为 SKILL.md + references/ + scripts/README.md + templates/README.md,引入分层

### 6.3 重构后暴露的两类问题

**问题 A — 脚本链接错位**(对应 §1 反模式新增):
- 删除 `config.sh` 合并到 `lib.sh` 后,5 个脚本里的 `if [ -f config.sh ]` 块未同步更新
- Agent 跑这些脚本直接 exit 1,后续 Procedure 输入丢失
- 影响需求:RAN-5741646(F1 45.99 → 0.00)

**问题 B — SKILL 瘦身让 Agent 跳过中间组件**(对应 §1 反模式新增):
- §4 ASCII 流程图外移到 router.md,Agent 自主决策时倾向走"更直接"路径
- 中间层组件(SMC、FCS)被跳过
- 影响需求:RAN-6166005(F1 24.88 → 0.00)

### 6.4 数据上的反直觉

| 现象 | 数值 | 直觉预测 | 实际 |
| --- | --- | --- | --- |
| SKILL.md 缩短 | -55% | 调用次数下降 | **调用次数 +53%**(脚本调用更密) |
| 耗时减少 | -29.6% | 单次调用更快 | **单次调用耗时 -54%**(决策成本更低) |
| 工具调用增多 | +53% | 耗时增加 | **耗时反而降** |
| F1 微涨 | +1.68 | 退化少 | **实际 6 需求中 2 个退化到 0,1 个从 0 恢复** |

**核心结论**:**「调用次数」「耗时」「F1」是同一个 trade-off (精度 vs 速度) 的不同投影**,数据层面是"压力扫描 vs 精准射击"两种模式的选择。

### 6.5 后续重构该怎么做

1. 应用模式 A/B/C 时,**先做「source 链一致性」grep 检查**(对应 `重构后检查-Skill完整性验证.md` §10.1)
2. **回归测试 R-N 场景必须包含「完整中间层」用例**(对应 `重构后检查-等效性与回归测试.md` §1.4)
3. **重写 description 时不要追求简洁而丢失触发词**(对应本文档 §4.5 描述公式)
4. **保留 router.md 关键路径的「强制中间层」标注**(对应本文档 §10.2)

---

## 7. 模式选择的扩展决策树(含本案例补充)

```
拿到一段 SKILL.md body...
│
├── 包含 >20 行 Python/Shell 代码?
│   └── 是 → 模式 A(代码 → scripts/)
│       └── ⚠️ 合并多个 util 脚本时:先 grep 所有 source 链,再删旧文件(§6.3 问题 A)
│
├── 包含类型化的规则列表(每条 >5 行说明)?
│   └── 是 → 模式 B(规范 → references/)
│       └── ⚠️ 关键链路/中间层不要完全外移(§6.3 问题 B)
│
├── 包含 8+ 步骤的线性流程?
│   └── 是 → 模式 C(单体 → 分层 + 脚本 + 状态)
│
└── 三者混合?
    └── 多个模式并行应用,但每步都做「source 链检查 + 中间层保留检查」
```