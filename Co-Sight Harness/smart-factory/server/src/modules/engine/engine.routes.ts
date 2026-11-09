import { Router } from 'express';
import { engineController } from './engine.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（engine/*）
 *
 * 只读：两个端点都经适配器起一次只读探测（不发起模型调用、不落会话），
 * 给前端展示「当前 Claude Code 的 `/` 菜单」与「它自己的信息」。
 * 形状见 04-api/4.16-引擎信息与命令.md。
 */
export const engineRouter = Router();

engineRouter.get('/engine/commands/list', engineController.commands);
engineRouter.get('/engine/detail', engineController.detail);
