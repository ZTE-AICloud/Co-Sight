import type { RouteObject } from 'react-router';

import { AppShell } from '../components/shell/AppShell';
import { ModuleHost } from '../components/module/ModuleHost';
import { AgentDevPage } from '../pages/AgentDevPage';
import { GuidePage } from '../pages/GuidePage';
import { KnowledgePage } from '../pages/KnowledgePage';
import { NotFoundPage } from '../pages/NotFoundPage';

/**
 * 宿主路由表。
 *
 * 除 404 外，**所有内容页都是模块宿主**——把某个 capability 对应的模块前端嵌进来（C2）。
 * `/experts` 曾经是框架自己渲染的原生页（决策 C1），现在交给 smart-factory 的 `/agents`：
 * 专家列表与智能体本来就是同一份数据，两套界面各自演进只会越来越不一致。
 *
 * 表里**没有**"某个模块是否存在"的条件判断：模块清单是运行期扫描出来的
 * （`$COSIGHT_HOME` 下 `modules` 目录里的 module.json），路由表在编译期就定了。
 * 找不到模块时，ModuleHost 渲染的是"该模块尚未接入"，而不是 404——
 * 路由存在、内容由模块提供，这两件事必须分开。
 *
 * 单独导出 `routes` 而不是在这里 `createBrowserRouter`：测试要用
 * `createMemoryRouter(routes, { initialEntries })` 跑同一条路由表。
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      /*
       * 首页 = 会话对话页。用户明确要求这个页面"不需要直接开发"，
       * 嵌对应模块的页面即可（需求 1）。
       */
      { index: true, element: <ModuleHost capability="conversation" /> },
      /*
       * 专家页由 smart-factory 提供（清单里 `experts → /agents`）。它按框架的
       * 「当前工作区」取数，所以切换工作区后要重建 iframe——否则列表还停在旧工作区。
       */
      { path: 'experts', element: <ModuleHost capability="experts" reloadOnContextChange /> },
      { path: 'agent-dev', element: <AgentDevPage /> },
      { path: 'history', element: <ModuleHost capability="history" /> },
      /*
       * 使用说明是宿主自己的内容，不是模块：它不依赖运行期扫描出来的清单，
       * 也不该在模块缺失时显示"尚未接入"。
       */
      { path: 'guide', element: <GuidePage /> },
      /*
       * 「知识库」不是清单里的模块：内容是用户在设置里配的地址。侧栏入口现在直接在
       * **新标签页**打开它（见 `KnowledgeNavItem`）；这条宿主路由保留给直接访问与
       * 旧书签，把地址嵌进主面板（见 `KnowledgePage`）。没有可用路由时空态里直接给
       * 「去设置新增」。
       */
      { path: 'knowledge', element: <KnowledgePage /> },
      { path: 'observability', element: <ModuleHost capability="observability" /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
