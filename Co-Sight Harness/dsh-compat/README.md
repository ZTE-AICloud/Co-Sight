# 把五个插件装进 DeepSeek Harness（dsh）

[简体中文](README.md) · [English](README.en.md)

一条命令装好 `drive`、`agent-genesis`、`agent-evaluator`（goldeval）、`skill-optimizer`、
`cosight-bot`（CoSightBot）。四个 Claude 插件的源码一行不改，由兼容层
`cosight-plugin-compat` 挂到 dsh 原生表面上；`drive` 由它自带的 `drive-compat` 挂载。

| bundle | 承载插件 |
|---|---|
| `drive-compat` | drive |
| `cosight-plugin-compat` | agent-genesis、agent-evaluator、skill-optimizer、cosight-bot |

实测规模：技能 25、命令 10、agent 角色 28、钩子规则 1；装好后 dsh 运行时技能总数 52
（本包 35 + drive 17），启动无报错。源码安装与 `--pkg` 发布包安装都验证过。

---

## 1. 前置条件与安装

**前置条件**

- 一个**已经能跑起来**的 dsh：已发布的 CLI，或一份源码 checkout（源码模式下脚本用
  `node --import tsx/esm apps/cli/src/bin.ts` 启动它，所以那份 checkout 要装过依赖）。
- **bash**：`install-dsh.sh` 是 bash 脚本（Linux / macOS 直接用；Windows 走 WSL 或 Git Bash）。
- `drive` 目录（默认取脚本同级的 `drive/`），除非加 `--no-drive`。
- 安装器会调用 `dsh plugin add`，所以 `dsh` 命令（或 `--dsh "pnpm dsh"`）要能在 PATH 上找到。

**安装**。以下命令都在**仓库根目录**（`dsh-compat/` 的上一级）执行。
`DSH_SOURCE_DIR` 是你的 dsh 源码 checkout，按实际位置设置；不设时脚本会自动探测。

```bash
export DSH_SOURCE_DIR="$HOME/Co-sight Harness"   # 换成你的 dsh 源码目录

# ① 安装 + 自检（幂等，可重复执行）
bash install-dsh.sh --verify

# ② 重启 dsh（bundle 成员只在启动时读取）
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

安装器只动两处：向 profile 的 `cordis.patch.yml` 写入一个带时间戳备份的标记块，
再用 `dsh plugin add` 登记两个 bundle；已存在则跳过，所以重复执行安全。
想先看它会做什么而不落盘，用 `bash install-dsh.sh --dry-run`。

启动日志应出现：

```text
cosight-plugin-compat: mounted 35 skills/commands (25 skills, 10 commands, 0 failed, 0 skipped)
cosight-plugin-compat: agent roles=28, shims registered=[Task], skipped=[]
cosight-plugin-compat: 1 PreToolUse hook rule(s) active: agent-genesis[Write|Edit]
```

## 2. 启动（前端与后端）

dsh 是**单进程应用**：同一个端口既提供后端 API，也提供前端页面（默认 `3080`）。
兼容层**不是**独立服务，没有自己的前端/后端进程——它在 dsh 启动时被加载进那个进程，
把技能、命令、角色、钩子注册到 dsh 的运行时上。所以这里没有"分别启动前后端"这一步，
只有"用哪种方式启动 dsh"。

**源码 checkout**（开发或本机调试）：

```bash
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

**已发布的 dsh CLI**：

```bash
dsh web --no-open --port 3080
# 装进别的 profile：dsh --profile mylab web --no-open --port 3080
```

**临时叠加、不安装**（改完兼容层源码想立刻验证时）：

```bash
bash install-dsh.sh --dev-patch      # 打印一条带 --patch 的启动命令，照着跑
```

打开 <http://127.0.0.1:3080/> 即可。按 **Ctrl-C** 停止。

**装完必须重启 dsh**：bundle 成员与配置块都只在启动时读取，重启前界面不会有任何变化。

## 3. 配置说明

**兼容层配置**（profile 的 patch 里 `cosight-plugin-compat` 的 `config`，一般不用改）：

| 键 | 默认 | 说明 |
|---|---|---|
| `pluginsRoot` | 自动推断 | 四个插件所在的父目录；`AUTO` = 用包内 `plugin-assets/` |
| `plugins` | 全部 | 只挂载指定子集（目录名数组） |
| `skills` / `shims` / `hooks` | `true` | 分别控制技能、agent 工具、钩子层 |
| `extraShims` | `false` | 额外注册 `Agent`/`TodoWrite`/`AskUserQuestion`（与 drive 共存时**不要**打开，会工具重名） |
| `hookTimeoutMs` | `60000` | 钩子超时上限（毫秒） |

`pluginsRoot` 解析顺序：`config.pluginsRoot` → 环境变量 `COSIGHT_COMPAT_PLUGINS_ROOT`
→ 包内 `plugin-assets/` → 开发布局（仓库根）。

**安装器读取的环境变量**：

| 变量 | 用途 |
|---|---|
| `PROFILE` | 装进哪个 dsh profile，等价于 `--profile`（默认 `web`） |
| `DSH_SOURCE_DIR` | dsh 源码目录；设置后按源码模式启动 |
| `DSH_HOME` | dsh 的配置根（profile 都在它下面），一般不用设 |
| `COSIGHT_COMPAT_PLUGINS_ROOT` | 四个插件的父目录，等价于 `--plugins-root` |

