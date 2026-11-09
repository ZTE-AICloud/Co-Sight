/**
 * `docs/modules/*.launch.json` 的合法性回归。
 *
 * 与 `module-manifests-doc.test.ts` 是同一套思路的另一半：那份守的是**运行时清单**
 * （`<id>.module.json`，「页面能不能挂上」），这份守的是**启动清单**
 * （`<id>.launch.json`，「本机怎么把它跑起来」，只被 `scripts/dev-all.mjs` 消费）。
 *
 * 为什么值得单测：两者的失配方式全都**不报错**，只表现为"某个模块没起来"。
 *   · 加了 `module.json` 忘了加 `launch.json` → `scanLaunchEntries` 扫不到，
 *     那个模块安静地不启动，退出码照样是 0；
 *   · 两份文件的 `id` 不一致 → 同上（扫描按文件名，不是按内容）；
 *   · 两个模块声明同一个端口 → 要等前一个就绪之后才炸 EADDRINUSE，
 *     此时人已经在看一屏带前缀的日志了；
 *   · `port` 写成字符串 "3000" → 就绪探测静默失效（`Number.isInteger` 会拒，
 *     但那是脚本运行期的事，CI 里没人跑脚本）。
 *
 * 这里把"登记了模块就必须登记它的启动方式，且两份清单自洽"变成 CI 能拦住的约束。
 *
 * 不 import `scripts/lib/module-launch.mjs`：server 的 `tsconfig.rootDir` 是 `.`，
 * 从 `tests/` 反引仓库另一侧的 `.mjs` 会让 tsc 报 TS6059。所以这里只读文件 + 断言，
 * 校验规则刻意与那个模块**重复**一份——重复的是十来行断言，换来的是 CI 不依赖脚本能跑起来。
 */

import fs from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

/** 用 `import.meta.dirname` 而不是 `process.cwd()`：与测试运行时的目录无关。 */
const manifestsDir = path.resolve(import.meta.dirname, '..', '..', 'docs', 'modules');

/** 与 `module-launch.mjs` 的 `MODULE_ID_PATTERN` 保持一致。 */
const MODULE_ID_PATTERN = /^[a-z][a-z0-9-]{1,62}$/;

interface LaunchService {
  name?: unknown;
  cwd?: unknown;
  command?: unknown;
  port?: unknown;
  readyPath?: unknown;
}

/** 产物重建步骤。字段与 `scripts/lib/module-launch.mjs` 的 `BUILD_FIELDS` 一致。 */
interface BuildSpec {
  command?: unknown;
  cwd?: unknown;
  inputs?: unknown;
  outputs?: unknown;
  timeoutMs?: unknown;
}

interface LaunchManifest {
  id?: unknown;
  moduleRoot?: unknown;
  priority?: unknown;
  build?: unknown;
  services?: unknown;
  isolatedEnv?: unknown;
}

/** 与 `module-launch.mjs` 的 `BUILD_FIELDS` 保持一致。 */
const BUILD_FIELDS = ['command', 'cwd', 'inputs', 'outputs', 'timeoutMs'];

/** 收集一个 `build` 字段的问题；`build` 缺省是合法的（大多数模块不吃产物）。 */
function collectBuildProblems(fileName: string, build: unknown, problems: string[]): void {
  if (build === null || typeof build !== 'object' || Array.isArray(build)) {
    problems.push(`${fileName} build: 必须是对象`);
    return;
  }

  const spec = build as BuildSpec;
  for (const key of Object.keys(spec)) {
    if (!BUILD_FIELDS.includes(key)) {
      // 未知字段在真读取时会直接报错（`assertKnownFields`），CI 里也拦一道：
      // `output`（少个 s）这种错拼最要命——它会让"产物永远不存在"变成"永远不重建"。
      problems.push(`${fileName} build: 未知字段 "${key}"（可选：${BUILD_FIELDS.join(' / ')}）`);
    }
  }

  if (!Array.isArray(spec.command) || spec.command.length === 0) {
    problems.push(`${fileName} build.command: 必须是"程序 + 参数"的非空数组`);
  } else if (spec.command.some((part) => typeof part !== 'string' || part.length === 0)) {
    problems.push(`${fileName} build.command: 里只能放非空字符串`);
  }

  if (spec.cwd !== undefined && (typeof spec.cwd !== 'string' || spec.cwd.length === 0)) {
    problems.push(`${fileName} build.cwd: 必须是非空字符串`);
  }

  if (spec.inputs !== undefined) {
    if (!Array.isArray(spec.inputs) || spec.inputs.length === 0) {
      problems.push(`${fileName} build.inputs: 给了就必须是非空数组（不给默认 ["."]）`);
    } else if (spec.inputs.some((part) => typeof part !== 'string' || part.length === 0)) {
      problems.push(`${fileName} build.inputs: 里只能放非空字符串`);
    }
  }

  // outputs 必填：没有它就只能无条件重建，而这个字段存在的全部理由就是**不**无条件重建。
  if (!Array.isArray(spec.outputs) || spec.outputs.length === 0) {
    problems.push(`${fileName} build.outputs: 必填且非空（陈旧判据全靠它）`);
  } else if (spec.outputs.some((part) => typeof part !== 'string' || part.length === 0)) {
    problems.push(`${fileName} build.outputs: 里只能放非空字符串`);
  }

  if (spec.timeoutMs !== undefined && (!Number.isInteger(spec.timeoutMs) || (spec.timeoutMs as number) <= 0)) {
    problems.push(`${fileName} build.timeoutMs: 必须是正整数毫秒数`);
  }
}

