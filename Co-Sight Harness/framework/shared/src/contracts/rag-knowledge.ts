/**
 * RAG 知识库跳转路由契约（设置 → 知识库路由设置）。
 *
 * 这一份记录回答两个问题：
 *   1. 用户配置的「跳转路由」是哪一个地址（`routeUrl`）；
 *   2. 当前生效（「可用」）的是哪一条。
 *
 * 三条刻意定死的语义：
 *
 * - **全局至多一条生效。** 不做 `enabled` + `isDefault` 两个开关：模块拿到一份配置
 *   就该知道用哪条，多一个「可用但没选」的状态只会让它无从下手。数据库侧还有一条
 *   部分唯一索引兜底（见 `server/src/db/schema.ts`）。
 * - **没有「至少一条生效」的约束。** 用户删掉生效项后就该是"当前没有"，而不是被系统
 *   自作主张换成另一条——那属于替用户改配置。
 * - **模块面只读。** 消费者只需要知道用哪条，写入者是设置里的用户。
 *
 * `routeUrl` 是整个功能唯一有攻击面的字段：它最终会变成可点击的链接。校验规则见
 * `ragKnowledgeRouteUrlSchema`，拒绝清单写在它上面。
 *
 * ## 账号密码与 API Key
 *
 * 知识库站点通常要先登录，所以每条路由可以带一组账号密码；模块用它自己的
 * Agent API（`X-API-Key`）访问知识服务时，还需要一枚 API Key。
 *
 * - **用户名按普通字段处理**：它不是秘密，界面要显示"这条用的是哪个账号"，
 *   编辑时也要能带出来。它是可空的，空表示不需要登录。
 * - **密码与 API Key 遵循 D26（只写不读）**，与模型密钥、代理令牌完全同一条路：
 *   明文只存在于 `$COSIGHT_HOME/.credentials.yaml`，库里只存引用键；
 *   浏览器面只给 `hasPassword` / `hasApiKey` 与固定掩码，**永远不出现明文**；
 *   三态（留空保持 / 送值覆盖 / 送 `null` 清除）由 `resolveSecret` 负责。
 * - 模块面（`module-rag-knowledge.ts`）**有**明文 `password` 与 `apiKey`，
 *   前提是带本机令牌。与模型两面共存的三条结构性保证一模一样，
 *   见那个文件的开头。
 *
 * `apiKey` 对应模块（smart-factory）的 `CO_KNOWLEDGE_API_KEY`，形如 `ragk_...`。
 * 服务端还可以用 `COSIGHT_KNOWLEDGE_API_KEY`（或模块同名的 `CO_KNOWLEDGE_API_KEY`）
 * 预置一枚**全局默认**：路由自己没配时，模块面回落到它。默认值只以布尔
 * `hasDefaultApiKey` 的形式让浏览器知道"有没有"，值本身不出服务端。
 */

import { z } from 'zod';

import { httpUrlSchema } from './primitives';

/** 与设置面板的字段提示共用一组上限。 */
export const RAG_KB_ROUTE_MAX_LENGTH = 2048;
export const RAG_KB_NAME_MAX_LENGTH = 64;
export const RAG_KB_DESCRIPTION_MAX_LENGTH = 256;
/** 账号名上限；与其它标识类字段同量级，够放 `域\账号` 这类写法。 */
export const RAG_KB_USERNAME_MAX_LENGTH = 128;
/** 密码上限与模型密钥 / 代理令牌一致（同为 2048）。 */
export const RAG_KB_PASSWORD_MAX_LENGTH = 2048;
/** Agent API Key 上限；与密码同量级（`ragk_` 开头的令牌远短于此）。 */
export const RAG_KB_API_KEY_MAX_LENGTH = 2048;

/**
 * 跳转路由：**只接受 http/https 绝对地址，且不能内嵌账号密码**。
 *
 * 基础协议限制复用 `httpUrlSchema`。在这个之上补一条：`https://user:pass@host/`
 * 能通过协议校验，但凭据会随链接进入浏览器历史、Referer 与截图；而一个「跳转路由」
 * 没有需要内嵌凭据的正当场景。其余形状由 `z.url` 自己挡掉（已实测）：
 * `javascript:`、`data:`、`file:`、`//evil.example`、`/\evil.example`、相对路径。
 */
export const ragKnowledgeRouteUrlSchema = httpUrlSchema
  .max(RAG_KB_ROUTE_MAX_LENGTH)
  .refine((value) => {
    // zod 在 `z.url()` 已经判失败后仍会跑这条 refine（不 abort），
    // 所以这里必须自己兜住解析异常，否则 safeParse 会直接抛 TypeError。
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return false;
    }
    return url.username === '' && url.password === '';
  }, '跳转路由不能内嵌账号密码');

