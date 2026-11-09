# 重构原则 ④ — Skill 极致代码化(LLM vs 脚本分工)

> **来源**:AgentGenesis `skill-design-guide.md §6 + skill-examples.md` + d7bcf0da 组件间流程设计 Skill 重构实战(2026-07)
> **用途**:重构阶段把"**确定性操作归脚本,语义判断归 LLM**"这条核心原则落到**可执行的判定 + 反模式 + 脚本独立性约束**
> **适用**:所有被 `/skill_refactor` / `/skill_optimize` 处理的、含 scripts/ 子目录或内联代码块的目标 Skill
> **与现有 3 份原则的关系**:① 分层与目录结构(放哪)→ ② 重构模式库(怎么拆)→ ③ 性能与 token 优化(怎么省)→ **④ 极致代码化(LLM/脚本谁来做)**

---

## 0. 一句话核心

> **LLM 擅长推理、生成、判断;脚本擅长精确、重复、可验证。不要把 LLM 当作脚本引擎使用。**

这条原则决定了一件事:**重构的尽头是"少让 LLM 干确定性的事,多让脚本干,LLM 只做语义"。** 它既是分层原则 ① 的延伸(确定性操作 → scripts/),也是模式库 ② 模式 A 的内核(为什么要提取),还是性能优化 ③ 的杠杆点(脚本比 LLM 快/准/省)。

---

## 1. LLM vs 脚本决策框架(可复制粘贴)

### 1.1 决策矩阵

| 操作类型 | 推荐方式 | 理由 | 常见反例 |
|---------|:------:|------|---------|
| YAML/JSON 语法校验 | **脚本** | 确定性操作,LLM 容易漏报 | LLM 逐行"看着像合法 YAML" |
| Mermaid/PlantUML 语法检查 | **脚本** | 精确语法规则,LLM 难以逐字校验 | LLM 写完图后不校验,渲染报错 |
| 代码风格检查(PEP8/ESLint/Ruff) | **脚本** | 已有成熟工具,无需 LLM 复刻 | LLM 用"len(line) > 79"模拟行长度检查 |
| 文件内容匹配模式(grep/regex) | **脚本** | 精确匹配优于 LLM "看起来像" | LLM 判断"是否包含硬编码密钥" |
| 格式转换(JSON↔YAML/Markdown 解析) | **脚本** | 确定性转换,不应有变体 | LLM 手工解析 markdown 表格 |
| 数学计算、统计、数据聚合 | **脚本** | 浮点精度 + O(n) 保证 | LLM 心算"平均值" |
| 时间戳/路径/文件名规范化 | **脚本** | 一行 `date +%Y%m%d_%H%M%S` 完事 | LLM 拼字符串 |
| 文件存在/可读/可写校验 | **脚本** | `test -f/-r/-w` 一行解决 | LLM 反复 Read 探测 |
| 调用外部工具或 API | **脚本** | 封装 + 重试 + 超时 | LLM 直接 Bash `curl | sh` |
| 复杂 SQL 查询 | **脚本** | schema 校验 + 注入防护 | LLM 拼接 SQL 字符串 |
| **生成审查意见 / 报告** | **LLM** | 需要理解和判断 | 脚本化"找出所有 TODO" |
| **判断代码意图 / 命名质量** | **LLM** | 需要语义理解 | 脚本判"驼峰 vs 下划线" |
| **评估输出质量 / 决定修复策略** | **LLM** | 需要综合判断 + 权衡 | 脚本给所有问题打同样严重级 |
| **生成新内容(章节、示例、对话)** | **LLM** | 需要创造 + 上下文 | 脚本模板填空过于死板 |

### 1.2 速判流程图

```
拿到一段操作描述,问 3 个问题:

Q1: 这操作是"找/算/转/验"还是"想/评/创"?
    ├─ 找/算/转/验 → 脚本
    └─ 想/评/创 → LLM

Q2: 如果 LLM 错了,后果是"输出有偏差"还是"系统崩溃/数据错"?
    ├─ 系统崩溃/数据错 → 必须脚本(LLM 幻觉不能容忍)
    └─ 输出有偏差 → 都可以,但优先脚本(可重试 + 可审计)

Q3: 这个操作要跑多少次?
    ├─ 一次(单 case) → LLM 可接受
    └─ 循环/批量 → 脚本(LLM 上下文会爆炸)
```

---

