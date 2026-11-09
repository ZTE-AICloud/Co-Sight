# 环境与自测

> **本文件只写从代码里读不出来的环境知识**（命令、端口、数据落在哪、怎么自测）。
> 凡是 `package.json` / `vite.config.ts` 里能读到的，这里不重复。
>
> 最后核对：2026-10-17

## 跑起来

后端和前端要**同时**起（专家页的数据来自本仓 server）：

```bash
cd server && npm run dev     # :4100，见 server/.env
cd web    && npm run dev     # :4110
```

- **后端没起的样子**是「响应不是 JSON」：vite 代理连不上 4100，回的是 HTML。前端会把这一族
  翻译成「本地服务没响应 —— 确认 server 已启动」，判据见 `shared/api/agents.ts` 的 `isBackendDown`。
- 后端 `ENGINE=fake` 可以跳过模型配置校验，只是看页面的话够用：
  `ENGINE=fake npm run dev`。
- **创建页阶段①（生成）需要后端**：那一栏的对话是真的 —— 进页面就按 `(agentId, development)`
  找或建会话、连实时通道。只起前端的话，那一页停在「连不上本地服务」（阶段②③仍是演示内核，
  不需要后端）。桩引擎的触发词（`需要审批` / `连续审批` / `需要提问` / `带思考` / `带工具`）可以对出各类帧。

## 专家卡片「使用」跳去哪

那一颗是**离开本模块**的整页跳转（去框架首页＝会话页），不是模块内的路由。
地址与三条硬约束写在 `src/features/agent-list/AgentListPage.tsx` 的 `useExpertInFramework`；
这里只说环境口径：

- **被框架嵌着**（`http://localhost:4310/agent-dev` 那个 iframe）时，地址按 `document.referrer`
  的源推，不用配任何变量 —— 模块与宿主**必然**不同源（框架的模块清单契约禁止同源）。
- **单跑 4110**（浏览器直接开）时落到 `http://localhost:4310/`；框架不在本机这个地址才需要
  `VITE_FRAMEWORK_HOME_URL`（见 `.env.example`）。
- **2026-10-21 起是原页跳转**：framework 的 `ModuleHost` iframe 给了
  `allow-top-navigation-by-user-activation`（D44 补充），用户点一下就能带顶层走。
  宿主还是旧版本（没这条权限）时，顶层跳转会被挡下（Chrome 抛 SecurityError），代码
  catch 住回落成 `window.open` —— **看到"点了多出一个标签页"不是模块的 bug**，是宿主版本旧。
- 自测这一颗不必起框架：URL 会照样变（4310 没起就是连接失败页），断言 `location.href` 即可。

## 被框架嵌着时（嵌态）

模块会被框架嵌在 iframe 里（上面那个 `http://localhost:4310/agent-dev`）。**嵌态下不挂左侧菜单**：
导航归宿主页面，模块再挂一条就是两个导航打架。判据与 `?embed=` 调试开关见 `src/shared/embed.ts`。

自测**不用起框架**，三种看法：

- **想看嵌态**：单跑 4110 加参数 —— `http://localhost:4110/agents?embed=1`
- **被嵌着想把菜单调出来**：宿主 iframe 的地址加 `?embed=0`
- **想看真的嵌态**：自己写个宿主页 iframe 指向 4110，**端口不同就是跨源**，够用了

**部署别给模块加 `X-Frame-Options` / CSP `frame-ancestors`** —— 加了宿主就嵌不进来。
vite dev 默认不发这两个头，挂 nginx 时最容易顺手加上。

## 演示数据在哪、怎么重置

- **智能体（专家）**：在 `{SMART_FACTORY_HOME:-~/.smart-factory}/smart-factory.db` 里，
  没有 seed。要造数据就调接口或走页面：
  `curl -X POST localhost:4100/api/smart-factory/v1/agents -H 'Content-Type: application/json' -d '{"name":"天气专家"}'`
  （初次要建库就 `cd server && node scripts/db.mjs sync` —— db push + bootstrap.sql，自己从 COSIGHT_HOME 推连接串）。
- **模型**：在**框架（Cosight）**的「设置 → 模型设置」里维护 —— 本模块只有只读列表，
  没有新增 / 编辑 / 删除。前端打 `GET /api/smart-factory/v1/models/list`（本仓 server 代理），
  由 server 读 `$COSIGHT_HOME/.module-token` 去框架取；浏览器不直接接触框架接口与密钥。
  框架没起或令牌不对时，下拉会显示服务端翻译好的中文原因。
