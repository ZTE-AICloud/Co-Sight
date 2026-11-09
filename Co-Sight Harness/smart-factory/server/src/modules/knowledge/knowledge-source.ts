/**
 * 知识服务的运行参数来源：**框架「设置 → 知识库路由设置」优先，环境变量兜底**。
 *
 * 框架模块面 `GET /api/framework/v1/rag-knowledge/active` 给两样东西：
 *
 * - `routeUrl`：用户点开的知识库网页地址。本模块只取它的 **origin** 当服务根地址——
 *   代理还要自己拼 `/api/co-knowledge/v1/agent/workflows`，所以不能带路径 / hash
 *   （出厂默认是 `http://rag-studio.example.com/#/login?redirect=/kb`）。
 * - `apiKey`：**生效值**，路由自己的 Key 优先，没配时是框架服务端的默认。所以拿到什么用什么，
 *   不需要再判断框架那一层用了哪个环境变量。
 *
 * 回落的三种情形都按「框架没给」处理，不报错：框架没启动、模块令牌缺失、框架里没有生效路由
 * （`data: null`）。知识检索是可选能力，框架的一次故障不该把它变成硬失败。
 *
 * ## 与产物技能共用同一套来源
 *
 * 产物里的 `rag-knowledge-search` 技能同样优先读取框架「知识库路由设置」的生效路由
 * （`routeUrl` + `apiKey`，经 `{COSIGHT_HOME}/.module-token` 访问
 * `/api/framework/v1/rag-knowledge/active`），框架不可用时才回落到
 * `CO_KNOWLEDGE_BASE_URL` / `CO_KNOWLEDGE_API_KEY`，调用 `POST /api/co-knowledge/v1/agent/query`。
 * 本文件只服务列表代理；两处取的是同一枚 Agent API Key。
 */

import { config } from '../../config/index.js';
import { fetchActiveRagKnowledge, type FrameworkRagKnowledge } from '../../shared/framework/client.js';

export interface KnowledgeSource {
  /** 知识服务根地址（`scheme://host[:port]`），不含路径；空串 = 没配 */
  baseUrl: string;
  /** 知识服务 Agent API Key（`ragk_...`）；空串 = 没配 */
  apiKey: string;
}

/**
 * 网页地址 → 服务根地址。解析失败或不是 http(s) 时返回 `null`（交给环境变量兜底）。
 *
 * `origin` 天然丢掉 path / query / hash，也不会带账户密码（框架写入时已禁止）。
 */
export function baseUrlFromRouteUrl(routeUrl: string): string | null {
  let url: URL;
  try {
    url = new URL(routeUrl);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  return url.origin;
}

/** 空串与空白都按「没配」处理：`KEY=` 这种写法不能变成一个能用的空密钥。 */
function nonEmpty(value: string | null | undefined): string | null {
  const text = value?.trim() ?? '';
  return text === '' ? null : text;
}

/**
 * 解析本次请求要用的基址与 Key。每次现取，保证设置里的改动立刻生效。
 *
 * 两个字段各自回落：框架有生效路由但没给 Key（两层都没有）时，基址仍用框架的、Key 用 env。
 */
export async function resolveKnowledgeSource(): Promise<KnowledgeSource> {
  let active: FrameworkRagKnowledge | null = null;
  try {
    active = await fetchActiveRagKnowledge();
  } catch {
    // 框架不可达 / 令牌不可用 / 旧版本没有这个端点：静默回落环境变量。
  }

  const frameworkBaseUrl = active === null ? null : baseUrlFromRouteUrl(active.routeUrl);

  return {
    baseUrl: frameworkBaseUrl ?? nonEmpty(config.coKnowledgeBaseUrl) ?? '',
    apiKey: nonEmpty(active?.apiKey) ?? nonEmpty(config.coKnowledgeApiKey) ?? '',
  };
}
