import type { AgentSource } from '../agent-source';
import type { PageResult } from '../types';
import { msg } from '../../i18n/useI18n';
import { API_BASE_URL, ApiError, createApiClient } from './client';

/**
 * 智能体管理的数据入口。正本是 `server/docs/05-openapi/5.01-agent-openapi.yaml`，
 * 机制（id 与目录的关系、status 怎么翻、删除会连带删什么）见 `server/docs/03-architecture/07-agent.md`。
 *
 * 后端就在本仓（`server/src/modules/agent/`），不再是 mock —— 请求经 vite proxy 的
 * `/api` 打到 `localhost:4100`。**这是唯一改 base URL 的地方**，页面一行不动：
 *
 *   VITE_AGENTS_API_BASE_URL 缺省 = `${VITE_API_BASE_URL}/smart-factory/v1`
 *                                = /api/smart-factory/v1  ← 本仓后端
 *   指向别的机器时才需要设它，如 http://127.0.0.1:8080/v1
 *
 * 注意 base 是**服务前缀、不是资源前缀**：资源段 `/agents` 写在下面每个方法里
 * （要让 base 收进 `/agents` 也行，但那样 5 个端点都得改成相对路径，反而看不清全貌）。
 *
 * 路径规则与旧资源相反：**资源身份一律进路径**（集合 `/agents`，个体 `/agents/{id}`、
 * `/agents/{id}/update|delete`），请求体只承载可变字段、不承载身份。
 */

/**
 * 一条智能体记录。
 *
 * 列表与详情返回的是**同一条记录**的两种切法，没有「列表给摘要、详情给全文」的分层
 * （契约 5.01 的 `Agent`：`GET /agents/{id}` 与 create 的响应形状完全一致）。
 * 后端若给详情加额外字段（会话数、模型、技能清单……），在这里扩一个
 * `AgentDetail extends Agent`，别把字段往 `Agent` 上堆 —— 列表卡片不需要它们。
 */
export interface Agent {
  /** 主键，`agt_<uuid>`，服务端生成、不可变；**同时就是产物目录名**。客户端不得解析其内容 */
  id: string;
  /**
   * 归属的框架工作区 uuid。**建后不可改**；产物目录挂在
   * `<工作区 directory>/.smart-factory/agents/{id}` 下（见 `shared/api/workspaces.ts`）。
   * 内置智能体（`source: 'builtin'`）不属于任何工作区，恒为 null。
   */
  workspaceId: string | null;
  /**
   * 来源：`user` = 用户建的（含首页创建与收养的存量目录）；`builtin` = 随产品提供、
   * boot seed 按定义目录登记。建后不可改，也不由创建请求指定。
   *
   * 内置行**只读**（update/delete 一律 409）、只能发起 runtime 会话；`id` 是定义目录名
   * （如 `example-builtin-agent`），不是 `agt_<uuid>`。来源不是标签：`tags` 里不出现
   * `内置` / `自定义`（保留字）。
   */
  source: AgentSource;
  /** 展示名，同一工作区内唯一（重名 409），trim 后 1–40 字 */
  name: string;
  /** 缺省空串。update 传空串表示清空，不传才是「不改」 */
  description: string;
  /**
   * 创建时的第一句需求原文（`POST /agents` 的 `init.input` 原样落库，不截断）。
   * 空串 = 创建时没带 `init` 或没写第一句；**建后不可改**，也不是对话内容（不产生消息）。
   *
   * 与 `description` 语义不同：那是卡片摘要（≤120 字，可编辑），这是需求原文。
   * 用途是设计页在路由 state 丢失（刷新 / 从列表再次进入）且会话为空时恢复首轮，
   * 见 `features/agent-create/useCreationChat.ts` 的 `stored`。
   */
  initialInput: string;
  /**
   * 创建时挂的附件（`POST /agents` 的 `init.attachments`），后端校验后的**真实绝对路径**；
   * 空数组 = 创建时没带附件。**建后不可改**，也不是对话内容（不产生消息）。
   *
   * 与 `initialInput` 同一用途：设计页在路由 state 丢失且会话为空时，连同首轮一起恢复。
   */
  initialAttachments: string[];
  /**
   * 当前绑定的知识检索工作流 id（`RAG_Workflow_xxx`）；**空串 = 没有 / 已取消**。
   *
   * 创建时从首条消息的 `--knowledge-workflow-id` 解析落库，之后在设计页的 chip 上改；
   * 改完只影响**下一次**以 `/agent-genesis:harness-create` 开头的消息，产物里已注入的
   * `rag-knowledge-search` 技能不会因此消失（要在技能弹层里删，或重建产物）。
   */
  knowledgeWorkflowId: string;
  /**
   * 标签，恒为数组（空数组表示没有标签，不是缺省占位）。
   *
   * 库里存的是 **JSON 数组串**（同 `messages.content` 的存法），接口这一层已经解成数组 ——
   * 前端拿到手就是 `string[]`，不要自己再 `JSON.parse`。脏数据由后端兜成空数组。
   */
  tags: string[];
  /**
   * 封面图的 HTTP(S) 地址。**空串表示没有封面**（这是一个有意义的取值，不是缺省占位）。
   *
   * 后端不解析也不校验形态，只管长度 —— 所以取不到是常态之一，头像要有兜底：
   * 没有封面、或封面加载失败时，落到**名称的第一个字**（见 shared/components/AgentAvatar）。
   */
  icon: string;
  /**
   * 产物状态，与 `GET /agents/{id}/production` 的 `status` **同源**（服务端现算、不落库）：
   * `not_started` / `building` / `blocked` / `failed` / `completed`。
   *
   * 内置智能体开箱即用，恒为 `completed`（`/production` 对它们返回 409）；`null` 只会在
   * 普通行读取磁盘状态失败时出现。**只有 `completed` 才允许使用**（卡片上的门禁）。
   * 列表与详情都带；要拿到 `reasons` / `pipeline` 等明细仍走 `/production`。
   */
  status: AgentProductionStatus | null;
  /** 产物目录绝对路径，恒为 {SMART_FACTORY_HOME}/agents/{id}。服务端现算，不代表此刻一定存在 */
  dir: string;
  createdAt: string;
  updatedAt: string;
}

