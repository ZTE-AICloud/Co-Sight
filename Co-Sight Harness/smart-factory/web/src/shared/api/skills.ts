import { api } from './client';

/**
 * 技能库的数据入口。
 *
 * 正本：`server/docs/03-architecture/10-skill-library.md` §4（接口形状）与
 * `web/docs/capability-routing.md` §4（前端口径）。
 *
 *   GET /api/smart-factory/v1/skills?workspaceId=<uuid>  → { root, cwd, items }
 *
 * 一次请求返回两路来源：技能库（`source = 'library'`，全局、不属于任何工作区）与
 * 当前工作区智能体产出的技能（`source = 'agent'`）。**落点判据只看 `source` / `ownerAgentId`，
 * 不靠路径字符串猜** —— 两路可能同名。
 *
 * `root`（库目录）与 `cwd`（工坊会话的 cwd）都由服务端给出：前端推导不出
 * `{COSIGHT_HOME}`，也就不要在客户端 `dirname` 拼路径。
 *
 * 后端实现在 `server/src/modules/skill/`（2026-10-22 落地）。前端只做真实请求、
 * **不造 mock 数据**：请求失败时页面照实说「技能库没拿到」，不拿假数据把卡片填满。
 */

/** 技能来源：技能库（全局） / 某个智能体的产物 */
export type SkillSource = 'library' | 'agent';

/**
 * 一条技能。字段与后端 DTO 同形，这里不加派生逻辑。
 *
 * 版本是目录里的 `v<数字>` 里最大的一个，没有版本目录时为空串（**不是**缺省占位）；
 * `description` / `ownerName` 同样可能为空串 / null，界面要按「没有」处理，别填空话术。
 */
export interface Skill {
  /** `SKILL.md` frontmatter 的 name；解析失败时回落目录名 */
  name: string;
  /** 技能目录的绝对路径（不是版本目录）。优化时原样传给 skill-foundry */
  path: string;
  source: SkillSource;
  /** `source === 'agent'` 时是该技能的归属智能体；库技能为 null */
  ownerAgentId: string | null;
  /** 归属智能体名；库技能为 null */
  ownerName: string | null;
  /** 形如 `v2`；空串 = 没有版本目录 */
  version: string;
  description: string;
  /** 技能目录 mtime（ISO 串） */
  updatedAt: string;
}

export interface SkillsResponse {
  /** 技能库根目录，供展示 / 排查用 */
  root: string;
  /** 工坊会话的 cwd（`{skillsRoot}`）；建目录会话时原样传回 */
  cwd: string;
  /** 库在前、智能体在后，组内按 `updatedAt` 倒序 —— 排序由接口负责 */
  items: Skill[];
}

export const skillsApi = {
  /**
   * `workspaceId` 省略 = 只返回技能库（库是端侧全局资产，不属于任何工作区）；
   * 给了才附带扫该工作区智能体的技能。
   */
  list(workspaceId?: string): Promise<SkillsResponse> {
    const search = new URLSearchParams();
    if (workspaceId !== undefined) search.set('workspaceId', workspaceId);
    const query = search.toString();
    return api.get<SkillsResponse>(`/smart-factory/v1/skills${query === '' ? '' : `?${query}`}`);
  },
};
