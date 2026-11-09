# Co-Sight Harness 打包 · 安装 · 启动手册

> **给谁看：** 拿到压缩包的使用者、做验收的测试同学、需要自己出包的开发同学。
> **写法：** 每一步只讲"敲什么、看到什么算成功、不对时先查哪里"。
> 想了解为什么这样设计，看 [`operations-manual.md`](./operations-manual.md)、
> [`packaging.md`](./packaging.md)、[`plugin-install.md`](./plugin-install.md)。

---

## 0. 三条路，先对号入座

| 你的情况 | 从哪一节开始 | 需要准备什么 |
| --- | --- | --- |
| 拿到 `cosight-harness-<版本>-<时间戳>.tar.gz` / `.zip`，想跑起来 | 第 1 节 → 第 2 节 | Node.js、Claude Code（可选 Python 3） |
| 测试安装与启动，包括异常场景 | 第 1 节 → 第 5 节 | 同上，外加一个干净的用户目录 |
| 从源码出包，交给别人 | 第 3 节 | Node.js + pnpm + 各模块依赖 |

一句话流程：

```text
出包机：pnpm install → pnpm build → pnpm package → 得到 .package/ 里的两个归档
使用机：解压 → install（检查+装插件）→ start（起模块与框架）→ 浏览器打开 127.0.0.1:4300
```

---

## 1. 准备工作

### 1.1 环境要求

| 项 | 要求 | 怎么确认 | 没有会怎样 |
| --- | --- | --- | --- |
| Node.js | `^22.19.0 \|\| >=24.0.0` | `node -v` | 安装/启动直接报版本不符，退出码 **10** |
| Claude Code | `>= 2.1.287` | `claude --version` | 退出码 **10**；不想装可用 `--skip-plugins` 跳过 |
| Claude 配置目录 | 默认 `~/.claude`，必须可写 | 试着建个文件 | 退出码 **10**（多半是曾用 sudo 跑过，不要 sudo） |
| Python 3 | PATH 上有 `python3` | `python3 --version` | 退出码 **10**；drive / agent-genesis 的 hooks 需要它 |
| 磁盘 | 数据目录所在盘 ≥ 512 MB | `df -h` | 只告警，不阻塞 |
| 平台 | Linux x64 / Windows x64 | — | 其他平台在预检阶段失败 |

> **产物里不需要 pnpm、不需要联网、不需要管理员权限。** 需要 pnpm 的只有"出包"那台机器。

### 1.2 先跑一次自检（不写任何文件）

在解压目录里执行：

```bash
node start.mjs --self-check
```

它逐项打印 `[OK]` / `[WARN]` / `[FAIL]`，最后给结论。**有 `[FAIL]` 时就地处理，别急着安装**。
Windows 上同样可以直接跑这条命令。

---

## 2. 使用：安装与启动

### 2.1 解压

```bash
# Linux
tar -xzf cosight-harness-*.tar.gz
cd cosight-harness-*/
```

Windows：右键压缩包 →「全部解压缩」（或 7-Zip），进入解压目录。
两种归档内容完全等价，解压后没有符号链接，Windows 自带解压器也能正确还原。

### 2.2 安装（一行命令，约两分钟）

```bash
./install.sh
```

Windows：双击 `install.cmd`，或在命令行执行 `install.cmd`。

它会按顺序做四件事，**重复执行是安全的**：

1. **前置检查（只读）**：平台、Node、Claude Code 版本、配置目录可写、Python 3、
   插件载荷、数据目录、配置文件。任一阻塞项失败 → 打印四段
   **检查项 / 原因 / 处理 / 影响**，退出码 **10**，一个文件都不写；
2. 建数据目录（默认 `~/.cosight-harness`，权限 `0700`）；
3. 没有 `cosight.env` 时从模板生成一份（内容全是注释，行为与不配置相同）；
4. **装五个 Claude Code 插件**（`user` scope），版本与内容都没变时跳过。
   失败退出码 **12**，会打印失败的插件、执行的命令和 CLI 报错。

