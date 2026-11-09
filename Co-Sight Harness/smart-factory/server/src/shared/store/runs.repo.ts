import { Prisma, type Run as RunModel } from '@prisma/client';
import { prisma } from '../prisma/client.js';
import { newId } from '../ids.js';
import { BadRequestError, ConflictError, NotFoundError } from '../errors.js';
import type { AgentRunStatus, RunRow } from '../types/index.js';
import { ACTIVE_RUN_STATUSES } from './run-status.js';

/**
 * 跨阶段守卫文案：development 与兄弟阶段共用，避免调用方逐字重复。
 *
 * runtimeBusy：development 起跑时 runtime 仍有活跃 run（两者共享 development 产物树）。
 * developmentBusy：preview / runtime / evaluation 起跑时 development 仍在重新生成（源快照不稳定）。
 */
export const STAGE_GUARD_MESSAGES = {
  runtimeBusy: '智能体正在运行，请等待运行结束再重新生成',
  developmentBusy: '智能体正在重新生成，请等待本次运行结束再进入该阶段',
} as const;

/** findRoot 的最大上溯层数：防脏数据成环导致死循环。 */
const MAX_ROOT_HOPS = 64;

function toRunRow(row: RunModel): RunRow {
  return {
    id: row.id,
    sessionId: row.sessionId,
    instanceId: row.instanceId,
    parentRunId: row.parentRunId,
    parentToolUseId: row.parentToolUseId,
    subagentType: row.subagentType,
    delegationDepth: row.delegationDepth,
    taskId: row.taskId,
    status: row.status as AgentRunStatus,
    error: row.error,
    startedAt: row.startedAt?.toISOString() ?? null,
    finishedAt: row.finishedAt?.toISOString() ?? null,
    createdAt: row.createdAt.toISOString(),
  };
}

/** P2002 是 Prisma 映射的唯一约束冲突；部分唯一索引未必被 Prisma 识别，所以再看消息。 */
function isUniqueViolation(error: unknown): boolean {
  if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002') return true;
  return error instanceof Error && /UNIQUE constraint failed/i.test(error.message);
}

