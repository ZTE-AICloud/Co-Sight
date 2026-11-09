import { mkdirSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { BadRequestError, ConflictError, NotFoundError } from '../../shared/errors.js';
import { fetchWorkspaces } from '../../shared/framework/client.js';
import { agentsRepo, type AgentListWhere, type AgentUpdateData } from '../../shared/store/agents.repo.js';
import { instancesRepo } from '../../shared/store/instances.repo.js';
import { runsRepo } from '../../shared/store/runs.repo.js';
import { assertAgentId, stageDir } from '../../shared/workspace/dir-resolver.js';
import { resolveAttachmentPaths } from '../../shared/workspace/local-path.js';
import { readProductionStatus } from '../../shared/workspace/production.js';
import { scanExecutables } from '../../shared/skills/executables.js';
import { builtinAgentDir, scanBuiltinAgents } from '../../shared/workspace/builtin-agents.js';
import { agentRoot, resolveAgentWorkspace, resolveWorkspaceDirectory } from '../../shared/workspace/workspace-resolver.js';
import { optionalString, pageParams, readWorkspaceId, requireEnum } from '../../shared/validate.js';
import { AGENT_SOURCES, AGENT_STATUSES, DEFAULT_ICON, NAME_MAX, readDescription, readIcon, readKnowledgeWorkflowId, readName, readTag, readTags } from './agent-fields.js';
import { KNOWLEDGE_SKILL_NAME, parseKnowledgeWorkflowId } from '../../shared/knowledge/workflow-id.js';
import { assertModelRunnable } from '../model/model.service.js';
import { sessionService } from '../session/session.service.js';
import { scheduleMetadataRefresh } from './agent-metadata.js';
import type { Agent, AgentDetail, AgentProductionStatus, AgentProductionView, AgentRow, Instance, PageResult } from '../../shared/types/index.js';

/**
 * 智能体元数据。契约见 server/docs/05-openapi/5.01-agent-openapi.yaml，
 * 机制（工作区归属、目录与 id 的关系、盘库顺序、启动收养、status）见 docs/03-architecture/08-agent.md。
 *
 * 本域只管**元数据行**：产物目录由创建向导的 development 会话写，这里只建/删那颗目录本身。
 */
// 字段校验（readName / readDescription / readIcon / readTag / readTags 与各上限常量）
// 在 ./agent-fields.js —— boot seed 的内置清单校验与这里是同一套规则。

/** 一个可改字段都没给时的措辞：空请求会刷新 updatedAt、把该行顶到列表最前，是调用方看不见的副作用。 */
const NOTHING_TO_UPDATE = 'update 至少要给一个字段：name / description / tags / icon / knowledgeWorkflowId';

export interface AgentListQuery {
  keyword?: unknown;
  tag?: unknown;
  workspaceId?: unknown;
  /** 来源筛选：`user` | `builtin`；不传 = 两种都要 */
  source?: unknown;
  /**
   * 产物状态筛选：`not_started` | `building` | `blocked` | `failed` | `completed`。
   * 不传 / 空串 = 不按状态筛；枚举外的取值 400（与 source 同口径，不静默退化成「全部」）。
   */
  status?: unknown;
  page?: unknown;
  pageSize?: unknown;
}

/** 标签清单的一项：标签文本 + 带这个标签的智能体数量。 */
export interface AgentTagCount {
  tag: string;
  count: number;
}

export interface AgentCreateInput {
  workspaceId?: unknown;
  name?: unknown;
  description?: unknown;
  tags?: unknown;
  icon?: unknown;
  /** 可选：建智能体时顺带把 development 初始化会话建好（契约 5.01）。 */
  init?: unknown;
}

/**
 * 已解析的初始化参数。两个字段都恒为字符串：空串表示「没给」，
 * 与 `given()` 的 null/undefined 口径一起收口在这里，后面的流程不再判类型。
 */
interface Initialization {
  /**
   * 首轮需求正文。**落库（`agents.initial_input`），但不落消息、不起 run**：
   * 前端拿自己手上的原文在设计页触发，后端不替它动会话内容。
   * 落这一列是为了「前端数据丢了还能找回来」—— 路由 state 一刷新就没了，
   * 而创建时那句话是智能体唯一的需求来源。
   */
  input: string;
  /**
   * 创建时挂的附件。**落库（`agents.initial_attachments`）**，存的是服务端校验过的
   * 真实绝对路径；与 input 一样不产生消息、不起 run。
   * 校验边界与 `messages/send` 的 attachments 完全一致（同一个 shared 函数）。
   */
  attachments: string[];
  /** 会话 modelId；带 `init` 时必填非空，没有跟随本机配置的回落。 */
  modelId: string;
}

/** `init` 的固定字段白名单：以后扩参数就加在这里，不把整个对象当任意 JSON 存。 */
const INIT_FIELDS = ['input', 'modelId', 'attachments'] as const;

/**
 * 解析 `init`，**严格**按白名单：
 *
 * - 不传（含 JSON null）= 保持旧行为，只建智能体；
 * - 不是对象、含未知字段、`input` / `modelId` 不是字符串、`attachments` 不是数组 → 400。
 *   `null` 也算「没给对」- 初始化参数是明确的协议，不沿用顶层字段「null 等于没给」的宽松口径。
 *
 * `input` 落 `agents.initial_input`、`attachments` 落 `agents.initial_attachments`（原话与附件
 * 不再只活在前端），但**不落消息、不起 run**：首轮由前端在设计页触发，用户才能看到初始化过程
 * （08-agent.md §3.1）。
 */
async function readInit(value: unknown): Promise<Initialization | undefined> {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new BadRequestError('init 必须是对象', 'error.bad_request.invalid_value', { name: 'init', value: 'object', allowed: 'object' });
  }

  const record = value as Record<string, unknown>;
  const unknownFields = Object.keys(record).filter((key) => !(INIT_FIELDS as readonly string[]).includes(key));
  if (unknownFields.length > 0) {
    throw new BadRequestError(`init 含未知字段：${unknownFields.join(' / ')}（只支持 input / modelId / attachments）`, 'error.bad_request.unknown_fields', { fields: unknownFields.join(' / ') });
  }

  const readField = (field: 'input' | 'modelId'): string => {
    if (!Object.prototype.hasOwnProperty.call(record, field) || record[field] === undefined) return '';
    const raw = record[field];
    if (typeof raw !== 'string') throw new BadRequestError(`init.${field} 必须是字符串`);
    return raw;
  };

  // 附件在这里就解析成真实路径：形态 / 存在性校验与 messages/send 共用同一份实现。
  // 放在落行之前 —— 400 / 404 不产生需要回滚的副作用。
  const rawAttachments = record.attachments;
  if (rawAttachments !== undefined && !Array.isArray(rawAttachments)) {
    throw new BadRequestError('init.attachments 必须是数组', 'error.bad_request.attachments_array');
  }
  const attachments = await resolveAttachmentPaths(rawAttachments, 'init.attachments');

  const input = readField('input');
  return {
    // 空白串与空串同义：都视为用户没写第一句话
    input: input.trim() === '' ? '' : input,
    attachments,
    modelId: readField('modelId').trim(),
  };
}

