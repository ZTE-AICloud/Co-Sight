# 后端配置目录

| 文件 | 用途 |
|---|---|
| `sensitive_words.txt` | 编排合成算子使用的敏感词表：每行一个词，`#` 开头为注释，空白行忽略；空词表表示不做敏感词过滤。 |
| `readme.md` | 本说明。 |

默认路径由 `SENSITIVE_WORDS_FILE` 覆盖（未设置时读取本目录下的
`sensitive_words.txt`），实现见 `src/parsing/sensitive.py`。词表变更后需重启
`rag-knowledge-base` 生效；没有热更新。
