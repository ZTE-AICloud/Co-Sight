import { api } from './client';

/**
 * 模型清单的数据入口。
 *
 * 正本是框架（Cosight）的模型配置：`Cosight-Harness-开源/model-config-api.md`。
 * 但**浏览器不能直接打那三个接口** —— 框架拒绝带 `Origin` 的请求（包括本模块自己的页面），
 * 而且 `/active` 与 `/{id}` 会返回明文密钥。所以这里打的是本仓 server 的只读代理：
 *
 *   GET /api/smart-factory/v1/models/list   → { items, activeId }
 *
 * server 侧读本机 `.module-token`、请求 `http://127.0.0.1:4300/api/framework/v1/models`，
 * 只把不含密钥的列表转出来（见 `server/src/modules/model/`）。
 *
 * 本期**只有 list，且是只读的**。新增 / 编辑 / 删除请在框架的「设置 → 模型设置」里做；
 * 框架模块面根本没注册写接口，本服务也不代理。
 */

/** 协议类型：决定用哪套 SDK / 报文格式。值由框架直接给，不从 provider 硬推。 */
export const MODEL_PROTOCOLS = ['anthropic', 'openai'] as const;
export type ModelProtocol = (typeof MODEL_PROTOCOLS)[number];

/**
 * 一条模型（框架列表响应的子集）。
 *
 * 与旧 mock 版的差别：`displayName` 改叫 `label`（框架的字段名），
 * `protocol` 变成小写（框架的取值），`baseUrl` 可能是 `null`（表示用官方地址），
 * 并且**没有 `apiKey`** —— 密钥只在服务端进程里，永远不进浏览器。
 */
export interface ModelSummary {
  /** 框架里的 uuid */
  id: string;
  /** 供应商：openai / anthropic / azure-openai / ollama / openai-compatible */
  provider: string;
  protocol: ModelProtocol;
  /** 界面上显示的名称 */
  label: string;
  /** 发给供应商的 model 字段（CC 配置里的那种），不是显示名 */
  modelName: string;
  /** null = 用该供应商的官方地址；框架不做默认值推导 */
  baseUrl: string | null;
  hasApiKey: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ModelListResult {
  items: ModelSummary[];
  /** 当前生效模型；没有生效模型时为 `null`。一次调用即可预选，避免「先列表再查 active」的竞态 */
  activeId: string | null;
}

export const modelsApi = {
  list(): Promise<ModelListResult> {
    return api.get<ModelListResult>('/smart-factory/v1/models/list');
  },
};
