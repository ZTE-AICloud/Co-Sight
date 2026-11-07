import axios from 'axios';
import appState from '@/app/state';
import message from '@/shared/lib/message';
import { FILE_NAME_CONFLICT_CODE } from '@/shared/constants/index.js';
import { encodeHeaderValue } from '@/shared/lib/cookies.ts';
import { $t, isGlobalZh } from '@/app/i18n/i18n.js';
import { hasUnauthorizedHandler, notifyUnauthorized } from '@/shared/api/unauthorized';

const HTTP_HEADER = {
  EMP_NO: 'X-Emp-No',
  EMP_NAME: 'X-Emp-Name',
  LANG: 'X-Lang-Id',
  ACCEPT_LANGUAGE: 'Accept-Language',
  TOKEN: 'X-Auth-Value',
  TENANT: 'X-Tenant-Id'
}
// 后端（RKB compat 层）的文案语言只认 Accept-Language：X-Lang-Id 在那边是死信。
// 只有 zh-CN（与 *）渲染中文，其余语言回落英文 —— 所以这里不发原始 locale，
// 而是按 **i18n 的界面语言判定**（isGlobalZh，zh* 前缀）映射成 zh-CN / en-US，
// 保证「界面是中文就发 zh-CN、界面是英文就发 en-US」，两边不会说两套话。
const ACCEPT_LANGUAGE = {
  ZH: 'zh-CN',
  EN: 'en-US'
}
/**
 * 统一的请求头。抽出来是因为**流式请求走不了 axios**（XHR 拿不到增量），
 * 只能原生 fetch —— 但两条路的鉴权头必须是同一套，否则改动鉴权方案时会漏掉一条。
 * `api/stream.js` 复用的就是这个函数。
 */
export function buildRequestHeaders () {
  const headers = {
    // [HTTP_HEADER.EMP_NO]: encodeURIComponent(appState.user.userName),
    [HTTP_HEADER.TOKEN]: appState.user.authValue,
    // 'X-Org-Id': appState.tenantId,
    [HTTP_HEADER.EMP_NO]: encodeHeaderValue(appState.user.userName),
    [HTTP_HEADER.LANG]: appState.langId.replace('-', '_'),
    // 与界面语言一致：zh 界面发 zh-CN（后端才给中文文案），其余发 en-US。
    // 注意 X-Lang-Id 保留不删（对端老网关/其他服务仍在读）
    [HTTP_HEADER.ACCEPT_LANGUAGE]: isGlobalZh ? ACCEPT_LANGUAGE.ZH : ACCEPT_LANGUAGE.EN
  };

  return headers;
}

const axiosInstance = axios.create();
let messageInstance = null;
// 不使用固定域名，默认同域（前端与后端经同一 nginx 入口）
axiosInstance.defaults.timeout = 3600000, // 请求超时时间
// 本地账号会话走 HttpOnly Cookie；同源请求本来就会带 Cookie，这里显式声明意图。
axiosInstance.defaults.withCredentials = true;
// 请求拦截器，注入header信息
axiosInstance.interceptors.request.use(config => {
  Object.assign(config.headers, buildRequestHeaders());
  return config;
}, error => {
  return Promise.reject(error);
});

/**
 * 统一的请求失败对象（后端为纯 REST + RFC 9457）。
 *
 * 字段与 ``application/problem+json`` 对齐；非 problem 的 HTTP/网络错误也归一成同一形状，
 * 调用方不再需要区分「信封里的 code.msg」与「error.response.data」。
 */
export class ApiError extends Error {
  constructor ({ status, code, detail, title, type, instance, problem, response, cause }) {
    super(detail || title || `HTTP ${status || 0}`)
    this.name = 'ApiError'
    this.status = status || 0
    this.code = code || 'http_error'
    this.detail = detail || ''
    this.title = title || ''
    this.type = type || ''
    this.instance = instance || ''
    this.problem = problem || null
    this.response = response
    if (cause) {
      this.cause = cause
    }
  }
}

