/**
 * 入口。
 *
 * 只做三件事：挂 Provider、建路由、把应用塞进 #root。
 * 业务逻辑一律不在这里——这个文件在覆盖率统计里是排除项（见 vite.config.ts），
 * 写进去的代码就等于没被测过。
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createBrowserRouter } from 'react-router';

import { queryClient } from './api/queryClient';
import { routes } from './app/routes';
import './styles/global.css';

const container = document.getElementById('root');
if (container === null) {
  // 静默失败在这里代价最大：整页空白且控制台无任何线索。宁可抛一个明确的错。
  throw new Error('找不到 #root：index.html 被改动了');
}

createRoot(container).render(
  /*
   * StrictMode 在开发态会把 effect 跑两遍，这是**故意**的：它把"effect 没写清理函数"
   * 这类问题在开发期就暴露出来。生产构建里不会有这个双重执行。
   */
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createBrowserRouter(routes)} />
    </QueryClientProvider>
  </StrictMode>,
);