## 2. Design Form 4 项强制检查(DF-M1~M4)

> 重构方案落地前必须先过 4 项 Design Form 检查。**结构分层建立之前,不执行功能层面的优化。**

| 编号 | 检查 | 通过标准 | 不通过的修复 |
|:----:|------|---------|-------------|
| **DF-M1** | 目录分层 | 有需分层内容时应有 `references/scripts/templates` 目录 | 在 `before_skill/` 拷贝时一并建好子目录 |
| **DF-M2** | 渐进式加载 | SKILL.md 不内联 >100 行的参考文档或代码块 | 外移到 `references/<topic>.md` 或 `scripts/<verb>_<noun>.py` |
| **DF-M3** | 描述公式 | description 含「做什么」+「何时触发」+「输入」+「输出」 | 按 §4 公式重写,控制在 30~1024 字符 |
| **DF-M4** | 脚本独立 | 有确定性操作时应通过 Bash 调用 `scripts/` 脚本 | 把内联代码段提取成独立脚本,SKILL.md 用单行 `Bash python scripts/xxx.py` 引用 |

**DF-M4 是"极致代码化"的核心闸门**:任何在 SKILL.md body 里写 >10 行 Python/Shell 代码块的,都视为违反 DF-M4,必须先重构通过才能进入功能层优化。

---

## 3. scripts/ 子目录的 6 条独立性硬规则

> 每个 `scripts/<name>.py` 或 `<name>.sh` 必须满足以下 6 条,否则视为"伪脚本"(本质是把 LLM 当脚本用)。

### 3.1 可独立运行
```bash
# 必须能直接跑,不依赖任何 LLM 上下文
python scripts/check_pep8.py <file_path>         # ✅
python scripts/check_pep8.py                     # ❌ 缺参数
```

### 3.2 不依赖 LLM 对话历史
- 禁止 `os.environ.get('COSIGHT_SESSION_ID')` 之类的反模式
- 禁止"假设 LLM 已经把 X 变量传给我"——所有输入必须显式

### 3.3 输入输出走文件 / stdin / stdout / 命令行参数
```python
# ✅ 标准做法
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--output", "-o", type=Path, default=None)
    args = parser.parse_args()
    ...

# ❌ 反模式:从环境变量读
def main():
    file_path = os.environ["SKILL_TARGET_FILE"]   # 不可移植
```

### 3.4 退出码明确
- `0` = 成功
- `非 0` = 失败 + 错误信息输出到 stderr
- 不要用 `print("FAILED")` 然后 `exit(0)`(骗自己)

### 3.5 结构化输出
- 优先 JSON(机器可解析)
- 次选明确的文本格式(表格、key:value)
- **禁止** "成功!搞定!" 之类的自然语言成功消息(token 税 + 不可解析)

### 3.6 可独立测试
```bash
# 必须能写一个最小 pytest / bash 断言验证脚本逻辑
python -m pytest scripts/test_check_pep8.py       # ✅
bash -n scripts/check_pep8.sh                     # ✅ 语法校验
```

---

## 4. Description 4 要素公式(DF-M3 配套)

> 一个能准确触发的 description 必须含 4 要素,缺一不可。

### 4.1 标准公式

```
「做什么」+「何时触发」+「接收什么输入」+「产出什么输出」
```

### 4.2 正反对比

```
✅ 好:代码安全审查:检查 Python/JS 代码中的安全漏洞(SQL 注入、XSS、硬编码密钥)。
       当用户请求代码安全检查、安全审查或提交代码前审查时触发。
       输入为文件路径或代码 diff,输出包含严重级别(CRITICAL/HIGH/MEDIUM/LOW)
       的 Markdown 审查报告。

❌ 差 1:"帮助处理代码" → 太宽泛,Agent 无法判断何时触发
❌ 差 2:"代码审查" → 缺输入/输出说明,Agent 不知道能接收什么
❌ 差 3:"这是一个用于执行多种安全相关任务的通用工具" → 描述本身是"自我描述的死循环"
```

### 4.3 字符预算

- **下限 30 字符**:少于 30 字符几乎一定不达标
- **上限 1024 字符**:超出后 L1 注入 token 税过重,触发率反而下降
- **目标 100~300 字符**:含 4 要素最舒适区间

---

## 5. 8 个常见反模式(重构必查)

