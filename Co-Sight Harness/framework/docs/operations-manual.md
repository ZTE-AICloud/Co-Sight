# Co-Sight Harness 打包、安装与本地启动手册

> 适用版本：`0.1.0`（以仓库根 `package.json` 为准）
> 读者：拿到源码需要出包的人；拿到压缩包需要安装、启动、排查的人。
>
> 本文只讲**怎么做**。为什么这样设计见
> [`packaging.md`](./packaging.md)、[`framework-decisions.md`](./framework-decisions.md)（D40–D42）。
>
> 给测试同学与普通使用者的易读版（含验收清单与退出码对照）：
> [`user-guide.md`](./user-guide.md)。

---

## 1. 两条路，先选清楚

| 目标 | 用哪条路 | 入口 |
| --- | --- | --- |
| 日常开发、改代码、热更新 | 源码开发态 | `pnpm dev` / `pnpm dev:all` |
| 交付给别人、验证安装后的真实形态 | 打产物 → 解压 → 安装 → 启动 | `pnpm package` → `install.*` → `start.*` |
| 出包机器上做端到端验收 | 打包 + 自动解压启动 | `pnpm smoke:package` |

**产物里没有 pnpm、没有构建工具链、也不需要联网。** 装包的人只要有 Node。
出包的人需要 Node + pnpm，并且模块依赖已经在其源码树里装好。

---

## 2. 环境要求

| 项 | 要求 | 用在哪 |
| --- | --- | --- |
| Node.js | `^22.19.0 \|\| >=24.0.0` | 开发、打包、运行产物 |
| Claude Code CLI | `>= 2.1.287`（`claude --version`），配置目录可写 | 安装五个插件；不想装插件可 `--skip-plugins` |
| Python 3 | PATH 上的 `python3` | drive、agent-genesis 的 hooks 与 cosight-bot 的技能脚本；其余插件不需要 |
| pnpm | `11.28.5`（仓库 `packageManager` 指定的版本） | 开发与打包；**产物运行不需要** |
| 磁盘 | 源码依赖之外，打包工作区约 1 GB（原始产物约 580 MB + 两个归档约 437 MB） | 打包 |
| 系统工具 | `tar`；`unzip`（只有冒烟需要）；Windows 10+ 自带 `tar` | 打包后验证 |
| 平台 | 框架本体：Linux x64 / Windows x64；`smart-factory` 模块目前**仅 linux-x64** | 运行 |

检查版本：

```bash
node -v
pnpm -v
```

Node 版本不对时，产物自检会直接报出「当前版本 / 要求版本 / 下载地址」，不用猜。

---

## 3. 五分钟快速路径

### 3.1 出包（在源码仓库根目录）

```bash
pnpm install
pnpm build          # 必须：生成 framework/web/dist，打包脚本不会替你构建框架前端
pnpm package
```

产物在 `.package/`：

```text
.package/cosight-harness-<版本>-<时间戳>.tar.gz
.package/cosight-harness-<版本>-<时间戳>.zip
.package/cosight-harness-<版本>-<时间戳>.manifest.txt
```

### 3.2 安装并启动（在解压目录内）

Linux：

```bash
tar -xzf cosight-harness-*.tar.gz
cd cosight-harness-*/
./install.sh
./start.sh
```

Windows：

1. 右键 `cosight-harness-<版本>-<时间戳>.zip` →「全部解压缩」；
2. 进入解压目录，双击 `install.cmd`；
3. 双击 `start.cmd`。

打开 <http://127.0.0.1:4300/>。按 **Ctrl-C** 停止。

---

## 4. 打包

### 4.1 首次准备

```bash
cd /path/to/cosight-harness
pnpm install
```

仓库使用 pnpm workspace。若本机没有 pnpm：

```bash
corepack enable
corepack prepare pnpm@11.28.5 --activate
```

### 4.2 打包前自检

```bash
pnpm lint
pnpm typecheck
pnpm test:scripts
```

这三条是当前**确定全绿**的门禁；`pnpm verify` 会把它们连同三个工作区的测试
一起跑一遍（2026-10-20 全绿）。打包前建议直接跑 `pnpm verify`。

另外确认模块依赖已就位。打包脚本**只构建、不装依赖**（D34），模块源码树里缺
`node_modules` 时会带着「请先在模块目录里装依赖」的信息失败。smart-factory 的依赖
由模块方按其仓库说明安装（`npm ci` / Prisma 生成 / 建库脚本），框架侧不代劳。

