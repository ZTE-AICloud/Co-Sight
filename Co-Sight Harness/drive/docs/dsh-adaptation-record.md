# drive 适配 DeepSeek Harness 实操记录

> 本文回答一个问题：**要让 drive 在 dsh 上正常跑起来，需要做哪些适配？**
> 结论先行——**drive 一行代码没改**，全部适配都在环境侧完成，共 6 步。
> 配套：[兼容性评估报告](./dsh-compatibility-report.html)——基于 dsh 源码核查的资产级兼容矩阵与 Gap 分析。

## 元信息

| 项        | 值                                       |
| -------- | --------------------------------------- |
| 验证日期     | 2026-10-22                              |
| dsh 运行版本 | `0.2.1-rc.2`（制品方式，npm 全局安装）             |
| dsh 核查版本 | `dsh-v0.2.1-rc.2`（源码，HEAD `687f282e86`） |
| drive 版本 | `v2.3.4`，**零改动**                        |
| 验证工作区    | `drive/.dsh-lab/`                       |

---

## 1. dsh 部署方式：制品，不是源码

这是本次适配的第一个决策点，需要说清楚。

### 采用的方式：npm 制品

```bash
npm install -g @deepseek-ai/dsh@0.2.1-rc.2
```

安装位置 `~/.config/nvm/versions/node/v22.23.2/lib/node_modules/@deepseek-ai/dsh`，259 个包。这是**制品方式**——直接消费 npm 上发布的 `@deepseek-ai/dsh` 包，不编译源码。

### 源码仓库的用途：仅核查，不参与运行

`/media/vdc/github/harness-related/deepseek-harness` 有一份完整源码 clone，本次 fast-forward 5218 个提交到 `dsh-v0.2.1-rc.2`。但它**只用于源码核查**——定位 matcher 实现、session 格式常量、frontmatter 校验等。运行实例与它无关。

### 为什么选制品而不是源码

仓库里已存在一套源码方式的启动脚本（`scripts/dsh-web.sh` + `profile-minimax.yml`），走 `pnpm dsh web --patch` 并用 undici ProxyAgent 注入以适配代理环境。本次没有沿用，原因有二：

| 维度    | 制品方式（采用）                     | 源码方式（未采用）                                           |
| ----- | ---------------------------- | --------------------------------------------------- |
| 模型接入  | DeepSeek 原生 key 直接用，无需代理     | 需 MiniMax 代理层，`MINIMAX_CN_API_KEY` 在 `.env` 中处于注释状态 |
| 启动开销  | 安装一次，之后 `dsh` 命令即用           | 每次 `pnpm run build` + 源码启动                          |
| 版本对应  | npm `latest` 就是 `0.2.1-rc.2` | 需自行保证 build 产物与 tag 一致                              |
| 与他人协作 | 版本可复现                        | 依赖本地构建状态                                            |

若后续需要切回源码方式，现有 `scripts/dsh-web.sh` 可直接复用，profile overlay 写法与本文 §4 相同。

### 部署过程中被替换的旧版本

原有全局 dsh 为 `0.1.0-rc.7`，被本次安装替换。替换前已备份 `~/.dsh/settings.yaml`（现存 `settings.yaml.bak-0.1.0-rc.7`）。**如需回退，需重新钉版本安装 `0.1.0-rc.7`**——这一点未验证。

---

## 2. 适配总览

驱动 drive 跑起来，共 6 步环境侧动作：

| #   | 动作                          | 是否 drive 侧改动 | 难度          |
| --- | --------------------------- | ------------ | ----------- |
| 1   | 安装 dsh 最新制品                 | 否            | 低           |
| 2   | 清理遗留 profile                | 否            | **中（隐蔽阻塞）** |
| 3   | 安装 hooks 桥及其 peer           | 否            | **中（版本陷阱）** |
| 4   | 准备工作区并挂载 17 个技能             | 否            | 低           |
| 5   | 编写 patch overlay 挂载 hooks 桥 | 否            | 低           |
| 6   | 配置模型凭据                      | 否            | 低           |

**drive 侧改动量：0 行。**

以下逐条展开。

---

## 3. 步骤 1–2：部署与清理

### 步骤 1：安装 dsh 最新制品

```bash
npm install -g @deepseek-ai/dsh@0.2.1-rc.2
```

npm 上 `latest` 标签即 `0.2.1-rc.2`，与本次验证目标一致，无需钉版本。

