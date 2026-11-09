/**
 * 服务端版本号。
 *
 * 为什么不读 `process.env.npm_package_version`：那个变量只在通过包管理器脚本
 * 启动时才存在（`pnpm start` 有、直接 `node dist/index.js` 没有），会让健康检查
 * 在两种启动方式下返回不同的东西，也让这个分支无法测试。
 * 这里的常量与 package.json 的一致性由 tests/version.test.ts 断言钉住。
 */

export const SERVER_VERSION = '0.1.0';
