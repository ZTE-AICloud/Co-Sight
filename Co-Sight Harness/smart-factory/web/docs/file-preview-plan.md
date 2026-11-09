# 对话文件引用预览（右侧栏）实施方案

> 状态：**已实现**（2026-10-21 落码：后端 `/fs/read`、`/fs/raw/*`；前端 `shared/components/FilePreview/*` 与四个接入点）
> 参考：dsh web（本机 `@deepseek-ai/dsh@0.2.0-rc.2`）的 `fileMentions` + `sidebarRight.openResource` 链路
> 落到本仓时砍掉了它的插件注册表 / RPC / 分页，只保留对本项目成立的那部分。

---

## 0. 一句话

**前端算出「哪些词是文件」并渲染成按钮，点了才去后端读，读回来在右侧停靠面板里按扩展名渲染。**

管线：

```
① 收集路径（前端，按轮）→ ② 匹配（前端）→ ③ 渲染成可点（前端）
→ ④ 点击解析绝对路径（前端）→ ⑤ 后端读（/fs/read、/fs/raw）→ ⑥ 右侧面板渲染（前端）
```

匹配**不在后端**：文件名出现在对话正文里，后端看不到渲染上下文。

---

## 1. 目标

1. 对话正文里的文件引用（行内代码、本地 Markdown 链接）、工具调用里的 `file_path`、已发消息的附件 chip，点击后**在右侧打开文件内容**。
2. `.md` 按 Markdown 渲染；`.html` 真正渲染（可执行脚本，但被沙箱隔离）；图片按图片显示；代码按源码显示；二进制给下载。
3. 同一文件重复点击只聚焦已有 tab，不重复打开。

### 不做（本期）

- **编辑**：后端没有任何写入口，面板只读。
- **运行页（框架会话页）**：那是 `cosight-viewer` / `framework` 的事，不在本仓。组件按「可搬走」放 `shared/`。
- **文本分页**：2 MiB 全量读，超限给下载；dsh 的分页（`offset/limit`）以后需要再加。
- **纯文本里的裸文件名**（不裹代码、不是链接）：不做。误报噪音太大。
- **插件化的 tab 类型 / 渲染器注册表**：本仓没有插件体系，按扩展名直接 if/else 分流。

---

## 2. 关键决策（三条，先看这个）

### 2.1 行内代码的「可点」判定 = 本轮产物集合，不是正则

**不要**用正则判断「这串字符像不像文件名」就直接加链接。dsh 的做法是：把这一轮真正写入过的文件收成一个集合，行内代码只在**精确命中路径**或**basename 唯一命中**时才变成按钮；两个同名文件导致歧义时宁可不做。

- 来源：本轮 `Write` / `Edit` / `MultiEdit` / `NotebookEdit` 工具调用里成功（`tool_result.isError === false`）的 `input.file_path`。
- 数据已经在 `ConversationMessage.entries`（`ToolEntry` 保留了 `input` 与 `status`），**不需要改数据模型**，在 `turns.ts` 里按轮扫一遍即可。
- 只对**已定型消息**生效；流式中的那段（`id` 以 `live-` 开头）不加 mention 解析，避免把过期 handler 固化进渲染。

### 2.2 预览面是右侧停靠面板，不是弹窗

- 页面级 context 持有打开状态；tab 的 **id 就是绝对路径**，天然去重。
- 面板固定在视口右侧，页面根 `.ac` 加一个 `padding-right` 把内容挤压过去 —— 不改 `SplitLayout` 的 grid 模板，三个 stage 通用。
- 窗口窄（< 768px）时退化成全宽覆盖。

### 2.3 读文件走 `fs/*`，不走 `artifacts/*`

- `artifacts` 绑死 `stage + agentId`，只能看 stage 根内；对话里经常出现 stage 外的绝对路径（例如 `~/.../node_modules/.../README.md`）。
- `fs/*` 是「整机只读浏览」模型（`fs/list` 已经如此），预览与它同一口径，一套路径空间覆盖 stage 内外。
- `artifacts` 保持现状，工作区文件树继续用它。

---

## 3. 实施前先读这些文件

