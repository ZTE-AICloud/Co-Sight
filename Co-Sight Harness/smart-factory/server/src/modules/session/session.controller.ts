import type { Request, Response } from 'express';
import { requireString } from '../../shared/validate.js';
import { sessionService, type CreateSessionInput, type MessageListQuery, type SessionListQuery } from './session.service.js';

/** HTTP 适配：取参 → service → 组装响应；业务规则不在这里。集合级端点 id 进 query/请求体；`sessions/:sessionId/update` 个体更新走路径（照 agents 模块）。 */
export const sessionController = {
  async create(req: Request, res: Response): Promise<void> {
    res.json(await sessionService.createSession((req.body ?? {}) as CreateSessionInput));
  },

  async list(req: Request, res: Response): Promise<void> {
    res.json(await sessionService.listSessions(req.query as SessionListQuery));
  },

  async detail(req: Request, res: Response): Promise<void> {
    res.json(await sessionService.getSession(requireString(req.query.sessionId, 'sessionId')));
  },

  async update(req: Request, res: Response): Promise<void> {
    const sessionId = requireString(req.params.sessionId, 'sessionId');
    res.json(await sessionService.updateSession(sessionId, (req.body ?? {}) as { modelId?: unknown }));
  },

  async remove(req: Request, res: Response): Promise<void> {
    await sessionService.deleteSession(requireString((req.body ?? {}).sessionId, 'sessionId'));
    res.json({});
  },

  async abort(req: Request, res: Response): Promise<void> {
    res.json(await sessionService.abortSession(requireString((req.body ?? {}).sessionId, 'sessionId')));
  },

  async listMessages(req: Request, res: Response): Promise<void> {
    res.json(await sessionService.listMessages(req.query as MessageListQuery));
  },

  async send(req: Request, res: Response): Promise<void> {
    const body = (req.body ?? {}) as {
      sessionId?: unknown;
      agentId?: unknown;
      prompt?: unknown;
      /** 本机文件：`[{ path }]` 或裸路径字符串 */
      attachments?: unknown;
      modelId?: unknown;
      mode?: unknown;
      effort?: unknown;
    };
    // 与 WS 同一入口同一校验：定位与新建会话参数原样透传
    res.json(await sessionService.sendMessage(body));
  },

  async respond(req: Request, res: Response): Promise<void> {
    const body = (req.body ?? {}) as { messageId?: unknown; decision?: unknown; answers?: unknown };
    res.json(await sessionService.respondMessage(body));
  },
};
