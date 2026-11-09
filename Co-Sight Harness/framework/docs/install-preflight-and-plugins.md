# 安装闸门：前置检查、插件安装与启动失败即停

> **状态：已实现（P1–P6）。** 本文保留"要做什么、为什么这样做"的原始论证，
> 落地时的实际取舍见 §12；用户视角的操作说明见 [`plugin-install.md`](./plugin-install.md)。
>
> 相关文档：[`packaging.md`](./packaging.md)（产物形态与打包）、
> [`operations-manual.md`](./operations-manual.md)（用户侧运维）、
> [`module-artifact-integration.md`](./module-artifact-integration.md)（模块进产物）、
> [`framework-decisions.md`](./framework-decisions.md)（D45–D47）。

## 0. 一句话

把"检查 → 装插件 → 启模块"做成**一条有闸门的流水线**：任何一道检查不过，
就在动手之前停下，打印"哪一项、为什么、怎么办、影响到什么"，退出码非零；
全部通过之后才碰 `~/.claude`，插件装好之后才拉起任何模块。

## 1. 改造前的现状与缺口

### 1.1 改造前是谁在做什么

| 环节 | 现状 | 文件 |
| --- | --- | --- |
| 安装入口 | 只找 `node`，然后 `node start.mjs --init` | `scripts/artifact/install.sh` / `install.cmd` |
| Node 版本 | 已严格校验，不满足直接抛错退出 | `start.mjs` 的 `checkNodeVersion`（:325） |
| 自检 | `--self-check` 报告平台、Node、布局、数据目录、配置、模块，退出 0/1 | `printSelfCheck`（:395） |
| 初始化 | 建数据目录、生成 `cosight.env`、同步模块清单 | `runInit`（:472） |
| 模块完整性 | 只查 `module.json` 与启动入口在不在；问题**不阻塞**启动 | `describeModules`（:629）/ `inspectBundledModule`（:683） |
| 模块启动失败 | 记一行、继续；框架照常提供其余能力 | `startModules` + `main` 的注释（:978） |
| Claude Code | **完全没有检查** | — |
| 四个插件 | **完全不在产物里**，靠各自仓库的安装脚本手工装 | `drive/`、`agent-genesis/`、`agent-evaluator/`、`skill-optimizer/` |

### 1.2 缺口

1. 干净机器上装上产物、`./start.sh` 能起来，但 `drive` / `agent-genesis` /
   `agent-evaluator` / `skill-optimizer` 一个都不在 Claude Code 里；
   smart-factory 拉起 agent 时才会以"技能不存在"的形式暴露，离根因很远。
2. `claude` 没装、版本太老、`~/.claude` 不可写——现在都是"装到一半才炸"。
3. 模块清单里声明了 `bundle.required` / `bundle.executable`（打包期已经逐个断言过），
   运行期却只查启动入口。产物被手工动过（少一个 `.so`、可执行位丢了）发现不了。
4. 模块起不来不阻塞，与"缺失或异常就启动失败"的目标相反。

## 2. 目标流水线

```
install.sh / install.cmd
  └─ node start.mjs --install
       ［1］preflight   只读：平台 / Node / Claude Code / Python / 目录 / 配置 / 插件载荷 / 模块载荷
       ［2］init        写：数据目录、cosight.env、模块清单
       ［3］plugins     写：~/.claude/plugins/...（幂等，内容有变才重装）
       ［4］summary     打印每个插件的结果与"新会话生效"提示
      退出（不启动）

start.sh / start.cmd
  └─ node start.mjs
       ［1］preflight   同上（只读）
       ［2］plugins     同一段代码：缺就装、旧就更新、没变就跳过
       ［3］modules     同步清单 → 起模块 → 起框架 → 等就绪 → 起依赖框架的模块
       ［4］gate        任一模块起不来 / 框架不就绪 → 停掉已起的进程，退出非零
```

两个入口共用同一段插件代码（`ensurePlugins()`）。区别只有一条：
`--install` 装完就退出，供镜像烘焙、离线预装、`install.sh && start.sh` 使用；
`start` 装完继续拉起模块，对应需求里的"之后再启动各个模块"。

**为什么 `start` 也允许写 `~/.claude`**：需求要的是一条命令跑到底。把插件安装
只在 `install.sh` 里做，用户直接跑 `start.sh` 就会得到一个"框架全绿、Agent 全废"
的半成品——那正是现在最难受的失败形态。代价是 `start` 会改用户的全局 Claude 配置，
所以：

