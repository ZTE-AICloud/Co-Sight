import { Router } from 'express';
import { modelController } from './model.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（models/*）
 *
 * 模型由框架（Cosight）维护，本服务只做只读代理：不新增、不修改、不删除，
 * 也不代理会返回明文密钥的 `/active` 与 `/{id}`（见 model.service.ts 文件头）。
 * 路径沿用 4.02 的集合级形态：资源名 + 动作词。
 */
export const modelRouter = Router();

modelRouter.get('/models/list', modelController.list);
