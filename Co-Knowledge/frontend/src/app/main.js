// @ts-nocheck
import 'core-js/stable';
import 'regenerator-runtime/runtime';
import App from './App.vue'
import routerConfigs from './router.js'
import { store } from '@/app/store'
// import i18nConfig from '@/app/i18n'
import i18n, { locale, $t, isGlobalZh } from '@/app/i18n/i18n.js'

import directives from '@/app/directives/index'

import { createApp } from 'vue'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus';
// import * as ElementPlusIconsVue from '@/shared/lib/icons';
import zh from 'element-plus/es/locale/lang/zh-cn';
import en from 'element-plus/es/locale/lang/en';
import 'element-plus/dist/index.css'
// EP 官方深色变量（html.dark）；必须排在 index.css 之后、本站主题之前
import 'element-plus/theme-chalk/dark/css-vars.css'
// 字形随应用部署（Inter / Noto Sans SC / JetBrains Mono，精确锁版）
import '@/styles/fonts.css'
// JSON 编辑器的深色主题：CSS 自限定在 .jse-theme-dark，不影响浅色
import 'vanilla-jsoneditor/themes/jse-theme-dark.css'
// 必须排在 Element Plus 之后：用 !important 覆盖组件库的动画默认值
import '@/styles/reduced-motion.css'
// 视觉层：六份样式文件按固定顺序全局加载。
import '@/styles/tokens.css'
import '@/styles/base.css'
import '@/styles/tables.css'
import '@/styles/management.css'
// 新建/编辑弹窗视觉层（StudioDialog / FormSection / 选择卡 / 折叠区）。
// 导入顺序：management.css 之后、workspaces.css 之前。
import '@/styles/dialogs.css'
// 危险操作统一视觉（删除按钮、菜单项、删除确认弹窗）。
import '@/styles/deletions.css'
import '@/styles/workspaces.css'
// 编排节点配置抽屉（680px、算子卡片、提示词展开）的共享排版。
import '@/styles/flow-config.css'
import '@/styles/theme.css'
import { initializeTheme } from '@/shared/lib/theme'

import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
import { initSession } from '@/features/auth/session'
import { installAuthGuard } from '@/features/auth/guard'
import { installRouteProgress } from '@/shared/lib/route-progress'


// const originalPush = VueRouter.prototype.push
// // 解决VeinUIPlus导航栏中的vue-router在3.0版本以上重复点菜单报错问题
// VueRouter.prototype.push = function push (location) {
//   return originalPush.call(this, location).catch(err => err)
// }


let app = null

const base = process.env.BASE_URL
const ROUTER_MODE = process.env.VUE_APP_ROUTE_MODE
const mode = ROUTER_MODE
const router = createRouter({
  history: mode === 'hash' ? createWebHashHistory(base) : createWebHistory(base), // 此处代码是根据父应用路由模式变化，也可以固定不变化
  routes: routerConfigs
})

// 独立部署时的产品名兜底（组件树里没有任何一处设过它，见 vue.config.js 的 title 注释）
const APP_TITLE = 'Knowledge Studio'

router.beforeEach((to, from, next) => {
  // 路由 meta.title 优先；router.js 里没有 meta.title，所以实际永远走兜底
  // （避免 document.title 全站为空）。
  document.title = to.meta && to.meta.title ? $t(to.meta.title) : APP_TITLE;
  // 无障碍：`public/index.html` 里 `<html lang="">` 也是空串，按界面语言补齐
  // （切换语言走整页重载，这里每次导航重设不额外增加成本）
  document.documentElement.setAttribute('lang', isGlobalZh ? 'zh-CN' : 'en-US');
  next();
});

// 顶部加载进度条。注册在 auth 守卫**之前**：守卫里的 `/auth/status` 与随后的
// 懒加载 chunk 都算这次导航，用户从点击到新页面出现全程有反馈。
installRouteProgress(router)

// 本地账号会话：注册全局 401 处理器 + 路由守卫。
// 顺序在 title/lang 之后：守卫可能重定向，重定向后的新导航会再跑一遍 title 逻辑。
initSession(router)
installAuthGuard(router)


/* 国际化信息处理 */
// UniWork默认语言参数是zh-CN | en-US，适配不同平台，语言格式可能不同，可以只取前两个字符
// const { zh, en } = window.VeinUiPlusLocale

// 主题必须在挂载前生效：EP 的深色变量读 html.dark，首屏不能先亮后暗。
initializeTheme()

app = createApp(App)
app.use(router)

app.use(ElementPlus, {
  locale: locale.substring(0, 2) === 'zh' ? zh : en
  // Use default-size components with --el-component-size:40px.
  // A global `size: 'large'` adds `--large` classes and changes dropdown/control
  // metrics (e.g. menu item padding 7px 20px instead of 10px 18px).
})
app.use(i18n)
app.use(directives)
app.use(store)
app.config.globalProperties.$store = store;

app.config.globalProperties.$message = options => {
  // eslint-disable-next-line new-cap
  return ElMessage({
    showClose: true,
    ...options
  });
};
['success', 'warning', 'info', 'error'].forEach(type => {
  app.config.globalProperties.$message[type] = options => {
    return ElMessage[type]({
      type,
      showClose: true,
      message: options
    });
  };
});

app.config.globalProperties.$confirm = (message, title, options, appContext) => {
  return ElMessageBox.confirm(message, title, { closeOnClickModal: false, closeOnPressEscape: false, ...options }, appContext)
}

window.aipVueInstance = app.config.globalProperties;

app.config.globalProperties.$globalZh = locale.substring(0, 2) === 'zh'

// 父应用传递的容器,必须在props上获取
const container = document.querySelector('#app') || '#app'

// 等首个路由就绪再挂载：`public/index.html` 里的启动占位一直显示到登录页 chunk
// 和 `/auth/status` 都回来为止，避免「先闪一下空白再出登录页」。
//
// 两条兜底，缺一不可：
//   - 导航失败（chunk 404、守卫抛错）时 `isReady()` 是 reject，必须吞掉再挂载；
//   - `isReady()` 也可能**永远不返回**（后端不可达且请求不超时），所以再加一道
//     硬超时，到点照常挂载——宁可回到「空白 + 守卫错误页」的老行为，也不能让
//     启动占位一直转下去。
const MOUNT_TIMEOUT = 15000
let mounted = false
function mountApp () {
  if (mounted) {
    return
  }
  mounted = true
  app.mount(container)
}
Promise.race([
  router.isReady().catch(() => {}),
  new Promise(resolve => setTimeout(resolve, MOUNT_TIMEOUT))
]).then(mountApp)

