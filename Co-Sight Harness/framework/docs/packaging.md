# 产物打包与跨平台安装

> 这份文档讲的是**产物**：`pnpm package` 出来的那个压缩包长什么样、
> 为什么长这样、以及怎么验证它在别人的机器上真的能跑。
> 决策记录见 `framework-decisions.md` 的 D40（打包与安装）、D41（产物里的模块）
> 与 D42（多服务模块与 smart-factory 的生产链路）。

---

## 1. 产物形态

```
cosight-harness-<版本>-<时间戳>/
├── install.sh / install.cmd     一次性安装（预检 → 数据目录 → 配置文件 → 五个插件）
├── start.sh   / start.cmd       启动（薄壳，包住 start.mjs）
├── cosight.env.example          配置模板（两个平台同一份，全注释）
├── README.md                    用户侧说明（由 lib/artifact-readme.mjs 生成）
├── start.mjs                    真正的启动入口，0755
├── lib/                         start.mjs 的内部模块（runtime / module-probe / artifact-spec /
│                                env-file / node-version / text），0644
├── server/                      TypeScript 源码 + 已解析的 node_modules（零软链）
├── web/                         前端静态产物，由服务端静态托管
├── plugins/                     ← 五个 Claude Code 插件 + index.json（见 §1.1）
│   ├── index.json               坐标、版本、内容哈希、requires（打包期生成）
│   ├── drive/                   .claude-plugin/plugin.json + marketplace.json
│   ├── agent-genesis/
│   ├── agent-evaluator/         （安装 ID 是 goldeval@goldeval）
│   ├── skill-optimizer/
│   └── cosight-bot/             （安装 ID 是 cosightbot@cosightbot）
└── modules/                     ← 被装配进来的模块，一个模块一个目录（见 §6）
    ├── cosight-viewer/
    │   ├── module.json          运行时契约（宿主用它拼 iframe 地址）
    │   ├── artifact.json        装配态启动清单（start.mjs 按它拉起）
    │   ├── package.json
    │   ├── server/  scripts/    生产态需要的源码
    │   ├── client/dist/         前端构建产物
    │   └── node_modules/        生产依赖（纯 JS，实体树）
    └── smart-factory/           （linux-x64 + win32-x64）
        ├── module.json / artifact.json
        ├── db-init.mjs          启动前把模板库复制到用户数据目录
        ├── web-server.mjs       静态托管 + /api/WS 同源代理（随包搬运的辅助件）
        ├── db-template.sqlite   打包期生成的空库模板
        ├── server/              dist / node_modules / prisma
        └── web/dist/            前端构建产物
```

产出两个归档：`cosight-harness-<版本>-<时间戳>.tar.gz` 与 `.zip`，
外加一份 `*.manifest.txt` 条目清单。两个归档**内容完全等价**（见 §3）。

时间戳形如 `20261026-143015`（本地时间），归档名与归档内的顶层目录名共用同一个串：
同版本的多份构建不会互相覆盖，`.package/` 里留着的上一份既是回滚点也是对照物，
解压到同一处也不会串。冒烟按 manifest 的 mtime 自动选最新一份，不需要手动指定名字。

命令：

```bash
pnpm package              # 打包（含全部打包期断言，失败即退出、不留半成品）
pnpm smoke:package        # 打包 + 解压 + 模拟安装 + 真启动一遍
pnpm smoke:package --skip-package   # 复用已有归档，只跑后面的验证
```

### 1.1 插件载荷

五个 Claude Code 插件随产物分发，源码在仓库根目录，坐标写在
`framework/scripts/artifact/plugins.json`（宿主侧声明，不改插件仓库）：

| 源码目录 | 安装 ID | 版本 |
| --- | --- | --- |
| `drive/` | `drive@zte-ai-lab` | 2.3.4 |
| `agent-genesis/` | `agent-genesis@agent-genesis` | 0.22.0 |
| `agent-evaluator/` | `goldeval@goldeval` | 1.0.0 |
| `skill-optimizer/` | `skill-optimizer@skillx` | 1.0.0 |
| `cosight-bot/` | `cosightbot@cosightbot` | 0.1.0 |