- 只在**确实缺失或内容过期**时写，正常情况下一次写操作都不发；
- 提供 `--skip-plugins`，明确表示"我的 Claude 环境我自己管"；
- `--self-check` 永远只读。

## 3. 前置检查（preflight）

### 3.1 检查项与判定

检查项写成登记表，每项返回
`{ id, label, level: 'block' | 'warn', ok, detail, remedy, impact }`，
由统一的渲染器输出。新增检查只加一条登记，不改流程。

| # | 检查项 | 判定 | 级别 | 失败时告诉用户什么 |
| --- | --- | --- | --- | --- |
| 1 | 平台 | `process.platform-process.arch` ∈ `ARTIFACT_TARGETS`（`linux-x64` / `win32-x64`） | block | 当前平台不在支持范围；给出已发布的两个平台 |
| 2 | Node | `satisfies(versions.node, engines.node)`（复用 `lib/node-version.mjs`） | block | 当前版本 / 要求范围 / 下载地址（现有实现原样搬进报告） |
| 3 | Claude Code CLI | ① 找到可执行文件 ② `claude --version` 5s 内返回 ③ 输出含 `Claude Code` ④ 版本 ≥ 常量 `MIN_CLAUDE_VERSION` | block | 三个分支分开说：没找到（查过哪些路径）/ 找到但不是 Claude Code（打出版本行）/ 版本过低（当前 vs 要求 + 升级命令） |
| 4 | Claude 状态目录 | `~/.claude`（或 `$CLAUDE_CONFIG_DIR`）存在时可写；不存在时其父目录可写 | block | 不要用 sudo；给出 chown 建议 |
| 5 | Python 3 | 仅当产物里的插件在其 `requires.bins` 里声明了 `python3` 时 | block | drive / agent-genesis 的 hooks 硬编码 `python3`；给出安装与 PATH 建议 |
| 6 | 插件载荷 | `plugins/index.json` 可解析；每个插件目录有 `.claude-plugin/plugin.json` 与 `marketplace.json`；`plugin` / `marketplace` / `version` 与 index 一致；`claude plugin validate <dir>` 退出码 0 | block（validate 的 warning 记 warn） | 报出哪个插件、哪个文件、期望值 vs 实际值 |
| 7 | marketplace 名冲突 | 见 §5.2 | block | 同名 marketplace 是 git 源的，说明为什么不能覆盖、给出 `--replace-marketplace` |
| 8 | 数据目录 | 现有 `inspectDataDir` | block | 现有文案 |
| 9 | 配置文件 | `loadConfigFile` 解析失败即 block | block | 现有文案（带行号） |
| 10 | 模块载荷 | 现有检查 + `modules/<id>/artifact.json` 里的 `bundle.required` 逐项存在 + `bundle.executable` 有可执行位 | block | 逐项列出缺失文件；这是"产物被搬坏"的最早信号 |
| 11 | 端口 | 仅 `start` 阶段：框架端口 + 已启用模块的 `services[].port` 能否 bind | block | 端口被谁占了（`netstat`/`lsof` 提示）+ `--port` 用法 |
| 12 | 磁盘空间 | 可用空间 < 512 MB 时 warn | warn | 仅提示 |

**只读保证**：preflight 不创建任何目录、不写任何文件、不调用会改状态的 CLI
（`plugin validate` 是只读的；`plugin list --json` / `marketplace list --json` 也是）。
`--self-check` 与正常启动的第一阶段跑的就是它。

**平台跳过不算失败**：模块在 `platforms` 里没声明当前平台，是"本就不适用"，
不是"缺失"（沿用现在的 `skipped` 语义）。插件没有这层概念——产物里带了就必须能装。

### 3.2 报告格式

状态标记只用 ASCII（`[OK]` / `[FAIL]` / `[WARN]`），不用 `✓✗`：Windows 控制台
在 GBK 代码页下会把它们打成乱码，而这段输出恰恰是给"看不懂日志的人"看的。

