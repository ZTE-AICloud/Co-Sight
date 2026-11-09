# 四能力入口与技能工坊 · 前端实施方案

> 状态：**待评审**。本文定义四类能力的入口、技能库页与工坊对话页。
> 配套后端：[`server/docs/03-architecture/10-skill-library.md`](../../server/docs/03-architecture/10-skill-library.md)（目录会话 + `GET /skills`）。
> 本文只定前端口径；接口形状以后端文档为正本。

## 0. 一句话

**「创建智能体」留在首页输入框里，另外三个动作长在它们作用的对象旁边**：技能库 tab（创建 / 优化，与专家列表同页）、专家列表（评估，已有）、工坊对话页（真正干活的地方）。

不引入能力 chip、不解析正文里的目标、不改 Composer。

## 1. 页面与入口

| 路由 | 页面 | 状态 |
|---|---|---|
| `/` | 首页：输入框保持现状 + 新增三张快捷卡 | 改 |
| `/agents` | **专家 · 技能**：专家 tab（现状）+ 技能 tab（两路来源），页头切换 | 改 |
| `/agents?tab=skills` | 技能库 tab（与专家列表同页） | **新增** |
| `/skills` | 重定向到 `/agents?tab=skills`（首页快捷卡的落点） | **新增**（重定向） |
| `/workshop` | 工坊对话（技能线的唯一工作台） | **新增** |
| `/agents/:id/design` | 设计页：接受「把这句话放进发送框」的 replay | 小改 |

> 2026-10-22 改版：技能库不再单独占一页，和专家列表合成一页用 tab 切换，左侧导航
> 从「专家」改叫「专家·技能」。`/skills` 保留成短地址并重定向，免得首页快捷卡 / 旧记录
> 落进 `*` 兜底被静默送回首页。

入口矩阵：

| 动作 | 入口 | 落点 |
|---|---|---|
| 创建智能体 | 首页输入框（现状） | `/agents/:id/design` |
| 创建技能 | 首页卡 / 技能库页头「＋ 创建技能」 | `/workshop` |
| 技能优化 | 技能卡「优化」 | 库技能 → `/workshop?target=…`；智能体技能 → 该智能体设计页（replay） |
| 评估智能体 | 首页卡 → `/agents`；专家卡「评估」 | `/agents/:id/design?stage=evaluation` |

首页三张快捷卡只是**导航**（跳到上面三个页面），不承载选择态、不带参数。

## 2. 为什么不再做能力 / 目标 chip

被否掉的方案（本文件 2026-10-22 草案）在输入框里摆两颗 token，再从正文解析目标。砍掉的理由：

- 目标都能从列表点出来，解析省下的是一次点击，换来的是三态解析 + 歧义弹窗 + 提交兜底；
- Composer 需要新增「不可删的前缀 token」，而它现在是 DOM token + IME / 选区 / 粘贴一起跑的 1300 行组件，风险与收益不成比例；
- 动作放在对象旁边后，「作用在谁身上」由页面上下文回答，不需要一个控件来表达。

**结论：Composer 一行不改。**

## 3. `/workshop` 工坊对话

### 3.1 结构

```text
┌──────────────────────────────────────────────┐
│ 工坊                          [历史] [新会话] │
├──────────────────────────────┬───────────────┤
│                              │ 技能库文件     │
│   Conversation               │ ┌────┬──────┐ │
│   （复用 shared/components） │ │ 树 │ 预览 │ │
│                              │ └────┴──────┘ │
├──────────────────────────────┤               │
│  Composer（只收正文与附件）   │               │
└──────────────────────────────┴───────────────┘
```

- 复用 `Conversation` + `Composer` + `useLiveSession`，与设计页同一套；
- **右侧技能库文件面板**（`components/SkillFilesPanel.tsx`）：左树右预览，树根是
  `GET /skills` 的 `root`，走 `/fs/list` / `/fs/read` 懒加载；一轮对话结束后重拉根与
  已展开目录（接口没有订阅）。预览复用 `FilePreviewBody`，md / html / 图片 / 二进制
  分流与文件预览面板同一套。窄屏（≤860px）让位给对话，整块收起；
