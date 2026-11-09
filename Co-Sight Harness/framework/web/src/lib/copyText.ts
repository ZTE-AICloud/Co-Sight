/**
 * 复制一段文本到剪贴板。
 *
 * 返回**布尔**而不是抛异常：复制失败不是错误状态，只是这次没成功，调用方要做的
 * 是换一句话提示用户手动选中，而不是渲染一个错误面板。把三件都可能失败的事
 * （浏览器没有 `navigator.clipboard`、非安全上下文、用户拒绝权限）收敛成一个 `false`。
 *
 * 不做 `document.execCommand('copy')` 兜底：那个 API 已废弃，而且它要求先往页面里
 * 插一个隐藏 `<textarea>` 再聚焦——为一条提示语引入一次真实 DOM 写入与焦点抢夺，
 * 得不偿失。页面上的 `<code>` 本来就是可选中复制的。
 */

export async function copyText(text: string): Promise<boolean> {
  try {
    const clipboard = navigator.clipboard;
    if (clipboard === undefined) {
      return false;
    }
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
