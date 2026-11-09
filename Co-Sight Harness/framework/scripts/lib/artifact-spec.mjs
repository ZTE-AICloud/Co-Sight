/**
 * 装配态模块清单（`docs/modules/<id>.artifact.json`）的读取与校验。
 *
 * ── 为什么要第二份清单，而不是复用 `<id>.launch.json` ────────────────────
 *
 * `launch.json` 描述的是"在这台开发机上怎么把模块跑起来"：命令是 `npm run dev`，
 * 工作目录相对**仓库根**，还会注入隔离的 home。产物里没有仓库、没有 npm 装好的
 * 开发工具链，这段描述整个不成立。
 *
 * 装配态要回答的是另一组问题："哪些文件进包、构建怎么做、装到用户机器上用什么命令起"。
 * 混进 `launch.json` 会让一份文件同时服务两个互斥的场景，且打包脚本必须去猜
 * "这一行是不是只该在开发态生效"。所以分成两份，各自一个消费者：
 *
 *   `<id>.launch.json`    → `dev-all.mjs`（开发编排）
 *   `<id>.artifact.json`  → `package.mjs`（搬运 + 构建）与 `start.mjs`（拉起）
 *
 * 两份清单的 `services.cwd` / `services.command` 长得很像，但**取值不同**：
 * 开发态是 `npm run dev`，装配态是 `node server/index.js` 这种不需要工具链的命令。
 * 它们不是同一件事的两份写法，别试图合并。
 *
 * ── `bundle` 段只有打包脚本读 ──────────────────────────────────────────
 *
 * `start.mjs` 只消费 `services`。`bundle`（进包哪些文件、构建怎么做）在安装后的机器上
 * 没有意义——产物里的模块目录已经是搬运与构建的结果。同一份文件里放两段，
 * 是为了让"这个模块怎么打包、怎么运行"在一处写完，避免两处漂移；代价是
 * 两个消费者各读一段，所以这里把边界写死：`resolveSpecForRuntime` 返回的对象里
 * **没有** `bundle`。
 *
 * ── 越界检查不是洁癖 ────────────────────────────────────────────────────
 *
 * 清单里的 `cwd` 与 `command` 最终会变成一次 `spawn`。清单在产物里，
 * 而能改产物的人本来就能改 `start.mjs`，所以这里不新增信任边界；但一个写错的
 * `"cwd": "../../.."` 会让模块的进程跑到框架目录外面去，排查时完全看不出是清单的问题。
 * 当场报错比事后猜便宜。
 */

import fs from 'node:fs';
import path from 'node:path';

import { stripBom } from './text.mjs';

export const ARTIFACT_SPEC_SCHEMA_VERSION = 1;
export const ARTIFACT_SPEC_FILE_NAME = 'artifact.json';

/**
 * 数据目录占位符。产物里的模块需要往"用户的数据目录"写东西（会话库、隔离 home），
 * 而它们在包里的位置和用户解压到哪无关——只有 `start.mjs` 知道 `--home` 是什么。
 * 用一个占位符把这件事交给它，比让清单写死 `~` 或相对路径都可靠：
 * 前者在 Windows 上解析规则不同，后者会把数据写进产物目录里。
 */
export const DATA_DIR_PLACEHOLDER = '{{dataDir}}';

/**
 * 框架地址占位符。模块启动后要回调框架（例如 smart-factory 读工作区列表），
 * 而框架端口是 `start.mjs --port` 决定的，清单不能写死。与 `{{dataDir}}` 一样，
 * 只支持白名单，写错一律报错。
 */
export const FRAMEWORK_URL_PLACEHOLDER = '{{frameworkUrl}}';

/** `startAfter` 目前只允许这一个值：等框架 `/api/health` 就绪后再起。 */
export const START_AFTER_FRAMEWORK = 'framework';

export const DEFAULT_READY_PATH = '/';
export const DEFAULT_READY_TIMEOUT_MS = 30_000;
const DEFAULT_BUILD_TIMEOUT_MS = 300_000;
// 安装要联网、要从缓存里拷一大坨文件，比构建慢得多：10 分钟起步，
// 真的更久的部署不该放在打包期做。
const DEFAULT_INSTALL_TIMEOUT_MS = 600_000;
const DEFAULT_PREPARE_TIMEOUT_MS = 30_000;

