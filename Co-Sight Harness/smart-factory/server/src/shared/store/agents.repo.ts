import { Prisma, type Agent as AgentModel } from '@prisma/client';
import { prisma } from '../prisma/client.js';
import { newId } from '../ids.js';
import { ConflictError } from '../errors.js';
import type { AgentRow, AgentSource, PageResult } from '../types/index.js';
import { parseKnowledgeWorkflowId } from '../knowledge/workflow-id.js';

/**
 * `tags` 列的编解码：库里是 JSON 数组串（同 messages.content 的存法），DTO 里是数组。
 *
 * 解码容错：列里的东西理论上只有本仓库写得进去，但**解析失败宁可当空数组，也不让一次列表查询
 * 因为一行脏数据整个 500**（手改过库、或将来有人直接写 SQL 都会造成这种情况）。
 */
/** 编码侧：DTO 的数组 → 库里的 JSON 数组串。校验（长度 / 数量 / 禁用字符）在 service 层。 */
function encodeTags(tags: string[]): string {
  return JSON.stringify(tags);
}

function decodeTags(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((tag): tag is string => typeof tag === 'string') : [];
  } catch {
    return [];
  }
}

/** 附件列与 tags 同一种存法（JSON 数组串），解码容错也同一口径：脏数据当空数组，不 500。 */
function encodeAttachments(paths: string[]): string {
  return JSON.stringify(paths);
}

function decodeAttachments(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((path): path is string => typeof path === 'string') : [];
  } catch {
    return [];
  }
}

/**
 * 智能体元数据行 ↔ 仓储形状。
 *
 * `dir` 不在表里：库里只存 `workspaceId`，路径由服务层经工作区解析后补 -存下来的绝对路径
 * 只会在工作区换目录时变成脏数据（契约 5.01 的 `Agent.dir`）。
 */