- 挂 `FilePreviewProvider`（对话里会有文件引用）；
- 通道状态 / 重试 / notice 复用设计页那套（`link.conn` / `link.retry` / `link.notice`）；
- **没有目标条。** 创建与优化都是同一场对话，区别只在首条消息怎么拼（§3.3）；
  从哪个入口进来只影响首条与会话名，不作为页面上常驻的一块信息 —— 目标不是会话的持久属性。

### 3.2 会话生命周期：**第一次发送时才建会话**

与设计页不同，工坊页**不在 mount 时建会话**：

1. 进页面只连 WS、拉 `GET /skills` 拿 `cwd` 与技能信息，不建会话；
2. 用户点发送 → `POST /sessions/create { cwd, modelId, name }` → `openSession` → 发送；
3. 成功后 `replace` 地址为 `/workshop?…&session=<id>`，刷新即恢复这一场；
4. 用户没发送就离开 → 不留下空会话。

这样做的两个好处：历史列表里不会出现一串空场；会话名可以按首条正文命名（见 §3.3），而不是只能叫「新建技能」。

恢复路径：带 `?session=` 进来时 `sessions/detail` 校验 `instance.cwd === cwd`，不一致按无效参数提示并回到新建态（不猜、不跨目录打开）。

### 3.3 首条消息：页面拼前缀

正文由用户写，**命令与目标由页面拼**，只在「这一场的第一条」加：

| 场景 | 首条消息 |
|---|---|
| 创建技能 | `/agent-genesis:skill-foundry 创建一个新技能：<正文>` |
| 优化（库技能） | `/skill-optimizer:skill_optimize --mode optimize --skill-path "<skillMdPath>"` +（正文非空时接 `--expert-guidance "<正文>"`） |

- **正文可以为空**：优化场「只选了技能、什么都不写」本身就是一次完整的发送（命令 + 路径由页面拼），
  首页按下发送就表示用户要跑这一场，工坊必须照发，不能把人拦在输入框前再问一句。
  判定：`location.state` 存在即「首页按过发送」；创建场仍要求正文或附件非空，优化目标失效时也不发
  （页面提示「技能不存在」，用户已写的正文放回发送框）；
- `skillMdPath` = `<skill.path>/<skill.version>/SKILL.md`，`version` 为空串时 `<skill.path>/SKILL.md`；
- 优化走 `skill_optimize --mode optimize`（多维评分 → 缺口 → 改动 → 再评分），与创建场的 `skill-foundry`
  不是同一个技能；目标是绝对路径，避免同名技能选错；
- 正文按 `--expert-guidance` 传：那是 skill_optimize 唯一认的自然语言入参，命令后面的裸文本它不解析。
  路径与正文都包在双引号里（路径可能带空格，正文可能带引号与换行，见 `compose-prompt.ts` 的 `quoteArg`）；
- 创建场由 skill-foundry 从输入语义判定，**不要伪造 `--mode` 参数**（它的 SKILL.md 就是这么约定的）；
  `--mode` 只有优化场传，且是必填 —— 不传 skill_optimize 会当场报错退出，所以它写在 `SKILL_OPTIMIZE` 常量里；
- 会话名：创建场 `新建技能：<正文前 20 字>`，优化场 `优化 <skill.name>`（`sessions/create` 的 `name`，建后不可改）；
- 后续轮次原样发送，不再拼前缀；
- 页面上不显示「目标」：它只存在于首条消息和会话名里。优化场的空态用一句话说明在改哪个技能，
  不常驻成一条 bar。

已知粗糙点（P0 接受）：对话里用户气泡会显示完整的命令与路径。P1 再在 `Conversation` 里把首行命令渲染成徽标（后端不改）。

### 3.4 历史抽屉

- 数据：`sessions/list?cwd=<cwd>&stage=development&pageSize=20`（工坊会话是目录实例、开发阶段；不带阶段时服务端默认只返回 runtime），无限滚动沿用列表页的 `page` 逻辑；
- 行：会话名（空则回落到 `firstUserMessage` 首行，再退 `lastMessage` 摘要）+ 状态 + 相对时间；
- 点一行：`replace` 到 `?session=<id>` 并 `openSession`；
- 删除：`sessions/delete` 二次确认；删的是当前场则回到新建态；
- 「新会话」：**回首页**（预选「创建技能」），不在工坊就地清空重开。
  新会话要先答「创建，还是优化哪个技能」，那是首页四张能力卡的事；工坊只承接
  已经发起的那一场。从优化入口进来也不沿用 `target` —— 目标属于发起时的输入，
  不属于工作台。

