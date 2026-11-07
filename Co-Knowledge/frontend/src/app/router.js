import { kbPermissionMeta } from '@/shared/constants/index.js'
import Home from '@/app/layout/AppShell.vue'

// 登录页。必须与 `/` 平级：放进 Home 的 children 会把左侧栏/主面板
// 外壳一起渲染出来，登录页就不再是整页布局。
const Login = () => import(/* webpackChunkName: "module.auth" */'@/pages/login/LoginPage.vue');
// 强制改密页：与 /login 同为顶层路由，不套主面板外壳。
const ChangePassword = () => import(/* webpackChunkName: "module.auth" */'@/pages/login/ChangePasswordPage.vue');

// 知识库管理（/knowledge）
const Knowledge = () => import(/* webpackChunkName: "module.kb" */'@/pages/knowledge-base/KnowledgeBaseListPage.vue');
// 知识库详情（数据集 / 基本信息）与文档管理两个视图共用一个组件。
// 路由名 knowledge-detail / knowledge-documents，参数名 :id。
const KnowledgeDetail = () => import(/* webpackChunkName: "module.kb" */'@/pages/knowledge-base/KnowledgeBaseDetailPage.vue');

// 知识图谱（独立页面，从「图谱知识库」入口进入）
// 只保留后端确有对应接口的页面：/graph（列表）、/graph/detail/:id、/graph/edit/:id。
const KnowledgeGraphPage = () => import(/* webpackChunkName: "module.kb" */'@/pages/graph/GraphListPage.vue');
const CreateKnowledgeGraph = () => import(/* webpackChunkName: "module.kb" */'@/features/graph/CreateKnowledgeGraph.vue');
const KnowledgeGraphDetail = () => import(/* webpackChunkName: "module.kb" */'@/pages/graph/GraphDetailPage.vue');
const EditKnowledgeGraph = () => import(/* webpackChunkName: "module.kb" */'@/features/graph/EditKnowledgeGraph.vue');
const GraphTemplateDesigner = () => import(/* webpackChunkName: "module.kb" */'@/features/graph/GraphTemplateDesigner.vue');

// 算子管理（/operators）
const ExtendedManagementIndex = () => import(/* webpackChunkName: "module.extendedManagement" */'@/pages/operators/OperatorListPage.vue');

// 检索编排（画布 + 列表）
// 后端 /api/co-knowledge/v1 提供接口。
const CustomizedAdvancedFlow = () => import(/* webpackChunkName: "module.flow" */'@/pages/workflow/WorkflowEditorPage.vue');
const WorkFlowIndex = () => import(/* webpackChunkName: "module.flow" */'@/pages/workflow/WorkflowListPage.vue');
// 对话测试页（视图 + lib + composables）
const ChatTest = () => import(/* webpackChunkName: "module.flow" */'@/pages/chat/ChatPage.vue');

const routes_kb_flow = [
  {
    path: '/flow',
    name: 'flow',
    component: WorkFlowIndex
  },
  {
    // 参数名：/flow/detail/:id
    path: '/flow/detail/:id',
    name: 'flow-detail',
    component: CustomizedAdvancedFlow,
    // 编排画布是左栏内的 workspace（面包屑 + 标题 + 工具条 + 画布），不隐藏左栏。
    // 画布的专注模式由页面自己的按钮切换。
    meta: {}
  },
  {
    path: '/chat',
    name: 'chat',
    component: ChatTest
  }
]

const routes_kb_extended_management = [
  {
    path: '/operators',
    name: 'operators',
    component: ExtendedManagementIndex
  }
]

// 模型管理（LLM / Embedding / Reranker 三类 OpenAI 兼容端点）。
// 路由：/models。
const ModelManagementIndex = () => import(/* webpackChunkName: "module.model" */'@/pages/model/ModelListPage.vue');

// 远程接入（MCP / REST 接入说明 + API Key 管理）。
// 路由：/access 与 /keys（两条独立路由）。
//
// 两条路由共用 AgentLayout 这层布局（面包屑/标题/状态只取一次）：布局组件按
// `route.name` 渲染对应子页；未注册的地址由全局兜底处理。
const RemoteAccessIndex = () => import(/* webpackChunkName: "module.remoteAccess" */'@/pages/agent/AgentLayout.vue');

const routes_remote_access = [
  {
    path: '/access',
    name: 'access',
    component: RemoteAccessIndex,
    // hiddenBorder：与 /knowledge、/models 等列表页一致，去掉主面板那条边框
    meta: { hiddenBorder: true, subpageLabelKey: 'nav.remoteAccessGuide' }
  },
  {
    path: '/keys',
    name: 'keys',
    component: RemoteAccessIndex,
    meta: { hiddenBorder: true, subpageLabelKey: 'nav.remoteAccessKeys' }
  }
]

