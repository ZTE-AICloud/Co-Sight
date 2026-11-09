# Harness 接入联调记录（CoSightBot SOC）

- 日期：2026-10-10
- 机制：Cosight Harness「目录即专家」——每个专家是一个自包含工作目录，`cd` 进入该目录启动 Claude Code 即可使用；无需插件安装/注册步骤。
- 结论：**通过**——目录自包含性、技能发现、首装链路、数据落位均已验证。

## 一、联调验证点

| # | 验证点 | 验证方式 | 结果 |
|---|--------|---------|------|
| H-01 | 主 Spec 自动加载 | 目录根 `CLAUDE.md`（身份边界/安全约束表/工具策略/数据布局）随会话自动注入 | ✅ |
| H-02 | 技能自动发现 | `.claude/skills/cosightbot-soc-*/SKILL.md` × 7（kb-build / extract / respond / review / fill / answer / analyze） | ✅ |
| H-03 | 权威规则外置 | `.claude/rules/safety-constraints.md` 被主 Spec 与技能引用 | ✅ |
| H-04 | 首装 preflight 链路 | 技能脚本 bootstrap：未装依赖时 `exit 3` + `{"hint": "please_run_install"}`；`python scripts/install.py` 幂等补齐（.venv + data/.env 模板 + .install-stamp） | ✅ |
| H-05 | 数据落位工作目录 | 全部运行数据在 `./data/`（workspace-soc / canvas / logs）；`data/` 已 gitignore（含 `.env` API key） | ✅ |
| H-06 | 非交互可代理执行 | install.py 无 stdin 交互；技能 CLI 输出结构化 JSON，退出码语义明确（0 成功 / 1 失败 / 3 请首装） | ✅ |

## 二、端到端冒烟（本目录内实跑）

- 标书链：`add-builtin` → `build`（2 common + 1 historical，0 失败）→`extract`（8 条需求 / 2 sheet）→ `respond`（历史范式命中）→`review`（误报"量子加密"正确判冲突）→ `fill`（8 列新增 + 冲突标红，原件未覆盖）→ validate 双闸门 exit 0
- 独立工具：`soc-answer`（FC 0.95，file:// 引文落 `data/canvas/`）、`soc-analyze`（8 章节报告齐全）
- 复测：respond 未命中条目不再默认 FC （compliance 留空 + 显式人工应答标记），fill validate 未命中清单/重复行/冲突空值/缺合规列四闸门正负例实测通过。
- 2026-10-10 全新环境实测（git 导出纯净副本，不含 data/.env/.venv）：安装链（预检 exit 3 → install 幂等 → requirements 漂移检测）、标书链 13 例（review 正确识别 3 条检索伪命中并标冲突）、负例闸门 5 例（非法 compliance / 空 items / 覆盖原件 / 未命中误标 FC / 无 embedding 硬失败）全绿。该流程已沉淀为可重复回归脚本`scripts/smoke_test.py`（任一断言失败退出码 1；`--offline` 跳过 LLM/embedding 用例）。

## 三、接入步骤（用户视角）

```bash
cd cosightbot-soc       # 目录即专家
claude                  # 启动 Claude Code，主 Spec 与技能自动生效
# 首次使用任一技能时，脚本 exit 3 → 按提示执行：
python scripts/install.py
# 然后由 Claude 引导填写 data/.env（Embedding + LLM，二者可同服务）
```

## 四、已知限制

- 联调环境走自建 LLM 代理（OPENAI_* 回退），用户按 README 环境变量表配置公网/自有服务即可；
- shell 级 `all_proxy=socks://...` 会使 httpx 报 "Unknown scheme for proxy URL"，公开环境用户按 README 指引安装 `httpx[socks]`；
- 会话继承的 `ANTHROPIC_BASE_URL` 若指向仅支持 Anthropic 协议的端点，构建/复核链（OpenAI chat/completions 协议）会 404——需在 `data/.env` 配置 OpenAI 兼容的 `OPENAI_*`（主配置，优先于会话继承）；
- 相似度未命中阈值 0.45 面向真实规模知识库标定；小体量示例库上相似度地板偏高，未命中路径主要靠 review 复核兜底（实测有效）。
