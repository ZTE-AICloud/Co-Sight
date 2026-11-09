/**
 * 配置面板（模型设置 / Agent 代理配置）用例共用的打桩工具。
 *
 * 比共享的 `stubFetch` / `stubFetchSequence` 多两件事：
 *
 * 1. **按方法分发**：一个面板既有列表 GET，也有增删改的写请求。用固定顺序打桩
 *    就得依赖"谁先发"，而 React Query 的失效重取让这个顺序随实现变化；
 * 2. **记录请求体**：这两个面板最要紧的断言是"序列化之后到底发出去了什么"——
 *    密钥留空是 `null` 还是空串、数值是 number 还是 string、编辑时某个键有没有
 *    出现在请求体里，**在界面上都看不出来**，只有把请求体解出来才知道。
 *
 * 请求体断言一律走解 JSON（`body()`），不比对原始字符串：字符串比对会把
 * "键的顺序"也钉进去，那样改一个字段的书写顺序就会红，且红的原因与被测行为无关。
 */

import { vi } from 'vitest';

import { envelope, jsonResponse, type FakeResponse } from './render';

/** 记录到的一次请求。`body` 保留原始字符串，解 JSON 由 `body()` 负责。 */
export interface FetchCall {
  url: string;
  method: string;
  body: string | null;
}

export interface ConfigApiStubOptions {
  /** 列表 GET 的响应；要测加载失败就传一个错误信封。 */
  list: FakeResponse;
  /**
   * `/api/health` 的响应。
   *
   * 单独一项而不是让它也吃 `list`：健康检查返回的是**对象**信封，而列表是数组，
   * 用列表的响应去答健康检查会让 `health.data.cosightHome` 静默变成 undefined，
   * 于是"令牌文件路径"那条断言永远只能测到兜底文案。默认给一份可用的数据目录。
   */
  health?: FakeResponse;
  /**
   * `/api/rag-knowledge/defaults` 的响应。
   *
   * 与 `health` 同理单独一项：它返回的也是**对象**信封（`{ hasDefaultApiKey }`），
   * 拿列表的数组信封去答它会让 `hasDefaultApiKey` 静默变成 undefined，
   * 于是"留空会回落默认密钥"那条提示语的用例永远测不到。
   */
  defaults?: FakeResponse;
  /** 写请求的响应；不给则返回一个成功信封（内容不重要，调用方只看请求体）。 */
  write?: (call: { method: string; url: string }) => FakeResponse;
}

export interface ConfigApiStub {
  /** 按发生顺序返回记录到的请求。 */
  calls: () => FetchCall[];
  /** 解出某一次写请求的 JSON 请求体；这个请求没发生过就直接失败。 */
  body: (method: string, url: string, index?: number) => Record<string, unknown>;
  /** 某个请求有没有发生过（"点取消不该有 DELETE"这类断言用它）。 */
  has: (method: string, url: string) => boolean;
}

/** 健康检查的默认响应：一个可用的数据根目录，让令牌路径断言有真实内容可测。 */
const DEFAULT_HEALTH = jsonResponse(
  envelope({
    status: 'ok',
    version: '0.1.0',
    uptimeSeconds: 1,
    cosightHome: '/tmp/cosight-home',
    database: '/tmp/cosight-home/test.sqlite',
  }),
);

/** 没有预置默认密钥——绝大多数用例关心的就是这一种。 */
const DEFAULT_DEFAULTS = jsonResponse(envelope({ hasDefaultApiKey: false }));

/** 打桩 `globalThis.fetch`。用法与共享的 `stubFetch` 相同，返回的对象多两个查询方法。 */
export function stubConfigApi(options: ConfigApiStubOptions): ConfigApiStub {
  const calls: FetchCall[] = [];

  vi.stubGlobal(
    'fetch',
    vi.fn((input: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const url = String(input);
      calls.push({
        url,
        method,
        body: typeof init?.body === 'string' ? init.body : null,
      });

      if (method === 'GET') {
        if (url.endsWith('/api/health')) {
          return Promise.resolve(options.health ?? DEFAULT_HEALTH);
        }
        if (url.endsWith('/api/rag-knowledge/defaults')) {
          return Promise.resolve(options.defaults ?? DEFAULT_DEFAULTS);
        }
        return Promise.resolve(options.list);
      }
      return Promise.resolve(
        options.write?.({ method, url: String(input) }) ??
          // 写请求的响应内容不影响这些用例：断言的是请求体与请求次数。
          jsonResponse({ success: true, data: null, meta: null }),
      );
    }),
  );

  function matching(method: string, url: string): FetchCall[] {
    return calls.filter((call) => call.method === method && call.url === url);
  }

  return {
    calls: () => [...calls],
    has: (method, url) => matching(method, url).length > 0,
    body: (method, url, index = 0) => {
      const target = matching(method, url)[index];
      if (target === undefined || target.body === null) {
        throw new Error(`用例期待的 ${method} ${url} 没有发生（第 ${String(index)} 次）`);
      }
      return JSON.parse(target.body) as Record<string, unknown>;
    },
  };
}
