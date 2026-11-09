/**
 * 类名拼接。
 *
 * 有它才能写出 `className={cn(styles.base, isActive && styles.active)}`：
 * 直接模板串拼会在 `isActive` 为 false 时留下一个 `"false"` 类名，
 * 在 CSS Modules 里不会报错、只是悄悄多出一个无用类，属于很难发现的那种脏。
 */
export function cn(...parts: readonly (string | false | null | undefined)[]): string {
  return parts.filter((part): part is string => typeof part === 'string' && part !== '').join(' ');
}