const MODULE_ID_PATTERN = /^[a-z][a-z0-9-]{1,62}$/;
/** 与 `project.mjs` 的 `ARTIFACT_TARGETS` 同一套命名（`<os>-<arch>`）。 */
const PLATFORM_PATTERN = /^(?:linux|win32|darwin)-(?:x64|arm64)$/;
/** POSIX 环境变量名；Windows 上同样适用。 */
const ENV_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

const TOP_LEVEL_FIELDS = new Set([
  'schemaVersion',
  'id',
  'moduleRoot',
  'priority',
  'bundle',
  'services',
  'env',
  'prepare',
  'startAfter',
  'platforms',
  'notes',
]);
const BUNDLE_FIELDS = new Set([
  'include',
  'exclude',
  'build',
  'builds',
  'install',
  'assets',
  'database',
  'dependencyRoots',
  'required',
  'executable',
]);
const BUILD_FIELDS = new Set(['command', 'cwd', 'inputs', 'outputs', 'timeoutMs', 'env']);
// 安装步骤没有 inputs/outputs：它不是"重建产物"，而是"补齐缺件"，
// 什么时候跑由打包脚本按断言结果决定，没有陈旧与否的判断。
const INSTALL_FIELDS = new Set(['command', 'cwd', 'timeoutMs', 'env']);
const SERVICE_FIELDS = new Set([
  'name',
  'cwd',
  'command',
  'port',
  'readyPath',
  'readyTimeoutMs',
  'env',
]);
const PREPARE_FIELDS = new Set(['name', 'cwd', 'command', 'timeoutMs']);
const ASSET_FIELDS = new Set(['from', 'to', 'exclude']);
const DATABASE_FIELDS = new Set(['command', 'cwd', 'template', 'file']);

function fail(file, message) {
  throw new Error(`${file} 的装配态清单有问题：${message}`);
}

function assertPlainObject(file, value, scope) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail(file, `${scope}必须是对象`);
  }
}

function assertKnownFields(file, object, known, scope) {
  for (const key of Object.keys(object)) {
    if (!known.has(key)) {
      fail(
        file,
        `${scope}出现未知字段 "${key}"（可选：${[...known].join(' / ')}）。` +
          '未知字段一律报错，避免写错名字后静默失效。',
      );
    }
  }
}

function readStringArray(file, value, scope, { allowEmpty = false } = {}) {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) {
    fail(file, `${scope} 必须是${allowEmpty ? '' : '非空的'}字符串数组`);
  }
  for (const [position, entry] of value.entries()) {
    if (typeof entry !== 'string' || entry.length === 0) {
      fail(file, `${scope}[${position}] 必须是非空字符串`);
    }
  }
  return [...value];
}

function readCommand(file, value, scope) {
  if (!Array.isArray(value) || value.length === 0) {
    fail(file, `${scope} 必须是"程序 + 参数"的非空数组，例如 ["node", "server/index.js"]`);
  }
  for (const [position, part] of value.entries()) {
    if (typeof part !== 'string' || part.length === 0) {
      fail(file, `${scope}[${position}] 必须是非空字符串`);
    }
  }
  return [...value];
}

function readPort(file, value, scope) {
  if (!Number.isInteger(value) || value < 1 || value > 65_535) {
    fail(file, `${scope} 必须是 1..65535 的整数，收到 ${JSON.stringify(value)}`);
  }
  return value;
}

/**
 * 环境变量表。
 *
 * 服务级 env 不允许空值：空字符串在 `spawn` 里等于"设成空"，与"没设"在
 * 大部分程序里行为不同，写清单的人通常想要的是后者。构建期 env 例外——
 * `VITE_WS_BASE_URL=""` 是一个有意义的取值（关掉绝对地址覆盖）。
 */
function readEnvMap(file, value, scope, { allowEmptyValue = false } = {}) {
  assertPlainObject(file, value, scope);
  const env = {};
  for (const [key, entry] of Object.entries(value)) {
    if (!ENV_KEY_PATTERN.test(key)) {
      fail(file, `${scope}.${key} 不是合法的环境变量名`);
    }
    if (typeof entry !== 'string' || (!allowEmptyValue && entry.length === 0)) {
      fail(
        file,
        `${scope}.${key} 必须是${allowEmptyValue ? '' : '非空的'}字符串（收到 ${JSON.stringify(entry)}）`,
      );
    }
    env[key] = entry;
  }
  return env;
}

