import { API_BASE_URL, createApiClient } from './client';

/**
 * 知识检索工作流的数据入口。
 *
 * 打的是本仓 server 的只读代理：`GET /knowledge/workflows/list`。
 * 上游是 RAG Studio 的 Agent API，凭据只在服务端；代理只返回**已发布**的工作流。
 * 契约见 `server/docs/04-api/4.15-知识库.md`。
 */

export interface KnowledgeWorkflow {
  /** `RAG_Workflow_xxx`，拼进 harness-create 的 `--knowledge-workflow-id` */
  id: string;
  name: string;
  description: string;
}

export interface KnowledgeWorkflowList {
  items: KnowledgeWorkflow[];
  /** 上游报告的过滤前总数；前端不据此分页 */
  total: number;
}

/** 与本仓其它模块同一条基址：`/api/smart-factory/v1`（不是裸 `/api`）。 */
const client = createApiClient(`${API_BASE_URL}/smart-factory/v1`);

export const knowledgeApi = {
  listWorkflows(): Promise<KnowledgeWorkflowList> {
    return client.get<KnowledgeWorkflowList>('/knowledge/workflows/list');
  },
};
