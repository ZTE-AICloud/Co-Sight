// SPDX-License-Identifier: Apache-2.0
/**
 * @file host-params.ts
 * @description 把**宿主(harness)的入口信息**翻译成本模块自己的路由与参数。
 *
 * 这是全模块唯一读宿主参数的地方 —— 页面层只认本应用自己的 `hash` 路由与查询串,
 * 于是 `pages/ChatPage.tsx` 与商业版逐行一致(它读 `useSearchParams().get("agentId")`)。
 *
 * ⚠️ 为什么不能直接用 `useSearchParams()` 读宿主参数:
 * 宿主把参数拼在 iframe 地址的 `?` 上(`…:4830/?locale=…&capability=…&expert=…`),
 * 那属于 `location.search`;而本应用是 **HashRouter**,页面自己的参数在 `#` 之后。
 * `useSearchParams()` 只读后者。
 *
 * 宿主侧对应的传参见 `framework/web/src/components/module/ModuleHost.tsx`:
 * `locale`(界面语言)、`capability`(当前能力);另有专家页「使用」回跳带的 `expert`,
 * 以及宿主侧栏「最近」点会话时带的 `agentRuntimeSessionId` / `resumeSessionId`。
 */

/**
 * 从宿主查询串**原样搬进哈希**的参数。
 *
 * 这两个是「恢复会话」的两个入口(ChatPage 的 `initialSessionId` /
 * `initialResumeSessionId`)。宿主的侧栏「最近」把一个会话 id 拼在 iframe 地址的
 * `?` 上,而页面层读的是哈希里的查询串,所以必须在这里搬一次;不搬的话 iframe
 * 地址看着带了参数,对话页却停在新会话空态。
 *
 * 与 `expert` 不同,这里**不做改名**:两个名字在页面层就是最终名字,多一层映射
 * 只会让"宿主与模块之间用哪个词"多一处需要记住的地方。
 */
const PASS_THROUGH_PARAMS = ["agentRuntimeSessionId", "resumeSessionId"] as const;

/** 取宿主传下来的参数(不在哈希段里)。 */
function readHostParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

/**
 * 能力 → 本模块的内部路由(HashRouter 的 hash 段)。
 *
 * 为什么需要它:宿主拼 iframe 地址时**只用清单的 `entry`**,`mount.path` 不参与;
 * 而 cosight-viewer 的清单同时挂了「新建对话」与「观测」两个能力 → 两者的 iframe
 * 地址完全相同。模块因此必须自己按 `capability` 决定渲染哪个页面。
 */
const CAPABILITY_ROUTES: Record<string, string> = {
  conversation: "/chat",
  observability: "/sessions",
};

/** 当前哈希是否还停在"没有路由"的状态(`""` / `#` / `#/` 都算没有)。 */
function hasNoRoute(route: string): boolean {
  return route.replace(/^\/+/, "") === "";
}

/**
 * 把宿主入口翻译成模块内部路由 —— **必须在 `<Router>` 挂载之前调用**(见 `App.tsx`)。
 *
 * 用 `history.replaceState` 直接改地址,而不是渲染后再 `navigate()`:踩过的坑是
 * HashRouter 初始化会把地址规范化成 `#/`,渲染后的导航会被那次规范化覆盖
 * (表现为"日志里明明成功了、地址却又回到 `#/`")。这里也在 Router 之前执行,天然没这个竞态。
 *
 * 做三件事:
 *   1. **按能力摆路由**:`capability=conversation → #/chat`、`observability → #/sessions`;
 *   2. **翻译宿主参数**:`?expert=<uuid>` → 写成哈希里的 `?agentId=<uuid>`。
 *      翻译之后,页面层读的就是本应用自己的 `agentId` —— 与商业版 `?agentId=` 走同一条
 *      预选路径(`useChatSession` 里那个只生效一次的 `preselectionDoneRef`),因此
 *      **进来时替用户选好、之后照常能改选**。
 *      哈希里已有 `agentId` 时不覆盖:站内链接(如 `/agents` 回跳)的显式意图优先。
 *   3. **透传恢复会话参数**:`?agentRuntimeSessionId=` / `?resumeSessionId=` 搬进哈希
 *      (见 `PASS_THROUGH_PARAMS`),宿主侧栏「最近」靠它直接恢复一场会话。
 *
 * 只在"哈希里没有路由"时摆路由;已有路由(用户直接以 `#/chat` 打开、或自己导航过)不干预。
 */
export function applyHostEntry(): void {
  if (typeof window === "undefined") return;

  const rawHash = window.location.hash.replace(/^#/, "");
  const [rawRoute = "", rawQuery = ""] = rawHash.split("?");
  const capabilityRoute = hasNoRoute(rawRoute)
    ? (CAPABILITY_ROUTES[readHostParam("capability") ?? ""] ?? null)
    : null;
  const route = capabilityRoute ?? rawRoute;

  const params = new URLSearchParams(rawQuery);
  const hostExpertId = readHostParam("expert");
  if (hostExpertId && !params.has("agentId")) {
    params.set("agentId", hostExpertId);
  }

  // 恢复会话:哈希里已有同名参数时以哈希为准(站内导航的意图更具体)。
  for (const name of PASS_THROUGH_PARAMS) {
    const value = readHostParam(name);
    if (value !== null && value !== "" && !params.has(name)) {
      params.set(name, value);
    }
  }

  const query = params.toString();
  const nextHash = `#/${route.replace(/^\/+/, "")}${query === "" ? "" : `?${query}`}`;
  if (nextHash !== window.location.hash) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${nextHash}`
    );
  }
}
