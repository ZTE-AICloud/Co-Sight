/**
 * 版本号一致性。
 *
 * `SERVER_VERSION` 是从 `process.env.npm_package_version` 换过来的常量
 * （那个环境变量只在 `pnpm start` 下存在，直接 `node dist/index.js` 就没有）。
 * 常量换来的代价是"可能与 package.json 脱节"，所以这里把两者钉在一起：
 * 发版时改了 package.json 却忘了改常量，这条会红。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { SERVER_VERSION } from '../src/version';

describe('服务端版本号', () => {
  it('与 package.json 的 version 一致', () => {
    const packageJsonPath = path.join(import.meta.dirname, '..', 'package.json');
    const pkg = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8')) as { version?: string };
    expect(pkg.version).toBe(SERVER_VERSION);
  });

  it('是合法的 semver', () => {
    expect(SERVER_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
