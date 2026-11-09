# 插件安装：装了什么、装到哪、怎么排障

> 面向用户与运维。设计理由与实现细节见
> [`install-preflight-and-plugins.md`](./install-preflight-and-plugins.md)。
>
> 一句话：`install.sh` / `install.cmd` 会把包里自带的五个 Claude Code 插件
> 装进**当前用户的** Claude Code（`user` scope），装完退出；
> `start.sh` / `start.cmd` 在产物布局下做同一件事，然后才拉起模块。

## 1. 装的是哪五个

| 插件目录 | 安装 ID | 版本来源 | 备注 |
| --- | --- | --- | --- |
| `drive` | `drive@zte-ai-lab` | `drive/.claude-plugin/plugin.json` | hooks 需要 `python3` |
| `agent-genesis` | `agent-genesis@agent-genesis` | `agent-genesis/.claude-plugin/plugin.json` | hooks 需要 `python3` |
| `agent-evaluator` | **`goldeval@goldeval`** | `agent-evaluator/.claude-plugin/plugin.json` | 目录名与插件名不同 |
| `skill-optimizer` | `skill-optimizer@skillx` | `skill-optimizer/.claude-plugin/plugin.json` | 安装时 CLI 可能提示一条 README 相关 warning |
| `cosight-bot` | `cosightbot@cosightbot` | `cosight-bot/.claude-plugin/plugin.json` | 技能里的脚本需要 `python3` |

安装 ID 是 `<插件名>@<marketplace 名>`，**不是目录名**——`agent-evaluator`
装出来叫 `goldeval`。插件源码不改一行：产物里的 `plugins/` 是只读载荷。

## 2. 装到哪

Claude Code 自己决定最终安装位置；宿主只保证两件事：

```text
$CLAUDE_CONFIG_DIR/plugins/marketplaces/<marketplace>/   ← 产物载荷的副本
$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json        ← Claude Code 写的状态
$CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json       ← Claude Code 写的状态
```

`$CLAUDE_CONFIG_DIR` 默认是 `~/.claude`（Windows：`%USERPROFILE%\.claude`）。

- 先把 `plugins/<dir>/` 复制到 `plugins/marketplaces/<marketplace>/`：
  marketplace 的注册只记路径，而解压目录可能被移动或删除，指向副本才长期有效。
- 再用 `claude plugin marketplace add <副本目录> --scope user --json` 注册。
- 最后 `claude plugin install <id> --scope user --json -y`。

查询实际状态：

```bash
claude plugin list --json
claude plugin marketplace list --json
```

## 3. 什么时候会写

| 入口 | 行为 |
| --- | --- |
| `./install.sh` / `install.cmd` | 预检 → 初始化 → **装插件** → 退出 |
| `./start.sh` / `start.cmd`（产物布局） | 预检 → **装插件（按需）** → 启动模块与框架 |
| `node start.mjs --self-check` | **只读**：只报告，不写任何东西 |
| 仓库开发态（`pnpm dev:all`） | 不装；要装就显式 `node framework/scripts/start.mjs --install` |

"按需"的判定同时看**版本**与**内容哈希**：

| 现状 | 动作 |
| --- | --- |
| 没装过 | 安装 |
| 版本不同 | 升级（`plugin update`；失败则退化为卸载重装） |
| 版本相同、内容不同 | 卸载后重装 |
| 版本与内容都相同 | 跳过，不发任何写命令 |

因此重复运行是安全的；发布新产物时把 `plugins/` 换成新的，下次启动会自动刷新。
安装期间 `$COSIGHT_HOME/.install.lock` 防止两个进程同时改 Claude Code。

## 4. 不想让它动我的 Claude 环境

```bash
./install.sh --skip-plugins
./start.sh --skip-plugins
```

跳过之后模块照常启动，只是依赖插件的能力不可用（专家页、drive 的保护钩子等）。
`--self-check` 本来就不写盘。

## 5. marketplace 同名冲突

产物里的 marketplace 名是固定的（`zte-ai-lab`、`agent-genesis`、`goldeval`、`skillx`、`cosightbot`）。
如果用户机器上已经有**同名、来源是 git 仓库**的 marketplace，宿主**默认拒绝覆盖**：

```text
插件安装失败

  插件      drive
  命令      claude plugin marketplace remove zte-ai-lab
  原因      marketplace zte-ai-lab 已由 git 仓库提供（git https://…），默认不覆盖…
  处理
            1. 确认要用产物里的本地市场替换它时，加 --replace-marketplace 重新运行
            2. 或者先手动执行 claude plugin marketplace remove zte-ai-lab
  影响      插件没有全部就绪，模块未启动；已装好的插件保留，修好后重跑即可。
```

同意覆盖时：

```bash
./install.sh --replace-marketplace
```

