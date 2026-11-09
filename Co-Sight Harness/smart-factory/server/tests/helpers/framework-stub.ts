import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

/** 与框架模块面同形的测试替身：校验 Bearer，只提供 GET 读接口。 */

export interface StubWorkspace {
  id: string;
  name: string;
  directory: string | null;
  /** 省略按 null 处理（未设置工作区默认模型） */
  defaultModelId?: string | null;
  defaultAgentId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface StubModel {
  id: string;
  provider: string;
  protocol: 'anthropic' | 'openai';
  label: string;
  modelName: string;
  baseUrl: string | null;
  hasApiKey: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  apiKey: string | null;
  temperature: number;
  topP: number;
  maxOutputTokens: number | null;
  contextWindow: number | null;
  timeoutSeconds: number;
}

export interface FrameworkStub {
  url: string;
  /** 每个请求的人为延迟，用于超时场景；可随时改写。 */
  delayMs: number;
  /** 响应头发出后延迟响应体，用于响应体读取阶段的超时场景。 */
  bodyDelayMs: number;
  /** 当前生效的模型 id，可在用例中切换。 */
  activeModelId: string | null;
  /** 当前生效的工作区 id，可在用例中切换（null = 框架没有生效工作区）。 */
  activeWorkspaceId: string | null;
  /** 内部模型数组：用例可 splice 清空 / 恢复，模拟框架没有任何模型。 */
  readonly models: StubModel[];
  /** `/models` 的响应状态，用于上游 404 / 5xx 场景；可随时改写。 */
  modelsStatus: number;
  /** `/workspaces` 的响应状态，用于上游 404 / 5xx 场景；可随时改写。 */
  workspacesStatus: number;
  requests: Array<{ method: string; path: string }>;
  close(): Promise<void>;
}

const PREFIX = '/api/framework/v1';

function sendJson(res: import('node:http').ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function ok(data: unknown): unknown {
  return { success: true, data, error: null, meta: null };
}

function fail(code: string, message: string): unknown {
  return { success: false, data: null, error: { code, message }, meta: null };
}

/** 列表投影：与框架模块面一致，去掉明文密钥与推理参数。 */
function toSummary({ apiKey: _apiKey, temperature: _temperature, topP: _topP, maxOutputTokens: _maxOutputTokens, contextWindow: _contextWindow, timeoutSeconds: _timeoutSeconds, ...summary }: StubModel): unknown {
  return summary;
}

export async function startFrameworkStub(options: {
  token: string;
  workspaces?: StubWorkspace[];
  models?: StubModel[];
  activeWorkspaceId?: string | null;
  activeModelId?: string | null;
}): Promise<FrameworkStub> {
  const workspaces = options.workspaces ?? [];
  const models = options.models ?? [];
  const requests: Array<{ method: string; path: string }> = [];
  const state = {
    delayMs: 0,
    bodyDelayMs: 0,
    activeModelId: options.activeModelId ?? null,
    activeWorkspaceId: options.activeWorkspaceId ?? null,
    modelsStatus: 200,
    workspacesStatus: 200,
  };

  const server: Server = createServer((req, res) => {
    void (async () => {
      const path = new URL(req.url ?? '/', 'http://127.0.0.1').pathname;
      requests.push({ method: req.method ?? '', path });

      if (state.delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, state.delayMs));
      }

      if (req.method !== 'GET') {
        sendJson(res, 405, fail('METHOD_NOT_ALLOWED', '只支持 GET'));
        return;
      }
      if (req.headers.authorization !== `Bearer ${options.token}`) {
        sendJson(res, 401, fail('UNAUTHORIZED', '模块令牌无效'));
        return;
      }

      if (path === `${PREFIX}/workspaces`) {
        if (state.workspacesStatus !== 200) {
          sendJson(res, state.workspacesStatus, fail('NOT_FOUND', '框架工作区接口不可用'));
          return;
        }
        const payload = ok({ items: workspaces, activeId: state.activeWorkspaceId });
        if (state.bodyDelayMs > 0) {
          res.writeHead(200, { 'content-type': 'application/json' });
          res.flushHeaders();
          await new Promise((resolve) => setTimeout(resolve, state.bodyDelayMs));
          res.end(JSON.stringify(payload));
          return;
        }
        sendJson(res, 200, payload);
        return;
      }
      if (path === `${PREFIX}/models`) {
        if (state.modelsStatus !== 200) {
          sendJson(res, state.modelsStatus, fail('NOT_FOUND', '框架模型接口不可用'));
          return;
        }
        const payload = ok({ items: models.map(toSummary), activeId: state.activeModelId });
        if (state.bodyDelayMs > 0) {
          res.writeHead(200, { 'content-type': 'application/json' });
          res.flushHeaders();
          await new Promise((resolve) => setTimeout(resolve, state.bodyDelayMs));
          res.end(JSON.stringify(payload));
          return;
        }
        sendJson(res, 200, payload);
        return;
      }

      const workspaceMatch = path.match(/^\/api\/framework\/v1\/workspaces\/([^/]+)$/);
      if (workspaceMatch !== null) {
        const id = decodeURIComponent(workspaceMatch[1]);
        const workspace = workspaces.find((item) => item.id === id);
        sendJson(res, workspace === undefined ? 404 : 200, workspace === undefined ? fail('NOT_FOUND', '工作区不存在') : ok(workspace));
        return;
      }

      const modelMatch = path.match(/^\/api\/framework\/v1\/models\/([^/]+)$/);
      if (modelMatch !== null) {
        const id = decodeURIComponent(modelMatch[1]);
        const model = models.find((item) => item.id === id);
        sendJson(res, model === undefined ? 404 : 200, model === undefined ? fail('NOT_FOUND', '模型配置不存在') : ok(model));
        return;
      }

      sendJson(res, 404, fail('NOT_FOUND', '接口不存在'));
    })();
  });

  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    get delayMs() {
      return state.delayMs;
    },
    set delayMs(value: number) {
      state.delayMs = value;
    },
    get bodyDelayMs() {
      return state.bodyDelayMs;
    },
    set bodyDelayMs(value: number) {
      state.bodyDelayMs = value;
    },
    get activeModelId() {
      return state.activeModelId;
    },
    set activeModelId(value: string | null) {
      state.activeModelId = value;
    },
    get activeWorkspaceId() {
      return state.activeWorkspaceId;
    },
    set activeWorkspaceId(value: string | null) {
      state.activeWorkspaceId = value;
    },
    get models() {
      return models;
    },
    get modelsStatus() {
      return state.modelsStatus;
    },
    set modelsStatus(value: number) {
      state.modelsStatus = value;
    },
    get workspacesStatus() {
      return state.workspacesStatus;
    },
    set workspacesStatus(value: number) {
      state.workspacesStatus = value;
    },
    requests,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
