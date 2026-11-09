import type { Request, Response } from 'express';
import { requireString } from '../../shared/validate.js';
import { agentService, type AgentCreateInput, type AgentListQuery, type AgentUpdateInput } from './agent.service.js';
import {
  agentSkillService,
  type AttachSkillInput,
  type RemoveSkillInput,
} from './agent-skill.service.js';

/** HTTP 适配：取参 → service → 组装响应；业务规则不在这里。 */
export const agentController = {
  async list(req: Request, res: Response): Promise<void> {
    res.json(await agentService.listAgents(req.query as AgentListQuery));
  },

  /** 标签清单：可选按工作区过滤，无分页。 */
  async listTags(req: Request, res: Response): Promise<void> {
    res.json(await agentService.listTags(req.query.workspaceId));
  },

  async create(req: Request, res: Response): Promise<void> {
    res.json(await agentService.createAgent((req.body ?? {}) as AgentCreateInput));
  },

  async detail(req: Request, res: Response): Promise<void> {
    res.json(await agentService.getAgent(requireString(req.params.agentId, 'agentId')));
  },

  /** 产物状态：只读，不因「尚未开始」返回错误。 */
  async production(req: Request, res: Response): Promise<void> {
    res.json(await agentService.getProduction(requireString(req.params.agentId, 'agentId')));
  },

  /** 产物里的技能清单；未就绪也返回 200，用 ready / reasons 表达。 */
  async listSkills(req: Request, res: Response): Promise<void> {
    res.json(await agentSkillService.listSkills(requireString(req.params.agentId, 'agentId')));
  },

  /** 装配：把来源技能复制进当前产物；身份进路径，请求体只带来源。 */
  async attachSkill(req: Request, res: Response): Promise<void> {
    const agentId = requireString(req.params.agentId, 'agentId');
    res.json(await agentSkillService.attachSkill(agentId, (req.body ?? {}) as AttachSkillInput));
  },

  async removeSkill(req: Request, res: Response): Promise<void> {
    const agentId = requireString(req.params.agentId, 'agentId');
    res.json(await agentSkillService.removeSkill(agentId, (req.body ?? {}) as RemoveSkillInput));
  },

  async update(req: Request, res: Response): Promise<void> {
    const agentId = requireString(req.params.agentId, 'agentId');
    res.json(await agentService.updateAgent(agentId, (req.body ?? {}) as AgentUpdateInput));
  },

  async remove(req: Request, res: Response): Promise<void> {
    // 删除无请求体：身份经路径参数传递（契约 5.01 的「资源身份一律进路径」）
    await agentService.deleteAgent(requireString(req.params.agentId, 'agentId'));
    res.json({});
  },
};