### 4.3 执行打包

```bash
pnpm build      # 框架前端静态产物；缺了它会直接报「请先执行 pnpm build」
pnpm package
```

打包过程会按顺序做这些事：

1. 收集 `framework/docs/modules/*.artifact.json`；
   **有清单的模块才会进包**，有 `module.json` 却没有对应 `artifact.json` 的会在输出里列为「未打进」。
2. 对每个模块：按需重建前端/服务端产物（产物不旧时跳过），生成数据库模板（如声明），
   核对依赖树，展开 `bundle.include`。
3. 组装框架运行时（已解析的 `node_modules`、零软链）。
4. 按 `scripts/artifact/plugins.json` 把五个插件复制进 `plugins/`，生成
   `plugins/index.json`（版本 + 内容哈希 + `requires`），复制前后哈希必须一致。
5. 写 `tar.gz` 与 `zip`，再**逐个归档读回校验**：条目、大小、必需路径、
   可执行位、零软链、插件目录与 index 哈希。

成功时最后几行类似：

```text
打包完成：
  .package/cosight-harness-<版本>-<时间戳>.tar.gz  210.2 MB
  .package/cosight-harness-<版本>-<时间戳>.zip     226.8 MB
  条目清单  .package/cosight-harness-<版本>-<时间戳>.manifest.txt
  版本      框架 0.1.0 / 服务端 0.1.0 / pnpm 11.28.5
  平台      linux-x64 + win32-x64（原生件 ...）
  模块      cosight-viewer, smart-factory
```

### 4.4 产物里有什么

```text
cosight-harness-<版本>-<时间戳>/
├── install.sh   / install.cmd     一次性安装
├── uninstall.sh / uninstall.cmd  卸载（摘插件与市场，按需删数据目录）
├── start.sh   / start.cmd       启动薄壳
├── cosight.env.example          配置模板
├── README.md                    用户侧说明（包内生成）
├── start.mjs + lib/             真正入口与内部模块
├── server/                      服务端（TypeScript 源码 + 完整 node_modules）
├── web/                         框架前端静态产物
├── plugins/                     五个 Claude Code 插件 + index.json（安装时写入 Claude Code）
└── modules/
    ├── cosight-viewer/
    └── smart-factory/           仅 linux-x64
```

`tar.gz` 与 `zip` **内容等价**，任选其一。产物内零符号链接，Windows 自带解压器
与 7-Zip 都能正确还原。

### 4.5 打包失败怎么查

| 现象 | 原因与处理 |
| --- | --- |
| `找不到 .../web/index.html` | 没跑 `pnpm build`，或构建失败。先构建框架前端 |
| `请先在模块目录里装依赖` | 模块 `node_modules` 缺失。到模块目录按其说明安装；打包脚本不会联网安装 |
| 模块构建失败 | 看输出的构建命令与最后几行；通常是模块自己的依赖/类型错误 |
| `缺少 <id>.artifact.json` | 该模块不会进包。要进包就补清单；不进包可忽略这行提示 |
| 端口/进程相关错误 | 打包本身不监听端口；多半是模块构建脚本自己的副作用 |
| 归档里存在符号链接 | `bundle.exclude` 没排掉 `.bin` 一类目录。打包会拒绝产出坏包 |

打包失败**不会留下半成品归档**；修好后重跑即可。

---

## 5. 安装

### 5.1 Linux

```bash
tar -xzf cosight-harness-*.tar.gz
cd cosight-harness-*/
./install.sh
```

指定数据目录：

```bash
./install.sh --home /srv/cosight-harness
```

### 5.2 Windows

1. 用资源管理器右键 →「全部解压缩」（或 7-Zip）；
2. 进入解压目录，双击 `install.cmd`；
3. 命令行等价写法：

```bat
install.cmd --home D:\cosight-harness
```

### 5.3 安装脚本做了什么

步骤固定为四段，且**可重复执行**：

1. **前置检查（只读）**：平台、Node、Claude Code（能找到、`--version` 可解析、
   ≥ 2.1.287）、`~/.claude` 可写、Python 3（五个插件里有 hooks / 脚本需要）、
   插件载荷完整性、数据目录、配置文件。任一阻塞项失败 → 打印
   **检查项 / 原因 / 处理 / 影响**，退出 **10**，不写任何文件；
