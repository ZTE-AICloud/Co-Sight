/**
 * 「最近会话」的 smart-factory 数据源实现。
 *
 * **这是本功能唯一知道 smart-factory 地址、路径与响应形状的地方**；其它文件
 * （UI、查询、领域映射）都只依赖 `RecentSessionSource`。换来源时删掉这个文件、
 * 换一个实现即可。
 *
 * 直连模块后端而不是走框架 `/api` 的理由：
 * - 框架的 `/api` 没有模块数据的代理，也没有"会话"这类资源——框架只负责外壳与
 *   capability 路由；
 * - 模块前端跑在自己的源上（4110），它的 `/api` 由 Vite（开发）或
 *   `web-server.mjs`（产物）反代到后端，但两者都**没有给跨源页面加 CORS 头**；
 * - 模块后端本身 `cors({ origin: '*' })`，因此从宿主页面直接调 4100 是通的。
 *
 * 端口沿用代码默认值（与 `cosight-viewer/client/src/config/api-config.ts` 同一口径）：
 * 改 smart-factory 默认端口时必须同批改这两处。
 *
 * 响应是**裸 JSON**，没有框架的 `{ success, data, meta }` 信封，所以不走
 * `api/client.ts`。
 */

import {
  RECENT_SESSION_LIMIT,
  toRecentSessions,
  type ServiceSession,
} from './session-view';
import type { RecentSession, RecentSessionSource } from './source';

/** smart-factory 后端基址（与模块清单里的前端 entry 同机不同口，见文件头）。 */
const SMART_FACTORY_API_URL = 'http://127.0.0.1:4100/api/smart-factory/v1';

interface ServiceSessionPage {
  items: ServiceSession[];
  total: number;
}

/**
 * 读裸 JSON。用 `text()` 再 `JSON.parse` 而不是 `response.json()`：测试里的
 * `fetch` 打桩只实现了 `status` / `text()`（见 `tests/helpers/render.tsx`），
 * 与 `api/client.ts` 的 `readJson` 保持同一口径。
 */
async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${SMART_FACTORY_API_URL}${path}`, {
    method: 'GET',
    mode: 'cors',
    ...(signal === undefined ? {} : { signal }),
  });
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`会话服务返回 HTTP ${String(response.status)}`);
  }
  const text = await response.text();
  if (text === '') {
    throw new Error('会话服务返回了空响应');
  }
  return JSON.parse(text) as T;
}

export const smartFactoryRecentSource: RecentSessionSource = {
  async list(signal?: AbortSignal): Promise<RecentSession[]> {
    const page = await getJson<ServiceSessionPage>(
      `/sessions/list?page=1&pageSize=${String(RECENT_SESSION_LIMIT)}`,
      signal,
    );
    return toRecentSessions(page.items);
  },
};
