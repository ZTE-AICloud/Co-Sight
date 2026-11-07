/**
 * Left navigation labels. Reuses the existing keys for every label that already
 * exists (see `nav/menu.config.js`); labels with no page-level key live here.
 */
export default {
  chat: 'Chat Test',
  modelManagement: 'Model Management',
  remoteAccess: 'Remote Access',
  remoteAccessGuide: 'Access Methods',
  remoteAccessKeys: 'API Keys',
  collapse: 'Collapse sidebar',
  expand: 'Expand sidebar',
  switchToLight: 'Switch to light theme',
  switchToDark: 'Switch to dark theme',
  // title/aria-label of the language button. The button's visible text is deliberately
  // NOT translated — it shows the *other* language's autonym (English in the Chinese UI,
  // 中文 in the English UI) so it reads correctly under any locale; see LeftNav.vue.
  switchLanguage: 'Switch language',
  // Footer preferences (UX prototype 0.1.0): language options live in the popover
  preferences: 'Preferences',
  interfaceLanguage: 'Interface language',
  langZh: '简体中文',
  langZhCurrent: 'Simplified Chinese, current language',
  langEn: 'English',
  langEnCurrent: 'English, current language',
  // Sidebar promo card (UX prototype): split into two lines on purpose
  promoLine1: 'Build your own knowledge,',
  promoLine2: 'make AI understand your business'
}
