# Brief 工序模板 — skill（Skill 目录，非单文件）★

> 原料: knowledge/skill/skill-creation-guide.yaml（§4 目录决策树 + G1/G2 + SF-6）+
> skills/e2e-test-runner/ 样例（结构最全: scripts/golden-cases/task 三形态）

## 工序 0 — 目录裁决（先裁决，再生成）

按 §4 决策树判定本 skill 需要哪些子目录：
- 有**确定性操作**（格式校验/精确比对/转换/计算）? → `scripts/`（DF-M4: LLM 不做确定性事）
- 有**大块参考知识**（>100 行）? → `references/`（SKILL.md 禁止内联 >100 行参考）
- 有**输入/输出模板**? → `templates/`
- 有**测试用例**? → `golden-cases/`
产物是 `.claude/skills/{name}/` **目录**；build-plan 中附属文件块以 `type: skill` + 路径前缀天然关联（零 schema 变更）。
【自查】每个子目录都有内容归属了吗？确定性内容真的进 scripts 了吗（问三次）？

## 生成工序（按目录裁决结果逐文件）

1. **SKILL.md（L2 入口，最后写但先规划）**: frontmatter(name/description **SF-6**/何时触发) /
   触发条件 / 知识依赖表 / 执行流程；正文引用 references/scripts/templates 的相对路径
   【自查】渐进加载: 无 >100 行内联参考? 引用链闭合（声明的文件都存在）?
2. **scripts/**: CLI 入口契约（参数 + 无副作用模式如 --list/--help）/ 沙箱与路径约束 / 错误退出码；
   禁止静默吞错。【自查】可独立运行（python3 -m py_compile / --help）?
3. **references/**: 知识分块 + 每块头部一句话索引；SKILL.md 显式引用
4. **templates/**: 可复制即用 + 占位符说明
5. **golden-cases/**（如有）: 用例 YAML + suite.yaml

## 落点规则

`.claude/skills/{name}/SKILL.md` + 同目录子结构（上表）。**废止根级 `skills/` 平铺**。

## 自样例

同 build 中首个 skill 生成后，后续 skill 与其保持同构；skill-creation-guide 与 e2e-test-runner 样例已读过可跳过。
