# CoSightBot（CC 插件）

CoSightBot 企业知识助手，**Claude Code 插件**形态：以**个人知识库（PKM，个人知识管理智能体）**为主要能力，同时内置标书应答专家（SOC）。

| 专家模式 | 定位 | 能力 |
|---|---|---|
| PKM 个人知识管理智能体（主能力） | 个人资料检索 | 绑定本地资料目录 → 预处理 + 章节树/section 向量索引构建 → 基于章节树的知识检索问答 |
| SOC 标书智能体 | 标书应答 | 本地构建 SOC 知识库 → 标书 Excel 需求提取 → 批量应答 → LLM 复核 → 回填 |

## 安装

```bash
# 1. 添加本地市场并安装（在仓库根目录执行）
claude plugin marketplace add cosight-bot
claude plugin install cosightbot@cosight-bot

# 2. 首装运行环境（创建双 venv、初始化数据根、生成 .env；幂等可重跑）
python cosight-bot/scripts/install.py

# 3. 编辑数据根下的 .env（embedding 必需；构建链必需 LLM：OPENAI_* 优先）
#    数据根默认 ~/.claude/plugins/data/cosightbot/（可用 COSIGHTBOT_HOME 覆盖）
```

开发调试可用 `claude --plugin-dir cosight-bot` 直接加载本目录。

## 快速上手（个人知识库 PKM）

### 1. 初始化环境

```bash
python cosight-bot/scripts/install.py   # 创建 .venv-pkm、初始化数据根、生成 .env；幂等可重跑
```

编辑数据根下的 `.env`（默认 `~/.claude/plugins/data/cosightbot/.env`，可用 `COSIGHTBOT_HOME` 覆盖）：

- `OPENAI_BASE_URL/_API_KEY/_MODEL`：技能内部 LLM，构建必需（OpenAI chat/completions 兼容协议；未配置时回退继承 CC 会话的 `ANTHROPIC_*`，端点需支持 OpenAI 协议）；
- `COSIGHTBOT_EMBEDDING_API_URL/_KEY`：embedding 端点，动态检索用——不配置时章节树照常生成、章节树检索仍可用，但 section 向量索引记为失败/部分完成，动态 `resolve` 不可用；
- `COSIGHTBOT_RERANK_API_URL/_MODEL`：可选，动态检索强烈建议。

### 2. 绑定资料目录

在 Claude Code 会话里说或用命令：

```
/cosightbot:pkm 绑定 /path/to/你的资料目录
```

绑定成功后**自动首次构建**（产出章节树 `overview.md` 与 section 级向量索引）。大目录首次构建需数分钟，插件会转后台执行并汇报进度；日常加文件（「把 xx 加入知识库」）、删文件、资料有更新（「同步一下」）都是一句话完成，操作即自动增量构建，无需手动跑构建命令。

### 3. 问问题

```
/cosightbot:pkm 帮我查一下 xx 项目的验收结论
/cosightbot:retrieve xx 的操作步骤是什么
```

也可以直接自然语言提问（如「用个人知识管理智能体查一下……」），插件会自动接管并按检索纪律执行。

### 检索流程（插件内部自动完成的三步法）

1. **拿章节树**：小库直接读全量章节树 `merged_overview`；大库/超阈值自动走 `resolve` 动态概览（section 向量 + 全文混合召回，返回 Tier 1/2 候选池）；
2. **读全文**：按候选节点 `[F###]` 逐篇 `read-doc` 实读原文（含图片实读），结论只来自实读，不凭标题或记忆作答；
3. **综合答案**：事实与推断分层、字段术语逐字、冲突文档按证据采信，末尾披露候选池规模与未读情况，保证答案可溯源。

用户只需关心第 1～3 步的提问，检索纪律由插件自动遵守。

## 使用

**命令触发**：

- `/cosightbot:pkm <事务>`：进入个人知识管理模式（绑定资料目录、构建索引、检索问答）；
- `/cosightbot:soc <事务>`：进入标书专家模式（知识库构建、需求提取、应答复核回填）；
- `/cosightbot:retrieve <问题>`：直接对已绑定资料做一次检索问答；
- `/cosightbot:soc-pipeline <标书Excel>`：执行标书应答全流水线（extract → respond → review → fill）。

**自然语言触发**：直接说「使用个人知识管理智能体帮我查一下 xx」「使用标书智能体完成这份标书的应答」等，插件内 `pkm-expert` / `soc-expert` 技能会自动接管并按对应专家纪律执行。

**技能清单**（也可在自然语言中点名调用）：

| 技能 | 侧 | 用途 |
|---|---|---|
| cosightbot-material | PKM | 资料目录绑定/入库/删除/索引构建 |
| cosightbot-retrieve | PKM | 知识检索三步法（章节树 → 读全文 → 综合答案，纯只读） |
| cosightbot-soc-kb-build | SOC | SOC 知识库注册/构建/状态/删除 |
| cosightbot-soc-extract | SOC | 标书 Excel → 需求条目 JSON（schema 自检） |
| cosightbot-soc-respond | SOC | 批量应答（向量匹配历史范式） |
| cosightbot-soc-review | SOC | 应答结果 LLM 复核（冲突标记，失败率 >30% 终止） |
| cosightbot-soc-fill | SOC | 应答回填 Excel（另存 `-应答后.xlsx`） |
| cosightbot-soc-answer | SOC | 单项需求深度应答（FC/PC/NC + 全量引文溯源） |
| cosightbot-soc-analyze | SOC | 标书整本通读分析（8 段结构化报告） |

