/**
 * 判断一个请求错误是否只是「被主动取消」，而不是真的失败。
 *
 * 表格每次取数都会 abort 掉上一次未完成的请求（列表取数每次都会 abort 上一次）——这是正常的「新请求替换旧请求」。这种取消不应该被当成失败上报到控制台，
 * 更不应该让它把已经渲染出来的表格清空（旧请求的善后不能覆盖新请求的结果）。
 *
 * 判据与 api/base.js 拦截器里的 `error?.code !== 'ERR_CANCELED'` 保持一致，
 * 另外兼容原生 AbortController 抛出的 AbortError 和 axios v1 的 CanceledError。
 */
export function isRequestCanceled (error) {
  if (!error) {
    return false
  }
  return error.code === 'ERR_CANCELED' ||
    error.name === 'CanceledError' ||
    error.name === 'AbortError'
}
