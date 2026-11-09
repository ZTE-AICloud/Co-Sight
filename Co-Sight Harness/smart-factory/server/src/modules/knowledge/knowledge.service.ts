import { config } from '../../config/index.js';
import { BadGatewayError } from '../../shared/errors.js';
import { resolveKnowledgeSource } from './knowledge-source.js';

/**
 * 知识检索（RAG Studio 工作流）列表代理。
 *
 * 为什么代理而不是前端直连：`/workflows` 没有 CORS 预检（OPTIONS 直接 404），
 * 且原生 REST 走本地会话 / 网关鉴权；Key 只能留在服务端。
 *
 * 走 **Agent API**（不是原生 `/workflows`）：
 *
 *   GET /api/co-knowledge/v1/agent/workflows?page=1&size=500&publishType=1
 *   X-API-Key: ragk_...
 *   → { "items": [ { "workFlowId": "RAG_Workflow_780f", "name": "test1",
 *                    "description": "", "publishType": 1, ... } ],
 *       "total": 3, "page": 1, "pageSize": 500 }
 *
 * 两条上游路径的差别（2026-10-28 实测）：
 * - `/agent/workflows`：Agent Key 可用，**`publishType=1` 生效**（返回 3 条已发布）；
 * - `/workflows`：只认本地会话 cookie，且 `publishType=1` 被忽略（8 条里 5 条草稿）。
 * 所以固定走前者；按字段再筛一遍仍是必须的防御（换部署 / 上游回退时不能把草稿漏出去）。
 *
 * 字段名是 `workFlowId`（大写 F），对外统一成 `id`。
 *
 * 基址与 Key 的来源见 `knowledge-source.ts`：**框架「设置 → 知识库路由设置」优先**
 * （`/rag-knowledge/active` 的 `routeUrl` origin 与生效的 `apiKey`），环境变量兜底。
 */

const WORKFLOWS_PATH = '/api/co-knowledge/v1/agent/workflows';
/** 一次全量拉取；上游的 keyword 参数不认，搜索在前端做。 */
const LIST_QUERY = 'page=1&size=500&publishType=1';
/** 与注入器同一把尺子：workflow_id 会被写进 Python 字面量。 */
const WORKFLOW_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * 上游失败统一走 502，message 里带可动手的原因（前端没登记这个 key 时会原样显示）。
 * 刻意不登记 `error.bad_gateway.knowledge`：登记的通用文案会把「该改哪个 env」盖掉。
 */
const UPSTREAM_KEY = 'error.bad_gateway.knowledge';

export interface KnowledgeWorkflow {
  /** `RAG_Workflow_xxx`，拼进 harness-create 的 `--knowledge-workflow-id` */
  id: string;
  name: string;
  description: string;
}

export interface KnowledgeWorkflowList {
  items: KnowledgeWorkflow[];
  /** 上游报告的**过滤前**总数；当前部署 ≤ 500，一页拿得下。 */
  total: number;
}

/** 上游条目里本模块读的字段，其余忽略。 */
interface RawWorkflow {
  workFlowId?: unknown;
  name?: unknown;
  description?: unknown;
  publishType?: unknown;
}

interface RawList {
  items?: unknown;
  total?: unknown;
}

function upstream(message: string): BadGatewayError {
  return new BadGatewayError(message, UPSTREAM_KEY);
}

/** baseUrl 只到根（config 已去掉尾斜杠），路径与查询在这里拼死。 */
export function buildWorkflowsUrl(baseUrl: string): string {
  return `${baseUrl}${WORKFLOWS_PATH}?${LIST_QUERY}`;
}

/**
 * 认证头（纯函数，便于单测）。
 *
 * Agent API 两种头都收（`X-API-Key` / `Authorization: Bearer`），这里固定用前者：
 * 与部署方给的 curl 一致，也避免和原生 REST 的 `Authorization` 混在一起排查。
 */