## 目录结构

```
cosight-bot/
├── .claude-plugin/plugin.json   # 插件清单
├── commands/                    # /cosightbot:pkm|soc|retrieve|soc-pipeline
├── skills/                      # 11 个技能（9 个功能技能 + 2 个专家模式入口）
├── rules/                       # 判定规则（pkm/ soc/ 两套，被 SKILL.md 与命令引用）
├── runtime/
│   ├── pkm/                     # PKM 内核（common + watch_dog + requirements.txt）
│   └── soc/                     # 标书内核（common + watch_dog + requirements.txt）
├── scripts/
│   ├── install.py               # 首装（双 venv + 数据根 + .env + stamp）
│   ├── .env.template            # 统一环境变量模板
│   ├── smoke_test_pkm.py     # PKM 链回归冒烟
│   └── smoke_test_soc.py        # SOC 链回归冒烟
├── knowledge/                   # SOC 示例知识库与演示标书
├── docs/                        # SOC 知识库格式等文档
├── evaluation/                  # 验收用例与联调记录（pkm/ soc/）
└── README.md
```

## 运行数据与配置

- **数据根**：`COSIGHTBOT_HOME` 环境变量 > `CLAUDE_PLUGIN_DATA`（CC 插件数据目录）> `~/.claude/plugins/data/cosightbot`（默认）。PKM 与 SOC 共用一个数据根，`workspace-main/`（资料索引）与 `workspace-soc/`（标书知识库）互不干扰。
- **venv**：数据根下 `.venv-pkm/` 与 `.venv-soc/` 两套独立虚拟环境（依赖相互隔离）；技能 CLI 启动时自动重入，对用户透明。
- **配置**：数据根下唯一 `.env`（模板 `scripts/.env.template`）。首次使用时构建资料索引和 SOC 知识库即可（embedding 模型不变时 SOC 知识库可用 `--force` 快速重建）。

```
<数据根>/
├── .env                                   # 唯一配置文件
├── .venv-pkm/ .venv-soc/               # 两侧独立虚拟环境
├── .install-stamp-pkm/ -soc            # 依赖漂移检测 stamp
├── workspace-main/llamaindex_data/        # PKM：pre-processed/ lancedb/ inbox/ upload_files/
├── workspace-soc/                         # SOC：kbs/<kb_id>/ soc_kb_registry.json builder/
├── canvas/deep-search/                    # SOC：应答引文与 markdown 产物
└── logs/
```

## 环境变量

统一见 `scripts/.env.template`（与两侧原 `.env.template` 合并，变量集一致）：

- `COSIGHTBOT_EMBEDDING_API_URL/_KEY/_MODEL`：**必需**（SOC 构建检索必需；PKM 动态概览必需），OpenAI `/v1/embeddings` 兼容端点；
- `COSIGHTBOT_RERANK_API_URL/_MODEL`：PKM 动态检索强烈建议，SOC 可选；
- `OPENAI_BASE_URL/_API_KEY/_MODEL`：技能内部 LLM（OpenAI chat/completions 兼容协议），构建链必需；未配置时回退继承 CC 会话的 `ANTHROPIC_*`（端点需支持 OpenAI 协议）；
- `SSL_CERT_FILE`：install.py 自动探测写入；
- `COSIGHTBOT_M1_MODEL`（可选 `COSIGHTBOT_M1_BASE_URL/_API_KEY/_WORKERS/_TIMEOUT_S`）：构建期 M1 文档角色先验——弱标题文档由 OpenAI 兼容小模型（单篇一请求）分类，端点与密钥缺省复用 `OPENAI_*`，不设模型名则跳过 M1（静态标题规则仍生效）；
- `COSIGHTBOT_JEV_ENABLED / COSIGHTBOT_JEV_INTERNAL_ENDPOINTS / COSIGHTBOT_JEV_INTERNAL_MODEL`：开启私有化 JEV 五节点（`E1,E2,A1,A2,A3`）检索导航与出口核验；默认 `internal` 直连且绝不自动回退公网端点（评测可显式设 `COSIGHTBOT_JEV_CHANNEL=external` 切换备选通道）；
- 其余（视觉模型、超时重试、动态概览调优等）见模板内注释。

## 回归验证

```bash
python scripts/smoke_test_pkm.py --offline   # PKM 链静态与闸门用例
python scripts/smoke_test_soc.py --offline      # SOC 链静态与闸门用例（主进程需 openpyxl，
                                                #  首次运行会自动首装并用 venv 解释器重入）
claude plugin validate cosightbot               # 插件清单校验
```

冒烟脚本会在临时 HOME 里真实执行 `scripts/install.py`（创建双 venv + pip 安装）；首次运行需下载依赖，耗时会明显长于后续运行（pip 缓存生效后变快）。