Node 要求 `^22.19.0 || >=24.0.0`，环境为 v22.23.2，满足。

### 步骤 2：清理 0.1.x 遗留的同名 profile（隐蔽阻塞）

这一步不做，后续所有插件安装都会失败。

**现象**：任何 `dsh plugin add` 都报：

```
[ERR_PNPM_FETCH_404] GET https://registry.npmjs.org/dsh-codebase: Not Found
```

**根因**：`~/.dsh/profiles/web/` 是 0.1.x 时代创建的同名自定义 profile，**遮蔽了 dsh 内置的 shipped `web` 模板**。其 `package.json` 仍钉着 `dsh-codebase@0.1.1`——这个包在 npm、dsh 仓库源码、已安装 npm 包**三处都不存在**，是已从 registry 下架的历史包。pnpm 解析 profile 依赖时必然 404。

**为什么不能自动修复**：`web` 是 shipped 保留名，运行时明确拒绝覆盖：

```
Error: profile "web" names shipped profile "web" and cannot be a custom profile target;
omit --from-default-profile to use it
```

`--from-default-profile web` 同样被这条校验挡住。**唯一解法是把旧目录移走**，让 dsh 回落��官方模板。

```bash
mv ~/.dsh/profiles/web ~/.dsh/profiles/web.old-0.1.x
```

移走后 `dsh --profile web --dump-config` 可正常组合，模型默认值为 `deepseek-official / deepseek-flash`，不再出现 `dsh-codebase`。

> **判定启发**：升级 dsh 跨 minor 版本线时，先检查 `~/.dsh/profiles/*/package.json` 里是否有已下架依赖。旧 profile 会静默遮蔽新模板，且失败信息（404）完全不指向 profile 本身，极易误判为网络或权限问题。

---

## 4. 步骤 3：安装 hooks 桥（版本陷阱）

drive 的 `hooks/hooks.json` 想在 dsh 上生效，需挂官方桥 `@deepseek-ai/dsh-hooks-claude-code`。

### 陷阱一：`latest` 标签落后于核心

直接 `add` 不带版本会被版本门禁拒绝：

```
installation rejected: @deepseek-ai/dsh-hooks-claude-code@0.0.1-rc.5 is incompatible with
dsh 0.2.1-rc.2: requirements {"@deepseek-ai/dsh-llm":"^0.0.1-rc.5", ...}
```

dist-tag 现状：

| 包                                    | `latest`               | `next`             |
| ------------------------------------ | ---------------------- | ------------------ |
| `@deepseek-ai/dsh-hooks-claude-code` | `0.0.1-rc.5`（peer 不兼容） | `0.2.1-rc.2`（版本匹配） |
| `@deepseek-ai/dsh`                   | `0.2.1-rc.2`           | —                  |

版本匹配的发布存在于 `next` 标签下，**必须显式钉版本**。

### 陷阱二：peer 依赖不随宿主安装

```bash
dsh plugin --profile web add @deepseek-ai/dsh-hooks-claude-code@0.2.1-rc.2
# → 装上了，但启动时报
# Cannot find package '.../dsh-hook-protocol/index.js'

dsh plugin --profile web add @deepseek-ai/dsh-hook-protocol@0.2.1-rc.2   # 必须补装
```

`@deepseek-ai/dsh-hook-protocol` 是 peer 依赖，host 安装不携带（profile 的 pnpm workspace 配了 `autoInstallPeers: false`）。

### 装完仍不生效

即便两个包都装好、启动日志零报错，**当前没有任何 shipped preset 组合 `hooks-claude-code`**——它是 opt-in。必须通过步骤 5 的 patch overlay 显式 insert。

### 关于 hooks 桥的定位

**挂上它不等于 drive 的强制层生效。** 实测结论是桥已挂载、配置解析成功，但 matcher 大小写不匹配导致三个守卫全部静默失效（详见验证报告）。桥本身装对了，只是 drive 的 `hooks.json` 里的 PascalCase matcher（`Bash` / `Write|Edit|MultiEdit`）与 dsh 的全小写工具名（`bash` / `write` / `edit`）不兼容。

所以这一步的实际价值是：**排除了「装不上」这个变量，隔离出「装上了但不匹配」这个真问题**。

---

## 5. 步骤 4：准备工作区并挂载技能

### 为什么必须换目录

