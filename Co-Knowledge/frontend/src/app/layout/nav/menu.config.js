import { Document, Share, Search, ChatDotRound, Link, Key } from '@element-plus/icons-vue'
import { CubeIcon, PuzzleIcon } from '@/shared/ui/icons'

/**
 * 左栏导航的**唯一真值**。
 *
 * 为什么不从 router 的 `meta` 生成：菜单顺序、分组、图标不是路由的属性；而且
 * 知识库组还有「子页归到哪个入口高亮」这层映射（`resolveActiveMenu`），`meta` 表达不了。
 *
 * 左栏路径：
 *   /knowledge、/graph、/flow、/chat、/operators、/models、/access、/keys。
 *
 * 字段：
 *   index    el-menu 的唯一键，也是 `LeftNav.vue` 里 `activeMenu` 要比对的字符串
 *   labelKey i18n 键。⚠️ 知识库组两项**故意复用页面里已有的键**（页头面包屑用的是
 *            同一批）—— 共用键是「菜单与页内文案不会各改各的」的唯一硬保证。
 *   icon     一级菜单图标。用 `<img>` 渲染，不走 EP 的 `icon` prop（后者走
 *            `<component :is>`，传 SVG URL 会被当成组件解析）。
 *   children 有则渲染 `el-sub-menu`；缺省则渲染根级 `el-menu-item`
 *   route    `router` 模式下实际 push 的对象（EP `menu.mjs` 里 `menuItem.route || index`）
 *
 * 有意不进菜单的路由：
 *   `/knowledge/detail/*`、`/graph/detail/*` 等 —— 子页，由页内导航进入
 */
export const NAV_MENUS = [
  {
    index: 'kb',
    labelKey: 'modules.kb.kb',
    iconComponent: Document,
    children: [
      {
        index: '/knowledge',
        labelKey: 'modules.kb.dockb',
        iconComponent: Document,
        route: { path: '/knowledge' }
      },
      {
        index: '/graph',
        labelKey: 'modules.kb.graphKnowledgeBase',
        iconComponent: Share,
        route: { path: '/graph' }
      }
    ]
  },
  // 知识检索与对话测试是同级入口：列表页、新建按钮、对话测试统一叫「知识检索」，
  // 不再用「检索编排」作为二级菜单名（同一个对象两套叫法，测试侧会当成不一致）。
  {
    index: '/flow',
    labelKey: 'ragFlow.ragWorkflow',
    iconComponent: Search,
    route: { path: '/flow' }
  },
  {
    index: '/chat',
    labelKey: 'nav.chat',
    iconComponent: ChatDotRound,
    route: { path: '/chat' }
  },
  {
    index: '/operators',
    labelKey: 'modules.extendedManagement.extendedManagement',
    iconComponent: PuzzleIcon,
    route: { path: '/operators' }
  },
  {
    // 模型管理（LLM / Embedding / Reranker 三类 OpenAI 兼容端点）。
    // 平级入口、无 query —— 所以 `resolveActiveMenu` 不用改（走末尾的 `return path` 兜底）。
    index: '/models',
    labelKey: 'nav.modelManagement',
    iconComponent: CubeIcon,
    route: { path: '/models' }
  },
  {
    // 远程接入：接入说明与 Key 管理是两件独立的事（一个给集成方看，一个给
    // 管理员用），拆成子菜单而不是页内页签 —— 与「知识库」组同一结构。
    index: 'remoteAccess',
    labelKey: 'nav.remoteAccess',
    iconComponent: Link,
    children: [
      {
        index: '/access',
        labelKey: 'nav.remoteAccessGuide',
        iconComponent: Link,
        route: { path: '/access' }
      },
      {
        index: '/keys',
        labelKey: 'nav.remoteAccessKeys',
        iconComponent: Key,
        route: { path: '/keys' }
      }
    ]
  }
]

/**
 * 由当前路由算出应该高亮哪一项。
 *
 * ⚠️ 返回值必须与 `NAV_MENUS` 里的 `index` **完全相等**（el-menu 拿它比 index）。
 * 知识库/图谱的子页都落在各自的路径前缀下，映射就是两条前缀判断。
 *
 * @param {string} path  `route.path`
 * @returns {string} 命中菜单项的 index；无命中返回 path 本身（结果为「不高亮」）
 */
export function resolveActiveMenu (path) {
  // 远程接入的两个子页。带尾斜杠时 route.path 会保留斜杠（vue-router strict:false
  // 仍然匹配），不能用精确相等判——否则整条左栏不高亮。
  if (path === '/access' || path.startsWith('/access/')) {
    return '/access'
  }
  if (path === '/keys' || path.startsWith('/keys/')) {
    return '/keys'
  }
  // 图谱知识库列表本身 + 它的子页（详情/新建/编辑/模版设计器）：
  // /graph、/graph/detail/...、/graph/create、/graph/edit/...、/graph/createTemplate/...
  if (path === '/graph' || path.startsWith('/graph/')) {
    return '/graph'
  }
  // 文档知识库列表 + 其余 /knowledge/* 子页（详情/文档管理）
  if (path === '/knowledge' || path.startsWith('/knowledge/')) {
    return '/knowledge'
  }
  return path
}
