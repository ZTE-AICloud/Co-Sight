import { API_BASE_URL, createApiClient } from './client';

/**
 * 智能体产物技能（装配 / 清单 / 删除）。
 *
 * 正本：`server/docs/04-api/4.13-智能体技能.md`。
 *
 * 装配 = 把技能**复制**进智能体当前产物的 `.claude/skills/<目录名>/`，复制完即生效：
 * runtime 原地读产物，preview / evaluation 起 run 前从产物整拷。
 * **不记来源、不落库、不改 CLAUDE.md** —— 清单里的项就是产物里的目录。
 */

/** 产物里的一条技能；`name` 是目录名（也是 `/` 命令名），删除时用它。 */
export interface AgentSkill {
  name: string;
  /** SKILL.md frontmatter 的 name；缺失时等于 name */
  displayName: string;
  description: string;
  /** frontmatter 的 version（如 `1.0`）；没有则空串 */
  version: string;
  /** 产物里的技能目录绝对路径（优化时拼 `<path>/SKILL.md`） */
  path: string;
  updatedAt: string;
}

export interface AgentProductRef {
  agentName: string;
  version: string;
  dir: string;
}

export interface AgentSkillsResponse {
  agentId: string;
  /** 产物未就绪时为 false：items 为空，reasons 说明原因 */
  ready: boolean;
  reasons: string[];
  product: AgentProductRef | null;
  items: AgentSkill[];
}

export interface AttachSkillResult {
  item: AgentSkill;
  product: AgentProductRef;
}

export interface RemoveSkillResult {
  removed: string;
}

const client = createApiClient(`${API_BASE_URL}/smart-factory/v1`);

export const agentSkillsApi = {
  /** 未就绪也是 200（同理产物状态端点），用 `ready` / `reasons` 表达。 */
  list(agentId: string): Promise<AgentSkillsResponse> {
    return client.get<AgentSkillsResponse>(`/agents/${encodeURIComponent(agentId)}/skills`);
  },

  /**
   * 装配。`path` 是技能目录绝对路径（技能库或智能体产出的技能都行），
   * `version` 缺省取来源里数字最大的 `vN`；显式传就把用户看到的版本钉住。
   */
  attach(agentId: string, input: { path: string; version?: string }): Promise<AttachSkillResult> {
    return client.post<AttachSkillResult>(
      `/agents/${encodeURIComponent(agentId)}/skills`,
      input.version === undefined ? { path: input.path } : { path: input.path, version: input.version },
    );
  },

  /** 从产物删除一份技能（目录名，不是 frontmatter 名）。 */
  remove(agentId: string, name: string): Promise<RemoveSkillResult> {
    return client.post<RemoveSkillResult>(
      `/agents/${encodeURIComponent(agentId)}/skills/remove`,
      { name },
    );
  },
};
