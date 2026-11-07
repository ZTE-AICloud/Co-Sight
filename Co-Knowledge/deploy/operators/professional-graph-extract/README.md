# 专业知识图谱算子（v1.0.0）

系统算子 `id=-5` 的源码包。按用户提供的 **Schema（知识图谱模板）** 对专业领域
文档做实体与关系抽取，适合领域本体已经定义清楚的场景。

| profile | 说明 |
|---|---|
| 通用知识图谱算子（`-6`） | 不依赖 Schema，直接从文档抽通用图谱 |
| 专业知识图谱算子（`-5`） | 按 `schemaId` 指定的 Schema 抽取，实体/关系受本体约束 |

## 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `schemaId` | str | 空 | 知识图谱模板 id（必填；由平台解析为 Schema 后传入算子） |
| `llm` | str | 空 | 抽取所用的大模型注册名 |
| `chunkSize` | int | 512 | 每片最大字符数 |
| `overlap` | int | 128 | 相邻切片重叠字符数 |

## 打包与播种

运行期由 `operators.bootstrap` 在首次启动时播种到 `operator` 表
（`id=-5`、`system=true`），包体来自
`backend/src/operators/templates/professional-graph-extract.zip`。

改完源码后重新打包，保持两者一致：

```bash
cd deploy/operators/professional-graph-extract
zip -j ../../../backend/src/operators/templates/professional-graph-extract.zip \
  config.json graph_extract.py
```

> 算子依赖 Python 标准库与 `operator_api.*`。ABI v2 的公开导入面是
> `operator_api`；使用 `client.*` 等旧顶层包的算子会在导入阶段收到
> `operator_plugin_incompatible`，按当前模板重新导出即可。