成功时最后几行长这样：

```text
插件：
  载荷      5 个（产物）
  Claude    /usr/local/bin/claude
  drive：已安装 2.3.4
  agent-genesis：已安装 0.22.0
  agent-evaluator：已安装 1.0.0
  skill-optimizer：已安装 1.0.0
  cosightbot：已安装 0.1.0
插件已就绪。

下一步：./start.sh            （或 node start.mjs）
```

五个插件的真实 ID（**不是目录名**，对照日志与排障时用）：

| 目录 | 安装 ID | 版本 |
| --- | --- | --- |
| `drive/` | `drive@zte-ai-lab` | 2.3.4 |
| `agent-genesis/` | `agent-genesis@agent-genesis` | 0.22.0 |
| `agent-evaluator/` | `goldeval@goldeval` | 1.0.0 |
| `skill-optimizer/` | `skill-optimizer@skillx` | 1.0.0 |
| `cosight-bot/` | `cosightbot@cosightbot` | 0.1.0 |

**常用变体**

```bash
./install.sh --home /srv/cosight-harness   # 换数据目录
./install.sh --skip-plugins                # 不碰 Claude Code 的插件
./install.sh --replace-marketplace         # 允许覆盖同名的 git 市场（默认拒绝）
./install.sh --claude /path/to/claude      # 指定 Claude Code 可执行文件
```

> `--skip-plugins` 会跳过第 4 步，模块仍能启动，但依赖插件的能力不可用。
> `--self-check` 永远只读；`--init` 只做第 2、3 步，不装插件。

### 2.3 启动

```bash
./start.sh
```

Windows：双击 `start.cmd`。打开 <http://127.0.0.1:4300/>。

启动顺序（终端里按这个顺序打印）：

1. **预检**（只读，与 `--self-check` 同一套检查）；
2. **插件**（按需：缺失才装、过期才更新、没变就跳过）；
3. **立即模块**：`prepare`（如首次复制数据库模板）→ 按优先级拉起并等就绪；
4. **框架服务端**：等 `/api/health` 返回 2xx；
5. **延迟模块**：需要框架地址或 `.module-token` 的模块；
6. **汇总**：每个模块/服务的探活结果。

看到这一行就算起来了：

```text
已就绪，浏览器打开 http://127.0.0.1:4300/ （Ctrl-C 退出）
其他机器打开 http://127.0.0.1:4300/
```

第二行的地址随本机网卡变化，是给同网段其他同事用的；只绑本机（`--host 127.0.0.1`）
时不会出现。

**默认工作区**：全新安装第一次启动时，框架会自动建一个「默认工作区」并设为当前工作区，
目录在 `$COSIGHT_HOME/workspaces/默认工作区`。smart-factory 的预置智能体是全局的
（不属于某个工作区），会出现在**每个**工作区的专家列表里；但没有当前工作区时页面
根本不会去请求列表——所以这个自动建出来的工作区就是它们的落脚点。

只要已经存在任意一个工作区（包括你删掉默认的那个、自己另建了一个），框架就**不再**
创建。把工作区全部删光后重启，会重新建一个。

当前包内端口：

| 服务 | 端口 | 用途 |
| --- | --- | --- |
| 框架 | 4300 | 首页、`/api/health`、`/api/docs`、`/api/modules` |
| cosight-viewer | 4830 | 观测/会话页面 |
| smart-factory API | 4100 | 专家/Agent 相关接口 |
| smart-factory 页面 | 4110 | 静态托管 + API 代理 |

**失败即停（默认）**：任一模块起不来、框架 30 秒内不就绪、框架端口被占，
都会停掉已起进程并退出码 **13**，输出固定四段。想先跑其余部分：

```bash
./start.sh --keep-going
```

**常用参数**