export interface AgentUpdateInput {
  name?: unknown;
  description?: unknown;
  tags?: unknown;
  icon?: unknown;
  /** 知识检索工作流 id；空串 = 取消。给了 `null` 视为没给（「不改」与「取消」靠空串分开） */
  knowledgeWorkflowId?: unknown;
}

/** 「给了这个字段」的判据：null 与 undefined 一律算没给（JSON 里 null 是「没有值」的常见写法）。 */
function given(value: unknown): boolean {
  return value !== undefined && value !== null;
}

/**
 * 列表一次查好的产物状态输入：development 实例 + 这些实例里哪些有活跃 run。
 *
 * 列表最多 200 行，逐行查库会把一次首屏放大成几百次往返；这里按页批量取。
 * 单条请求（详情 / 创建 / 更新）不预取，仍走 `withDir` 的逐条分支。
 */
interface ProductionInputs {
  /** agentId → development 实例；没有实例的 agent 不在 Map 里 */
  instances: Map<string, Instance>;
  /** 有活跃 run 的实例 id（逐实例，不能把「有一个在跑」套到整页） */
  activeInstanceIds: Set<string>;
}

/** 批量取一页的产物状态输入；查询失败返回 undefined，让调用方退回逐条读取。 */
async function productionInputsOf(rows: AgentRow[]): Promise<ProductionInputs | undefined> {
  try {
    const instances = await instancesRepo.findByAgentIds(
      rows.filter((row) => row.source !== 'builtin').map((row) => row.id),
      'development',
    );
    const activeInstanceIds = await runsRepo.activeInstanceIds([...instances.values()].map((instance) => instance.id));
    return { instances, activeInstanceIds };
  } catch (error) {
    // 批量失败退回逐条：单条库/盘问题仍然只影响那一条，不拖垮整页
    console.error('[smart-factory] 批量读取产物状态失败，退回逐条读取：', error);
    return undefined;
  }
}