- 复制进产物时排除测试与缓存（`tests/`、`__pycache__/`、`.pytest_cache/`、
  `.ruff_cache/`、`*.pyc`、`.git/`、`node_modules/`、`.env`、`work/`、`output/`、
  `.agent-genesis/`，以及**顶层的** `.claude/`）；
- 复制前后各算一次内容哈希，必须相等；哈希算法与运行期 `lib/plugin-hash.mjs`
  是同一套（排序后的 POSIX 相对路径 + 文件字节 → SHA-256 前 16 位）；
- 生成的 `plugins/index.json` 是运行期唯一可信来源：版本来自各插件的
  `plugin.json`，打包期与 `plugins.json` 的坐标交叉校验，不一致即打包失败；
- 运行期 `start.mjs` 按 index 判断装 / 升 / 重装 / 跳过，细节见
  [`plugin-install.md`](./plugin-install.md)。

## 2. 一份通用包

同一个包里同时含 **linux-x64** 与 **win32-x64** 两套原生依赖，用户不需要先判断
"我该下哪个包"。拆成两份时，判断错的表现是启动失败或缺原生件——
一个用户读不懂的错误；而多出来的体积（约 15–20 MB）只是一次下载的事。
**范围明确不含 macOS 与 ARM**（见 §3 怎么加平台）。

## 3. 跨平台原生件：机制与写法

产物里跑服务端的是 TypeScript 源码（`build` 只做 `tsc --noEmit`），
所以真正需要分平台的是两个**原生**依赖：

| 包 | Linux x64 | Windows x64 |
| --- | --- | --- |
| libsql（SQLite 绑定） | `@libsql/linux-x64-gnu` | `@libsql/win32-x64-msvc` |
| esbuild（tsx 的转换器） | `@esbuild/linux-x64` | `@esbuild/win32-x64` |

Windows 那一列的名字**带 ABI 后缀**，不是把 `linux` 换成 `win32` 就完事：
libsql 用 `@neon-rs/load` 的 `currentTarget()` 拼包名再 `require`，
它在 win32 + x64 上给的是 `win32-x64-msvc`。这张表抄自源码，不是猜的，
而且写成了常量 + 测试（`lib/project.mjs` 的 `nativePackagesFor()` 与
`scripts/tests/project.test.mjs`）。

**pnpm 侧怎么写**（这一条是实测出来的，别照直觉改）：

```bash
pnpm deploy --filter harness-server --prod \
  --config.node-linker=hoisted --config.preferSymlinkedExecutables=false \
  --os=linux --cpu=x64 --os=win32 --cpu=x64
```

- 平台只能从 **CLI 旗标**给：`--os=` / `--cpu=`（pnpm 11 里读取这两个的开关是
  `overrideSupportedArchitecturesWithCLI`）。`--config.supportedArchitectures.os=` 这条路
  **不生效**。
- 这些旗标**刻意没有**写进 `pnpm-workspace.yaml`。写进去同样能让 deploy 出双平台原生件，
  但副作用落在开发态：每个开发者的 `node_modules` 也会多拉两份可选依赖（约 +20 MB）。
  我们只在打包时那一次需要它，所以放在命令里，并由 `deployPlatformArgs()` 统一生成、
  由测试钉住（`ARTIFACT_TARGETS` 是唯一真相）。

**加一个平台**（例如 darwin-arm64）：在 `ARTIFACT_TARGETS` 加上目标、
在 `nativePackagesFor()` 的映射表里补上该平台的原生包名（名字去
`@neon-rs/load` 的 `currentTarget()` 与 esbuild 的 `install.js` 里对，别猜）。
测试会立刻要求你把映射补齐——这是刻意的：漏一个包时，报错会发生在用户的机器上。

**裁平台**：从 `ARTIFACT_TARGETS` 里去掉即可，体积会相应下降。

## 4. 零软链

打包时的第二次安装（补 tsx 那一次）用 `--config.node-linker=hoisted`，产出一棵
**实体目录树**：符号链接 230 → 0。于是 zip 与 tar.gz 等价，
Windows 自带解压器与 7-Zip 都能正确还原。

这不是"更保险"：软链在产物里没有任何收益（产物是要被解压的独立物，没有共享 store
可言），而它的失效方式是**静默的**——解压器不建软链、落一个 0 字节文件，
然后在运行时报一个和软链无关的错。所以它被做成打包期断言，而不是 README 里的一句提醒。

