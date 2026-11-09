// SPDX-License-Identifier: Apache-2.0
/**
 * @file agent-api.ts
 * @description Agent Runtime API 调用封装
 *
 * ⚠️ OSS 差异点:`fetchAgentPickerPage` / `fetchAgentDetail` / `fetchModels` 三个函数的数据源
 * 改为开源版的服务(见 `./harness-api`):智能体走 smart-factory 的 `GET /agents`,
 * 模型走框架的 `GET /api/models`。上层(`pages/chat/useChatSession.ts` 等)因此无需改动。
 *
 * 另外,开源版删掉了两个**没有调用点、且契约已不再匹配**的旧函数
 * (`fetchAgents` / `fetchVersions`)—— 它们指向 agent-runtime 的旧协议。
 */

import { AGENT_RUNTIME_API_URL, AGENT_RUNTIME_TOKEN } from "../config/api-config";
import type { DropdownOption } from "../components/Dropdown";
import {
  DEFAULT_AGENT_VERSION_ID,
  fetchAgentPage,
  fetchModelsAsOptions,
  fetchServiceAgent,
  toAgent,
  type AgentQuery,
} from "./harness-api";

// 智能体数据结构
export interface Agent {
  id: string;
  name: string;
  icon?: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  /**
   * 智能体根目录（绝对路径）。用于定位 runtime 产物目录，见
   * `pages/chat/useSessionFiles.ts`。列表与详情都会带回来。
   */
  dir?: string;
  /**
   * 运行时工作目录（绝对路径，会话 cwd）。会话里的相对路径都以它为根；
   * 服务端现算，产物未就绪时缺省。见 `pages/chat/useSessionFiles.ts`。
   */
  runtimeDir?: string;
  /** 所属工作区 id；用于 `dir` 反推不出工作区时向框架查目录。 */
  workspaceId?: string;
  /** `builtin` 表示内置智能体：runtime cwd 就是 `dir` 本身。 */
  source?: string;
  /**
   * 产物里可执行的斜杠命令（`GET /agents/{id}` 详情才有；列表项没有）。
   * 命令名就是 `name`，`namespace` 只用于展示来源，不参与 `/name`。
   */
  commands?: AgentCommand[];
  /**
   * 产物里的技能（详情才有）。技能同样以 `/<name>` 调用；
   * 插件技能自带 `plugin:` 前缀，直接使用 `name` 即可。
   */
  skills?: AgentSkill[];
}

/** 智能体产物里的一条技能（`.claude/skills/<name>` / 插件技能）。 */
export interface AgentSkill {
  /** 调用名（插件技能形如 `plugin:skill`），也是 `/` 菜单里的 `/<name>` */
  name: string;
  /** 展示名；缺省时用 `name` */
  displayName?: string;
  /** frontmatter 的 description；没有则为空串 */
  description: string;
  version?: string;
  /** 技能目录绝对路径 */
  path?: string;
  /** 目录 mtime 的 ISO 串 */
  updatedAt?: string;
}

/** 一条可执行斜杠命令（`.claude/commands/**\/*.md`）。 */
export interface AgentCommand {
  /** 文件名去 `.md`，也是 `/` 菜单里的 `/<name>` */
  name: string;
  /** 所在子目录（`/` 连接）；顶层为空串。不参与命令名 */
  namespace: string;
  /** frontmatter 的 description；没有则为空串 */
  description: string;
  /** 命令文件绝对路径 */
  path: string;
  /** 文件 mtime 的 ISO 串 */
  updatedAt: string;
}

// 智能体详情数据结构（包含版本列表）
export interface AgentDetail extends Agent {
  modelId?: string;
  versions: AgentVersion[];
}

// 版本数据结构（简化版，API 返回的版本信息）
export interface AgentVersion {
  id: string;
  version: string;
  status: string;
  updatedAt: string;
}

// 模型数据结构
export interface Model {
  id: string;
  name: string;
  displayName: string;
  provider?: string;
  apiType?: string;
  baseUrl?: string;
  source?: string;
  status?: string;
  isDefault?: boolean;
}

/**
 * 通用 API 请求函数
 */
export async function fetchApi<T>(endpoint: string): Promise<T> {
  const url = `${AGENT_RUNTIME_API_URL}${endpoint}`;

  const response = await fetch(url, {
    method: "GET",
    headers: {
      "otaf-token": AGENT_RUNTIME_TOKEN,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();

  if (data.code !== 200) {
    throw new Error(`API error: ${data.message || "Unknown error"}`);
  }

  return data;
}

/** 选择器的一页结果；`total` 是服务端按同一过滤条件算出的总数。 */
export interface AgentPickerPage {
  items: Agent[];
  total: number;
  hasMore: boolean;
}

/**
 * 获取智能体选择器的一页（原始数据，非下拉框格式）。
 *
 * OSS:数据源为 smart-factory 的 `GET /agents`(`api/harness-api.ts`)。
 * `+` 菜单只需要前 N 个与关键字结果，不再全量翻页拉取。
 */
export async function fetchAgentPickerPage(
  query: AgentQuery = {},
  page = 1,
): Promise<AgentPickerPage> {
  const result = await fetchAgentPage(query, page);
  return {
    items: result.items.map(toAgent),
    total: result.total,
    hasMore: result.hasMore,
  };
}

/**
 * 根据 ID 获取智能体详情（包含版本列表）
 *
 * 单条查询(`GET /agents/{agentId}`),不再把全部智能体翻页拉一遍再 `find`。
 *
 * OSS:专家没有版本概念，这里**伪造一个唯一版本** `DEFAULT_AGENT_VERSION_ID`，
 * 让上层的 `resolveVersion()` 原样可用（它取列表第一个），从而不必改动
 * `pages/chat/useChatSession.ts` —— 该文件因此与上游逐行一致，后续同步无需手工合并。
 */
export async function fetchAgentDetail(agentId: string): Promise<AgentDetail | null> {
  const agent = await fetchServiceAgent(agentId);
  return agent ? { ...agent, versions: [defaultAgentVersion()] } : null;
}

/** OSS 伪造的唯一版本记录。 */
function defaultAgentVersion(): AgentVersion {
  const now = new Date().toISOString();
  return {
    id: DEFAULT_AGENT_VERSION_ID,
    version: DEFAULT_AGENT_VERSION_ID,
    status: "published",
    updatedAt: now,
  };
}

/**
 * 模型列表结果：下拉框选项 + 默认选中模型
 */
export interface ModelListResult {
  /** 下拉框选项（框架里的全部模型） */
  options: DropdownOption[];
  /** 默认选中模型 id：当前生效（`isActive`）的那条；没有生效模型时为 null */
  defaultModelId: string | null;
}

/**
 * 获取模型列表，转换为下拉框格式并解析默认模型
 *
 * OSS:数据源改为 harness 框架的模型列表（`GET /api/models`，见 `api/harness-api.ts`）。
 */
export async function fetchModels(): Promise<ModelListResult> {
  return fetchModelsAsOptions();
}
