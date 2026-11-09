# 单目标研究文件格式（fan-out 产物契约）

每个目标一个 markdown 文件, 文件名 `{target-slug}.md`, 由扇出子代理用 heredoc 写入
`{OUTPUT_DIR}/`。汇聚脚本按本格式解析——字段名与段落顺序禁改动。

## 固定字段（文件头）

```yaml
---
slug: <kebab-case>
name: <目标名>
product_description: <原句/转述, 无据则 Unknown>
industry: <未知则 Unknown>
evidence: <支撑 product_description 的原文片段出处>
scores:
  fit_score: <1-5, 证据不足封顶 3>
  fit_reasoning: <一句话理由; 证据不足注明 Insufficient evidence>
---
```

## 固定段落（顺序固定）

1. `## 证据` — 页面抽取字段原文（TITLE/META/HEADINGS/BODY 相关行）, 逐条标注来源 URL。
2. `## 分析` — 基于证据的画像, 禁引入证据外推断。
3. `## 失败记录` — 抽取/访问失败如实记录（无失败则写 `无`）; 汇聚脚本据此统计缺失。

## 禁项

- 禁改字段名/段落名（汇聚按字面解析）。
- 禁在文件内写凭据或环境变量值。
- 禁用 Write 工具写本文件（子代理单 Bash heredoc 批量写）。