| 文件 | 为什么 |
|---|---|
| `web/src/shared/live/map-message.ts` | 消息 → `ConversationMessage` 投影；`ToolEntry` 的 `input/status` 就从这里来 |
| `web/src/shared/components/Conversation/{types.ts,turns.ts,Turn.tsx,Entry.tsx}` | 一轮的分组、渲染链；mention 集合在这里算、往下传 |
| `web/src/shared/components/Markdown/Markdown.tsx` | 行内代码与链接的接入点（`a` 已自定义，`code` 还没有） |
| `web/src/features/agent-create/AgentCreatePage.tsx` | 页面根 `.ac`，预览 Provider/Panel 挂这里；`agent.dir` 也从这里拿 |
| `web/src/features/agent-create/components/FileViewer.tsx` | 扩展名分类 / 语言标签 / 图片分类从这搬（`classify`、`LANGUAGE_BY_EXT` 等） |
| `web/src/shared/api/fs.ts` | 现有 `fsApi`（roots/list），新端点加这里 |
| `server/src/modules/fs/{fs.routes,fs.controller,fs.service}.ts` | 后端落点 |
| `server/src/shared/workspace/local-path.ts` | `resolveLocalTarget`（绝对路径 + realpath 校验），直接复用 |
| `server/src/modules/artifact/artifact.service.ts` | 文本读取 / 大小上限的现成写法，照抄口径 |
| `server/docs/03-architecture/07-artifact.md` | 产物路径与安全口径；本次新端点与它是并列关系 |

---

## 4. 后端：两个只读端点

全部落在 `server/src/modules/fs/`，挂载点已是 `/api/smart-factory/v1`（`server/src/app.ts:39`）。

### 4.1 `GET /fs/read?path=<绝对路径>`

```
200 { path: string, name: string, size: number, mtime: string, content: string }
400 path 缺失 / 非绝对路径 / 不是普通文件
404 路径不存在
413 超过 config.artifactMaxFileBytes（默认 2 MiB）
415（可选）二进制
```

实现要点：

- 路径校验用 `resolveLocalTarget(input.path, 'file')`（`local-path.ts:114`）。
- 读取口径与 `artifactService.file` 完全一致：`readFileSync(path, 'utf8').replace(/^﻿/, '')`，上限复用 `config.artifactMaxFileBytes`（`config/index.ts:54`）。
- 建议加二进制判定：读出的前 8 KiB 含 `\0` → `415`（或返回 `{ binary: true }`）。前端会先按扩展名挡一层，这是兜底。
- 建议顺手支持 `~/`：在 `resolveLocalTarget` 里先 `input = input.replace(/^~(?=\/|$)/, homedir())`。模型很爱写 `~/xxx`，现在会被「必须是绝对路径」挡掉。

### 4.2 `GET /fs/raw/<绝对路径去掉开头的 />`

例：`GET /api/smart-factory/v1/fs/raw/home/u/proj/report.html`

```
200 原始字节流
Content-Type:            按扩展名（res.sendFile 自带）
Content-Disposition:     inline
X-Content-Type-Options:  nosniff
Cache-Control:           no-store
Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups   // html/svg/xml 必须带
```

**为什么必须用路径分段而不是 `?path=`**：HTML 渲染要在 iframe 里加载相对资源。

- `?path=/a/b/index.html` 里 `./style.css` 会被解析成 `/fs/style.css`（query 丢失），全挂；
- `/fs/raw/a/b/index.html` 里 `./style.css` 自然落到 `/fs/raw/a/b/style.css`，图表、CSS、相对跳转全部正确。

实现要点：

- Express 5：`fsRouter.get('/fs/raw/*splat', ...)`，`req.params.splat` 是段数组，拼回 `'/' + segments.join('/')`。
- 前端每段 `encodeURIComponent`；服务端用 `resolveLocalTarget` 再校验一次。
- `res.sendFile(real, { dotfiles: 'allow', headers })`。**`dotfiles: 'allow'` 必须带**：产物路径常有 `.smart-factory` 这类点段，`artifact.controller.ts:24` 已经踩过这个坑。
- 文本上限不适用于 raw（`/read` 才限 2 MiB）；大 HTML / 图片 / PDF 靠流式发送。
- 响应头里 `CSP: sandbox` 只对文档类资源有意义，统一加也无害。

### 4.3 测试

`server/tests/fs-api.test.ts` 追加：

1. `read` 正常返回内容，BOM 被去掉；
2. `read` 相对路径 400、不存在 404、目录 400；
3. `read` 超 2 MiB 413（可用 env 把上限调小）；
4. `read` 含 NUL 的二进制（若实现 415）；
5. `raw` 返回正确 Content-Type；HTML 响应带 `nosniff` 与 `CSP: sandbox`；
6. `raw` 的路径分段能处理中文 / 空格（`encodeURIComponent` 往返）；
7. `raw` 不存在 404。

### 4.4 文档

