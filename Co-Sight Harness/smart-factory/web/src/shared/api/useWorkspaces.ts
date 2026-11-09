import { useCallback, useEffect, useRef, useState } from 'react';
import { msg } from '../../i18n/useI18n';
import { ApiError } from './client';
import { workspacesApi } from './workspaces';
import type { WorkspaceSummary } from './workspaces';

/**
 * 框架工作区清单 + 当前生效工作区，供专家页、首页创建与详情弹窗共用。
 *
 * 与 `useModels` 同一套模式（一次请求、`activeId` 同响应返回），但多两件事：
 *
 * 1. **当前工作区是服务端状态，别人也能改。** 切换发生在框架界面，模块收不到通知，
 *    所以窗口重新获得焦点 / 页面重新可见时静默重查一次 —— 否则「界面上显示的工作区」
 *    和「实际生效的工作区」会分叉。
 * 2. **不兜底到第一个工作区。** `activeId` 为空就是 `null`：调用方据此显示
 *    「未选择工作区」并停止取数，而不是悄悄拿 `items[0]` 冒充当前工作区。
 *
 * `activeId` 指向一个列表里不存在的 id（工作区刚被删、库被换过）同样按 `null` 处理；
 * 框架读取端会自愈清指针，这里不替它猜。
 */
export interface UseWorkspacesResult {
  /** 框架当前生效的工作区；没有生效工作区时为 `null` */
  workspace: WorkspaceSummary | null;
  /** 全部工作区。详情弹窗按 id 查名字用 */
  items: WorkspaceSummary[];
  loading: boolean;
  /** 加载失败时的人话；成功为 `null` */
  error: string | null;
  /** 手动重查（错误条上的「重试」、切工作区后主动刷新） */
  refresh: () => void;
}

export function useWorkspaces(): UseWorkspacesResult {
  const [items, setItems] = useState<WorkspaceSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** 只认最后一次请求的响应：聚焦重查与手动刷新可能同时在飞 */
  const requestSeq = useRef(0);

  /**
   * `silent` 用于聚焦重查：不把页面打回加载态，也不清掉已有数据 ——
   * 用户只是切了个窗口，不该看到列表闪一下骨架屏。
   */
  const load = useCallback(async (silent = false) => {
    const seq = ++requestSeq.current;
    if (!silent) {
      setLoading(true);
      setError(null);
    }

    try {
      const result = await workspacesApi.list();
      if (seq !== requestSeq.current) return;
      setItems(result.items);
      setActiveId(result.activeId);
      setError(null);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      // 失败保留上一次的工作区：静默重查失败不该让正在看的列表凭空消失。
      // 首次加载失败时 workspace 本来就是 null，调用方会显示错误条。
      setError(describeWorkspacesError(err));
    } finally {
      // 无论 silent 与否都由**最后一次**请求收尾：初次加载还在飞时若来了一个静默重查，
      // 前者已被序号作废、后者又不负责清加载态，否则 `loading` 会一直停在 true。
      if (seq === requestSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * 框架里切工作区不会通知 iframe，也没有可订阅的事件。
   * 回到本页时重查一次是成本最低的同步方式：窗口聚焦（点进 iframe）或
   * 标签页重新可见都会触发。静默执行，失败也不打扰用户。
   */
  useEffect(() => {
    function recheck(): void {
      if (document.visibilityState === 'hidden') return;
      void load(true);
    }

    window.addEventListener('focus', recheck);
    document.addEventListener('visibilitychange', recheck);
    return () => {
      window.removeEventListener('focus', recheck);
      document.removeEventListener('visibilitychange', recheck);
    };
  }, [load]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  // activeId 指向不存在的项时按「没有当前工作区」处理，不猜 items[0]
  const workspace = activeId === null ? null : (items.find((item) => item.id === activeId) ?? null);

  return { workspace, items, loading, error, refresh };
}

/**
 * 与 `useModels` 的 `describeModelsError` 同源：
 * 请求压根没发出去是本地 dev server / 后端没起；ApiError 则已经是服务端翻译好的人话。
 */
function describeWorkspacesError(err: unknown): string {
  if (err instanceof DOMException && err.name === 'AbortError') {
    return msg('api.workspaceTimeout');
  }
  if (err instanceof TypeError) {
    return msg('api.cannotConnect');
  }
  if (err instanceof ApiError) {
    return msg('api.workspaceLoadFailedDetail', { error: err.message });
  }
  return err instanceof Error
    ? msg('api.workspaceLoadFailedDetail', { error: err.message })
    : msg('api.workspaceLoadFailed');
}