/**
 * 详情比列表多两样只有单条才值得读的东西：产物里的可执行技能 / 命令，以及
 * 「产物里有没有知识检索技能」。
 *
 * 后者与 `knowledgeWorkflowId` 是两件事：配置可以取消，但产物里已注入的
 * `rag-knowledge-search` 只有重建才会消失。设计页据此提示并给出重建入口。
 */
export interface AgentDetail extends Agent {
  knowledgeInjected: boolean;
}

/* ── 产物状态（契约 4.10 / 5.03） ────────────────────────────────────────── */

export type AgentProductionStatus = 'not_started' | 'building' | 'blocked' | 'failed' | 'completed';
export type ProductionLane = 'full' | 'fast';
export type DeliveryVerdict = 'PASS' | 'CONCERNS' | 'FAIL';

/**
 * 智能体生成产物状态。
 *
 * 权威口径见 `server/docs/04-api/4.10-智能体产物状态.md`：`status` / `ready` 由服务端
 * 读 AgentGenesis 的过程状态与交付门禁派生。**只有 `ready === true` 才允许进入预览 / 评估**；
 * `reasons` 是可以直接展示给用户的原因（不含内部编号）。
 *
 * 字段与后端 DTO 同形，不要在这里加派生逻辑 —— 判断只在服务端做一处。
 */
export interface AgentProduction {
  agentId: string;
  status: AgentProductionStatus;
  /** `status === 'completed'` 的派生布尔，进入预览 / 评估的唯一依据 */
  ready: boolean;
  /** 技能车道；无法判断为 null */
  lane: ProductionLane | null;

  /** 原始过程状态，排障用；不要拿它替代 `status` */
  pipeline: {
    status: string | null;
    currentStep: string | null;
    completedSteps: number;
    lastUpdate: string | null;
    retryCount: number | null;
    retryBudget: number | null;
  } | null;

  /** 交付门禁证据；`concerns` 是内部诊断信息，不建议原样展示 */
  delivery: {
    verdict: DeliveryVerdict | null;
    source: string | null;
    concerns: string[];
  } | null;

  /** 产物定位结果；`path` 相对 development 目录 */
  product: {
    name: string;
    version: string;
    path: string;
    updatedAt: string;
  } | null;

  /** ready=false 时的人话原因 */
  reasons: string[];
}

