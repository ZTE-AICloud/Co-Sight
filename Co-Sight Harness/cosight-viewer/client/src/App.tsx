// SPDX-License-Identifier: Apache-2.0
/**
 * @file App.tsx
 * @description 简化版应用路由（仅会话功能 + 宿主挂载时的对话页）
 * 个人模式，固定亮色主题
 */

import { HashRouter, Routes, Route } from "react-router-dom";
import { useCallback } from "react";
import { Layout } from "./components/Layout";
import { Sessions } from "./pages/Sessions";
import { SessionDetail } from "./pages/SessionDetail";
import { ChatPage } from "./pages/ChatPage";
import { NotFound } from "./pages/NotFound";
import { useWebSocket } from "./hooks/useWebSocket";
import { useNotifications } from "./hooks/useNotifications";
import { eventBus } from "./lib/eventBus";
import { applyHostEntry } from "./lib/host-params";
import type { WSMessage } from "./lib/types";

/*
 * 被宿主以 iframe 挂载时，把宿主入口翻译成本模块自己的路由与参数
 * （能力 → 页面；宿主的 `?expert=` → 本模块的 `?agentId=`）。
 *
 * 放在**模块作用域**：`main.tsx` 导入 App 时就会执行，早于 `createRoot(...).render()`
 * 里 HashRouter 的初始化 —— 而渲染后再改地址会被 HashRouter 的地址规范化覆盖
 * （详见 `lib/host-params.ts`）。
 */
applyHostEntry();

export default function App() {
  const onMessage = useCallback((msg: WSMessage) => {
    eventBus.publish(msg);
  }, []);

  const { connected } = useWebSocket(onMessage);
  useNotifications();

  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout wsConnected={connected} />}>
          <Route index element={<Sessions />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="sessions/:id" element={<SessionDetail />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
