# Harness 接入联调记录（CoSightBot PKM）

- 日期：2026-10-10
- 机制：Cosight Harness「目录即专家」——每个专家是一个自包含工作目录，`cd` 进入该目录启动 Claude Code 即可使用；无需插件安装/注册步骤。
- 结论：**通过**——目录自包含性、技能发现、首装链路、数据落位均已验证。

## 一、联调验证点

| # | 验证点 | 验证方式 | 结果 |
|---|--------|---------|------|
| H-01 | 主 Spec 自动加载 | 目录根 `CLAUDE.md`（身份边界/安全约束表/工具策略/数据布局）随会话自动注入 | ✅ |
| H-02 | 技能自动发现 | `.claude/skills/cosightbot-*/SKILL.md` × 2（material / retrieve） | ✅ |
| H-03 | 权威规则外置 | `.claude/rules/safety-constraints.md`、`retrieval-discipline.md` 被主 Spec 与技能引用 | ✅ |
| H-04 | 首装 preflight 链路 | 技能脚本 bootstrap：未装依赖时 `exit 3` + `{"hint": "please_run_install"}`；`python scripts/install.py` 幂等补齐（.venv + data/.env 模板 + .install-stamp） | ✅ |
| H-05 | 数据落位工作目录 | 全部运行数据在 `./data/`（workspace-main / logs）；`data/` 已 gitignore（含 `.env` API key） | ✅ |
| H-06 | 非交互可代理执行 | install.py 无 stdin 交互；技能 CLI 输出结构化 JSON，退出码语义明确（0 成功 / 1 失败 / 3 请首装） | ✅ |
| H-07 | 长任务进度 | 构建进度走 runner 子进程 stdout `[progress]` 行，material_cli 流式透传（Popen 逐行转发），实时落后台任务输出文件（中途可查）；无 daemon/IPC，文件信息由 runner 直接落盘 common.index_api | ✅ |

## 二、端到端冒烟（本目录内实跑）

- PKM 链：绑定资料目录 → 自动首建 → 检索三步法——隔离 `COSIGHTBOT_HOME` 下实测通过（bind 自动触发 common_build、 merged_overview 返回章节树、read-doc/scan 往返正常、未绑定 hint 正确）。进度链（流式透传 + 本地进度对象直写 index_api）与"无 LLM/embedding 配置时构建硬失败（非零退出）"在隔离 home 下重验通过——`[progress]` 行实时流出、`index_status: ready`、 retrieve 主命令 `ready: true` 返回 `[F###]` 章节树。复测：inbox 路由接入 collect_routes （ingest --global 入库 → merged_overview 出现 `## inbox:agent` 章节树， remove --global 后路由消失）；wiki/share/builtin/global 死代码簇整体切除后 force 重建 + status 对账全绿。
- 2026-10-10 全新环境实测（git 导出纯净副本，不含 data/.env/.venv）：安装链（预检 exit 3 → install 幂等 → requirements 漂移检测）、PKM 链 14 例（含会话隔离、降级 inbox、增量漂移重建、unbind 不动原件、纯图片页 PDF 的 OCR 链路）、负例闸门全绿。该流程已沉淀为可重复回归脚本 `scripts/smoke_test.py`（任一断言失败退出码 1；`--offline` 跳过 LLM/embedding 用例）。实测记录另修复：overview 章节树模板与日志文件名中的 daemon 残留措辞（统一为 cosightbot.log）。

## 三、接入步骤（用户视角）

```bash
cd cosightbot-pkm    # 目录即专家
claude                  # 启动 Claude Code，主 Spec 与技能自动生效
# 首次使用任一技能时，脚本 exit 3 → 按提示执行：
python scripts/install.py
# 然后由 Claude 引导填写 data/.env（Embedding + LLM，二者可同服务）
```

## 四、已知限制

- 联调环境走自建 LLM 代理（OPENAI_* 回退），用户按 README 环境变量表配置公网/自有服务即可；
- shell 级 `all_proxy=socks://...` 会使 httpx 报 "Unknown scheme for proxy URL"，公开环境用户按 README 指引安装 `httpx[socks]`；
- 会话继承的 `ANTHROPIC_BASE_URL` 若指向仅支持 Anthropic 协议的端点，构建链（OpenAI chat/completions 协议）会 404——需在 `data/.env` 配置 OpenAI 兼容的 `OPENAI_*`（主配置，优先于会话继承）；
- 模型不在多模态启发式名单时扫描页 OCR 默认跳过（`image-ocr:pending`），确认模型支持图片后在 data/.env 设 `COSIGHTBOT_MODEL_SUPPORTS_IMAGES=1`。