```bash
./start.sh --port 8080                  # 换框架端口
./start.sh --host 127.0.0.1             # 只绑本机（默认是 0.0.0.0，先读第 6 节安全提示）
./start.sh --home /var/lib/cosight      # 换数据目录
./start.sh --config /etc/cosight.env
./start.sh --no-config                  # 只认环境变量与命令行
./start.sh --skip-plugins               # 不碰 Claude Code
./start.sh --skip-module smart-factory  # 不拉起指定模块（仍出现在注册表）
./start.sh --no-modules                 # 只起框架
./start.sh --log-level debug
```

参数优先级：**命令行 > 真实环境变量 > `cosight.env` > 内置默认值**。
完整列表：`./start.sh --help`。

### 2.4 停止

在启动窗口按 **Ctrl-C**。脚本按逆序停止（延迟模块 → 框架 → 立即模块），
按进程组回收，端口会释放。

不要用任务管理器强杀或直接关窗口：可能留下 `sqlite.db-wal` / `sqlite.db-shm`
（不影响下次启动，但不是干净退出）。

### 2.5 安装与启动分别写了什么

| 位置 | 内容 |
| --- | --- |
| 解压目录/`cosight.env` | 配置文件，安装时生成，之后不覆盖 |
| `~/.cosight-harness/` | 数据目录：`sqlite.db`、`.credentials.yaml`(0600)、`.module-token`(0600)、`modules/`、`workspaces/` |
| `~/.claude/plugins/` | 五个插件与 marketplace 副本（**不在数据目录里**） |

卸载 = 跑 `uninstall.sh` / `uninstall.cmd` + 删解压目录；数据目录默认保留，按需加
`--purge-data --yes`（见第 8 节）。只删目录**不算**卸载——插件在 `~/.claude` 下。

---

## 3. 出包：从源码生成交付物

### 3.1 前置

```bash
cd /path/to/cosight-harness
pnpm install                 # 仓库依赖（版本由 packageManager 固定：pnpm 11.28.5）
pnpm build                   # 必须：生成 framework/web/dist，打包不会替你构建
```

还要确认**模块依赖已装好**。打包脚本只构建、**不联网装依赖**，缺了会明确报
「请先在模块目录里装依赖」。smart-factory 的依赖按其仓库说明装
（`npm ci` → `prisma generate` → 建库同步）；**不要**在它的 `web/` 里跑
`npm install`，会弄脏 lockfile。

### 3.2 打包与冒烟

```bash
pnpm package                 # 打包（含全部打包期断言，失败不留半成品）
pnpm smoke:package           # 打包 + 解压 + 模拟安装 + 真启动 + HTTP 断言
pnpm smoke:package --skip-package   # 复用已有归档，只跑验证
```

> 注意参数写法：**不要**写 `pnpm smoke:package -- --skip-package`。
> pnpm 会把 `--` 原样传给脚本，冒烟会报「未知参数 --」。

冒烟会用到系统 `tar` / `unzip`，并占用默认的 4399 / 4400（可用 `--port` 改）以及
模块端口 4100 / 4110 / 4830。**跑之前先把开发态服务停掉**，否则会因端口占用直接拒绝执行。
冒烟里的安装带 `--skip-plugins`，不会碰你真实的 `~/.claude`。

产物在 `.package/`：

```text
cosight-harness-<版本>-<时间戳>.tar.gz        210.2 MB
cosight-harness-<版本>-<时间戳>.zip           226.8 MB
cosight-harness-<版本>-<时间戳>.manifest.txt  条目清单
```

两个归档内容等价；共 34046 个条目、零符号链接、同时含 linux-x64 与 win32-x64 原生依赖。

### 3.3 打包失败先看这里

