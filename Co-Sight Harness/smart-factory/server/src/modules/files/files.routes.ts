import { Router } from 'express';
import { filesController, uploadSingleFile } from './files.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（files/*）
 *
 * 与 agents 域同规（05-openapi 覆盖域）：集合路径不带动作词、语义由方法表达（POST 建、GET 取），
 * 个体走 `/{存储名}`，存储名即对外 id（4.08 文件 §3）。
 */
export const filesRouter = Router();

filesRouter.post('/files', uploadSingleFile, filesController.upload);
filesRouter.get('/files/:fileId', filesController.get);
