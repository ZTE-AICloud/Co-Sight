/**
 * 模块**启动清单**（`docs/modules/<id>.launch.json`）的读取与校验。
 *
 * ── 为什么是"旁挂"而不是加进 module.json ────────────────────────────────
 *
 * `module.json` 是**运行时契约**（`shared/src/contracts/module.ts`）：描述"宿主该把哪个
 * capability 挂到哪条路由、允许从哪个源加载"，并且会被 `/api/modules` 原样发给浏览器。
 * "在这台开发机上怎么把模块跑起来"是**开发编排**，不是运行时契约——两者的生命周期和
 * 消费方都不一样。混进去会让清单里多出 shell 命令，还会随接口泄露到前端。
 *
 * 所以启动方式登记在**同目录的另一个文件**里：`<id>.launch.json` 与 `<id>.module.json`
 * 一对一。运行时契约一个字段都没动；加一个模块 = 加一个 json，framework 代码不用改。
 *
 * **装配态另有一份 `<id>.artifact.json`（`lib/artifact-spec.mjs`，D41）。** 两份清单
 * 长得很像，但引用的东西不同：这份写 `npm run dev`、路径相对仓库根，是给开发机的；
 * 那份写 `node server/index.js`、路径相对模块目录，要连同模块代码一起装进产物。
 * 正因为两边的工具链与目录基准都不一样，才没有合并成一份。
 *
 * 刻意不复用 `shared` 里的 zod schema（`module-probe.mjs:13-16` 已说明同一取舍）：
 * `scripts/` 不是工作区包，`.mjs` import 不了"不构建、直接导出 src/*.ts"的 TypeScript 源码。
 * 这里的校验是**给写清单的人看的**——报错必须带上文件名与字段路径，宁可严过头。
 */

import fs from 'node:fs';
import path from 'node:path';

import { stripBom } from './text.mjs';

export const LAUNCH_SCHEMA_VERSION = 1;
export const DEFAULT_READY_PATH = '/';
export const DEFAULT_READY_TIMEOUT_MS = 30_000;

/** 模块之间按 priority 升序启动；框架自己固定排在最前（脚本里写死，不走清单）。 */
export const FRAMEWORK_PRIORITY = 0;

const TOP_LEVEL_FIELDS = new Set([
  'schemaVersion',
  'id',
  'moduleRoot',
  'priority',
  'build',
  'services',
  'env',
  'isolatedEnv',
  'notes',
]);

/**
 * 模块产物的重建步骤（可选）。字段放这么少是刻意的：这里只需要回答
 * "现在这份产物是不是旧的"，所以**输入、产物、命令**三样就够，不做一个通用构建系统。
 */
const BUILD_FIELDS = new Set(['command', 'cwd', 'inputs', 'outputs', 'timeoutMs']);

const DEFAULT_BUILD_TIMEOUT_MS = 300_000;

const SERVICE_FIELDS = new Set([
  'name',
  'cwd',
  'command',
  'port',
  'readyPath',
  'readyTimeoutMs',
  'stripEnvPrefixes',
]);

const MODULE_ID_PATTERN = /^[a-z][a-z0-9-]{1,62}$/;

function fail(file, message) {
  throw new Error(`${file} 的启动清单有问题：${message}`);
}

function assertKnownFields(file, object, known, scope) {
  for (const key of Object.keys(object)) {
    if (!known.has(key)) {
      fail(file, `${scope}出现未知字段 "${key}"（可选：${[...known].join(' / ')}）。未知字段一律报错，避免写错名字后静默失效。`);
    }
  }
}

function assertPlainObject(file, value, scope) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(file, `${scope}必须是对象`);
  }
}

/** 环境变量的值只允许字符串：数字/布尔写成别的类型会在注入时变成 "undefined"。 */
function readStringMap(file, value, scope) {
  assertPlainObject(file, value, scope);
  const out = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw !== 'string' || raw.length === 0) {
      fail(file, `${scope}.${key} 必须是字符串（收到 ${JSON.stringify(raw)}）`);
    }
    out[key] = raw;
  }
  return out;
}

