import { Prisma, type Message as MessageModel } from '@prisma/client';
import { prisma } from '../prisma/client.js';
import { newId } from '../ids.js';
import type {
  ApprovalDecision,
  DecisionSource,
  Message,
  MessageContent,
  MessagePage,
  MessageRole,
  MessageStatus,
  MessageType,
} from '../types/index.js';

function parseContent(raw: string): MessageContent {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as MessageContent) : {};
  } catch {
    return {};
  }
}

function toMessage(row: MessageModel): Message {
  return {
    id: row.id,
    sessionId: row.sessionId,
    runId: row.runId,
    seq: row.seq,
    role: row.role as MessageRole,
    type: row.type as MessageType,
    status: (row.status as MessageStatus | null) ?? null,
    content: parseContent(row.content),
    createdAt: row.createdAt.toISOString(),
  };
}

function isUniqueViolation(error: unknown): boolean {
  if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === 'P2002') return true;
  return error instanceof Error && /UNIQUE constraint failed/i.test(error.message);
}

export interface AppendInput {
  sessionId: string;
  runId?: string | null;
  role: MessageRole;
  type: MessageType;
  status?: MessageStatus | null;
  content?: MessageContent;
}

export interface MessageListFilter {
  sessionId?: string;
  runId?: string;
  afterSeq?: number;
  beforeSeq?: number;
  limit: number;
  status?: MessageStatus;
}

export interface SettlePatch {
  status: MessageStatus;
  content: Partial<MessageContent> & { decision?: ApprovalDecision; decisionSource?: DecisionSource };
}