| # | 反模式 | 问题 | 正确做法 |
|:-:|--------|------|---------|
| 1 | **内联一切** | SKILL.md 800+ 行,参考/脚本/模板全在一个文件 | 按原则 ① §4 分类提取到 references/scripts/templates/ |
| 2 | **LLM 做脚本的事** | 用 LLM 做 JSON 校验、代码风格检查 | 写成独立脚本,SKILL.md 用 Bash 调用 |
| 3 | **过早拆分** | 3 个步骤的简单 Skill 拆成 5 个 SubAgent | 单体先做到 300 行以内 + 分层清晰,再考虑拆分 |
| 4 | **描述模糊** | "帮助处理代码" | 用 §4 公式重写,4 要素齐全 |
| 5 | **幽灵引用** | `references/` 下文件未被 SKILL.md 引用 | 每个 L3 文件必须在 SKILL.md 有明确引用 |
| 6 | **引用断链** | SKILL.md 引用了 `references/xxx.md` 但文件不存在 | 建立引用后必须 `test -f` 验证 |
| 7 | **脚本依赖上下文** | 脚本假设 LLM 会提供某些变量的值 | 脚本通过命令行参数或 stdin 接收所有输入 |
| 8 | **模板不可用** | 模板含大量 "请填入..." 但无结构指导 | 模板应可直接复制,含占位符和填写说明 |

---

## 6. d7bcf0da 实战案例对照(2026-07 组件间流程设计 Skill 重构)

> d7bcf0da session 用本原则重构了一个 33 文件 +752/-970 行的 Skill,**核心收益 80% 来自"确定性操作脚本化"**。

### 6.1 重构前后的 scripts/ 对比

| 维度 | Before | After |
|------|--------|-------|
| scripts/ 文件数 | 6 个(分散) | 1 个 `lib.sh`(353 行集中)+ 6 个独立工具脚本 |
| 内联 Shell 代码块 | SKILL.md 含 ~80 行 Shell | 0 行,全部改为 `Bash bash scripts/xxx.sh <args>` |
| source 链 | 5 个脚本残留 `if [ -f config.sh ]` 块(config.sh 已删除) | 全部改为 `source lib.sh` 直调 |
| 脚本可独立测试 | 0 个可 pytest | 100% 可 `bash -n` 语法校验 |
| 单步调试 | 必须跑完整 Skill 才能验证 | 单脚本 `bash -x scripts/extract_design_input.sh` 即可 |

### 6.2 重构后 7 步 plan 中"极致代码化"相关 step

d7bcf0da 实战中,**Step 5(脚本化确定性操作)** 和 **Step 1.5(source 链一致性预检)** 都是本原则的产物:

- **Step 5** 对标本原则 §1 决策矩阵,把"找/算/转/验"类操作全部外移到 `scripts/`
- **Step 1.5** 对标本原则 §3(脚本独立性),在合并/删除脚本前先 `grep -rn "source\|if.* -f" scripts/` 列出所有 source 引用点,确认每个引用都已同步

### 6.3 退化的 2 个反面教训

| 退化 | 原因 | 修复 |
|------|------|------|
| **5 个 validate_*.sh 残留 `if [ -f config.sh ]` 块** | 合并 config.sh 到 lib.sh 后,5 个脚本的 `if` 块没同步删 | 在 Step 9 应用前必跑 `grep -rn "if.*-f.*\.sh" scripts/` 校验 |
| **1/6 需求 router.md 中间层丢失** | 把详细流程图外移到 `references/router.md` 时,简化了链路,跳过了 SMC/FCS/XC 中间组件 | router.md 关键路径加 ⚠️ "必须包含中间组件" 标注 |

---

## 7. 13 类 FD 中"极致代码化"相关检查项(对标 d7bcf0da)

> 在 `/skill_refactor` 的 LLM 诊断 prompt 中,以下 FD 编号与本原则直接对应。重构 agent 输出 findings 时**必须包含本节相关检查**,不适用时输出 `severity=LOW + recommendation='不适用,因 <原因>'`。