## 5. 用户侧脚本的真源

`framework/scripts/artifact/` 下的五个文件是产物里那五个文件的**唯一真相**：
打包时原样搬运并规整，不存在"打包时另写一版"的分叉。两条编码规则必须在打包期守住，
因为**在 Linux 开发机上完全看不出来**（文件本身是合法的，只有别人的机器会炸）：

| 规则 | 为什么 | 守的方式 |
| --- | --- | --- |
| `.cmd` 纯 ASCII | `cmd.exe` 按 ANSI（中文系统是 GBK）逐字节读批处理，UTF-8 中文注释会乱码，`chcp 65001` 救不了（解析器已读过那一行） | 打包期 `assertAsciiOnly`（带行号列号报错）+ 测试 |
| `.cmd` 用 CRLF | cmd.exe 对 LF-only 批处理的容错很差 | 打包期规整 + 断言 |
| `.sh` 用 LF | CRLF 的 `.sh` 在 Linux 上报 `bad interpreter: /bin/sh^M` | 同上 |
| 可执行脚本有 shebang | 解压后 `./start.sh` 直接可用 | `loadArtifactScript` 校验 |

（仓库里没有 `.gitattributes`，也刻意没加：行尾在打包期统一规整，
仓库内部用哪种行尾都不影响产物。）

## 6. 产物里的模块

框架本身只提供外壳；会话、观测这些页面由模块提供。模块进产物走的是**旁挂清单**：

```
framework/docs/modules/<id>.artifact.json   ← 真源（人工维护）
                    │ 打包时原样拷成
                    ▼
产物/modules/<id>/artifact.json             ← start.mjs 读它拉起进程
产物/modules/<id>/module.json               ← 宿主读它拼 iframe 地址
```

**判定规则只有一条**：`docs/modules/<id>.artifact.json` 存在 ⇒ 这个模块进产物。
没有硬编码名单；打包时会打印「已打进 / 未打进（缺少 `<id>.artifact.json`）」两栏，
漏一个模块必须有人看得见。运行时契约（`<id>.module.json`）描述"怎么嵌"，
装配态清单（`<id>.artifact.json`）描述"怎么打包、怎么启动"——两份清单的分工与理由见 D41。

清单的字段（schema v1，未知字段一律报错）：

| 字段 | 作用 |
| --- | --- |
| `id` / `moduleRoot` / `priority` | 模块 id、源码目录（相对仓库根）、启动顺序 |
| `env` | 模块级环境变量，并入每个服务与 `prepare`（服务同名键优先） |
| `prepare[]` | 起服务前的一次性动作（建库、生成配置）：命令、工作目录、超时。失败时只跳过该模块的服务 |
| `startAfter` | 目前只支持 `"framework"`：等框架 `/api/health` 就绪后再起（需要 `.module-token` / 框架基址的模块） |
| `platforms` | 该模块支持哪些 `<os>-<arch>`；未列出的平台启动时跳过（打包仍会带上文件） |
| `bundle.include` / `bundle.exclude` | 进包的文件（目录会逐层展开；include 写错路径直接报错） |
| `bundle.build` / `bundle.builds` | 一条或多条构建：命令、工作目录、输入、产物、超时、构建期 env；产物不旧时不执行 |
| `bundle.assets` | 从**仓库根**取辅助**文件**或**目录**放进模块目录（如框架随包发的 `web-server.mjs`；目录可用 `exclude` 按段名剔子树） |
| `bundle.database` | 打包期用 `COSIGHT_HOME=<临时目录>` 跑一次建库命令，把生成的库作为模板进包 |
| `bundle.dependencyRoots` | 前后端各自装依赖时，到哪些子目录核对 `package.json` 的依赖是否齐全 |
| `bundle.install` | **缺件时才执行**的补齐命令（按顺序试、补上就停）；不写就没有自动修复 |
| `bundle.required` | 额外断言必须在产物里的路径（构建产物之外的运行时文件） |
| `bundle.executable` | 必须保留可执行位的文件（如 SDK 自带的 `claude` 二进制） |
| `services[]` | 启动命令、工作目录、端口、探活路径与超时、环境变量 |
| `notes` | 取舍说明（给人读的） |