/** 只允许相对路径，且不许用 `..` 跳出模块目录。 */
function assertRelativePath(file, value, scope) {
  if (typeof value !== 'string' || value.length === 0) {
    fail(file, `${scope} 必须是非空字符串`);
  }
  const segments = value.split(/[\\/]/);
  if (path.isAbsolute(value) || segments.includes('..')) {
    fail(file, `${scope} 必须是模块目录内的相对路径，收到 ${JSON.stringify(value)}`);
  }
}

function readPrepare(file, raw, index) {
  const scope = `prepare[${index}]`;
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, PREPARE_FIELDS, scope);

  if (typeof raw.name !== 'string' || !/^[a-z][a-z0-9-]*$/.test(raw.name)) {
    fail(file, `${scope}.name 必须是小写字母/数字/连字符，收到 ${JSON.stringify(raw.name)}`);
  }
  if (typeof raw.cwd !== 'string' || raw.cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对模块目录，模块根写 "."）`);
  }
  if (raw.timeoutMs !== undefined && (!Number.isInteger(raw.timeoutMs) || raw.timeoutMs <= 0)) {
    fail(file, `${scope}.timeoutMs 必须是正整数毫秒数`);
  }

  return {
    name: raw.name,
    cwd: raw.cwd,
    command: readCommand(file, raw.command, `${scope}.command`),
    timeoutMs: raw.timeoutMs ?? DEFAULT_PREPARE_TIMEOUT_MS,
  };
}

function readAsset(file, raw, index) {
  const scope = `bundle.assets[${index}]`;
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, ASSET_FIELDS, scope);

  if (typeof raw.from !== 'string' || raw.from.length === 0) {
    fail(file, `${scope}.from 必须是非空字符串（相对仓库根，也可写绝对路径）`);
  }
  assertRelativePath(file, raw.to, `${scope}.to`);

  // exclude 只对目录 asset 有意义：按路径段名匹配，命中段所在子树整棵剔除（任何层级都算）。
  // 段名语义 = 禁分隔符与相对段，防止它被误用成路径模式。
  const exclude = raw.exclude === undefined
    ? undefined
    : readStringArray(file, raw.exclude, `${scope}.exclude`);
  if (exclude?.some((segment) => /[\\/]/.test(segment) || segment === '.' || segment === '..')) {
    fail(file, `${scope}.exclude 每条必须是单个路径段名（不含 / \\ . ..），收到 ${JSON.stringify(raw.exclude)}`);
  }

  return { from: raw.from, to: raw.to, exclude };
}

function readDatabase(file, raw) {
  const scope = 'bundle.database';
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, DATABASE_FIELDS, scope);

  const cwd = raw.cwd ?? '.';
  if (typeof cwd !== 'string' || cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对模块目录）`);
  }
  assertRelativePath(file, raw.template, `${scope}.template`);
  if (typeof raw.file !== 'string' || raw.file.length === 0 || /[\\/]/.test(raw.file) || raw.file === '.' || raw.file === '..') {
    fail(file, `${scope}.file 必须是不带路径分隔符的文件名，收到 ${JSON.stringify(raw.file)}`);
  }

  return {
    command: readCommand(file, raw.command, `${scope}.command`),
    cwd,
    template: raw.template,
    file: raw.file,
  };
}