```
Co-Sight Harness 安装前检查
  [OK]   平台          linux x64
  [OK]   Node          v22.22.2（要求 ^22.19.0 || >=24.0.0）
  [FAIL] Claude Code   未找到
         查过：PATH、/usr/local/bin/claude、~/.local/bin/claude、~/.claude/local/claude
         处理：npm install -g @anthropic-ai/claude-code
               或把已有的 claude 所在目录加入 PATH
         影响：无法把 drive / agent-genesis / agent-evaluator / skill-optimizer / cosight-bot 装进 Claude Code
  [OK]   Claude 目录   /home/u/.claude（可写）
  [OK]   Python 3      3.11.8（drive、agent-genesis 的 hooks、cosight-bot 的脚本需要）
  [OK]   插件载荷      5 个：drive 2.3.4、agent-genesis 0.22.0、goldeval 1.0.0、skill-optimizer 1.0.0、cosightbot 0.1.0
  [OK]   数据目录      /home/u/.cosight-harness（尚未创建，上级目录可写）
  [OK]   模块          smart-factory、cosight-viewer
  [WARN] 磁盘空间      可用 412 MB（模块首次启动会写数据库，建议留 1 GB 以上）

结论：1 项失败，安装中止。退出码 10。
```

失败项永远四行：**检查项 / 原因 / 处理 / 影响**。少了"影响"，用户会误以为可以忽略。

### 3.3 为什么仍然放在 `start.mjs`

与现有 Node 校验同一条理由（`start.mjs:315-318`）：`install.sh`、`install.cmd`、
直接 `node start.mjs`、以及将来可能出现的第三种入口，都要经过同一道闸门。
写进两个 shell 包装里必定漏一个，而且 `cmd.exe` 那份还得再写一遍解析逻辑。

## 4. 插件怎么进产物

### 4.1 五个插件的真实坐标（容易写错）

| 源码目录 | 插件名（`plugin.json`） | marketplace 名 | 版本 | 体积 |
| --- | --- | --- | --- | --- |
| `drive/` | `drive` | `zte-ai-lab` | 2.3.4 | 1.9 MB |
| `agent-genesis/` | `agent-genesis` | `agent-genesis` | 0.22.0 | 3.9 MB |
| `agent-evaluator/` | **`goldeval`** | `goldeval` | 1.0.0 | 1.1 MB |
| `skill-optimizer/` | `skill-optimizer` | `skillx` | 1.0.0 | 3.6 MB |
| `cosight-bot/` | `cosightbot` | `cosightbot` | 0.1.0 | 2.8 MB |

安装 ID 是 `<plugin>@<marketplace>`，**不是目录名**：`agent-evaluator/` 装出来是
`goldeval@goldeval`。目录名与插件名不一致这一条必须在清单里显式写出，不能靠推导。

五个目录都是干净的插件根：无软链、无 `node_modules`、无 `.git`、无 `.env`、无 `.claude`，
`claude plugin validate` 全部通过（`skill-optimizer` 有一条 README 安装行的 warning）。

### 4.2 产物布局

```
plugins/
├── index.json                     ← 打包期生成，运行时唯一可信来源
├── drive/                         ← 原样拷贝（排除非运行时文件）
├── agent-genesis/
├── agent-evaluator/
├── skill-optimizer/
└── cosight-bot/
```

`index.json`：

```json
{
  "schemaVersion": 1,
  "plugins": [
    {
      "id": "drive",
      "dir": "drive",
      "plugin": "drive",
      "marketplace": "zte-ai-lab",
      "version": "2.3.4",
      "sha256": "9f2c…",
      "files": 214,
      "requires": { "bins": ["python3"] }
    }
  ]
}
```

- `sha256` 是**运行时文件集合**的内容哈希（算法见 §5.3），打包期算一次，运行期用它判断
  "同版本内容有没有变"。
- `requires` 是**宿主侧声明**（写在 `scripts/artifact/plugins.json` 里），
  不改插件仓库的任何文件。当前只有 `drive` 与 `agent-genesis` 声明 `python3`——
  两者的 `hooks/hooks.json` 都把 `python3 "${CLAUDE_PLUGIN_ROOT}"/hooks/...` 写死了。
- 插件自身的 `plugin.json` 仍是版本与名字的真源；`index.json` 里的值在打包期
  **读出来并交叉校验**，不一致就打包失败。

### 4.3 打包阶段的改动