### 3.5 空态与错误

| 场景 | 行为 |
|---|---|
| 没有生效工作区 | 挡住发送，文案与首页一致（去框架里选工作区） |
| 没有可用模型 | 同上；模型按 `resolveDefaultModelId` 解析（工作区默认 → 框架生效 → 列表第一项） |
| 后端没起 | 沿用 `isBackendDown` 判据与措辞 |
| `GET /skills` 失败 | 页面可打开，但**挡住发送**：目录会话的 `cwd` 就是接口给的，没有它建不了会话。文案照实说「技能库不可用」，不假装能开始 |
| 技能库里没有任何技能 | 创建场正常；优化入口在 `/skills` 空态里不出现 |
| `?target=` 对应的技能已不存在 | 发送前挡下：不在 `GET /skills` 里就退回创建场语义，空态提示这条技能已不存在，不把失效的绝对路径拼进 prompt |

### 3.6 模型

P0 只解析默认模型并用它建会话；切换沿用会话级 `model.switch`（`useLiveSession.updateSessionModel`），不在工坊页另做模型选择器。

## 4. 技能库 tab（`/agents?tab=skills`）

### 4.1 数据

`GET /skills?workspaceId=<active>`（新增接口，见后端文档 §4）。响应里的 `root` / `cwd` 直接用，**客户端不拼路径、不算 `dirname`**。

> 2026-10-26：**「历史」改为在技能库页内开抽屉**（按 `优化 <name>` 筛），选中会话才带
> `?session=` 进工坊 —— 不再为了挑一场会话先打开一个空对话区。工具条另加「工坊历史」
> （不过滤，同样在库内开抽屉），空库时也有路回到还在跑的会话。
> 2026-10-22 晚：工坊页（`/workshop`）落地后，卡上的「优化」已经接上 —— 库技能进工坊
> （`?target=`），智能体技能回设计页（`优化` 带 replay、`去设计页` 不带）。
> **本页工具条不放「创建技能」**（按评审去掉，创建走首页快捷卡）。
> 2026-10-28：**空态例外，但只是回入口的快捷方式** —— 空库时加一颗「创建技能」，
> 落点是 `navigate('/', { state: { capability: 'skill.create' } })`，
> 与工坊「新会话」同一条路：**创建技能只有首页那一个入口**（框架里就是 `/agent-dev`
> 嵌着的首页），不在技能库页另起一场工坊会话。
> 2026-10-28 术语：界面不写「工坊」，这一页叫**技能开发**；会话历史统一叫**历史会话**
> （工具条按钮 / 工坊顶栏按钮 / 抽屉标题），不再派生「开发记录 / 开发会话」这类同义变体。
> **空态不再重复「历史会话」**：工具条那颗一直可见，空库也点得到。
> 后端 `GET /skills` 已实现（`server/src/modules/skill/`），请求失败时页面照实显示
> 「技能库没拿到」/ 服务端原话，**不垫 mock 数据**。

### 4.2 卡片

| 区域 | 内容 |
|---|---|
| 标题 | `name`（`SKILL.md` 的 name，取不到时回落目录名）+ 版本 `v2`（无版本目录则空） |
| 右上角 | 来源：`技能库` / 智能体名（`ownerName`） |
| 副标题 | `description`（为空显示「未填写描述」占位，与专家卡同款两行定高） |
| 元信息 | `updatedAt` 相对时间（与动作同行，贴在行末） |
| 动作 | 「优化」「历史」「装配」/ 智能体技能另有「去设计页」 |

排序沿用接口（库在前、组内按时间倒序）；不做分组标题，靠来源标签区分。

版式与专家卡一致（2026-10-22 对齐）：20px 内边距 / 10px 圆角、40px 卡头、16px 名称、
13px 两行简介、卡底发丝线 + 12px 文字链动作；技能卡只是少一行标签、动作换成「优化 / 历史」。

**卡片宽度与专家卡一致**（2026-10-27）：栅格直接用专家的 `.al-grid`（默认 4 列，逐断点
同宽）。**高度不钉**：技能卡没有专家卡那行标签，钉成 239px 只会在简介与卡底之间留出
约 46px 空白，所以按内容走，同一行由栅格 stretch 拉齐、动作行用 `margin-top: auto` 贴底。
右上角徽标只写 `技能库` / `智能体` 这档短字，归属智能体名进 `title` 与卡底提示，
否则长名字会把技能名挤到只剩几个像素。

