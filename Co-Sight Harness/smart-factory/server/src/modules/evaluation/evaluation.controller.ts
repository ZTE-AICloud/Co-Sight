import type { Request, Response } from 'express';
import { evaluationService } from './evaluation.service.js';

/** HTTP 适配：取参 → service → 组装响应。全部 GET（4.09-评估报告 §3）。 */
export const evaluationController = {
  async list(req: Request, res: Response): Promise<void> {
    res.json(
      await evaluationService.listReports({
        agentId: req.query.agentId,
        status: req.query.status,
        page: req.query.page,
        pageSize: req.query.pageSize,
      }),
    );
  },

  async detail(req: Request, res: Response): Promise<void> {
    res.json(
      await evaluationService.getReportDetail({
        agentId: req.query.agentId,
        reportId: req.query.reportId,
      }),
    );
  },

  async caseList(req: Request, res: Response): Promise<void> {
    res.json(
      await evaluationService.listCases({
        agentId: req.query.agentId,
        reportId: req.query.reportId,
        status: req.query.status,
        dimension: req.query.dimension,
        page: req.query.page,
        pageSize: req.query.pageSize,
      }),
    );
  },

  async caseDetail(req: Request, res: Response): Promise<void> {
    res.json(
      await evaluationService.getCaseDetail({
        agentId: req.query.agentId,
        reportId: req.query.reportId,
        caseId: req.query.caseId,
      }),
    );
  },
};