2. 建数据目录（默认 `~/.cosight-harness`，权限 `0700`）；
3. 若没有 `cosight.env`，从 `cosight.env.example` 生成一份（内容全是注释，
   行为等同于不配置）；
4. **装插件**：把产物 `plugins/` 里的 drive、agent-genesis、agent-evaluator
   （装出来叫 goldeval）、skill-optimizer、cosight-bot（装出来叫 cosightbot）
   注册为本地 marketplace 并安装到
   Claude Code 的 `user` scope。版本与内容都没变时跳过。失败退出 **12**，
   并打印失败的插件、执行的命令与 CLI 报错尾部。

**不会**：安装 Node / Claude Code、sudo/管理员提权、写系统目录、改 PATH、联网、
注册系统服务、后台常驻。因此解压到哪就在哪运行，删目录即卸载。

不想让它改 Claude Code 的配置：`./install.sh --skip-plugins`
（启动脚本同样支持）。插件细节见 [`plugin-install.md`](./plugin-install.md)。

> Windows 上 `install.cmd` 里没有中文是刻意的：`cmd.exe` 按 ANSI/GBK 读取批处理，
> UTF-8 中文注释会乱码。中文说明在包内 `README.md` 和本手册里。

### 5.4 安装结果

```text
解压目录/cosight.env               ← 配置文件（安装时生成，之后不再覆盖）
$COSIGHT_HOME/                     ← 默认 ~/.cosight-harness
├── sqlite.db                      业务数据（首次启动自动建库/迁移）
├── .credentials.yaml              密钥，0600（模型密钥等明文存放）
├── .module-token                  模块面接口令牌，0600
├── modules/<id>/module.json       模块清单（启动时从包内同步）
└── workspaces/                    工作区文件
```

`sqlite.db` 与密钥分文件存放：单独备份/分享数据库不会连带泄露密钥。
迁移或升级时**整个 `COSIGHT_HOME` 带走**即可。

插件不在 `COSIGHT_HOME` 里：它们装在 Claude Code 自己的配置目录
（默认 `~/.claude/plugins/`）。换一份产物重跑安装即可刷新；卸载产物目录
**不会**顺带卸载插件，卸载命令见 [`plugin-install.md`](./plugin-install.md) §7。

---

## 6. 本地启动（产物形态）

### 6.1 启动

Linux：

```bash
./start.sh
```

Windows：双击 `start.cmd`，或：

```bat
start.cmd
```

`start.sh` / `start.cmd` 只是薄壳，真正入口是 `node start.mjs`，参数完全一致。

访问：

| 地址 | 内容 |
| --- | --- |
| <http://127.0.0.1:4300/> | 框架首页 |
| <http://127.0.0.1:4300/api/health> | 健康检查 |
| <http://127.0.0.1:4300/api/docs> | 接口文档 |
| <http://127.0.0.1:4300/api/modules> | 模块注册与可达状态 |

启动摘要里还有一行 `外部访问  http://<本机网卡地址>:4300/`（就绪时也会再打一次
`其他机器打开 …`）。那是同网段其他机器该用的地址——`0.0.0.0` 只是监听通配地址，
浏览器不能直接打开。绑 `--host 127.0.0.1` 时不会有这一行。

### 6.2 启动顺序

`start.mjs` 在产物布局下按下面的顺序启动：

1. **准备步骤**：模块的 `prepare`（如 smart-factory 首次复制数据库模板）；
2. **立即模块**：按 `priority` 升序拉起，逐个等待 `readyPath` 返回 2xx；
3. **框架服务端**：等 `/api/health` 就绪；
4. **延迟模块**：`startAfter: "framework"` 的模块（需要 `.module-token` 或框架基址）；
5. **汇总报告**：打印每个模块/服务的探活结果。

任一模块起不来，**整次启动失败**：已起的进程按逆序停掉，退出 **13**（D45）。
要恢复旧的"记一行 `✗` 并跳过该模块"，加 `--keep-going`。

**默认工作区**：框架服务端启动时（第 3 步，`server/src/index.ts` 的 `seedDefaultWorkspace`），
若 `workspaces` 表为空，就建一个「默认工作区」并设为当前工作区，目录为
`<工作区根>/默认工作区`。它建在监听端口之前，所以第一次 `/api/health` 通过时已经存在。

