import cors from 'cors';
import express, { type Express } from 'express';
import { config } from './config/index.js';
import { errorHandler, notFoundHandler } from './middleware/error-handler.js';
import { requestLogger } from './middleware/request-logger.js';
import { agentRouter } from './modules/agent/index.js';
import { artifactRouter } from './modules/artifact/index.js';
import { engineRouter } from './modules/engine/index.js';
import { evaluationRouter } from './modules/evaluation/index.js';
import { filesRouter } from './modules/files/index.js';
import { fsRouter } from './modules/fs/index.js';
import { healthRouter } from './modules/health/index.js';
import { knowledgeRouter } from './modules/knowledge/index.js';
import { modelRouter } from './modules/model/index.js';
import { runRouter } from './modules/run/index.js';
import { sessionRouter } from './modules/session/index.js';
import { skillRouter } from './modules/skill/index.js';
import { workspacesRouter } from './modules/workspace/index.js';

/**
 * 装配 Express 应用。
 *
 * 与 index.ts 分离，是为了让集成测试可以直接 createApp() 而不监听端口。
 * 路由前缀与接口风格见 server/docs/04-api/4.02-通用规范.md。
 */
export function createApp(): Express {
  const app = express();

  app.use(cors({ origin: config.corsOrigin }));
  app.use(express.json({ limit: '2mb' }));
  app.use(requestLogger);

  const api = '/api/smart-factory/v1';
  app.use(`${api}/health`, healthRouter);
  app.use(api, engineRouter);
  app.use(api, workspacesRouter);
  app.use(api, agentRouter);
  app.use(api, sessionRouter);
  app.use(api, runRouter);
  app.use(api, artifactRouter);
  app.use(api, skillRouter);
  app.use(api, evaluationRouter);
  app.use(api, filesRouter);
  app.use(api, fsRouter);
  app.use(api, modelRouter);
  app.use(api, knowledgeRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
