---
name: cosightbot-soc-answer
description: >
  单条标书需求的深度应答：同时检索产品规范与历史范式，调用大模型做语义融合、
  合规判定（FC/PC/NC）与多文档冲突检测，产出带全量引文溯源的 Markdown 应答。
  在用户说"应答/答复/解答 某条需求"、或直接抛出一个标书条款问题时触发（默认路径）；
  仅当用户明确说"搜索/检索/查一下"时才走普通检索而非本技能。
---

# cosightbot-soc-answer —— 单项需求深度应答器

## When to Activate

- 用户说"应答 / 答复 / 解答"某个需求、条款或问题（即使内容读起来像普通问题，只要动词是应答类就走本技能）
- 用户没明说动词、直接抛出一个标书条款问题时，也默认走本技能
- 需要追溯产品原始规范、或怀疑历史应答与当前规范有出入时

**Not for**：批量应答需求 JSON（→ cosightbot-soc-respond）；标书整体通读分析（→ cosightbot-soc-analyze）；个人资料检索（由本插件的个人知识管理智能体 pkm-expert / cosightbot-material / cosightbot-retrieve 承担）。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-answer/scripts/respond.py "<待应答的单条需求文本>"

# 用户明确限定产品范围时（如"在 某产品 里面应答 xxx"）：
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-soc-answer/scripts/respond.py "<需求文本>" \
    --product-scope "<产品名或分类路径>"
```

- `--product-scope`（可选）：**仅当用户明确要求限定产品范围时传入**；范围词匹配知识库产品分类表（taxonomy），匹配不到自动回退全局检索。用户没限定时**严禁**根据需求正文自行猜测传入。

## 行为契约

- **检索双源**：同时召回产品规范（top 10，BGE 重排后 +0.15 加成）与历史范式（top 5），LLM 综合判定而非只看历史。
- **合规判定**：输出 FC / PC / NC 三枚举之一 + 置信度；检测到多文档冲突时强制 PC 并输出冲突清单（优先采用更新时间较新的文档）。
- **引用全量化**：末尾「📚 参考文档」列出**所有**参考条目（文档标题、章节、时间、链接），严禁只展示"最佳匹配"。
- **引文链接**：全部为 `file://` 本地文件 URL，指向`数据根/canvas/deep-search/soc/<msg_sn>/` 下的引文/合并文件；完整应答同时落盘`output.md`，长答案被上下文截断时引导用户查看该文件。
- **未命中**：如实输出"未命中知识库"（合规 N/A），**禁止**用 LLM 自身知识编造应答。
- **知识库未就绪 / LLM 未配置 / embedding 失败 → exit 1**，不产出任何占位应答。

## 环境自检（preflight）

脚本返回 **exit 3** + `{"hint": "please_run_install", ...}` 时：执行`python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`，并按 `数据根目录下的 .env` 引导配置 embedding + LLM （本技能两者都必需）。**不得绕过**（S-05）。

## 执行方式与汇报

- 单次应答通常 30 秒~2 分钟（两次 LLM 调用：合规判定 + 详细合成）；直接前台执行即可，超过预期时改后台。
- 汇报时**原样保留**脚本输出的 4 个强制段（冲突提示 / 应答判定 / 详细分析 /参考文档列表），引文标注 `[参考文档 M](url)` 不得丢失。

## 检查清单

- [ ] 调用前按 `"${CLAUDE_PLUGIN_ROOT}"/rules/soc/response-orchestration.md` 完成多轮指代补全（能补全不反问；已完整不展开）；≥3 项独立子需求已走拆条工作流并发调用
- [ ] 无 --product-scope 时未自行猜测产品范围
- [ ] 输出保留了全部参考文档条目与引文链接
- [ ] 未命中时如实反馈，未编造应答，未使用"行业通行做法/主流厂商普遍支持"类措辞
- [ ] preflight 失败时执行了 install.py 而非绕过
