// SPDX-License-Identifier: Apache-2.0
/**
 * @file harness-api.ts
 * @description 会话相关数据的两处来源:
 *
 * - **智能体**:`GET {smart-factory}/agents` —— REST 走 viewer 同源反代
 *   `/api/smart-factory/v1`，由 viewer 服务端转发到 `127.0.0.1:4100`。
 * - **模型**:走**框架** `GET /api/models` —— 同样走 viewer 同源反代
 *   `/framework-api`，由 viewer 服务端转发到 `127.0.0.1:4300`。
 *
 * 为什么需要适配层:两边的契约字段与组件消费的 `Agent` / `DropdownOption` 不同,
 * 这里把数据**适配成既有形状**,组件侧只需要换数据源。
 *
 * | 用途 | 来源字段 | 适配到 |
 * |---|---|---|
 * | 智能体 | `id/name/icon/description` | `Agent.id/name/icon/description` |
 * | 模型 | `id/label/modelName/isActive` | `DropdownOption.id/name` |
 *
 * 两个服务的响应信封不同:框架是 `{ success, data, error, meta }`,smart-factory 是
 * **裸 JSON**(列表 `{ items, total }`),所以下面有两个请求封装。
 *
 * **模型只能走「浏览器面」`/api/models`,不能走模块面 `/api/framework/v1/models`**:
 * 后者对任何带 `Origin` 头的请求一律 403,还要出示 `$COSIGHT_HOME/.module-token`,
 * 而浏览器两样都过不去(`framework/docs/module-facing-api.md` §4)。
 */

import type { Agent } from "./agent-api";
import type { DropdownOption } from "../components/Dropdown";
import { AGENT_RUNTIME_API_URL as SESSION_API_BASE } from "../config/api-config";

/** viewer 自己的源；SSR/构建期没有 window 时返回空串，退回相对路径。 */
function viewerOrigin(): string {
  if (typeof window === "undefined" || !window.location) return "";
  const origin = window.location.origin;
  return origin && origin !== "null" ? origin : "";
}

/**
 * 框架 REST 的同源反代前缀：`/framework-api/*` → viewer 服务端转发到
 * `http://127.0.0.1:4300/api/*`。浏览器不再跨源，也不再写死回环地址。
 * **目前只用于模型与工作区查询**。
 */
export const HARNESS_API_BASE = `${viewerOrigin()}/framework-api`;

/**
 * OSS 版把智能体的"版本"固定为这个值 —— 界面上不呈现版本概念。
 *
 * 开源版的协议已经不再发送 `versionId`(首帧改为 `agentId`),这个常量只留给
 * `agent-api.ts` 里伪造 `versions` 的旧代码使用;等那处清理掉即可一并删除。
 */
export const DEFAULT_AGENT_VERSION_ID = "default";

/** 框架统一响应封装:`{ success, data, error, meta }`(见 `shared/src/envelope.ts`)。 */
interface Envelope<T> {
  success: boolean;
  data: T | null;
  error: { code?: string; message?: string } | null;
  meta: { total?: number; page?: number; pageSize?: number } | null;
}

// ────────────────────────── smart-factory:智能体 ──────────────────────────

/**
 * smart-factory 的**派生产物状态**（`GET /agents` 的 `status`）。
 *
 * 服务端按 development 目录的过程状态、交付门禁与产物现算，不落库
 * （`server/src/shared/types/index.ts` 的 `AgentProductionStatus`）：
 * - `not_started`：还没开始生成；
 * - `building`：生成中（有活跃 run 或流程未收尾）；
 * - `blocked`：流程暂停；
 * - `failed`：流程失败 / 门禁 FAIL / 产物不完整；
 * - `completed`：流程收尾且门禁 PASS / CONCERNS。
 *
 * 列表里的 `status` 还可能是 `null`：内置智能体没有生产流程；历史行读取失败时也会保持 null。
 */
export type AgentProductionStatus =
  | "not_started"
  | "building"
  | "blocked"
  | "failed"
  | "completed";

/** 智能体来源（`GET /agents` 的 `source`）。内置/自定义只由它判定。 */
export type AgentSource = "user" | "builtin";

/** 来源筛选；`all` 表示不筛。 */
export type AgentSourceFilter = "all" | AgentSource;

/**
 * smart-factory 的 agent 契约(`GET /api/smart-factory/v1/agents` 的列表项)。
 *
 * 只列本模块用得到的字段;服务端以后加字段不影响这里(多出来的忽略)。
 */