dsh 的技能根目录有 6 个 rank（100/200/**250**/300/400/500/600），**`.claude/skills` 不在其中**。所以 drive 现有的 `skills/` 目录结构不能直接被 dsh 发现，必须挂到 dsh 的根上。

### 实操

```bash
WORKSPACE=<repo>/drive/.dsh-lab
mkdir -p "$WORKSPACE/.dsh/skills"
cd "$WORKSPACE" && git init -q          # projectRoot 靠最近的 .git 判定

DRIVE=<repo>/drive
for d in "$DRIVE"/skills/*/; do
  ln -s "$d" ".dsh/skills/$(basename "$d")"
done
```

用符号链接而非拷贝，避免源码更新后实验室与源目录漂移。

### 17 个技能的加载结果

全部加载成功，零 legacy frontmatter 键，name 全部符合 dsh 的 kebab-case 正则 `^[a-z0-9]+(?:-[a-z0-9]+)*$`。

`skills/list` API 只返回 5 个，这是**列表过滤不是加载失败**——12 个技能声明了 `user-invocable: false`，dsh 的列表接口只展示用户可直接调用的技能。实测轨迹中明确出现「加载技能 startup」，而 `startup` 正是 `user-invocable: false` 的技能，证明它们已加载且可被模型调用。

### drive 的 agents 与 commands 未挂载

本次验证没有适配这两类元素：

- `agents/*.md`：dsh 的 agent preset 是带 `agent.cordis.yml` 的**目录**，不是 markdown。本次改用 drive 的 skill 派发模板在提示词里内联 agent 角色定义（`读取 agents/analyzer.md` + 子代理任务），绕开了格式转换。
- `commands/`：drive 本来就没有依赖 `.claude/commands/`，无需适配。

---

## 6. 步骤 5：编写 patch overlay 挂载 hooks 桥

因为桥是 opt-in，需要在自己的 profile 层显式 insert。工作区内的 `lab-patch.yml`：

```yaml
- insert:
    - id: hooks-claude-code
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        # 指向 drive 包的真实 hooks.json（不改写，保留 PascalCase matcher）
        configPath: /abs/path/to/drive/hooks/hooks.json
        # 替换 hooks.json 命令串里的 ${CLAUDE_PLUGIN_ROOT}
        pluginRoot: /abs/path/to/drive
        # 替换 ${CLAUDE_PROJECT_DIR}，并作为同名环境变量导出给守卫进程
        projectDir: /abs/path/to/drive/.dsh-lab
```

三个字段的作用：

- `configPath` — 要桥读的 hooks 配置文件，指向 drive 未经改写的原文件
- `pluginRoot` — 替换 `hooks.json` 命令里的 `${CLAUDE_PLUGIN_ROOT}`。**这是 drive 侧的关键设计**：所有守卫都以 `python3 "${CLAUDE_PLUGIN_ROOT}"/hooks/xxx.py` 形式调用，靠这个变量定位自己
- `projectDir` — 替换 `${CLAUDE_PROJECT_DIR}`，同时作为环境变量导出给守卫进程

组合验证（不启动服务）：

```bash
dsh web --patch ./lab-patch.yml --dump-config | grep -A3 hooks-claude-code
```

确认补丁进入配置树后再启动。

---

## 7. 步骤 6：配置模型凭据

```bash
export DEEPSEEK_API_KEY=<key>
dsh web --patch ./lab-patch.yml --no-open --port 3080
```

Web UI 默认监听 `127.0.0.1:3080`，启动日志会打印带 token 的完整 URL（形如 `http://127.0.0.1:3080/?token=...`），该 token 即浏览器访问凭据。

模型默认走 `deepseek-official` provider。dsh 也支持 Anthropic / OpenAI / Kimi / GLM 及任何兼容 OpenAI Chat Completions / OpenAI Responses / Anthropic Messages 的自定义端点，但**不支持 OAuth 登录类 provider（如 Codex）**。

---

## 8. 验证结果

验证方式：在 dsh Web UI 中调用 `/drive 开发一个贪吃蛇小游戏，单文件 HTML + 原生 JS 实现即可`，全程用 chrome-devtools 驱动。结果摘要：

