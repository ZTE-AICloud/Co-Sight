/**
 * 前端自己那一小撮共享类型。
 *
 * 这里**不放智能体的记录形状** —— 那个是接口契约的一部分，长在
 * `shared/api/agents.ts` 的 `Agent` 上，跟着 `server/docs/05-openapi/5.01-agent-openapi.yaml` 走。
 * 曾经在这里放过一份自己写草稿（`AgentDefinition` / `AgentCreateRequest`），
 * 字段与真后端对不上，只能误导人，已删。
 *
 * TODO(smart-factory): 接口稳定后抽成共享包（packages/shared-types），
 * 由前后端同时依赖，消除这份重复。
 */

/** 分页响应的通用壳（契约 5.00 的 `Page`）。 */
export interface PageResult<T> {
  items: T[];
  /** 过滤后的**全量**条数，不是本页条数 */
  total: number;
}