**常用命令行选项**见第 6 节；完整列表用 `bash install-dsh.sh --help`。

## 4. 确认装好了

```bash
# bundle 登记（期望含 drive-compat、cosight-plugin-compat）
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.dsh/profiles/web/package.json')))['dsh']['profile']['bundles'])"

# 组合后的配置（权威检查，不用重启；期望两个 id 各带一行入口文件）
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --dump-config) | grep -E "drive-compat|cosight-plugin-compat"

# 离线验收（不依赖 dsh；期望 23/23 checks passed）
node dsh-compat/acceptance/probe.mjs | tail -1
```

界面里（<http://127.0.0.1:3080/>）再点三下：

- 输入 `/selftest` 能进入 → 命令类挂载成功；
- 技能列表搜 `goldeval-e2e-test-runner` → 技能挂载成功（含重名改名）；
- 让模型「用 debug-pro 看一下」→ 角色入口（`Task`）成功。

## 5. 卸载

```bash
bash install-dsh.sh --uninstall      # 同样在仓库根目录执行
```

然后重启 dsh。确认已清干净：

```bash
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.dsh/profiles/web/package.json')))['dsh']['profile']['bundles'])"
# 期望只剩 ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app']
```

## 6. 常用变体

| 场景 | 命令 |
|---|---|
| 先看会做什么，不落盘 | `bash install-dsh.sh --dry-run` |
| 只装四个 Claude 插件（不装 drive） | `bash install-dsh.sh --no-drive` |
| 目标机器没有本仓库，用发布包 | `bash install-dsh.sh --pkg dsh-compat/dist/cosight-dsh-plugins-0.1.0-dsh.0.tgz` |
| 装到别的 profile | `bash install-dsh.sh --profile mylab` |
| 不安装，临时叠加启动 | `bash install-dsh.sh --dev-patch`（打印带 `--patch` 的启动命令） |
| dsh 不在 PATH 上 | `bash install-dsh.sh --dsh "pnpm dsh"` |

## 7. 出问题先看这里

| 现象 | 处理 |
|---|---|
| 装完界面没变化 | 没重启；bundle 只在启动时读取 |
| 启动报工具重名（`duplicateError`） | 与 drive 共存时保持默认（只注册 `Task`），不要开 `extraShims` |
| 日志 `no plugin payload found` | `pluginsRoot` 指错；源码安装指向仓库根，发布包用 `AUTO` |
| 想彻底回退 | `bash install-dsh.sh --uninstall` 后重启 |

## 8. 能力边界（诚实清单）

映射不是逐字节等价，以下差异是设计上的取舍，不会静默假装：

- **`allowed-tools` 只作提示**：dsh 没有按命令收窄工具权限的机制，权限由 dsh 自己的策略决定。
- **`run_in_background` 一律等待**：dsh 子代理调用是同步语义。
- **技能正文里的 `${CLAUDE_PROJECT_DIR}` 不展开**（挂载时没有会话目录）；钩子命令里会展开。
  `${CLAUDE_PLUGIN_ROOT}`、`${PLUGIN_ROOT}`、`${CLAUDE_SKILL_DIR}` 在挂载时替换为绝对路径。
- **agent-evaluator 里调用 `claude -p` 的步骤**需要本机有 `claude` CLI，缺了就失败，不做替换。
- **skill-optimizer 里对 `/media/vdb` 等本机路径的假设**不会被改写，换机器需按实际路径配置。
- **`/name` 由用户手动输入**，模型不会自动选择命令类技能（这是 Claude 命令语义的忠实映射）。
- **角色入口是 `Task`**（与 drive 共存时）：模型按名字选角色，不是 Claude 的 `subagent_type` 调度。

## 9. 它是怎么挂上去的

| Claude Code 资源 | dsh 落地 | 触发方式 |
|---|---|---|
| `skills/*/SKILL.md` | `ctx.skills.register`，模型与用户都可调用 | 模型自动选，或 `/name` |
| `commands/*.md` | 同一注册表，仅用户可调用 | 只能输入 `/name` |
| `agents/*.md` | `Task` 工具，角色 Markdown 原文前置到 spawn 提示 | 任务里写角色名 |
| `hooks/hooks.json` 的 `PreToolUse` | `ctx.on('tools/pre-execute')` | dsh 工具调用前 |

命名规则：下划线转连字符（`skill_create` → `/skill-create`）；中文名走别名表
（`编码原则` → `coding-principles`）；重名先到先得，后来者加前缀
（agent-evaluator 的 `e2e-test-runner` → `goldeval-e2e-test-runner`）。

## 10. 开发者：验收与打包

```bash
bash dsh-compat/acceptance/run-all.sh     # 语法检查 + 23 项离线探针
bash dsh-compat/pack.sh                   # 生成自包含发布包到 dsh-compat/dist/
```

探针不需要 dsh，用桩 `ctx` 驱动全部模块，并**真实执行** agent-genesis 的守卫脚本，
验证「插件目录内写入被拒、外部写入放行」以及钩子退出码到 deny/ask/allow 的映射。