- `server/docs/04-api/4.01-接口总览.md` 端点表 +2 行；
- `server/docs/04-api/4.07-待前端对齐.md` 补形状与安全前提；
- 在 `fs.routes.ts` 文件头写清前提：本端点无鉴权、等于整机只读暴露。

---

## 5. 前端

### 5.1 新增共享模块

```
web/src/shared/
├── file-kind.ts                 // 从 FileViewer 抽出：extensionOf / classify / LANGUAGE_BY_EXT / fileIcon / formatBytes
├── file-ref.ts                  // 产物集合 + 匹配 + 路径解析（纯函数，不碰 React）
├── api/fs.ts                    // + read()、rawUrl()
└── components/FilePreview/
    ├── FilePreviewProvider.tsx  // context：标签页状态 + open/close/focus
    ├── FilePreviewPanel.tsx     // 停靠面板：标签条 + 路径条 + 预览/源码切换 + 关闭
    ├── FilePreviewBody.tsx      // 按类型分流渲染
    └── FilePreview.css
```

### 5.2 `file-ref.ts` 的接口

```ts
/** 本轮写过的文件（绝对路径）。从 tool entries 扫，不新增数据模型字段。 */
export function producedPathsOf(turn: ConversationTurn): string[];

/**
 * 行内代码匹配：精确路径命中，或 basename 唯一命中才返回目标路径。
 * 返回 undefined = 保持纯文本。
 */
export function resolveMention(value: string, produced: readonly string[]): string | undefined;

/** 点击时把相对路径解析成绝对路径。绝对路径原样；相对路径拼 baseDir。 */
export function resolveToAbsolute(raw: string, baseDir: string): string;
```

匹配细节：

1. 归一化：`decodeURIComponent`、去 `file://`、去 `#fragment`、去开头的 `./`。
2. 精确命中：`produced` 里存在相等项 → 命中。
3. 后缀命中（推荐加）：`produced` 里存在以 `'/' + value` 结尾的项 → 命中（正文常写相对片段，工具给的是绝对路径）。
4. basename 唯一命中：按 `basename(value)` 过滤，恰好 1 个 → 命中；0 个或多于 1 个 → `undefined`。
5. 永不猜：有歧义就不做链接。

`producedPathsOf(turn)` 的扫描规则：

- 遍历 `turn.replies[].entries`；
- `entry.kind === 'tool'`、`entry.status === 'done'`（`isError` 已被投影成 `failed`）；
- `WRITE_TOOLS = new Set(['Write', 'Edit', 'MultiEdit', 'NotebookEdit'])`；
- 取 `(entry.input as { file_path?: unknown }).file_path`，字符串且非空才收；
- 去重。

> 局限（写进代码注释）：`Bash` 里 `> out.html` 写出来的文件收不到；要覆盖得解析 shell 命令，不做。

### 5.3 四个接入点

| 接入点 | 判定 | 行为 |
|---|---|---|
| **行内代码**（`Markdown` 的 `code`） | `resolveMention(value, produced)` 命中 | 渲染 `<button class="md-file-mention">`（链接图标 + 代码底色），点击 `open(path)` |
| **本地 Markdown 链接**（`Markdown` 的 `a`） | href 不是 `http(s)` / `mailto:` / `#` | 渲染成同样的 button；**显式链接不再查产物集合**（用户/模型明确写了链接就按它打开，路径错由后端 404 兜底）；`#L24` 先剥掉，本期不做行号定位 |
| **工具条目**（`Entry.tsx`） | `entry.kind === 'tool'` 且有 `input.file_path / path / notebook_path` | 摘要文字变成可点链接；`stopPropagation()`，不触发折叠条 |
| **已发附件 chip**（`FileChip.tsx`） | `remove === undefined`（对话气泡下那条） | chip 可点；它本来就是绝对路径 |

组件通信：

- `FilePreviewProvider` 提供 `{ open(path), close(), active, tabs }`；
- `Markdown` 新增可选 prop `fileMentions?: { resolve(value): string | undefined; open(path): void }`，不传时完全保持现行为（demo 页不受影响）；
- `Turn` 把本轮的 `produced` 传给 `Reply` → `Markdown`；流式消息（`id.startsWith('live-')`）传 `undefined`；
- `Entry` / `FileChip` 直接用 `useFilePreview()`。

Markdown 组件里两个细节：

- `code` 组件现在没有自定义；行内代码与围栏代码块共用它。判据：**没有 `language-` 类且内容不含换行**才算行内，再走 mention 匹配。
- `a` 组件现在对相对路径是放行的 —— 那会导致 SPA 路由跳转、被 `*` 兜底静默送回首页（`App.tsx` 有注释提醒过这个坑）。本次一并修掉。

