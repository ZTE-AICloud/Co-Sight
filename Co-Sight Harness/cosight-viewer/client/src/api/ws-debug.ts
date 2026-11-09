// SPDX-License-Identifier: Apache-2.0
/**
 * @file ws-debug.ts
 * @description agent-runtime WebSocket 的**诊断日志开关**,默认关闭。
 *
 * 之前的逐帧 `console.log` 被当冗余代码清理掉了 —— 逐帧打全量 payload 确实会淹掉
 * 控制台,而且开着 DevTools 时 DevTools 会一直持有被打印的对象(不回收)。但它也是
 * 前端唯一能看到 agent-runtime 流量的地方,一刀切掉会让问题无从定位。所以改成:
 *
 *   - **开**:`?wsDebug=1` → 打印连接生命周期 + 每一帧的收发(含完整 payload)。
 *     开关会记进 localStorage,之后刷新/换页仍生效,不用每次改链接。
 *   - **关**:`?wsDebug=0`,或不带参数且没开过 → **一次 `console.*` 都不调**,
 *     所以关闭时是零成本,与 DevTools 开不开无关。
 *   - 也可以在控制台里随手开关:`__wsDebug(true)` / `__wsDebug(false)`。
 *
 * 本文件是全仓库**唯一**输出 WS 帧日志的地方,便于审计与统一关闭。
 */

/** localStorage 键:一次开启后持久生效 */
const STORAGE_KEY = "cosight:wsDebug";

/** URL 参数名 */
const PARAM = "wsDebug";

/**
 * 从 URL 读开关。返回 `null` 表示 URL 没指定,应回落到 localStorage。
 *
 * ⚠️ 应用用的是 HashRouter,查询串在 `#` 后面 —— `#/chat?wsDebug=1` 时
 * `window.location.search` 是空的,参数在 hash 里。两边都要读。
 */
function readFlagFromUrl(): boolean | null {
  if (typeof window === "undefined") return null;

  const fromSearch = new URLSearchParams(window.location.search).get(PARAM);
  const hash = window.location.hash;
  const fromHash = new URLSearchParams(
    hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : ""
  ).get(PARAM);

  const raw = fromSearch ?? fromHash;
  if (raw === null) return null;
  if (raw === "0" || raw === "false" || raw === "off") return false;
  if (raw === "1" || raw === "true" || raw === "on") return true;
  return null;
}

/** 内存缓存,避免每帧都去读 storage */
let cached: boolean | null = null;

/** 诊断日志是否开启。 */
export function isWsDebugEnabled(): boolean {
  if (cached !== null) return cached;

  if (typeof window === "undefined") {
    cached = false;
    return cached;
  }

  const fromUrl = readFlagFromUrl();
  if (fromUrl !== null) {
    cached = fromUrl;
    try {
      if (fromUrl) window.localStorage.setItem(STORAGE_KEY, "1");
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // 隐私模式等场景下 localStorage 不可用,不影响本次会话生效
    }
    return cached;
  }

  try {
    cached = window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    cached = false;
  }
  return cached;
}

/** 运行时开关(同时写回 localStorage)。 */
export function setWsDebugEnabled(enabled: boolean): void {
  cached = enabled;
  if (typeof window === "undefined") return;
  try {
    if (enabled) window.localStorage.setItem(STORAGE_KEY, "1");
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 忽略
  }
}

/**
 * 连接生命周期。
 *
 * 这是 console 相对 DevTools Network 面板**不可替代**的部分:连接断开后 Network
 * 里那条记录的呈现很反直觉,而"什么时候断的、有没有重连"正是排查会话类问题的关键。
 */
export function wsLogLifecycle(
  kind: "connected" | "disconnected" | "error",
  detail?: string
): void {
  if (!isWsDebugEnabled()) return;
  // eslint-disable-next-line no-console
  console.log(`[ChatSocket] ${kind}${detail ? ` — ${detail}` : ""}`);
}

/**
 * 一帧的方向、方法与体积,附完整 payload。
 *
 * `size` 由调用方传入:接收方向直接用原始帧字符串长度(解析前顺手拿,免费),
 * 避免为了打印而额外 stringify 一次。
 *
 * 心跳(ping/pong)不打 —— 每 30 秒一对,纯噪音,开了开关也只会在控制台里刷屏。
 */
export function wsLogFrame(
  direction: "→" | "←",
  method: string,
  size: number,
  payload?: unknown
): void {
  if (!isWsDebugEnabled()) return;
  if (method === "ping" || method === "pong") return;
  // eslint-disable-next-line no-console
  console.log(`[ChatSocket] ${direction} ${method} ${size}B`, payload);
}

// 便于在控制台里手动开关:__wsDebug(true) / __wsDebug(false)
declare global {
  interface Window {
    __wsDebug?: (enabled: boolean) => boolean;
  }
}

if (typeof window !== "undefined") {
  window.__wsDebug = (enabled: boolean) => {
    setWsDebugEnabled(enabled);
    return enabled;
  };
}
