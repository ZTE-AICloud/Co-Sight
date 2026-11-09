import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

export const API = '/api/smart-factory/v1';

const TERMINAL = ['succeeded', 'failed', 'aborted'];

export interface Json {
  status: number;
  body: any;
}

export interface TestApi {
  /** 底层 HTTP 服务：需要挂 WS 网关等额外配线时用 */
  server: Server;
  base: string;
  get(path: string): Promise<Json>;
  post(path: string, payload?: unknown): Promise<Json>;
  /** 轮询 run 到终态，超时抛错（5s 足够，FakeAdapter 很快） */
  waitTerminal(runId: string): Promise<any>;
  close(): Promise<void>;
}

/** 起一个真实 HTTP 服务，给出发请求的入口；收尾由调用方在 after 里 close()。 */
export async function startTestApi(): Promise<TestApi> {
  // 动态引入：调用方要先完成 prepareTestEnv 与 process.env 设置
  const { createApp } = await import('../../src/app.js');
  const server = createServer(createApp());
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

  async function call(method: 'GET' | 'POST', path: string, payload?: unknown): Promise<Json> {
    const response = await fetch(`${base}${path}`, {
      method,
      headers: { 'content-type': 'application/json' },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }

  return {
    server,
    base,
    get: (path) => call('GET', path),
    post: (path, payload) => call('POST', path, payload),
    async waitTerminal(runId: string): Promise<any> {
      for (let i = 0; i < 100; i += 1) {
        const { body } = await call('GET', `${API}/runs/detail?runId=${runId}`);
        if (TERMINAL.includes(body.status)) return body;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      throw new Error(`run ${runId} 未在 5s 内落终态`);
    },
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