/**
 * 仓储行 + 目录 → DTO；dir / runtimeDir / status 现算，不入库。普通行拼 agentRoot，内置行就是定义目录本身。
 *
 * 普通行的 `status` 与 `GET /agents/{id}/production` **同源**：都调 `readProductionStatus`。
 * 内置智能体没有生产流程（`/production` 对它们返回 409），但随产品提供、**开箱即用**：
 * 状态恒为 `completed`（2026-10-28 起）。前端据此放行「使用」，与普通智能体同一套口径。
 * `runtimeDir` 也从同一份快照里取（`ready` 且产物存在），不再单独走 `locateProducedAgent` ——
 * 否则一次列表会把同一棵产物树扫两遍。
 *
 * `preloaded` 只给列表用（见 `productionInputsOf`）；不给时逐条查实例与活跃 run。
 * 单条派生失败（盘不可读等）只让这一条的 runtimeDir / status 为 null，不拖垮整个列表。
 */
async function withDir(row: AgentRow, directory: string, preloaded?: ProductionInputs): Promise<Agent> {
  const dir = row.source === 'builtin' ? builtinAgentDir(row.id) : agentRoot(directory, row.id);
  if (row.source === 'builtin') return { ...row, dir, runtimeDir: dir, status: 'completed' };

  const developmentDir = stageDir(dir, 'development');
  let runtimeDir: string | null = null;
  let status: AgentProductionStatus | null = null;
  try {
    // 只读查实例，不用 getOrCreate：查展示状态不该顺手建出一行实例
    const instance = preloaded
      ? (preloaded.instances.get(row.id) ?? null)
      : await instancesRepo.findByAgentAndStage(row.id, 'development');
    const hasActiveRun =
      instance === null
        ? false
        : preloaded
          ? preloaded.activeInstanceIds.has(instance.id)
          : await runsRepo.hasActiveIn([instance.id]);
    const production = readProductionStatus(developmentDir, { hasActiveRun });
    status = production.status;
    if (production.ready && production.product !== null) {
      runtimeDir = join(developmentDir, 'output', 'agents', production.product.name, production.product.version);
    }
  } catch (error) {
    console.error(`[smart-factory] 读取智能体 ${row.id} 产物状态失败：`, error);
  }
  return { ...row, dir, runtimeDir, status };
}

/** 内置行守卫：source=builtin 一律 409（只读）。`what` 只用来拼报错措辞。 */
async function assertNotBuiltin(agentId: string, what: string): Promise<void> {
  const agent = await agentsRepo.findById(agentId);
  if (agent?.source === 'builtin') throw new ConflictError(what, 'error.conflict.builtin_agent', { agentId });
}

/**
 * create 的响应：带 `init` 时多一个初始化会议 id，其余形状与 detail 完全一致。
 * 不带 `init` 时该字段不出现 - 老调用方的响应一个字节都不变。
 */
export interface AgentCreateResult extends Agent {
  initSessionId?: string;
}

/**
 * 结果集中每个工作区只解析一次；任一工作区不可用都让整个请求失败（不猜路径）。
 * 内置行（workspaceId=null）不进这张表 —— 它们的 dir 不依赖任何工作区解析。
 */
async function directoriesOf(rows: AgentRow[]): Promise<Map<string, string>> {
  const workspaceIds = [...new Set(rows.filter((row) => row.source !== 'builtin').map((row) => row.workspaceId!))];
  const directories = await Promise.all(workspaceIds.map((id) => resolveWorkspaceDirectory(id)));
  return new Map(workspaceIds.map((id, index) => [id, directories[index]!]));
}