动机：smart-factory 的预置智能体是全局行（`workspace_id = null`、`builtin = true`），
会混入每个工作区的列表；但**没有当前工作区时前端不发列表请求**，用户看到的是一屏
「未选择工作区」。只要已经存在任意一个工作区就完全跳过；全部删光后重启会重建。
创建失败只记 `warn`、不阻断启动（用户仍可在界面上新建）。

**旧数据库的结构升级**：模块的 `prepare`（`db-init.mjs`）在数据目录里**已经有库**时，
会拿它和随包模板比一次结构，而不是直接跳过：

- 缺的表、可 ADD 的列 → 直接补齐；
- 列定义变了（可空性/默认值/类型）或新增必填无默认列 → 按模板**重建表**，
  历史行里新增的必填列用类型空值（`''`/`0`）补齐；
- 索引以模板为准：缺的补建、定义变了的重建、模板里没有的移除；
- 模板外的列保留（无法保留的 `NOT NULL` 无默认列会让 prepare 明确失败）。

真正改动前先 checkpoint WAL，并把旧库备份成 `<文件名>.bak-<时间戳>`；没有差异时
一个字节都不写。所以**升级产物不需要删库重来**。第一次启动的日志里会列出改了哪些表与索引，
以及备份路径。设计取舍见 [`framework-decisions.md`](framework-decisions.md) D48。

当前包内端口：

| 服务 | 端口 | 就绪地址 |
| --- | --- | --- |
| 框架 | 4300 | `/api/health` |
| cosight-viewer | 4830 | `/health` |
| smart-factory API | 4100 | `/api/smart-factory/v1/health` |
| smart-factory 页面/代理 | 4110 | `/` |

### 6.3 常用参数

```bash
./start.sh --port 8080              # 换框架端口
./start.sh --host 127.0.0.1         # 只绑本机（默认是 0.0.0.0，先读 §8 安全提示）
./start.sh --home /var/lib/cosight  # 换数据目录
./start.sh --config /etc/cosight.env
./start.sh --no-config              # 不读配置文件
./start.sh --no-modules             # 只起框架，不拉起模块（排查用）
./start.sh --skip-plugins           # 不碰 Claude Code 的插件状态
./start.sh --keep-going             # 某个模块起不来也继续（旧行为）
./start.sh --skip-module smart-factory   # 不拉起指定模块，可重复/逗号分隔
./start.sh --claude /path/to/claude # 指定 Claude Code 可执行文件
./start.sh --log-level debug
```

**失败即停**：模块没起来、框架 30 秒内没就绪、端口被占，都会停止已启动的进程
并退出 **13**。只想先看其余模块时加 `--keep-going`。

完整列表：

```bash
./start.sh --help
```

**参数优先级：命令行 > 真实环境变量 > `cosight.env` > 内置默认值。**

例如临时换端口，不必改文件：

```bash
COSIGHT_PORT=8080 ./start.sh
```

Windows：

```bat
set COSIGHT_PORT=8080 && start.cmd
```

### 6.4 配置文件 `cosight.env`

位置：与 `start.mjs` 同目录（解压目录根）。格式是两个平台共用的纯文本：

```text
COSIGHT_PORT=8080
COSIGHT_HOME=/var/lib/cosight-harness
COSIGHT_LOG_LEVEL=info
```

规则：一行一条 `KEY=VALUE`；空行与 `#` 开头忽略；值两侧空白去掉；含空格的值加引号。
改完**重启生效**。

常用键：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `COSIGHT_PORT` | `4300` | 监听端口 |
| `COSIGHT_HOST` | `0.0.0.0` | 监听地址，默认所有网卡；只绑本机写 `127.0.0.1` |
| `COSIGHT_HOME` | `~/.cosight-harness` | 数据根目录 |
| `COSIGHT_DATABASE_URL` | `file:$COSIGHT_HOME/sqlite.db` | 数据连接串 |
| `COSIGHT_LOG_LEVEL` | `info` | `fatal\|error\|warn\|info\|debug\|trace\|silent` |
| `COSIGHT_WEB_DIST` | 产物内 `web/` | 前端静态目录 |
| `COSIGHT_WORKSPACES_ROOT` | `$COSIGHT_HOME/workspaces` | 工作区根 |
| `COSIGHT_CORS_ORIGINS` | 开发态 `:4310` | 只有前端单独部署时才需要 |

