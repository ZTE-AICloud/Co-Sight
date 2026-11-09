import { Router } from 'express';
import { knowledgeController } from './knowledge.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（knowledge/*）
 *
 * 只做**只读**代理：知识库的建库、上传、问答都在 RAG Studio，本服务只把
 * 「有哪些已发布工作流」列出来给创建/优化智能体时选。
 * 路径沿用 4.02 的集合级形态：资源名 + 动作词。
 */
export const knowledgeRouter = Router();

knowledgeRouter.get('/knowledge/workflows/list', knowledgeController.listWorkflows);
