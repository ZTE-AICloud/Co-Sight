/**
 * 统一 HTTP 客户端。
 *
 * 开发态 VITE_API_BASE_URL 缺省为 '/api'，由 vite proxy 转发到后端；
 * 生产态由反向代理承担同一职责。前端代码只写相对路径。
 *
 * base URL 做成工厂是因为前端会同时面对**多个**后端：本仓的 server（/api），
 * 以及模型管理（shared/api/models.ts，仍打 mock）。它们的错误形状与请求方式一致，
 * 差的只是 base URL。
 */

import { currentLocale, msg } from '../../i18n/useI18n';
import { apiErrorText } from '../../i18n/translate';

/** 本仓 server 的根。智能体管理（shared/api/agents.ts）也挂在这棵树下。 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

export interface ApiErrorBody {
  error: string;
  message: string;
  /** 服务端给的 i18n 键（运行期字符串，可能不在词表里） */
  messageKey?: string;
  params?: Record<string, string | number> | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** 保留服务端的键与参数：调用方要重新翻译（或切语言后重译）时用得上 */
  readonly messageKey: string | null;
  readonly params: Record<string, string | number> | undefined;

  constructor(
    status: number,
    code: string,
    message: string,
    messageKey: string | null = null,
    params?: Record<string, string | number>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.messageKey = messageKey;
    this.params = params;
  }
}

export interface ApiClient {
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown) => Promise<T>;
  /**
   * POST 一份 `FormData`（multipart）。
   *
   * 单独一个方法而不是让 `post` 识别 FormData：`post` 会把 body `JSON.stringify`，
   * 且默认带 `Content-Type: application/json`；multipart 的 boundary 必须由浏览器自己生成，
   * 手写 Content-Type 反而会让后端解析失败。这里只发请求头、不碰 body。
   */
  postForm: <T>(path: string, body: FormData) => Promise<T>;
}

/**
 * 造一个绑定了 base URL 的客户端。path 一律以 `/` 开头，直接拼在 baseUrl 之后。
 *
 * 只提供 get / post：接口契约（server/docs/04-api/4.02-通用规范.md §4）只许这两个方法，
 * 删除也是 POST（旧资源走 `<资源>/delete` + 请求体带 id，agents 走 `<资源>/{id}/delete`
 * 且无请求体），所以不提供 delete/put/patch —— 提供了迟早有人用。
 */
export function createApiClient(baseUrl: string): ApiClient {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${baseUrl}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });

    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
      const params = body?.params ?? undefined;
      // 服务端只给 key；在这里按当前语言翻一次。词表里精确登记过的键用翻译，
      // 只落到分组 default / 根本没登记的（如新增资源类型）用服务端原话：
      // 那种情况服务端给的具体原因（「模型 x 的协议是 openai…」）比「请求格式不正确」有用。
      const text =
        body === null
          ? msg('api.requestFailed', { status: response.status })
          : apiErrorText(currentLocale(), body.messageKey, body.message, params);
      throw new ApiError(
        response.status,
        body?.error ?? 'UNKNOWN',
        text,
        body?.messageKey ?? null,
        params,
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }
    // 响应不是 JSON 时（如被 SPA fallback 吐了 index.html）要给出可读错误，而不是裸的 SyntaxError
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(response.status, 'BAD_RESPONSE', msg('api.badResponse', { path }));
    }
  }

  return {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
    // headers 显式传空对象：`request` 的默认头会被 init.headers 整体替换，
    // 这样浏览器才会自己补 multipart 的 `Content-Type: multipart/form-data; boundary=…`
    postForm: <T>(path: string, body: FormData) =>
      request<T>(path, { method: 'POST', body, headers: {} }),
  };
}

/** 本仓后端的客户端。 */
export const api = createApiClient(API_BASE_URL);