export interface AgentListQuery {
  /** 子串匹配 name / id / description 任一，ASCII 大小写不敏感 */
  keyword?: string;
  /**
   * 单个标签，**精确匹配**（不是子串）。未传 = 不按标签筛。
   *
   * 后端只收一个 `tag`，与 `keyword` / `status` 是 AND 关系；空串视为未传。
   * 筛选值直接用 `Agent.tags` 里的原字符串，不做大小写或 trim 归一化。
   */
  tag?: string;
  /** 按来源过滤；不传 = 两种都要。空串视为未传（后端口径） */
  source?: AgentSource;
  /**
   * 按**现算的**产物状态过滤（与 `Agent.status` 同一份派生结果，库里没有这一列）。
   *
   * 只收枚举里的五个：`null`（读盘失败的降级值）不是一种状态，也传不进去。
   * 与其余条件是 AND 关系；内置智能体恒为 `completed`，所以会出现在这个筛选里。
   * 服务端先过滤再切页，`total` 是过滤后的全量。
   */
  status?: AgentProductionStatus;
  /**
   * 按所属工作区精确过滤。专家页传框架的「当前生效工作区」（见
   * `shared/api/workspaces.ts`），**没传 = 全库**——所以工作区还没解析出来时
   * 不要发请求，否则会先闪一下别的工作区的智能体。
   */
  workspaceId?: string;
  page?: number;
  pageSize?: number;
}

/**
 * 创建：只收可变字段，id 由服务端发。同一工作区内重名 409。
 *
 * `workspaceId` **必填**：智能体归属哪个工作区，产物目录就挂在哪个工作区下。
 * 后端会经框架确认工作区存在且有目录，缺了直接 400 `workspaceId 必填`。
 * 候选来自 `shared/api/workspaces.ts`；首页那条创建路取框架的「当前生效工作区」。
 *
 * `tags` 与 update 那边不同：**创建时没有「不改」这一说**，不传就是空数组
 * （契约 5.01：`tags 不传即空数组`，「没有标签」与「标签列表为空」是同一件事）。
 * 规则同 `AgentUpdateInput.tags`。来源不在这里传：服务端恒写 `source='user'`，
 * `内置` / `自定义` 是保留字（写进 tags 是 400），见 `shared/agent-source.ts`。
 */
export interface AgentCreateInput {
  workspaceId: string;
  name: string;
  description?: string;
  tags?: string[];
  icon?: string;
  /**
   * 初始化参数（契约 5.01）。传了它，后端会顺手建好该智能体的
   * `development` 初始化会话：`modelId` 是这场会话的模型。
   *
   * `input` 与 `attachments` **落进 Agent 的 `initialInput` / `initialAttachments`**
   * （原文与真实路径），但**不落消息、不起 run**：首轮由设计页连上实时通道后自己发，
   * 用户才能看到初始化过程。落库是为了路由 state 丢失（刷新 / 从列表再次进入）时还能恢复首轮。
   *
   * `attachments` 与 `messages/send` 同形状（`[{ path }]`，本机绝对路径）：端侧没有上传，
   * 后端用同一个 `resolveAttachmentPaths` 校验存在性与可访问范围。
   */
  init?: { input?: string; modelId?: string; attachments?: Array<{ path: string }> };
}

/** create 的响应：带 `init` 时多一个初始化会话 id，其余形状与 `Agent` 完全一致。 */
export interface AgentCreateResult extends Agent {
  initSessionId?: string;
}

/** `GET /agents/tags` 的一项：标签文本 + 带这个标签的智能体数量。 */
export interface AgentTagCount {
  tag: string;
  count: number;
}

/**
 * 更新：只改传了的字段，其余原样。**至少给一个字段**，五个都不给后端返回 400
 * （空请求会刷新 updatedAt、把该行顶到列表最前，是调用方看不见的副作用）。
 *
 * `tags` 与 `description` / `icon` 同构：**传 `[]` 是清空标签**，不传才是「不改」——
 * 「清空」与「不改」靠「给没给这个字段」分开，不靠「给的值空不空」。
 * 规则（≤10 个、每项 1–10 字、不含 `" \ % _`、后端会 trim 并去重）见契约 5.01 的 `Agent.tags`。
 */
export interface AgentUpdateInput {
  name?: string;
  description?: string;
  tags?: string[];
  icon?: string;
  /**
   * 知识检索工作流 id。**传空串 = 取消**，不传才是「不改」—— 与 description / icon
   * 同一套「清空 vs 不改」的判别方式。形态只允许 `[A-Za-z0-9_-]{1,128}`。
   */
  knowledgeWorkflowId?: string;
}

const BASE_URL = import.meta.env.VITE_AGENTS_API_BASE_URL ?? `${API_BASE_URL}/smart-factory/v1`;

/** 出错时把地址说出来，用户才知道该去检查哪个服务。 */
export const AGENTS_API_BASE_URL = BASE_URL;

/**
 * 「后端没起」这一族的判据：**响应根本不是 JSON**。
 *
 * 后端没监听时，vite proxy 连不上，回的是 HTML/纯文本的 500，client.ts 会包成
 * `BAD_RESPONSE` —— 这正是「服务没起」在浏览器里的长相，跟「后端说不行」（有 JSON 的 4xx）
 * 是两回事，措辞也该不同。判据只有这一处，措辞留给各调用点。
 */