几处刻意的规则：

- **清单里的 `cwd` 必须在模块目录内**。它会变成一次 `spawn`，写错一个 `../../..`
  会让模块跑到框架目录外面，而现象完全看不出是清单的问题。
- **`command[0] === "node"` 会换成当前解释器**（`process.execPath`）。产物不依赖
  PATH 上的 `node`，也就不存在"用户装了两个 Node、跑错版本"。
- **只支持两个占位符**：`{{dataDir}}`（用户数据目录，由 `start.mjs` 注入）与
  `{{frameworkUrl}}`（框架实际监听地址，端口可能来自 `cosight.env`）。
  别的 `{{...}}` 一律报错——静默留下原样会让模块在一个叫 `{{data-dir}}` 的目录里建库。
- **打包时不做"猜出来的安装"**（D34）。`npm install` 会联网、会改模块的 lockfile、还会触发
  `prepare` / `postinstall`——`cosight-viewer` 的 `prepare` 会往仓库 `.git/config` 里写
  `core.hooksPath`，把 Gerrit 的 commit-msg 钩子静默关掉。所以自动修复**只跑清单里写明的
  `bundle.install` 命令**（一般带 `--ignore-scripts`），并且**只在断言发现缺件时才跑**、
  补上就停：正常打包一次安装都不执行。补不上仍然带着"缺什么、在哪补"失败；
  `pnpm package --no-fix` 可以整轮关掉自动修复（离线 / 只读的打包机）。
- **代码生成也属于构建，要自己声明**。构建产物来自 schema / 接口描述时（smart-factory 的
  Prisma Client 就是），生成物在 `node_modules/` 里、是 gitignore 的，改 schema 不会让它
  自动更新，`tsc` 只会报「某个字段不存在」。所以 `<id>.artifact.json` 的 `bundle.builds`
  里单独写一条 `npm run prisma:generate`，放在 `npm run build` 之前——`bundle.install` 不
  承担这件事：它只在断言发现缺件时才跑，而这里缺的是「新」，不是「有」。
- **模块树同样零软链**。`node_modules/.bin` 里天然是一堆软链（cosight-viewer 有 15 条），
  它们只服务于 `npm exec` 与 package script，必须在 `exclude` 里去掉了。
- **一个模块可以声明多个服务**。每个服务各有 `port` / `readyPath`，`start.mjs` 逐个探活；
  任一服务起不来默认让整次启动失败（退出 13）；`--keep-going` 时只跳过该模块、记一行 `✗`。
- **前端写死根相对 `/api/...` 时必须同源**。页面在 4110、接口在 4100 时，`/api/...`
  会被浏览器解析到 4110，接口全部 404（WebSocket 同样）。smart-factory 用随包搬运的
  `web-server.mjs` 把静态托管、SPA 回退、HTTP 与 WebSocket 代理合到一个端口；
  它由 `bundle.assets` 从框架侧搬进来，**模块源码一行没改**。
- **`prepare` 在每次启动前跑、但必须幂等**。smart-factory 的建库只在目标库不存在时
  复制模板，所以第二次启动不会覆盖用户数据。打包期的模板生成用临时 `COSIGHT_HOME`，
  不会往模块源码树里写库文件。
- **`startAfter: "framework"` 的模块在框架就绪后才起**。需要读
  `$COSIGHT_HOME/.module-token` 或调框架模块面接口的模块必须这样声明——令牌是框架
  启动时创建的，起早了只会拿到连接失败。启动顺序因此是：立即模块 → 框架 → 延迟模块。

`start.mjs` 在产物布局下（`modules/` 存在）按 `priority` 升序拉起模块、等各自
`readyPath`、再拉起框架服务端。**任一模块起不来或框架 30s 内不就绪，整次启动失败**：
按逆序停掉已起进程后退出 **13**（D45）。旧的"记一行、继续"语义保留在 `--keep-going` 里。
平台不支持的模块与 `--skip-module` 排除的模块不算失败。
仓库布局没有 `modules/`，开发态仍然只有 `pnpm dev:all`（D27 不变）。
`--no-modules` 可以只起框架。

