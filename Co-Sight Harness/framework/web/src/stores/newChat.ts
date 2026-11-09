/**
 * 「新建对话」的重建信号（D6 = A：Zustand，仅客户端状态）。
 *
 * 为什么需要它：对话能力挂在宿主首页路由 `/` 上。用户已经在对话中时再点
 * 「新建对话」，导航到同一个 location，React Router 不会重新挂载路由元素，
 * 对话模块的 iframe 也就既不重建、也不刷新——表现为“点了没反应”。
 *
 * 这里用一个只增不减的 nonce 作为该 iframe 的 key：点击时递增，`ModuleHost`
 * 观察到 key 变化后销毁旧 iframe、建新的，模块因此重新加载并回到空态。
 *
 * 不持久化：它是“这一屏上的一次动作”，刷新页面后没有必要保留。
 */

import { create } from 'zustand';

export interface NewChatState {
  /** 每次点击「新建对话」递增；仅用作 `ModuleHost` 的 iframe key。 */
  nonce: number;
  /** 请求对话模块重建（回到空态）。 */
  requestNewChat: () => void;
}

export const useNewChatStore = create<NewChatState>((set) => ({
  nonce: 0,
  requestNewChat: () => set((state) => ({ nonce: state.nonce + 1 })),
}));
