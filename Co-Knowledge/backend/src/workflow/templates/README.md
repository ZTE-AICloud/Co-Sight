# 默认画布模板

建流时由 `template_loader.build_default_canvas()` 读取这里的 JSON，把内容写进
`flow_config` 草稿 —— 新建的工作流一打开画布就有四段算子（预检索 / 检索 / 后检索 /
响应合成）以及它们之间的连线，而不是只有「开始」「结束」两个孤点。

## 模板清单

| 文件 | 用于 |
|---|---|
| `{zh,en}_Sequential.json` | 顺序检索 |
| `{zh,en}_Blended.json` | 混合检索（多路并行 → 融合） |
| `{zh,en}_Conditional.json` | 条件检索（按条件分支） |
| `{zh,en}_Blended_graph.json` | 混合检索，只绑定图谱库 |
| `{zh,en}_Blended_normal_graph.json` | 混合检索，普通库 + 图谱库 |

建流弹窗只提供三个基础选项（顺序 / 混合 / 条件）；图谱变体由服务端按绑定的知识库
自动选择：只绑图谱库 → `Blended_graph`，普通库 + 图谱库 → `Blended_normal_graph`。

## 节点里的两份 `variables` 必须完全相同

画布节点把算子存了两遍，读写的角色不同：

| 副本 | 谁读 | 谁写 |
|---|---|---|
| `variables` | 服务端：`template_loader` 播种、translator、`canvas` 校验、发布快照 | 播种；前端保存时按下面那份回写 |
| `data.variables` | 画布前端：节点组件取值显示 | 前端算子抽屉改完的值；`exportGraph()` 保存时以它为源回写顶层 |

两份不一致 = 「画布上看到的」与「真正跑的」不是一回事，而且用户点一次保存就会把播种
结果冲掉。两道防线：

- 模板里两份完全相同（`test_template_keeps_both_variable_copies_identical`）；
- 播种时两份都填（`template_loader._variable_copies` + `test_build_fills_both_variable_copies`）。

改了模板之后建议跑一遍 `tools/verify/verify-workflow-templates.py` —— 它会把
「打开画布 → 保存」这一轮按前端的口径重放一次。

## 改模板时的约定

- `templates/*.json` 是**数据**，`template_loader.py` 只读不解释结构
  （节点 UUID、连线都由 JSON 自述）。
- `nodeConfigDTOList[].nodeId` 与 `otherNodeConfigList` 中 `componentType=EDGES`
  的 `variables.edges[].source/target` 之间的引用必须自洽 —— 前端 `importGraph`
  按 `outputVariables[].targetNode` 重建连线，指向不存在的节点会画不出线。
- 检索器的 `kwargs.embedding` 留空，播种时按绑定知识库实际的 `embeddingModel` 回填；
  混选不同向量模型的库会被硬拒。