### 5.4 路径解析

```ts
baseDir = `${agent.dir}/${stageId}`   // agent.dir = agentRoot；会话 cwd 就是 agentRoot/<stage>
```

- `agent.dir` 来自 `agentsApi.detail()`（`agents.ts:75`），为空（还没加载完）时 mention 不启用；
- 点击时**当场**解析成绝对路径再交给面板，面板只认绝对路径 —— 这样切 stage 不会把已打开的 tab 解释错；
- `~/` 交给后端展开（见 4.1）。

### 5.5 渲染分流（`FilePreviewBody`）

| 类型 | 渲染 |
|---|---|
| `.md` | 复用 `<Markdown>`；`fileMentions` 的 `baseDir` 用**被预览文件所在目录**，相对链接 / 图片按它解析 |
| `.html/.htm` | `<iframe src={fsApi.rawUrl(path)} sandbox="allow-scripts allow-forms allow-popups allow-downloads" />`；**绝不加 `allow-same-origin`**；配「源码」模式显示 `<pre>` |
| 图片 / `.svg` | `<img src={rawUrl}>`（svg 也走 raw；`nosniff` + CSP 兜底） |
| 其它文本 | `<pre class="fp-code">` + 语言标签 + 复制 |
| 二进制 / 超大 | 不预览，给下载（沿用 `FileViewer.tsx:508` 的 Blob 下载） |

面板头：标签条（每个 tab 一个，可关）+ 当前文件绝对路径（可复制）+ `预览 / 源码` 切换（md、html）+ 重新读取 + 关闭。

错误态：404「文件不存在」、413「文件过大，请下载」、415「二进制文件」、后端不可达「本地服务不可用」，都带路径与重试。

### 5.6 挂载与布局

```tsx
// AgentCreatePage.tsx
<FilePreviewProvider baseDir={agent?.dir ? `${agent.dir}/${stageId}` : null}>
  <div className={`ac${dockOpen ? ' ac--dock-open' : ''}`}>
    ...原有内容...
  </div>
  <FilePreviewPanel />
</FilePreviewProvider>
```

```css
:root { --ac-dock-width: clamp(420px, 46vw, 760px); }

/* 挤压而不是盖住：内容区让出右侧宽度，面板固定贴在视口右边 */
.ac--dock-open { padding-right: var(--ac-dock-width); }

.fp-dock {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--ac-dock-width);
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
  z-index: 50;
}

/* 窄屏退化：全宽覆盖 */
@media (max-width: 767px) {
  .ac--dock-open { padding-right: 0; }
  .fp-dock { width: 100%; }
}
```

要点：

- 本仓定高陷阱：`.app-shell` 是 `min-height: 100vh`，`.ac` 自己钉了 `height: 100vh`（`agent-create.css:11-24`）。面板用 `position: fixed; top/right/bottom: 0`，**不要**指望父级 flex 给高度。
- 嵌入式（iframe）下 `fixed` 以 iframe 视口为准，行为一致。
- 生成 / 评估阶段的右栏文件树保持不动；面板是它之外的一层。预览阶段（单列居中）同样被挤压，不需要另写一套。
- 拖拽调宽是 P3，不做。

---

## 6. 安全

1. **iframe 永不带 `allow-same-origin`**；响应头再叠 `CSP: sandbox`。本地 HTML 的脚本能跑，但拿不到父页面 / cookie / localStorage，也调不动同源业务接口。
2. `X-Content-Type-Options: nosniff` + 按扩展名给类型。
3. 本端点等于整机只读暴露 —— 在路由文件头写死这个前提。
4. 只读，无写入口（与现有 `fs/*` 一致）。
5. **已知局限**：HTML 里的根绝对路径资源（`/assets/x.css`）会落到应用根而不是文件系统根 → 只有相对路径资源与单文件内联 HTML 能完整渲染。agent 产出多为后者；要彻底解决得换独立 origin，不做。

---

## 7. 改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `server/src/modules/fs/fs.service.ts` | `read()`、`raw()` |
| `server/src/modules/fs/fs.controller.ts` | 两个 handler（raw 在这里 `sendFile`） |
| `server/src/modules/fs/fs.routes.ts` | `GET /fs/read`、`GET /fs/raw/*splat` |
| `server/src/shared/workspace/local-path.ts` | 可选：`~/` 展开 |
| `server/tests/fs-api.test.ts` | 见 §4.3 |
| `server/docs/04-api/4.01-接口总览.md`、`4.07-待前端对齐.md` | 端点与前提 |

