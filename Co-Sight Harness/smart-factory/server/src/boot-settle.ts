import { prisma } from './shared/prisma/client.js';
import { messagesRepo } from './shared/store/messages.repo.js';
import { runsRepo } from './shared/store/runs.repo.js';
import { sessionsRepo } from './shared/store/sessions.repo.js';

/**
 * 启动收口：重启不续跑。
 *
 * 孤儿 run 置 failed、残留挂起置 aborted，再把全部 `in_progress` 会话重算一遍：
 * 重算面只取刚置 failed 的 run 会漏掉「run 已条件落终态、会话还没重算」的残留。
 */
export async function settleOnBoot(): Promise<void> {
  const affected = await runsRepo.failAllActiveRuns();
  const aborted = await messagesRepo.abortAllPending('restart');
  const inProgress = await prisma.session.findMany({ where: { status: 'in_progress' }, select: { id: true } });
  // 派生收口逐条走 completeIfNoActiveRun，判断只有一处
  for (const session of inProgress) {
    await sessionsRepo.completeIfNoActiveRun(session.id);
  }
  if (affected.length > 0 || aborted.length > 0 || inProgress.length > 0) {
    console.log(
      `[smart-factory] 启动收口：${affected.length} 个会话的活跃 run 置 failed，挂起消息 ${aborted.length} 条置 aborted，重算会话 ${inProgress.length} 个`,
    );
  }
}
