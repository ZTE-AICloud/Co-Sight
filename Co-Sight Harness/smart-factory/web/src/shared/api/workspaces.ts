import { api } from './client';

/**
 * 工作区清单的数据入口。
 *
 * 正本：`server/docs/04-api/4.01-接口总览.md` §4.5。工作区由框架（Cosight）管理 ——
 * 创建、绑定目录、切换都在框架界面里做，本服务只代理一份只读列表，**不下发 directory**：
 *
 *   GET /api/smart-factory/v1/workspaces/list   → { items: [{ id, name, defaultModelId }], activeId }
 *
 * `defaultModelId` 原样转发框架的值，供预览 / 评估首次建会话时解析默认模型
 * （见 `shared/api/default-model.ts`）。
 *
 * 前端有两处消费它：
 * 1. **专家页按当前工作区展示**（`useWorkspaces`）：列表与标签都只取 `activeId`
 *    对应的那一个工作区；
 * 2. **创建智能体时给出必填的 `workspaceId`**（见 `create-agent`）。
 *
 * `activeId` 是框架的「当前生效工作区」，没有生效工作区时为 `null` —— 这时前端
 * **不拿列表第一项兜底**，而是显示「未选择工作区」并停止创建 / 取数（口径见
 * `useWorkspaces`）。切换工作区在框架界面完成，本服务不提供写端点。
 */
export interface WorkspaceSummary {
  /** 框架里的工作区 uuid */
  id: string;
  /** 界面上的展示名 */
  name: string;
  /**
   * 该工作区的默认模型 id；`null` = 沿用框架全局当前模型。
   * 供预览 / 评估首次建会话时的默认模型解析（见 `shared/api/default-model`）。
   */
  defaultModelId: string | null;
}

export interface WorkspaceListResult {
  items: WorkspaceSummary[];
  /** 当前生效工作区；框架没有生效工作区时为 `null` */
  activeId: string | null;
}

export const workspacesApi = {
  list(): Promise<WorkspaceListResult> {
    return api.get<WorkspaceListResult>('/smart-factory/v1/workspaces/list');
  },
};