function readService(file, raw, index) {
  const scope = `services[${index}]`;
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, SERVICE_FIELDS, `${scope}`);

  const name = raw.name;
  if (typeof name !== 'string' || !/^[a-z][a-z0-9-]*$/.test(name)) {
    fail(file, `${scope}.name 必须是小写字母/数字/连字符，收到 ${JSON.stringify(name)}`);
  }

  if (typeof raw.cwd !== 'string' || raw.cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对 moduleRoot，模块根写 "."）`);
  }

  if (!Array.isArray(raw.command) || raw.command.length === 0) {
    fail(file, `${scope}.command 必须是"程序 + 参数"的非空数组，例如 ["npm", "run", "dev"]`);
  }
  for (const [position, part] of raw.command.entries()) {
    if (typeof part !== 'string' || part.length === 0) {
      fail(file, `${scope}.command[${position}] 必须是非空字符串`);
    }
  }

  // 端口是就绪探测的依据，必须能自己算出来——写错成字符串 "3000" 会让探测悄悄失效。
  if (!Number.isInteger(raw.port) || raw.port < 1 || raw.port > 65_535) {
    fail(file, `${scope}.port 必须是 1..65535 的整数，收到 ${JSON.stringify(raw.port)}`);
  }

  if (raw.readyPath !== undefined && (typeof raw.readyPath !== 'string' || !raw.readyPath.startsWith('/'))) {
    fail(file, `${scope}.readyPath 必须以 / 开头，收到 ${JSON.stringify(raw.readyPath)}`);
  }

  if (
    raw.readyTimeoutMs !== undefined &&
    (!Number.isInteger(raw.readyTimeoutMs) || raw.readyTimeoutMs <= 0)
  ) {
    fail(file, `${scope}.readyTimeoutMs 必须是正整数毫秒数，收到 ${JSON.stringify(raw.readyTimeoutMs)}`);
  }

  if (raw.stripEnvPrefixes !== undefined) {
    if (!Array.isArray(raw.stripEnvPrefixes)) {
      fail(file, `${scope}.stripEnvPrefixes 必须是字符串数组`);
    }
    for (const prefix of raw.stripEnvPrefixes) {
      if (typeof prefix !== 'string' || prefix.length === 0) {
        fail(file, `${scope}.stripEnvPrefixes 里只能放非空字符串前缀`);
      }
    }
  }

  return {
    name,
    cwd: raw.cwd,
    command: [...raw.command],
    port: raw.port,
    readyPath: raw.readyPath ?? DEFAULT_READY_PATH,
    readyTimeoutMs: raw.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS,
    stripEnvPrefixes: [...(raw.stripEnvPrefixes ?? [])],
  };
}

/** 读一个路径数组字段（`inputs` / `outputs`）：相对 `cwd`，空数组与非字符串都报错。 */
function readPathList(file, value, scope) {
  if (!Array.isArray(value) || value.length === 0) {
    fail(file, `${scope} 必须是非空的字符串数组（路径相对 cwd）`);
  }
  for (const [position, entry] of value.entries()) {
    if (typeof entry !== 'string' || entry.length === 0) {
      fail(file, `${scope}[${position}] 必须是非空字符串`);
    }
  }
  return [...value];
}

/**
 * 读可选的 `build`：启动前要不要把模块的产物重新打一遍。
 *
 * ── 为什么要这个字段 ────────────────────────────────────────────────
 * 有的模块的**开发态入口就是产物**（cosight-viewer 的 server 静态托管 `client/dist`），
 * 而产物是 gitignore 的：`git pull` 拉到了新源码，页面还是旧的，人只会以为"功能没做"。
 * 于是"启动前把产物刷一遍"必须有人负责——把它写成清单里的一个字段，谁都不用记得。
 *
 * ── 为什么不无条件重建 ──────────────────────────────────────────────
 * 无条件重建是最简单的，也是最贵的：每次 `pnpm dev:all` 都白等一次完整构建。
 * 所以 `inputs` / `outputs` 是**必填**的：脚本据此判断"产物是不是旧的"，新旧相同就跳过。
 * 判据是保守的（输入里有任何一个比产物新就重建），宁可多建一次，不会少建一次。
 * 要强制重建用脚本的 `--rebuild`，不要靠删字段绕过。
 *
 * `inputs` 省略即 `["."]`（整个 cwd）。`outputs` 不能省——没有它就只能无条件重建，
 * 而这个字段存在的全部理由就是**不**无条件重建。
 */
function readBuild(file, raw, moduleRoot) {
  const scope = 'build';
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, BUILD_FIELDS, scope);

  if (!Array.isArray(raw.command) || raw.command.length === 0) {
    fail(file, `${scope}.command 必须是"程序 + 参数"的非空数组，例如 ["npm", "run", "build"]`);
  }
  for (const [position, part] of raw.command.entries()) {
    if (typeof part !== 'string' || part.length === 0) {
      fail(file, `${scope}.command[${position}] 必须是非空字符串`);
    }
  }

  if (raw.cwd !== undefined && (typeof raw.cwd !== 'string' || raw.cwd.length === 0)) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对 moduleRoot，模块根写 "."）`);
  }

  if (raw.timeoutMs !== undefined && (!Number.isInteger(raw.timeoutMs) || raw.timeoutMs <= 0)) {
    fail(file, `${scope}.timeoutMs 必须是正整数毫秒数，收到 ${JSON.stringify(raw.timeoutMs)}`);
  }

  const cwd = path.resolve(moduleRoot, raw.cwd ?? '.');

  return {
    command: [...raw.command],
    cwd,
    inputs: raw.inputs === undefined ? ['.'] : readPathList(file, raw.inputs, `${scope}.inputs`),
    outputs: readPathList(file, raw.outputs, `${scope}.outputs`),
    timeoutMs: raw.timeoutMs ?? DEFAULT_BUILD_TIMEOUT_MS,
  };
}