| 项                                             | 结果                                               |
| --------------------------------------------- | ------------------------------------------------ |
| `/drive` 端到端工作流                               | ✅ 跑通，`verdict = pass`，15/15 AC VERIFIED          |
| 交付物                                           | `snake.html` 38981 字节，单文件、零外部依赖                  |
| 阶段流转                                          | analyze → plan → execute → evaluate，四次门禁全部弹出并被遵守 |
| 子代理编排                                         | ✅ analyzer / planner / executor 正常               |
| wave 调度 / critic / trace / headless Chrome 验证 | ✅ 全部零障碍                                          |
| HITL 门禁                                       | ⚠️ 可用但无强制——走 dsh 的 `ask_user_question`，由模型主动发起   |
| PreToolUse 守卫                                 | ❌ 三个 matcher 全部静默失效                              |
| `allowed-tools`                               | ❌ 被忽略，零权限弹窗                                      |

---

## 9. 环境侧改动清单（可逆性）

| 位置                                  | 改动                                                                   | 回退方式                                    |
| ----------------------------------- | -------------------------------------------------------------------- | --------------------------------------- |
| `~/.dsh/settings.yaml`              | 未改动（原文件已备份为 `settings.yaml.bak-0.1.0-rc.7`）                          | 移回备份                                    |
| `~/.dsh/profiles/web/`              | 被 shipped 模板取代；旧目录移至 `web.old-0.1.x`                                 | `mv web.old-0.1.x web`                  |
| `~/.dsh/profiles/web/node_modules/` | 新增 `dsh-hooks-claude-code@0.2.1-rc.2`、`dsh-hook-protocol@0.2.1-rc.2` | `dsh plugin --profile web remove <pkg>` |
| 全局 npm                              | dsh `0.1.0-rc.7` → `0.2.1-rc.2`                                      | 重装钉版本（未验证）                              |
| `<repo>/drive/.dsh-lab/`            | 新建工作区（未跟踪）                                                           | 直接删除                                    |
| `<repo>/drive/docs/`                | 新增 3 份文档（未跟踪）                                                        | 直接删除                                    |

**drive 全部受版本控制的文件零改动**——`hooks/`（1356 行）、`skills/`（17 个）、`agents/`（7 个）、`.claude-plugin/` 均未触碰。

---

## 10. 还没做的适配

上面 6 步只让 drive **能跑**。以下才是让 drive 在 dsh 上**跑得住**的部分，本次未做：

| #   | 待适配项                                                    | 性质                  | 预估        |
| --- | ------------------------------------------------------- | ------------------- | --------- |
| 1   | 守卫重写为 dsh 原生插件，挂 `tools/pre-execute` 按 `exec.name` 自行分发 | 恢复 harness 层强制力     | 2–3 人日    |
| 2   | HITL 契约固化为显式 `ask_user_question` 调用                     | 把模型自觉变为系统契约         | 可能 < 1 人日 |
| 3   | `agents/*.md` → `agent.cordis.yml` 目录                   | 若要正式启用 dsh 原生子代理    | 2–3 人日    |
| 4   | `${CLAUDE_SKILL_DIR}` 在 dsh 的等价变量                       | 消除脚本定位失败（实测已发生 2 次） | 0.5 人日    |
| 5   | 守卫存活探针                                                  | 消除静默失效（G5）          | 0.5 人日    |

其中 **第 4 项最值得优先做**——它在本次端到端运行中造成了两次 exit 2 并让 agent 反复摸索路径，成本最低、收益最直接。

第 2 项成本可能远低于早先预估：实测中模型已自发采用 `ask_user_question` 实现门禁，多半只需把这一用法写进 SKILL.md 固化为契约，而非改代码。

---

## 11. 一页速查

```bash
# 1. 装制品
npm install -g @deepseek-ai/dsh@0.2.1-rc.2

# 2. 清遗留 profile（0.1.x 时代遗留，不做则插件全 404）
mv ~/.dsh/profiles/web ~/.dsh/profiles/web.old

# 3. 装 hooks 桥（钉版本 + 补 peer）
dsh plugin --profile web add @deepseek-ai/dsh-hooks-claude-code@0.2.1-rc.2
dsh plugin --profile web add @deepseek-ai/dsh-hook-protocol@0.2.1-rc.2

# 4. 挂技能
mkdir -p <ws>/.dsh/skills && cd <ws> && git init
for d in <drive>/skills/*/; do ln -s "$d" ".dsh/skills/$(basename "$d")"; done

# 5. 写 lab-patch.yml（insert hooks-claude-code，指定 configPath/pluginRoot/projectDir）

# 6. 起服务
export DEEPSEEK_API_KEY=<key>
dsh web --patch ./lab-patch.yml --no-open --port 3080
```