import { ModuleHost } from '../components/module/ModuleHost';

/**
 * Agent 开发 / 评估页（需求 4.1、4.5 的落点）。
 *
 * 这是个**薄壳**：页面本身没有内容，一切交给 `agent-dev` 模块；它存在的理由是
 * 把 `mode` / `expert` 这两个参数的路由约定写在一处、并有地方承接。
 *
 * URL 约定（D19 = A）：
 * - `/agent-dev?mode=create`              页头「专家智能体创建」
 * - `/agent-dev?expert=<id>&mode=design`  卡片「设计」
 * - `/agent-dev?expert=<id>&mode=evaluate` 卡片「评估」
 * - `/agent-dev?expert=<id>&mode=optimize` 卡片「优化」
 *
 * 宿主**不解析** `mode`，原样转发（见 ModuleHost，它把当前查询串整体拼给模块）。
 * 这样将来新增一个 mode 不需要改框架。
 *
 * 关于 `agent-eval`：契约 `MODULE_CAPABILITIES` 里留着这个能力位，但
 * `EXPERT_ACTION_KIND`（同一份契约）把评估/优化也归到 `agent-dev`，
 * 四个动作共用一个路由。也就是说 v1 **没有**任何路由会挂载 `agent-eval` 模块；
 * 等评估真的拆成独立前端时，这里按 `mode` 在两份清单之间二选一即可。
 *
 * **模型 / 工作区切换后整页刷新**（`reloadOnContextChange`）：开发和评估页的结果
 * 都是按「当前模型 + 当前工作区」取出来的，而切上下文发生在设置弹窗 / 侧栏，
 * iframe 里的模块收不到通知。由宿主重建 iframe，模块入口会自然重拉一遍数据。
 * 评估与优化也走这条路由，所以一并生效。
 */
export function AgentDevPage() {
  return <ModuleHost capability="agent-dev" reloadOnContextChange />;
}
