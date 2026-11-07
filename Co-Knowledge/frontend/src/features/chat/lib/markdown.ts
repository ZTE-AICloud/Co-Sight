/**
 * markdown → 可安全 `v-html` 的 HTML。
 *
 * 零 Vue 依赖的纯函数层：只做「文本进、消毒后的 HTML 出」，方便单测直接跑。
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/**
 * 不允许出现在渲染结果里的标签。
 *
 * `script` / `iframe` 之类本来就不在 DOMPurify 的默认白名单里，这里只补上
 * **默认允许、但在聊天答案里没有任何正当用途**的几个：
 *   - img/媒体：从「检索到的文档正文」这类外部可写文本里带进来就是外部信标（加载即上报）；
 *   - style/表单控件：改页面样式、伪造输入框；
 *   - svg/math：markdown 本来就不产出它们，而**未闭合的原始 `<svg>` 会把后面所有
 *     正文吞进 svg 元素里**（实测：一条 `<svg/onload=…>` 让答案后半截消失），
 *     禁用比留着划算。
 */
export const FORBIDDEN_HTML_TAGS: string[] = [
  'img', 'style', 'form', 'input', 'button', 'select', 'textarea', 'video', 'audio', 'source',
  'svg', 'math'
]

// 表格（gfm）与「单个换行即换行」（breaks）都要：用户输入框里的 Shift+Enter 换行、
// 模型输出里逐行排的要点，都不带空行；不断行它们会全部挤成一行。
marked.setOptions({ gfm: true, breaks: true })

/**
 * markdown → 可以安全 `v-html` 的 HTML。
 *
 * **必须先 sanitize**：答案里会混进检索到的文档正文，那是外部可写文本，
 * 未经消毒直接 `v-html` 就是 XSS 入口。DOMPurify 默认档会剥掉 `script`、
 * `iframe` 以及**所有** `on*` 事件属性；这里只额外禁掉几个聊天答案用不到、
 * 却能被检索内容拿来搞副作用的标签（见 `FORBIDDEN_HTML_TAGS`）。
 *
 * @param text 原始 markdown；空值直接返回空串（调用方不必先判空）
 *
 * 传给 `marked.parse` 的 `{ async: false }` 只是给类型重载用的显式同步声明 ——
 * marked 默认就是同步解析，写出来是让 TS 拿到 `string` 而不是 `string | Promise<string>`，
 * **不改变任何渲染结果**。
 */
export function renderMarkdown (text?: string | null): string {
  if (!text) {
    return ''
  }
  return DOMPurify.sanitize(marked.parse(text, { async: false }), { FORBID_TAGS: FORBIDDEN_HTML_TAGS })
}
