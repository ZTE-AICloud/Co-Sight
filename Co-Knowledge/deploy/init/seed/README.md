# 首条链路验收样本集

本目录是「首条业务链路验收」所需的**最小样本集**，随仓库分发，保证任何 clone 者都能复现
「建库 → 导入 → 切分 → 索引 → 检索」的端到端链路。

> 全部样本为自行撰写，无版权风险。合计约 64 KB。
> 完整启动与最小链路步骤见仓库根目录 [`README.md`](../../../README.md)「快速开始」。

## 文件清单

| 文件 | 格式 | 大小（约） | 覆盖点 |
|---|---|---|---|
| `sample-zh.md` | Markdown | ~3 KB | 标题层级、有序/无序列表、代码块、表格 |
| `sample-zh.pdf` | PDF（3 页） | ~6 KB | PDF 文本层解析样本（E2E `IMP-02b` 跟踪其解析状态） |
| `sample-zh.docx` | DOCX | ~39 KB | 段落、表格 |
| `sample-en.txt` | 纯文本 | ~1.5 KB | 纯段落、中文/ASCII 混排 |
| `sample_operator.zip` | 算子包 | ~1 KB | 自定义算子「上传注册 → 参数系统 → 沙箱执行 → 结果进索引」 |

## 系统算子 -1 上传必填参数

用系统算子（`operatorId=-1`）导入时，`metadata.splitOperator` 的 `args` 必须**逐项显式给出**
`argName` + `argType` + `defaultValue` 三字段，缺任一字段或裸传 `args:[]` 会失败：

```json
"splitOperator": {
  "md": {
    "operatorId": -1,
    "fileFormat": "md",
    "args": [
      {"argName": "maxWordCount", "argType": "int", "defaultValue": 512},
      {"argName": "overlap",      "argType": "int", "defaultValue": 128}
    ]
  }
}
```

- `overlap` 必须小于 `maxWordCount`。
- 默认值真实来源：`backend/src/ingestion/split/operator_all.json`（`operatorId=-1`）。
- `fileFormat` 随文件类型变化：`md`/`pdf`/`docx`/`txt`。

## 自定义算子 `sample_operator.zip`

**扁平结构**（zip 根目录直接放置，勿再套一层目录）：

```
sample_operator.zip
├── config.json      # 算子元数据（display_name/desc/module/version/supportedFormat/...）
└── text_split.py    # 入口函数 file_split(file_path, **args)
```

要点：

- `config.json` 的 `module` 为 `text_split`，`display_name.en` 只含 `[A-Za-z0-9_]`（连字符/标点会被拒）。
- 入口函数签名 `file_split(file_path: str, max_len: int = 200) -> list`；`file_path` 由解析/切分链注入，`max_len` 来自 `defaultArgs`。
- 返回值必须是 JSON 可序列化结构：`[{"content": str, "metadata": {"source", "chunk_index", "split_type"}}]`，
  经 `result_convert` 转为 `ChunkNode`（`contracts/schemas/chunk.json`）。
- 行为：按 `max_len` 定长切分，不丢内容，无空片；`metadata.source` 记录来源文件名。

## 如何跑首链验收

```bash
# 1) 环境：照根 README「快速开始」启动默认 4 容器并确认 healthy
# 2) 创建知识库 demo-kb，取默认目录 id
# 3) 导入样本：先单文件 sample-zh.md，切分方式选系统算子 -1（参数见上）
# 4) 等待导入成功，切片页可见 N 个 chunk
# 5) 触发索引：向量行数 == chunk 行数，维度 == 该库绑定的 embedding 维度
#    （默认 Qwen3-Embedding-0.6B = 1024；启用 local-embedding profile 时为 bge-base-zh-v1.5 = 768）
# 6) 检索：提问「什么是 RAG」等样本中确有其文的问题，应命中样本片段
# 7) 回归：换 sample-zh.docx / sample-en.txt 重跑 ②~⑤；PDF 样本用于解析器调试
```

## 危险算子（沙箱验收用）

为验证沙箱 `code-check` 会拒绝危险代码（如 `import os; os.system(...)`），
可现场构造一份**仅测试用**的恶意算子（本目录**不预置**，避免误上传到生产）：

提交含 `import os; os.system(...)` 的算子，`code-check` 应返回拒绝（`code=0005`，`Custom operator content validation failed.`）。
