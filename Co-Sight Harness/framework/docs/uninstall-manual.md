# Co-Sight Harness 卸载手册

> 适用：产物（解压出来的交付包）与源码仓库两种形态。
> 结论先行：**先跑卸载脚本，再删解压目录**；数据目录默认保留，要删得显式说两次。

---

## 1. 为什么不能只删目录

安装会往三个地方写东西，只有一处和解压目录有关：

| 位置 | 装了什么 | 删解压目录能清掉吗 |
| --- | --- | --- |
| 解压目录 | 框架、服务端、前端静态产物、模块、配置模板 | ✅ 能 |
| Claude Code 配置目录（默认 `~/.claude`） | 5 个插件注册 + 5 份 marketplace 载荷副本 | ❌ **不能**，要脚本摘 |
| 数据目录（默认 `~/.cosight-harness`） | 数据库、工作区、密钥令牌 | ❌ 不能，按需删 |

只删目录的结果是：界面没了，但 `claude plugin list` 里还挂着 `drive@zte-ai-lab` 等五条，
而且它们指向的载荷副本已经没人维护——下次想装回来，市场名还可能冲突。

---

## 2. 快速卸载（三步）

**第 1 步：停掉服务。** 在启动窗口按 `Ctrl-C`。

**第 2 步：跑卸载脚本。** 在解压目录里：

```bash
./uninstall.sh                 # Linux / macOS
```

Windows：在解压目录里**双击 `uninstall.cmd`**（或在命令行里执行 `uninstall.cmd`）。

想先看它会动什么、又什么都不改：

```bash
./uninstall.sh --dry-run
```

数据目录**默认保留**（里面有会话、工作区与密钥）。确认不要了，趁解压目录还在时删：

```bash
./uninstall.sh --purge-data --yes
```

`--purge-data` 表示意图，`--yes` 表示确认——两个都给才会真删，且不可恢复。
也可以跳过这步，稍后直接删目录（见下面「手工清理数据目录」）。

**第 3 步：删解压目录。** 手工删，或

```bash
cd .. && rm -rf cosight-harness-<版本>-<时间戳>
```

手工清理数据目录（任何时候都能做）：`rm -rf ~/.cosight-harness`，
Windows 删 `%USERPROFILE%\.cosight-harness`。

---

## 3. 脚本做了什么

`uninstall.sh` / `uninstall.cmd` 本身只做一件事：**找到 node**，然后把参数交给
`node start.mjs --uninstall`。逻辑只有一份实现，两个平台的薄壳不会各自跑偏。

`start.mjs --uninstall` 按固定顺序做三件事：

1. **卸插件**（5 条命令）

   ```text
   claude plugin uninstall drive@zte-ai-lab --scope user --json
   claude plugin uninstall agent-genesis@agent-genesis --scope user --json
   claude plugin uninstall goldeval@goldeval --scope user --json
   claude plugin uninstall skill-optimizer@skillx --scope user --json
   claude plugin uninstall cosightbot@cosightbot --scope user --json
   ```

2. **摘市场**（5 条命令）

   ```text
   claude plugin marketplace remove zte-ai-lab --scope user --json
   claude plugin marketplace remove agent-genesis --scope user --json
   claude plugin marketplace remove goldeval --scope user --json
   claude plugin marketplace remove skillx --scope user --json
   claude plugin marketplace remove cosightbot --scope user --json
   ```

   顺序不能反：先摘市场会让已装插件变成指向空处的悬空注册项。

3. **清载荷副本**：删掉 `<Claude 配置目录>/plugins/marketplaces/<市场名>` 下安装时复制进去的那几份。
   只删这五个目录名，不整目录清空——`marketplaces/` 下通常还有别人的市场。

卸完会再读一次插件状态，最后打印一行汇总：动了几个、还剩什么。

---

## 4. 参数

| 参数 | 作用 |
| --- | --- |
| `--uninstall` | 卸载入口（脚本已自动带上，手工调 `node start.mjs` 时才需要写） |
| `--dry-run` | 只读状态并打印将要执行什么，不改任何东西 |
| `--purge-data` | 连数据目录一起删；还要再给 `--yes` |
| `--yes` | 确认删除数据目录（不可撤销） |
| `--skip-plugins` | 不动 Claude Code 那侧，只处理数据目录 |
| `--claude <路径>` | 指定 Claude Code 可执行文件（PATH 上找不到时用） |
| `--home <目录>` | 指定数据目录（等价 `COSIGHT_HOME`） |