同名但来源是本地目录、注册路径就是副本位置时，只刷新内容；注册到别处时
会移除后重建（同样不涉及 git 来源时）。

## 6. 失败时怎么查

退出码：

| 码 | 阶段 | 典型原因 |
| --- | --- | --- |
| 10 | 前置检查 | 没装 Claude Code / 版本 < 2.1.287 / `~/.claude` 不可写 / 缺 `python3` / 插件载荷损坏 |
| 11 | 初始化 | 数据目录或配置文件写不进去 |
| 12 | 插件安装 | `claude` 命令失败、marketplace 冲突、装完复核不一致 |
| 13 | 启动 | 模块没起来、框架 30s 内没就绪、端口被占 |

排障顺序：

1. 读最后一屏的固定四段：**检查项 / 原因 / 处理 / 影响**；
2. 手动跑报告里给出的 `claude ...` 命令看完整报错；
3. 状态对不上时，对照 `claude plugin list --json` 与
   `$CLAUDE_CONFIG_DIR/plugins/installed_plugins.json`（CLI 输出坏掉时宿主会回落到文件）；
4. `~/.claude` 归 root 所有是常见原因（曾用 sudo 跑过安装）：**不要 sudo**，
   把所有权改回当前用户后再试；
5. 怀疑锁文件残留（上次进程被强杀）：确认没有其他安装在跑，删除
   `$COSIGHT_HOME/.install.lock` 后重试。

## 7. 更新与卸载

**更新**：换用新版产物，重跑 `./start.sh` 或 `./install.sh` 即可。判定依据是
产物里 `plugins/index.json` 记的版本与内容哈希；同版本但内容变了也会重装。

**只卸载某个插件**：

```bash
claude plugin uninstall goldeval@goldeval --scope user --json
```

**整体卸载**：跑产物里的卸载脚本，别手敲下面那串命令。

```bash
./uninstall.sh                  # Linux / macOS
uninstall.cmd                   # Windows
./uninstall.sh --dry-run        # 先看一眼会动什么
```

它按「先卸插件、再摘市场、最后清载荷副本」的顺序做完全部十条命令；反过来做会留下
指向空处的悬空注册项。**别人的插件还挂在同一个市场上时，那个市场会被保留**并提示
手动命令——卸载自己不该拆掉用户环境里的其它东西。

手工兜底（脚本跑不了时）：

```bash
claude plugin list --json       # 先看实际状态，别照着文档硬删
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
rm -rf ~/.claude/plugins/marketplaces/{zte-ai-lab,agent-genesis,goldeval,skillx,cosightbot}
```

卸载产物目录本身**不会**自动卸载插件——插件是装在 Claude Code 里的独立状态，
也不随目录消失（五份载荷副本，都在 `~/.claude` 下）。

## 8. 产物里的 `plugins/index.json`

打包期生成，运行期唯一可信来源：

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
      "sha256": "9f2c…（运行时文件集合的内容哈希）",
      "files": 214,
      "requires": { "bins": ["python3"] }
    }
  ]
}
```

- `sha256` 按 POSIX 相对路径排序后对"路径 + 文件字节"求 SHA-256，取前 16 位；
- 复制与哈希用**同一套排除规则**：`tests/`、`__pycache__/`、`.pytest_cache/`、
  `.ruff_cache/`、`*.pyc`、`.git/`、`node_modules/`、`.env`、`work/`、`output/`、
  `.agent-genesis/`，以及**顶层的** `.claude/`（插件自身的嵌套快照是内容）；
- 打包期还会把 `index.json` 与每个插件的两份 manifest 逐字读回校验，篡改或漏文件
  都会让打包失败，而不是等到用户机器上才发作。

## 9. Windows 提示

- `claude` 通常是 `claude.cmd`。宿主经 `cmd.exe /d /s /c` 调用，路径含空格或中文
  已处理；参数里出现 `"`、`%`、换行会被拒绝（无法安全转义）。
- Python 依赖检查找的是 `python3`（PATH 或 `py -3` 的常见位置）。没装 Python 时，
  用 `--skip-plugins` 或先装 Python 3。

## 10. 相关命令速查

| 目的 | 命令 |
| --- | --- |
| 只检查（含插件载荷） | `node start.mjs --self-check` |
| 安装 + 装插件 | `./install.sh` |
| 卸载五个插件与市场 | `./uninstall.sh` |
| 预览卸载动作 | `./uninstall.sh --dry-run` |
| 只初始化、不装插件 | `node start.mjs --init` |
| 强制换 marketplace | `./install.sh --replace-marketplace` |
| 跳过插件 | `./install.sh --skip-plugins` |
| 指定 claude | `node start.mjs --install --claude /path/to/claude` |
| 看插件状态 | `claude plugin list --json` |
| 看 marketplace 状态 | `claude plugin marketplace list --json` |