| 现象 | 原因与处理 |
| --- | --- |
| `找不到 .../web/index.html` | 没跑 `pnpm build`，或构建失败 |
| `请先在模块目录里装依赖` | 模块源码树缺 `node_modules`；到模块目录按其说明安装 |
| `缺少 <id>.artifact.json` | 该模块**不会**进包。要进包就补 `framework/docs/modules/<id>.artifact.json` |
| 归档里存在符号链接 | `bundle.exclude` 没排掉 `.bin` 一类目录；打包会拒绝产出坏包 |
| 构建报「inputs 里的 X 不存在」 | 模块清单里的输入路径写错，属于故意报错 |
| 插件相关断言失败 | 检查 `scripts/artifact/plugins.json` 与各插件的 `.claude-plugin/plugin.json` 是否一致 |

打包失败**不会留下半成品归档**；修好后重跑即可。

---

## 4. 三分钟自检（安装后 / 启动后）

```bash
curl -s http://127.0.0.1:4300/api/health     # status=ok 即框架健康
curl -s http://127.0.0.1:4300/api/modules    # 应看到 cosight-viewer、smart-factory
claude plugin list --json                    # 五个插件应为已安装、enabled=true
```

只看这五个插件装没装：

```bash
claude plugin list --json | node -e '
let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{
for(const id of ["drive@zte-ai-lab","agent-genesis@agent-genesis","goldeval@goldeval","skill-optimizer@skillx","cosightbot@cosightbot"]){
 const p=JSON.parse(d).find(x=>x.id===id);
 console.log(p?`[已安装] ${id} ${p.version} enabled=${p.enabled}`:`[未安装] ${id}`);}})'
```

判定标准：**在列表里 + `scope=user` + `enabled=true`**。
注意 `node start.mjs --self-check` 只检查"能不能装"，**不报告"装没装"**。

页面侧最小验收：

1. 首页「新建对话」能进入对话页；
2. 左侧「观测」能进入会话列表（说明 cosight-viewer 已拉起）；
3. 新建工作区、打开文件面板正常（顺带验证 SQLite 原生件）；
4. 侧栏「最近」列出近期会话（默认 5 条，「查看更多」展开到最多 100 条），点一条能恢复该会话。

---

## 5. 测试人员验收清单

### 5.1 正向路径

- [ ] `node start.mjs --self-check` 全 `[OK]`，退出码 0；
- [ ] `./install.sh` 首次执行：五个插件显示「已安装」，退出码 0；
- [ ] 再执行一次：五个插件显示「已是最新」，无写操作；
- [ ] `./start.sh` 出现「已就绪」，4300 首页 HTML、`/api/health` ok；
- [ ] `/api/modules` 中模块已注册且可达（Linux 上含 smart-factory）；
- [ ] 侧栏「最近」：默认 5 条、`查看更多（N）` 可展开/收起、点会话恢复到对话页；点击「新建对话」清空会话参数回到空态；
- [ ] 全新数据目录首次启动后，`curl -s http://127.0.0.1:4300/api/workspaces` 返回 1 条
      「默认工作区」，`/api/workspaces/active` 的 id 与它一致；
- [ ] Ctrl-C 后框架与模块端口全部释放（`ss -ltn | grep -E ':(4300|4830|4100|4110)'` 无输出）；
- [ ] 改 `cosight.env` 里的 `COSIGHT_PORT` 后重启，监听端口跟着变；
- [ ] 插件：`claude plugin list --json` 五个 ID 均在、`enabled=true`。

### 5.2 异常路径（默认应当**失败**）

| 场景 | 做法 | 预期 |
| --- | --- | --- |
| 没有 Claude Code | `PATH` 里去掉 `claude`，或 `--claude /不存在` | 预检 `[FAIL]`，退出 **10**，`~/.claude` 零写入 |
| Claude 版本过低 | 用旧版 `claude` | 报告当前版本 / 要求版本 / 升级命令，退出 **10** |
| 配置目录不可写 | `chmod 500 ~/.claude`（测试后改回） | 退出 **10**，提示不要 sudo、给出 chown 建议 |
| 端口被占 | 先占住 4300 再 `./start.sh` | 四段报告 + 退出 **13**，已起模块被回收 |
| 模块起不来 | 占住 4830 / 4100，或临时改坏清单 | 退出 **13**；加 `--keep-going` 则继续并记 `✗` |
| 明确跳过 | `./start.sh --skip-module smart-factory` | 该模块不拉起但仍在注册表，其余正常 |
| 不想动 Claude | `CLAUDE_CONFIG_DIR=<临时目录> ./install.sh --skip-plugins` | 临时目录**零文件**，输出「插件：已跳过」 |
| 同名 git marketplace | 预置同名 git 来源后安装 | 退出 **12**，**不执行** `marketplace remove`；加 `--replace-marketplace` 才替换 |