### 4.3 两个动作

| 来源 | 优化 | 历史 |
|---|---|---|
| `library` | `/workshop?target=<path>&name=<name>` | 技能库页内抽屉（按 `优化 <name>` 筛），点会话后进 `/workshop?session=<id>` |
| `agent` | `/agents/<ownerAgentId>/design` + replay（见 §5.2） | 该智能体的开发会话本身，跳设计页即可 |

### 4.3.1 装配（2026-10-26）

卡底「装配」= 把这一版技能**复制**进目标智能体当前产物的 `.claude/skills/`（后端
[4.13](../../server/docs/04-api/4.13-智能体技能.md)）。复制完当下生效：runtime 原地读产物，
预览 / 评估起 run 前从产物整拷。

- 弹层只选目标智能体（当前工作区、`source=user`）；选中后现拉一次
  `GET /agents/:id/skills`，用于预判同名、显示产物是否就绪、展示已有项数。
- **复制完与技能库无关**：不钉版、不同步、不记来源；技能列表不因装配多出条目。
- 拒绝：产物未就绪 / 内置智能体 / 有活跃 run / 同名 —— 都是 `409`，弹层照实显示。
- 产物技能在设计页生成阶段的「产物技能」里管理（`优化` 把命令放回发送框、`删除` 移除目录）；
  预览阶段的 `/` 词表来自同一个 `GET`，命令是 `/＜目录名＞`。
- 重建会产出新的 `vN` 目录，装配的技能需要重新装配（本期不做自动带过去）。

### 4.4 刷新与搜索

进入页面拉一次；另给一个刷新按钮。**不做轮询、不做实时推送** —— 工坊产出一个技能后，用户回到这个页面自然重拉。

搜索框在工具条右侧，**在前端筛**（接口没有 keyword 参数，技能库是一屏量级）：
匹配 `name` / `description` / `ownerName`，大小写不敏感；筛后计数显示「匹配 N / 共 M 个」，
没命中时给空态与「清空搜索」。

### 4.5 空态

- 两路都为空：「还没有技能」+ 一句「技能库或智能体产物里生成技能后，会出现在这里」；
- 搜索没命中：「没有匹配「<关键词>」的技能」+「清空搜索」；
- 只有库为空但智能体有技能：照常展示。

## 5. 专家侧的两处小改

### 5.1 评估入口：已存在，不动

`AgentCard` 的卡底已有「设计 / 评估 / 编辑 / 删除」，`onEvaluate` 直接落 `?stage=evaluation`（`AgentListPage.tsx:241`）。首页「评估智能体」卡只是导航到 `/agents`。

### 5.2 智能体技能的「优化」：设计页接收 replay

设计页的开发阶段已经有 `seed.firstPrompt`（路由 state），但它**只在会话为空时补发**——对已有对话的智能体等于不生效。所以这条改用 **replay**（放进发送框，不自动发）：

- `/skills` 点智能体技能的「优化」→ `navigate('/agents/<id>/design', { state: { replay: { text, paths } } })`；
- `text` = 与工坊首条消息**同一句**：`/skill-optimizer:skill_optimize --mode optimize --skill-path "<skillMdPath>"`（+ 用户写了要求时接 `--expert-guidance "<正文>"`），拼法统一在 `composeOptimizeMessage`（`compose-prompt.ts`）—— 三个入口各写一遍必然漂移；（可附一行「改动会更新该智能体的当前产物」）
- `AgentCreatePage` 读 `location.state.replay` → 转成 `Composer` 的 `replay` prop（`ComposerReplay` 已存在，`key` 自增即可），**不自动发送**：一轮优化跑几分钟、烧 token，发不发由用户按发送键；
- 不进 `useCreationChat`：它管会话与首轮，这条只是「把话放进框里」。

## 6. 数据依赖