function readService(file, raw, index) {
  const scope = `services[${index}]`;
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, SERVICE_FIELDS, scope);

  if (typeof raw.name !== 'string' || !/^[a-z][a-z0-9-]*$/.test(raw.name)) {
    fail(file, `${scope}.name 必须是小写字母/数字/连字符，收到 ${JSON.stringify(raw.name)}`);
  }
  if (typeof raw.cwd !== 'string' || raw.cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对模块目录，模块根写 "."）`);
  }
  if (raw.readyPath !== undefined && (typeof raw.readyPath !== 'string' || !raw.readyPath.startsWith('/'))) {
    fail(file, `${scope}.readyPath 必须以 / 开头，收到 ${JSON.stringify(raw.readyPath)}`);
  }
  if (
    raw.readyTimeoutMs !== undefined &&
    (!Number.isInteger(raw.readyTimeoutMs) || raw.readyTimeoutMs <= 0)
  ) {
    fail(file, `${scope}.readyTimeoutMs 必须是正整数毫秒数`);
  }

  const env = raw.env === undefined ? {} : readEnvMap(file, raw.env, `${scope}.env`);

  return {
    name: raw.name,
    cwd: raw.cwd,
    command: readCommand(file, raw.command, `${scope}.command`),
    port: readPort(file, raw.port, `${scope}.port`),
    readyPath: raw.readyPath ?? DEFAULT_READY_PATH,
    readyTimeoutMs: raw.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS,
    env,
  };
}

function readBuild(file, raw, scope = 'bundle.build') {
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, BUILD_FIELDS, scope);

  const cwd = raw.cwd ?? '.';
  if (typeof cwd !== 'string' || cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对模块目录）`);
  }
  if (raw.timeoutMs !== undefined && (!Number.isInteger(raw.timeoutMs) || raw.timeoutMs <= 0)) {
    fail(file, `${scope}.timeoutMs 必须是正整数毫秒数`);
  }

  return {
    command: readCommand(file, raw.command, `${scope}.command`),
    cwd,
    inputs: raw.inputs === undefined ? ['.'] : readStringArray(file, raw.inputs, `${scope}.inputs`),
    outputs: readStringArray(file, raw.outputs, `${scope}.outputs`),
    timeoutMs: raw.timeoutMs ?? DEFAULT_BUILD_TIMEOUT_MS,
    env: raw.env === undefined
      ? {}
      : readEnvMap(file, raw.env, `${scope}.env`, { allowEmptyValue: true }),
  };
}

/**
 * 读一条安装步骤。
 *
 * 与 `build` 的区别是**没有 `inputs` / `outputs`**：安装不是"产物旧了就重建"，
 * 而是"断言发现缺件才补"。打包脚本按当前缺什么决定跑不跑，
 * 不在这里声明触发条件——两处各写一份"什么时候算缺"，迟早会漂移。
 */
function readInstall(file, raw, scope = 'bundle.install') {
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, INSTALL_FIELDS, scope);

  const cwd = raw.cwd ?? '.';
  if (typeof cwd !== 'string' || cwd.length === 0) {
    fail(file, `${scope}.cwd 必须是非空字符串（相对模块目录）`);
  }
  if (raw.timeoutMs !== undefined && (!Number.isInteger(raw.timeoutMs) || raw.timeoutMs <= 0)) {
    fail(file, `${scope}.timeoutMs 必须是正整数毫秒数`);
  }

  return {
    command: readCommand(file, raw.command, `${scope}.command`),
    cwd,
    timeoutMs: raw.timeoutMs ?? DEFAULT_INSTALL_TIMEOUT_MS,
    env: raw.env === undefined
      ? {}
      : readEnvMap(file, raw.env, `${scope}.env`, { allowEmptyValue: true }),
  };
}

function readBundle(file, raw) {
  const scope = 'bundle';
  assertPlainObject(file, raw, scope);
  assertKnownFields(file, raw, BUNDLE_FIELDS, scope);

  // 单构建与多构建二选一：同时写两处时，"到底跑哪几个"没有唯一答案。
  if (raw.build !== undefined && raw.builds !== undefined) {
    fail(file, 'bundle.build 与 bundle.builds 只能写一个（多构建请统一用 builds）');
  }
  let builds = [];
  if (raw.builds !== undefined) {
    if (!Array.isArray(raw.builds) || raw.builds.length === 0) {
      fail(file, 'bundle.builds 必须是非空数组');
    }
    builds = raw.builds.map((entry, index) => readBuild(file, entry, `bundle.builds[${index}]`));
  } else if (raw.build !== undefined) {
    builds = [readBuild(file, raw.build)];
  }

  let install = [];
  if (raw.install !== undefined) {
    if (!Array.isArray(raw.install)) {
      fail(file, 'bundle.install 必须是数组（按顺序尝试，补上了就停）');
    }
    install = raw.install.map((entry, index) => readInstall(file, entry, `bundle.install[${index}]`));
  }

  const assets = raw.assets === undefined
    ? []
    : (Array.isArray(raw.assets) ? raw.assets : fail(file, 'bundle.assets 必须是数组'))
        .map((entry, index) => readAsset(file, entry, index));

  const destinations = new Set();
  for (const asset of assets) {
    if (destinations.has(asset.to)) {
      fail(file, `bundle.assets 里有两份文件要写到同一个位置：${asset.to}`);
    }
    destinations.add(asset.to);
  }

  const stringList = (value, name, { allowEmpty = true } = {}) =>
    value === undefined ? [] : readStringArray(file, value, `${scope}.${name}`, { allowEmpty });

  return {
    include: readStringArray(file, raw.include, `${scope}.include`),
    exclude: stringList(raw.exclude, 'exclude'),
    build: builds[0] ?? null,
    builds,
    install,
    assets,
    database: raw.database === undefined ? null : readDatabase(file, raw.database),
    dependencyRoots: stringList(raw.dependencyRoots, 'dependencyRoots'),
    required: stringList(raw.required, 'required'),
    executable: stringList(raw.executable, 'executable'),
  };
}