给模块作者看的对接要求（一定要提供什么才能进包）见
[`module-artifact-integration.md`](./module-artifact-integration.md)。

## 7. 打包期断言清单

`pnpm package` 的取向是**宁可打不出包，也不产出一个坏包**。以下每一条都对应一类
"只在别人机器上发作"的错：

| 断言 | 守的错 |
| --- | --- |
| 四个平台原生包的目录实体都在 | Windows 上 `ERR_MODULE_NOT_FOUND` |
| 整棵树里 0 条符号链接 | 解压器不建软链 → `tsx` 变 0 字节文件 |
| `tsx` / `harness-shared` / `fastify` / `@libsql/client` 是实体目录 | 同上，钉住关键入口 |
| `start.mjs` 的 import 闭包 ⊆ 搬运清单 | 少搬一个 `lib/*.mjs`（本机毫无征兆） |
| `.cmd` 的 ASCII 与 CRLF、`.sh` 的 LF | 控制台乱码 / `bad interpreter` |
| 入口与安装脚本可执行位 | 解压后 `./start.sh` 失败 |
| `bundle.executable` 列出的文件存在且带可执行位 | 按平台装出来的原生件被重装依赖（`npm ci` 会删整个 `node_modules`）清掉，打进一个启动即失败的包 |
| 归档写完**读回逐条校验**（内容、大小、清单条目数） | 写坏的归档 |
| 归档条目可复现排序 | diff 噪声 |
| 每个进包模块的 `module.json`、`artifact.json`、include 里的文件、构建产物的 `outputs` 都在 | 少了某个页面/入口，现象是 iframe 白屏 |
| 模块 `package.json` 的每个 `dependencies` 都在它的 `node_modules` 里 | 用户机器上第一次 `require` 才 `ERR_MODULE_NOT_FOUND`；缺件时先按 `bundle.install` 自动补，补不上再报错，并按缺的依赖根列出 `cd … && npm ci`（有 `package-lock.json` 时）这类可直接粘贴的命令，没有锁文件才给 `npm install` |
| 自动修复只在缺件时跑，且只跑与缺件位置相关的步骤 | 换一台 checkout 就挂在与本次改动无关的缺件上；反过来，在没缺东西的目录里白装一遍，几分钟且动到别人的工作树 |
| 模块树零软链（`bundle.exclude` 去掉 `.bin` 之后） | Windows 解压出 0 字节文件 |
| 构建命令返回 0 之后**再判一次陈旧** | 构建脚本缺工具时安静跳过，包里的页面是旧的 |
| 五个插件目录、两份 manifest、`plugins/index.json` 都在，且 index 里的哈希与目录重算结果一致 | 少一个插件或载荷被改过，用户机器上装到一半才失败 |
| 归档读回后逐个校验 `plugins/` 的 `requiredPaths` | 写坏的归档 |

## 8. 体积

| 项 | 只有框架 | 现在（含 cosight-viewer + smart-factory + 五个插件） |
| --- | --- | --- |
| tar.gz | 29.5 MB | **378.7 MB** |
| zip | 33.7 MB | **396.2 MB** |
| 条目数 | 7908 | **33910**（其中符号链接 0 条） |
| 原始大小 | 92.9 MB | **950.8 MB** |

两列差出的约 349 MB（压缩后）里，cosight-viewer 只占约 15 MB、五个插件合计
约 3 MB（原始约 9 MB，已去掉测试与缓存）；其余来自 `modules/smart-factory`，
其中最大的一项是 Claude Agent SDK 的可执行件——**两个平台各一份**（linux-x64
255 MB、win32-x64 259 MB），其次是 `@prisma/client` 与两个 Prisma 查询引擎。

两条模块**都不含**构建工具链：cosight-viewer 的 `client/node_modules`（184 MB）
与 smart-factory 的 `web/node_modules`（Vite / TypeScript）只服务于打包期构建。
smart-factory 还刻意排除了 `prisma` CLI（71 MB）、`@prisma/engines`（45 MB）、
`typescript`（23 MB）与 musl 版 SDK（249 MB）——这些都是构建期或另一平台的东西。

