/**
 * API 客户端：统一解包信封。
 *
 * **所有**请求都经这里，页面里不出现裸 `fetch`。理由：信封解包、错误分类、
 * 查询串拼装这三件事只要有一处绕过，就会在某个页面上表现为"错误提示是空的"
 * 或"点了没反应"，而且很难定位到是哪一次调用漏了处理。
 *
 * 基址固定为相对路径 `/api`：
 * - 开发态由 Vite 代理到 :4300（见 vite.config.ts），**保持同源**，
 *   `SameSite=Lax` 的桥接 cookie 才会被带上；
 * - 生产态前端由 harness-server 同源托管，相对路径天然正确。
 * 因此这里**不放** `VITE_API_BASE_URL` 这类可配置项：一旦允许跨源，
 * 上面的 cookie 前提就破了，得同时改三处配置才能修好。
 */

import type { PageMeta } from 'harness-shared';

import { ApiNetworkError, ApiRequestError, looksLikeEnvelope } from './errors';

/** 接口前缀。与 framework/server/src/app.ts 里注册的 `/api` 前缀对应。 */
const API_BASE = '/api';

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  /** 查询参数；`undefined` / `null` / 空串的项会被跳过。 */
  query?: Record<string, string | number | boolean | null | undefined>;
  /** 请求体；会被 JSON 序列化。 */
  body?: unknown;
  /*
   * 显式带上 `| undefined`：`exactOptionalPropertyTypes` 下，`signal?: AbortSignal`
   * 表示"可以没有这个键，但键存在时不能是 undefined"。而调用方手上往往就是
   * 一个 `AbortSignal | undefined`（Query 传来的），于是每个调用点都得写
   * `...(signal === undefined ? {} : { signal })`。在**声明处**放宽一次，
   * 换来所有调用点的直白写法。
   */
  signal?: AbortSignal | undefined;
}

export interface ApiResult<T> {
  data: T;
  /** 分页元信息；非分页接口为 null。 */
  meta: PageMeta | null;
}

function buildUrl(path: string, query: RequestOptions['query']): string {
  const url = `${API_BASE}${path}`;
  if (query === undefined) {
    return url;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') {
      continue;
    }
    params.append(key, String(value));
  }
  const serialized = params.toString();
  return serialized === '' ? url : `${url}?${serialized}`;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const { method = 'GET', query, body, signal } = options;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      // 同源请求要带上 cookie（桥接会话）；跨源模块改走 Authorization 头。
      credentials: 'same-origin',
      headers:
        body === undefined
          ? { Accept: 'application/json' }
          : { Accept: 'application/json', 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal === undefined ? {} : { signal }),
    });
  } catch (error) {
    // AbortError 是调用方主动取消（如切换页签），不是故障，原样抛给 Query 处理。
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiNetworkError('请求未能到达服务端', error);
  }

  const payload = await readJson(response);

  if (!looksLikeEnvelope(payload)) {
    // 典型场景：代理配置写错，把 404 页面当接口返回了 HTML；
    // 或后端返回了非信封的 JSON。必须报出来，不能当成成功。
    throw new ApiNetworkError(
      `响应不是标准信封（HTTP ${String(response.status)}）`,
      payload,
    );
  }

  if (payload.success === false) {
    throw new ApiRequestError(response.status, payload.error);
  }

  // 只有这一处需要断言：信封本身校验不了 `data` 的具体形状，
  // 那是各接口自己的 zod 契约在做的事（服务端已按契约序列化）。
  return { data: payload.data as T, meta: payload.meta ?? null };
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === '') {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (error) {
    throw new ApiNetworkError(`响应不是合法 JSON（HTTP ${String(response.status)}）`, error);
  }
}

/** 只要 data、不要 meta 的便捷包装，用于绝大多数非分页接口。 */
export async function requestData<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { data } = await request<T>(path, options);
  return data;
}
