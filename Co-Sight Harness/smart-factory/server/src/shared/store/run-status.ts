import type { AgentRunStatus } from '../types/index.js';

/** 活跃 = 还没落到终态；run 仲裁与部分唯一索引都按这两个状态判定。 */
export const ACTIVE_RUN_STATUSES: AgentRunStatus[] = ['pending', 'running'];
