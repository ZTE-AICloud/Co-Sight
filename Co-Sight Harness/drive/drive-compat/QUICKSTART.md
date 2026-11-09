# QUICKSTART — 作为第三方使用 drive + drive-compat 于 dsh

> 这份手册给"不是在 drive 仓库作者"的人：拿到一份 drive 制品副本，把它装进
> **你自己**的 dsh（DeepSeek Harness），让 drive 的 17 个技能 + 强制层（写守卫 /
> 审计 / HITL）在你的环境里跑起来。
>
> 全程**不需要**任何来自原作者机器的配置（不依赖内网 IP、模型 key、路径）。

## 拿到的是什么（两种形态）

| 形态 | 适用 | 第三节安装命令 |
|---|---|---|
| **A. 发布包**（`drive-dsh-plugin-<ver>.tgz`） | 最常见；**无需 drive 仓库**，自包含 | `install.sh --pkg <tgz>`（见 §2.2） |
| **B. 源码仓库**（含 `drive-compat/`） | 开发/调试/魔改 | `install.sh`（见 §2.1） |

## 0. 你要先有的三样东西

| 依赖 | 检查命令 | 说明 |
|---|---|---|
| dsh（v0.2.x） | `dsh --version` | 没有就 `npm install -g @deepseek-ai/dsh` |
| Node ≥ 22.19 | `node -v` | dsh 的运行要求 |
| Python 3 | `python3 --version` | drive 的守卫脚本是纯 stdlib 的 python |
| 一个可用模型 | 你自己 dsh 本来就能跑对话 | drive-compat 与模型无关，用你已配好的 provider 即可 |

## 1. 拿到制品

把整个 **drive 仓库（含 `drive-compat/` 子目录）** 拷到你的机器，放到一个你愿意
长期保留的位置（例如 `~/deploy/drive`）。**不要只拷 `drive-compat/` 单独一个
目录**——drive-compat 依约定位于 drive 仓库内，靠这个相对位置自动找到
`hooks/` 和 `skills/`（见第 3 步的"自动推断"）。

```bash
# 例：从 git 拉取，或从发布包解压
git clone <drive-repo-url> ~/deploy/drive
cd ~/deploy/drive && ls drive-compat     # 应看到 install.sh / src / acceptance ...
```

## 2. 安装（一条命令）

### 2.1 形态 A：发布包（推荐，无需 drive 仓库）

```bash
bash path/to/drive-compat/install.sh --pkg path/to/drive-dsh-plugin-2.3.4-dsh.0.tgz
# 或直接：dsh plugin --profile web add file:path/to/that.tgz
```

发布包**自包含**：里面已经带着 drive 的 hooks/skills/agents（`drive-assets/`），
不需要任何 drive 仓库；`install.sh` 会把 `driveRoot` 写成 `AUTO`，让插件自动
用包内资产。

### 2.2 形态 B：源码仓库（开发/魔改）

```bash
cd ~/deploy/drive
bash drive-compat/install.sh            # 默认装进 profile 'web'
```

### 两种形态脚本都做的事（幂等，可重复跑）

1. `dsh plugin --profile web add ...` → 装成 **bundle**，入 `dsh.profile.bundles`
   （常驻，不需要 `--patch`）。
2. 在你的 `~/.dsh/profiles/web/cordis.patch.yml` 里写入 `drive-compat` 配置块
   （形态 A 写 `driveRoot: AUTO`；形态 B 注入本机 drive 根），带 marker 便于
   卸载/升级。
3. 校验 + 打印重启步骤。

常用变体：
```bash
bash drive-compat/install.sh --dry-run        # 先预览，什么都不改
bash drive-compat/install.sh --profile p2     # 装到 p2 而不是 web
bash drive-compat/install.sh --drive-root /abs/path  # 形态 B：drive 不在默认位置
bash drive-compat/install.sh --uninstall      # 卸载
```

## 3. 重启 + 生效

```bash
# 停掉当前 dsh web，再用你平时的启动方式重启（会带出新组合）
kill $(pgrep -f 'bin/dsh web')
dsh web                                  # 或你的启动脚本/命令
```

> 首次安装必须重启（组合树在启动时解析）。之后改 `install.sh` 生成的配置块走
> web 的 config-only HMR，改插件代码仍要重启。

## 4. 验证真的生效（30 秒）

**快速层**：新开会话，看模型选择器旁的技能目录里是否出现 `drive` /
`drive-cleanup` / `drive-record` / `startup` / `state-machine` 等 17 个 drive 技能。

**强制层（最重要，别跳过）**：让模型做这三件事，应分别被拒 / 留痕 / 要人批：

| 测试 | 预期 | 若不通过 |
|---|---|---|
| `write` 一个 `.drive/<plan>/` 白名单外路径（如 `evil.txt`） | **BLOCKED** | driveRoot 没配好 → 见"排错" |
| 跑一条会写 `.drive/.../run-log.jsonl` 的 bash | run-log 里出现 `bash_called` | 同上 |
| 不带人工确认调 `confirm_stage.py` | 触发人工审批（approval 弹窗） | approval policy 是 `never` → 改 `ask` |

也可跑配套自动化探针（在一次性临时工作区跑，不碰你任何真实数据）：
```bash
bash drive-compat/acceptance/run-all.sh   # 需在 drive 仓库根运行；自动使用临时工作区
```

## 5. 排错速查

| 现象 | 原因 → 修法 |
|---|---|
| 启动日志出现 `resolved driveRoot ... is missing the drive payload` | 插件找不到 drive。`install.sh` 注入的 `driveRoot` 不对：重跑 `install.sh --drive-root <真实drive根>` |
| 守卫"好像没生效"但无报错 | 大概率是上面的 fail-loud 被当成"没装"。确认启动日志无 error；再跑第 4 节三条 |
| `confirm_stage` 不弹人工确认 | 你的 approval policy 是 `never`（headless/CI 姿态）。HITL 需要 `ask` 策略 |
| 内网/代理请求超时 | 这是**你机器**的网络问题，与本插件无关：调整你的 `no_proxy` / 代理 |
| 技能出现在目录但 `/drive` 调了没反应 | 检查 exec 工具（bash/python3）在你的沙箱/权限策略下可用 |

## 6. 升级 / 回滚

```bash
# 升级：拿新版 drive，重跑 install.sh（bundle 更新 + 配置块重写）后重启
bash drive-compat/install.sh
# 卸载：移除 bundle 与配置块
bash drive-compat/install.sh --uninstall
```
每次修改 profile 前 install.sh 都会留 `cordis.patch.yml.bak.<ts>` 备份。

## 7. 你知道的这些边界

- `allowed-tools`（drive 技能声明式工具白名单）在 dsh **没有等价物**：由本兼容层
  动态 deny/ask 兜底，或不管。这是平台差距，插件补不回。
- HITL 依赖 approval policy = `ask`；`never` 下 ask 会被直接拒绝（等于无 HITL）。
- `subagent` 完成是异步的；`Agent` shim 会把子代理结果同步等回再返回。