export interface HarnessAgent {
  id: string;
  /** 内置智能体不属于任何工作区，为 null。 */
  workspaceId: string | null;
  name: string;
  description: string;
  tags: string[];
  /**
   * 封面图 URL。服务端给的是以 `/api/...` 开头的**相对地址**（相对 smart-factory 的源），
   * 而本页跑在 4830，直接塞进 `<img src>` 会打到 viewer 自己的服务端 → 404。
   * 因此 `fetchAgentPage` / `toAgent` 会先补全成绝对地址，组件拿到的永远是可直接用的 URL。
   */
  icon: string;
  /** 派生的产物状态；`null` = 内置 / 历史行，没有可用的生产状态。 */
  status: AgentProductionStatus | null;
  createdAt: string;
  updatedAt: string;
  /** 智能体根目录（服务端现算的绝对路径）。 */
  dir?: string;
  /**
   * 运行时工作目录（runtime 会话的 cwd，绝对路径）。内置智能体 = `dir`；普通智能体 =
   * development 最新产物目录。产物未生成时为 null/缺省。
   *
   * 这是会话里**相对路径的解析根**：智能体在 runtime 目录里跑，工具/正文写的相对路径
   * 都是相对它。优先于 `dir + /production` 推导（少一次请求，且产物未就绪时口径一致）。
   */
  runtimeDir?: string | null;
  /** `builtin` / `user`；内置/自定义身份只由它判定（不要用 `status === null` 推断）。 */
  source: AgentSource;
  /**
   * 可执行斜杠命令。只有 `GET /agents/{id}` 详情返回；列表项没有这个字段。
   * 服务端按 `name` 去重，`namespace` 只用于展示来源。
   */
  commands?: HarnessAgentCommand[];
  /** 技能清单；同样只有详情返回 */
  skills?: HarnessAgentSkill[];
}

/** 智能体详情里的斜杠命令（`.claude/commands/**\/*.md`）。 */
export interface HarnessAgentCommand {
  name: string;
  namespace: string;
  description: string;
  path: string;
  updatedAt: string;
}

/** 智能体详情里的技能（`.claude/skills/<name>` / 插件技能）。 */
export interface HarnessAgentSkill {
  name: string;
  displayName?: string;
  description: string;
  version?: string;
  path?: string;
  updatedAt?: string;
}

/** 相对图标地址 → 可直接放进 `src` 的绝对地址；emoji / 文本 / 绝对地址原样返回。 */
export function resolveServiceAssetUrl(value: string): string {
  if (!value.startsWith("/")) return value;
  try {
    return new URL(value, SESSION_API_BASE).toString();
  } catch {
    return value;
  }
}

/**
 * 取 agent 的一页。
 *
 * `hasMore` 用响应里的 `total` 判断 —— smart-factory 直接给总数,比按"满页"推断准
 * (服务端会把 pageSize 夹到上限,满页推断会误判)。
 */
export interface AgentPage {
  items: HarnessAgent[];
  /** 服务端按当前过滤条件算出的总条数（不是本页条数）。 */
  total: number;
  hasMore: boolean;
}

/** smart-factory `pageParams` 的上限(`server/src/shared/validate.ts`)。 */
const AGENT_PAGE_SIZE_MAX = 200;
/** 选择器/列表一次取多少。 */
const AGENT_PAGE_SIZE = 60;

/**
 * 选择器在本机内存里最多攒多少位智能体。
 *
 * 只挡"滚到底还没到底"这一种病:滚动加载是逐页追加的,没有这个数,后端异常时
 * 用户能一直往下滚,内存和 DOM 一起涨。正常规模下永远碰不到它。
 */
export const MAX_EXPERTS = 10000;

/** 智能体选择器的查询条件(对齐 smart-factory `GET /agents`)。 */
export interface AgentQuery {
  /** 关键字,匹配 name / id / description;空串表示不筛。 */
  keyword?: string;
  /**
   * 来源筛选（服务端 `?source=user|builtin`）；`all` 表示不筛。
   */
  source?: AgentSourceFilter;
  /** 产物状态筛选（服务端 `?status=`）；选择器固定传 `completed`。 */
  status?: AgentProductionStatus;
  pageSize?: number;
}

/**
 * 取智能体的**一页**,保留 `tags` / `source` / `status` / `icon` 等完整字段。
 *
 * 为什么是"一页"而不是"取完":交给调用方按滚动逐页追加。一次取完在 agent 数
 * 超过一页时会静默截断,滚动加载天然没有这个问题。
 *
 * 过滤条件都交给服务端：`keyword` / `source` / `status`。
 * `status` 是派生值，服务端会先现算再过滤并返回准确的 `total`。
 */
