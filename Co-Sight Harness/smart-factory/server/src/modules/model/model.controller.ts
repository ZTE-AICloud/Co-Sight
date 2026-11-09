import type { Request, Response } from 'express';
import { modelService } from './model.service.js';

/** HTTP 适配：转调 service，业务与上游失败翻译都不在这里。 */
export const modelController = {
  async list(_req: Request, res: Response): Promise<void> {
    res.json(await modelService.listModels());
  },
};