### 6.5 停止

在启动窗口按 **Ctrl-C**。脚本会按**逆序**停止：延迟模块 → 框架 → 立即模块，
按进程组回收，端口会释放。

不要用任务管理器强杀或直接关控制台窗口——可能留下 `sqlite.db-wal` / `sqlite.db-shm`
（不影响下次启动，SQLite 会自行恢复，但不是干净退出）。

### 6.6 启动前后自检

启动前只检查不运行：

```bash
node start.mjs --self-check
```

它会报告：Node 版本、当前布局（产物/仓库）、数据目录、配置文件、平台、
以及产物里认到了哪些模块、清单是否有问题。

启动后：

```bash
curl -s http://127.0.0.1:4300/api/health
curl -s http://127.0.0.1:4300/api/modules
```

`/api/modules` 里应能看到 `cosight-viewer`（以及 linux 上的 `smart-factory`），
并显示可达状态。

---

## 7. 本地启动（源码开发态）

### 7.1 只起框架

```bash
pnpm install
pnpm dev
```

- 后端：<http://127.0.0.1:4300>
- 前端（Vite 热更新）：<http://127.0.0.1:4310>
- 前端通过 Vite proxy 把 `/api` 转到 4300。

### 7.2 连模块一起起

```bash
pnpm dev:all
```

按模块清单里的优先级依次拉起框架前后端与各模块，每步等就绪；Ctrl-C 按逆序全停。
启动前会预检端口，并把占用者分成「上次残留 / 上次仍在运行 / 别人的进程」分别处理。

常用参数：

```bash
pnpm dev:all --home /tmp/cosight-dev   # 换框架数据目录（模块清单也落在这里）
pnpm dev:all --reuse                   # 端口被占用时复用已有实例（不归本脚本管）
pnpm dev:all --kill-ports              # 授权停掉占用端口的进程
pnpm dev:all --rebuild                 # 无条件重建模块前端产物
pnpm dev:all --no-build                # 完全不碰模块产物
pnpm dev:all --live                    # 不隔离模块数据目录（会读真实用户配置，慎用）
```

模块怎么被拉起登记在 `framework/docs/modules/<id>.launch.json`，
详见 [`dev-all.md`](./dev-all.md)。

### 7.3 仓库布局下跑“生产形态”

```bash
pnpm build
pnpm start
```

`pnpm start` 在仓库布局下只起框架（4300）并探活已注册模块，**不会拉起模块**；
模块编排在开发态由 `pnpm dev:all` 负责，在产物态由 `start.mjs` 负责。
这是刻意的（D27）。

### 7.4 开发态与产物的区别

| 项 | 开发态 | 产物态 |
| --- | --- | --- |
| 前端 | Vite dev server（4310，热更新） | 构建后的 `web/`，由 4300 托管 |
| 模块启动 | `dev:all` 按 `launch.json` | `start.mjs` 按 `artifact.json` |
| 依赖 | workspace / 模块自己的 `node_modules` | 随包携带的已解析 `node_modules` |
| 需要 pnpm | 是 | 否 |

---

## 8. 数据目录与安全

- **默认监听 `0.0.0.0`（所有网卡）。** 这会把服务暴露到网络：模型配置里可能有
  明文密钥，工作区文件浏览接口也只接受回环来源。只在本机使用时传 `--host 127.0.0.1`；
  对外提供前请自行评估边界与访问控制。
- `$COSIGHT_HOME/.credentials.yaml` 权限 `0600`、父目录 `0700`，但内容是**明文密钥**。
  不要提交到版本库、不要随日志/截图外发。
- `cosight.env` 本身默认不含密钥；若你往里写了密钥，同样不要提交。
- 数据目录包含对话、工作区与密钥。**备份/迁移整目录一起走**；分享 `sqlite.db` 前先确认
  里面没有敏感信息。
- 卸载 = 删目录。删除 `COSIGHT_HOME` 会**同时删除所有会话、工作区与密钥**，先备份。

---

## 9. 常见问题

### 9.1 启动即退出 / 提示 Node 版本不符

```bash
node start.mjs --self-check
```

