import { Prisma, type Session as SessionModel } from '@prisma/client';
import { prisma } from '../prisma/client.js';
import { newId } from '../ids.js';
import { ConflictError } from '../errors.js';
import { ACTIVE_RUN_STATUSES } from './run-status.js';
import type {
  InstanceStage,
  PageResult,
  SessionEffort,
  SessionMode,
  SessionRow,
  SessionStatus,
} from '../types/index.js';

function toSessionRow(row: SessionModel): SessionRow {
  return {
    id: row.id,
    instanceId: row.instanceId,
    name: row.name,
    status: row.status as SessionStatus,
    modelId: row.modelId,
    resumeSessionId: row.resumeSessionId,
    approvalMode: row.mode as SessionMode,
    approvedAll: row.approvedAll,
    effort: row.effort as SessionEffort,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export interface SessionListFilter {
  agentId?: string;
  /** `subjectType=agent`：只要智能体实例的会话（排除自由对话等目录实例）。 */
  agentOnly?: boolean;
  /** 目录会话按实例 cwd 精确匹配；与 agentId / stages 取交集（智能体实例 cwd 为 null，天然不命中）。 */
  cwd?: string;
  /** 阶段集合；与 agentId / instanceId 取交集。 */
  stages?: InstanceStage[];
  instanceId?: string;
  /** 会话状态集合，按 IN 匹配。 */
  statuses?: SessionStatus[];
  /** 会话名子串（SQLite LIKE，ASCII 大小写不敏感）。 */
  name?: string;
  /** 会话 id 集合，按 IN 匹配。 */
  ids?: string[];
  /** 引擎 resume 标识，多值按 IN 过滤；不要求全局唯一。 */
  resumeSessionIds?: string[];
  createdFrom?: Date;
  createdTo?: Date;
  page: number;
  pageSize: number;
}

/** 更新入参用 DTO 字段名；approvalMode 在写库时映射回 mode 列。 */
export interface SessionUpdateData {
  modelId?: string;
  resumeSessionId?: string | null;
  approvalMode?: SessionMode;
  approvedAll?: boolean;
  effort?: SessionEffort;
}

export const sessionsRepo = {
  async create(input: {
    instanceId: string;
    name?: string;
    /** 会话模型必填非空，由上层在入参边界校验。 */
    modelId: string;
    approvalMode?: SessionMode;
    effort?: SessionEffort;
  }): Promise<SessionRow> {
    const row = await prisma.session.create({
      data: {
        id: newId('sess'),
        instanceId: input.instanceId,
        name: input.name ?? '',
        modelId: input.modelId,
        mode: input.approvalMode ?? 'workspace_write',
        effort: input.effort ?? 'high',
      },
    });
    return toSessionRow(row);
  },

  async findById(id: string): Promise<SessionRow | null> {
    const row = await prisma.session.findUnique({ where: { id } });
    return row ? toSessionRow(row) : null;
  },

  /** 可变字段更新：未命中返回 null 由上层转 404（照 agents.repo 的 updateMany 计数写法）。 */
  async update(id: string, data: SessionUpdateData): Promise<SessionRow | null> {
    const { approvalMode, ...rest } = data;
    const { count } = await prisma.session.updateMany({
      where: { id },
      data: { ...rest, ...(approvalMode === undefined ? {} : { mode: approvalMode }) },
    });
    if (count === 0) return null;
    return sessionsRepo.findById(id);
  },

  /**
   * 只在会话名仍为空时写入：引擎标题补名不得覆盖用户/调用方已给的名字。
   *
   * 条件更新是原子的，读改之间的重命名不会被回退；未写入返回 null。
   */
  async nameIfEmpty(id: string, name: string): Promise<SessionRow | null> {
    const { count } = await prisma.session.updateMany({ where: { id, name: '' }, data: { name } });
    return count === 0 ? null : sessionsRepo.findById(id);
  },

  async list(filter: SessionListFilter): Promise<PageResult<SessionRow>> {
    const where: Prisma.SessionWhereInput = {};
    const instanceWhere: Prisma.InstanceWhereInput = {};
    // agentId 是精确定位；subjectType=agent 只是「排除目录实例」（自由对话）
    if (filter.agentId) instanceWhere.agentId = filter.agentId;
    else if (filter.agentOnly) instanceWhere.agentId = { not: null };
    if (filter.cwd) instanceWhere.cwd = filter.cwd;
    if (filter.stages && filter.stages.length > 0) {
      // 存量兼容：2026-10-26 之前目录实例的 stage 是 'dir'，语义已并入 development。
      // 旧库没跑数据订正时，按 development 查要把它一起带上，否则工坊历史会查空。
      const wanted = new Set<string>(filter.stages);
      if (wanted.has('development')) wanted.add('dir');
      instanceWhere.stage = { in: [...wanted] };
    }
    if (Object.keys(instanceWhere).length > 0) {
      const instances = await prisma.instance.findMany({ where: instanceWhere, select: { id: true } });
      const matched = instances.map((i) => i.id);
      // instanceId 与实例级过滤取交集；空交集让 in: [] 自然返回空页
      where.instanceId = { in: filter.instanceId ? matched.filter((id) => id === filter.instanceId) : matched };
    } else if (filter.instanceId) {
      where.instanceId = filter.instanceId;
    }
    if (filter.statuses && filter.statuses.length > 0) where.status = { in: filter.statuses };
    if (filter.name) where.name = { contains: filter.name };
    if (filter.ids && filter.ids.length > 0) where.id = { in: filter.ids };
    if (filter.resumeSessionIds && filter.resumeSessionIds.length > 0) {
      where.resumeSessionId = { in: filter.resumeSessionIds };
    }
    if (filter.createdFrom || filter.createdTo) {
      where.createdAt = {
        ...(filter.createdFrom ? { gte: filter.createdFrom } : {}),
        ...(filter.createdTo ? { lte: filter.createdTo } : {}),
      };
    }

    const [rows, total] = await Promise.all([
      prisma.session.findMany({
        where,
        // 最近有活动的排最前（改名 / 状态变更 / 补 resume 标识都会刷新 updatedAt）；
        // id 只是同毫秒的确定性兜底。
        orderBy: [{ updatedAt: 'desc' }, { id: 'asc' }],
        skip: (filter.page - 1) * filter.pageSize,
        take: filter.pageSize,
      }),
      prisma.session.count({ where }),
    ]);
    return { items: rows.map(toSessionRow), total, page: filter.page, pageSize: filter.pageSize };
  },

  /**
   * 显式级联：数据库层无外键，删会话必须同事务删 message 与 run。
   *
   * 无条件删除，供「刚建但尚未投入使用」的会话清理使用；面向用户的删除走 deleteCascadeIfIdle。
   */
  async deleteCascade(id: string): Promise<void> {
    await prisma.$transaction([
      prisma.message.deleteMany({ where: { sessionId: id } }),
      prisma.run.deleteMany({ where: { sessionId: id } }),
      prisma.session.deleteMany({ where: { id } }),
    ]);
  },

  /**
   * 无活跃 run 才级联删除；检查与删除在同一交互事务里，堵住「检查后 send 新建 run 再被删掉」的窗口。
   *
   * 活跃 run 按任意层级判断（含子 run）：只终止了顶层 run、子 run 仍在跑时也不能删。
   * 有活跃 run 抛 409，调用方先 abort；会话不存在按已删除处理。
   */
  async deleteCascadeIfIdle(id: string): Promise<void> {
    await prisma.$transaction(async (tx) => {
      const session = await tx.session.findUnique({ where: { id }, select: { id: true } });
      if (!session) return;

      const active = await tx.run.findFirst({
        where: { sessionId: id, status: { in: ACTIVE_RUN_STATUSES } },
        select: { id: true },
      });
      if (active) throw new ConflictError(`会话 ${id} 有活跃 run，先 abort 再删`);

      await tx.message.deleteMany({ where: { sessionId: id } });
      await tx.run.deleteMany({ where: { sessionId: id } });
      await tx.session.deleteMany({ where: { id } });
    });
  },

  async markInProgress(id: string): Promise<void> {
    await prisma.session.updateMany({ where: { id }, data: { status: 'in_progress' } });
  },

  /**
   * 收口：无活跃 run 才置 completed。派生判断放在 SQL 里，不做应用层计数。
   *
   * SQLite 的 DateTime 由 Prisma 存成 integer（ms），所以 updated_at 直接写 Date.now()。
   */
  async completeIfNoActiveRun(id: string): Promise<void> {
    await prisma.$executeRawUnsafe(
      `UPDATE sessions SET status = 'completed', updated_at = ?
       WHERE id = ? AND NOT EXISTS (
         SELECT 1 FROM runs WHERE session_id = ? AND status IN ('pending', 'running'))`,
      Date.now(),
      id,
      id,
    );
  },
};