/**
 * 读取并校验一个启动清单。
 *
 * @param {string} file 清单的绝对路径
 * @param {{repoRoot: string, live?: boolean}} options
 *        `live` 为真时**不注入** `isolatedEnv`（模块改用自己真实的 home / 数据目录）。
 * @returns {{
 *   id: string, file: string, priority: number, notes: string|null,
 *   moduleRoot: string, isolatedEnv: Record<string, string>, live: boolean,
 *   build: {command: string[], cwd: string, inputs: string[], outputs: string[],
 *           timeoutMs: number}|null,
 *   services: Array<{name: string, label: string, cwd: string, command: string[],
 *                    port: number, readyPath: string, readyTimeoutMs: number,
 *                    stripEnvPrefixes: string[], env: Record<string, string>}>,
 * }} `isolatedEnv` 的值与每个 service 的 `env` 都已是**绝对路径**（相对目录按 moduleRoot 解析）。
 */
export function readLaunchEntry(file, options) {
  const repoRoot = options.repoRoot;
  const live = options.live === true;

  let parsed;
  try {
    // stripBom：launch.json 是人手写的（Windows 上多半是记事本），带 BOM 的
    // JSON.parse 会直接抛，报错还会说成"读不出启动清单"（见 lib/text.mjs）。
    parsed = JSON.parse(stripBom(fs.readFileSync(file, 'utf8')));
  } catch (error) {
    throw new Error(`读不出启动清单 ${file}：${error.message}`, { cause: error });
  }

  assertPlainObject(file, parsed, '清单');
  assertKnownFields(file, parsed, TOP_LEVEL_FIELDS, '清单');

  if (parsed.schemaVersion !== LAUNCH_SCHEMA_VERSION) {
    fail(file, `schemaVersion 必须是 ${LAUNCH_SCHEMA_VERSION}，收到 ${JSON.stringify(parsed.schemaVersion)}`);
  }

  const id = parsed.id;
  if (typeof id !== 'string' || !MODULE_ID_PATTERN.test(id)) {
    fail(file, `id 必须是小写字母/数字/连字符（同 module.json 的规则），收到 ${JSON.stringify(id)}`);
  }

  // 文件名前缀与 id 必须一致：否则"哪个模块没起"要靠猜。
  const expectedPrefix = `${path.basename(file).replace(/\.launch\.json$/, '')}`;
  if (expectedPrefix !== id) {
    fail(file, `文件名前缀 "${expectedPrefix}" 与 id "${id}" 不一致`);
  }

  if (typeof parsed.moduleRoot !== 'string' || parsed.moduleRoot.length === 0) {
    fail(file, 'moduleRoot 必须是非空字符串（相对仓库根，也可写绝对路径）');
  }

  if (parsed.priority !== undefined && !Number.isInteger(parsed.priority)) {
    fail(file, `priority 必须是整数，收到 ${JSON.stringify(parsed.priority)}`);
  }

  if (parsed.notes !== undefined && typeof parsed.notes !== 'string') {
    fail(file, 'notes 必须是字符串');
  }

  if (!Array.isArray(parsed.services) || parsed.services.length === 0) {
    fail(file, 'services 必须是非空的数组');
  }

  const rawServices = parsed.services.map((raw, index) => readService(file, raw, index));

  const names = new Set();
  for (const service of rawServices) {
    if (names.has(service.name)) {
      fail(file, `services 里 name "${service.name}" 重复`);
    }
    names.add(service.name);
  }

  const env = parsed.env === undefined ? {} : readStringMap(file, parsed.env, 'env');
  const rawIsolated = parsed.isolatedEnv === undefined ? {} : readStringMap(file, parsed.isolatedEnv, 'isolatedEnv');

  const moduleRoot = path.isAbsolute(parsed.moduleRoot)
    ? parsed.moduleRoot
    : path.resolve(repoRoot, parsed.moduleRoot);

  // isolatedEnv 的值是目录，按 moduleRoot 解析成绝对路径——**只解析，不创建**：
  // 读取清单这件事不该有副作用，建目录由调用方（dev-all）在自己那步做。
  const isolatedEnv = Object.fromEntries(
    Object.entries(rawIsolated).map(([key, value]) => [
      key,
      path.isAbsolute(value) ? value : path.resolve(moduleRoot, value),
    ]),
  );

  const sharedEnv = live ? env : { ...env, ...isolatedEnv };

  // 读 `build` 要在 moduleRoot 解析之后：它的 `cwd` 相对 moduleRoot。
  const build = parsed.build === undefined ? null : readBuild(file, parsed.build, moduleRoot);

  // 只有一个服务时标签省掉 ":name"——单服务模块打印成 `[cosight-viewer]` 比
  // `[cosight-viewer:server]` 好读，多服务模块才需要区分。
  const services = rawServices.map((service) => ({
    ...service,
    label: rawServices.length === 1 ? id : `${id}:${service.name}`,
    cwd: path.resolve(moduleRoot, service.cwd),
    env: { ...sharedEnv },
  }));

  return {
    id,
    file,
    priority: parsed.priority ?? 100,
    notes: parsed.notes ?? null,
    moduleRoot,
    build,
    isolatedEnv,
    live,
    services,
  };
}