const routes_model_management = [
  {
    // 路由：/models。
    // ⚠️ 路由名**不要**叫 `model`：`Home.vue` 里有一条按 `$route.name==='model'` 挂的
    // class `el-main--model`，而 `common.less:605` 给它配了背景 `#E9EDF7` ——
    // 取名 `model` 会让本页内容区整块变成浅蓝灰，与全站其他页（白底）不一致。
    path: '/models',
    name: 'models',
    component: ModelManagementIndex,
    // hiddenBorder：列表页约定，去掉主面板那条边框（与 /knowledge、/operators 一致）
    meta: { hiddenBorder: true }
  }
]

const routes_kb = [
  {
    path: '/knowledge',
    name: 'knowledge',
    component: Knowledge,
    meta: {
      permission: kbPermissionMeta,
      hiddenBorder: true
    }
  },
  {
    // 知识库详情：数据集（分块）+ 基本信息。
    // 参数名 `:id`（/knowledge/detail/:id）。
    path: '/knowledge/detail/:id',
    name: 'knowledge-detail',
    component: KnowledgeDetail,
    meta: {
      permission: kbPermissionMeta,
      hiddenBorder: true
    }
  },
  {
    // 文档管理：目录 + 文件表格（与详情页共用组件，用路由名区分视图）
    path: '/knowledge/detail/:id/documents',
    name: 'knowledge-documents',
    component: KnowledgeDetail,
    meta: {
      permission: kbPermissionMeta,
      hiddenBorder: true
    }
  },
]

// 知识图谱的页面路由：/graph、/graph/detail/:id、/graph/edit/:id
const routes_knowledge_graph = [
  {
    // 图谱知识库列表页（左栏「图谱知识库」入口）。
    path: '/graph',
    name: 'graph',
    component: KnowledgeGraphPage,
    meta: { permission: kbPermissionMeta, hiddenBorder: true }
  },
  {
    // 图谱详情。
    path: '/graph/detail/:id',
    name: 'graph-detail',
    component: KnowledgeGraphDetail,
    meta: { permission: kbPermissionMeta }
  },
  {
    path: '/graph/edit/:id',
    name: 'graph-edit',
    component: EditKnowledgeGraph,
    meta: { permission: kbPermissionMeta }
  },
  {
    // 整页新建入口；挂在图谱资源下，保持 /graph/* 的命名空间一致。
    path: '/graph/create',
    name: 'graph-create',
    component: CreateKnowledgeGraph,
    meta: { permission: kbPermissionMeta }
  },
  {
    // 图谱模板设计器。
    path: '/graph/createTemplate/:templateId',
    name: 'graph-template',
    component: GraphTemplateDesigner,
    meta: { permission: kbPermissionMeta }
  }
]

const routes_out = [
  {
    // `/` 默认重定向到 `/login`（登录页是默认首页）。
    path: '/',
    component: Home,
    redirect: { name: 'login' },
    children: [
      ...routes_kb,
      ...routes_kb_extended_management,
      ...routes_model_management,
      ...routes_remote_access,
      ...routes_kb_flow,
      ...routes_knowledge_graph,
      {
        // 全局兜底（必须放最后一条）：hash 路由 + SPA 回退下，任何匹配不到的地址
        // 既不会 404 也不会提示，只会渲染成空白页（`#app` 里只剩
        // `<div class="saas"><!----></div>`，零 API 请求）。未注册地址走全局兜底，
        // 统一按未知地址落到文档知识库。
        //
        // 落在 children 里（而不是顶层）是为了不破坏「单根 `/` + children」结构 ——
        // 重定向后仍回到 Home.vue 的布局。因为是 redirect，兜底记录自己从不渲染。
        // 用函数形式显式清空 query：对象形式会把旧参数（如 `?tab=knowledgeGraph`）带到
        // 文档知识库上。
        path: '/:pathMatch(.*)*',
        redirect: () => ({ name: 'knowledge', query: {} })
      }
    ]
  },
  {
    // 顶层登录页（与 `/` 平级，不能放进 Home 的 children）：meta.layout = 'auth'；
    // App.vue 直接渲染 router-view，页面不会套 Home 的侧栏壳。
    // 放在 `/` 之后是为了让 routes_out[0] 仍是 Home 根记录。
    path: '/login',
    name: 'login',
    component: Login,
    meta: { layout: 'auth' }
  },
  {
    // 强制改密：must_change_password=true 的账号登录后被守卫送到这里。
    // 与 /login 平级；AUTH_MODE != local 时守卫不会启用，直接访问仍会渲染本页，
    // 但改密接口返回 409 auth_not_enabled。
    path: '/change-password',
    name: 'changePassword',
    component: ChangePassword,
    meta: { layout: 'auth' }
  }
]

export default routes_out
