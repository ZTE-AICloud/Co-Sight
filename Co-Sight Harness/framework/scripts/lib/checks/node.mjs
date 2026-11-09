/**
 * Node 版本检查。
 *
 * 判定本身复用 `lib/node-version.mjs`（不引依赖、不认识的区间必须报错），
 * 这里只负责把三种情况翻成报告条目：
 *
 *   - 清单没写 `engines.node` → 通过（那是打包侧的疏漏，不该让用户停机）
 *   - 区间写法解析不了        → 失败（这是我们自己的 bug，静默放过会变成玄学）
 *   - 明确不满足              → 失败，并给出当前版本 / 要求 / 下载地址
 *
 * `engines.node` 放在**服务端**清单里而不是仓库根：根 package.json 不进产物，
 * 而安装脚本与启动脚本都需要一个能在产物里读到的答案。
 */

import fs from 'node:fs';
import path from 'node:path';

import { satisfies, UnsupportedRangeError } from '../node-version.mjs';

export const NODE_DOWNLOAD_URL = 'https://nodejs.org/zh-cn/download';

/**
 * 读服务端清单里的 `engines.node`；没写就是 `null`。
 *
 * @param {string} appDir 服务端目录
 * @returns {string|null}
 */
export function readNodeRequirement(appDir) {
  const manifestPath = path.join(appDir, 'package.json');
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    throw new Error(`读不到服务端清单 ${manifestPath}：${error.message}`, { cause: error });
  }
  const range = manifest.engines?.node;
  return typeof range === 'string' && range.trim() !== '' ? range.trim() : null;
}

/**
 * @param {{appDir: string, currentVersion?: string, downloadUrl?: string}} options
 *   `currentVersion` 可注入，单测才能覆盖"版本太低"而不必换 Node。
 */
export function nodeCheck(options) {
  const { appDir } = options;
  const current = options.currentVersion ?? process.versions.node;
  const downloadUrl = options.downloadUrl ?? NODE_DOWNLOAD_URL;

  return {
    id: 'node',
    label: 'Node',
    level: 'block',
    run: () => {
      const range = readNodeRequirement(appDir);

      if (range === null) {
        return { ok: true, detail: `v${current}（服务端清单未声明 engines.node，跳过版本校验）` };
      }

      let satisfied;
      try {
        satisfied = satisfies(current, range);
      } catch (error) {
        if (error instanceof UnsupportedRangeError) {
          return {
            ok: false,
            detail: `无法解析服务端声明的 Node 版本要求「${range}」（当前 v${current}）`,
            remedy: ['这是打包侧的缺陷，请反馈'],
            impact: '无法判断当前 Node 是否可用，因此不继续',
          };
        }
        throw error;
      }

      if (satisfied) {
        return { ok: true, detail: `v${current}（满足 ${range}）` };
      }

      return {
        ok: false,
        detail: `v${current} 不满足要求 ${range}`,
        remedy: [`安装 ${range} 范围内的 Node：${downloadUrl}`],
        impact: '服务端以 TypeScript 源码运行，旧版本 Node 不支持它用到的语法与 API',
      };
    },
  };
}