- 智能体与模型**都没有 mock 中间件了**（`web/mock/` 已随后端落地一起删掉）。
- **会话**：创建页进阶段①时自动找一个智能体的 development 会话，没有才建 —— 所以自测点几次
  页面不会堆出一串空会话，刷新也能看到上次的对话。要清就删那几条 `sessions` 行（或换一个
  `SMART_FACTORY_HOME`）。

## 自测：怎么驱动浏览器（本机没有 Playwright）

用 `google-chrome --headless=new` + CDP，Node 内置 `WebSocket` 直连调试端口即可。
把**目标 URL 直接写在启动参数里**，不要启动后再 `Page.navigate`（原因见第 5 条）：

```bash
google-chrome --headless=new --remote-debugging-port=9444 --remote-allow-origins='*' \
  --user-data-dir=/tmp/<自己起个目录> --disable-gpu --blink-settings=primaryHoverType=2,availableHoverTypes=2 \
  --window-size=1440,907 "http://localhost:4110/agents"
```

六条坑，都踩过：

1. **`--window-size` 比真实视口高 87px**：想要 820 高的视口就写 `907`。
   或者干脆用 `Emulation.setDeviceMetricsOverride` 把视口钉死。
2. **连不上先加 `--remote-allow-origins='*'`**：不加的话 WebSocket 握手会被拒，脚本会静默挂住。
3. **`console.log` 写到管道是异步的**：脚本被 kill 时输出会整片丢失（现象是「什么都没打印」，
   其实已经跑完了）。调试期输出一律重定向到文件。
4. **Enter 发送要带 `text: '\r'`**：`dispatchKeyEvent` 只给 keyCode 不触发提交。
5. **`hover` 媒体特性在无头下不可靠**：默认报 `hover: none`，会把「悬停才显」的**触屏兜底**
   当真相（专家卡片上的编辑/删除就全冒出来了）。只能靠启动参数
   `--blink-settings=primaryHoverType=2,availableHoverTypes=2` 打开，**而且一旦发生导航就丢**。
   想覆盖它，`Emulation.setEmulatedMedia` 不管用（反而把 blink 的设置重置回 none）——
   要么让 chrome 直接启动在目标 URL 上、不要 `Page.navigate`，要么截屏前往页面里插一条
   同名的 `!important` 样式把桌面那套规则压在最上面。
6. **同一张截图前一定要重新导航**：复用页面会把上一张的弹窗 / 筛选状态带进来，拍出来的不是初态。

交互驱动优先用 `Input.insertText`（走真实输入事件，中文没问题）和
`Input.dispatchMouseEvent`；直接改 DOM 会绕过 React 的事件，测出来的不是真实行为。

## 本机是多会话共用

- 每个会话可能各起一个 vite，**杀进程按端口找 pid**（`ss -ltnp | grep <port>`），
  不要 `pkill -f vite` —— 会误杀别人的，也会把你自己那条命令匹配掉。
- **chrome 的调试端口也别写死**：上面那条命令里的 `9444` 只是举例。本机各会话各起各的 chrome，
  写死就会**连到别人那个实例上** —— 现象是 `Runtime.evaluate` 拿到的页面不是你在开的那个
  （踩过：连上别的会话的 chrome，读到的是另一个 vite 端口下的页面，查半天以为页面没渲染）。
  用 `--remote-debugging-port=0` 让 chrome 自己挑，再从 `<user-data-dir>/DevToolsActivePort`
  第一行读回端口。
- 端口冲突就用 `SMART_FACTORY_WEB_PORT` / `SMART_FACTORY_SERVER_PORT` 另起一组。
- 数据落在 `SMART_FACTORY_HOME`：**自测用独立的临时目录**（`SMART_FACTORY_HOME=/tmp/...`），
  别往用户真实的 `~/.smart-factory` 里造记录。

## 改完至少跑一次

- `npm run typecheck`。dev server 不做类型检查，React 的未知 prop 只是静默忽略 ——
  共享组件改签名（如 `Composer`）时，漏改的调用点只会在 typecheck 里暴露。
- 动了 `server/` 就跑 `cd server && npm test`。
