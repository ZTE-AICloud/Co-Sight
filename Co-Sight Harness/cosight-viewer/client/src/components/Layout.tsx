// SPDX-License-Identifier: Apache-2.0
/**
 * @file Layout.tsx
 * @description 主布局组件 - 仅页面内容区
 */

import { Outlet } from "react-router-dom";
import { UpdateNotifier } from "./UpdateNotifier";

interface LayoutProps {
  wsConnected: boolean;
}

/**
 * 简化布局：仅内容区，无侧边栏、无顶部导航
 */
export function Layout({ wsConnected: _wsConnected }: LayoutProps) {
  return (
    <div className="flex h-screen bg-surface-0">
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <UpdateNotifier />
        <main className="flex-1 min-w-0 overflow-auto bg-surface-1">
          <div className="pb-6 max-w-full overflow-x-hidden">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
