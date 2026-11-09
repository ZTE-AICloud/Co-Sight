// SPDX-License-Identifier: Apache-2.0
/**
 * @file bare-json.ts
 * @description smart-factory 的**裸 JSON** 请求封装（没有 `{ success, data, error }` 信封）。
 *
 * 与 `harness-api.ts` 里那个私有版本同口径，但多带一个 `status`：文件预览要按
 * `404` / `413` / `415` 给出不同提示，只有错误文案是不够的。
 */

/** 非 2xx 响应；`status` 供调用方分流 404 / 413 / 415。 */
export class BareJsonError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BareJsonError";
    this.status = status;
  }
}

/** 从错误响应体里取一句人读的 message；取不到就退回 HTTP 状态行。 */
async function errorMessageOf(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as {
      message?: unknown;
      error?: { message?: unknown };
    };
    const message =
      typeof body.message === "string"
        ? body.message
        : typeof body.error?.message === "string"
          ? body.error.message
          : null;
    return message ?? fallback;
  } catch {
    return fallback;
  }
}

export async function requestBareJson<T>(
  url: string,
  timeoutMs = 15000,
  init: RequestInit = {}
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      ...init,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new BareJsonError(response.status, await errorMessageOf(response));
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}
