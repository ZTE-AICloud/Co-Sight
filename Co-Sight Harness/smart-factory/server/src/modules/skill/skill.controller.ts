import type { Request, Response } from 'express';
import { skillService } from './skill.service.js';

/** HTTP 适配：取参 → service → 组装响应。 */
export const skillController = {
  async list(req: Request, res: Response): Promise<void> {
    res.json(await skillService.list({ workspaceId: req.query.workspaceId }));
  },
};