按输出处理。产物要求 `^22.19.0 || >=24.0.0`，且不依赖 npm/pnpm。

### 9.2 端口被占用

```bash
# Linux
ss -ltnp | grep -E ':(4300|4830|4100|4110)\b'

# Windows
netstat -ano | findstr :4300
```

换端口启动：

```bash
./start.sh --port 8081
```

或把 `COSIGHT_PORT=8081` 写进 `cosight.env`。

框架端口在启动前会试绑一次：被占用时不再等子进程报栈，而是直接打印
「阶段 / 原因 / 处理 / 影响」并退出 **13**，已起的模块会被停掉。

### 9.3 模块没起来（终端里一行 `✗`）

1. 确认平台：`smart-factory` 清单写了 `platforms: ["linux-x64"]`，Windows 上会
   明确跳过，这是预期行为；
2. 看那一行 `✗` 后面的服务名与错误；
3. 只起框架排除干扰：`./start.sh --no-modules`；
4. 跑 `node start.mjs --self-check` 看清单是否被识别、依赖/入口是否齐备；
5. 若为 smart-factory，检查数据目录下 `smart-factory.db` 是否生成、4100/4110 是否空闲；
6. 日志里出现 `The column 'main.<表>.<列>' does not exist in the current database`：
   数据目录里是旧版本的库。当前版本的 `prepare` 会自动补齐并备份（§6.2）；
   如果 prepare 报了「结构不兼容」，按它打印的处理办法备份后删除该库文件再启动。

**默认语义已改**：模块起不来会让整次启动失败（退出码 13），已起的进程会被
按逆序停掉，避免留下孤儿进程占端口。只想先看其余模块时加 `--keep-going`；
某次不想要某个模块时加 `--skip-module <id>`（模块仍在注册表里，只是不拉起）。

### 9.4 首页打不开 / 白屏

```bash
curl -I http://127.0.0.1:4300/
curl -s http://127.0.0.1:4300/api/health
```

- 两个都不通：服务没起来，看启动窗口报错；
- 首页 200 但白屏：清浏览器缓存后重试；仍不行时看 `/api/health` 与浏览器控制台；
- 控制台请求 `index-<旧哈希>.js` 得到 **404**（或报 `Failed to load module script …
  MIME type of "text/html"`）：页面来自升级/重装前的缓存。旧版本静态资源按「字节数 + mtime」
  生成 ETag，而打包把 mtime 统一成 1970，新旧 `index.html` 大小一样时 ETag 撞车，
  浏览器回源只拿到 304，于是一直用指向旧 bundle 的页面。**硬刷新**（Ctrl+Shift+R）
  或关掉旧标签重开即可；当前版本已关闭静态 ETag/Last-Modified、`index.html` 用
  `no-cache`（D50），缺失资源也如实返回 404 而不回退成 HTML（D49）；
- 确认访问的是**框架端口**（默认 4300），不是模块端口或开发态 4310。

### 9.5 改了端口没生效

优先级：命令行 > 环境变量 > `cosight.env` > 默认值。检查是否有更高优先级的
`COSIGHT_PORT` 覆盖；改配置文件后必须**重启**。

### 9.6 安装脚本重复跑会不会覆盖配置

不会。数据目录已存在则保留；`cosight.env` 已存在则**不覆盖**。安装是幂等的。

### 9.7 Windows 相关

- 解压用资源管理器右键「全部解压缩」或 7-Zip，不要只双击打开压缩包再运行里面文件；
- `install.cmd` 提示找不到 Node：重装时勾选「Add to PATH」，或用绝对路径调用
  `C:\nodejs\node.exe start.mjs --install`；
- 双击窗口一闪而过：失败时脚本会 `pause`，先看最后几行；也可在命令行里运行；
- 用户目录含空格/非 ASCII 且遇到问题：用纯英文路径 `start.cmd --home D:\cosight`；
- 防火墙弹窗默认就会弹（监听 `0.0.0.0`）；只想本机用就传 `--host 127.0.0.1`，不会有弹窗；
- smart-factory 在 Windows 上会被跳过，框架与 cosight-viewer 正常工作。

### 9.8 出包后想自动验收

```bash
pnpm smoke:package                  # 重新打包 + 解压 + 安装 + 启动 + 断言
pnpm smoke:package --skip-package
```

可选参数：

