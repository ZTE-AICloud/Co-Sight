# 总启动脚本（`pnpm dev:all`）

一条命令把 framework 的前后端 + 各模块的前后端全起起来，Ctrl-C 一次全停。

```bash
cd <仓库根>
pnpm dev:all
# 打开 http://localhost:4310/
# Ctrl-C 停止全部（按逆序）
```

## 先读这段：它在四条命令里的位置

这个脚本**不替代**任何已有入口，它是第四条。四条命令服务四件不同的事：

| 命令 | 服务的事 | 起什么 |
|---|---|---|
| `pnpm dev` | 框架自己的开发态（D27=A 认定的唯一开发入口） | 框架后端 4300 + 前端 4310 |
| `pnpm start` | 装配态：**产物**能不能跑起来 | 走 `scripts/start.mjs`；产物布局下按 `docs/modules/<id>.artifact.json` **拉起模块**，仓库布局下只探活（D41） |
| 模块自带脚本 | 单独调某个模块 | `node smart-factory/scripts/dev.mjs start`、`co-sight-viewer start` |
| `pnpm dev:all` | 开发机上"一条命令把整套调起来" | 框架 + 全部登记过的模块 |

与 `start.mjs` 的边界是**分开的，不是放宽的**：两者回答的是不同的问题。
`start.mjs` 问"装到用户机器上怎么跑"（产物布局），`pnpm dev:all` 问"我坐在这台开发机上怎么跑"。
命令本身就不一样（`node server/index.js` vs `npm run dev`）、工作目录基准也不一样
（模块目录 vs 仓库根），所以是两份清单，不是一份清单的两个分支（D41）。

**运行时契约仍然没有启动命令字段。** `shared/src/contracts/module.ts` 里的
（`entry` / `capability` / `healthcheck`）一个字没动，`/api/modules` 也不会把 shell 命令发给浏览器。
启动方式登记在同目录的两份**旁挂清单**里：开发编排是 `<id>.launch.json`（本脚本读），
装配态是 `<id>.artifact.json`（打包脚本与 `start.mjs` 读）。

## 启动顺序与优先级

框架自己写在脚本里（宿主就是本仓库，不存在"第三方登记"问题），模块走 `launch.json` 的 `priority` 升序。

| 顺序 | 标签 | cwd | 端口 | 就绪探测 |
|---|---|---|---|---|
| 1 | `framework:server` | 仓库根 | 4300 | `/api/health` |
| 2 | `framework:web` | 仓库根 | 4310 | `/` |
| 3 | `cosight-viewer` | `cosight-viewer/` | 4830 | `/health` |
| 4 | `smart-factory:server` | `smart-factory/server/` | 4100 | `/api/smart-factory/v1/health` |
| 5 | `smart-factory:web` | `smart-factory/web/` | 4110 | `/` |

**每一步都等就绪才走下一步。** 后起的服务往往依赖前面的在监听：smart-factory 的 Vite proxy
要转发到它的后端，框架前端要转发到框架后端。抢跑只会得到一屏"连接被拒绝"，然后人以为脚本坏了。

**同一模块内按 `services` 数组的顺序起**，所以 `smart-factory` 的 `server` 写在 `web` 前面——
与它自带 `scripts/dev.mjs start` 的顺序一致，理由同上。

