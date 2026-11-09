import { sessionService } from '../session/session.service.js';
import type { PageResult, Run } from '../../shared/types/index.js';

/**
 * 运行域服务：只做运行记录的查询与中止，编排都在 session 域（跨域只走 service）。
 */
export const runService = {
  list(sessionId: string, page: unknown, pageSize: unknown): Promise<PageResult<Run>> {
    return sessionService.listRuns(sessionId, page, pageSize);
  },

  detail(runId: string): Promise<Run> {
    return sessionService.getRun(runId);
  },

  children(runId: string, page: unknown, pageSize: unknown): Promise<PageResult<Run>> {
    return sessionService.listChildRuns(runId, page, pageSize);
  },

  abort(runId: string): Promise<Run> {
    return sessionService.abortRun(runId);
  },
};
