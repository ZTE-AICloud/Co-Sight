import type { Request, Response } from 'express';
import { artifactService } from './artifact.service.js';

/** HTTP 适配：取参 → service → 组装响应。download 的 raw 流在这里直出。 */
export const artifactController = {
  async list(req: Request, res: Response): Promise<void> {
    res.json(await artifactService.list({ stage: req.query.stage, agentId: req.query.agentId, path: req.query.path }));
  },

  async file(req: Request, res: Response): Promise<void> {
    res.json(await artifactService.file({ stage: req.query.stage, agentId: req.query.agentId, path: req.query.path }));
  },

  async download(req: Request, res: Response): Promise<void> {
    const { absolutePath, fileName } = await artifactService.download({
      stage: req.query.stage,
      agentId: req.query.agentId,
      path: req.query.path,
    });
    // dotfiles: 'allow' 必须带：产物路径常含 .smart-factory 等点段、目录内也有 .gitignore 类点文件，
    // express 的 send 默认对点段回 404，会被错误层归一成 400
    res.download(absolutePath, fileName, { dotfiles: 'allow' });
  },
};