/** 读模型。时间戳用 ISO 字符串，与其它契约一致。 */
export const ragKnowledgeBaseSchema = z.object({
  id: z.uuid(),
  /** 用户可见名称，用于区分同一条路由的不同环境（如「生产」「测试」）。 */
  name: z.string().min(1).max(RAG_KB_NAME_MAX_LENGTH),
  routeUrl: ragKnowledgeRouteUrlSchema,
  /** 登录知识库用的账号；null 表示这条路由不需要登录。 */
  username: z.string().max(RAG_KB_USERNAME_MAX_LENGTH).nullable(),
  /**
   * 密码的读法（D26）：只给"配没配"与一个固定掩码，**明文永不出现在浏览器面**。
   * 掩码的存在是为了让列表行与表单能说清"这里有一个密码"，而不是让谁去解析它。
   */
  passwordMasked: z.string().nullable(),
  hasPassword: z.boolean(),
  /**
   * 模块访问知识服务用的 Agent API Key（`CO_KNOWLEDGE_API_KEY`）的读法，
   * 与密码同一套 D26：只给"配没配"与固定掩码，明文永不出浏览器面。
   */
  apiKeyMasked: z.string().nullable(),
  hasApiKey: z.boolean(),
  description: z.string().max(RAG_KB_DESCRIPTION_MAX_LENGTH).nullable(),
  /** 是否为当前生效的那一条（全局至多一个）。 */
  isActive: z.boolean(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export type RagKnowledgeBase = z.infer<typeof ragKnowledgeBaseSchema>;

export const createRagKnowledgeBaseInputSchema = z.object({
  name: z.string().trim().min(1).max(RAG_KB_NAME_MAX_LENGTH),
  routeUrl: ragKnowledgeRouteUrlSchema,
  /** 账号留空即 `null`（不需要登录），不是空串——空串在对外的读模型里没有意义。 */
  username: z.string().trim().max(RAG_KB_USERNAME_MAX_LENGTH).nullable().default(null),
  /**
   * 明文密码（写入侧唯一一次出现）。`min(1)`：空串这里判非法而不是"清除"，
   * 新建时"不设置密码"用 `null` 表达；否则用户看到的是"请求参数校验未通过"。
   */
  password: z.string().min(1).max(RAG_KB_PASSWORD_MAX_LENGTH).nullable().default(null),
  /**
   * 模块用的 Agent API Key（`CO_KNOWLEDGE_API_KEY`）。与 `password` 同一条 D26：
   * 留空 = 用服务端预置的默认（若有），不在这里塞空串——空串会被 `min(1)` 判 422。
   */
  apiKey: z.string().min(1).max(RAG_KB_API_KEY_MAX_LENGTH).nullable().default(null),
  description: z
    .string()
    .trim()
    .max(RAG_KB_DESCRIPTION_MAX_LENGTH)
    .nullable()
    .default(null),
  /**
   * 新增时直接设为可用。
   *
   * 面板里是一个勾选框（默认不勾）。默认值取 `false` 而不是「自动成为唯一一条」：
   * 新增的动机常常只是先把地址存下来，替用户激活会让正在用的那条被悄悄换掉。
   */
  isActive: z.boolean().default(false),
});

/**
 * 仓储 / 服务层的创建入参取 `z.input`：带 `default` 的字段在类型上仍可选，
 * 这样 seed 与测试可以直接传 `{ name, routeUrl, isActive }`，不必补一串 null。
 * 缺省值由 `createRagKnowledgeBaseInputSchema.parse` 在 HTTP 边界上补齐。
 */
export type CreateRagKnowledgeBaseInput = z.input<typeof createRagKnowledgeBaseInputSchema>;

/**
 * PATCH 语义与模型 / Agent 代理一致：`undefined` = 不改，`null` = 清空
 * （`description` / `username` / `password`），字符串 = 覆盖。
 * `isActive: true` 会清掉别的生效项，`false` 只是取消本条。
 */
export const updateRagKnowledgeBaseInputSchema = z
  .object({
    name: z.string().trim().min(1).max(RAG_KB_NAME_MAX_LENGTH).optional(),
    routeUrl: ragKnowledgeRouteUrlSchema.optional(),
    /** `null` 清空账号；空串在这里判非法，界面会把空输入框映射成 `null`。 */
    username: z.string().trim().max(RAG_KB_USERNAME_MAX_LENGTH).nullable().optional(),
    /** `null` 清除已存密码；`undefined` 保持原密码（JSON 序列化时这个键消失）。 */
    password: z.string().min(1).max(RAG_KB_PASSWORD_MAX_LENGTH).nullable().optional(),
    /** `null` 清除自己的 API Key（回落服务端默认）；`undefined` 保持不变。 */
    apiKey: z.string().min(1).max(RAG_KB_API_KEY_MAX_LENGTH).nullable().optional(),
    description: z.string().trim().max(RAG_KB_DESCRIPTION_MAX_LENGTH).nullable().optional(),
    isActive: z.boolean().optional(),
  })
  .refine((patch) => Object.values(patch).some((value) => value !== undefined), {
    message: '至少需要一个待更新字段',
  });

export type UpdateRagKnowledgeBaseInput = z.infer<typeof updateRagKnowledgeBaseInputSchema>;

/**
 * 面板要知道"服务端有没有预置默认 API Key"，但**不能**拿到它。
 *
 * 这就是一个布尔：默认值来自服务端环境变量（`COSIGHT_KNOWLEDGE_API_KEY`，或模块
 * 同名的 `CO_KNOWLEDGE_API_KEY`），不落库、不回显。界面据此把"留空会怎样"说清楚，
 * 而不是让用户对着一个空输入框猜自己刚保存的密钥到底生效了没有。
 */
export const ragKnowledgeDefaultsSchema = z.object({
  hasDefaultApiKey: z.boolean(),
});

export type RagKnowledgeDefaults = z.infer<typeof ragKnowledgeDefaultsSchema>;
