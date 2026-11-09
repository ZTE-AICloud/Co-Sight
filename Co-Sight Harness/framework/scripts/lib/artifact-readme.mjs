/**
 * 产物内 README 的生成。
 *
 * 单独成文件是因为它是"给人看的东西"，和打包逻辑的修改节奏完全不同——
 * 混在一起时，改打包算法会顺带搅动这份文案的 diff。
 *
 * 写这份 README 的判断标准只有一个：**拿到这个压缩包的人，不看仓库也能跑起来。**
 * 所以它按"Linux 一条路 / Windows 一条路"来写，而不是先讲一遍通用概念再补差异——
 * 用户只关心自己那台机器上的下一步。只有打包方才知道的坑（为什么 Windows 上
 * `.cmd` 里没有中文、强杀会留下什么）也写在这里。
 */

/**
 * @param {{version: string, serverVersion: string, artifactName: string}} info
 */
export function renderArtifactReadme(info) {
  return `# Co-Sight Harness ${info.version}

AI 工程使能中心框架的**可运行分发包**：包含框架后端、已构建的前端静态产物，
以及安装与启动脚本。解压后即可运行，**不需要 pnpm，也不需要联网**。

- 框架版本：\`${info.version}\`
- 服务端版本：\`${info.serverVersion}\`
- 产物名：\`${info.artifactName}\`

## 1. 运行要求

- **Node.js \`^22.19.0 || >=24.0.0\`**（与服务端 \`engines\` 一致）。
  只要 Node 本身，**不需要 npm / pnpm / 联网**，也没有编译步骤。
- **Claude Code CLI 2.1.287 或更新**（\`claude --version\` 能跑）。
  安装会把 drive、agent-genesis、agent-evaluator、skill-optimizer、cosight-bot
  五个插件装进它；Claude Code 的配置目录（默认 \`~/.claude\`）必须可写。
  已经有自己的插件环境、不想被改？安装与启动都可以加 \`--skip-plugins\`。
- **Python 3**（PATH 上的 \`python3\`）：drive 与 agent-genesis 的 hooks、
  cosight-bot 的技能脚本直接调用它。只用其余模块时可以 \`--skip-plugins\`
  跳过这三个插件。
- 一个可写的目录用于存放数据（默认 \`~/.cosight-harness\`，Windows 上是
  \`%USERPROFILE%\\.cosight-harness\`）。
- 不需要管理员 / root 权限。安装脚本不写系统目录、不改 PATH、不注册服务。

装完 Node 后先用这一条自检，它会告诉你差什么：

\`\`\`bash
node start.mjs --self-check
\`\`\`

## 2. 解压

\`\`\`bash
# Linux
tar -xzf ${info.artifactName}.tar.gz

# Windows（两者等价，任选；tar 是 Windows 10+ 自带的）
tar -xf ${info.artifactName}.zip
\`\`\`

两种格式**内容完全等价**：产物里没有任何符号链接，所以 Windows 自带解压器
和 7-Zip 都不会解出坏掉的依赖树。

## 3. 安装（一次性，两分钟）

Linux：

\`\`\`bash
cd ${info.artifactName}
./install.sh
\`\`\`

Windows：进入解压出来的目录，**双击 \`install.cmd\`**。

它做的事有四件，且都可重复执行：

1. **前置检查（只读）**：平台、Node、Claude Code 版本、\`~/.claude\` 可写性、
   Python 3、插件载荷完整性、数据目录与配置文件。任何一项阻塞性检查不过，
   就打印"检查项 / 原因 / 处理 / 影响"并退出 **10**，一个文件都不写；
2. 建好数据目录（权限 0700）；
3. 若没有配置文件，就从 \`cosight.env.example\` 生成一份 \`cosight.env\`
   （内容全是注释，行为与不配一样）；
4. **装插件**：把包里自带的五个插件注册成本地 marketplace 并装进 Claude Code
   （\`user\` scope）。已装且版本与内容都一致时跳过，所以重跑不会重复写。
   失败时打印失败的插件、执行的命令与 CLI 报错，退出 **12**。

它**不做**的事：不装 Node / Claude Code、不 sudo、不写系统目录、不改 PATH、
不联网、不注册服务。所以在哪解压就在哪运行。

但**删掉目录不等于卸载**：五个插件装在 Claude Code 的配置目录下，\`~/.claude\` 里还有
安装时复制的五份载荷副本，它们都不在本目录里。详见第 11 节。

不想让它碰 Claude Code 的配置，用：

\`\`\`bash
./install.sh --skip-plugins
\`\`\`

启动脚本（\`start.sh\` / \`start.cmd\`）在产物布局下也会做同一套检查与插件刷新，
只是成功之后继续拉起模块；同样支持 \`--skip-plugins\`。

## 4. 启动

Linux：

\`\`\`bash
./start.sh
\`\`\`

Windows：**双击 \`start.cmd\`**，或在命令行里 \`start.cmd\`。

两个脚本都只是薄壳，真正的入口是 \`node start.mjs\`（等价，可直接用）。
启动后访问 \`http://127.0.0.1:4300/\`，接口文档在 \`/api/docs\`。
在窗口里按 **Ctrl-C** 干净退出。

常用参数（完整列表见 \`node start.mjs --help\`）：

\`\`\`bash
./start.sh --port 8080                 # 换端口
./start.sh --host 127.0.0.1            # 只绑本机（默认是 0.0.0.0，先读第 10 节的安全提示）
./start.sh --home /var/lib/cosight     # 换数据目录
./start.sh --config /etc/cosight.env   # 指定配置文件
./start.sh --no-config                 # 不读配置文件
./start.sh --skip-plugins              # 不碰 Claude Code 的插件状态
./start.sh --keep-going                # 某个模块起不来也继续（默认整体失败）
./start.sh --skip-module smart-factory # 不拉起指定模块，可重复
\`\`\`

参数优先级：**命令行 > 真实环境变量 > \`cosight.env\` > 内置默认值**。

### 关于开发态

本分发包含的是**已构建的前端**，启动入口就是生产形态。
需要热更新、改代码的开发场景请使用源码仓库：在仓库根目录执行 \`pnpm dev\`。

## 5. 配置文件 \`cosight.env\`

与 \`start.mjs\` 同目录，纯 \`KEY=VALUE\` 文本，两个平台同一份格式
（模板见 \`cosight.env.example\`，里面每个键都带注释）。例如：

\`\`\`
COSIGHT_PORT=8080
COSIGHT_LOG_LEVEL=warn
\`\`\`

改完**重启即生效**，不需要重新安装。这份文件由 \`start.mjs\` 解析，而不是由
\`start.sh\` / \`start.cmd\` 各自解析一遍——两个平台各写一份解析，语义一定会分叉。

## 6. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| \`COSIGHT_PORT\` | \`4300\` | 监听端口 |
| \`COSIGHT_HOST\` | \`0.0.0.0\` | 监听地址。默认所有网卡（无登录，请自行评估网络边界）；只绑本机写 \`127.0.0.1\` |
| \`COSIGHT_HOME\` | \`~/.cosight-harness\` | 数据根目录（见下一节） |
| \`COSIGHT_DATABASE_URL\` | \`file:$COSIGHT_HOME/sqlite.db\` | libsql 连接串 |
| \`COSIGHT_WEB_DIST\` | 产物内的 \`web/\` | 前端静态产物目录 |
| \`COSIGHT_CORS_ORIGINS\` | \`http://localhost:4310,http://127.0.0.1:4310\` | 允许跨源的源，逗号分隔 |
| \`COSIGHT_HOST_ORIGIN\` | 与 API 同源 | 宿主前端源，用于模块清单的跨源校验 |
| \`COSIGHT_LOG_LEVEL\` | \`info\` | \`fatal\\|error\\|warn\\|info\\|debug\\|trace\\|silent\` |
| \`COSIGHT_KNOWLEDGE_API_KEY\` / \`CO_KNOWLEDGE_API_KEY\` | 空 | 知识服务 Agent API Key 的服务端默认；浏览器面只被告知有没有，值只从模块面 \`/active\` 出去 |

这些变量的解析与校验只有一处实现：\`server/src/config/env.ts\`。

## 7. 数据目录

默认 \`~/.cosight-harness/\`，布局固定为：

\`\`\`
$COSIGHT_HOME/
├── sqlite.db            业务数据（启动时自动建库并执行迁移，可重复启动）
├── .credentials.yaml    密钥，权限 0600，父目录 0700
├── .module-token        模块面接口令牌，权限 0600
├── modules/             模块清单，一个模块一个子目录（<id>/module.json）
└── workspaces/          工作区文件（根目录默认在 $COSIGHT_HOME 之内）
\`\`\`

密钥与业务数据分文件存放是刻意的：单独备份或分享 \`sqlite.db\` 时不会连带泄漏密钥。
**升级或迁移时整目录带走即可。**

## 8. 模块

模块是本分发包**自带**的独立服务与页面，放在 \`modules/<模块 id>/\`
（当前包里带了哪些，看一眼 \`modules/\` 目录就知道）：

\`\`\`
modules/
└── <模块 id>/
    ├── module.json     运行时契约（宿主用它拼页面地址）
    ├── artifact.json   启动清单（start.mjs 按它拉起进程）
    └── …               该模块自己的服务端与前端产物
\`\`\`

启动时 \`start.mjs\` 按 \`artifact.json\` 把模块拉起来（需要框架的模块等框架就绪后再起），
并把这些清单同步到 \`$COSIGHT_HOME/modules/<id>/module.json\` 供宿主发现。
**任一模块起不来，整次启动失败**：已经起来的进程会被停掉，终端打印
"阶段 / 原因 / 处理 / 影响"并退出 **13**。想先跑其余部分时加 \`--keep-going\`；
只想不拉起某个模块时加 \`--skip-module <id>\`；只想起框架时加 \`--no-modules\`。

\`$COSIGHT_HOME/modules/\` 里的清单在每次启动时会被包内的同名清单覆盖；
要改某个自带模块的清单，改 \`modules/<id>/module.json\`。

没有打进这个包的模块也可以自行部署：把它的 \`module.json\` 放到
\`$COSIGHT_HOME/modules/<id>/\` 即视为注册。框架只探活并如实报告
"已注册 / 可达 / 不可达"，不会拉起它——那种模块的启动由部署者负责。

## 9. 目录结构

\`\`\`
${info.artifactName}/
├── install.sh   / install.cmd     一次性安装（预检、数据目录、配置、五个插件）
├── uninstall.sh / uninstall.cmd  卸载（摘插件与市场，按需删数据目录）
├── start.sh   / start.cmd     启动（薄壳，包住 start.mjs）
├── cosight.env.example        配置模板（两个平台同一份）
├── start.mjs                  真正的启动入口（可执行）
├── lib/                       start.mjs 的内部模块，不要单独调用
├── server/                    服务端运行时包：TypeScript 源码 + 已解析的 node_modules
├── web/                       前端静态产物（由服务端静态托管）
├── plugins/                   随包发布的五个 Claude Code 插件（含 index.json）
└── modules/                   随包发布的模块（每个模块一个目录，见第 8 节）
\`\`\`

\`server/\` 里带了一份完整的 \`node_modules\`，所以产物体积偏大（含 tsx 与 esbuild）。
这是**刻意的取舍**：换来"解压即运行、目标机器不需要包管理器也不需要联网"。
服务端以 TypeScript 源码形态直接运行（其 \`build\` 脚本只做类型检查、不产出 JS），
因此运行时必须携带 tsx。

产物里同时带了 **Linux x64 与 Windows x64** 两套原生依赖
（libsql 与 esbuild 各一份），所以同一份包在两个平台上都能直接跑；
代价是体积比只带一个平台大约多 15–20 MB。

## 10. Windows 常见问题

**\`install.cmd\` 说找不到 Node** —— 装 Node 时没勾"Add to PATH"。要么重新装并勾上，
要么在 PATH 里加上 Node 目录，要么直接用绝对路径：\`C:\\nodejs\\node.exe start.mjs\`。

**端口被占用** —— \`./start.sh --port 8081\` 换一个，或把 \`COSIGHT_PORT\` 写进
\`cosight.env\`。查占用：\`netstat -ano | findstr :4300\`。

**防火墙弹窗** —— 默认监听 \`0.0.0.0\`，所以首次启动时可能弹窗；放行后同网段其他机器
也能访问到（服务无登录鉴权）。只在本机使用时传 \`--host 127.0.0.1\`，不会有弹窗，
也不会被同网段其他机器访问到。

**双击窗口一闪而过** —— 启动失败时 \`start.cmd\` 会 \`pause\`（安装脚本同理），
窗口不会直接关掉；先看窗口里最后几行报错。

**数据目录路径** —— 默认 \`%USERPROFILE%\\.cosight-harness\`。若用户目录含空格或
非 ASCII 字符且遇到问题，用纯英文路径：\`start.cmd --home D:\\cosight\`。

**想让它后台常驻** —— 本分发不注册系统服务、不做开机自启（那是运维策略，不是
安装脚本该替用户决定的事）。Linux 用 systemd、Windows 用任务计划程序或
\`nssm\` 包一层即可，命令都是 \`node start.mjs\`。

**用任务管理器结束进程 / 直接关掉控制台窗口** —— 这等于强杀，
\`COSIGHT_HOME\` 里可能留下 \`sqlite.db-wal\` / \`sqlite.db-shm\`。
它们不影响下次启动（SQLite 会自行恢复），要干净退出请在窗口里按 **Ctrl-C**。

**为什么 \`.cmd\` 里全是英文** —— \`cmd.exe\` 按 ANSI（中文系统上是 GBK）逐字节读批处理，
UTF-8 中文注释会变成乱码，而 \`chcp 65001\` 救不了（解析器已经读过那一行）。
所以两个 \`.cmd\` 里一个中文都没有，中文说明就是本文件。

## 11. 卸载

先跑卸载脚本，再删目录：

\`\`\`bash
./uninstall.sh                  # Windows 双击 uninstall.cmd
./uninstall.sh --dry-run        # 先看一眼会动什么，什么都不改
\`\`\`

它做三件事，顺序很重要：

1. 把五个插件从 Claude Code 里卸掉；
2. 摘掉五个 marketplace，并清掉安装时复制进
   \`~/.claude/plugins/marketplaces/\` 的载荷副本；
   若某个市场下还挂着**别的**插件，该市场会保留并提示手动命令——卸载自己不会拆别人的环境；
3. 然后删掉这个解压目录。

数据目录（\`COSIGHT_HOME\`，默认 \`~/.cosight-harness\`）**默认保留**：里面有会话、
工作区与密钥。要一并删除：

\`\`\`bash
./uninstall.sh --purge-data --yes
\`\`\`

两个开关都要给：\`--purge-data\` 表示意图，\`--yes\` 表示确认（不可恢复）。框架还在跑时
删除会被拒绝，先按 Ctrl-C 停掉。

没有注册表项、没有系统服务、没有系统目录里的残留。

---

*本文件由源码仓库的 \`scripts/package.mjs\` 生成。*
`;
}
