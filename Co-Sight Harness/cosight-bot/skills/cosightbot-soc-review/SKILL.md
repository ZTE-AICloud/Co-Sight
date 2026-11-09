---
name: cosightbot-soc-review
description: >
  标书已应答 JSON 的大模型并发复核：逐条比对客户需求与知识库匹配文本，
  死磕品牌、数值、版本号等关键冲突，判为不符合的条目标记 conflict=true，
  产出 `<stem>-已大模型复核.json`。在用户要求"复核应答结果/检查应答冲突/
  LLM 复核已应答 JSON"时触发。任何纯向量匹配命中的条目，交付前必须经本技能复核。
---

# cosightbot-soc-review —— 大模型并发复核器

## When to Activate

- 用户说"复核应答结果 / 检查一下有没有冲突 / 跑一遍 LLM 复核"
- 位于 SOC 流水线：respond（批量应答）→ **review** → fill（回填）

**Not for**：单条需求深度应答（→ cosightbot-soc-answer）；首次批量应答（→ cosightbot-soc-respond）。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-review/scripts/review.py "<*-已应答.json>" \
    [--req_field requirement] [--matched_field matched_req] \
    [--result_field llm_review_result] [--concurrency 6]
```

- 输入：cosightbot-soc-respond 的产物 `*-已应答.json`。
- 产物：**`<stem>-已大模型复核.json`**（自动剥掉 `-已应答` 后缀），与输入同目录。
- 每条新增 `llm_review_result` 字段；判为不符合的条目强制 `conflict=true` +`review_notes` 警告。

## 关键规则（硬性要求）

- **兜底防线定位**：本技能是纯向量检索（cosightbot-soc-respond）之后的最后一道复核关，专门解决"意境相近但关键实体矛盾"的漏检问题。**任何纯向量匹配命中的条目，最终交付前必须经本技能复核**，不能跳过。
- **一票否决项**：品牌互斥、数值矛盾、版本号不一致、客户明确声明的硬性条款不匹配，一律判为冲突。
- **失败语义**：
  - 单条 LLM 请求失败不阻塞整批（失败信息写入该条 `llm_review_result`）；
  - 真实失败率（LLM/网络/JSON 解析错误）**> 30% → exit 1**（产物仍落盘保留已成功项，但必须如实告知用户整批不可信、排查后重跑）；
  - "需求描述为空 / 未命中知识库" 是合法软跳过，不计入失败率。

## 依赖

- LLM 配置：`数据根目录下的 .env` 中 `OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL`（主配置；未配时回退继承 Claude Code 会话的 `ANTHROPIC_*`），协议为 OpenAI chat/completions 兼容。
- Python 依赖 `aiohttp`（由 "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py 安装）。

## 环境自检（preflight）

脚本返回 **exit 3** + `{"hint": "please_run_install", ...}` 时：执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`。**不得绕过**（S-05）。

## 执行方式与汇报

- 默认 6 并发；条目多时是分钟级任务，后台执行并告知用户。
- 完成后汇报：「复核完成：共 N 条，冲突 M 条（已标 conflict），产物`<stem>-已大模型复核.json`」；有冲突项时列出冲突条目的编号与原因，提示用户人工定夺后再回填（cosightbot-soc-fill）。

## 检查清单

- [ ] 输入是 `*-已应答.json`（含 matched_req 字段）
- [ ] 冲突条目已标 conflict=true 且汇报给用户
- [ ] 失败率 >30% 时如实报告不可信而非声称完成
- [ ] preflight 失败时执行了 install.py 而非绕过
