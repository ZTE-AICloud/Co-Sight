import { Router } from 'express';
import { evaluationController } from './evaluation.controller.js';

/** 挂载点：/api/smart-factory/v1（evaluations/*）；id 一律走 query（4.02 §3）。 */
export const evaluationRouter = Router();

evaluationRouter.get('/evaluations/list', evaluationController.list);
evaluationRouter.get('/evaluations/detail', evaluationController.detail);
evaluationRouter.get('/evaluations/cases/list', evaluationController.caseList);
evaluationRouter.get('/evaluations/cases/detail', evaluationController.caseDetail);