function isSuccessStatus (status) {
  return status >= 200 && status < 300
}

function isProblemBody (data) {
  return Boolean(data) && typeof data === 'object' &&
    typeof data.code === 'string' && typeof data.status === 'number'
}

async function parseBlobJson (blob) {
  try {
    return JSON.parse(await blob.text())
  } catch (error) {
    return null
  }
}

function httpFallbackMessage (status) {
  if (!status) {
    return $t('public.networkError')
  }
  const key = `public.httpError${status}`
  const text = $t(key)
  if (text && text !== key) {
    return text
  }
  return $t('public.httpError', { statusCode: status })
}

async function toApiError (errorLike) {
  const response = errorLike?.response || (errorLike?.status ? errorLike : null)
  let data = response?.data
  // blob 下载失败时 axios 给的是 Blob，problem+json 需要先读文本再解析
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    data = await parseBlobJson(data)
  }
  const status = response?.status || 0
  if (isProblemBody(data)) {
    return new ApiError({
      status: data.status || status,
      code: data.code,
      detail: data.detail,
      title: data.title,
      type: data.type,
      instance: data.instance,
      problem: data,
      response,
      cause: errorLike
    })
  }
  return new ApiError({
    status,
    code: status ? 'http_error' : 'network_error',
    detail: httpFallbackMessage(status),
    response,
    cause: errorLike
  })
}

function notifyError (apiError, config) {
  if (!apiError) {
    return
  }
  // 同名文件冲突由页面弹「覆盖/恢复」确认，不弹全局 toast
  if (apiError.code === FILE_NAME_CONFLICT_CODE) {
    return
  }
  // 413/414 是代理层对超长请求的拒绝，problem body 不一定带可读 detail；
  // 统一换成用户能理解的提示，不再显示「请求失败，状态码: 414」这类原始状态码。
  let msg = (apiError.status === 413 || apiError.status === 414)
    ? $t('public.requestTooLarge')
    : (apiError.detail || apiError.title || $t('public.networkError'))
  if (config?.url && config.url.includes('/app/import')) {
    msg = `${$t('modules.agentApp.importFailed')}: ${msg}`
  }
  if (messageInstance) {
    messageInstance.close()
  }
  messageInstance = message.error({ message: msg })
}

async function rejectFailure (errorLike, config) {
  const apiError = await toApiError(errorLike)
  if (config?.skipErrorHandler) {
    return Promise.reject(apiError)
  }
  // 401 交给会话层统一处理（清状态 + 跳登录）；不要再弹一条“未授权”的通用 toast。
  if (apiError.status === 401 && hasUnauthorizedHandler()) {
    notifyUnauthorized(apiError)
    return Promise.reject(apiError)
  }
  // skipErrorMessage：只抑制全局 toast，保留 401 会话处理（页面自己提示时用）。
  if (config?.skipErrorMessage) {
    return Promise.reject(apiError)
  }
  notifyError(apiError, config)
  return Promise.reject(apiError)
}

axiosInstance.interceptors.response.use(
  async res => {
    // validateStatus: () => true 的端点会把 4xx/5xx 也送进 fulfilled 分支
    if (!isSuccessStatus(res.status)) {
      return rejectFailure({ response: res, status: res.status }, res.config)
    }
    const contentType = String(
      res.headers?.get?.('content-type') || res.headers?.['content-type'] || ''
    )
    if (contentType.includes('application/problem+json')) {
      return rejectFailure({ response: res, status: res.status }, res.config)
    }
    if (res.config?.responseType === 'blob') {
      return res.data
    }
    if (res.status === 204 || res.data === '' || res.data === undefined) {
      return null
    }
    return res.data
  },
  async error => {
    if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') {
      return Promise.reject(error)
    }
    return rejectFailure(error, error?.config)
  }
)

export default axiosInstance