**两个平台都支持**：smart-factory 的清单里是
`"platforms": ["linux-x64", "win32-x64"]`，产物因此同时带两套 SDK 可执行件
（linux 约 255 MB、win32 约 259 MB）与两个 Prisma 查询引擎。这是刻意的取舍：
一份包分不出"我该下哪个"，而判断错的表现是启动失败或缺原生件——一个用户读不懂
的错误（同 §2 的理由）。macOS 与 ARM 仍不在范围内。

## 9. 怎么验证

```bash
pnpm test:scripts            # 打包相关纯函数与脚本规则的快速测试（毫秒级）
pnpm lint && pnpm run typecheck
pnpm package                 # 打包期断言全绿
pnpm smoke:package           # 端到端：系统 tar/unzip 解压 → 安装 → 启动 → HTTP 断言
```

### 在 Windows 打包机上

仓库的 workspace 只覆盖 `framework/*`，两个模块的依赖要按各自 README 装好
（`cosight-viewer` 与 `cosight-viewer/client`、`smart-factory/server` 与
`smart-factory/web`）。产物要同时覆盖 linux-x64 与 win32-x64，而 Prisma 的两个
查询引擎只会按当前平台生成，先跑一次准备脚本补齐：

```bash
node smart-factory/scripts/prepare-native-artifacts.mjs
pnpm package
```

- Prisma 的两个查询引擎（`libquery_engine-debian-openssl-1.0.x.so.node` 与
  `query_engine-windows.dll.node`）：靠 `smart-factory/server/prisma/schema.prisma`
  的 `binaryTargets` 生成，脚本发现缺哪个就重跑一次 `prisma generate`。

脚本对打包机平台不作假设，缺哪个补哪个；幂等，且**只补件、不装依赖**。
Claude Code CLI 是用户侧外部前置，不在产物里，脚本也不再下载任何 Anthropic 的
SDK / 平台二进制。

> **现在打包会自己补这一步。** `smart-factory.artifact.json` 把这条脚本写进了
> `bundle.install`，断言发现原生件缺失时（典型场景：`npm ci` 删掉整个 `node_modules`，
> 补好的另一平台原生件随之消失）打包会先自动跑它，再重查一遍。上面这行手工命令仍然可用，
> 也只是手工跑一遍同样的东西；补不上时错误信息里也会把它印出来。
> 想让打包完全不执行安装类命令，用 `pnpm package --no-fix`。

`pnpm smoke:package` 用的是**系统自带**的 `tar` 与 `unzip`，不是仓库里的归档读写器——
同一份代码读自己写的归档证明不了什么。它还会：

1. 用独立读取器解压，逐条比对条目数与清单；
2. 断言解压后的可执行位、零软链、关键依赖入口；
3. 跑产物自己的安装入口——POSIX 上是 `sh install.sh`，Windows 上是
   `node start.mjs --install`（也就是 `install.cmd` 背后那一条，`cmd.exe` 不参与），
   断言数据目录与 `cosight.env` 真的被建出来；
   同时断言 `plugins/` 五个目录、`index.json` 与各插件 manifest 齐全，且
   `index.json` 里的版本/哈希与目录重算结果一致；
4. 往生成的 `cosight.env` 里改一个非默认端口，再跑启动入口，
   断言**监听端口确实变成配置文件里那个**（证配置真的生效，而不是"文件在那儿"）；
5. 从 tar 与 zip 两棵解压树各启动一次，断言 `/api/health` 就绪、首页是 HTML、
   引用的脚本可下载，然后干净关停；
6. **把模块也走一遍端到端**：产物里 `modules/<id>/{module.json,artifact.json}`
   可解析、启动入口在、清单之间的端口一致、`bundle.required` 的路径都在、
   `bundle.executable` 的可执行位还在；启动后每个服务的 `readyPath` 2xx
   （页面服务断言 HTML 与 `cosight-viewer` 的 capability 路由，API 服务断言 JSON）；
   `/api/modules` 里注册着这些模块；smart-factory 额外走四条链路：
   **同源 API 代理**（`/api/smart-factory/v1/health` 返回后端 JSON）、
   **SPA 深链接**（回 index.html）、**WebSocket 升级**（101）、
   **首次建库**（`$COSIGHT_HOME/smart-factory.db` 非空）；
   关停后**框架与所有模块服务的端口都释放**（证明进程组回收，而不是只杀了父进程）；
   清单 `platforms` 不含当前平台的模块**按同一条规则跳过并打印出来**，既不探活、
   也不写进小结里的"已验证"（当前两个模块都声明了 linux-x64 + win32-x64，所以这条
   规则在 Windows 上不再命中，是留给定平台模块的）；