export const runsRepo = {
  /**
   * 起一个活跃顶层 run：事务内校验会话与实例仍存在，再按粒度仲裁，另有部分唯一索引兜底。
   *
   * 跨阶段守卫也在这个事务里：development 与其它阶段读写同一 agentRoot，
   * 任一侧有活跃 run（任意层级）时另一侧不得起跑。runtime 与 development 共享产物树，
   * preview / evaluation 又把 development 的产物当源快照，重新生成期间两者都不稳定。
   * resolveRunSetup 的预检只是快速失败，事务内判断才是权威，堵住「两边预检都通过」的窗口。
   * 任何 stage 都先查同 session 的活跃顶层 run；非 runtime stage 再查同 instance 的。
   * runtime 允许同 instance 的不同 session 并行，但同 session 仍串行。
   * 同 session / 同 instance 的仲裁只看顶层 run（parentRunId 为 null）；子 run 由 createSubRun 直插，不参与这里。
   * 跨阶段兄弟检查则看任意层级：顶层已终态、子 run 尚未收敛时也不能放行。
   * 会话校验与「删会话的检查」串行化在各自事务里，挡住删会话与起 run 交错留下无主 run 的窗口。
   * 活跃 run 冲突转成 409，调用方先 abort 或等它结束；索引兜底时只复判会话粒度，
   * 命中给会话文案，否则给通用冲突文案。
   *
   * 默认以 `pending` 起步；调用方已把起跑条件解析完时可直接以 `running` 起步，此时记 startedAt。
   */
  async createActiveRun(input: {
    sessionId: string;
    instanceId: string;
    status?: 'pending' | 'running';
  }): Promise<RunRow> {
    const status = input.status ?? 'pending';
    try {
      return await prisma.$transaction(async (tx) => {
        const session = await tx.session.findUnique({
          where: { id: input.sessionId },
          select: { id: true, instanceId: true },
        });
        if (!session) throw new NotFoundError(`会话 ${input.sessionId}`, 'error.not_found.session', { sessionId: input.sessionId });
        if (session.instanceId !== input.instanceId) throw new BadRequestError('会话与实例不匹配');

        const instance = await tx.instance.findUnique({
          where: { id: input.instanceId },
          select: { id: true, agentId: true, stage: true },
        });
        if (!instance) throw new NotFoundError(`实例 ${input.instanceId}`, 'error.not_found.instance', { instanceId: input.instanceId });

        const siblingStage = instance.stage === 'development' ? 'runtime' : 'development';
        // 目录实例（agentId 为 null）没有跨阶段兄弟，直接跳过；实例级仲裁由下面的非 runtime 分支兜住
        const sibling = instance.agentId === null ? null : await tx.instance.findUnique({
          where: { agentId_stage: { agentId: instance.agentId, stage: siblingStage } },
          select: { id: true },
        });
        if (sibling) {
          const inSibling = await tx.run.findFirst({
            where: { instanceId: sibling.id, status: { in: ACTIVE_RUN_STATUSES } },
            select: { id: true },
          });
          if (inSibling) {
            throw new ConflictError(
              instance.stage === 'development' ? STAGE_GUARD_MESSAGES.runtimeBusy : STAGE_GUARD_MESSAGES.developmentBusy,
            );
          }
        }

        const inSession = await tx.run.findFirst({
          where: { sessionId: input.sessionId, parentRunId: null, status: { in: ACTIVE_RUN_STATUSES } },
          select: { id: true },
        });
        if (inSession) throw new ConflictError(`会话 ${input.sessionId} 已有活跃 run`, 'error.conflict.active_run', { sessionId: input.sessionId });

        if (instance.stage !== 'runtime') {
          const inInstance = await tx.run.findFirst({
            where: { instanceId: input.instanceId, parentRunId: null, status: { in: ACTIVE_RUN_STATUSES } },
            select: { id: true },
          });
          if (inInstance) throw new ConflictError(`实例 ${input.instanceId} 已有活跃 run`, 'error.conflict.active_run', { instanceId: input.instanceId });
        }

        const row = await tx.run.create({
          data: {
            id: newId('run'),
            sessionId: input.sessionId,
            instanceId: input.instanceId,
            stage: instance.stage,
            status,
            ...(status === 'running' ? { startedAt: new Date() } : {}),
          },
        });
        return toRunRow(row);
      });
    } catch (error) {
      if (isUniqueViolation(error)) {
        // 索引兜底：只按会话粒度复判；没有命中就不再猜是实例冲突。
        const inSession = await prisma.run.findFirst({
          where: { sessionId: input.sessionId, parentRunId: null, status: { in: ACTIVE_RUN_STATUSES } },
          select: { id: true },
        });
        throw new ConflictError(inSession ? `会话 ${input.sessionId} 已有活跃 run` : '活跃 run 冲突', 'error.conflict.active_run');
      }
      throw error;
    }
  },

  /**
   * 落一个子 run：直接以 running 起步并记 startedAt，不经过活跃仲裁（同一父 run 下可并存多个）。
   * 会话与实例归属由调用方从父 run 继承；parentRunId 必须已解析到顶层或上层 run。
   * 子 run 不参与部分唯一索引，但 stage 列必填，从 instance 抄一份。
   */
  async createSubRun(input: {
    sessionId: string;
    instanceId: string;
    parentRunId: string;
    parentToolUseId?: string | null;
    subagentType?: string | null;
    delegationDepth: number;
    taskId?: string | null;
  }): Promise<RunRow> {
    const instance = await prisma.instance.findUnique({ where: { id: input.instanceId }, select: { stage: true } });
    if (!instance) throw new NotFoundError(`实例 ${input.instanceId}`, 'error.not_found.instance', { instanceId: input.instanceId });

    const row = await prisma.run.create({
      data: {
        id: newId('run'),
        sessionId: input.sessionId,
        instanceId: input.instanceId,
        stage: instance.stage,
        parentRunId: input.parentRunId,
        parentToolUseId: input.parentToolUseId ?? null,
        subagentType: input.subagentType ?? null,
        delegationDepth: input.delegationDepth,
        taskId: input.taskId ?? null,
        status: 'running',
        startedAt: new Date(),
      },
    });
    return toRunRow(row);
  },

  async findById(id: string): Promise<RunRow | null> {
    const row = await prisma.run.findUnique({ where: { id } });
    return row ? toRunRow(row) : null;
  },

  /** 会话下任意层级的活跃 run（含子 run）。 */
  async findActiveBySession(sessionId: string): Promise<RunRow | null> {
    const row = await prisma.run.findFirst({ where: { sessionId, status: { in: ACTIVE_RUN_STATUSES } } });
    return row ? toRunRow(row) : null;
  },

  /** 只查会话的活跃顶层 run（parentRunId 为 null）；session 级唯一索引锁的就是它。 */
  async findActiveTopBySession(sessionId: string): Promise<RunRow | null> {
    const row = await prisma.run.findFirst({ where: { sessionId, parentRunId: null, status: { in: ACTIVE_RUN_STATUSES } } });
    return row ? toRunRow(row) : null;
  },

  async findActiveByInstance(instanceId: string): Promise<RunRow | null> {
    const row = await prisma.run.findFirst({ where: { instanceId, status: { in: ACTIVE_RUN_STATUSES } } });
    return row ? toRunRow(row) : null;
  },

  /** 这些实例里是否有活跃 run（阶段门禁 / 产物判读用）。 */
  async hasActiveIn(instanceIds: string[]): Promise<boolean> {
    if (instanceIds.length === 0) return false;
    const row = await prisma.run.findFirst({
      where: { instanceId: { in: instanceIds }, status: { in: ACTIVE_RUN_STATUSES } },
      select: { id: true },
    });
    return row !== null;
  },

  /**
   * 批量版：这些实例里**各自**是否有活跃 run（列表算 `status=building` 用）。
   * 与 `hasActiveIn` 的区别是逐实例返回，不能把「有一个在跑」套到整页。
   */
  async activeInstanceIds(instanceIds: string[]): Promise<Set<string>> {
    if (instanceIds.length === 0) return new Set();
    const rows = await prisma.run.findMany({
      where: { instanceId: { in: instanceIds }, status: { in: ACTIVE_RUN_STATUSES } },
      select: { instanceId: true },
      distinct: ['instanceId'],
    });
    return new Set(rows.map((row) => row.instanceId));
  },

  /**
   * 删智能体前要停掉的那批 run：这些实例下的**活跃顶层 run**（子 run 由 `abortRun` 沿血缘收敛）。
   *
   * 只取顶层：一个会话至多一条活跃顶层 run（session 级唯一索引），中止它即中止整棵 run 树。
   */
  async listActiveTopByInstances(instanceIds: string[]): Promise<RunRow[]> {
    if (instanceIds.length === 0) return [];
    const rows = await prisma.run.findMany({
      where: { instanceId: { in: instanceIds }, parentRunId: null, status: { in: ACTIVE_RUN_STATUSES } },
      orderBy: [{ createdAt: 'asc' }, { id: 'asc' }],
    });
    return rows.map(toRunRow);
  },

  /** 会话的 run 列表只看顶层 run；子 run 走 listChildren。 */
  async listBySession(sessionId: string, page: number, pageSize: number): Promise<{ items: RunRow[]; total: number }> {
    const where = { sessionId, parentRunId: null };
    const [rows, total] = await Promise.all([
      prisma.run.findMany({ where, orderBy: { createdAt: 'desc' }, skip: (page - 1) * pageSize, take: pageSize }),
      prisma.run.count({ where }),
    ]);
    return { items: rows.map(toRunRow), total };
  },

  /** 某 run 的直接子 run：startedAt 升序，id 兜底同毫秒顺序。 */
  async listChildren(parentRunId: string, page: number, pageSize: number): Promise<{ items: RunRow[]; total: number }> {
    const where = { parentRunId };
    const [rows, total] = await Promise.all([
      prisma.run.findMany({
        where,
        orderBy: [{ startedAt: 'asc' }, { id: 'asc' }],
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
      prisma.run.count({ where }),
    ]);
    return { items: rows.map(toRunRow), total };
  },

  /**
   * 沿 parentRunId 上溯到顶层 run。
   *
   * run 本身不存在返回 null；链路断开或超过最大层数（脏数据成环）时退回原 run。
   */
  async findRoot(runId: string): Promise<RunRow | null> {
    const origin = await prisma.run.findUnique({ where: { id: runId } });
    if (!origin) return null;

    let current = origin;
    for (let hops = 0; hops < MAX_ROOT_HOPS; hops += 1) {
      if (!current.parentRunId) return toRunRow(current);
      const parent = await prisma.run.findUnique({ where: { id: current.parentRunId } });
      if (!parent) return toRunRow(origin);
      current = parent;
    }
    return toRunRow(origin);
  },

  async markRunning(id: string): Promise<boolean> {
    const res = await prisma.run.updateMany({
      where: { id, status: 'pending' },
      data: { status: 'running', startedAt: new Date() },
    });
    return res.count === 1;
  },

  /** 终态守卫：条件更新，受影响行数为 0 即已终态（重放幂等）。 */
  async finish(id: string, status: 'succeeded' | 'failed' | 'aborted', error?: string): Promise<boolean> {
    const res = await prisma.run.updateMany({
      where: { id, status: { in: ACTIVE_RUN_STATUSES } },
      data: { status, error: error ?? null, finishedAt: new Date() },
    });
    return res.count === 1;
  },

  /**
   * 中止该 run 血缘下（任意层级）仍活跃的子 run，返回本次真正落终态的行供广播 task.notified。
   *
   * 逐行条件更新并检查受影响行数：与 `finish` 并发时，已由别的路径落终态的行不会被当成 aborted 返回。
   * 血缘按 parentRunId 遍历全部后代（含已终态中间节点下的活跃孙 run），不按 session 扫描。
   */
  async abortActiveDescendants(rootRunId: string): Promise<RunRow[]> {
    const pending = [rootRunId];
    const seen = new Set<string>([rootRunId]);
    const active: RunModel[] = [];
    while (pending.length > 0) {
      const parents = pending.splice(0);
      const rows = await prisma.run.findMany({ where: { parentRunId: { in: parents } } });
      for (const row of rows) {
        if (seen.has(row.id)) continue;
        seen.add(row.id);
        pending.push(row.id);
        if (row.status === 'pending' || row.status === 'running') active.push(row);
      }
    }

    const aborted: RunRow[] = [];
    for (const row of active) {
      if (!(await this.finish(row.id, 'aborted'))) continue;
      aborted.push(toRunRow({ ...row, status: 'aborted', finishedAt: new Date() }));
    }
    return aborted;
  },

  /** 启动收口：所有活跃 run 置 failed，返回需要重算状态的会话 id。 */
  async failAllActiveRuns(): Promise<string[]> {
    const rows = await prisma.run.findMany({ where: { status: { in: ACTIVE_RUN_STATUSES } }, select: { id: true, sessionId: true } });
    if (rows.length === 0) return [];
    await prisma.run.updateMany({
      where: { id: { in: rows.map((r) => r.id) } },
      data: { status: 'failed', error: '服务重启', finishedAt: new Date() },
    });
    return [...new Set(rows.map((r) => r.sessionId))];
  },

  /** 派生的挂起信息：该 run 下等待应答的 approval / tool_interactive 条数与最早一条的时间。 */
  async waitingOf(runId: string): Promise<{ count: number; since: string } | null> {
    const map = await this.waitingByRunIds([runId]);
    return map.get(runId) ?? null;
  },

  /** 批量版：避免按 run 逐条查询。 */
  async waitingByRunIds(runIds: string[]): Promise<Map<string, { count: number; since: string }>> {
    if (runIds.length === 0) return new Map();

    const rows = await prisma.message.findMany({
      where: { runId: { in: runIds }, status: 'pending', type: { in: ['approval', 'tool_interactive'] } },
      select: { runId: true, createdAt: true },
    });

    const acc = new Map<string, { count: number; earliest: Date }>();
    for (const row of rows) {
      if (!row.runId) continue;
      const current = acc.get(row.runId);
      if (current) {
        current.count += 1;
        if (row.createdAt < current.earliest) current.earliest = row.createdAt;
      } else {
        acc.set(row.runId, { count: 1, earliest: row.createdAt });
      }
    }

    return new Map([...acc].map(([id, value]) => [id, { count: value.count, since: value.earliest.toISOString() }]));
  },
};