export const messagesRepo = {
  /**
   * 追加一条消息：同一事务内 `MAX(seq)+1`，撞唯一约束重试一次。
   *
   * SQLite 单写者串行化保证不冲突，重试只是兜底。
   * 迁到 Postgres 时应改用 sequence。
   */
  async append(input: AppendInput): Promise<Message> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await prisma.$transaction(async (tx) => {
          const agg = await tx.message.aggregate({ where: { sessionId: input.sessionId }, _max: { seq: true } });
          const row = await tx.message.create({
            data: {
              id: newId('msg'),
              sessionId: input.sessionId,
              runId: input.runId ?? null,
              seq: (agg._max.seq ?? 0) + 1,
              role: input.role,
              type: input.type,
              status: input.status ?? null,
              content: JSON.stringify(input.content ?? {}),
            },
          });
          return toMessage(row);
        });
      } catch (error) {
        if (!isUniqueViolation(error) || attempt === 1) throw error;
      }
    }
    throw new Error('消息 seq 分配失败：唯一约束连续冲突');
  },

  async findById(id: string): Promise<Message | null> {
    const row = await prisma.message.findUnique({ where: { id } });
    return row ? toMessage(row) : null;
  },

  /** 会话消息总数：history 的 total 口径，不区分状态与类型。 */
  async countBySession(sessionId: string): Promise<number> {
    return prisma.message.count({ where: { sessionId } });
  },

  /** 批量统计消息数：会话列表按页取 id 后一次 groupBy，缺省由调用方补 0。 */
  async countBySessions(sessionIds: string[]): Promise<Map<string, number>> {
    if (sessionIds.length === 0) return new Map();
    const rows = await prisma.message.groupBy({
      by: ['sessionId'],
      where: { sessionId: { in: sessionIds } },
      _count: { _all: true },
    });
    return new Map(rows.map((row) => [row.sessionId, row._count._all]));
  },

  /**
   * 批量取每个会话最新一条 type='text' 消息的 content.text。
   *
   * 先 groupBy 拿到各会话的最大 seq，再按 (sessionId, seq) 回表；
   * content.text 不是字符串时该会话记 null。
   */
  async lastTextBySession(sessionIds: string[]): Promise<Map<string, string | null>> {
    if (sessionIds.length === 0) return new Map();
    const latest = await prisma.message.groupBy({
      by: ['sessionId'],
      where: { sessionId: { in: sessionIds }, type: 'text' },
      _max: { seq: true },
    });
    if (latest.length === 0) return new Map();
    const rows = await prisma.message.findMany({
      where: { OR: latest.map((row) => ({ sessionId: row.sessionId, seq: row._max.seq ?? -1 })) },
      select: { sessionId: true, content: true },
    });
    return new Map(
      rows.map((row) => {
        const content = parseContent(row.content) as { text?: unknown };
        return [row.sessionId, typeof content.text === 'string' ? content.text : null];
      }),
    );
  },

  /**
   * 批量取每个会话第一条 role='user' 且 type='text' 消息的 content.text。
   *
   * 与 lastTextBySession 对称：先 groupBy 拿到各会话的最小 seq，再按 (sessionId, seq) 回表；
   * 没有符合条件的消息、或 content.text 不是字符串时该会话不出现在 Map 里 / 记 null。
   */
  async firstTextBySession(sessionIds: string[]): Promise<Map<string, string | null>> {
    if (sessionIds.length === 0) return new Map();
    const earliest = await prisma.message.groupBy({
      by: ['sessionId'],
      where: { sessionId: { in: sessionIds }, role: 'user', type: 'text' },
      _min: { seq: true },
    });
    if (earliest.length === 0) return new Map();
    const rows = await prisma.message.findMany({
      where: { OR: earliest.map((row) => ({ sessionId: row.sessionId, seq: row._min.seq ?? -1 })) },
      select: { sessionId: true, content: true },
    });
    return new Map(
      rows.map((row) => {
        const content = parseContent(row.content) as { text?: unknown };
        return [row.sessionId, typeof content.text === 'string' ? content.text : null];
      }),
    );
  },

  /**
   * seq 升序返回一段窗口。
   *
   * - 给 `afterSeq`：其后最旧的 limit 条
   * - 给 `beforeSeq`：其前最近的 limit 条（倒序取再翻回升序）
   * - 都不给：最旧的 limit 条
   * - 两者同给：以 afterSeq 为准（调用方应先拒绝这种组合）
   *
   * `nextAfterSeq` 为窗口末条的 seq，仅在窗口取满 limit 条时非 null——客户端用它续拉新消息。
   */
  async list(filter: MessageListFilter): Promise<MessagePage> {
    const where: Prisma.MessageWhereInput = {};
    if (filter.sessionId) where.sessionId = filter.sessionId;
    if (filter.runId) where.runId = filter.runId;
    if (filter.status) where.status = filter.status;
    if (filter.afterSeq !== undefined) where.seq = { gt: filter.afterSeq };
    else if (filter.beforeSeq !== undefined) where.seq = { lt: filter.beforeSeq };

    const backwards = filter.afterSeq === undefined && filter.beforeSeq !== undefined;
    const rows = await prisma.message.findMany({
      where,
      orderBy: { seq: backwards ? 'desc' : 'asc' },
      take: filter.limit,
    });
    if (backwards) rows.reverse();

    const last = rows.at(-1);
    return {
      items: rows.map(toMessage),
      nextAfterSeq: rows.length === filter.limit && last ? last.seq : null,
    };
  },

  /**
   * 按偏移取最近一段：从最新往前跳 offset 条，取 limit 条后翻回 seq 升序。
   *
   * WS `history` 用：客户端按「最近若干条 + 跳过条数」取数，与游标分页互补。
   */
  async listRecent(input: { sessionId: string; limit: number; offset: number }): Promise<Message[]> {
    const rows = await prisma.message.findMany({
      where: { sessionId: input.sessionId },
      orderBy: { seq: 'desc' },
      skip: input.offset,
      take: input.limit,
    });
    return rows.reverse().map(toMessage);
  },

  /** 按 toolCallId 找待应答的交互消息：挂起天然很少，扫一遍 pending 后解析 content。 */
  async findPendingInteractiveByToolCallId(toolCallId: string): Promise<Message | null> {
    const rows = await prisma.message.findMany({
      where: { type: 'tool_interactive', status: 'pending' },
      orderBy: { seq: 'desc' },
    });
    for (const row of rows) {
      if ((parseContent(row.content) as { toolCallId?: unknown }).toolCallId === toolCallId) return toMessage(row);
    }
    return null;
  },

  /**
   * 结算挂起：条件更新抢仲裁，受影响 1 行者胜；0 行说明已结算（或不存在）。
   *
   * 内容在这里合并——先读后写不构成竞态，因为仲裁由 `WHERE status='pending'` 完成。
   */
  async settlePending(id: string, patch: SettlePatch): Promise<Message | null> {
    const row = await prisma.message.findUnique({ where: { id } });
    if (!row) return null;

    const content = { ...parseContent(row.content), ...patch.content };
    const res = await prisma.message.updateMany({
      where: { id, status: 'pending' },
      data: { status: patch.status, content: JSON.stringify(content) },
    });
    if (res.count === 0) return null;
    return toMessage({ ...row, status: patch.status, content: JSON.stringify(content) });
  },

  /** 该 run 的最后一条消息（seq 最大）；失败收口用它判断引擎是否已落过同一个错误。 */
  async lastByRun(runId: string): Promise<Message | null> {
    const row = await prisma.message.findFirst({ where: { runId }, orderBy: { seq: 'desc' } });
    return row ? toMessage(row) : null;
  },

  /** 中止给定 run 集合的全部挂起（顶层及其子 run），返回被结算掉的行（供广播）。 */
  async abortPendingByRuns(
    runIds: string[],
    source: Exclude<DecisionSource, 'user' | 'approved_all_auto'>,
  ): Promise<Message[]> {
    if (runIds.length === 0) return [];
    const rows = await prisma.message.findMany({ where: { runId: { in: runIds }, status: 'pending' } });
    return abortRows(rows, source);
  },

  /** 删除一条消息：终态守卫的收口窗口内误落的写入由调用方撤回。 */
  async remove(id: string): Promise<void> {
    await prisma.message.deleteMany({ where: { id } });
  },

  /** 中止该会话的全部挂起（含子 run），返回被结算掉的行（供广播）。 */
  async abortPendingBySession(
    sessionId: string,
    source: Exclude<DecisionSource, 'user' | 'approved_all_auto'>,
  ): Promise<Message[]> {
    const rows = await prisma.message.findMany({ where: { sessionId, status: 'pending' } });
    return abortRows(rows, source);
  },

  /** 启动 / 关闭收口：扫一遍残留 pending（不限 run）。 */
  async abortAllPending(source: Exclude<DecisionSource, 'user' | 'approved_all_auto'>): Promise<Message[]> {
    const rows = await prisma.message.findMany({ where: { status: 'pending' } });
    return abortRows(rows, source);
  },
};

async function abortRows(rows: MessageModel[], source: DecisionSource): Promise<Message[]> {
  const settled: Message[] = [];
  for (const row of rows) {
    const content = {
      ...parseContent(row.content),
      decisionSource: source,
      ...(row.type === 'approval' ? { decision: 'aborted' as const } : {}),
    };
    const res = await prisma.message.updateMany({
      where: { id: row.id, status: 'pending' },
      data: { status: 'aborted', content: JSON.stringify(content) },
    });
    if (res.count === 1) settled.push(toMessage({ ...row, status: 'aborted', content: JSON.stringify(content) }));
  }
  return settled;
}
