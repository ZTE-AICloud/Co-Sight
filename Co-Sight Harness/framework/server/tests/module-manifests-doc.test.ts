/**
 * `docs/modules/*.module.json` 的合法性回归。
 *
 * `tests/module-registry.test.ts` 用临时目录 + 内联清单测的是**扫描器**的行为；
 * 本文件补的是它够不到的一类：**仓库里真正登记的那几份清单**。
 *
 * 为什么值得单测：这些文件是版本控制里的真源（接入一个模块就把它 cp 到
 * `$COSIGHT_HOME/modules/<id>/module.json`），但复制这一步没有任何校验。
 * 而清单写错的表现特别隐蔽——`GET /api/modules` 照样返回 200，坏清单只是被
 * 挪进 `invalid`（`src/modules/registry.ts:52-90` 刻意的"坏清单不阻断扫描"），
 * 前端则退回「模块尚未接入」，和"这个模块根本没接"长得一模一样。
 * 于是"字段名写错"和"还没接"只能靠人去翻 `/api/modules` 才分得清。
 *
 * 这里把"仓库里登记的清单必须是合法清单"变成 CI 能拦住的约束。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { moduleManifestSchema, validateModuleManifest } from 'harness-shared';
import type { ModuleManifest } from 'harness-shared';

/**
 * 校验用的宿主源。
 *
 * 取**开发态前端**的地址（Vite 4310），不是 API 自己的 4300。开发态真正嵌 iframe 的是
 * 前者，而 `COSIGHT_HOST_ORIGIN` 的默认值取的是后者（`src/config/env.ts:99-109`），
 * 于是 D24 的同源守卫在开发态比较的是一个错的源——这是既有的老问题，
 * 本轮不修，但测试里不能跟着错。
 */
const HOST_ORIGIN = 'http://localhost:4310';

/** 用 `import.meta.dirname` 而不是 `process.cwd()`：与测试运行时的目录无关。 */
const manifestsDir = path.resolve(import.meta.dirname, '..', '..', 'docs', 'modules');

function listManifestFiles(): string[] {
  return fs
    .readdirSync(manifestsDir)
    .filter((name) => name.endsWith('.module.json'))
    .toSorted();
}

function readManifest(fileName: string): ModuleManifest {
  const raw = fs.readFileSync(path.join(manifestsDir, fileName), 'utf8');
  return moduleManifestSchema.parse(JSON.parse(raw));
}

/** 按 `id` 找一份清单。找不到就抛——静默返回 undefined 会让断言变得没有意义。 */
function findManifest(id: string): ModuleManifest {
  for (const fileName of listManifestFiles()) {
    const manifest = readManifest(fileName);
    if (manifest.id === id) {
      return manifest;
    }
  }
  throw new Error(`docs/modules 下没有 id = ${id} 的清单`);
}

describe('docs/modules 下登记的模块清单', () => {
  it('目录里至少有清单文件', () => {
    // 没有这一条，下面的断言在目录被人清空时会全部空转通过——
    // 而"清单没了"正是最需要被发现的情况。
    expect(listManifestFiles().length).toBeGreaterThan(0);
  });

  it('每一份都满足契约与跨源约束', () => {
    // 累积全部问题再断言，而不是遇到第一份就中断：
    // 一次跑出所有毛病，比逐个修-重跑省事。
    const problems: string[] = [];

    for (const fileName of listManifestFiles()) {
      const parsed = moduleManifestSchema.safeParse(
        JSON.parse(fs.readFileSync(path.join(manifestsDir, fileName), 'utf8')),
      );

      if (!parsed.success) {
        const detail = parsed.error.issues
          .map((issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`)
          .join('; ');
        problems.push(`${fileName} 不满足 moduleManifestSchema → ${detail}`);
        continue;
      }

      for (const issue of validateModuleManifest(parsed.data, HOST_ORIGIN)) {
        problems.push(`${fileName} 未通过跨源校验 → [${issue.code}] ${issue.path}: ${issue.message}`);
      }
    }

    expect(problems).toEqual([]);
  });

  it('smart-factory 挂在 agent-dev 上', () => {
    // 挂在 `agent-dev` 才能出现在左侧栏「Agent开发. 评估」的右侧内容区
    // （`framework/web/src/app/routes.tsx` → `AgentDevPage` → `ModuleHost capability="agent-dev"`）。
    const capabilities = findManifest('smart-factory').mounts.map((mount) => mount.capability);
    expect(capabilities).toContain('agent-dev');
  });

  it('smart-factory 的专家页挂在 experts 上，并指向模块内的 /agents', () => {
    /*
     * 左侧栏「专家」→ `/experts` 现在由 smart-factory 提供（原来的原生 ExpertsPage 已删）。
     * 它的专家列表在模块前端的 `/agents`，而 `entry` 指向模块首页——两者靠 `entryPath`
     * 连接。少了这一项，`/experts` 会落回模块首页（smart-factory 的欢迎页），
     * 而清单校验完全发现不了：它只是合法地打开了另一个页面。
     */
    const mount = findManifest('smart-factory').mounts.find(
      (candidate) => candidate.capability === 'experts',
    );
    expect(mount?.path).toBe('/experts');
    expect(mount?.entryPath).toBe('/agents');
  });

  it('cosight-viewer 挂在 observability 上', () => {
    // 左侧栏「观测」→ `/observability` 的内容区由它提供
    // （`framework/web/src/app/routes.tsx:38` → `ModuleHost capability="observability"`）。
    const capabilities = findManifest('cosight-viewer').mounts.map((mount) => mount.capability);
    expect(capabilities).toContain('observability');
  });

  it('smart-factory 的 entry 用 localhost 而不是 127.0.0.1', () => {
    /*
     * 不是风格偏好，是可达性问题：smart-factory 的 Vite 没设 `server.host`，
     * 默认的 `localhost` 在本机解析成 `::1`，于是只绑 IPv6——
     * `curl http://127.0.0.1:4110/` 拿不到任何东西，`localhost` 才通。
     *
     * 而这个错误**清单校验发现不了**：`http://127.0.0.1:4110` 是合法裸源，
     * 也不等于宿主源，扫描器会放行，只在浏览器里表现为 iframe 白屏。
     * 所以只能在这里钉死。等他们的 Vite 显式绑定了 IPv4，这条可以放开。
     */
    expect(new URL(findManifest('smart-factory').entry).hostname).toBe('localhost');
  });
});
