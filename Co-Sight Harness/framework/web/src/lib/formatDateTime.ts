/**
 * 契约里的时间戳（ISO 8601 字符串）转成本地可读文本。
 *
 * 用 `Intl.DateTimeFormat` 而不是拼 `getFullYear()`：日期顺序、上下午写法、月份名
 * 在两种语言里都不一样，手拼一定要写两套分支，而且每年都要回来看一眼。
 *
 * `timeZone` 显式留空（用运行环境的时区）：这是本地工具，用户看到的应该是**自己的**
 * 钟点，而不是服务端的。翻译与日期是两件事，所以语言用 `locale` 参数而不是自己猜。
 *
 * 解析失败（服务端给了非 ISO 串、或字段为 null）时返回 `null`，**不返回 "Invalid Date"**：
 * 那串英文会原样出现在中文界面上，而"该字段没有值"本来就该由调用方决定怎么显示。
 */

export function formatDateTime(value: string | null | undefined, locale: string): string | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(timestamp);
}