### 前端

| 文件 | 改动 |
|---|---|
| `web/src/shared/api/fs.ts` | `read()`、`rawUrl()` |
| `web/src/shared/file-kind.ts` | 新建；从 `FileViewer.tsx:63-166` 抽出 |
| `web/src/shared/file-ref.ts` | 新建；产物集合 / 匹配 / 绝对路径解析 |
| `web/src/shared/components/FilePreview/*` | 新建：Provider / Panel / Body / CSS |
| `web/src/shared/components/Markdown/Markdown.tsx`、`Markdown.css` | 行内 code 与本地链接接 panel；文件态样式 |
| `web/src/shared/components/Conversation/Turn.tsx` | 按轮算 `produced` 并往下传；流式消息不传 |
| `web/src/shared/components/Conversation/Entry.tsx` | `file_path` 可点 |
| `web/src/shared/components/FileChip.tsx` | 已发附件可点 |
| `web/src/features/agent-create/AgentCreatePage.tsx` | 挂 Provider + Panel；`.ac--dock-open` |
| `web/src/features/agent-create/agent-create.css` | dock 宽度变量与挤压规则 |
| `web/src/features/agent-create/components/FileViewer.tsx` | 改用共享 `file-kind`；预览区接入 `FilePreviewBody`（md/html 不再是 `<pre>`）；**修掉文件头那段过期的 download 注释**（`artifact.controller.ts:24` 已经修了 dotfiles） |
| `web/src/i18n/messages/{zh-CN,en-US}.ts` | 新增 `filePreview.*`；跑 `npm run check:i18n` |

---

## 8. 分期

| 期 | 内容 | 量 |
|---|---|---|
| **P0** | 后端 `/fs/read` + `/fs/raw/*` + 测试 + 文档 | 0.5 天 |
| **P1** | `file-kind` / `file-ref` / `fs.ts`；`FilePreview` 面板 + Provider；挂到 `AgentCreatePage`（先用固定路径手测） | 1–1.5 天 |
| **P2** | 四个接入点（行内 code / 本地链接 / Entry / FileChip）+ 流式排除 + i18n | 0.5–1 天 |
| **P3** | 可选：run 结束自动重读、`#L24` 行号定位、拖拽调宽、预览面板内相对图片改写 | — |

---

## 9. 验收

1. 点 `[README.md](README.md)` → 右侧打开，路径解析为 `<agent.dir>/<stage>/README.md`，Markdown 渲染。
2. 点行内代码 `output/agents/x/v1/SKILL.md` → 打开并渲染；同一路径重复点只聚焦 tab。
3. 点一个 `.html` → iframe 渲染，相对 CSS / 图片能加载；脚本被 sandbox（控制台里 `localStorage` 抛 SecurityError 属预期）；「源码」能看到原文。
4. 点工具条目的 `file_path` → 打开对应文件，且不触发折叠条展开。
5. stage 外的绝对路径（如 `~/.../node_modules/.../README.md`）能打开。
6. 正文里的 `package.json` 若本轮没写过 → 保持纯文本，不加链接。
7. 两个同名文件（`a/x.ts`、`b/x.ts`）都在本轮产物里 → 正文写 `x.ts` 时不加链接；写完整路径时才加。
8. 404 / 413 / 二进制 → 原因 + 下载出口，不白屏。
9. 后端挂掉 → 面板报「本地服务不可用」，不影响对话。
10. 流式输出过程中不出现文件按钮；落库后（消息定型）才出现。
11. 预览阶段（单列）打开面板会把对话挤压到左侧，窄屏（<768px）全宽覆盖。
12. `web: npx tsc -b --noEmit`、`npm run check:i18n`；`server: npm test` 全绿。

---

## 10. 待定 / 后续

- **运行页复用**：`FilePreviewProvider` / `FilePreviewPanel` / `file-ref` 都放 `shared/`，但框架会话页不 import 本模块，那边要单独接一次。
- **纯文本裸文件名**：需要先有「按消息批量探存在」的接口（`POST /fs/stat`），本期不做。
- **产物集合的来源扩展**：目前只有 Write/Edit 系工具。若以后引擎支持 `present` 类工具或多模态产物，把路径并进 `producedPathsOf` 即可。
- **文件变更自动刷新**：现在只有手动「重新读取」。要自动，可复用 `ProductionStage.tsx` 里 `chat.running` true→false 的信号给当前 tab 重读。
