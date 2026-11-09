/**
 * 评估右栏的数据来源：`/evaluations/*` 归一化端点的取数与刷新时机。
 *
 * 刷新时机（4.09 §8）：
 * - 进阶段 / 换智能体：拉一次；
 * - 换了一场会话（「重新评估」新建的）：重拉 —— 服务端在建会话时已连同沙箱把旧报告
 *   删掉（`sessions/create` 的 `resetSandbox`），这时拉回来的空页才是对的；
 * - 评估会话的 run 从「在跑」变「终态」：重拉（run 结束 = 报告可能多了新内容）；
 * - 评估会话在跑、或报告 status === 'running'：每 3 秒轮询 —— 一轮评估中途会新建
 *   报告目录，只靠终态边沿会一直停在旧报告上（报告文件是覆盖写，重复拉无副作用）。
 *
 * 「报告 = list 的 items[0]」：列表按 reportId 降序，第一份就是最新一轮。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { msg } from '../../i18n/useI18n';
import { evaluationsApi } from '../../shared/api/evaluations';
import type { EvaluationCaseSummary, EvaluationReportDetail } from '../../shared/api/evaluations';

export interface EvalResults {
  /** 最新一份报告的完整概览；还没有任何报告时为 null */
  report: EvaluationReportDetail | null;
  /** 这份报告的用例摘要（index 升序，整页取回） */
  cases: EvaluationCaseSummary[];
  loading: boolean;
  /** 取数失败的人话原因；空页不是错误（还没评过） */
  error: string | null;
  /** 手动重拉（「修复」发出新 run 后也走 running 边沿自动刷新） */
  reload: () => void;
  /** 「重新评估」点击时立刻清空：旧报告马上会被服务端随沙箱一起删掉 */
  reset: () => void;
}

const POLL_MS = 3000;

export function useEvalResults(agentId: string, running: boolean, sessionId = ''): EvalResults {
  const [report, setReport] = useState<EvaluationReportDetail | null>(null);
  const [cases, setCases] = useState<EvaluationCaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** run 状态边沿：true→false 的那一次才触发重拉，不是「不在跑」就一直拉 */
  const prevRunningRef = useRef(false);
  /** 只认最后一次请求的响应：切智能体时旧请求可能还在飞 */
  const requestSeq = useRef(0);
  /** 上一次 load 针对的智能体：换人时先清空，别在加载期间继续显示上一份报告 */
  const loadedAgentRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    if (agentId === '') {
      // 让还在飞的旧请求作废，不要回头把别人的报告写进空态
      requestSeq.current += 1;
      return;
    }
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    if (loadedAgentRef.current !== agentId) {
      loadedAgentRef.current = agentId;
      setReport(null);
      setCases([]);
      setError(null);
      setLoading(true);
    }
    try {
      const listed = await evaluationsApi.list(agentId, undefined, 1, 1);
      if (seq !== requestSeq.current) return;
      const latest = listed.items[0];
      if (latest === undefined) {
        setReport(null);
        setCases([]);
        setError(null);
        return;
      }
      const [detail, casePage] = await Promise.all([
        evaluationsApi.detail(agentId, latest.reportId),
        evaluationsApi.casesList(agentId, latest.reportId, { page: 1, pageSize: 200 }),
      ]);
      if (seq !== requestSeq.current) return;
      setReport(detail);
      setCases(casePage.items);
      setError(null);
    } catch (cause) {
      if (seq !== requestSeq.current) return;
      setError(cause instanceof Error ? cause.message : msg('eval.loadFailed'));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  /*
   * 新一场会话开好之后重拉（「重新评估」会新建会话，服务端已经删掉旧沙箱与旧报告）。
   * 会话为空（连接 / 正在准备）时不拉：那一段旧报告可能还没删，拉回来只会把
   * 刚清空的右栏又贴回旧数据。
   */
  useEffect(() => {
    if (sessionId !== '') void load();
  }, [sessionId, load]);

  useEffect(() => {
    const finished = prevRunningRef.current && !running;
    prevRunningRef.current = running;
    if (finished) void load();
  }, [running, load]);

  /*
   * 评估会话在跑的时候轮询：一轮评估会在中途新建 run 目录，光靠「run 结束」的边沿
   * 要等整轮跑完才看得到它——右侧会一直停在上一份报告（或空态）。报告本身还在
   * 写（status === 'running'）时也要继续轮询。
   */
  useEffect(() => {
    if (!running && report?.status !== 'running') return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, report?.status, load]);

  /** 「重新评估」：旧一轮报告已作废，先清空右栏，等新会话开好再重拉 */
  const reset = useCallback(() => {
    // 在途的旧请求作废，别把刚清掉的报告又写回来
    requestSeq.current += 1;
    setReport(null);
    setCases([]);
    setError(null);
    setLoading(false);
  }, []);

  return { report, cases, loading, error, reload: load, reset };
}