> 做插件相关用例时，**始终用隔离的 `CLAUDE_CONFIG_DIR`**，别拿自己真实的
> `~/.claude` 当靶子：
> `CLAUDE_CONFIG_DIR=$(mktemp -d) ./install.sh --skip-plugins`

### 5.3 退出码对照

| 码 | 阶段 | 典型原因 |
| --- | --- | --- |
| 0 | 成功 | — |
| 10 | 前置检查 | 没装/版本低的 Claude Code、Node 不符、目录不可写、缺 Python 3、载荷损坏 |
| 12 | 插件安装 / 卸载 | CLI 失败、marketplace 冲突、装完复核不一致；卸载时 `plugin uninstall` / `marketplace remove` 失败 |
| 13 | 启动 / 删数据目录 | 模块没起来、框架 30 秒不就绪、端口被占；卸载时框架还在跑，或只给了 `--purge-data` 没给 `--yes` |
| 1 | 其他 | 初始化写目录失败等未归类的启动错误 |

每一步失败都会打印固定四段：**检查项 / 原因 / 处理 / 影响**。
先读「处理」，照着敲；「影响」告诉你这次失败到底少了什么能力。

卸载不会改动你的 Claude 环境可以先验证：`./uninstall.sh --dry-run` 只读状态并打印
将执行哪些命令，什么都不改、退出码 0。

---

## 6. 安全与数据

- 默认监听 `0.0.0.0`（所有网卡），会暴露到网络；模型密钥是**明文**存在
  `~/.cosight-harness/.credentials.yaml`（0600）。只在本机使用时加 `--host 127.0.0.1`，
  对外提供前请自行评估访问控制。
- 从**别的机器**打开页面时，工作区文件浏览与「选择目录」按钮会返回 `403`：这几个接口
  只放行回环来源（防 DNS rebinding）。要远程用文件面板，目前只能走本机浏览器。
- `cosight.env` 默认不含密钥；若你往里写，不要提交、不要截图外发。
- 备份/迁移：整个 `COSIGHT_HOME` 一起带走；分享 `sqlite.db` 前先确认无敏感信息。
- 安装脚本不 sudo、不写系统目录、不改 PATH、不注册服务。

---

## 7. 常见问题

