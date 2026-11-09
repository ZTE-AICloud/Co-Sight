import type { Request, Response } from 'express';
import { engineService } from './engine.service.js';

/** HTTP 适配：转调 service，cwd 校验与探测失败翻译都不在这里。 */
export const engineController = {
  async commands(req: Request, res: Response): Promise<void> {
    res.json(await engineService.commands({ cwd: req.query.cwd }));
  },

  async detail(req: Request, res: Response): Promise<void> {
    res.json(await engineService.detail({ cwd: req.query.cwd }));
  },
};