export async function fetchAgentPage(query: AgentQuery = {}, page = 1): Promise<AgentPage> {
  const pageSize = Math.min(query.pageSize ?? AGENT_PAGE_SIZE, AGENT_PAGE_SIZE_MAX);
  const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  if (query.keyword !== undefined && query.keyword !== "") {
    params.set("keyword", query.keyword);
  }
  if (query.source !== undefined && query.source !== "all") {
    params.set("source", query.source);
  }
  if (query.status !== undefined) {
    params.set("status", query.status);
  }
  const data = await requestBareJson<{ items: HarnessAgent[]; total: number }>(
    `${SESSION_API_BASE}/agents?${params.toString()}`
  );
  return {
    // 图标地址在这里就补全：选择器直接把它塞进 <img src>，补全放在组件里会漏掉新调用方。
    items: data.items.map((agent) => ({ ...agent, icon: resolveServiceAssetUrl(agent.icon) })),
    total: data.total,
    hasMore: page * pageSize < data.total,
  };
}

/**
 * 引擎 `/` 菜单里的产品可见条目（smart-factory `GET /engine/commands/list`）。
 *
 * 只保留本模块要展示的字段；服务端已过滤掉 Claude Code 自带命令。
 * `cwd` 可选：不传时只返回用户级（`~/.claude`）与插件条目；自由对话当前按
 * 不传处理，工作区自己的项目级命令不会出现在菜单里（仍可手敲执行）。
 */
export interface EngineSlashCommand {
  name: string;
  description: string;
  argumentHint: string;
  aliases?: string[];
}

interface EngineCommandsResponse {
  engine: string;
  cwd: string;
  items: EngineSlashCommand[];
}

/**
 * 取引擎 `/` 菜单。
 *
 * 服务端探测进程冷启动约 10 秒、缓存 30 秒，因此只在自由对话挂载后后台取一次，
 * 不能在每次输入时调用。客户端超时大于服务端的 15 秒探测超时。
 */
export async function fetchEngineCommands(cwd?: string | null): Promise<EngineSlashCommand[]> {
  const params = new URLSearchParams();
  if (typeof cwd === "string" && cwd.trim() !== "") {
    params.set("cwd", cwd.trim());
  }
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  const data = await requestBareJson<EngineCommandsResponse>(
    `${SESSION_API_BASE}/engine/commands/list${suffix}`,
    20_000
  );
  return data.items;
}

/**
 * 取**单个**智能体(选中后解析、恢复会话时用)。
 *
 * 直接打 `GET /agents/{agentId}`,而不是"全量翻页再 `find`":后者一次选择要串行
 * 拉 ⌈总数/60⌉ 页、把整张表下载一遍,只为拿其中一条。查不到(404 / 网络失败)
 * 返回 `null` —— 与 `fetchAgentDetail` 的既有契约一致,调用方据此提示"没有可用版本"。
 */
export async function fetchServiceAgent(agentId: string): Promise<Agent | null> {
  try {
    const agent = await requestBareJson<HarnessAgent>(
      `${SESSION_API_BASE}/agents/${encodeURIComponent(agentId)}`
    );
    return toAgent(agent);
  } catch {
    return null;
  }
}

/**
 * 智能体产物状态（`GET /agents/{agentId}/production`，契约 4.10）。
 *
 * 只取 `product.path` —— 它是相对 development 目录的路径（如
 * `output/agents/<name>/v3`），与 `agent.dir` 拼起来就是 runtime 会话的 cwd。
 *
 * 内置智能体调这个接口会 409（它们不参与生产流程），这里统一返回 null；
 * 调用方按 `source === "builtin"` 直接使用 `agent.dir`。
 */
export interface AgentProductionView {
  product: {
    name: string;
    version: string;
    /** 相对 development 目录，服务端已把 `\` 归一成 `/` */
    path: string;
    updatedAt: string;
  } | null;
  ready?: boolean;
}

export async function fetchAgentProduction(
  agentId: string
): Promise<AgentProductionView | null> {
  try {
    return await requestBareJson<AgentProductionView>(
      `${SESSION_API_BASE}/agents/${encodeURIComponent(agentId)}/production`
    );
  } catch {
    return null;
  }
}

// ────────────────────────── 框架:模型 ──────────────────────────

/**
 * 框架模型契约(`shared/src/contracts/model.ts`)里本模块用得到的那几项。
 *
 * `isActive` = 当前生效的模型,契约注明**全局至多一个**(数据层在激活新模型时会把
 * 其余置 false),所以按它预选,与模块面那个 `activeId` 指的是同一件事。
 */