| FD 编号 | 检查主题 | 严重度 | 对应本原则章节 |
|:-------:|---------|:------:|:------------:|
| **FD-005** | scripts/ 工具层合并(对标 lib.sh 集中) | HIGH | §1 决策框架 + §6.1 |
| **FD-006** | scripts/load_rule.sh + table_io.sh + scripts/README.md | MEDIUM | §3 独立性硬规则 |
| **FD-012** | scripts/ source 链一致性预检 | MEDIUM | §3.3 输入输出 + §6.3 |
| **FD-014** | **DF-M4 脚本独立:SKILL.md 内联 >10 行 Python/Shell 代码块** | **HIGH** | §2 DF-M4 |
| **FD-015** | **Description 4 要素公式:缺"输入/输出/触发/做什么"中任一项** | **HIGH** | §4 Description 公式 |
| **FD-016** | **scripts/ 脚本依赖 LLM 上下文(从环境变量读 session_id 等)** | **MEDIUM** | §3.2 不依赖 LLM 对话 |

> FD-014/015/016 是本原则引入的新检查项。重构 agent 必须在 13 类必查 FD 基础上**至少覆盖** FD-014 和 FD-015(必查的 Design Form 项)。

---

## 8. 重构检查清单(本原则)

生成 refactor plan 时,逐项确认:

- [ ] **DF-M1** 有需分层内容时已建 `references/scripts/templates` 子目录
- [ ] **DF-M2** SKILL.md body 已不内联 >100 行参考文档或代码块
- [ ] **DF-M3** description 含「做什么」+「何时触发」+「输入」+「输出」(4 要素齐全)
- [ ] **DF-M4** SKILL.md body 已不内联 >10 行 Python/Shell 代码块(全部改为 Bash 调用)
- [ ] 每个 `scripts/<name>.{py,sh}` 满足 6 条独立性硬规则(可独立运行 + 不依赖 LLM + 文件 I/O + 明确退出码 + 结构化输出 + 可独立测试)
- [ ] 没有任何"用 LLM 做 JSON 校验/YAML 解析/正则匹配"的步骤
- [ ] 描述(description)在 30~1024 字符区间
- [ ] `references/` 下文件全部在 SKILL.md 中有显式引用(无幽灵引用)
- [ ] SKILL.md 引用的所有 `references/` 文件真实存在(无断链)
- [ ] 模板可直接复制使用,占位符有填写说明
- [ ] 合并/删除 scripts/ 源文件前已跑 source 链一致性预检
- [ ] 外移流程图前已验证关键路径/中间层保留

---

## 9. 与其他 3 份原则的协同

```
原则 ① (分层与目录结构) → 回答"放哪"
       ↓
原则 ② (重构模式库) → 回答"怎么拆"
       ↓
原则 ③ (性能与 token 优化) → 回答"怎么省"
       ↓
原则 ④ (极致代码化) → 回答"LLM/脚本谁来做"
       ↓
具体 refactor plan (Step 0~7) → 落地
```

**举例串联**:
1. 原则 ① 判定:"这个 30 行 Python 代码块是确定性操作"→ 该去 `scripts/`
2. 原则 ② 模式 A 提供:**怎么提取**的具体 Before/After 模板
3. 原则 ③ §2.1 解释:为什么提取能省 token(LLM 上下文减少 + 脚本可缓存)
4. **原则 ④** §1 决策框架 + §2 DF-M4 + §3 独立性硬规则:**为什么必须提取**(LLM 做这事会出错 / 不必要) + **提取后必须满足什么约束**(可独立 / 6 规则)

四份原则缺一不可,但**原则 ④ 是"为什么"的内核**——前 3 份都在讲"怎么做",原则 ④ 讲"为什么这样做是对的"。

---

## 10. 实战 cheat sheet(可贴到 plan mode plan 草稿)

```markdown
## 极致代码化检查(本步骤如涉及代码/脚本,必跑)

□ SKILL.md 是否内联 >10 行 Python/Shell 代码块?
  → 是 → 提取到 scripts/(FD-014)

□ 描述(description)是否含 4 要素(做什么/何时/输入/输出)?
  → 否 → 按 §4 公式重写(FD-015)

□ scripts/ 下的脚本是否依赖 LLM 上下文?
  → 是 → 改为命令行参数(FD-016)

□ 合并/删除 scripts/ 源文件前是否跑了 source 链预检?
  → 否 → 必跑 `grep -rn "source\|if.* -f" scripts/`

□ scripts/<name>.py 是否满足 6 条独立性?
  → 否 → 列出违反的条目,逐条修复
```

---

**版本**:v1.0(2026-07-09)
**维护**:skillx-alpha-agents `docs/` 目录
**反馈渠道**:实战中如发现新的反模式/决策点,补充到 §5 / §1 决策矩阵
