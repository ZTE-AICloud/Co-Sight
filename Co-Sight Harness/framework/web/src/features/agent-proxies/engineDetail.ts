/**
 * Agent 代理面板的数据源：smart-factory 的 `GET /engine/detail`。
 *
 * 本期 Agent 代理配置只展示**一个**代理 —— smart-factory 正在跑的 Claude Code。
 * 地址、路径与响应形状只出现在这一处；换来源时改这个文件即可。
 *
 * 直连模块后端而不是走框架 `/api`：框架没有模块数据的代理，且模块后端
 * `cors({ origin: '*' })`，从宿主页面直接调 4100 是通的（与
 * `recent-sessions/smart-factory-source.ts` 同一口径）。
 *
 * 响应是**裸 JSON**，没有框架的 `{ success, data, meta }` 信封，所以不走
 * `api/client.ts`。用 `text()` 再 `JSON.parse` 而不是 `response.json()`：
 * 测试里的 fetch 打桩只实现了 `status` / `text()`（见 `tests/helpers/render.tsx`）。
 */

import { useQuery } from '@tanstack/react-query';

/** `GET /engine/detail` 的响应形状（契约见 smart-factory `04-api/4.16`）。 */
export interface EngineDetail {
  /** 适配器标识：`claude-cli` / `fake` */
  engine: string;
  /** 探测时用的工作目录 */
  cwd: string;
  /** Claude Code 版本；老版本不报时为空串 */
  version: string;
  /** `/` 菜单里可见的技能与命令数 */
  commandCount: number;
  /** CLI 是否可用；缺省视为可用（兼容旧响应）。 */
  available?: boolean;
  /** 不可用原因。 */
  reason?: string;
  /** 安装 / 升级指引。 */
  installHint?: string;
}

/** smart-factory 后端基址（端口改动时同步改这里）。 */
const SMART_FACTORY_API_URL = 'http://127.0.0.1:4100/api/smart-factory/v1';

export async function fetchEngineDetail(signal?: AbortSignal): Promise<EngineDetail> {
  const response = await fetch(`${SMART_FACTORY_API_URL}/engine/detail`, {
    method: 'GET',
    mode: 'cors',
    ...(signal === undefined ? {} : { signal }),
  });
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Agent 代理信息接口返回 HTTP ${String(response.status)}`);
  }
  const text = await response.text();
  if (text === '') {
    throw new Error('Agent 代理信息接口返回了空响应');
  }
  const parsed: unknown = JSON.parse(text);
  // 裸 JSON 没有信封可校验：`null` / 字符串同样能解析成功，放进去会让面板读字段时炸掉。
  if (parsed === null || typeof parsed !== 'object') {
    throw new Error('Agent 代理信息接口返回了非对象响应');
  }
  return parsed as EngineDetail;
}

export const engineDetailKeys = {
  detail: ['agent-proxy-engine-detail'] as const,
};

/**
 * `enabled` 由调用方按"用户是否正看着这个面板"传入：设置弹窗把各配置面板**常驻挂载**
 * 在 `<section hidden>` 里（切页签不卸载，保住未保存的表单），但每次取详情都会让
 * smart-factory 起一个 Claude Code 探测进程（1–2 秒、200MB+）。不能因为"打开了设置"
 * 就替用户起一个他从没看过、甚至不知道存在的进程。
 *
 * `refetchOnWindowFocus: false`：窗口重新聚焦不会改变本机引擎信息，而每次重取都要
 * 再起一个进程 —— 这个面板不配享受"切回来就刷新"的默认待遇。
 */
export function useEngineDetail(enabled = true) {
  return useQuery({
    queryKey: engineDetailKeys.detail,
    queryFn: ({ signal }) => fetchEngineDetail(signal),
    enabled,
    refetchOnWindowFocus: false,
  });
}
