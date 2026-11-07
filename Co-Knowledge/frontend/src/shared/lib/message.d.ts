/**
 * `message.js` 的类型声明。
 *
 * 为什么单独放一个 .d.ts 而不是把实现改写成 .ts：`message.js` 的实现已由
 * `tests/unit/message.spec.js` 覆盖（12 条用例，含阳性对照），运行时形状与
 * Element Plus 的 `ElMessage` 完全一致 —— 直接复用 EP 自己的 `Message` 类型
 * 即可，不必手写一份会与实现漂移的接口。
 *
 * 少了这个文件，构建会报：
 *   src/lib/utils.ts:26  TS2339: Property 'success' does not exist on type
 *   '{ (options: any): MessageHandler; closeAll(...args: any[]): void; }'
 * —— TS 从 .js 推断时看不到实现里动态挂上去的 success/warning/info/error。
 */
import type { Message } from 'element-plus';

declare const message: Message;
export default message;
