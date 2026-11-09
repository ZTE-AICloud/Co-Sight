# 快速开始

[简体中文](QUICKSTART.md) · [English](QUICKSTART.en.md) · [← 返回 README](README.md)

这份文档只讲**怎么把它跑起来**：敲什么、看到什么算成功、不对时先查哪里。
为什么这样设计，见 [`framework/docs/`](framework/docs/) 与各组件 README；
产物安装的完整验收清单见 [`framework/docs/user-guide.md`](framework/docs/user-guide.md)。

```text
分发包：解压 → install（检查 + 装插件）→ start（起框架与模块）→ 打开 127.0.0.1:4300
源码态：clone → pnpm install → pnpm dev（框架）/ pnpm dev:all（连模块）→ 打开 localhost:4310
```

---

## 0. 选一条路径

| 你的情况 | 从哪一节开始 | 需要什么 |
|:---|:---|:---|
| 拿到 `cosight-harness-*.tar.gz` / `.zip`，想直接跑 | [路径 A](#2-路径-a使用分发包) | Node.js（Claude Code、Python 3 可选） |
| 要做二次开发、改代码 | [路径 B](#3-路径-b从源码启动) | Node.js + pnpm + 各模块依赖 |
| 要把产物打出来交给别人 | [8. 出包](#8-出包) | 同路径 B |
| 只想把五个插件装进 DeepSeek Harness | [7. 可选](#7-可选的-claude-code-插件与-dsh) | 一个能跑的 dsh |

---

## 1. 前置条件

| 项 | 要求 | 怎么确认 | 不满足时 |
|:---|:---|:---|:---|
| **Node.js** | `^22.19.0` 或 `>=24.0.0` | `node -v` | 安装/启动自检直接失败，退出码 **10** |
| **pnpm** | `11.28.5`（仅源码开发） | `corepack enable && pnpm -v` | 源码路径装不了依赖 |
| **Claude Code** | CLI `>= 2.1.287`（装插件用） | `claude --version` | 退出码 **10**；不想装可 `--skip-plugins` |
| **Python 3** | PATH 上有 `python3` | `python3 --version` | 退出码 **10**；插件 hooks 与 cosight-bot 需要 |
| **平台** | Linux x64 / Windows x64 | — | 预检阶段失败 |
| **磁盘** | 数据目录所在盘 ≥ 512 MB | `df -h` | 只告警，不阻塞 |

> 分发包**不需要 pnpm、不需要联网、不需要管理员权限**。需要 pnpm 的只有「出包」那台机器。

---

## 2. 路径 A：使用分发包

### 2.1 解压

```bash
tar -xzf cosight-harness-*.tar.gz
cd cosight-harness-*/
```

Windows：右键压缩包 →「全部解压缩」（或 7-Zip）。`tar.gz` 与 `zip` 内容等价，
解压后没有符号链接，Windows 自带解压器也能正确还原。

### 2.2 自检（推荐，只读）

```bash
node start.mjs --self-check
```

逐项打印 `[OK]` / `[WARN]` / `[FAIL]` 并给出结论。**有 `[FAIL]` 就先处理，别急着安装**——
这一步不写任何文件，可以反复跑。

### 2.3 安装

```bash
./install.sh
```

Windows：双击 `install.cmd`。

安装脚本按顺序做四件事，**重复执行是安全的（幂等）**：

1. **前置检查**（只读）：平台、Node、Claude Code 版本、配置目录可写、Python 3、载荷完整；
   任一阻塞项失败会打印「检查项 / 原因 / 处理 / 影响」，退出码 **10**，一个文件都不写。
2. **建数据目录**：默认 `~/.cosight-harness`，可用 `--home <目录>` 指定。
3. **生成配置**：从模板生成 `cosight.env`，已有配置不会被覆盖。
4. **装五个 Claude Code 插件**（`user` scope）：`drive`、`agent-genesis`、`goldeval`、
   `skill-optimizer`、`cosightbot`。失败退出码 **12**，会打印失败的插件与 CLI 原始报错。

常用参数：

```bash
./install.sh --home /srv/cosight-harness   # 指定数据目录
./install.sh --skip-plugins                # 不装插件（依赖插件的能力将不可用）
```

### 2.4 启动

```bash
./start.sh
```

Windows：双击 `start.cmd`。

启动脚本会拉起框架与全部模块，**逐个探活**；任一起不来，已起的进程按逆序停掉，
避免留下半套服务。端口被占、模块没起来等启动期失败退出码 **13**。

```bash
./start.sh --port 8080 --home /var/lib/cosight   # 换端口 / 换数据目录
./start.sh --no-modules                          # 只起框架
./start.sh --help                                # 全部参数
```

### 2.5 打开并验证

浏览器打开 <http://127.0.0.1:4300>。命令行验证：

```bash
curl -s http://127.0.0.1:4300/api/health     # {"status":"ok", ...}
curl -s http://127.0.0.1:4300/api/modules    # 已注册模块与可达状态
```

| 地址 | 内容 |
|:---|:---|
| `127.0.0.1:4300` | 框架首页（默认监听 `0.0.0.0`，本机访问用回环） |
| `/api/health` | 健康检查 |
| `/api/docs` | 接口文档 |
| `/api/modules` | 模块注册与可达状态 |

### 2.6 停止

在前台按 **Ctrl-C**：按启动的逆序停掉所有进程，端口自动释放
（`ss -ltn | grep -E ':(4300|4830|4100|4110)'` 应无输出）。

---

## 3. 路径 B：从源码启动

### 3.1 拉代码装依赖

```bash
git clone https://github.com/ZTE-AICloud/Co-Sight.git
cd "Co-Sight/Co-Sight Harness"
corepack enable      # 只需一次：按 packageManager 对齐 pnpm 版本
pnpm install         # 一次装齐 framework 的 shared / server / web
```

### 3.2 起框架

```bash
pnpm dev             # 后端 4300 + 前端热更新 4310
# 打开 http://localhost:4310
```

前端开发态由 Vite 把 `/api` 代理到 4300，所以代码里只写相对路径；
**不要**改成直连 `http://127.0.0.1:4300`，否则开发态与生产态的 cookie 行为会分叉。

只想起一边：

```bash
pnpm dev:server      # 仅后端：127.0.0.1:4300
pnpm dev:web         # 仅前端：127.0.0.1:4310（后端必须先起来，否则 /api 全部 502）
```

### 3.3 连模块一起起

先按各模块自己的 README 装好依赖——**总启动脚本不会替你装依赖**，缺了只会报错并给出指引：

```bash
# smart-factory：装依赖 + 生成 .env + Prisma Client + 建库
cd smart-factory && node scripts/dev.mjs setup && cd ..

# cosight-viewer：按其 README 安装依赖
cd cosight-viewer && npm install && cd ..
```

然后在仓库根：

```bash
pnpm dev:all         # 框架 + cosight-viewer + smart-factory，每步等就绪；Ctrl-C 逆序全停
```

| 顺序 | 服务 | 端口 | 就绪探测 |
|:---:|:---|:---:|:---|
| 1 | `framework:server` | 4300 | `/api/health` |
| 2 | `framework:web` | 4310 | `/` |
| 3 | `cosight-viewer` | 4830 | `/health` |
| 4 | `smart-factory:server` | 4100 | `/api/smart-factory/v1/health` |
| 5 | `smart-factory:web` | 4110 | `/` |

常用参数：`--home <dir>`（框架数据目录）、`--reuse`（端口被占时复用已有实例，
复用的实例不归脚本管，Ctrl-C 不会停它）、`--live`（不隔离模块数据目录，使用真实的 `~/.claude`）。
详见 [`framework/docs/dev-all.md`](framework/docs/dev-all.md)。

### 3.4 生产形态（本机验证）

```bash
pnpm build           # 前端出 dist；server 的 build 只做类型检查
pnpm start           # 托管 web/dist + API，同源 4300
```

仓库布局下 `pnpm start` 只**探活**已注册模块，不拉起它们（开发态编排是 `pnpm dev:all` 的事）。

### 3.5 提交前门禁

```bash
pnpm verify          # typecheck + oxlint + 全部测试（覆盖率阈值 80%）
```

---

## 4. 端口一览

| 端口 | 服务 | 备注 |
|:---:|:---|:---|
| `4300` | 框架 API / 产物态前端 | 分发包里首页也在这里 |
| `4310` | 框架前端（开发态） | Vite，`/api` 代理到 4300 |
| `4830` | cosight-viewer | 会话观测与任务中心 |
| `4100` | smart-factory 后端 | `/api/smart-factory/v1/health` |
| `4110` | smart-factory 前端 | 开发态 Vite |

---

## 5. 配置

### 5.1 两套来源，按运行方式选

- **分发包**：与 `start.mjs` 同目录的 `cosight.env`（`KEY=VALUE`，模板见包内
  `cosight.env.example`）。改完重启生效。
- **源码**：环境变量，例如 `COSIGHT_PORT=4400 pnpm dev`。

优先级：**命令行参数 > 真实环境变量 > `cosight.env` > 内置默认值**。

### 5.2 常用变量

| 变量 | 默认值 | 说明 |
|:---|:---|:---|
| `COSIGHT_PORT` | `4300` | 监听端口 |
| `COSIGHT_HOST` | `0.0.0.0` | 监听地址（默认所有网卡，无登录；只绑本机写 `127.0.0.1`） |
| `COSIGHT_HOME` | `~/.cosight-harness` | 数据根：库、凭据、模块清单、工作区 |
| `COSIGHT_DATABASE_URL` | `file:$COSIGHT_HOME/sqlite.db` | libsql 连接串 |
| `COSIGHT_LOG_LEVEL` | `info` | `fatal\|error\|warn\|info\|debug\|trace\|silent` |

完整清单（含 CORS、静态产物目录、知识库 API Key 等）见
[`framework/README.md` 的配置说明](framework/README.md#配置说明)。

---

## 6. 验收清单

跑完上面任一路径，逐条勾：

- [ ] `node start.mjs --self-check` 全 `[OK]`（分发包路径）
- [ ] 安装退出码 `0`，五个插件显示「已安装」
- [ ] 启动日志出现「已就绪」，`curl -s 127.0.0.1:4300/api/health` 返回 `status=ok`
- [ ] `curl -s 127.0.0.1:4300/api/modules` 能看到 `cosight-viewer`、`smart-factory`
- [ ] 浏览器打开首页，左侧栏可切换页面
- [ ] Ctrl-C 后 `ss -ltn | grep -E ':(4300|4830|4100|4110)'` 无输出

---

## 7. 可选的 Claude Code 插件与 dsh

### 7.1 插件单独安装

分发包的 `install.sh` 会自动装；源码态也可以手工装：

```bash
# 在仓库根执行，<dir> 为组件目录，<id> 为安装 ID
claude plugin marketplace add <dir>
claude plugin install <id> --scope user
```

| 组件目录 | 安装 ID |
|:---|:---|
| `drive` | `drive@zte-ai-lab` |
| `agent-genesis` | `agent-genesis@agent-genesis` |
| `agent-evaluator` | `goldeval@goldeval` |
| `skill-optimizer` | `skill-optimizer@skillx` |
| `cosight-bot` | `cosightbot@cosightbot` |

> 安装 ID 是 `<插件名>@<marketplace 名>`，**不是目录名**。`cosight-bot` 装完还需跑
> `python cosight-bot/scripts/install.py` 初始化运行环境，详见其 README。

### 7.2 装进 DeepSeek Harness（dsh）

```bash
bash install-dsh.sh --verify              # 默认 profile：web
bash install-dsh.sh --profile mylab       # 指定 profile
bash install-dsh.sh --dry-run             # 只看会做什么，不落盘
bash install-dsh.sh --uninstall           # 反向卸载
```

装完重启 dsh（单进程应用，默认 `3080` 端口同时提供前端与 API）。源码模式需要
`DSH_SOURCE_DIR` 指向 dsh checkout：

```bash
export DSH_SOURCE_DIR="$HOME/dsh"
bash install-dsh.sh --verify
(cd "$DSH_SOURCE_DIR" && node --import tsx/esm apps/cli/src/bin.ts web --no-open --port 3080)
```

详见 [`dsh-compat/README.md`](dsh-compat/README.md)。

---

## 8. 出包

在仓库根执行：

```bash
pnpm install
pnpm build          # 构建框架前端
pnpm package        # → .package/ 下生成 tar.gz 与 zip
pnpm smoke:package  # 可选：独立解压、模拟安装启动，断言各端口 2xx
```

产物顶层是 `install.*` + `start.*` + `server/` + `web/` + `modules/` + `start.mjs`，
一份归档同时包含 linux-x64 与 win32-x64 原生件。**打包脚本只构建、不联网装依赖**：
模块缺 `node_modules` 时会明确提示「请先在模块目录里装依赖」。

哪些模块进包由 `framework/docs/modules/<id>.artifact.json` 决定。

---

## 9. 常见问题

| 现象 | 原因 | 处理 |
|:---|:---|:---|
| 安装报 Node 版本不符 | 版本不在 `^22.19.0 \|\| >=24.0.0` | 按提示的下载地址升级 Node（退出码 **10**） |
| 安装提示 `claude` 找不到 | Claude Code 未装或不在 PATH | `npm i -g @anthropic-ai/claude-code`，或 `./install.sh --skip-plugins` |
| 提示缺 `python3` | 插件 hooks 需要 | 安装 Python 3 并确保在 PATH 上 |
| 启动退出码 **13**、提示端口被占 | 4300 / 4830 / 4100 / 4110 有残留进程 | `ss -ltn` 找到占用进程停掉；或 `./start.sh --port <新端口>` |
| `pnpm dev:all` 某服务反复「未就绪」 | 模块依赖没装（脚本不会代装） | 到模块目录按其 README 装依赖后重试 |
| 前端页面能开，但请求全是 502 | 单独起了前端而后端没起 | 先 `pnpm dev:server` 再 `pnpm dev:web` |
| `git pull` 后 cosight-viewer 界面没变 | 它以生产模式托管 `client/dist`，`dist` 不随仓库更新 | 在该模块内 `npm run build`，或用 `pnpm dev:all` 让它自动重建 |
| 启动日志有 `[WARN]` | 非阻塞项（如磁盘告警） | 可继续；有 `[FAIL]` 才需要处理 |
| Windows 双击脚本一闪而过 | 缺少前置依赖或不在解压目录 | 在该目录打开命令行执行 `install.cmd`，看完整输出 |

退出码对照：`0` 成功 · `10` 前置检查失败 · `12` 插件安装/卸载失败 · `13` 启动失败/端口被占。

---

## 10. 停止与卸载

**停止**：前台 `Ctrl-C`；`start.sh` 会按逆序回收全部进程。

**卸载**（分发包）：

```bash
./uninstall.sh --dry-run           # 只读：打印将执行哪些命令，不改任何东西
./uninstall.sh                     # 摘掉五个插件与 marketplace 注册
./uninstall.sh --purge-data --yes  # 连数据目录一起删（不可恢复）
```

Windows：`uninstall.cmd`。

**只删目录是不够的**：插件的载荷副本与状态在 `~/.claude` 下，必须走 `uninstall.sh`
或手工清理。完整说明见 [`framework/docs/uninstall-manual.md`](framework/docs/uninstall-manual.md)。

---

## 下一步

- 想看它解决什么问题、怎么设计：[README.md](README.md)
- 想了解产物安装的完整验收：[`framework/docs/user-guide.md`](framework/docs/user-guide.md)
- 想接入自己的模块：[`framework/docs/module-artifact-integration.md`](framework/docs/module-artifact-integration.md)
- 想定制专家与技能：从 [`agent-genesis/README.md`](agent-genesis/README.md) 开始