/**
 * 扫描目录里所有 `<id>.launch.json`，按 priority 升序、id 字典序返回。
 * 目录不存在返回空数组（还没登记任何模块的启动方式，是正常状态）。
 *
 * @param {string} modulesDir 仓库里的 `framework/docs/modules`
 * @param {{repoRoot: string, live?: boolean}} options
 */
export function scanLaunchEntries(modulesDir, options) {
  let names;
  try {
    names = fs.readdirSync(modulesDir);
  } catch (error) {
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  }

  const files = names
    .filter((name) => name.endsWith('.launch.json'))
    .map((name) => path.join(modulesDir, name))
    .toSorted();

  const entries = files.map((file) => readLaunchEntry(file, options));

  const priorities = new Map();
  for (const entry of entries) {
    const seen = priorities.get(entry.priority);
    if (seen !== undefined) {
      throw new Error(
        `启动优先级冲突：${seen} 与 ${entry.id} 都写了 priority = ${entry.priority}。` +
          '两者顺序将变得不确定，请给其中一个换一个值（建议留 10 的间隔）。',
      );
    }
    priorities.set(entry.priority, entry.id);
  }

  return entries.toSorted((a, b) => (a.priority === b.priority ? a.id.localeCompare(b.id) : a.priority - b.priority));
}

/** `isolatedEnv` 里声明的目录（已解析成绝对路径）。调用方负责 `mkdir -p`。 */
export function listIsolatedDirs(entry) {
  return Object.values(entry.isolatedEnv);
}