/**
 * 仓储行 → DTO 的批量版：工作区目录与产物状态输入各按批取一次，逐条只读盘。
 *
 * 列表两条路径（分页 / 按状态）共用，免得「按状态筛」那一版把批量取数几步漏掉。
 */
async function decorate(rows: AgentRow[]): Promise<Agent[]> {
  const directories = await directoriesOf(rows);
  // 实例与活跃 run 按批取；status / runtimeDir 仍逐条读盘现算，不缓存。
  // 分页路径的条数受 pageSize 约束；按状态筛那条给的是全部候选行（见 `listByStatus`）。
  const preloaded = await productionInputsOf(rows);
  return Promise.all(rows.map((row) => withDir(row, directories.get(row.workspaceId!) ?? '', preloaded)));
}

/**
 * 按产物状态筛选。
 *
 * status 不落库（08-agent.md §2），SQL 里没有这一列可筛，所以这里先把其余条件命中的行
 * **全取出来**、现算状态、再在内存里过滤与切页。不能改成「先分页再过滤」：`total` 与
 * 页数是按过滤后的全量算的，先切页会让「共 N 个」和翻页控件一起对不上。
 *
 * 代价是这条路径会为每个候选行读一次盘（其余列表路径只读一页）。端侧本地、按工作区展示，
 * 量级可控；真涨到读盘受不了时，该给 agents 加一列状态由生产流程写，而不是把分页改回去。
 */
async function listByStatus(
  filter: AgentListWhere & { status: AgentProductionStatus },
  page: number,
  pageSize: number,
): Promise<PageResult<Agent>> {
  const { status, ...where } = filter;
  const matched = (await decorate(await agentsRepo.listAll(where))).filter((agent) => agent.status === status);
  const start = (page - 1) * pageSize;
  return { items: matched.slice(start, start + pageSize), total: matched.length, page, pageSize };
}

/**
 * 回滚时删掉刚落下的智能体目录。删盘失败只记日志、不拦数据库回滚：
 * 留下孤儿目录最多让下次启动收养出一个空壳智能体，留下半成品行则会让前端看到一个永远缺会话的智能体。
 */
function removeAgentDir(directory: string, agentId: string): void {
  const root = agentRoot(directory, agentId);
  try {
    rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  } catch (error) {
    console.error(`[smart-factory] 初始化回滚：删除目录 ${root} 失败：`, error);
  }
}

/** 删除前等引擎退出的上限：适配器不响应中止也不该把删除请求吊死，到点就带着残留目录往下走。 */
const STOP_RUNS_TIMEOUT_MS = 8_000;

/**
 * 停掉这些实例下全部活跃顶层 run，并等各自驱动链收尾。
 *
 * 中止是收敛操作：并发下已被别人停掉（`409` 已终态）视为已停，不因此让删除失败。
 * 子 run 由 `abortRun` 沿血缘一并收敛，所以这里只处理顶层。
 */
async function stopActiveRuns(instanceIds: string[]): Promise<void> {
  if (instanceIds.length === 0) return;
  // 两轮：第一轮停掉当下在跑的；引擎退出期间可能又起了一轮（send 与删除并发），再收一次
  for (let round = 0; round < 2; round += 1) {
    const active = await runsRepo.listActiveTopByInstances(instanceIds);
    if (active.length === 0) return;
    for (const run of active) {
      try {
        await sessionService.abortRun(run.id);
      } catch (error) {
        // 已终态（409）或行已被并发删掉（404）：目的已达成，不因此让删除失败
        if (!(error instanceof ConflictError) && !(error instanceof NotFoundError)) throw error;
      }
    }
    await Promise.all(active.map((run) => sessionService.awaitRunStopped(run.id, STOP_RUNS_TIMEOUT_MS)));
  }
}