function listFiles(suffix: string): string[] {
  return fs
    .readdirSync(manifestsDir)
    .filter((name) => name.endsWith(suffix))
    .toSorted();
}

function readJson(fileName: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(manifestsDir, fileName), 'utf8'));
}

function readLaunch(fileName: string): LaunchManifest {
  const parsed = readJson(fileName);
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${fileName} 不是一个对象`);
  }
  return parsed as LaunchManifest;
}

function servicesOf(manifest: LaunchManifest): LaunchService[] {
  if (!Array.isArray(manifest.services)) {
    throw new Error('services 不是数组');
  }
  return manifest.services as LaunchService[];
}

describe('docs/modules 下登记的模块启动清单', () => {
  it('目录里至少有清单文件', () => {
    // 没有这一条，下面所有"遍历"型断言在目录被清空时会全部空转通过。
    expect(listFiles('.launch.json').length).toBeGreaterThan(0);
  });

  it('模块清单与启动清单一对一', () => {
    /*
     * 这是本文件存在的主要理由。两侧都用文件名前缀当 id，所以"缺一个"和"id 写错"
     * 在这里是同一个断言就能盖住的：`X.module.json` 存在 ⇔ `X.launch.json` 存在。
     */
    const modules = listFiles('.module.json').map((name) => name.replace(/\.module\.json$/, ''));
    const launches = listFiles('.launch.json').map((name) => name.replace(/\.launch\.json$/, ''));

    expect(launches).toEqual(modules);
  });

  it('每条启动登记都自洽', () => {
    // 累积全部问题再断言：一次跑出所有毛病，比逐个修-重跑省事。
    const problems: string[] = [];

    for (const fileName of listFiles('.launch.json')) {
      const prefix = fileName.replace(/\.launch\.json$/, '');
      const manifest = readLaunch(fileName);

      if (manifest.id !== prefix) {
        problems.push(`${fileName}: id 是 ${JSON.stringify(manifest.id)}，与文件名前缀不一致`);
      } else if (typeof manifest.id !== 'string' || !MODULE_ID_PATTERN.test(manifest.id)) {
        problems.push(`${fileName}: id 不符合模块 id 规则`);
      }

      if (typeof manifest.moduleRoot !== 'string' || manifest.moduleRoot.length === 0) {
        problems.push(`${fileName}: moduleRoot 必须是非空字符串`);
      }

      if (!Number.isInteger(manifest.priority)) {
        problems.push(`${fileName}: priority 必须是整数，收到 ${JSON.stringify(manifest.priority)}`);
      }

      if (manifest.build !== undefined) {
        collectBuildProblems(fileName, manifest.build, problems);
      }

      let services: LaunchService[];
      try {
        services = servicesOf(manifest);
      } catch (error) {
        problems.push(`${fileName}: ${(error as Error).message}`);
        continue;
      }
      if (services.length === 0) {
        problems.push(`${fileName}: services 不能为空`);
      }

      const names = new Set<string>();
      for (const [index, service] of services.entries()) {
        const scope = `${fileName} services[${index}]`;

        if (typeof service.name !== 'string' || !/^[a-z][a-z0-9-]*$/.test(service.name)) {
          problems.push(`${scope}: name 非法（${JSON.stringify(service.name)}）`);
        } else if (names.has(service.name)) {
          problems.push(`${scope}: name "${service.name}" 重复`);
        } else {
          names.add(service.name);
        }

        if (typeof service.cwd !== 'string' || service.cwd.length === 0) {
          problems.push(`${scope}: cwd 必须是非空字符串`);
        }

        if (!Array.isArray(service.command) || service.command.length === 0) {
          problems.push(`${scope}: command 必须是非空数组`);
        } else if (service.command.some((part) => typeof part !== 'string' || part.length === 0)) {
          problems.push(`${scope}: command 里只能放非空字符串`);
        }

        // 写成 "3000" 会让就绪探测静默失效——这是最隐蔽的一种错。
        if (!Number.isInteger(service.port) || (service.port as number) < 1 || (service.port as number) > 65_535) {
          problems.push(`${scope}: port 必须是 1..65535 的整数，收到 ${JSON.stringify(service.port)}`);
        }

        if (service.readyPath !== undefined) {
          if (typeof service.readyPath !== 'string' || !service.readyPath.startsWith('/')) {
            problems.push(`${scope}: readyPath 必须以 / 开头`);
          }
        }
      }
    }

    expect(problems).toEqual([]);
  });

  it('多个模块之间不撞端口', () => {
    /*
     * 框架自己的 4300 / 4310 写死在 dev-all.mjs 里，清单里看不到，所以这里只查模块之间的。
     * 模块内撞端口（同一 services 数组里两条同号）也一并盖住——同一个 Map 就够。
     */
    const byPort = new Map<number, string>();
    const clashes: string[] = [];

    for (const fileName of listFiles('.launch.json')) {
      const manifest = readLaunch(fileName);
      if (!Array.isArray(manifest.services)) {
        continue;
      }
      for (const service of manifest.services as LaunchService[]) {
        if (!Number.isInteger(service.port)) {
          continue;
        }
        const port = service.port as number;
        const owner = `${fileName}:${String(service.name)}`;
        const seen = byPort.get(port);
        if (seen !== undefined) {
          clashes.push(`端口 ${port} 被 ${seen} 与 ${owner} 同时声明`);
        }
        byPort.set(port, owner);
      }
    }

    expect(clashes).toEqual([]);
  });

  it('observability 模块的启动登记隔离了 viewer 自有数据目录', () => {
    /*
     * cosight-viewer 是唯一有副作用的模块，但它有两个**互不相干**的目录，别混：
     *
     * 1. CLI 源目录（只读会话 + 可写 hook）：`CLAUDE_CONFIG_DIR` ?? `~/.claude`。
     *    `installHooks(true)` 往这里的 `settings.json` 幂等地补自己的条目。
     *    **`COSIGHT_HOME` 管不到它**——之前拿 `COSIGHT_HOME` 当隔离开关是错的，
     *    "转录为空"的根因就在这里（见 `cosight-viewer/server/lib/claude-home.js` 文件头）。
     *    真要隔离全局 hook 写入，唯一有效的开关是 `CLAUDE_CONFIG_DIR`；当前默认刻意
     *    不设，让观测页读真实会话，代价是启动时写一次 `~/.claude/settings.json`。
     * 2. viewer 自有数据目录（可写）：`DASHBOARD_DATA_DIR`。数据库/日志/快照都在这里。
     *
     * 所以这条断言守的是：清单必须显式给 `DASHBOARD_DATA_DIR`，否则默认启动会把库
     * 写进模块目录。副作用与 `--live` 的差异见 `framework/docs/dev-all.md` 的"三段副作用"。
     */
    const manifest = readLaunch('cosight-viewer.launch.json');
    const isolated = manifest.isolatedEnv;

    expect(isolated).toBeTypeOf('object');
    expect(Object.keys(isolated as Record<string, unknown>)).toContain('DASHBOARD_DATA_DIR');
  });

  it('cosight-viewer 的启动登记声明了产物重建，且产物就是它托管的那个 dist', () => {
    /*
     * 这个模块的开发态入口**就是产物**：server 在 `CO_SIGHT_MODE=claude` 下是生产模式，
     * 静态托管 `client/dist`，而 `client/dist` 是 gitignore 的——`git pull` 只更新源码，
     * 不管产物。实测踩到过：同事合进来的对话页在本机 404，因为旧包里连那条 hash 路由都没有，
     * 而唯一的现象是"页面没更新"，很容易被读成"功能没做"。
     *
     * 所以这条不是格式偏好：删掉 `build` 就等于让默认启动回到"本机产物是几天前的"，
     * 而那件事**不报错**，只安静地骗人。拿不准就先去读 framework/docs/dev-all.md 的"模块产物"。
     */
    const manifest = readLaunch('cosight-viewer.launch.json');
    const build = manifest.build as BuildSpec | undefined;

    expect(build).toBeTypeOf('object');
    // 路径必须指向 server 真正托管的那个目录，否则"重建了"和"页面变了"是两件事。
    expect(build?.cwd).toBe('client');
    expect(build?.outputs).toContain('dist/index.html');
  });
});
