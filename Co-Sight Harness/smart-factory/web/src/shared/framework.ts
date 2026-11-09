/**
 * 宿主（框架）的地址口径 —— 本模块跑在框架的 iframe 里，「框架在哪」由这里统一推。
 *
 * 两个用途共用同一套口径：卡片「使用」去框架首页（`AgentListPage`），设计页「返回」
 * 回框架的专家页 `/experts`（`AgentCreatePage`）。拆开写迟早会漂。
 *
 * 推导两级（与 `.env.example` 里 `VITE_FRAMEWORK_HOME_URL` 的说明一致）：
 *
 * 1. 被框架嵌着时按 `document.referrer` 的**源**推：跨源只保留 origin（Referrer-Policy
 *    的默认值就是 strict-origin-when-cross-origin），而模块清单契约禁止模块与宿主同源，
 *    所以被嵌时 referrer 的源**必然**是框架 —— 开发态与部署态零配置就对。
 * 2. 没被嵌（浏览器直接开 4110）时落到 `VITE_FRAMEWORK_HOME_URL`，缺省本机 4310。
 */

/**
 * 框架首页（＝会话页）的兜底地址。
 *
 * 只有"单跑 4110、框架又不在本机默认地址"时才用得上它 —— 被嵌在框架里时地址由
 * `document.referrer` 推出来。真要改，配 `VITE_FRAMEWORK_HOME_URL` 比改这里好。
 */
const DEFAULT_FRAMEWORK_HOME = 'http://localhost:4310/';

/** 框架的基址：嵌态是宿主的源，单跑是配置的首页地址（可能自带查询串）。 */
export function frameworkBaseUrl(): string {
  if (window.self !== window.top) {
    try {
      const origin = new URL(document.referrer).origin;
      // 万一将来某个策略让 referrer 变成自己的源，就退回下面的口径 —— 别跳到自己身上。
      if (origin !== window.location.origin) {
        return origin;
      }
    } catch {
      // referrer 为空或不合法（直接打开本模块调试）：落到下面的口径
    }
  }
  // 内层用 `||` 而不是 `??`：`.env.local` 里写了个空串时 `??` 会放行，接着 `new URL('')` 抛错。
  return import.meta.env.VITE_FRAMEWORK_HOME_URL || DEFAULT_FRAMEWORK_HOME;
}

/**
 * 框架的专家页（宿主路由 `/experts`，内容就是本模块被嵌进去的 `/agents` 列表）。
 *
 * 用 `new URL('/experts', base)` 而不是字符串相加：基址可能带查询串或结尾斜杠，
 * 宿主的专家页在路由表的根上（`framework/web/src/app/routes.tsx`）。
 */
export function frameworkExpertsUrl(): string {
  return new URL('/experts', frameworkBaseUrl()).toString();
}

/**
 * 整页离开模块、跳到宿主地址。
 *
 * 三条都是**只能这么写**，不是随手定的（卡片「使用」与设计页「返回」共用）：
 *
 * 1. **被嵌时只能写 `window.top.location.href`。** 跨源下 `location` 允许**写**、不允许**读**，
 *    所以判断不了、只能直接赋。框架的 sandbox 从 2026-10-21 起给了
 *    `allow-top-navigation-by-user-activation`（D44 补充），用户点一下就是原页跳。
 *    宿主还是旧版本、没这条权限时，Chrome 会抛 SecurityError（可捕获，不是静默失败），
 *    于是 catch 里回落成**开新标签**（`allow-popups` 是给了的）—— 按钮不会变成"点了没反应"。
 *    代价：新标签会继承 iframe 的沙箱标记（框架没给 `allow-popups-to-escape-sandbox`），
 *    框架用不到 alert / pointer-lock 那类能力，所以看不出问题。
 * 2. **不能改成 async。** 异步会花掉点击那一次的 transient activation，开新标签会被弹窗拦截器挡掉。
 * 3. **单跑时整页跳就是整页跳**：没有沙箱，`location.assign` 即可。
 */
export function leaveToFramework(target: string): void {
  // `window.top` 的类型是 `Window | null`，只有在自己是顶层时才可能是 null
  const top = window.top;

  if (window.self === top || top === null) {
    window.location.assign(target);
    return;
  }

  try {
    top.location.href = target;
  } catch {
    // 沙箱拦下了顶层跳转（框架还没给 allow-top-navigation-by-user-activation）
    window.open(target, '_blank', 'noopener,noreferrer');
  }
}
