import type { Request, Response } from 'express';
import { requireString } from '../../shared/validate.js';
import { runService } from './run.service.js';

/** HTTP 适配：取参 → service → 组装响应。 */
export const runController = {
  async list(req: Request, res: Response): Promise<void> {
    res.json(
      await runService.list(requireString(req.query.sessionId, 'sessionId'), req.query.page, req.query.pageSize),
    );
  },

  async detail(req: Request, res: Response): Promise<void> {
    res.json(await runService.detail(requireString(req.query.runId, 'runId')));
  },

  async children(req: Request, res: Response): Promise<void> {
    res.json(
      await runService.children(requireString(req.query.runId, 'runId'), req.query.page, req.query.pageSize),
    );
  },

  async abort(req: Request, res: Response): Promise<void> {
    res.json(await runService.abort(requireString((req.body ?? {}).runId, 'runId')));
  },
};