```text
--port <n>          常规冒烟端口（默认 4399）
--config-port <n>   验证 cosight.env 生效的端口（默认 --port + 1）
--skip-package      复用已有归档
--keep-temp         保留临时解压目录与数据目录，便于人工翻看
```

冒烟会用系统 `tar`/`unzip` 独立解压，使用**全新的临时数据目录**，断言：安装产物、
配置端口生效、框架与模块就绪、smart-factory 的同源 API / SPA 深链接 / WebSocket 101 /
首次建库，以及关停后所有端口释放。运行前需要系统里有 `unzip`，且上述端口空闲。

---

## 10. 卸载

**删解压目录不够**：安装往 Claude Code 里写了五个插件注册和五份市场载荷副本
（`~/.claude/plugins/marketplaces/<市场名>`），它们都不在解压目录里。
所以先跑卸载脚本，再删目录。

```bash
./uninstall.sh                    # Linux / macOS
uninstall.cmd                     # Windows
./uninstall.sh --dry-run          # 只打印将做什么，不改任何东西
```

脚本按顺序做三件事：

1. 逐个 `claude plugin uninstall <插件>@<市场> --scope user`；
2. 摘掉五个 marketplaces——**先卸插件再摘市场**，顺序反了会留下指向空处的悬空注册项。
   若某个市场下还挂着别人的插件（例如你自己装的其它插件），该市场**保留**并提示手动命令，
   不会为了卸自己而去拆别人的环境；
3. 清掉安装时复制进 `~/.claude/plugins/marketplaces/` 的载荷副本。

然后手动删解压目录。数据目录默认**不删**：

```bash
rm -rf ~/.cosight-harness          # Linux / macOS；Windows 删 %USERPROFILE%\.cosight-harness
```

要连数据一起删，加两个开关（`--purge-data` 表示意图，`--yes` 表示确认；会话、工作区与
密钥都会没，且不可恢复）：

```bash
./uninstall.sh --purge-data --yes
```

框架还在跑时，删除会被拒绝——先去停掉服务，否则删的是一份正在被写的库。

在源码仓库里也能跑（`node framework/scripts/start.mjs --uninstall`）：只处理 Claude Code
那侧的插件状态，不动源码目录。

没有注册表项、系统服务、PATH 修改或系统目录残留。

手工兜底命令（脚本跑不了，比如 node 坏了）：

```bash
claude plugin list --json          # 看实际装了什么
claude plugin uninstall drive@zte-ai-lab --scope user
# 另外三个 ID 与 marketplace 的清理命令见 docs/plugin-install.md §7
```

完整单篇手册（参数、输出怎么读、退出码、自检、FAQ）：[`docs/uninstall-manual.md`](uninstall-manual.md)。

---

## 11. 命令速查

| 目的 | 命令 |
| --- | --- |
| 装源码依赖 | `pnpm install` |
| 构建框架前端 | `pnpm build` |
| 出包 | `pnpm package` |
| 端到端验收 | `pnpm smoke:package` |
| 复用归档冒烟 | `pnpm smoke:package --skip-package` |
| 开发态起框架 | `pnpm dev`（4300 + 4310） |
| 开发态连模块一起起 | `pnpm dev:all` |
| 仓库布局生产形态 | `pnpm build && pnpm start` |
| 产物安装 | `./install.sh` / `install.cmd` |
| 产物启动 | `./start.sh` / `start.cmd` |
| 只检查不启动 | `node start.mjs --self-check` |
| 只起框架 | `./start.sh --no-modules` |
| 跳过插件 | `./install.sh --skip-plugins` |
| 强制替换同名 marketplace | `./install.sh --replace-marketplace` |
| 看已装插件 | `claude plugin list --json` |
| 看全部启动参数 | `./start.sh --help` |
| 健康检查 | `curl -s http://127.0.0.1:4300/api/health` |
| 模块状态 | `curl -s http://127.0.0.1:4300/api/modules` |
| 停止 | 启动窗口 Ctrl-C |
| 卸载 | `./uninstall.sh` / `uninstall.cmd`（再删解压目录；数据目录默认保留） |
| 预览卸载动作 | `./uninstall.sh --dry-run` |
| 连数据目录一起删 | `./uninstall.sh --purge-data --yes` |
| 手工摘插件 | `claude plugin uninstall <插件>@<市场> --scope user` |