export function buildAuthHeaders(apiKey: string): Record<string, string> {
  if (apiKey === '') {
    throw upstream(
      '未配置知识库 Agent API Key：在框架「设置 → 知识库路由设置」里填 API Key，或设置 CO_KNOWLEDGE_API_KEY（形如 ragk_...）',
    );
  }
  return { 'x-api-key': apiKey };
}

function describeNetworkError(error: unknown, timeoutMs: number): string {
  const name = (error as { name?: unknown } | null)?.name;
  if (name === 'TimeoutError' || name === 'AbortError') return `超时（>${timeoutMs}ms）`;
  return error instanceof Error ? error.message : String(error);
}

/**
 * 拉取已发布工作流。
 *
 * 失败一律 502 + 人话（前端直接显示 message）：未配置、401/403、非 2xx、非 JSON、
 * 结构不符都走同一种出口，不降级成空列表 —— 空列表会让用户以为「没有知识库」。
 */
export async function listWorkflows(): Promise<KnowledgeWorkflowList> {
  const { baseUrl, apiKey } = await resolveKnowledgeSource();

  if (baseUrl === '') {
    throw upstream(
      '未配置知识库服务地址：在框架「设置 → 知识库路由设置」启用一条路由，或设置 CO_KNOWLEDGE_BASE_URL（只到根地址，不带路径）',
    );
  }

  const url = buildWorkflowsUrl(baseUrl);
  const headers = { accept: 'application/json', ...buildAuthHeaders(apiKey) };

  let response: Response;
  try {
    response = await fetch(url, {
      headers,
      signal: AbortSignal.timeout(config.coKnowledgeListTimeoutMs),
    });
  } catch (error) {
    throw upstream(
      `连不上知识库服务（${baseUrl}）：${describeNetworkError(error, config.coKnowledgeListTimeoutMs)}`,
    );
  }

  if (response.status === 401 || response.status === 403) {
    throw upstream(
      `知识库拒绝了请求（HTTP ${response.status}）：检查当前生效的 Agent Key（框架知识库路由设置或 CO_KNOWLEDGE_API_KEY，形如 ragk_...）`,
    );
  }
  if (!response.ok) {
    throw upstream(`知识库返回 HTTP ${response.status}（${url}）`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw upstream(
      `知识库工作流列表不是合法 JSON：${describeNetworkError(error, config.coKnowledgeListTimeoutMs)}`,
    );
  }

  return normalizeWorkflowList(payload);
}

/**
 * 上游响应 → 对外列表。**导出只为测试**：三种失败（缺 items / 结构不对 / 空）和
 * 草稿过滤都收敛在这里，路由层与网络层不再各判一遍。
 */
export function normalizeWorkflowList(payload: unknown): KnowledgeWorkflowList {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw upstream('知识库工作流列表响应不是对象');
  }

  const raw = payload as RawList;
  if (!Array.isArray(raw.items)) {
    throw upstream('知识库工作流列表响应缺少 items');
  }

  const items = raw.items
    .map(toWorkflow)
    .filter((item): item is KnowledgeWorkflow => item !== null);

  return {
    items,
    total: typeof raw.total === 'number' ? raw.total : raw.items.length,
  };
}

/** 单条：只认已发布 + 合法 id；名字缺失退回 id，描述缺失给空串。 */
function toWorkflow(value: unknown): KnowledgeWorkflow | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;

  const raw = value as RawWorkflow;
  // 当前 /agent/workflows 会按 publishType 过滤；这里再筛一遍是防换部署 / 上游回退
  if (raw.publishType !== 1) return null;

  const id = typeof raw.workFlowId === 'string' ? raw.workFlowId.trim() : '';
  if (!WORKFLOW_ID_RE.test(id)) return null;

  const name = typeof raw.name === 'string' && raw.name.trim() !== '' ? raw.name.trim() : id;
  const description = typeof raw.description === 'string' ? raw.description.trim() : '';

  return { id, name, description };
}

export const knowledgeService = { listWorkflows };
