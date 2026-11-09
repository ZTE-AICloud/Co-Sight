import type { Request, Response } from 'express';
import { knowledgeService } from './knowledge.service.js';

/** HTTP 适配：转调 service，上游失败的翻译都在 service。 */
export const knowledgeController = {
  async listWorkflows(_req: Request, res: Response): Promise<void> {
    res.json(await knowledgeService.listWorkflows());
  },
};