| 现象 | 先做什么 |
| --- | --- |
| 安装/启动立刻退出 | 看最后一屏四段报告；必要时 `node start.mjs --self-check` |
| `claude` 找不到 | `npm install -g @anthropic-ai/claude-code`，或 `--claude <路径>` |
| Windows 双击一闪而过 | 失败时脚本会 `pause`；仍看不到就在命令行里跑 |
| `install.cmd` 说找不到 Node | 装 Node 时勾「Add to PATH」，或用绝对路径 `C:\nodejs\node.exe start.mjs --install` |
| 端口被占 | 换端口 `./start.sh --port 8081`；查占用 `netstat -ano \| findstr :4300`（Win）/ `ss -ltnp \| grep :4300`（Linux） |
| 模块显示 `✗` | 看服务名与错误；`--skip-module` 隔离；smart-factory 在 Windows 上会被**预期跳过** |
| 启动日志出现 `column ... does not exist in the current database` | 数据目录里是旧版本的模块库。新版启动时会自动补齐结构并备份成 `smart-factory.db.bak-<时间戳>`，直接重启即可，**不用删库**；若提示「结构不兼容」，按提示备份后删除 `$COSIGHT_HOME/smart-factory.db` 再启动 |
| 首页白屏 | 确认访问的是 4300（不是 4310 或模块端口）；看浏览器控制台与 `/api/health` |
| 首页白屏，控制台请求 `index-<旧哈希>.js` 得到 404，或报 `MIME type of "text/html"` | 浏览器仍在用升级前的缓存页面。**硬刷新**（Ctrl+Shift+R / Cmd+Shift+R），或关掉旧标签重新打开。根因：旧版本按「字节数 + mtime」生成 ETag，而产物 mtime 统一为 1970，新旧首页字节数相同时 ETag 撞车，回源只拿到 304。当前版本已对 `index.html` 用 `no-cache` 且不再发 ETag（D50），缺失资源也如实返回 404（D49） |
| 改了 `cosight.env` 没生效 | 必须重启；检查是否有更高优先级的命令行/环境变量覆盖 |
| 插件装完当前会话没反应 | 插件在新会话加载，重启 Claude Code |
| 安装提示锁被占用 | 确认没有另一个安装进程；必要时删 `$COSIGHT_HOME/.install.lock` 再试 |
| `~/.claude` 归 root | 曾用 sudo 跑过；改回当前用户所有权，**不要 sudo** |

---

## 8. 卸载

1. Ctrl-C 停止；
2. 跑卸载脚本（Linux `./uninstall.sh`，Windows 双击 `uninstall.cmd`）——它把五个插件
   从 Claude Code 里卸掉、摘掉五个 marketplace，并清掉装进去的载荷副本；
   想先看会动什么就加 `--dry-run`；
3. 删除解压目录；
4. 按需删除数据目录：`rm -rf ~/.cosight-harness`（**会删掉会话、工作区与密钥**，先备份），
   或直接让脚本做：`./uninstall.sh --purge-data --yes`。

删除产物目录**不会**顺带卸载插件——它们装在 Claude Code 自己的配置里，所以第 2 步是必须的。

脚本跑不了时（比如 node 坏了），手敲这几条，**顺序不能反**（先卸插件，再摘市场）：

```bash
claude plugin uninstall drive@zte-ai-lab --scope user
claude plugin uninstall agent-genesis@agent-genesis --scope user
claude plugin uninstall goldeval@goldeval --scope user
claude plugin uninstall skill-optimizer@skillx --scope user
claude plugin uninstall cosightbot@cosightbot --scope user
claude plugin marketplace remove zte-ai-lab --scope user
claude plugin marketplace remove agent-genesis --scope user
claude plugin marketplace remove goldeval --scope user
claude plugin marketplace remove skillx --scope user
claude plugin marketplace remove cosightbot --scope user
```

---

## 9. 速查

| 目的 | 命令 |
| --- | --- |
| 只检查不启动 | `node start.mjs --self-check` |
| 安装（含插件） | `./install.sh` |
| 只初始化 | `node start.mjs --init` |
| 启动 | `./start.sh` |
| 只起框架 | `./start.sh --no-modules` |
| 失败也继续 | `./start.sh --keep-going` |
| 跳过插件 | `./install.sh --skip-plugins` |
| 出包 | `pnpm build && pnpm package` |
| 端到端验收 | `pnpm smoke:package --skip-package` |
| 看已装插件 | `claude plugin list --json` |
| 看 marketplace | `claude plugin marketplace list --json` |
| 健康检查 | `curl -s http://127.0.0.1:4300/api/health` |
| 模块状态 | `curl -s http://127.0.0.1:4300/api/modules` |
| 打包/安装细节 | [`operations-manual.md`](./operations-manual.md) |
| 插件排障 | [`plugin-install.md`](./plugin-install.md) |
| 产物设计 | [`packaging.md`](./packaging.md) |
| 预检与失败即停 | [`install-preflight-and-plugins.md`](./install-preflight-and-plugins.md) |
