import { Router } from 'express';

/** 健康检查：既供探活，也用于验证服务骨架已跑通。 */
export const healthRouter = Router();

healthRouter.get('/', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'smart-factory-server',
    version: '0.1.0',
    time: new Date().toISOString(),
  });
});