interface HarnessModel {
  id: string;
  label: string;
  modelName: string;
  isActive: boolean;
}

// ────────────────────────── 请求封装 ──────────────────────────

/**
 * 框架的**带信封** JSON 请求:HTTP 非 2xx 或 `success: false` 抛出可读错误。
 *
 * 返回 `T | null`:信封里的 `data` 允许为 `null`,那不是错误 —— 由调用方决定怎么兜底。
 */
async function requestJson<T>(url: string, timeoutMs = 10000): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    const body = (await response.json()) as Envelope<T>;
    if (!body.success) {
      throw new Error(body.error?.message ?? "框架接口返回失败");
    }
    return body.data;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * smart-factory 的**裸 JSON** 请求:成功响应直接是资源本身,没有 `{success,data}` 包裹。
 */
async function requestBareJson<T>(url: string, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { method: "GET", signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

// ────────────────────────── 映射 ──────────────────────────

/** smart-factory agent → `Agent`(`icon` 为空时组件回落到内置图标)。 */
export function toAgent(agent: HarnessAgent): Agent {
  return {
    id: agent.id,
    name: agent.name,
    icon: agent.icon === "" ? undefined : resolveServiceAssetUrl(agent.icon),
    description: agent.description,
    createdAt: agent.createdAt,
    updatedAt: agent.updatedAt,
    dir: agent.dir,
    runtimeDir: agent.runtimeDir ?? undefined,
    workspaceId: agent.workspaceId ?? undefined,
    source: agent.source,
    commands: agent.commands?.map((command) => ({
      name: command.name,
      namespace: command.namespace,
      description: command.description,
      path: command.path,
      updatedAt: command.updatedAt,
    })),
    skills: agent.skills?.map((skill) => ({
      name: skill.name,
      displayName: skill.displayName,
      description: skill.description,
      version: skill.version,
      path: skill.path,
      updatedAt: skill.updatedAt,
    })),
  };
}

/** 框架工作区里本模块用得到的字段（`GET /api/workspaces/*` 的浏览器面）。 */
interface HarnessWorkspace {
  id: string;
  name: string;
  directory: string;
  defaultModelId?: string | null;
}

/**
 * 按 id 取工作区目录；失败返回 null。
 *
 * 用途：智能体 `dir` 反推不出工作区时（布局被改过 / 非常规目录），
 * 用 agent 自带的 `workspaceId` 直接问框架要目录。
 */
export async function fetchWorkspaceDirectory(workspaceId: string): Promise<string | null> {
  try {
    const workspace = await requestJson<HarnessWorkspace>(
      `${HARNESS_API_BASE}/workspaces/${encodeURIComponent(workspaceId)}`
    );
    return workspace?.directory ?? null;
  } catch {
    return null;
  }
}

/**
 * 当前激活工作区的目录；没有工作区或框架不可达时返回 null。
 *
 * 用途：拿不到会话所属工作区时的兜底（产品约定：退回"当前默认工作区"）。
 */
export async function fetchActiveWorkspaceDirectory(): Promise<string | null> {
  try {
    const workspace = await requestJson<HarnessWorkspace | null>(
      `${HARNESS_API_BASE}/workspaces/active`
    );
    return workspace?.directory ?? null;
  } catch {
    return null;
  }
}

/**
 * 模型 → 下拉选项。
 *
 * 默认项 = **当前生效**的那条;框架里没有生效模型时给 `null`,于是列表照常显示、
 * 但不预选。刻意**不**回落到第一项:那会让"默认 = 生效模型"这句话失真。
 */
function toModelOptions(models: HarnessModel[]): {
  options: DropdownOption[];
  defaultModelId: string | null;
} {
  const options: DropdownOption[] = models.map((model) => ({
    id: model.id,
    name: model.label || model.modelName,
  }));
  const active = models.find((model) => model.isActive);
  return { options, defaultModelId: active?.id ?? null };
}

/** 取模型列表与默认项(等价于原来 agent-runtime 的 `fetchModels`)。 */
export async function fetchModelsAsOptions(): Promise<{
  options: DropdownOption[];
  defaultModelId: string | null;
}> {
  // 列表接口:一个模型都没配时给 `[]`(不是 `null`);`?? []` 只是对信封的防御
  const models = await requestJson<HarnessModel[]>(`${HARNESS_API_BASE}/models`);
  return toModelOptions(models ?? []);
}