| 用途 | 接口 | 状态 |
|---|---|---|
| 技能列表 / 库根 / 工坊 cwd | `GET /skills?workspaceId=` | **新增**（后端文档 §4） |
| 产物技能清单 / 装配 / 删除 | `GET /agents/:id/skills`、`POST /agents/:id/skills`、`POST /agents/:id/skills/remove` | **新增**（后端 [4.13](../../server/docs/04-api/4.13-智能体技能.md)） |
| 建工坊会话 | `POST /sessions/create { cwd, modelId, name? }` | **新增入参形态** |
| 工坊历史 | `GET /sessions/list?cwd=&stage=development` | **新增过滤参数**（不带阶段时默认只返回 runtime） |
| 会话 DTO | `instance.agentId` 可空、`instance.cwd` | **变更**（两处读点，见后端文档 §3.6） |
| 对话 / 审批 / 停止 | WS `send` / `messages` / `abort` | 已有 |
| 文件 | `/fs/list`、`/fs/read`、`/fs/raw` | 已有 |
| 智能体列表 / 产物状态 | `GET /agents`、`GET /agents/:id/production` | 已有 |

## 7. 实施清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/shared/api/skills.ts`（新增） | `list(workspaceId)` 的类型与调用；`Skill` / `SkillsResponse` |
| 2 | `src/shared/api/sessions.ts` | `createByCwd`、`list({ cwd })`；`instance.cwd` 类型 |
| 3 | `src/features/skill-library/SkillLibraryPanel.tsx`（新增） | tab 内容：取数、三态、刷新 |
| 4 | `src/features/skill-library/components/SkillCard.tsx`（新增） | §4.2 |
| 5 | `src/features/skill-library/skill-library.css`（新增） | 技能卡；栅格 / 错误条 / 空态沿用 `agent-list.css` |
| 6 | `src/features/skill-workshop/WorkshopPage.tsx`（新增） | §3.1 / §3.2（顶栏 + 对话 + Composer，**无目标条**） |
| 7 | `src/features/skill-workshop/components/HistoryDrawer.tsx`（新增） | §3.4 |
| 8 | `src/features/skill-workshop/compose-prompt.ts`（新增） | §3.3 的纯函数（好单测） |
| 9 | `src/features/skill-workshop/useWorkshopSession.ts`（新增） | 延迟建会话 + openSession + send 前缀 |
| 11 | `src/App.tsx` | 导航改名「专家·技能」；`/skills` 重定向；`/workshop` 路由 |
| 11b | `src/features/agent-list/AgentListPage.tsx` | 页头 tab（`?tab=skills`）+ 挂技能面板 |
| 12 | `src/features/home/HomePage.tsx` | 三张快捷卡 |
| 13 | `src/features/agent-create/AgentCreatePage.tsx` | 消费 `location.state.replay` |
| 14 | `src/i18n/messages/{zh-CN,en-US}.ts` | 新页面文案 |

## 8. 自检清单

- [ ] 首页「创建技能」→ 工坊，直接发送 → 工坊 cwd 下出现 `output/skills/<name>/v1/SKILL.md`。
- [ ] 回 `/skills` 刷新，新技能出现，来源标 `技能库`。
- [ ] 点「优化」→ 工坊空态说明在改哪个技能；发送后首条消息带绝对路径的 `SKILL.md`。
- [ ] 刷新工坊页，会话经 `?session=` 恢复，历史抽屉里能看到这一场。
- [ ] 没发送就离开，历史里没有空会话。
- [ ] 智能体技能的「优化」→ 设计页，**发送框里已有那句话，但没有自动发**。
- [ ] 专家卡「评估」→ 评估阶段，行为与改动前一致。
- [ ] 无工作区 / 无模型 / 后端没起：四个入口都给出原因，不出现空白页。
- [ ] 技能库里同名技能两路来源，标签能区分，优化不串台。

## 9. 不做 / 待定

**不做**

- 能力 chip、目标 chip、正文目标解析、歧义弹窗（§2）。
- 用户消息里的命令渲染成徽标（P1，见 §3.3）。
- 工坊会话按技能分桶（P1：后端把优化会话的 cwd 下探到技能目录之后才成立，见后端文档 §6）。
- 技能删除 / 重命名 / 标签（P2）。
- 评估阶段的正文预填：本设计里首页不再携带正文到评估，评估页「开始评估」保持现状。

**待定**

1. 创建场的历史命名是「正文前 20 字」，换成「技能名」需要**模型产完技能后回写会话名** —— 本期没有改名端点。