function toAgentRow(row: AgentModel): AgentRow {
  return {
    id: row.id,
    workspaceId: row.workspaceId,
    source: row.source as AgentSource,
    name: row.name,
    description: row.description,
    initialInput: row.initialInput,
    initialAttachments: decodeAttachments(row.initialAttachments),
    /*
     * 存量行（本列引入前创建）是 NULL：按创建时的原话现推，语义与「创建时就记住」一致。
     * 用户改过一次后库里必是具体 id 或空串，不再走推导 —— 否则取消会被历史原文复活。
     */
    knowledgeWorkflowId: row.knowledgeWorkflowId ?? parseKnowledgeWorkflowId(row.initialInput),
    tags: decodeTags(row.tags),
    icon: row.icon,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

function isUniqueViolation(error: unknown): boolean {
  return error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002';
}

/**
 * 列表的过滤条件（不含分页）。`status` 不在其中：它是派生字段、库里没有这一列
 * （08-agent.md §2），按状态筛选的回落在 service 层做。
 */
export interface AgentListWhere {
  /** 子串匹配 name / id / description 任一（SQLite 的 LIKE 天然 ASCII 大小写不敏感、Unicode 大小写敏感） */
  keyword?: string;
  /** 精确匹配某一个标签（不是子串）：给 profile 前端，不匹配任何标签时返回空页 */
  tag?: string;
  /** 精确匹配所属工作区；给了就只返回该工作区内的行。内置行（source=builtin）不受此限，混入每个列表 */
  workspaceId?: string;
  /** 精确匹配来源；不传 = 两种都要 */
  source?: AgentSource;
}

export interface AgentListFilter extends AgentListWhere {
  page: number;
  pageSize: number;
}

/** 过滤条件 → where。`list` 与 `listAll` 共用，两条查询的口径不能分叉。 */
function whereOf(filter: AgentListWhere): Prisma.AgentWhereInput {
  return {
    // 内置行混进每个列表（含按工作区筛选的查询），所以工作区 scope 是 OR 而不是等值过滤；
    // 顶层 OR 已被 keyword 占用，scope 塞进 AND 里（AND 与顶层条件同层 AND 起来）。
    ...(filter.workspaceId ? { AND: [{ OR: [{ workspaceId: filter.workspaceId }, { source: 'builtin' }] }] } : {}),
    ...(filter.source ? { source: filter.source } : {}),
    // 精确元素匹配：JSON 里每个元素天生被引号夹着，所以补上两侧引号即可，
    // `"天气"` 不会被 `["天气2"]` 命中。service 保证 tag 本身不含引号。
    ...(filter.tag ? { tags: { contains: `"${filter.tag}"` } } : {}),
    ...(filter.keyword
      ? {
          OR: [
            { name: { contains: filter.keyword } },
            { id: { contains: filter.keyword } },
            { description: { contains: filter.keyword } },
          ],
        }
      : {}),
  };
}

export interface AgentCreateData {
  workspaceId: string;
  name: string;
  description: string;
  /** `init.input` 原文；没带 `init` 时传空串（列有默认值，但调用方显式给出更不容易漏） */
  initialInput: string;
  /** `init.attachments` 解析后的真实路径；没带附件时传空数组（同上，显式给出） */
  initialAttachments: string[];
  /** 创建时从 `init.input` 解析出的知识检索 id；没有就传空串（明确「没有」，不是 NULL） */
  knowledgeWorkflowId: string;
  tags: string[];
  icon: string;
}

export interface AgentUpdateData {
  name?: string;
  description?: string;
  tags?: string[];
  icon?: string;
  /** 空串 = 取消知识检索（写成空串而不是 NULL，避免存量推导把它复活） */
  knowledgeWorkflowId?: string;
}

/** 该智能体名下的全部实例 id（development / preview / runtime / evaluation 四态）。 */
async function instanceIdsOf(agentId: string): Promise<string[]> {
  const rows = await prisma.instance.findMany({ where: { agentId }, select: { id: true } });
  return rows.map((row) => row.id);
}

/** 这些实例名下的全部会话 id（含预览实例的，删盘范围与库范围都以它为准）。 */
async function sessionIdsOf(instanceIds: string[]): Promise<string[]> {
  if (instanceIds.length === 0) return [];
  const rows = await prisma.session.findMany({ where: { instanceId: { in: instanceIds } }, select: { id: true } });
  return rows.map((row) => row.id);
}

export const agentsRepo = {
  /**
   * 重名判定交给唯一索引，不做「先查再插」：两段式在并发下有 TOCTOU 窗口，
   * 而这里的 409 是前端「顺位重试」的唯一信号（08-agent.md §6），不能漏也不能误。
   */
  async create(data: AgentCreateData): Promise<AgentRow> {
    const { tags, initialAttachments, ...rest } = data;
    try {
      const row = await prisma.agent.create({
        data: { id: newId('agt'), ...rest, tags: encodeTags(tags), initialAttachments: encodeAttachments(initialAttachments) },
      });
      return toAgentRow(row);
    } catch (error) {
      if (isUniqueViolation(error)) throw new ConflictError(`该工作区已有同名智能体「${data.name}」`, 'error.conflict.agent_name', { name: data.name });
      throw error;
    }
  },

  /**
   * 收养存量目录用：id 由调用方给定（保留原目录名，不重发 uuid），且**不覆盖已有行**。
   *
   * 撞上 id 或 (workspaceId, name) 的唯一约束即返回 null（那颗目录名与同一工作区内的展示名
   * 重复了），由调用方跳过，不让 boot 因为一颗脏目录起不来。
   */
  async insertAdopted(id: string, workspaceId: string, name: string): Promise<AgentRow | null> {
    try {
      const row = await prisma.agent.create({
        data: { id, workspaceId, source: 'user', name, description: '', icon: '' },
      });
      return toAgentRow(row);
    } catch (error) {
      if (isUniqueViolation(error)) return null;
      throw error;
    }
  },

  async findById(id: string): Promise<AgentRow | null> {
    const row = await prisma.agent.findUnique({ where: { id } });
    return row ? toAgentRow(row) : null;
  },

  /**
   * boot seed 用：登记一个内置智能体行（id=定义目录名，workspaceId=null，source='builtin'）。
   *
   * 撞上唯一约束（id 已被占用）返回 null，由调用方告警跳过——不让一颗脏定义目录挡住启动。
   */
  async insertBuiltin(id: string, data: { name: string; description: string; tags: string[]; icon: string }): Promise<AgentRow | null> {
    try {
      const row = await prisma.agent.create({
        data: { id, workspaceId: null, source: 'builtin', ...data, tags: encodeTags(data.tags) },
      });
      return toAgentRow(row);
    } catch (error) {
      if (isUniqueViolation(error)) return null;
      throw error;
    }
  },

  /** 目录已消失的内置行 id（调用方逐个 deleteCascade）。 */
  async findBuiltinNotIn(keepIds: string[]): Promise<string[]> {
    const rows = await prisma.agent.findMany({
      where: { source: 'builtin', id: { notIn: keepIds } },
      select: { id: true },
    });
    return rows.map((row) => row.id);
  },

  async exists(id: string): Promise<boolean> {
    return (await prisma.agent.count({ where: { id } })) > 0;
  },

  /** 排序固定为 updatedAt 降序；并上 id 升序只是为了让同毫秒的行有确定次序，不改变主序。 */
  async list(filter: AgentListFilter): Promise<PageResult<AgentRow>> {
    const where = whereOf(filter);

    const [rows, total] = await Promise.all([
      prisma.agent.findMany({
        where,
        orderBy: [{ updatedAt: 'desc' }, { id: 'asc' }],
        skip: (filter.page - 1) * filter.pageSize,
        take: filter.pageSize,
      }),
      prisma.agent.count({ where }),
    ]);
    return { items: rows.map(toAgentRow), total, page: filter.page, pageSize: filter.pageSize };
  },

  /**
   * 不分页取**全部**匹配行，排序与 `list` 相同。
   *
   * 只给按状态筛选用：status 是现算的派生字段，SQL 里筛不了，只能把候选行全取出来后
   * 在内存里过滤（见 agent.service 的 `listByStatus`）。这里不退化成 `listByWorkspace`：
   * 那个只取 `source=user`，会把内置行漏掉。
   */
  async listAll(filter: AgentListWhere): Promise<AgentRow[]> {
    const rows = await prisma.agent.findMany({
      where: whereOf(filter),
      orderBy: [{ updatedAt: 'desc' }, { id: 'asc' }],
    });
    return rows.map(toAgentRow);
  },

  /**
   * 技能扫描用（10-skill-library.md §4.3）：某工作区全部 `source=user` 智能体。
   *
   * 只读、不分页 —— 扫描要全集；排序键只是让输出稳定，技能接口自己还会再排。
   */
  async listByWorkspace(workspaceId: string): Promise<AgentRow[]> {
    const rows = await prisma.agent.findMany({
      where: { workspaceId, source: 'user' },
      orderBy: [{ updatedAt: 'desc' }, { id: 'asc' }],
    });
    return rows.map(toAgentRow);
  },

  /**
   * 智能体的标签，按 agent 分组返回（每行一个数组）。
   *
   * 只取 `tags` 一列：标签聚合不需要整行，也不需要工作区解析。
   * 去重、计数与排序在 service 层做 —— 那边才认识「一个标签算一次」的口径。
   * `workspaceId` 给了就只取该工作区内智能体的标签（专家页的标签下拉要跟着工作区走）。
   */
  async listTags(workspaceId?: string): Promise<string[][]> {
    const rows = await prisma.agent.findMany({
      // 与 list 同口径：内置行的标签混进每个工作区的下拉
      ...(workspaceId ? { where: { OR: [{ workspaceId }, { source: 'builtin' }] } } : {}),
      select: { tags: true },
    });
    return rows.map((row) => decodeTags(row.tags));
  },

  /**
   * 只改传了的字段。`updatedAt` 显式写死，不依赖 @updatedAt -它是列表的排序键，
   * 刷新这件事不该由 ORM 的隐式行为决定。返回 null 表示行已被并发删掉。
   *
   * 改成一个已被占用的 name 同样撞唯一索引 → 409（「改回自己原来的名字」不算冲突：
   * 值没变就不会触发唯一性检查）。
   */
  async update(id: string, data: AgentUpdateData): Promise<AgentRow | null> {
    const { tags, ...rest } = data;
    try {
      const patch = { ...rest, ...(tags === undefined ? {} : { tags: encodeTags(tags) }), updatedAt: new Date() };
      const { count } = await prisma.agent.updateMany({ where: { id }, data: patch });
      if (count === 0) return null;
    } catch (error) {
      if (isUniqueViolation(error)) throw new ConflictError(`该工作区已有同名智能体「${String(data.name)}」`, 'error.conflict.agent_name', { name: String(data.name) });
      throw error;
    }
    return agentsRepo.findById(id);
  },

  /**
   * 条件更新：只有 `updatedAt` 仍是调用方读到的值时才写。
   *
   * 后台任务（自动命名）用它做乐观并发：生成要几秒，期间用户可能已经手改过元数据 ——
   * 基线不符就一行都不写，返回 null。名字撞唯一索引仍抛 409，由调用方决定改名重试。
   */
  async updateIfUnchanged(id: string, data: AgentUpdateData, expectedUpdatedAt: string): Promise<AgentRow | null> {
    const { tags, ...rest } = data;
    try {
      const patch = { ...rest, ...(tags === undefined ? {} : { tags: encodeTags(tags) }), updatedAt: new Date() };
      const { count } = await prisma.agent.updateMany({
        where: { id, updatedAt: new Date(expectedUpdatedAt) },
        data: patch,
      });
      return count === 0 ? null : agentsRepo.findById(id);
    } catch (error) {
      if (isUniqueViolation(error)) throw new ConflictError(`该工作区已有同名智能体「${String(data.name)}」`, 'error.conflict.agent_name', { name: String(data.name) });
      throw error;
    }
  },

  instanceIdsOf,
  sessionIdsOf,

  /**
   * 删行级联：五张表在同一事务里清掉（零外键，没有数据库级联兜底）。
   *
   * **刻意不删盘** - 「先盘后库」的顺序由 service 负责（08-agent.md §4）：
   * 库删了盘还在，下次启动的收养会把这颗目录登记成新智能体，等于删不掉。
   */
  async deleteCascade(agentId: string): Promise<void> {
    const instanceIds = await instanceIdsOf(agentId);
    const sessionIds = await sessionIdsOf(instanceIds);
    const ids = { in: sessionIds };

    await prisma.$transaction([
      prisma.message.deleteMany({ where: { sessionId: ids } }),
      prisma.run.deleteMany({ where: { sessionId: ids } }),
      prisma.session.deleteMany({ where: { id: ids } }),
      prisma.instance.deleteMany({ where: { id: { in: instanceIds } } }),
      prisma.agent.deleteMany({ where: { id: agentId } }),
    ]);
  },
};
