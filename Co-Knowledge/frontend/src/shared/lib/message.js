/**
 * 轻提示（toast）的统一出口 —— 本仓「提示风格」的单一事实来源。
 *
 * 为什么需要它：
 *   应用入口注册的全局 `$message` 会给每次提示自动注入
 *   `showClose: true`（模板/组件里约 171 处走它）；但 JS/TS 代码里另有约 40 处
 *   直接 `import { ElMessage } from 'element-plus'` 调用，**不带** `showClose` ——
 *   同一次会话里，提示的关闭按钮时有时无，风格不统一。
 *   本模块把「默认 showClose: true」这一个决定收进一处：凡是要直连 ElMessage 的
 *   调用点都改从本模块 import，行为与 `$message` 对齐；调用方**显式传的值优先**
 *   （例如 `message({ message: '…', showClose: false })` 仍然不带关闭按钮）。
 *
 * 形状与 Element Plus 的 `ElMessage` 完全一致：
 *   message('文本')              / message({ message, type })
 *   message.success(...)         message.warning(...)
 *   message.info(...)            message.error(...)
 *   message.closeAll()
 * 四个便捷方法与基础调用一样同时接受两种实参形态：
 *   1) 字符串 —— 消息内容，如 message.error('保存失败')；
 *   2) 对象 —— 完整配置，如 message.error({ message: '保存失败', duration: 5000 })，
 *      对象直接展开，因此调用方传的 showClose / duration / dangerouslyUseHTMLString
 *      等字段逐项生效。
 *
 * 只依赖 element-plus，不 import 本仓任何模块（尤其不要指向 main.ts 的封装，
 * 那会绕出一圈循环依赖）。
 */
import { ElMessage } from 'element-plus';

// 非对象实参是「消息内容」的简写，包成 `{ message }`；对象实参本身就是配置，原样返回。
// 覆盖本仓全部调用点的两种形态（字符串、配置对象）；VNode 实参本仓没有调用点，不做特判 ——
// 真要用时再补（EP 内部是用 vue 的 isVNode 判的，本模块刻意不 import vue）。
const toOptions = options => (
  options !== null && typeof options === 'object' ? options : { message: options }
);

const message = options => {
  // eslint-disable-next-line new-cap
  return ElMessage({
    // showClose 写在展开之前：调用方显式传的 showClose 覆盖默认值
    showClose: true,
    ...toOptions(options)
  });
};

['success', 'warning', 'info', 'error'].forEach(type => {
  message[type] = options => ElMessage[type]({
    showClose: true,
    ...toOptions(options),
    // type 写在展开之后：与 EP 自身一致，方法名决定提示类型
    type
  });
});

// 其余静态方法按原样透传，保证与 ElMessage 同形状（EP 的 closeAll 还接受可选的 type 过滤）
message.closeAll = (...args) => ElMessage.closeAll(...args);

export default message;
