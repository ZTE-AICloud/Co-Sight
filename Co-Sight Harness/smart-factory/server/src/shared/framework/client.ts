import { config } from '../../config/index.js';
import { BadGatewayError, NotFoundError } from '../errors.js';
import { moduleTokenPath, readModuleToken } from './module-token.js';

/**
 * 框架模块面只读客户端。
 *
 * 令牌每个请求现读 `{cosightHome}/.module-token`：改文件立即生效，且不进环境变量、
 * 不进日志、不进错误消息。所有上游异常统一映射成 502 BAD_GATEWAY，404 映射 NotFoundError。
 */

const API_PREFIX = '/api/framework/v1';
const REQUEST_TIMEOUT_MS = 3000;
const WORKSPACE_CACHE_TTL_MS = 60_000;

export interface FrameworkWorkspace {
  id: string;
  name: string;
  directory: string | null;
  /** 该工作区的默认模型；null = 沿用框架全局当前模型 */
  defaultModelId: string | null;
  defaultAgentId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface FrameworkWorkspaceList {
  items: FrameworkWorkspace[];
  activeId: string | null;
}

/**
 * 框架「设置 → 知识库路由设置」里生效的那一条（模块面 `/rag-knowledge/active`）。
 *
 * 只声明本模块用到的字段（响应里还有 `name` / `username` / `password` / `hasApiKey` 等）。
 *
 * `apiKey` 是**生效值**：路由自己的 Key 优先，没配时是框架服务端的默认
 * （`COSIGHT_KNOWLEDGE_API_KEY` / `CO_KNOWLEDGE_API_KEY`）。所以 `hasApiKey === false`
 * 不代表拿不到 Key，只表示这条路由没自己配。
 */
export interface FrameworkRagKnowledge {
  /** 浏览器打开的知识库地址；本模块只取它的 origin 当服务根地址 */
  routeUrl: string;
  apiKey: string | null;
}

/** 工作区详情缓存：路径解析只读 directory，60 秒内的滞后可接受。 */
const workspaceCache = new Map<string, { value: FrameworkWorkspace; expiresAt: number }>();

/**
 * 网络异常 → 人话。`timeoutMs` 由调用方给，保证文案里的秒数与该请求实际使用的超时一致。
 *
 * 不直接回传 error.message：底层异常消息可能带上请求头等敏感上下文。
 */
export function describeFrameworkNetworkError(error: unknown, timeoutMs: number): string {
  if (!(error instanceof Error)) return '未知网络错误';
  if (error.name === 'TimeoutError') return `请求超时（${timeoutMs / 1000} 秒）`;
  const cause = (error as { cause?: { code?: unknown } }).cause;
  if (typeof cause?.code === 'string') {
    if (cause.code === 'ECONNREFUSED') {
      return 'ECONNREFUSED：检查框架进程是否已启动，或 FRAMEWORK_BASE_URL 是否正确';
    }
    return cause.code;
  }
  return `网络异常（${error.name}）`;
}

async function upstreamMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: unknown } | null };
    const message = body.error?.message;
    if (typeof message === 'string' && message !== '') return message;
  } catch {
    // 非 JSON 响应时退回状态文本
  }
  return response.statusText;
}

async function getData<T>(path: string, notFoundWhat: string): Promise<T> {
  const token = readModuleToken();

  let response: Response;
  try {
    response = await fetch(`${config.frameworkBaseUrl}${API_PREFIX}${path}`, {
      method: 'GET',
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    throw new BadGatewayError(
      `框架请求失败（${path}）：${describeFrameworkNetworkError(error, REQUEST_TIMEOUT_MS)}`,
      'error.bad_gateway.framework',
      { path },
    );
  }

  if (response.status === 401) {
    throw new BadGatewayError(
      `框架拒绝了模块令牌（401）：检查 ${moduleTokenPath()} 是否与框架一致`,
      'error.bad_gateway.module_token',
    );
  }
  if (response.status === 403) {
    throw new BadGatewayError('框架拒绝了本服务的请求（403）：模块面只接受本机回环地址，且不接受 Origin 头');
  }
  if (response.status === 404) {
    throw new NotFoundError(notFoundWhat);
  }
  if (!response.ok) {
    throw new BadGatewayError(
      `框架返回 HTTP ${response.status}（${path}）：${await upstreamMessage(response)}`,
      'error.bad_gateway.framework',
      { path, status: response.status },
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (error instanceof Error && error.name === 'TimeoutError') {
      throw new BadGatewayError(`框架响应超时（${REQUEST_TIMEOUT_MS / 1000} 秒，${path}）`);
    }
    throw new BadGatewayError(`框架返回了非 JSON 响应（${path}）`);
  }

  const envelope = body as { success?: unknown; data?: unknown; error?: { message?: unknown } | null } | null;
  if (envelope === null || envelope.success !== true) {
    const reason = typeof envelope?.error?.message === 'string' ? envelope.error.message : '未知错误';
    throw new BadGatewayError(`框架响应失败（${path}）：${reason}`);
  }
  return envelope.data as T;
}

/** 工作区列表；返回项含 directory，代理端点由调用方投影后再下发。 */
export async function fetchWorkspaces(): Promise<FrameworkWorkspaceList> {
  try {
    return await getData<FrameworkWorkspaceList>('/workspaces', '框架工作区列表');
  } catch (error) {
    // 列表端点的 404 更可能是框架路由缺失或版本不匹配：按上游不可用报 502，不落成 NOT_FOUND
    if (error instanceof NotFoundError) throw new BadGatewayError('框架工作区列表不可用：上游返回 404');
    throw error;
  }
}

/** 工作区详情；按 id 缓存 60 秒，用于路径解析。 */
export async function fetchWorkspace(id: string): Promise<FrameworkWorkspace> {
  const cached = workspaceCache.get(id);
  if (cached !== undefined && cached.expiresAt > Date.now()) {
    return cached.value;
  }

  const workspace = await getData<FrameworkWorkspace>(`/workspaces/${encodeURIComponent(id)}`, `框架工作区 ${id}`);
  workspaceCache.set(id, { value: workspace, expiresAt: Date.now() + WORKSPACE_CACHE_TTL_MS });
  return workspace;
}

/**
 * 当前生效的知识库路由；框架里一条都没配时返回 `null`（HTTP 仍是 200，不是 404）。
 *
 * **不做缓存**：用户在设置里改了地址或 Key 应当立刻生效，而列表代理本身就是按需调用。
 * 框架不可达时由调用方决定怎么兜底（见 `modules/knowledge/knowledge-source.ts`）。
 */
export async function fetchActiveRagKnowledge(): Promise<FrameworkRagKnowledge | null> {
  return getData<FrameworkRagKnowledge | null>('/rag-knowledge/active', '框架知识库路由');
}
