/**
 * 模块面模型契约（对外接口 `/api/framework/v1/models`）。
 *
 * ⚠️ **本文件与 `model.ts` 是刻意相反的两面。改动前请把下面这段读完。**
 *
 * - `model.ts` = **浏览器面**。它有一句硬声明：「本契约里没有任何字段会返回明文密钥」，
 *   由 `tests/api-model.test.ts` 钉死。这句话现在依然成立，一个字都没松。
 * - 本文件 = **模块面**。它**有**明文 `apiKey`——代价是调用方必须带一枚本机令牌，
 *   那枚令牌只存在于 `$COSIGHT_HOME/.module-token`（文件 0600）。浏览器读不到本机文件，
 *   所以 XSS 与跨源页面拿不到密钥；这正是这套门禁存在的**全部**理由。
 *
 * 两面能共存，靠的是三条**结构性**保证，而不是"大家写的时候注意点"：
 *
 * 1. **本文件不写进 `contracts/index.ts`。** 那个 index 是 `export *`，写进去就等于
 *    顺着 barrel 自动流到浏览器前端。服务端经 subpath `harness-shared/module-models`
 *    导入（见 `shared/package.json` 的 `exports`），于是前端唯一入口 `harness-shared`
 *    根本看不见本文件。
 * 2. **服务端的投影函数物理分离。** 浏览器面是 `repositories/model-config.repository.ts`
 *    的 `toModelConfig()`，模块面是 `services/module-models.ts` 的 `ModuleModelService`。
 *    两边没有共享的映射代码，所以没有一处改动能同时把两面弄坏。
 * 3. **有一条守卫测试**（`tests/module-contract-isolation.test.ts`）断言前端源码与两个
 *    barrel 里都不出现本文件——把"某天有人顺手把它加进 index"变成 CI 能拦住的错误。
 *
 * 关于 `protocol`：框架的 `provider` 回答"是哪家供应商"，模块要问的是"讲哪种线协议"
 * （Anthropic Messages vs OpenAI chat-completions）。没有这个字段，用户把
 * `provider: 'openai'` 的模型设为当前生效，模块会**静默**拿 anthropic SDK 去打一个
 * OpenAI 端点，最后表现为一句语焉不详的上游报错。它是**派生字段，不落库**——
 * 将来若要允许用户覆盖，只改 `protocolFromProvider`，响应形状不变。
 */

import { z } from 'zod';

import { MODEL_PROVIDER_KINDS, type ModelProviderKind } from './model';

/** 线协议。判定依据是"讲哪套 API"，不是"哪家厂商"。 */
export const MODEL_PROTOCOLS = ['anthropic', 'openai'] as const;

export type ModelProtocol = (typeof MODEL_PROTOCOLS)[number];

/**
 * 供应商 → 线协议。
 *
 * `ollama` 归到 `openai`：它对外暴露的是 OpenAI 兼容的 `/v1`。
 * `azure-openai` 也归到 `openai`，但注意它的**地址形态**与 openai 不同
 * （要带 deployment 段），所以本契约**不对 `baseUrl` 做默认值推导**——
 * 推导会静默给出错误地址，比返回 null 更糟。null 的语义是"用该供应商的官方地址"，
 * 由消费方自己决定。
 */
export function protocolFromProvider(provider: ModelProviderKind): ModelProtocol {
  return provider === 'anthropic' ? 'anthropic' : 'openai';
}

/**
 * 列表项：只放"选中一个模型"所需的字段。
 *
 * 刻意**没有** `apiKey`，也刻意**没有** `apiKeyMasked`——掩码在模块面没有语义，
 * 给了只会让人误用。明文只从 `GET /models/:id` 与 `GET /models/active` 两条路由出去，
 * 泄漏面因此是固定的两条，而不是"每个返回模型的地方"。
 */
export const moduleModelSummarySchema = z.object({
  id: z.uuid(),
  /** 原样透传，便于排查"是哪一种被归并成了 openai"。 */
  provider: z.enum(MODEL_PROVIDER_KINDS),
  protocol: z.enum(MODEL_PROTOCOLS),
  /** 用户可见名称，对应 smart-factory 前端下拉的 `label`。 */
  label: z.string().min(1).max(64),
  /** 发给供应商的 model 字段（就是 Claude Code 配置里那种），对应 `MODEL_NAME`。 */
  modelName: z.string().min(1).max(128),
  /** 自定义网关地址；null 表示用该供应商的官方地址。 */
  baseUrl: z.string().nullable(),
  /** 是否已配置密钥。列表只给状态，不给值。 */
  hasApiKey: z.boolean(),
  isActive: z.boolean(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type ModuleModelSummary = z.infer<typeof moduleModelSummarySchema>;

/**
 * 详情：summary + **明文密钥** + 推理参数。
 *
 * `apiKey` 为 null 表示这个模型没配密钥（`hasApiKey === false`），
 * 消费方必须自己处理这一支，而不是把 null 当空串塞进环境变量。
 */
export const moduleModelSecretSchema = moduleModelSummarySchema.extend({
  apiKey: z.string().nullable(),

  temperature: z.number().min(0).max(2),
  topP: z.number().min(0).max(1),
  maxOutputTokens: z.number().int().positive().nullable(),
  contextWindow: z.number().int().positive().nullable(),
  timeoutSeconds: z.number().int().positive(),
});

export type ModuleModelSecret = z.infer<typeof moduleModelSecretSchema>;

/**
 * 列表响应。
 *
 * 带上 `activeId` 是为了让消费方一次调用就能预选中下拉项——否则它得先拉列表、
 * 再拉 `/active`，而这两次调用之间"当前生效的模型被换掉"会产生一个真实的竞态。
 */
export const moduleModelListResponseSchema = z.object({
  items: z.array(moduleModelSummarySchema),
  activeId: z.uuid().nullable(),
});

export type ModuleModelListResponse = z.infer<typeof moduleModelListResponseSchema>;

/** 模块面的 base path；与 `app.ts` 的注册前缀必须一致。 */
export const MODULE_FACE_BASE_PATH = '/api/framework/v1';

/**
 * 凭据载体：`Authorization: Bearer <token>`。
 *
 * 用 `Authorization` 而不是自定义头，是因为 `app.ts` 的 pino `redact` 本来就覆盖
 * `req.headers.authorization`——这条"令牌不落日志"的保护**已经存在且已被测试覆盖**；
 * 换成自定义头就意味着必须记得去加 redact，漏一次就静默泄漏。
 *
 * 只认请求头，**不认 query 参数**：查询串会进 Referer、浏览器历史、反向代理访问日志
 * （与 `bridge/session.ts` 同一个理由）。
 *
 * 注意语义：`routes/bridge.ts` 的 `Authorization: Bearer` 装的是**桥接会话 id**，
 * 与本令牌是两回事。模块面**不接受**桥接会话——那会让"有一个跨源 iframe 会话"
 * 等价于"能读密钥库"，把两个信任域混成一个。
 */
export const MODULE_TOKEN_HEADER = 'authorization';
export const MODULE_TOKEN_SCHEME = 'Bearer ';
