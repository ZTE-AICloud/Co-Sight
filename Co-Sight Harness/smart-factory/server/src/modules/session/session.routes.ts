import { Router } from 'express';
import { sessionController } from './session.controller.js';

/** 挂载点：/api/smart-factory/v1（sessions/* 与 messages/*） */
export const sessionRouter = Router();

sessionRouter.get('/sessions/list', sessionController.list);
sessionRouter.post('/sessions/create', sessionController.create);
sessionRouter.get('/sessions/detail', sessionController.detail);
sessionRouter.post('/sessions/:sessionId/update', sessionController.update);
sessionRouter.post('/sessions/delete', sessionController.remove);
sessionRouter.post('/sessions/abort', sessionController.abort);

sessionRouter.get('/messages/list', sessionController.listMessages);
sessionRouter.post('/messages/send', sessionController.send);
sessionRouter.post('/messages/respond', sessionController.respond);
