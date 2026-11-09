# Brief 工序模板 — workflow_md（运行时步骤编排，落 phase/02-workflows/）

> 槽位原料: matching-decision v2（结构决策 + 决策物化）+ clarified-agent-requirements.yaml

## 生成工序（4 步）

1. **步骤序列**: Step ID 连续；每步 输入→输出→depends_on（DT1 物化）；并行段标注（S1 触发时）
   【自查】步骤间无断链? 每步产出有消费者?
2. **门禁绑定**: 每步 gate 引用（内置 fallback + 自定义）；失败回退路径
3. **knowledge refs**: 运行时知识只引用产物内路径（.claude/skills、.claude/rules、schemas/ 等），
   禁止引用插件内部路径（产物离开插件后引用必断）
4. **审批节点**（IH3 时）: 触发条件 + 产物 + 通过后去向
   【自查】I/O 闭合 + 无悬空产物 + 降级/恢复路径可客观判定

## 落点规则

`phase/02-workflows/<phase-name>.md`，每个运行时 Phase 一个文件。

## 自样例

build-plan 中每个 phase/02-workflows/ 条目一个 workflow_md。
