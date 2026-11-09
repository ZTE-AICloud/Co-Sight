/**
 * 本页是不是正被宿主页面嵌在 iframe 里。
 *
 * 现在只有一件事要它：把**只属于独立访问的外壳**收掉 —— 就是左侧菜单（见 `App.tsx`）。
 * 被框架嵌着打开时导航归宿主页面负责，模块自己再挂一条侧边栏就是两个导航打架。
 *
 * 判据用 `window.self !== window.top`：跨源下被禁的是**读** `window.top` 的属性，
 * **比较引用**本身不抛异常，所以框架那种 sandbox iframe 里照样成立
 * （同一招 `features/agent-list/AgentListPage.tsx` 的 `useExpertInFramework` 也在用）。
 *
 * 不用 `document.referrer` 判这件事：它会被 `Referrer-Policy: no-referrer` 抹掉，
 * 而且宿主页地址一变判断就飘 —— referrer 只适合推"宿主首页地址"那种用途。
 *
 * 按框架的模块清单契约，模块与宿主**必然不同源**，所以这个判据在本仓没有假阳性
 * （能误判的只有同源 iframe，而契约禁止同源）。
 */

/**
 * `?embed=` 的显式强扭：`1` 当被嵌、`0` 当独立，没带或值不认识就是 `null`（不表态）。
 *
 * 留这个开关是为了**调嵌态**：被宿主嵌着时想把侧边栏调出来看一眼、或单跑时想确认嵌态
 * 长什么样，加个参数就行，不用改代码。
 *
 * 它**不是**主判据 —— 宿主是另一个团队，把"菜单该不该出"押在"他们每次记得带参数"上
 * 是交付风险。所以缺省回落到自动判，参数只用来强扭。
 */
function forcedEmbed(): boolean | null {
  const value = new URLSearchParams(window.location.search).get('embed');
  if (value === '1') return true;
  if (value === '0') return false;
  return null;
}

/** 本页是否被嵌在 iframe 里（`?embed=1/0` 优先，缺省按 `window.self !== window.top` 判） */
export function isEmbedded(): boolean {
  const forced = forcedEmbed();
  if (forced !== null) return forced;

  // `window.top` 的类型带着 null，只有自己就是顶层时才可能是 null
  const top = window.top;
  return top !== null && window.self !== top;
}