7. 模块端口在启动前也要求空闲：占着的那个会被 `start.mjs` 当作"已经在跑"复用，
   关停时它不归冒烟管，"端口已释放"的断言就会变成误报。

冒烟的数据目录是**临时目录**，并在 `cosight.env` 里连 `COSIGHT_HOME` 一起写死——
`install.sh --home` 只影响安装那一次，`start.sh` 不继承它。

`pnpm test` 会先跑脚本测试再跑各工作区测试；`pnpm verify` 在 2026-10-20 是
全绿的（脚本 222、shared 91、server 346、web 343）。此后为 Windows 适配补了
21 条脚本测试，合入 upstream 的卸载与内置专家两个特性后又多了 18 条
（2026-10-27 实测脚本 261 条：259 通过、2 跳过）。

冒烟里的 `install.sh` / `start.sh` 都带 `--skip-plugins`：插件安装会写
`$CLAUDE_CONFIG_DIR/plugins`，冒烟不能拿开发机真实的 `~/.claude` 当靶子，
也不应要求冒烟机装好 Claude Code。插件载荷与安装行为分别由 §7 的断言与
`plugin-install.test.mjs` 覆盖。

## 10. Windows：验过什么、没验过什么

**打包与冒烟已在 Windows 上跑通**（Windows 10 + Node 22）：`pnpm package` 出包，
`pnpm smoke:package` 用系统 `tar` / `unzip` 解出两棵全新的树、逐条比对 33910 个条目、
跑安装、按 `cosight.env` 里的端口启动、探活模块、关停后确认端口释放。
**两个模块都在 Windows 上真的被拉起**：3 个模块服务就绪并出现在 `/api/modules`，
smart-factory 的同源 API 代理、SPA 深链接、WebSocket 101、首次建库全部通过
（3144 个目录在两种归档的树上都逐条核对过）。

为此改掉的都是**只在非 Linux 打包机上才发作**的地方，不是为了本机能跑而绕过去的：

| 症状 | 修在哪 |
| --- | --- |
| `spawnSync('pnpm')` 报 `ENOENT` / `EINVAL`（Node ≥ 18.20 之后不再走 shell） | `lib/cli-exec.mjs` 的 `resolveExecutable` + `buildSpawnSpec`；`package.mjs`、`dev-all.mjs` 都改走它 |
| Windows 没有可执行位，`fs.stat` 一律报 `0666` | 归档条目由 `withExecutableModes` 显式补 `0755`；解压后的可执行位断言只在 POSIX 上做 |
| PATH 里的 `tar` 是 MSYS 版 GNU tar，会把 Windows 绝对路径当远程主机 | 优先用 `%SystemRoot%\System32\tar.exe`（原生 bsdtar）；归档一律切到所在目录、只传文件名 |
| bsdtar 把非 ASCII 条目打印成 `\342\230\203` | 比对前用 `unescapeListedName` 还原（只是打印层转义，解出来的文件名是对的） |
| Info-ZIP 对目录时间戳/权限报 warning 并以 1 退出 | 只放行**元数据类**告警，并由"清单里每个目录都必须真的建出来"兜底 |
| 冒烟杀掉 `sh` 壳子后 node 变孤儿，端口不释放 | Windows 上直接跑 `node start.mjs`（`start.cmd` 干的就是这件事）；关停按进程树 `taskkill /T` |
| 模块目录清单是相对归档根的，与已剥掉顶层的 `root` 拼成 `base/base/...` | 目录名先剥掉顶层前缀，再拼 `root` |
| `bsdtar -tzf` 不给目录条目加尾斜杠（GNU tar 才加），"每个目录都在"退化成空转、还打印"0 个目录都在" | tar 侧改用 `-tvzf` 按首列 `d` 取目录，并断言列表非空——下次清单格式再变会直接炸，而不是静默跳过 |
| **在真终端里**（双击 `start.cmd`）服务进程以退出码 1 结束、终端里**一条日志都没有**；同一条命令在冒烟（管道）里完全正常 | 框架服务不再 `stdio: 'inherit'`：`detached` 的子进程继承的是父进程控制台的句柄，而它已不在那个控制台会话里，第一次写日志就 `EBADF`，Node 当成未捕获错误直接退出。改走管道 + `forwardVerbatim` 原样转发（`runtime.test.mjs` 钉住"不加前缀、不改行尾"） |

