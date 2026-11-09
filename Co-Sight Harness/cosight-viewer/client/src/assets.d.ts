// SPDX-License-Identifier: Apache-2.0
/**
 * 图片资源的类型声明。
 *
 * 本工程**没有**引 `vite/client` 那套全量类型(它顺带声明 `import.meta.env` 等一整片),
 * 而这里只用得上"import 一张图拿到 URL"这一条,所以就只声明这一条 ——
 * 与 `lib/config.ts` 里 `declare const __DEV_API_BASE__` 就地声明的做法一致。
 *
 * 没有它,`import robotUrl from "../assets/robot.png"` 会报 TS2307(模块找不到),
 * 虽然 Vite 运行时完全能处理。
 */
declare module "*.png" {
  const src: string;
  export default src;
}
