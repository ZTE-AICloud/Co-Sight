import { Router } from 'express';
import { agentController } from './agent.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（agents/*）
 *
 * **资源身份一律进路径**：集合走集合路径，个体走 `<集合>/{id}/<动作词>`，
 * 请求体只承载可变字段、不承载身份。这条与 4.02 通用规范 §4 的「id 不进路径」相反，
 * 是 05-openapi/ 覆盖的资源上生效的新规则（见 99-adr/0002）。
 */
export const agentRouter = Router();

agentRouter.get('/agents', agentController.list);
agentRouter.post('/agents', agentController.create);
// ⚠️ 必须排在 `/agents/:agentId` 之前：否则 `tags` 会被当成一个 agentId，
// 详情路由查库落空后回 404，而不是标签清单。
agentRouter.get('/agents/tags', agentController.listTags);
agentRouter.get('/agents/:agentId', agentController.detail);
// 产物状态：能否进入预览 / 评估的权威读点（口径与 send 门禁同源）
agentRouter.get('/agents/:agentId/production', agentController.production);
// 产物技能：装配 = 复制进 <product>/.claude/skills（见 docs/04-api/4.13-智能体技能.md）
agentRouter.get('/agents/:agentId/skills', agentController.listSkills);
agentRouter.post('/agents/:agentId/skills', agentController.attachSkill);
agentRouter.post('/agents/:agentId/skills/remove', agentController.removeSkill);
agentRouter.post('/agents/:agentId/update', agentController.update);
agentRouter.post('/agents/:agentId/delete', agentController.remove);
