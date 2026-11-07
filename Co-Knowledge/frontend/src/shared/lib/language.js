/**
 * 界面语言的读取与切换（登录页 / 左栏偏好设置共用）。
 *
 * ⚠️ 优先级必须与 `app/i18n/i18n.js`、`app/state.js` 完全一致，否则会出现
 * 「按钮显示中文、界面却是英文」这种自相矛盾：
 *   localStorage（JSON 编码）→ navigator.language → 'zh-CN'
 *
 * 切换后**必须整页重载**，不能只改 vue-i18n 的 `locale`：
 *   语言在**模块导入期**被读了多处 —— `i18n.js` 的 `locale` 常量与 `isGlobalZh`、
 *   `appState.js` 的 `langId`（它会进 API 的 LANG 请求头）；
 *   而 Element Plus 的语言是 `main.js` 里 `app.use(ElementPlus, {...})` 安装时传入的。
 * 只改运行时的 `i18n.global.locale` 会留下「界面切了、请求头没切、EP 组件没切」
 * 的半中半英状态。整页重载让这几处一起重新求值，是唯一能保证一致的做法。
 */

export const LANGUAGE_STORAGE_KEY = 'language-option'
export const ZH_CN = 'zh-CN'
export const EN_US = 'en-US'

/** 当前生效语言：localStorage → navigator.language → 'zh-CN'。 */
export function readEffectiveLanguage () {
  if (typeof localStorage === 'undefined') {
    return ZH_CN
  }
  let stored = null
  try {
    stored = JSON.parse(localStorage.getItem(LANGUAGE_STORAGE_KEY))
  } catch {
    // 存了非法 JSON（例如有人手工写成裸 `en`）时不能让整个组件挂掉 —— 按「没设过」处理。
    stored = null
  }
  const browser = typeof navigator === 'undefined'
    ? ''
    : (navigator.language || navigator.userLanguage || '')
  return String(stored || browser || ZH_CN)
}

/** 只有中文与英文两种界面语言，其余值（含 `zh-TW` 等）一律按首选语言归一。 */
export function isChineseLanguage (language = readEffectiveLanguage()) {
  return /^zh/i.test(String(language))
}

export function normalizeLanguage (language) {
  return language === ZH_CN ? ZH_CN : EN_US
}

/**
 * 切换界面语言并整页重载。
 *
 * @param {'zh-CN' | 'en-US'} language 目标语言
 * @returns {boolean} 是否真的写入了新语言（点当前语言返回 false，不重载）
 */
export function switchLanguage (language) {
  const next = normalizeLanguage(language)
  if (next === (isChineseLanguage() ? ZH_CN : EN_US)) {
    return false
  }
  localStorage.setItem(LANGUAGE_STORAGE_KEY, JSON.stringify(next))
  if (typeof location !== 'undefined' && location.reload) {
    location.reload()
  }
  return true
}