/**
 * 读一份装配态清单。只做解析与校验，**不解析任何相对路径**——
 * 同一份文件在打包机上相对仓库根、在产物里相对模块目录，两个基准由调用方给。
 *
 * @param {string} file 清单的绝对路径
 */
export function readArtifactSpec(file) {
  let parsed;
  try {
    // stripBom：这份文件也是人手写的，Windows 记事本会写出 BOM。
    parsed = JSON.parse(stripBom(fs.readFileSync(file, 'utf8')));
  } catch (error) {
    throw new Error(`读不出装配态清单 ${file}：${error.message}`, { cause: error });
  }

  assertPlainObject(file, parsed, '清单');
  assertKnownFields(file, parsed, TOP_LEVEL_FIELDS, '清单');

  if (parsed.schemaVersion !== ARTIFACT_SPEC_SCHEMA_VERSION) {
    fail(file, `schemaVersion 必须是 ${ARTIFACT_SPEC_SCHEMA_VERSION}，收到 ${JSON.stringify(parsed.schemaVersion)}`);
  }

  if (typeof parsed.id !== 'string' || !MODULE_ID_PATTERN.test(parsed.id)) {
    fail(file, `id 必须是小写字母/数字/连字符（同 module.json 的规则），收到 ${JSON.stringify(parsed.id)}`);
  }

  // 文件名前缀与 id 必须一致，否则"哪个模块没被拉起"要靠猜。
  // 运行时文件名固定是 artifact.json，目录名就是 id，所以两种形态各查一次。
  const baseName = path.basename(file);
  if (baseName !== ARTIFACT_SPEC_FILE_NAME) {
    const prefix = baseName.replace(/\.artifact\.json$/, '');
    if (prefix !== parsed.id) {
      fail(file, `文件名前缀 "${prefix}" 与 id "${parsed.id}" 不一致`);
    }
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

  const services = parsed.services.map((raw, index) => readService(file, raw, index));
  const names = new Set();
  for (const service of services) {
    if (names.has(service.name)) {
      fail(file, `services 里 name "${service.name}" 重复`);
    }
    names.add(service.name);
  }

  // `prepare` 是"起服务之前必须跑完的一次性动作"（建库、生成配置）。名字要唯一：
  // 启动日志与失败归因都靠这个名字，重名时看不出是哪一步出了问题。
  let prepare = [];
  if (parsed.prepare !== undefined) {
    if (!Array.isArray(parsed.prepare)) {
      fail(file, 'prepare 必须是数组');
    }
    prepare = parsed.prepare.map((raw, index) => readPrepare(file, raw, index));
    const prepareNames = new Set();
    for (const step of prepare) {
      if (prepareNames.has(step.name)) {
        fail(file, `prepare 里 name "${step.name}" 重复`);
      }
      prepareNames.add(step.name);
    }
  }

  if (parsed.startAfter !== undefined && parsed.startAfter !== START_AFTER_FRAMEWORK) {
    fail(
      file,
      `startAfter 目前只支持 "${START_AFTER_FRAMEWORK}"（等框架 /api/health 就绪后再起），` +
        `收到 ${JSON.stringify(parsed.startAfter)}`,
    );
  }

  let platforms = null;
  if (parsed.platforms !== undefined) {
    platforms = readStringArray(file, parsed.platforms, 'platforms');
    const seen = new Set();
    for (const [index, platform] of platforms.entries()) {
      if (!PLATFORM_PATTERN.test(platform)) {
        fail(file, `platforms[${index}] 必须是 "<os>-<arch>"（如 linux-x64），收到 ${JSON.stringify(platform)}`);
      }
      if (seen.has(platform)) {
        fail(file, `platforms 里 "${platform}" 重复`);
      }
      seen.add(platform);
    }
  }

  const env = parsed.env === undefined ? {} : readEnvMap(file, parsed.env, 'env');

  return {
    file,
    id: parsed.id,
    moduleRoot: parsed.moduleRoot,
    priority: parsed.priority ?? 100,
    notes: parsed.notes ?? null,
    env,
    prepare,
    startAfter: parsed.startAfter ?? null,
    platforms,
    bundle: readBundle(file, parsed.bundle),
    services,
  };
}

/**
 * 扫描产物里的 `modules/`，读出每个模块目录下的 `artifact.json`。
 *
 * 目录不存在返回空结果（没有打进任何模块是正常状态）；单个模块的清单坏掉
 * **不**让整个启动失败——把它记进 `problems`，由调用方打印出来。
 *
 * @param {string} modulesDir 产物里的 `modules/`
 * @returns {{specs: Array<ReturnType<typeof readArtifactSpec>>, problems: Array<{id: string, message: string}>}}
 */
export function scanArtifactSpecs(modulesDir) {
  let dirents;
  try {
    dirents = fs.readdirSync(modulesDir, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { specs: [], problems: [] };
    }
    throw error;
  }

  const specs = [];
  const problems = [];

  for (const dirent of dirents.filter((item) => item.isDirectory()).toSorted((a, b) => a.name.localeCompare(b.name))) {
    const file = path.join(modulesDir, dirent.name, ARTIFACT_SPEC_FILE_NAME);
    if (!fs.existsSync(file)) {
      problems.push({ id: dirent.name, message: `缺少 ${ARTIFACT_SPEC_FILE_NAME}，这个模块不会被拉起` });
      continue;
    }
    try {
      const spec = readArtifactSpec(file);
      if (spec.id !== dirent.name) {
        problems.push({ id: dirent.name, message: `清单 id 是 "${spec.id}"，与目录名不一致` });
        continue;
      }
      specs.push(spec);
    } catch (error) {
      problems.push({ id: dirent.name, message: error.message });
    }
  }

  const priorities = new Map();
  for (const spec of specs) {
    const seen = priorities.get(spec.priority);
    if (seen !== undefined) {
      problems.push({
        id: spec.id,
        message: `priority ${spec.priority} 与 ${seen} 冲突，启动顺序不确定（建议留 10 的间隔）`,
      });
    }
    priorities.set(spec.priority, spec.id);
  }

  specs.sort((a, b) => (a.priority === b.priority ? a.id.localeCompare(b.id) : a.priority - b.priority));
  return { specs, problems };
}

/** `target` 是否落在 `base` 之内（含 base 本身）。 */
function isInside(base, target) {
  const relative = path.relative(base, target);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function resolveInside(file, base, relative, scope) {
  const absolute = path.resolve(base, relative);
  if (!isInside(base, absolute)) {
    fail(file, `${scope} 指向模块目录之外：${relative} → ${absolute}。模块只能在它自己的目录里运行。`);
  }
  return absolute;
}

/**
 * 替换清单里允许的两个占位符。
 *
 * 只支持白名单，而且**无论有没有替换过都要做残留检查**：写错成 `{{data-dir}}` 时，
 * 静默留下原样会让服务在一个叫 `{{data-dir}}` 的目录里建库——那种现象没人能
 * 联想到是清单写错了。
 */
function substitutePlaceholders(file, value, options) {
  const values = {
    [DATA_DIR_PLACEHOLDER]: options.dataDir,
    [FRAMEWORK_URL_PLACEHOLDER]: options.frameworkUrl,
  };

  let replaced = value;
  for (const [placeholder, replacement] of Object.entries(values)) {
    if (!replaced.includes(placeholder)) {
      continue;
    }
    if (typeof replacement !== 'string' || replacement.length === 0) {
      fail(file, `清单里用了 ${placeholder}，但调用方没有给出对应的值`);
    }
    replaced = replaced.split(placeholder).join(replacement);
  }

  const leftover = /\{\{[^}]*\}\}/.exec(replaced);
  if (leftover !== null) {
    fail(
      file,
      `不支持的占位符 ${leftover[0]}（只支持 ${DATA_DIR_PLACEHOLDER} 与 ${FRAMEWORK_URL_PLACEHOLDER}）`,
    );
  }
  return replaced;
}

/** `node` → 当前进程的可执行文件；其余命令原样返回。 */
function rewriteNodeCommand(command) {
  return command[0] === 'node' ? [process.execPath, ...command.slice(1)] : [...command];
}

/**
 * 产物里的清单 → 可以 spawn 的服务。
 *
 * `command[0] === "node"` 时换成 `process.execPath`：产物里没有任何东西依赖 PATH
 * 上有 `node`（安装脚本要求的 Node 就是当前这个进程），换掉之后
 * "用户装了两个 Node、PATH 指向另一个版本"这类问题整类消失。
 *
 * 顶层 `env` 会并入每个服务的 env，服务自己写的同名键优先——一份模块级配置
 * （数据目录、框架地址）不必在每个服务里重复三遍。
 *
 * @param {ReturnType<typeof readArtifactSpec>} spec
 * @param {{moduleDir: string, dataDir: string, frameworkUrl?: string}} options
 */
export function resolveSpecForRuntime(spec, options) {
  const moduleDir = path.resolve(options.moduleDir);
  const substitute = (value) => substitutePlaceholders(spec.file, value, options);

  const sharedEnv = Object.fromEntries(
    Object.entries(spec.env).map(([key, value]) => [key, substitute(value)]),
  );
  const serviceEnv = (env) => ({
    ...sharedEnv,
    ...Object.fromEntries(Object.entries(env).map(([key, value]) => [key, substitute(value)])),
  });

  return {
    id: spec.id,
    priority: spec.priority,
    moduleDir,
    startAfter: spec.startAfter,
    env: sharedEnv,
    prepare: spec.prepare.map((step) => ({
      name: step.name,
      label: `${spec.id}:${step.name}`,
      cwd: resolveInside(spec.file, moduleDir, step.cwd, `prepare.${step.name}.cwd`),
      command: rewriteNodeCommand(step.command),
      timeoutMs: step.timeoutMs,
      env: serviceEnv({}),
    })),
    services: spec.services.map((service) => ({
      name: service.name,
      label: spec.services.length === 1 ? spec.id : `${spec.id}:${service.name}`,
      cwd: resolveInside(spec.file, moduleDir, service.cwd, `services.${service.name}.cwd`),
      command: rewriteNodeCommand(service.command),
      port: service.port,
      readyPath: service.readyPath,
      readyTimeoutMs: service.readyTimeoutMs,
      env: serviceEnv(service.env),
    })),
  };
}

/**
 * 仓库里的清单 → 打包脚本要的绝对路径。
 *
 * @param {ReturnType<typeof readArtifactSpec>} spec
 * @param {{repoRoot: string}} options
 */
export function resolveSpecForPackaging(spec, options) {
  const moduleRoot = path.isAbsolute(spec.moduleRoot)
    ? spec.moduleRoot
    : path.resolve(options.repoRoot, spec.moduleRoot);

  const builds = spec.bundle.builds.map((build, index) => ({
    ...build,
    // 多构建时单数 scope 会让人以为只有一条规则，带上序号才定位得到。
    cwd: resolveInside(spec.file, moduleRoot, build.cwd, `bundle.builds[${index}].cwd`),
  }));

  return {
    id: spec.id,
    file: spec.file,
    moduleRoot,
    priority: spec.priority,
    notes: spec.notes,
    platforms: spec.platforms,
    include: [...spec.bundle.include],
    exclude: [...spec.bundle.exclude],
    build: builds[0] ?? null,
    builds,
    install: spec.bundle.install.map((step, index) => ({
      ...step,
      // 与构建同理：cwd 必须落在模块目录内，否则这条命令会跑到别人的 checkout 里装依赖。
      cwd: resolveInside(spec.file, moduleRoot, step.cwd, `bundle.install[${index}].cwd`),
      // `node scripts/xxx.mjs` 换成当前解释器：打包机上可能有多个 Node，
      // 用 PATH 里的那个会把"验证通过"建立在错误的运行时上。
      command: rewriteNodeCommand(step.command),
    })),
    assets: spec.bundle.assets.map((asset) => ({
      from: path.isAbsolute(asset.from) ? asset.from : path.resolve(options.repoRoot, asset.from),
      to: asset.to,
      exclude: asset.exclude,
    })),
    database: spec.bundle.database === null
      ? null
      : {
          ...spec.bundle.database,
          cwd: resolveInside(spec.file, moduleRoot, spec.bundle.database.cwd, 'bundle.database.cwd'),
        },
    dependencyRoots: [...spec.bundle.dependencyRoots],
    required: [...spec.bundle.required],
    executable: [...spec.bundle.executable],
  };
}
