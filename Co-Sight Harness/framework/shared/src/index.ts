/**
 * harness-shared —— 框架前后端共享契约层（D1 = A）。
 *
 * 这里只放**两端都要认同**的东西：schema、类型、枚举、纯函数。
 * 不放任何一端独有的实现（HTTP 客户端、DB 访问、React 组件）。
 *
 * 消费方式：harness-server 经 tsx 直接加载 TS 源码；harness-web 经 Vite 打包。
 * 因此本包**不做构建**，`exports` 直接指向 src——契约改动即刻对两端可见，
 * 不存在"改了 schema 忘了重新构建 shared"的漂移。
 */

export * from './bridge';
export * from './contracts';
export * from './envelope';
export * from './errors';
export * from './locale';
