/**
 * 「观测」模块的重载信号。
 *
 * 与 newChatStore 相同的模式：用户已经在观测页面时再点击「观测」导航项，
 * React Router 不会重新挂载路由，iframe 不会重建。用 nonce 作为 key 的一部分，
 * 递增后触发 iframe 重建，模块重新加载并回到会话列表页。
 */

import { create } from 'zustand';

export interface ObservabilityReloadState {
  /** 每次点击「观测」导航项递增；用作 `ModuleHost` 的 iframe key。 */
  nonce: number;
  /** 请求观测模块重载。 */
  requestReload: () => void;
}

export const useObservabilityReloadStore = create<ObservabilityReloadState>((set) => ({
  nonce: 0,
  requestReload: () => set((state) => ({ nonce: state.nonce + 1 })),
}));
