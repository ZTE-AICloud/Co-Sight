// 这个模块也会被 node 环境的单测间接 import（LeftNav → appState），
// 浏览器全局在这里做一次守卫，避免测试在模块加载期就挂在 window/localStorage。
const hasWindow = typeof window !== 'undefined';
const tenantId = hasWindow ? (window.getUserTenantID?.() || '') : '';
const username = hasWindow ? (window.getUserName?.() || '') : '';
const authValue = '';
const navLanguage = typeof navigator !== 'undefined'
  ? (navigator.language || navigator.userLanguage || '')
  : '';
let storedLanguage = null;
try {
  storedLanguage = typeof localStorage !== 'undefined'
    ? JSON.parse(localStorage.getItem('language-option'))
    : null;
} catch {
  // 存了非法 JSON（手工写成裸 `en`）时按没设过处理，与应用其余读法一致。
  storedLanguage = null;
}
const langId = storedLanguage || navLanguage || 'zh-CN';

const appState = {
  langId, // 当前界面语言
  tenantId, // 外部身份头里的组织 ID
  user: { // 当前用户信息
    authValue, // 外部身份头里的访问令牌
    userName: username, // 用户账号
    personName: '', // 用户显示名
    displayLongName: '', // 用户完整名称
    avatar: '', // 用户头像 URL
    email: ''
  },
  system: process.env.VUE_APP_SYSTEM,
  loginUrl: process.env.VUE_APP_UAC // 外部登录页地址（可选）
}
export function updateAppState ({ langId, tenantId, user, loginUrl, system }) {
  appState.langId = langId || appState.langId
  appState.tenantId = tenantId || appState.tenantId
  appState.user = user || appState.user
  appState.loginUrl = loginUrl || appState.loginUrl
  appState.system = system || appState.system
}
export default appState