还有一条**不是验证得出的、但会拦住 Windows 用户**的环境前提：`drive` 与
`agent-genesis` 的 hooks 调用的是 `python3`，而 Windows 版 Python 只提供
`python.exe`。预检会把它拦成 block，并给出可执行的做法（在 Python 安装目录里
复制一份 `python3.exe`）。插件代码不改——见
[`install-preflight-and-plugins.md`](./install-preflight-and-plugins.md) 里那条
"Windows 上按设计拦住"的决策。

### 10.1 Windows 人工验收清单（仍需人工走一遍）

冒烟直接跑 `node start.mjs`，覆盖的是 `.cmd` 背后的同一份逻辑；"双击 → `cmd.exe`
开着窗口 → `pause` 不闪退 → 浏览器打开页面"这一段是 shell 交互，脚本验不了。
拿到 Windows 机器上照下面走一遍：

1. 把 `cosight-harness-<版本>-<时间戳>.zip` 拷到 Windows 上，**用资源管理器右键解压**（不要用命令行），
   确认 `start.mjs` 旁边有 `install.cmd`；
2. 双击 `install.cmd`：应看到 Node 预检 → 数据目录 → 生成 `cosight.env`，
   最后打印下一步提示；窗口以 `pause` 结尾，不会一闪而过；
3. 双击 `start.cmd`：应在浏览器打开 `http://127.0.0.1:4300/` 后能看到界面，
   终端里那行"已就绪"出现，并且模块行显示 `cosight-viewer` 与 `smart-factory`
   都是 `✓` 已就绪（两个模块在 Windows 上都由产物拉起，见 §9、§10.2）；
4. 首页的「新建对话」应落在**对话页**（不是观测页）；左侧导航点「观测」应落在
   会话列表（这两步同时验了模块被拉起与 capability 路由）；
5. 界面里新建一个工作区、打开工作区文件面板，确认功能正常（这一步顺带验了
   sqlite 的 win32 原生件）；
6. 把 `cosight.env` 里的 `COSIGHT_PORT` 改成 8081 再重启，确认监听端口跟着变；
7. 在窗口里按 **Ctrl-C**，确认框架与模块都退出、终端回到提示符、相关端口都释放
   （框架 4300 与各模块端口）；

任何一步与预期不符，把终端里的完整输出留下来——`node start.mjs --self-check`
会打印平台、Node 版本、布局、数据目录、配置文件五项，是报障时最有用的一条命令。

## 11. 刻意不做的事

- **不带 Node 运行时**：安装脚本只做预检与下载指引。带运行时意味着要跟着选版本、
  打进 40+ MB、还要处理两个平台的解压差异与许可证——换来的只是"少装一个 Node"。
- **不装到系统目录、不 sudo、不改 PATH、不注册服务、不建快捷方式**：
  产物自带依赖树、无编译步骤，"安装"只剩预检、数据目录、一份配置。
  固定安装位置只会带来权限与卸载问题。**卸载 = 删目录。**
- **不做 macOS / ARM**（用户已确认范围）；加平台的路子见 §3。
- **不假装验过没验的部分**：双击 `install.cmd` / `start.cmd` 与浏览器里的点击仍靠
  §10.1 的人工清单；冒烟覆盖的是它们背后的 `start.mjs`。smart-factory 在 Windows
  上验到的是"服务起来 + 静态/SPA/API/WS/建库四条链路"，**没有**验"真的跑一次 agent"
  （那要框架配好模型与凭据，会花掉真实额度）；SDK 自带的 `claude.exe` 只验到
  `--version` 能执行。这一条写在这里，是为了不让"冒烟全绿"被读成"智能体功能已验证"。