`--dry-run`、`--purge-data`、`--yes` 只能与 `--uninstall` 搭配。误用会直接报错，不会被静默忽略。

---

## 5. 输出怎么读

**正常**：逐条「已卸载 / 已移除」，最后一行汇总。

**某个市场被保留**：

```text
市场 zte-ai-lab 保留：还有别的插件挂在上面（their-tool@zte-ai-lab）。
  确认那些插件不要了再手动删：claude plugin marketplace remove zte-ai-lab --scope user
```

这是因为该市场下还挂着**不属于本产品**的插件。卸载自己不该拆掉你环境里的其它东西，
所以脚本跳过它并给出手动命令。

**失败**：固定四段——原因 / 处理 / 影响。按「处理」逐条做，然后重跑即可（幂等，
已经卸掉的会显示「未安装，跳过」）。

| 退出码 | 含义 |
| --- | --- |
| 0 | 完成（或按当前参数完成；`--dry-run` 也是 0） |
| 12 | 插件命令失败：`claude` 不可用、未登录、无写权限、装到一半失败 |
| 13 | 数据目录没删：框架还在跑、只给了 `--purge-data` 没给 `--yes`、或删除本身失败 |

---

## 6. 手工兜底

脚本跑不了时（例如 node 坏了、`claude` 只能手敲），照这个顺序做：

```bash
claude plugin list --json          # ① 先看实际装了什么，别照抄
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

Windows 下把 `rm -rf` 换成删除 `%USERPROFILE%\.claude\plugins\marketplaces\` 下的那五个目录。

**先卸插件、再摘市场**，顺序反了会留下悬空注册项。

---

## 7. 卸载后自检

```bash
claude plugin list --json              # 五条本产品插件都不在
claude plugin marketplace list --json  # 五个市场都不在
ls ~/.claude/plugins/marketplaces/     # 五个目录已删（其它市场不受影响）
ls ~/.cosight-harness                  # 还在 → 保留了（正常）；不存在 → 已 purge
```

都没问题后，删掉解压目录即可。

---

## 8. 常见问题

**只想清数据、插件留着继续用？**
`./uninstall.sh --skip-plugins --purge-data --yes`

**卸载后想重装？**
重新解压并跑 `./install.sh`。市场重新注册、插件重新安装；数据目录若还在会被继续使用。

**报「端口 4300 上还有进程在监听」？**
框架还在跑，删的会是一份正在被写的库。先 `Ctrl-C` 或结束 `start.sh` / `start.cmd` 窗口，
再重跑 `--purge-data --yes`。

**报「找不到 Claude Code 可执行文件」？**
先跑 `npm install -g @anthropic-ai/claude-code`，或用 `--claude <路径>` 指定；
确实不需要处理插件就加 `--skip-plugins`。

**只装了源码，没解压过产物？**
一样能用，在仓库根目录：

```bash
node framework/scripts/start.mjs --uninstall --dry-run    # 先看
node framework/scripts/start.mjs --uninstall
```

它只处理 Claude Code 那侧的插件与市场，**不动源码目录**。源码开发态下模块可能在仓库里
留自己的状态目录（例如 smart-factory 的 `.smart-factory/`），要不要删由你决定，脚本不碰。

**Windows 双击 `uninstall.cmd` 闪一下就没了？**
说明它提前退出了：窗口里的英文提示会说明是「找不到 node」还是「卸载没做完」。`.cmd`
里刻意只有英文——`cmd.exe` 按 ANSI（中文系统上是 GBK）逐字节读批处理，UTF-8 中文会乱码，
`chcp 65001` 也救不了。中文说明就是本文件。

---

## 9. 它刻意不做的事

- 不 `sudo`、不写系统目录、不改 `PATH`、不写注册表、不注册系统服务、不联网；
- 不删别人挂在同一市场下的插件（会保留市场并给出提示）；
- 不碰解压目录之外的任何文件，除了上面写明的那三处位置；
- 数据目录默认不删——那是你的会话、工作区与密钥。

卸载干净后，机器上不会留下本产品的系统级痕迹。