export function isBackendDown(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'BAD_RESPONSE';
}

/** 「后端没起」的下一步动作。各页把它接在自己的动词后面。 */
export const BACKEND_DOWN_HINT = `本地服务没响应（${AGENTS_API_BASE_URL}）—— 确认 server 已启动（server 目录下 npm run dev）`;

/** 当前语言下的同一条提示；新代码用函数，旧调用点保留常量。 */
export function backendDownHint(): string {
  return msg('api.backendDown', { url: AGENTS_API_BASE_URL });
}

const client = createApiClient(BASE_URL);

export const agentsApi = {
  /**
   * 列表。排序是 **updatedAt 降序**（最近改动过的在最前）—— `sessions/list` 同样是
   * updatedAt 降序，`runs/list` 才是 createdAt 降序；都是契约写死的，前端不要自己重排。
   */
  list(query: AgentListQuery = {}): Promise<PageResult<Agent>> {
    const params = new URLSearchParams();
    if (query.keyword) params.set('keyword', query.keyword);
    if (query.tag) params.set('tag', query.tag);
    if (query.source) params.set('source', query.source);
    if (query.status) params.set('status', query.status);
    if (query.workspaceId) params.set('workspaceId', query.workspaceId);
    if (query.page !== undefined) params.set('page', String(query.page));
    if (query.pageSize !== undefined) params.set('pageSize', String(query.pageSize));
    const search = params.toString();
    return client.get<PageResult<Agent>>(`/agents${search ? `?${search}` : ''}`);
  },

  /**
   * 标签清单（去重 + 计数）。
   *
   * 供专家页的标签筛选下拉使用。计数口径是「有多少个智能体带这个标签」，
   * 与当前关键词 / 排序无关；排序由后端固定为 count 降序、tag 升序。
   * 无分页 —— 标签是短词，规模远小于智能体本身。
   *
   * `workspaceId` 与列表同口径：专家页按当前工作区展示，标签下拉也必须只列
   * 这个工作区里的标签 —— 否则会挑到一个别的工作区的标签、筛出空结果。
   */
  listTags(workspaceId?: string): Promise<{ items: AgentTagCount[] }> {
    const params = new URLSearchParams();
    if (workspaceId) params.set('workspaceId', workspaceId);
    const search = params.toString();
    return client.get<{ items: AgentTagCount[] }>(`/agents/tags${search ? `?${search}` : ''}`);
  },

  /**
   * 取单个智能体。创建页靠它拿顶栏的身份（名称 / 描述 / 图标）。
   *
   * 找不到是 404 `NOT_FOUND`；`id` 形态非法（含 `/`、`..` 之类）是 400 `BAD_REQUEST`
   * —— 后者由后端拦，前端不做路径形态校验。
   */
  detail(id: string): Promise<AgentDetail> {
    return client.get<AgentDetail>(`/agents/${encodeURIComponent(id)}`);
  },

  /**
   * 产物状态。**进入预览 / 评估前必须先调它**（契约 4.10）。
   *
   * 成功恒 200：智能体还没开始生成时也是 200 + `status='not_started'`，
   * 不要用 404 / 409 去区分「还没开始」。
   * `ready === false` 时不要切阶段；把 `reasons` 原样展示给用户即可。
   */
  production(id: string): Promise<AgentProduction> {
    return client.get<AgentProduction>(`/agents/${encodeURIComponent(id)}/production`);
  },

  /** 新建。重名是 409 `CONFLICT`，后端不自动加后缀 —— 调用方自己决定改名后重试。 */
  create(input: AgentCreateInput): Promise<AgentCreateResult> {
    return client.post<AgentCreateResult>('/agents', input);
  },

  /** 更新。成功即刷新 updatedAt（该行会跳到列表最前）。重名同样是 409。 */
  update(id: string, patch: AgentUpdateInput): Promise<Agent> {
    return client.post<Agent>(`/agents/${encodeURIComponent(id)}/update`, patch);
  },

  /**
   * 删除。**无请求体**，身份在路径上。
   *
   * 不可恢复：元数据行、产物目录、预览目录，以及该智能体名下全部实例的会话 / 运行 / 消息
   * 一并删掉。名下有活跃 run 时后端先停掉那些会话再删；内置智能体是 409，目标不存在是 404（不幂等）。
   */
  async remove(id: string): Promise<void> {
    await client.post<unknown>(`/agents/${encodeURIComponent(id)}/delete`);
  },
};
