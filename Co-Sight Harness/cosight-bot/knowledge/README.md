# knowledge/ —— 示例数据

本目录附带**虚构产品（Acme）**的示例数据，用于 5 分钟跑通标书应答全链路：

| 路径 | 用途 |
|------|------|
| `sample-kb/` | 示例知识库源目录（布局见 `docs/soc-kb-format.md`）：`01_Specs_PD/` 三份产品文档 + `02_Historical_Responses/` 历史应答 xlsx |
| `sample-tender.xlsx` | 演示标书（6 条技术需求 + 2 条商务需求），供通读分析（cosightbot-soc-analyze）与提取/应答/回填流水线演示 |

## 快速上手

```bash
# 1. 注册并构建示例知识库
python .claude/skills/cosightbot-soc-kb-build/scripts/kb_cli.py add-builtin \
  --kb-id sample --name "Acme 示例知识库" --source-dir knowledge/sample-kb
python .claude/skills/cosightbot-soc-kb-build/scripts/kb_cli.py build sample

# 2. 单条需求深度应答
python .claude/skills/cosightbot-soc-answer/scripts/respond.py "路由器须支持 Wi-Fi 6"

# 3. 标书通读分析
python .claude/skills/cosightbot-soc-analyze/scripts/analyze.py "$PWD/knowledge/sample-tender.xlsx"
```

> 注意：示例数据为开源演示而虚构，与任何真实厂商/产品无关。
