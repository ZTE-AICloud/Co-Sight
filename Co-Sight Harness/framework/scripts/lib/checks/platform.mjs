/**
 * 平台检查：产物只带 linux-x64 与 win32-x64 的原生件。
 *
 * 为什么要在最前面拦：服务端的 libsql 与 esbuild 是**原生依赖**，在别的平台上
 * 打包时根本没有对应文件。放行的话，用户会在几秒后拿到一句
 * `Cannot find module '@libsql/…'`——那看起来像包装坏了，其实是平台不支持。
 *
 * 平台清单在 `lib/preflight.mjs`，打包侧（`lib/project.mjs`）引用同一份。
 */

import { SUPPORTED_PLATFORMS } from '../preflight.mjs';

/**
 * @param {{platform?: string, arch?: string, supported?: string[]}} [options]
 *   参数可注入，单测才能覆盖"不支持"的分支而不必真的换一台机器。
 */
export function platformCheck(options = {}) {
  const platform = options.platform ?? process.platform;
  const arch = options.arch ?? process.arch;
  const supported = options.supported ?? SUPPORTED_PLATFORMS;
  const target = `${platform}-${arch}`;

  return {
    id: 'platform',
    label: '平台',
    level: 'block',
    run: () =>
      supported.includes(target)
        ? { ok: true, detail: target }
        : {
            ok: false,
            detail: `当前平台是 ${target}，不在支持范围内`,
            remedy: [
              `本产物只带 ${supported.join(' / ')} 的原生依赖`,
              '请换一台受支持的机器运行；或从源码在目标平台上自行构建',
            ],
            impact: '服务端的原生依赖（libsql）无法加载，启动必然失败',
          },
  };
}