- `lib/project.mjs`：`ARTIFACT_LAYOUT` 增加 `pluginsSubdir: 'plugins'`。
- `scripts/artifact/plugins.json`：新增，五个插件的坐标 + `requires`（上表）。
- `package.mjs`：
  - 按 `plugins.json` 把五个目录复制进 staging，**排除**
    `tests/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`*.pyc`、`.git/`、
    `node_modules/`、`.claude/`、`.env`、`work/`、`output/`、`.agent-genesis/`；
  - 复制前后各算一次哈希，写入 `plugins/index.json`；
  - 把 `plugins/index.json` 与每个插件的两份 manifest 加进 `requiredPaths` 断言，
    归档读回后逐个校验（与现有 `verifyArchive` 同一条路）。
- `smoke-package.mjs`：解包后检查 `plugins/` 五个目录与 index；再用一个**假的 `claude`**
  （见 §8）在临时 `HOME` 下跑一遍 `install.sh`，断言两份状态 JSON 被写对。

### 4.4 不改同事的仓库

五个插件目录只**读取与复制**，不改一行。`requires` 写在宿主侧清单里；
将来插件的 hook 改成可移植写法（比如优先 `python3`、回退 `python`），
只需改 `plugins.json`，不用发插件的新版本。

## 5. 插件安装算法

### 5.1 状态从哪来

优先用 CLI 的结构化输出，文件只作兜底：

| 信息 | 首选 | 兜底 |
| --- | --- | --- |
| 已装插件 | `claude plugin list --json` → `id` / `version` / `scope` / `enabled` / `installPath` | `~/.claude/plugins/installed_plugins.json` |
| marketplace | `claude plugin marketplace list --json` → `name` / `source` / `installLocation` | `~/.claude/plugins/known_marketplaces.json` |

两次调用批量拿全量，不要每个插件各调一次。注意两种来源的 `source` 形状不同：
CLI 给字符串（`"git"`），文件里是对象（`{"source":"git","url":…}`），读取时要归一化。

### 5.2 marketplace 名冲突

marketplace 的源目录**不指向产物目录**，而是按 CLI 的规范位置放一份副本：

```
~/.claude/plugins/marketplaces/<marketplace>/
```

理由有两条：CLI 的 marketplace 只记路径、要求它长期存在；产物目录可能被移动或删除。
副本放在用户目录之后，"把产物移到别的盘"不会让插件失效。

冲突判定（同名 marketplace）：

| 现状 | 动作 |
| --- | --- |
| 未注册 | 复制副本 → `marketplace add <目录>` |
| 已注册，`source !== 'git'`，且注册路径就是规范位置 | 刷新副本（内容有变时）→ `marketplace add` |
| 已注册，`source !== 'git'`，但注册到别处 | `marketplace remove <名>` → 复制 → `add` |
| 已注册，`source === 'git'` | **block**：同名但来源是别人的 git 仓库，覆盖会毁掉用户已有的插件来源。提示改用 `--replace-marketplace` 显式确认 |

这一条比 `drive/scripts/install.sh` 现有做法更保守：它遇到路径不同就直接
`marketplace remove`。`zte-ai-lab` 这个名字在企业内网很可能已经被别的 git 仓库占用，
默认覆盖会造成"装完框架，原来的插件没了"。**删目录前必须同时满足**：名字在四插件
白名单里、路径解析后确实位于 `~/.claude/plugins/marketplaces/` 下、且来源不是 git。

### 5.3 幂等与内容刷新

CLI 的两个已知行为（来自 `drive/scripts/install.sh` 的实测记录）：

- `plugin install` 对**已安装**的插件是 no-op，不会把元数据升到新版本；
- `plugin update` 只在**版本号变化**时才复制内容，同版本内容变化会被跳过。

所以判定必须同时看版本与内容哈希：

```js
// 纯函数：不碰文件系统，便于单测
decidePluginAction({ installedVersion, payloadVersion, cacheHash, payloadHash })
// → 'install' | 'update' | 'reinstall' | 'none'
```

| installedVersion | 版本相等 | cacheHash vs payloadHash | 动作 |
| --- | --- | --- | --- |
| 无 | — | — | `install` |
| 有 | 否 | — | `update`（失败则 `uninstall` + `install`） |
| 有 | 是 | 不同 | `uninstall` + `install`（`reinstall`） |
| 有 | 是 | 相同 | `none` |

内容哈希的算法（打包期与运行期共用同一份实现）：

```
按相对路径排序 → 对每个文件写入 "posix/相对路径\0" + 文件字节
→ SHA-256 → 取前 16 位十六进制
```

文件集合 = 复制进产物的那套（即 §4.3 的排除规则之后的全部文件）。
cache 目录用同一套排除规则算，才能与 payload 比。

命令一律带 `--scope user --json`；非交互场景必须带 `-y`
（CLI 帮助写明：stdin/stdout 不是 TTY 时，marketplace 声明的命令需要 `-y`）。
五个插件都是纯源码 marketplace，没有"执行远程命令"的条目；`-y` 在这里只是让
本地安装不弹提示，不会顺带信任别的东西。每次调用 120s 超时。

**安装前后各读一次状态**，安装后用
`installed_plugins.json` / `plugin list --json` 复核三项：
`version` 等于 payload 版本、`installPath` 存在、内容哈希一致。任何一项不符即失败。

### 5.4 Windows

`claude` 在 Windows 上通常是 `claude.cmd`（npm 全局安装）或 `claude.exe`（原生安装）。
Node 的 `spawn` **不能直接执行 `.cmd`**。解析顺序：

1. `--claude <path>` 显式指定（测试与非常规安装）；
2. PATH 中按 `PATHEXT` 找 `claude.exe` → 直接 spawn；
3. 找到 `claude.cmd` / `claude.bat` → `cmd.exe /d /s /c` + 自行拼 quoting；
4. 已知位置兜底：`%USERPROFILE%\.local\bin\claude*`、`%USERPROFILE%\.claude\local\claude*`、
   npm 全局前缀下的 `claude*`。

quoting 必须覆盖**路径含空格与中文**的情况（本仓库路径里就有中文）。
把它写成独立的纯函数并单测，输入用
`C:\Users\张 三\AppData\Roaming\npm\claude.cmd` 这类样本。
POSIX 侧永远 `shell: false`，参数按数组传，不做字符串拼接。

### 5.5 失败与清理

- 插件阶段失败发生在**任何模块进程出现之前**，没有进程要回收；
- 已装好的前几个插件保留（幂等，下次重跑会跳过）——**不回滚**。
  回滚意味着卸载用户可能本来就在用的插件，风险大于收益；
- 失败即退出码 12，并打印失败的那个插件、执行的命令（不含密钥，本来也没有）、
  CLI 的 stderr 尾部和补救建议；
- `--install` 期间持有 `$COSIGHT_HOME/.install.lock`（`wx` 打开，`finally` 删除），
  防止两个安装进程同时改 `~/.claude`。

## 6. 启动闸门（fail-fast）

### 6.1 阶段与退出码

| 阶段 | 失败时 | 退出码 |
| --- | --- | --- |
| preflight | 打印报告，不写任何东西 | 10 |
| init | 打印失败步骤 | 11 |
| plugins | 打印失败插件 + CLI 尾部 | 12 |
| start（模块/框架起不来） | 停掉已起进程，打印失败模块与最后几行日志 | 13 |

现有 `main().catch` 只打印 `启动失败：…` 并退 1；改为用带 `code` 的
`StartupError` 携带阶段，顶层统一渲染。`0` 仍表示成功。

### 6.2 模块失败的默认语义要改

现在（`start.mjs:978-981` 的注释）明确写着"模块起不来不拖垮框架"。本方案**默认反转**：

- 产物里带的模块是产品的一部分，"专家页打不开"不能算可接受的降级；
- 模块启动失败（spawn 失败、进程立刻退出、`readyPath` 超时）→ 停掉所有已起进程 → 退 13；
- 框架本身 30s 内不就绪 → 同样视为失败（现在只是打一行超时提示）；
- 平台不支持的模块（`skipped`）与 `--skip-module` 明确排除的模块**不算失败**；
- `--keep-going` 恢复旧行为（记一行、继续），给"我只想要会话，不要专家页"的场景留口子。

这是一个决策变更，需要补进 `framework-decisions.md`（新增 D 条目），
并在 `operations-manual.md` 里写清两种模式的差别。

### 6.3 清理

复用现有 `superviseAll` 的 `stopAll(code)`：它按负 PID 回收整个进程组。
失败路径上必须先 `await supervision.stopAll(13)` 再退出，否则
`detached: true` 拉起的模块进程会变成孤儿，占着端口，下一次启动报"端口被占"——
那会把真正的根因埋掉。

## 7. 代码落点

### 7.1 新增

| 文件 | 职责 |
| --- | --- |
| `scripts/lib/claude-cli.mjs` | 解析 `claude` 可执行文件、`--version` 解析、带超时的命令执行、Windows quoting |
| `scripts/lib/plugin-index.mjs` | 读写/校验 `plugins/index.json`、载荷完整性、内容哈希 |
| `scripts/lib/plugin-install.mjs` | `decideMarketplace` / `decidePluginAction` 纯函数 + `ensurePlugins()` 编排 |
| `scripts/lib/preflight.mjs` | 检查项登记与聚合 |
| `scripts/lib/checks/{platform,node,claude,plugins,modules,env}.mjs` | 每类检查一个文件（单文件控制在 200–400 行） |
| `scripts/artifact/plugins.json` | 五个插件的坐标 + `requires`（打包期真源） |
| `scripts/tests/{claude-cli,plugin-install,preflight}.test.mjs`、`scripts/tests/fake-claude/` | 见第 8 节 |
| `docs/plugin-install.md` | 用户/运维视角：装了什么、装到哪、怎么排障（本文讲设计） |

### 7.2 修改（均已完成）

| 文件 | 改动 |
| --- | --- |
| `scripts/start.mjs` | 新增 `--install` / `--skip-plugins` / `--keep-going` / `--claude <path>` / `--skip-module <id>`；preflight 接入 `--self-check`；`ensurePlugins()`；失败即停（退出码 10/12/13） |
| `scripts/artifact/install.sh` / `.cmd` | `--init` 改成 `--install`；帮助文案补一句"会往 Claude Code 装五个插件" |
| `scripts/lib/project.mjs` | `ARTIFACT_LAYOUT.pluginsSubdir` |
| `scripts/package.mjs` | 插件搬运 + `index.json` + 读回断言 |
| `scripts/smoke-package.mjs` | 插件存在性 + 假 `claude` 的端到端安装 |
| `scripts/lib/artifact-readme.mjs` | README 的"安装"一节加插件步骤与 `--skip-plugins` |
| `docs/packaging.md` | §1 产物形态加 `plugins/`；§7 断言清单加插件；§9 验证步骤加"插件已装" |
| `docs/operations-manual.md` | 前置条件、失败码表、插件更新/卸载、移动安装目录、`--keep-going` 语义 |
| `docs/framework-decisions.md` | 新增决策：启动失败即停；插件随产物分发；marketplace 冲突不默认覆盖 |
| `docs/task-list.md` | 对应小节与验收项 |

### 7.3 明确不做

- 不改 `drive/`、`agent-genesis/`、`agent-evaluator/`、`skill-optimizer/`、`cosight-bot/` 里任何文件；
- 不改 `smart-factory/`、`cosight-viewer/`；
- 不用 `sudo`、不写系统目录、不改 PATH、不装系统包；
- 不在 preflight 里联网（插件从本地路径安装，全程离线）；
- 不把插件写进 `project` scope（默认 `user`，可用 `--scope` 改）。

## 8. 测试计划

### 8.1 纯函数单测（快、无副作用）

- `decidePluginAction` 的四条分支 + 版本前缀 `v` / 空值；
- `decideMarketplace`：未注册 / 我们自己的 / 注册到别处 / git 源（block 与 `--replace-marketplace`）；
- 内容哈希：同一目录两次一致、文件改动后变化、排除目录不参与、
  路径分隔符不影响结果（用 POSIX 相对路径进哈希）；
- `claude --version` 解析：`2.1.304 (Claude Code)`、带 `v` 前缀、多余输出；
- Windows quoting：空格、中文、引号、`&`、`^`。

### 8.2 假 `claude` 端到端

`tests/fake-claude/` 提供一个用 Node 写的可执行文件，放在临时目录并置于 `PATH` 最前：

- `--version` 输出可配置的版本行；
- `plugin marketplace add|remove|list --json` 读写临时 `HOME` 下的
  `known_marketplaces.json`（按 CLI 的真实形状）；
- `plugin install|update|uninstall|list --json` 读写 `installed_plugins.json`
  并把 payload 复制到临时 cache 目录；
- 每次调用把 argv 追加到 `calls.jsonl`，供断言。

用例：

| 场景 | 断言 |
| --- | --- |
| 干净环境 | 五个插件按 `drive → agent-genesis → goldeval → skill-optimizer → cosightbot` 的顺序安装；ID 精确匹配；无多余命令 |
| 再跑一次 | 全部 `none`，不出现 `install` / `update` / `uninstall` |
| 同版本改了内容 | 走 `uninstall` + `install`，cache 哈希刷新 |
| 版本变了 | 走 `update` |
| marketplace 是 git 源 | 默认退出 12 且**没有** `marketplace remove`；加 `--replace-marketplace` 后正常 |
| `claude` 不存在 | 退出 10，`~/.claude` 下**零写入** |
| 缺 `python3` | 退出 10，报告点名 `drive` / `agent-genesis` |
| `--skip-plugins` | 完全不调用 `claude` |
| 启动阶段某模块 ready 超时 | 退出 13，所有子进程组已回收（端口可立即重新 bind） |

### 8.3 产物冒烟

`pnpm smoke:package`：解包 → 假 `claude` + 临时 `HOME` → `install.sh` →
断言五个插件就位 → `start.sh --self-check` 退出 0 →
（可选）真启动并探 `/api/health`。

### 8.4 Windows

按记忆里的教训（"本机 Linux 复现不了"）：先写守卫断言（quoting 单测、
`.cmd` 分支、`PATHEXT` 解析），再走一次人工清单——把产物放到含中文与空格的路径、
用 GBK 控制台跑 `install.cmd`，确认输出不乱码、五个插件都装上。

## 9. 文档与决策记录

- `framework-decisions.md` 新增三条：D45 启动失败即停（`--keep-going` 回退）、
  D46 插件随产物分发并从本地 marketplace 安装、D47 marketplace 同名冲突不默认覆盖。
- `packaging.md`：产物形态、断言清单、体积（实测原始 +6.3 MB / 压缩后 +2.0 MB，已去掉 tests 与缓存）。
- `operations-manual.md`：前置条件表、退出码表、常见失败与处理、插件更新方式。
- `plugin-install.md`：用户视角的"装了什么、装在哪、怎么卸"。

## 10. 风险与待确认

| # | 风险 / 待定 | 建议 |
| --- | --- | --- |
| 1 | `MIN_CLAUDE_VERSION` 取多少 | 已定 **`2.1.287`**（2026-10-21 按产品要求上调，取代最初的 `2.1.0`）；本机基线实测 2.1.304。版本常量只放一处，另加"版本解析失败但 `plugin list --json` 可用 → warn 放行"的兜底 |
| 2 | Windows 上 hooks 写死 `python3` | 默认 block 并给出安装指引；同时把"让 hook 回退 `python`"作为对接项提给插件作者。不改插件代码 |
| 3 | `zte-ai-lab` 这种 marketplace 名容易被 git 源占用 | 默认 block + `--replace-marketplace` 显式确认（§5.2） |
| 4 | `start` 默认写 `~/.claude` | 只在需要时写；`--skip-plugins` 关闭；文档写清 |
| 5 | 模块失败从"警告"变"失败" | 用 `--keep-going` 保留旧语义；决策记录写清理由 |
| 6 | 插件体积 +9 MB | 相对现有产物可忽略；打包期打印体积 |
| 7 | CLI 版本差异导致参数不存在 | 所有调用都带超时并保留 stderr；失败信息里带完整命令，便于对照 `--help` |
| 8 | 并发安装 | `.install.lock`（§5.5） |

## 11. 实施阶段与验收

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| P1 | preflight 框架 + 平台/Node/目录/配置检查接入 `--self-check` | 缺 Node、目录不可写时退 10；报告格式固定；`pnpm verify` 通过 |
| P2 | `claude-cli.mjs` + Claude Code/Python 检查 | 假 `claude` 单测覆盖"找不到 / 版本低 / 非 Claude Code / 正常"；Windows quoting 单测 |
| P3 | 插件进产物（`plugins.json`、打包、index、断言） | `pnpm package` 产物含五个目录与 index；哈希交叉校验；`smoke:package` 通过 |
| P4 | `ensurePlugins()` + `--install` + 幂等/冲突/刷新 | §8.2 的九条用例全绿 |
| P5 | 启动闸门（fail-fast + 清理） | ready 超时退 13 且端口立即可复用；`--keep-going` 恢复旧行为 |
| P6 | 文档、决策记录、Windows 人工验收 | 文档三处更新；Windows 清单打勾；`pnpm verify` 与 `smoke:package` 全绿 |

P3 之后产物形态就变了，P4 之前 `install.sh` 仍走 `--init`，中间的产物可以先不带
插件分发——但一旦 P3 合入，`start` 在产物布局下就必须能处理"有 `plugins/` 但还没装"
的状态，所以 P3 与 P4 建议同一批提交。

## 12. 落地结果与偏差

实施完 P1–P6 后，与本文计划一致的部分不再重复；这里只记**实际做法与计划的差别**，
以及计划里写了但**没有做**的事（避免后来者以为已经覆盖）。

### 12.1 与计划一致

- 检查项登记表 + 固定四段渲染（检查项 / 原因 / 处理 / 影响），退出码
  10 预检、12 插件、13 启动；
- 插件载荷进产物、`plugins/index.json`、内容哈希、打包期交叉校验与归档读回断言；
- `ensurePlugins()` 的 install / update / reinstall / none 判定、marketplace 冲突
  策略、`--replace-marketplace`、`.install.lock`、装后复核；
- 启动闸门：端口试绑、模块/框架失败即停、`--keep-going`、`--skip-module`、
  `stopAll(13)` 清理；
- 文档四处更新（`plugin-install.md` 新增，`packaging.md`、`operations-manual.md`、
  `framework-decisions.md` D45–D47）。

### 12.2 偏差

| 计划里写的 | 实际做的 | 原因 |
| --- | --- | --- |
| 退出码 11（init 失败）独立实现 | init 失败沿用原有 `main().catch` 路径，退出 **1**；10/12/13 已按计划实现 | init 只有"建目录 / 写配置"两步，原有错误信息已带路径与 errno；单独包一层 `StartupError` 只是换个数字，没有新增信息。文档只承诺 10/12/13 |
| 预检第 11 项「端口」 | 端口检查放在**启动阶段开头**（`checkTcpBind`），不在预检登记表里 | `--self-check` 是只读自检，不应因为"现在 4300 被占"就报失败；端口属于启动前置条件 |
| 预检第 7 项「marketplace 名冲突」 | 在 `ensurePlugins()` 里按插件逐个判定，不在预检里 | 冲突的处理方式取决于是否安装、是否给了 `--replace-marketplace`，属于安装决策而不是环境事实；`--self-check` 仍只读 |
| `claude plugin validate <dir>` 作为预检项 | **没有做**。预检只静态校验 `index.json` 与两份 manifest | `validate` 需要真实 `claude` 且其退出码语义在 2.1.x 上未稳定；静态校验已经能覆盖"坐标/文件缺失"，运行期失败由退出码 12 兜底 |
| `StartupError` 类 | 用 `exitCode` + 固定四段渲染函数（`renderStartFailure` / `renderPluginFailure`） | 阶段信息在调用点已知，没必要再引入异常类型与转换层 |
| `tests/fake-claude/` 独立可执行假 CLI | 单测里用**进程内的假状态机**（`makeHarness`）覆盖同一批用例 | 同样的断言不需要跨进程；真实 CLI 另做过一次手工端到端（见 12.3） |
| `smoke:package` 用假 `claude` 跑 `install.sh` | 冒烟只断言 `plugins/` 五目录、manifest 与 index 哈希；**不跑插件安装** | 冒烟环境没有 `claude`，也不应写用户真实配置。安装行为由单测 + 手工真实 CLI 覆盖 |

### 12.3 验证记录

- `plugin-payload.test.mjs` / `plugin-install.test.mjs` / `claude-check.test.mjs` /
  `preflight.test.mjs` / `runtime.test.mjs`：脚本测试全绿（合计 222 条）；
- 真实 `claude 2.1.304` + 隔离 `CLAUDE_CONFIG_DIR`（**最终产物**里解压出来的
  `install.sh`）：首次安装四个插件成功，第二次运行全部 `none`、零写命令，
  用户真实 `~/.claude` 未被触碰；
- `--install --skip-plugins`：隔离的 `CLAUDE_CONFIG_DIR` 下**零文件写入**，
  输出明确写「插件：已跳过（--skip-plugins）」；
- 手工占住框架端口后启动：输出四段并退出 13，已起进程被回收；
  正常启动到达「已就绪」，SIGTERM 后端口立即可复用；
- `pnpm verify`：全绿（脚本 222、shared 91、server 346、web 343）。

**验证时发现并修掉的一个 bug**：`--install` 分支原先无条件调用
`runPluginInstall()`，绕过了 `--skip-plugins`——用户明确要求"别碰我的 Claude 环境"，
却仍被写入了四个 marketplace 副本。现在判定收敛到
`lib/plugin-install.mjs` 的 `shouldInstallPlugins()`（纯函数，四个组合全有单测），
两条路径（`--install` 与产物布局的 `start`）共用同一份判定。

### 12.4 仍需人工确认

- **Windows 全链路**：`claude.cmd` 调用、GBK 控制台下的输出、含中文/空格路径，
  只有单测与守卫断言，没有真机跑过（与 §8.4 的计划一致）；
- 插件作者侧：`drive` / `agent-genesis` 的 hooks 写死 `python3`，
  Windows 上需要它们回退 `python`；这属于对接项，本轮不改对方代码。
