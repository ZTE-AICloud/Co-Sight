import { Router } from 'express';
import { runController } from './run.controller.js';

/** 挂载点：/api/smart-factory/v1（runs/*） */
export const runRouter = Router();

runRouter.get('/runs/list', runController.list);
runRouter.get('/runs/detail', runController.detail);
runRouter.get('/runs/children', runController.children);
runRouter.post('/runs/abort', runController.abort);