声明了 `build` 的模块会多一步**产物准备**，它挂在该模块第一个服务之前：
**该模块构建（如果需要）→ 它的第一个服务 → 其余服务**。挂在模块前面而不是把所有构建
提到最前，是为了让框架先起来——不然一个十几秒的前端全量构建会把 `framework:web` 一起拖住。
详见下面的[模块产物](#模块产物产物旧了不报错只骗人)。

### 端口 / 超时一览

| 服务 | 变量覆盖 | 默认就绪超时 |
|---|---|---|
| `framework:server` | `COSIGHT_PORT` | 30s |
| `framework:web` | —（Vite 4310） | 30s |
| 模块各服务 | 清单里的 `port` / `readyTimeoutMs` | 30s |

## 选项

| 选项 | 作用 |
|---|---|
| `--live` | **不隔离**模块的数据目录，让模块用你真实的 `~/.claude` 等。默认关闭，详见下节 |
| `--home <dir>` | 框架数据目录（等价 `COSIGHT_HOME`，默认 `~/.cosight-harness`），同时也是模块清单的落地目录 `<home>/modules` |
| `--reuse` | 端口被占用时复用已有实例，不报错。**复用的实例不归本脚本管，Ctrl-C 不会停它** |
| `--kill-ports` | 授权本脚本停掉占用端口的进程（TERM → 宽限 → KILL）。只在确认那是你自己的进程时用 |
| `--rebuild` | 无条件重建所有声明了 `build` 的模块产物。默认**只在产物比源码旧时**重建 |
| `--no-build` | 完全不碰模块产物，用本机现状启动。排查"是不是构建本身的问题"时用 |
| `-h`, `--help` | 帮助 |

未知参数直接报错退出（与 `start.mjs` 的风格一致）——静默忽略拼错的选项会让人以为它生效了。
`--rebuild` 与 `--no-build` 互斥（一个要求"都重建"、一个要求"都别碰"），同时给就直接报错，
不去猜哪个优先。

## 模块产物：产物旧了不报错，只骗人

有的模块的**开发态入口就是产物**：`cosight-viewer` 的 server 在 `CO_SIGHT_MODE=claude` 下
是生产模式，静态托管 `client/dist`；而 `client/dist` 在 `.gitignore` 里，`git pull` 只更新源码、
不管产物。于是本机跑的是几天前的包——**页面缺了同事刚合的功能，而你只会以为"功能没做"。**

实测踩到过：同事合进来的对话页在本机 404，因为旧包里连那条 hash 路由都没有。这类故障
**不报错**，只安静地骗人，靠"记得手工 build 一下"是防不住的（谁都不会记得）。

所以启动前刷一遍产物这件事，登记在清单里，由脚本负责：

```jsonc
"build": {
  "cwd": "client",                 // 相对 moduleRoot，默认 "."
  "command": ["npm", "run", "build"],
  "inputs": ["src", "index.html", "vite.config.ts", "package.json"],  // 省略即 ["."]
  "outputs": ["dist/index.html"],  // 必填：陈旧判据全靠它
  "timeoutMs": 300000              // 默认 300000（5 分钟）
}
```

| 选项 | 效果 |
|---|---|
| 默认 | 产物不存在、或**输入里最新的一个比产物里最旧的一个新** → 重建；否则跳过并打印"已是最新" |
| `--rebuild` | 跳过判据，一律重建 |
| `--no-build` | 一律不碰，直接用本机现状启动 |
| 构建失败 / `inputs` 里的路径不存在 / 构建目录没有 `node_modules` | 该模块的**服务不启动**，总表里记 `⊘` 并说明原因 |

**失败的方向是"宁可少起一个"。** 产物没准备好却照常起服务，就是把一份已知是旧的产物端给用户看
——那正是这个字段要防的事。要用当前产物启动，就显式加 `--no-build`，让"我在用旧产物"这件事
是你说的，不是脚本猜的。缺依赖时不代装（同 `--live` 那节第 3 条的理由），只报错并给出指引。

### 构建子进程拿到的是什么环境

**不是清单里的 `env`。** 构建只继承总脚本自己的环境，外加清掉 `npm_*` 前缀（我们自己多半就是
被 `pnpm dev:all` 起的，那批变量会让嵌套的 npm 认错项目根）。

理由：清单里的 `env` 描述的是**服务运行时**（`CO_SIGHT_MODE` 这类），把 `VITE_*` 那样的变量
喂给一次 `vite build` 会把运行期配置**打进产物**——那是"构建"和"配置"混在一起，产物从此
和这台机器的环境绑死。要影响构建，就在模块自己的构建配置里表达。

### 判据的两个细节

- **目录产物取它树里最新的文件时间**（"最后一次写产物的时刻"），单个文件产物的时间就是它自己。
  判据用的是**严格大于**：时间相同时刻不算陈旧。
- **遍历输入目录时跳过产物自身**。否则 `inputs: ["."]` 会把刚打完的产物当成"更新的输入"，
  导致永远陈旧、每次启动都白等一次构建。`node_modules`、`.git`、点开头的目录、
  以及 `dist` / `build` / `out` 这类名字的目录也一并跳过。

**尽量把 `inputs` 写成具体的源码路径，别图省事写 `["."]`。** 因为 `inputs: ["."]` 会把构建缓存
（`tsconfig.tsbuildinfo` 这类）也当成输入，它比产物新的话就永远重建。`cosight-viewer` 的清单
就是这么写的，可以抄。

### 什么时候**不**需要 `build`

**只在"开发态入口是产物"的模块上声明它。** `smart-factory` 的两个服务都是 `npm run dev`
（Vite 开发服务器直接读源码），产物对一个开发态进程没有任何影响——给它声明 `build` 只会
每次启动白等一次构建。这也是这个字段**可选**的原因。

## 端口冲突：三种归因，三种解法

**这个脚本占五个端口，任何一个被占都会让那半边"看着启动了、其实没起来"。**
所以启动前先一次性预检全部端口，再把占用者分成三类——三类的处理方式完全不同：

| 归因 | 怎么判出来的 | 脚本怎么做 |
|---|---|---|
| **上一次运行的残留** | 占用者的 pid **出现在**上次留下的状态文件里，但那个监督进程已经不在 | **自动回收**，并打印它杀了谁 |
| **上一次的运行仍在跑** | 同上，但监督进程还活着 | **不动**，提示你去那个终端 Ctrl-C |
| **别人的进程** | pid 不在记录里 | **不动**，报给你；要停得显式加 `--kill-ports` |

预检失败时打印的是三选一，而不是干巴巴一句"端口被占用"：

```
以下端口已被占用，本脚本不会主动接管别人的进程：
  4830   cosight-viewer           pid 12345（node）   不是本脚本起的进程
三选一：
  去那个终端 Ctrl-C（残留进程可直接 kill <pid>）
  pnpm dev:all --reuse       复用已在跑的实例，本脚本不碰它们
  pnpm dev:all --kill-ports  授权本脚本停掉占用者
```

### 为什么要落一个状态文件

残留不是猜的。`framework/.run/dev-all.json` 记着"本次运行起了哪些进程"：

```json
{
  "supervisorPid": 4096,
  "startedAt": "2026-10-15T03:12:44.000Z",
  "services": [
    { "label": "framework:server", "port": 4300, "pid": 4097, "listenerPid": 4102 }
  ]
}
```

**每起一个服务就落一次盘**，不是最后统一写——进程被 SIGKILL 时没有"最后"。
这份记录是下一次运行能认出"这是我自己的残留"的**唯一依据**；没有它，孤儿进程
（`detached` 起的 Vite / tsx watch，父进程被 `kill -9` 时会活下来）只能被归成"外来进程"，
于是每次都要求人来手工处理。

**为什么一条记录里有两个 pid**：`pid` 是 spawn 出来的直接子进程（`pnpm` / `npm` 包装器），
也是进程组的组长；`listenerPid` 是就绪之后探到的、**真正在监听端口**的那个进程——通常是
包装器的孙进程（`tsx watch` / `vite`）。两个往往不是同一个 pid，而 `ss` 看到的是后者。
只记组长的话，五个服务里有四个匹配不上，自己的残留会被当成"别人的进程"——
自动回收对它们就完全失效了。`listenerPid` 只能等就绪之后再补记，所以**它是后填的**；
没能就绪的服务这一项就是 `null`。

一个直接好处：**在另一个终端再跑一次 `pnpm dev:all` 不会误杀正在跑的那套**——
监督进程还活着，归因就是 `own-running`，脚本会停下来告诉你"上一次的启动仍在运行"。
`--reuse` 是跨过这一步的显式出口。

**一个文件只有一个主人。** 发现另一套总启动的监督进程还活着时，本次运行**不写这个文件**，
并说明原因——否则 `--reuse` 的那次会用它自己（通常只有一两个服务）的记事本把另一套
正在运行的服务的记录覆盖掉，那套服务之后就再也认不出来了。

### 回收：按端口 + 按记事本

两条路都要走，因为**有些残留根本不占端口**：

| 路径 | 收的是什么 |
|---|---|
| 按端口（预检） | 还占着端口的残留 |
| 按记事本（预检之前） | 记事本上记着、且监督进程已不在的**每一个**服务 |

第二条不能省：`tsx watch` / `vite` 这类监视进程在**程序崩了之后仍然活着**（它们的工作就是
等文件变化再重跑）。实测 `smart-factory:server` 因为缺依赖启动即崩，端口根本没绑上，
但它的 `npm run dev` → `tsx watch` 留在原地——只看端口的话永远发现不了它，
而它一旦哪天重跑成功，会把端口从新起的服务手里抢走。

不信任太旧的记事本（超过 24 小时就不按它回收，只作参考）：里面那些 pid 可能早就被系统
分配给别人了。同理，**记 pid 的前提是刚确认过**——按端口那条路是先看见"这个 pid 正听着
我们的端口"才动手的。

回收时按**进程组**发信号，而且要发的不止一个组：服务是 `detached: true` 起的（组长是那个
包装器），但真正监听的孙进程未必和包装器同组（实测 `pnpm run dev` 起的 tsx 落在一个中间组里）。
所以对「记事本里的组长组」「监听者自己的组」「监听者本身」都发一遍，全都尽力而为——
进程已经不在就吞掉 `ESRCH`。**两道保险**：组号 1 绝不发（`kill(-1)` 会打穿整台机器），
自己的进程组也绝不发（回收残留不该把自己收掉）。

### 两个回环地址都探

预检和就绪探测都会依次试 `127.0.0.1` → `localhost` → `[::1]`。

**这不是保险起见的冗余**：本仓库的 Vite 没设 `server.host`，默认的 `localhost` 在这台机器上
解析成 `::1`，于是**只绑 IPv6 回环**——`curl http://127.0.0.1:4310/` 拿不到任何东西，
`http://localhost:4310` 才通。浏览器两个都试，所以人肉访问感觉不到；只探 IPv4 的脚本会把
"其实已经起来了"误报成超时。4310 和 4110 实测都如此。

## `--live`：它到底改了什么

`cosight-viewer`（观测模块）有三段**会改动仓库外状态**的行为。先分清两个互不相干的目录：

- **CLI 源目录**（`CLAUDE_CONFIG_DIR` ?? `~/.claude`）：会话从这里的 `projects/` 读，
  `installHooks(true)` 也往这里的 `settings.json` 幂等地补自己的条目。
  **`COSIGHT_HOME` 管不到它**——它只用来推导 viewer 自有数据目录。
- **viewer 自有数据目录**（`DASHBOARD_DATA_DIR`）：数据库、日志、快照。

三段行为分别是：

1. **改全局配置**：`CO_SIGHT_MODE` 一旦设置，server 启动时会 `installHooks(true)`，
   往 CLI 源目录的 `settings.json` 补 hook（只替换本项目的旧条目，不碰用户其它 hook）。
   默认清单**不**注入 `CLAUDE_CONFIG_DIR`，所以观测页读得到真实会话，代价是启动时写一次
   `~/.claude/settings.json`。要完全不动全局配置，在清单的 `isolatedEnv` 里加
   `"CLAUDE_CONFIG_DIR": ".run/claude-home"`；此时观测页默认是空数据。
2. **不设 `CO_SIGHT_MODE` 的代价**：模块会没有数据库，并在 60s 后自检重启。
   所以清单里显式给了 `CO_SIGHT_MODE: "claude"`，而不是"什么都不设最安全"。
3. **`npm install` 的 `prepare`**：会在**本仓库**的 `.git/config` 写 `core.hooksPath = .husky`，
   静默关掉 Gerrit 的 `commit-msg` 钩子。所以这个脚本**永不执行任何 `npm install` / `pnpm install`**，
   依赖缺失时只报错并给出各模块自己的安装指引。这条没有"隔离模式"——只能不做。

`--live` 去掉清单里的 `isolatedEnv`：viewer 自有数据目录从 `.run/data` 落回真实位置
（`~/.cosight-harness/cosight-viewer`）。启用时总表下面会打一条醒目警告。
CLI 源目录在两种模式下都是真实的，区别只在 viewer 自有数据。

隔离出来的目录都在模块自己的 `.run/` 下（`cosight-viewer/.run/`），仓库根 `.gitignore`
里有一条无前导斜杠的 `.run/`，任意深度生效，不需要去改各模块自己的 `.gitignore`。

## 加一个新模块

1. **放运行时清单** `framework/docs/modules/<id>.module.json`（`id` / `entry` / `allowedOrigins` / `mounts`），
   见 [`module-integration-smart-factory.md`](module-integration-smart-factory.md)。这一步决定"页面能不能挂上"。
2. **放启动清单** `framework/docs/modules/<id>.launch.json`（下一个文件，字段见下表）。这一步决定"本机怎么跑"。
3. **开发态入口是产物的话，在启动清单里加 `build`**（见上文"模块产物"）。判据很简单：
   这个模块跑起来之后，浏览器读的是源码，还是某个 `dist/` / `build/` 目录里的文件？
   是后者就必须声明，否则 `git pull` 之后页面永远是旧的。走 `npm run dev`（Vite 开发服务器）
   的模块不需要。
4. **确认端口没被占、健康检查路径对**：`curl http://localhost:<port><readyPath>` 通不通。
5. `pnpm dev:all`。
6. **要跟着产物一起发出去的话，再加一份 `framework/docs/modules/<id>.artifact.json`**：
   进包哪些文件、构建怎么做、装到用户机器上用什么命令起。这份文件存在 ⇒ 模块进包（D41），
   与 `launch.json` 是两份、基准不同（模块目录 vs 仓库根），**不要互相复制**。
   格式与要求见 [`module-artifact-integration.md`](module-artifact-integration.md)。

**不用改 framework 的任何代码。** 清单同步是自动的：脚本会把 `docs/modules/<id>.module.json`
拷到 `$COSIGHT_HOME/modules/<id>/module.json`（内容逐字节相同则跳过），
因为它读得懂 `<id>.launch.json`，两份文件必须同名成对——漏了一个，
`server/tests/module-launches-doc.test.ts` 会在 CI 里拦住。

> `<id>.launch.json` **只留在仓库里，永不进运行时目录**。它是开发编排，属于版本控制。

### `<id>.launch.json` 字段

```jsonc
{
  "schemaVersion": 1,              // 必须 1
  "id": "smart-factory",           // 必须与 <id>.module.json 的 id、以及文件名前缀三处一致
  "moduleRoot": "smart-factory",   // 相对仓库根（也可写绝对路径），cwd 相对它解析
  "priority": 30,                  // 升序启动；模块之间建议留 10 的间隔便于插队
  "build": {                       // 可选：只在"开发态入口是产物"的模块上写，见上文"模块产物"
    "cwd": "client",
    "command": ["npm", "run", "build"],
    "inputs": ["src", "index.html", "package.json"],
    "outputs": ["dist/index.html"],
    "timeoutMs": 300000
  },
  "services": [
    {
      "name": "server",            // 小写字母/数字/连字符；同一条里不能重名
      "cwd": "server",             // 相对 moduleRoot；模块根写 "."
      "command": ["npm", "run", "dev"],   // "程序 + 参数"数组，不经过 shell
      "port": 4100,                // 1..65535 的整数；写成 "4100" 会让就绪探测静默失效
      "readyPath": "/api/smart-factory/v1/health",  // 以 / 开头，默认 "/"
      "readyTimeoutMs": 30000,     // 默认 30000
      "stripEnvPrefixes": ["npm_"] // 可选：注入前清掉这些前缀的环境变量
    }
  ],
  "env": {},                       // 只允许字符串值
  "isolatedEnv": {},               // 值按 moduleRoot 解析成绝对路径；--live 时整块不注入
  "notes": "…"                     // 可选，写给下一个人看的取舍说明
}
```

校验是**严过头**的：出现未知字段直接报错。写错字段名（`ready_path`、`port:` 写成字符串）
如果不能报错就会静默失效——而那正是最难查的一类。报错都带文件名和字段路径。
`build` 同样严格：`outputs` 必填（缺了就只能无条件重建，而这个字段存在的全部理由就是
**不**无条件重建），未知字段里最危险的是 `output` 少个 `s`——它会让"产物永远不存在"
变成"永远不重建"，正好把这个字段要防的事放回来。

一个模块只有一个服务时，日志标签是 `[<id>]`；多个服务才用 `[<id>:<name>]` 区分。

## 输出与排障

### 日志

前台运行，五路日志**带前缀**混排到当前终端：

```
[framework:server] {"level":30,"msg":"Server listening at 4300"}
[framework:web]      VITE v7.1.5  ready in 312 ms
[cosight-viewer:build] vite v7.1.5 building for production...
[cosight-viewer]     Dashboard on http://localhost:4830
[smart-factory:server] 服务已启动: http://localhost:4100
[smart-factory:web]     VITE ready
```

不用 `stdio: 'inherit'`：五个进程直接继承 stdio 会让日志互相穿插、分不清哪行是谁的。
前缀宽度取最长标签，终端里能竖着扫。

看某个服务的完整日志：把总脚本的输出重定向到文件后 `grep '^\[smart-factory:web\]'`。
想要干净的单独日志，直接跑那个模块自己的启动脚本。

### 就绪总表

全部起完后打印：

```
就绪总表
  ✓ framework:server  http://localhost:4300/api/health    1.2s
  ✓ framework:web     http://localhost:4310/              0.8s
  ✓ cosight-viewer    http://localhost:4830/health        0.5s
  ✓ smart-factory:server  http://localhost:4100/api/...   1.1s
  ✓ smart-factory:web     http://localhost:4110/          0.9s

模块产物
  = cosight-viewer:build  已是最新（源码不比产物新）

宿主页面    http://localhost:4310/
接口文档    http://localhost:4310/api/docs
模块页面    http://localhost:4310/observability    （cosight-viewer · observability）
模块页面    http://localhost:4310/agent-dev    （smart-factory · agent-dev）
```

后面那段是复用 `start.mjs` 的模块探活报告——模块注册表是"页面能不能挂上"的唯一依据，
主脚本和装配态脚本在这里必须给出一致的判断。

`✗ 未就绪` 只标注、不中断：模块慢或报错都该让人自己看日志，日志就在上面滚过去了。
`⊘ 未启动` 是另一回事：那是**刻意没起**（产物没准备好），原因紧跟着写在"模块产物"那段里。

### 常见现象

| 现象 | 原因 |
|---|---|
| 模块页面白屏、显示「模块尚未接入」 | `useModules()` 的 `staleTime` 是 `Infinity`——刚同步过清单的话需要**硬刷新**整页 |
| `http://127.0.0.1:4310` 打不开但 `localhost` 可以 | 见上文"两个回环地址都探"，这是 Vite 只绑 IPv6 的正常表现 |
| 提示"上一次的启动仍在运行" | 另一个终端里还跑着一套。去那边 Ctrl-C，或加 `--reuse` |
| Ctrl-C 之后端口还被占 | 先再按一次 Ctrl-C（第二次是强杀）。仍不行就 `pnpm dev:all`，下一次会按残留自动回收 |
| 某个服务反复 `✗ 未就绪` | 看它那几行前缀日志；通常是模块自己依赖没装（脚本不会替你装） |
| 改了模块源码、页面却没变 | 这个模块的开发态入口是产物（`dist`）而清单里没声明 `build`。补上；临时验证可先 `pnpm dev:all --rebuild` |
| `⊘ 未启动（产物没准备好）` | 该模块的构建失败了，往上翻它带前缀的日志。缺依赖就先去那个目录装依赖；确要用当前产物启动，加 `--no-build` |
| 每次启动都在重建，明明没改代码 | `inputs` 太宽（多半写成了 `["."]`），把构建缓存当成了输入。改成具体的源码路径 |
| 构建报"inputs 里的 X 不存在" | 清单里的输入路径写错了。这是**故意报错**的：写错的输入会让"改了源码却不重建" |

## 故障策略

| 情况 | 行为 |
|---|---|
| 框架服务意外退出 | **停掉全部、退出码 1**。宿主没了，"保证框架可用"这个目标已经不存在，继续挂着一堆模块只会让人以为还在跑 |
| 模块服务意外退出 | 只标注，不拖垮整体。开发态刻意比 `start.mjs` 的失败即停（D45）宽松：改代码时模块崩了还要能继续看其余部分 |
| 就绪超时 | 只标注，不影响其余服务 |
| 启动期任何报错 | 先把已经起来的服务收干净再退出，不留孤儿占端口 |

## 收尾

`SIGINT` / `SIGTERM` → 按**逆序**（后起的先停，模块先于宿主）给整个进程组发 `SIGTERM`，
宽限 10s 后 `SIGKILL`；**第二次 Ctrl-C 立即强杀**。另有一条 `process.on('exit')` 兜底，
保证异常路径也不留孤儿。

逆序不是洁癖：正序停会让上游先死，下游刷一屏"连接被拒"，看着像脚本自己出错了。

全部停干净后删掉状态文件；**若还有进程活着则保留它**——那正是下一次运行需要的线索。
删掉它等于把孤儿洗白成"来历不明的进程"。

## 相关

- `framework/scripts/dev-all.mjs` —— 本脚本
- `framework/scripts/lib/module-launch.mjs` —— 启动清单的读取与校验
- `framework/scripts/lib/module-build.mjs` —— 产物新旧判据 / 重建执行
- `framework/scripts/lib/port-guard.mjs` —— 端口的检测 / 归因 / 回收
- `framework/scripts/lib/runtime.mjs` —— 就绪探测、日志前缀、多进程收尾
- [`module-integration-smart-factory.md`](module-integration-smart-factory.md) —— 模块接入的样例
- [`framework-decisions.md`](framework-decisions.md) —— D24（跨源）、D27（开发入口）