export const agentService = {
  async listAgents(query: AgentListQuery): Promise<PageResult<Agent>> {
    const { page, pageSize } = pageParams(query.page, query.pageSize);
    // tag 是精确匹配（不是子串）：`?tag=天气` 不命中标签「天气2」。只收一个
    const tag = optionalString(query.tag) === undefined ? undefined : readTag(query.tag, 'tag');
    const workspaceId = optionalString(query.workspaceId) === undefined ? undefined : readWorkspaceId(query.workspaceId);
    // 来源筛选只认枚举值：`?source=` 空串视为未传，给错值是 400，不静默退化成「全部」
    const source = optionalString(query.source) === undefined ? undefined : requireEnum(query.source, AGENT_SOURCES, 'source');
    // 状态筛选同口径：空串视为未传，枚举外（含 `null` 那个降级值）一律 400
    const status = optionalString(query.status) === undefined ? undefined : requireEnum(query.status, AGENT_STATUSES, 'status');

    const keyword = optionalString(query.keyword);
    if (status !== undefined) return await listByStatus({ keyword, tag, workspaceId, source, status }, page, pageSize);

    const result = await agentsRepo.list({ keyword, tag, workspaceId, source, page, pageSize });
    return { items: await decorate(result.items), total: result.total, page, pageSize };
  },

  /**
   * 标签清单（带计数），给前端筛选下拉用。
   *
   * 口径是「有多少个智能体带这个标签」：每个 agent 的 tags 在写入时已去重，
   * 所以逐 agent 累加即可。空数组不产生条目。
   *
   * `workspaceId` 与列表同口径：给了就只统计该工作区内的智能体，空串视为未传。
   * 专家页按当前工作区展示，标签下拉必须跟着走 —— 否则会列出别的工作区的标签、
   * 选中后筛出空结果。
   *
   * 排序固定 `count` 降序、`tag` 升序：响应必须确定，前端与测试都不该依赖数据库行序。
   * 中文标签的先后按运行环境的 locale 排，不承诺语言学意义上的词典序 ——
   * 对「常用标签排前面」这个用途来说，count 才是主序。
   */
  async listTags(workspaceId?: unknown): Promise<{ items: AgentTagCount[] }> {
    const filterWorkspaceId =
      optionalString(workspaceId) === undefined ? undefined : readWorkspaceId(workspaceId);
    const rows = await agentsRepo.listTags(filterWorkspaceId);
    const counts = new Map<string, number>();
    for (const tags of rows) {
      for (const tag of tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }

    const items = [...counts].map(([tag, count]) => ({ tag, count }));
    items.sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
    return { items };
  },

  /**
   * 详情：元数据 + **此刻可执行**的技能与命令（04-api/4.14）。
   *
   * 清单只跟 `runtimeDir` 走，与 runtime 起跑门禁同源：内置智能体 = 定义目录，
   * 普通智能体 = latest vN 产物；产物未就绪时 `runtimeDir` 为 null，两项都是空数组。
   * 列表 / create / update 不带这两项 —— 列表一页 200 行，不能每行扫两棵 `.claude` 树。
   */
  async getAgent(agentId: string): Promise<AgentDetail> {
    assertAgentId(agentId);
    const agent = await agentsRepo.findById(agentId);
    if (!agent) throw new NotFoundError(`智能体 ${agentId}`);
    // 内置行的 dir 不依赖工作区解析（它没有 workspaceId）
    const detail = await withDir(agent, agent.source === 'builtin' ? '' : await resolveWorkspaceDirectory(agent.workspaceId!));
    const executables = scanExecutables(detail.runtimeDir);
    return {
      ...detail,
      ...executables,
      // 与「配置里有没有」分开：取消只改配置，产物里已注入的技能要等重建才会消失
      knowledgeInjected: executables.skills.some((skill) => skill.name === KNOWLEDGE_SKILL_NAME),
    };
  },

  /**
   * 产物状态：读 AgentGenesis 的生产过程状态与交付门禁，派生 `status` / `ready`。
   *
   * 只读；未知智能体 404，工作区不可解析 502。产物尚未开始时也返回 200，
   * 用 `status=not_started` 表达——调用方不需要用错误来区分「还没开始」。
   * 口径与 preview / evaluation 起跑门禁同源（shared/workspace/production.ts）。
   */
  async getProduction(agentId: string): Promise<AgentProductionView> {
    assertAgentId(agentId);
    await assertNotBuiltin(agentId, '内置智能体不参与生产流程');
    const workspace = await resolveAgentWorkspace(agentId);
    const developmentDir = stageDir(agentRoot(workspace.directory, agentId), 'development');
    // 只读查实例，不用 getOrCreate：查产物状态不该顺手建出一行实例
    const instance = await instancesRepo.findByAgentAndStage(agentId, 'development');
    const hasActiveRun = instance === null ? false : await runsRepo.hasActiveIn([instance.id]);

    return { agentId, ...readProductionStatus(developmentDir, { hasActiveRun }) };
  },

  /**
   * 新建：先校验入参与工作区，再落行、后建目录。
   *
   * 工作区必须在框架里存在且已绑定目录；解析失败（502）时不建行也不建目录。
   * 顺序不能反：目录是空壳，失败只需删掉它；反过来一旦重名 409 就留下一个
   * 永远没人认领的孤儿目录（08-agent.md §3）。
   *
   * 带 `init` 时再往前一步：建出 `(agentId, 'development')` 实例与初始化会话。
   * `init.modelId` 必填且须当前引擎可用（存在、anthropic、有密钥），校验在落行之前；
   * `init.input` / `init.attachments` 随行落库（`initial_input` / `initial_attachments`），
   * 不落消息、不起 run - 起跑由前端在设计页触发，用户才能看到初始化过程。
   * 两者落库是为了前端路由 state 丢失时还能恢复首轮。
   * 初始化是**全有或全无**：任一步同步失败都删掉刚落下的行与目录（08-agent.md §3.1）。
   */
  async createAgent(input: AgentCreateInput): Promise<AgentCreateResult> {
    // 400 先于 502：所有本地形态校验都在解析工作区、查询模型之前完成
    const workspaceId = readWorkspaceId(input.workspaceId);
    const name = readName(input.name);
    const description = given(input.description) ? readDescription(input.description) : '';
    const tags = given(input.tags) ? readTags(input.tags) : [];
    const icon = given(input.icon) ? readIcon(input.icon) : DEFAULT_ICON;
    const init = await readInit(input.init);

    const directory = await resolveWorkspaceDirectory(workspaceId);
    // 存在性校验放在落行之前：400 / 502 都不产生需要回滚的副作用；init.modelId 必填
    if (init) await assertModelRunnable(init.modelId, 'init.modelId');

    const agent = await agentsRepo.create({
      workspaceId,
      name,
      description,
      // 没带 init 的行也显式写空值：这两列回答「创建时的原话与附件是什么」，空就是没有
      initialInput: init?.input ?? '',
      initialAttachments: init?.attachments ?? [],
      // 首条消息里的参数就是创建时的选择：解析出来落成智能体自己的配置（之后可改 / 可取消）
      knowledgeWorkflowId: parseKnowledgeWorkflowId(init?.input ?? ''),
      tags,
      icon,
    });
    try {
      mkdirSync(join(agentRoot(directory, agent.id), 'development'), { recursive: true });
    } catch (error) {
      await agentsRepo.deleteCascade(agent.id);
      throw error;
    }

    if (!init) return await withDir(agent, directory);

    try {
      const session = await sessionService.createSession({
        agentId: agent.id,
        stage: 'development',
        modelId: init.modelId,
      });
      // 兜底元数据（正则名字 / 需求截断 / 空标签）已经落行；后台顺手刷一版 AI 的。
      // 不 await：创建不能被模型延迟绑住，失败也只是保持兜底值（见 agent-metadata.ts）。
      scheduleMetadataRefresh(agent.id, init.modelId);
      // input 不落消息、不写 description：首轮由前端在设计页触发，用户看得到初始化过程；
      // 卡片摘要（description）与首轮对话（input）语义不同，不能互相顶替。
      return { ...(await withDir(agent, directory)), initSessionId: session.id };
    } catch (error) {
      // 初始化失败不留「有 agent、没有会话」的半成品：先删盘、再删库（与 delete 同向，
      // 避免目录残留被下次启动收养回来），原始错误照常抛给调用方
      removeAgentDir(directory, agent.id);
      await agentsRepo.deleteCascade(agent.id);
      throw error;
    }
  },

  /**
   * 更新：只改传了的字段，身份与工作区都在建后不可改（换 id 就是「新建 + 删除旧的」）。
   *
   * 先解析工作区再落库：工作区不可用时返回 502 且不改任何行。
   */
  async updateAgent(agentId: string, input: AgentUpdateInput): Promise<Agent> {
    assertAgentId(agentId);

    const existing = await agentsRepo.findById(agentId);
    if (!existing) throw new NotFoundError(`智能体 ${agentId}`);
    // 只读先于「空请求」：对内置行连 PATCH {} 都不放行
    if (existing.source === 'builtin') throw new ConflictError(`智能体 ${agentId} 是内置智能体，不可修改`, 'error.conflict.builtin_agent', { agentId });

    const data: AgentUpdateData = {};
    if (given(input.name)) data.name = readName(input.name);
    if (given(input.description)) data.description = readDescription(input.description);
    if (given(input.tags)) data.tags = readTags(input.tags);
    if (given(input.icon)) data.icon = readIcon(input.icon);
    if (given(input.knowledgeWorkflowId)) data.knowledgeWorkflowId = readKnowledgeWorkflowId(input.knowledgeWorkflowId);

    if (Object.keys(data).length === 0) throw new BadRequestError(NOTHING_TO_UPDATE, 'error.bad_request.update_empty');

    const directory = await resolveWorkspaceDirectory(existing.workspaceId!);

    const updated = await agentsRepo.update(agentId, data);
    if (!updated) throw new NotFoundError(`智能体 ${agentId}`);
    return await withDir(updated, directory);
  },

  /**
   * 删除：先解析工作区、停掉名下运行的会话，再删盘，最后删库（08-agent.md §4）。
   *
   * 目录**缺失不可自愈**：一旦删盘失败而库已删，下次启动的收养会把这颗目录登记成一个新智能体，
   * 等于删不掉。工作区不可解析时什么都不删，也不改数据库。
   * 不幂等：目标不存在返回 404，不复用「已达成即成功」的语义。
   */
  async deleteAgent(agentId: string): Promise<void> {
    assertAgentId(agentId);
    const agent = await agentsRepo.findById(agentId);
    if (!agent) throw new NotFoundError(`智能体 ${agentId}`);
    // 只读在先：内置行不删盘、不删库（定义目录归产品管，删了下次 seed 也会复活）
    if (agent.source === 'builtin') throw new ConflictError(`智能体 ${agentId} 是内置智能体，不可删除`, 'error.conflict.builtin_agent', { agentId });

    // 拿不到工作区目录就不知道该删哪棵树：宁可报错也不改数据库
    const directory = await resolveWorkspaceDirectory(agent.workspaceId!);

    // 四个阶段的活跃 run 一律先停掉再删，不再拿 409 挡回去：
    // 引擎在收尾里还会碰产物目录，必须等它真正退出才动盘
    await stopActiveRuns(await agentsRepo.instanceIdsOf(agentId));

    // Windows 上文件可能被短暂占用（EBUSY/EPERM），留给内核几轮释放时间
    rmSync(agentRoot(directory, agentId), { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });

    await agentsRepo.deleteCascade(agentId);
  },

  /**
   * 启动收养：按工作区扫描盘上已有、表里没有的目录，补登记成行（幂等，08-agent.md §5）。
   *
   * - 工作区清单来自框架；`directory` 为 null 的工作区跳过；框架不可达时整轮跳过、不阻塞启动；
   * - 只扫 `<workspace.directory>/.smart-factory/agents/` 的**直接子目录**，隐藏目录与过不了
   *   形态校验的目录名跳过（手建的「我的笔记」「tmp dir」不该被收成智能体）；
   * - 补出的行 `id` / `name` 都取**原目录名，不重发 uuid** -`instances.agent_id` 是字符串引用，
   *   重发会让历史智能体的全部会话指向不存在的行；name 截断到 40 字；
   * - 表里有行、目录不存在时**不动**：宁留空壳，不误删数据。
   */
  async adoptExistingDirs(): Promise<number> {
    let workspaces;
    try {
      workspaces = await fetchWorkspaces();
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      console.warn(`[smart-factory] 收养跳过：框架工作区列表不可用：${reason}`);
      return 0;
    }

    let adopted = 0;
    for (const workspace of workspaces.items) {
      if (workspace.directory === null || workspace.directory.trim() === '') continue;

      let entries;
      try {
        entries = readdirSync(join(workspace.directory, '.smart-factory', 'agents'), { withFileTypes: true });
      } catch {
        continue; // 该工作区还没有智能体目录
      }

      for (const entry of entries) {
        const id = entry.name;
        if (!entry.isDirectory() || id.startsWith('.')) continue;
        try {
          assertAgentId(id);
        } catch {
          continue; // 形态非法或 Windows 不可用名：跳过，不收养
        }
        // id 是全局主键：不同工作区出现同名目录时先到先得
        if (await agentsRepo.exists(id)) continue;

        if (await agentsRepo.insertAdopted(id, workspace.id, id.slice(0, NAME_MAX))) adopted += 1;
        // 目录名与同一工作区内已有的展示名撞了：跳过而不是让 boot 起不来
        else console.warn(`[smart-factory] 收养跳过：目录 ${id} 与工作区 ${workspace.id} 内已有的 name 重复`);
      }
    }

    if (adopted > 0) console.log(`[smart-factory] 启动收养：${adopted} 个存量目录已登记为智能体`);
    return adopted;
  },

  /**
   * 启动 seed：扫描内置定义目录（{COSIGHT_HOME}/smart-factory/builtin-agents/），按清单登记 / 刷新行。
   *
   * - 零框架调用：框架不可达不影响内置智能体（它们不属于任何工作区）；
   * - 无行 → 登记；已有内置行且清单漂移 → 按清单刷新（清单是元数据权威）；
   * - id 被非内置行占用 → 告警跳过（用户行不动，定义目录休眠）；
   * - 定义目录已消失的内置行 → 级联删行（连带它的实例 / 会话 / 运行史）；
   * - 单目录 / 单行失败只告警，不挡启动。
   */
  async seedBuiltinAgents(): Promise<number> {
    const scanned = scanBuiltinAgents();

    let seeded = 0;
    const seenIds: string[] = [];
    const seenNames = new Set<string>();
    for (const { id, manifest } of scanned) {
      try {
        // 重名去重：name 在列表里是展示身份，两个内置清单同名时后到者告警丢弃
        if (seenNames.has(manifest.name)) {
          console.warn(`[smart-factory] 内置智能体跳过：${id}：与先到的内置清单重名「${manifest.name}」`);
          continue;
        }
        seenNames.add(manifest.name);

        const existing = await agentsRepo.findById(id);
        if (existing && existing.source !== 'builtin') {
          console.warn(`[smart-factory] 内置智能体跳过：${id}：id 已被非内置智能体占用`);
          continue;
        }

        if (!existing) {
          if (await agentsRepo.insertBuiltin(id, manifest)) {
            seeded += 1;
            console.log(`[smart-factory] 内置智能体登记：${id}（${manifest.name}）`);
          } else {
            console.warn(`[smart-factory] 内置智能体跳过：${id}：行已存在（并发或约束冲突）`);
          }
        } else {
          const drift =
            existing.name !== manifest.name ||
            existing.description !== manifest.description ||
            existing.icon !== manifest.icon ||
            JSON.stringify(existing.tags) !== JSON.stringify(manifest.tags);
          // 值没变就不 update：updatedAt 是列表排序键，无意义的刷新会把行顶到列表最前
          if (drift) await agentsRepo.update(id, manifest);
        }

        seenIds.push(id);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        console.warn(`[smart-factory] 内置智能体跳过：${id}：${reason}`);
      }
    }

    // 定义目录已消失：内置行跟着定义走，行没了目录还在等于「删不掉的幽灵」
    const stale = await agentsRepo.findBuiltinNotIn(seenIds);
    for (const id of stale) {
      try {
        await agentsRepo.deleteCascade(id);
        console.warn(`[smart-factory] 内置智能体移除：${id}：定义目录已消失（连带其会话与运行史）`);
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        console.warn(`[smart-factory] 内置智能体清理失败：${id}：${reason}`);
      }
    }

    if (seeded > 0) console.log(`[smart-factory] 内置智能体 seed：新登记 ${seeded} 个（source=builtin）`);
    return seeded;
  },
};
