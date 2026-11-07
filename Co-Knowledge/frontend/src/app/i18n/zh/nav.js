/**
 * 左栏导航新增词条。
 *
 * ⛔ 只放**新出现的**菜单文案：一级「知识库」「知识检索」「自定义算子」与二级
 * 「文档知识库」「图谱知识库」都复用页面里已有的键（见 `nav/menu.config.js`）。
 * 也不复用 `zh.js` 的 `aiMenu` 段——那是旧门户的一级菜单（聊天/应用/数据集/…），
 * 语义与新结构不匹配，且全仓零引用。
 */
export default {
  chat: '对话测试',
  modelManagement: '模型管理',
  remoteAccess: '远程接入',
  remoteAccessGuide: '接入方法',
  remoteAccessKeys: '密钥管理',
  collapse: '收起侧栏',
  expand: '展开侧栏',
  switchToLight: '切换到浅色主题',
  switchToDark: '切换到深色主题',
  // 语言切换按钮的 title/aria-label。按钮**显示的文字**不走 i18n —— 它写的是
  // 「另一种语言的自我称谓」（中文界面显示 English、英文界面显示 中文），
  // 这样按钮本身在任何语言下都自解释，见 LeftNav.vue 的 otherLanguageLabel。
  switchLanguage: '切换语言',
  // 页脚偏好设置：语言选项收进气泡
  preferences: '偏好设置',
  interfaceLanguage: '界面语言',
  langZh: '简体中文',
  langZhCurrent: '简体中文，当前语言',
  langEn: 'English',
  langEnCurrent: 'English，当前语言',
  // 侧栏底部宣传卡：两行文案分开，便于固定换行
  promoLine1: '构建专属知识，',
  promoLine2: '让 AI 真正懂你的业务'
}
