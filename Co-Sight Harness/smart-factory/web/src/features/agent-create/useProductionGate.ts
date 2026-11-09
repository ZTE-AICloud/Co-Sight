/**
 * 产物状态门禁：进入预览 / 评估之前，先问服务端「生成完了没有」。
 *
 * 判据只有服务端一处（`GET /agents/{id}/production`，契约 4.10）：本 Hook 不做任何
 * 本地推断，只负责取数与翻译错误。`ready === true` 才放行，其余一律把 `reasons`
 * 原样交给调用方展示。
 *
 * ── 为什么「进入时现拉一次」而不是只信缓存 ────────────────────────────────
 *
 * 挂载时拉一次是为了**提前**知道状态（步骤条上能标出哪一阶段还不能进），
 * 但那一条随时会过期：用户可能刚在生成阶段跑完一轮、也可能在另一个标签页里
 * 重新生成了。所以 `check()` 每次进入阶段都**重新请求**，缓存只用于展示。
 *
 * 请求失败按「不放行」处理（fail-closed）：服务端都问不到，进去也只会撞上
 * `messages/send` 的同一道门。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { msg } from '../../i18n/useI18n';
import { agentsApi, isBackendDown } from '../../shared/api/agents';
import type { AgentProduction } from '../../shared/api/agents';
import { ApiError } from '../../shared/api/client';

/** 一次进入判定：放行时带上状态，不放行时带人话原因 */
export type ProductionCheck =
  | { ok: true; snapshot: AgentProduction }
  | { ok: false; reason: string; snapshot: AgentProduction | null };

export interface ProductionGate {
  /** 最近一次读到的状态；null = 还没读到（加载中或失败；失败时按「不可进入」处理） */
  snapshot: AgentProduction | null;
  /** 首次 / 刷新中；`check()` 自己的忙碌不算在内（由调用方单独表示） */
  loading: boolean;
  /** 拉取失败的人话原因；成功为 null */
  error: string | null;
  /** 重新拉一次（展示用），不返回结果 */
  refresh: () => void;
  /** 进入阶段前的权威判定：**总是现拉一次**，不信任缓存 */
  check: () => Promise<ProductionCheck>;
}

/**
 * 智能体生成产物状态。
 *
 * `agentId` 为空（路由异常）时不发请求，直接按「未知」处理。
 */
export function useProductionGate(agentId: string): ProductionGate {
  const [snapshot, setSnapshot] = useState<AgentProduction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** 只让最后一次请求的结果落地：切智能体时旧响应必须丢掉 */
  const requestRef = useRef(0);

  const load = useCallback(async (): Promise<{ snapshot: AgentProduction | null; error: string | null }> => {
    if (agentId === '') return { snapshot: null, error: null };
    const ticket = ++requestRef.current;
    setLoading(true);
    try {
      const result = await agentsApi.production(agentId);
      if (ticket !== requestRef.current) return { snapshot: result, error: null };
      setSnapshot(result);
      setError(null);
      return { snapshot: result, error: null };
    } catch (cause) {
      const message = describeProductionError(cause);
      if (ticket !== requestRef.current) return { snapshot: null, error: message };
      /*
       * 拉失败就**清掉快照**（fail-closed）：准入判据只信服务端，
       * 拿不到就别拿旧值放行 —— 否则后端已挂、旧快照还写着 ready，
       * 用户会被放进一个根本跑不起来的阶段。
       */
      setSnapshot(null);
      setError(message);
      return { snapshot: null, error: message };
    } finally {
      if (ticket === requestRef.current) setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    setSnapshot(null);
    setError(null);
    void load();
    // 卸载 / 换 agentId 后旧请求的结果由 requestRef 挡住
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  const check = useCallback(async (): Promise<ProductionCheck> => {
    const { snapshot: fresh, error: failure } = await load();
    if (failure !== null) {
      return { ok: false, reason: failure, snapshot: fresh };
    }
    if (fresh === null) {
      return { ok: false, reason: msg('create.gate.noProduction'), snapshot: null };
    }
    if (fresh.ready) return { ok: true, snapshot: fresh };
    return { ok: false, reason: notReadyReason(fresh), snapshot: fresh };
  }, [load]);

  return { snapshot, loading, error, refresh, check };
}

/**
 * 不放行时的一句话。
 *
 * 优先用服务端给的 `reasons`（已经是用户语义），只在它为空时兜底 ——
 * 兜底句按 `status` 说，不暴露 gate / step 编号。
 */
function notReadyReason(snapshot: AgentProduction): string {
  const reasons = snapshot.reasons.filter((item) => item.trim() !== '');
  if (reasons.length > 0) return reasons.join(msg('common.clauseSeparator'));

  switch (snapshot.status) {
    case 'not_started':
      return msg('create.gate.notStarted');
    case 'building':
      return msg('create.gate.building');
    case 'blocked':
      return msg('create.gate.blocked');
    case 'failed':
      return msg('create.gate.failed');
    default:
      return msg('create.gate.notReady');
  }
}

/** 取状态失败的人话：后端没起 / 服务端原话 */
function describeProductionError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) {
      return msg('create.gate.localDown');
    }
    return msg('create.gate.readFailedDetail', {
      message: cause.message,
      status: cause.status,
    });
  }
  return cause instanceof Error ? cause.message : msg('create.gate.readFailed');
}
