/**
 * 把产物里的五个插件装进 Claude Code，并保证重复启动是幂等的。
 *
 * 三条来自实测的约束决定了这里的形状（详见 docs/install-preflight-and-plugins.md §5）：
 *   1. `plugin install` 对已安装插件是 no-op——不能靠它升级；
 *   2. `plugin update` 只在版本号变化时复制内容——同版本内容变化会被跳过；
 *   3. Windows 上 `claude` 常是 `.cmd`，Node 不能直接 spawn（见 cli-exec.mjs）。
 *
 * 所以每次启动都同时比 **版本** 与 **内容哈希**，再决定装 / 升 / 重装 / 跳过。
 * 已经装好的前几个插件不回滚：回滚意味着卸载用户可能本来就在用的东西。
 */

import fs from 'node:fs';
import path from 'node:path';

import { claudeConfigDir } from './checks/claude.mjs';
import { buildSpawnSpec, describeRunFailure, lastLine, runProcess } from './cli-exec.mjs';
import { collectPluginFiles, hashPluginDirectory } from './plugin-hash.mjs';

/** 插件阶段的退出码。 */
export const EXIT_PLUGINS = 12;

/** 单条 claude 命令的上限。实测安装都在秒级，120s 只用来兜住"卡死"。 */
export const PLUGIN_COMMAND_TIMEOUT_MS = 120_000;

/**
 * 全机插件市场的根（相对 Claude 配置目录）。
 *
 * 导出是为了让卸载走同一个位置：那边要按市场名精确删掉我们复制进去的载荷副本，
 * 两处各写一遍这个相对路径，改了一边就会删错地方。
 */
export const MARKETPLACES_SUBDIR = path.join('plugins', 'marketplaces');
const INSTALL_LOCK_NAME = '.install.lock';

function commandText(args) {
  return `claude ${args.join(' ')}`;
}

/**
 * 这次运行该不该碰 Claude Code。
 *
 * 三种入口（`--install`、产物布局下的 `start`、`--self-check`）共用这一条判定，
 * 避免"某个入口忘了看 `--skip-plugins`"——那个 bug 真的出现过：`--install`
 * 分支绕过判定，用户明确说别碰，仍然往 `~/.claude` 写了五个 marketplace。
 *
 * 纯函数：只看参数，不碰文件系统。
 *
 * @param {{skipPlugins?: boolean, install?: boolean, layoutMode?: string,
 *   pluginMode?: string}} input
 */
export function shouldInstallPlugins(input) {
  if (input.skipPlugins === true || input.pluginMode === 'none') {
    return false;
  }
  return input.install === true || input.layoutMode === '产物布局';
}

/**
 * 版本与内容都相同才算"已是最新"。
 *
 * 纯函数：不碰文件系统，单测可以直接覆盖四行判定表。
 *
 * @param {{installedVersion?: string|null, payloadVersion: string,
 *   cacheHash?: string|null, payloadHash: string}} input
 * @returns {'install'|'update'|'reinstall'|'none'}
 */
export function decidePluginAction(input) {
  const installedVersion = input.installedVersion ?? null;
  if (installedVersion === null || installedVersion === '') {
    return 'install';
  }
  if (installedVersion !== input.payloadVersion) {
    return 'update';
  }
  if ((input.cacheHash ?? null) !== input.payloadHash) {
    return 'reinstall';
  }
  return 'none';
}

/**
 * 同名 marketplace 怎么处理。
 *
 * 默认**不覆盖 git 来源**：`zte-ai-lab` 这类名字在企业内网很可能已经指向
 * 别人的仓库，覆盖会让用户原有的插件来源消失。
 *
 * @param {{registered?: {source?: unknown, installLocation?: string}|null,
 *   canonicalDir: string, replace?: boolean}} input
 * @returns {'add'|'refresh'|'replace'|'block'}
 */
export function decideMarketplaceAction(input) {
  const registered = input.registered ?? null;
  if (registered === null) {
    return 'add';
  }
  const kind = marketplaceSourceKind(registered.source);
  if (kind === 'git') {
    return input.replace === true ? 'replace' : 'block';
  }
  if (
    typeof registered.installLocation === 'string' &&
    path.resolve(registered.installLocation) === path.resolve(input.canonicalDir)
  ) {
    return 'refresh';
  }
  return 'replace';
}

function marketplaceSourceKind(source) {
  if (typeof source === 'string') {
    return source;
  }
  if (source !== null && typeof source === 'object' && typeof source.source === 'string') {
    return source.source;
  }
  return '';
}

function splitPluginId(id) {
  const at = id.indexOf('@');
  return at === -1
    ? { plugin: id, marketplace: '' }
    : { plugin: id.slice(0, at), marketplace: id.slice(at + 1) };
}

/**
 * 解析 `claude plugin list --json`。
 *
 * @param {string} text
 * @returns {Array<{id: string, plugin: string, marketplace: string, version: string,
 *   scope: string, installPath: string|null}>}
 */
export function parsePluginList(text) {
  const data = JSON.parse(text);
  if (!Array.isArray(data)) {
    throw new Error('plugin list --json 的输出不是数组');
  }
  return data
    .filter((item) => typeof item?.id === 'string')
    .map((item) => ({
      id: item.id,
      ...splitPluginId(item.id),
      version: typeof item.version === 'string' ? item.version : '',
      scope: typeof item.scope === 'string' ? item.scope : '',
      installPath: typeof item.installPath === 'string' ? item.installPath : null,
    }));
}

/**
 * 解析 `claude plugin marketplace list --json`。
 *
 * `source` 在 CLI 里是字符串、在状态文件里是对象——在这里保留原始值，
 * 判定时用 `marketplaceSourceKind` 归一化。
 *
 * @param {string} text
 */
export function parseMarketplaceList(text) {
  const data = JSON.parse(text);
  if (!Array.isArray(data)) {
    throw new Error('marketplace list --json 的输出不是数组');
  }
  return data
    .filter((item) => typeof item?.name === 'string')
    .map((item) => ({
      name: item.name,
      source: item.source,
      installLocation: typeof item.installLocation === 'string' ? item.installLocation : null,
    }));
}

function readJsonQuietly(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * 从状态文件读兜底信息（CLI 不可用或输出坏了时）。
 *
 * @param {string} configDir
 */
export function readStateFromFiles(configDir) {
  const pluginsFile = path.join(configDir, 'plugins', 'installed_plugins.json');
  const marketsFile = path.join(configDir, 'plugins', 'known_marketplaces.json');

  const installed = readJsonQuietly(pluginsFile);
  const known = readJsonQuietly(marketsFile);
  if (installed === null && known === null) {
    return null;
  }

  const plugins = [];
  const entries = installed?.plugins ?? {};
  if (entries !== null && typeof entries === 'object') {
    for (const [id, records] of Object.entries(entries)) {
      if (!Array.isArray(records) || records.length === 0) {
        continue;
      }
      // 同 id 可能在多个 scope 出现；用户级优先（我们只装 user scope）。
      const record = records.find((item) => item?.scope === 'user') ?? records[0];
      plugins.push({
        id,
        ...splitPluginId(id),
        version: typeof record?.version === 'string' ? record.version : '',
        scope: typeof record?.scope === 'string' ? record.scope : '',
        installPath: typeof record?.installPath === 'string' ? record.installPath : null,
      });
    }
  }

  const marketplaces = [];
  if (known !== null && typeof known === 'object') {
    for (const [name, record] of Object.entries(known)) {
      marketplaces.push({
        name,
        source: record?.source,
        installLocation:
          typeof record?.installLocation === 'string' ? record.installLocation : null,
      });
    }
  }

  return { plugins, marketplaces };
}

/**
 * 读一次插件与 marketplace 状态，批量拿全量（不要每个插件各调一次）。
 *
 * @param {{executable: string, platform?: string, configDir?: string,
 *   homeDir?: string, env?: NodeJS.ProcessEnv, run?: Function, timeoutMs?: number}} options
 */
export async function readPluginState(options) {
  const platform = options.platform ?? process.platform;
  const run = options.run ?? runProcess;
  const timeoutMs = options.timeoutMs ?? PLUGIN_COMMAND_TIMEOUT_MS;
  const configDir =
    options.configDir ?? claudeConfigDir({ env: options.env, homeDir: options.homeDir });
  const problems = [];

  const call = async (args) => {
    const result = await run(buildSpawnSpec(options.executable, args, { platform }), { timeoutMs });
    if (result.error !== null && result.error !== undefined) {
      return { ok: false, detail: `无法启动：${result.error.message}` };
    }
    if (result.timedOut) {
      return { ok: false, detail: `${Math.round(timeoutMs / 1000)} 秒内没有返回` };
    }
    if (result.code !== 0) {
      return { ok: false, detail: `退出码 ${result.code}：${lastLine(result.stderr)}` };
    }
    return { ok: true, stdout: result.stdout };
  };

  const pluginCall = await call(['plugin', 'list', '--json']);
  const marketCall = await call(['plugin', 'marketplace', 'list', '--json']);

  if (pluginCall.ok && marketCall.ok) {
    try {
      return {
        ok: true,
        source: 'cli',
        plugins: parsePluginList(pluginCall.stdout),
        marketplaces: parseMarketplaceList(marketCall.stdout),
        problems,
      };
    } catch (error) {
      problems.push(`解析 CLI 输出失败：${error.message}`);
    }
  } else {
    if (!pluginCall.ok) {
      problems.push(`plugin list --json 不可用（${pluginCall.detail}）`);
    }
    if (!marketCall.ok) {
      problems.push(`marketplace list --json 不可用（${marketCall.detail}）`);
    }
  }

  const fallback = readStateFromFiles(configDir);
  if (fallback === null) {
    return { ok: false, source: null, plugins: [], marketplaces: [], problems };
  }
  return { ok: true, source: 'files', ...fallback, problems };
}

/* ── 文件与命令 ───────────────────────────────────────────────────────── */

/**
 * 只复制会进产物的那套文件（与哈希同一套排除规则）。
 *
 * 不能整目录 `cp -r`：测试与缓存进了 marketplace 副本后，装出来的 cache
 * 内容与 payload 哈希永远不等，于是每次启动都重装。
 */
function copyPayload(sourceDir, targetDir) {
  fs.rmSync(targetDir, { recursive: true, force: true });
  for (const relative of collectPluginFiles(sourceDir)) {
    const destination = path.join(targetDir, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(path.join(sourceDir, relative), destination);
  }
}

/**
 * `child` 是否在 `parent` 之下（不含 parent 本身）。
 *
 * 导出给卸载用：它要在删掉某个市场的载荷副本之前，确认那个目录确实在市场根之下
 * ——`CLAUDE_CONFIG_DIR` 可以被指到别处，不校验就等于按市场名乱删。
 *
 * @param {string} parent
 * @param {string} child
 */
export function isInside(parent, child) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

/**
 * 安装期间的互斥锁。两个安装进程同时改 `~/.claude` 会互相踩状态。
 *
 * @param {string} home
 * @returns {{release: () => void}}
 */
export function acquireInstallLock(home) {
  fs.mkdirSync(home, { recursive: true });
  const lockPath = path.join(home, INSTALL_LOCK_NAME);
  let fd;
  try {
    fd = fs.openSync(lockPath, 'wx');
  } catch (error) {
    if (error.code === 'EEXIST') {
      throw new Error(
        `另一个安装进程正在运行（锁文件 ${lockPath}）。确认没有其他安装后再试。`,
        { cause: error },
      );
    }
    throw error;
  }
  fs.writeSync(fd, `${process.pid}\n`);
  fs.closeSync(fd);

  let released = false;
  return {
    release: () => {
      if (released) {
        return;
      }
      released = true;
      fs.rmSync(lockPath, { force: true });
    },
  };
}

function failure(plugin, command, detail, remedy) {
  return { plugin, command, detail, remedy };
}

/**
 * 装好五个插件。失败在**任何模块进程出现之前**返回，不抛错——
 * 调用方要统一打印报告并退出 12。
 *
 * @param {{plugins: Array<{id: string, dir: string, plugin: string, marketplace: string,
 *   version: string, sha256: string, path: string}>, executable: string,
 *   home: string, platform?: string, configDir?: string, replaceMarketplace?: boolean,
 *   run?: Function, readState?: Function, log?: (line: string) => void,
 *   timeoutMs?: number}} options
 * @returns {Promise<{ok: boolean, steps: Array<{plugin: string, action: string,
 *   detail: string}>, failure: object|null}>}
 */
export async function ensurePlugins(options) {
  const platform = options.platform ?? process.platform;
  const run = options.run ?? runProcess;
  const timeoutMs = options.timeoutMs ?? PLUGIN_COMMAND_TIMEOUT_MS;
  const log = options.log ?? (() => {});
  const configDir = options.configDir ?? claudeConfigDir({ homeDir: options.home });
  const marketplacesRoot = path.join(configDir, MARKETPLACES_SUBDIR);
  const readState =
    options.readState ??
    (() =>
      readPluginState({
        executable: options.executable,
        platform,
        configDir,
        run,
        timeoutMs,
      }));

  const steps = [];
  const plugins = options.plugins;

  // 同一 marketplace 名只能有一个源目录，否则复制副本时会互相覆盖。
  const byMarketplace = new Map();
  for (const item of plugins) {
    const existing = byMarketplace.get(item.marketplace);
    if (existing !== undefined && existing.dir !== item.dir) {
      return {
        ok: false,
        steps,
        failure: failure(
          item.id,
          null,
          `marketplace ${item.marketplace} 同时由 ${existing.dir} 与 ${item.dir} 提供`,
          ['同一个 marketplace 只能有一个源目录；检查 scripts/artifact/plugins.json'],
        ),
      };
    }
    byMarketplace.set(item.marketplace, item);
  }

  let state = await readState();
  if (!state.ok) {
    return {
      ok: false,
      steps,
      failure: failure(
        null,
        null,
        `读不到 Claude Code 的插件状态：${state.problems.join('；')}`,
        ['手动运行 claude plugin list --json 确认插件命令可用', '必要时升级 Claude Code'],
      ),
    };
  }
  log(`  状态来源：${state.source === 'cli' ? 'claude plugin list --json' : '~/.claude/plugins/*.json'}`);

  const execute = async (args) => {
    const spec = buildSpawnSpec(options.executable, args, { platform });
    return run(spec, { timeoutMs });
  };

  /* 1) marketplace：先让每个市场指向我们的副本。 */
  for (const [name, item] of byMarketplace) {
    const canonical = path.join(marketplacesRoot, name);
    const registered = state.marketplaces.find((entry) => entry.name === name) ?? null;
    const action = decideMarketplaceAction({
      registered,
      canonicalDir: canonical,
      replace: options.replaceMarketplace === true,
    });

    if (action === 'block') {
      return {
        ok: false,
        steps,
        failure: failure(
          item.id,
          commandText(['plugin', 'marketplace', 'remove', name]),
          `marketplace ${name} 已由 git 仓库提供（${describeSource(registered?.source)}），` +
            '默认不覆盖，以免删掉你已有的插件来源',
          [
            `确认要用产物里的本地市场替换它时，加 --replace-marketplace 重新运行`,
            `或者先手动执行 claude plugin marketplace remove ${name}`,
          ],
        ),
      };
    }

    if (action === 'replace') {
      const removed = await execute(['plugin', 'marketplace', 'remove', name, '--scope', 'user', '--json']);
      if (removed.timedOut || removed.code !== 0) {
        return {
          ok: false,
          steps,
          failure: failure(
            item.id,
            commandText(['plugin', 'marketplace', 'remove', name, '--scope', 'user', '--json']),
            describeRunFailure(removed, timeoutMs),
            [`手动执行 claude plugin marketplace remove ${name} 后重试`],
          ),
        };
      }
      log(`  marketplace ${name}：移除旧注册（原位置 ${registered?.installLocation ?? '未知'}）`);
    }

    const needsCopy =
      action === 'add' || action === 'replace'
        ? true
        : action === 'refresh'
          ? directoryHash(canonical) !== item.sha256
          : false;

    if (needsCopy) {
      if (!isInside(marketplacesRoot, canonical)) {
        return {
          ok: false,
          steps,
          failure: failure(
            item.id,
            null,
            `拒绝写入 ${canonical}：它不在 ${marketplacesRoot} 之下`,
            ['检查 CLAUDE_CONFIG_DIR 设置，确认这是你自己的配置目录'],
          ),
        };
      }
      copyPayload(item.path, canonical);
      log(`  marketplace ${name}：复制载荷到 ${canonical}`);
    }

    if (action === 'add' || action === 'replace' || needsCopy) {
      const args = ['plugin', 'marketplace', 'add', canonical, '--scope', 'user', '--json'];
      const added = await execute(args);
      if (added.timedOut || added.code !== 0) {
        return {
          ok: false,
          steps,
          failure: failure(item.id, commandText(args), describeRunFailure(added, timeoutMs), [
            `手动执行 claude plugin marketplace add "${canonical}" 查看报错`,
          ]),
        };
      }
    }
    log(`  marketplace ${name}：${action === 'refresh' && !needsCopy ? '内容未变，跳过刷新' : '已就绪'}`);
  }

  /* 2) 插件：按坐标清单的顺序安装。 */
  state = await readState();
  if (!state.ok) {
    return {
      ok: false,
      steps,
      failure: failure(null, null, `刷新插件状态失败：${state.problems.join('；')}`, []),
    };
  }

  for (const item of plugins) {
    const installed =
      state.plugins.find((entry) => entry.id === `${item.plugin}@${item.marketplace}`) ?? null;
    const cacheHash =
      installed?.installPath !== null &&
      installed?.installPath !== undefined &&
      fs.existsSync(installed.installPath)
        ? directoryHash(installed.installPath)
        : null;

    const action = decidePluginAction({
      installedVersion: installed?.version ?? null,
      payloadVersion: item.version,
      cacheHash,
      payloadHash: item.sha256,
    });

    if (action === 'none') {
      steps.push({ plugin: item.id, action, detail: `${item.version} 已是最新（内容一致）` });
      log(`  ${item.id}：已是最新（${item.version}）`);
      continue;
    }

    const outcome = await applyAction(item, action, execute, timeoutMs);
    if (!outcome.ok) {
      steps.push({ plugin: item.id, action, detail: outcome.detail });
      return {
        ok: false,
        steps,
        failure: failure(item.id, outcome.command, outcome.detail, outcome.remedy),
      };
    }

    // 安装后复核三项：版本、目录存在、内容哈希。CLI 说成功不算成功。
    const verified = await verifyInstalled(item, readState);
    if (!verified.ok) {
      steps.push({ plugin: item.id, action, detail: verified.detail });
      return {
        ok: false,
        steps,
        failure: failure(item.id, outcome.command, verified.detail, verified.remedy),
      };
    }

    steps.push({ plugin: item.id, action, detail: `${action} → ${item.version}` });
    log(
      `  ${item.id}：${{ install: '已安装', update: '已升级', reinstall: '内容有变，已重装' }[action]} ${item.version}`,
    );
    state = verified.state;
  }

  return { ok: true, steps, failure: null };
}

function directoryHash(dir) {
  try {
    return hashPluginDirectory(dir).sha256;
  } catch {
    return null;
  }
}

function describeSource(source) {
  const kind = marketplaceSourceKind(source);
  if (source !== null && typeof source === 'object' && typeof source.url === 'string') {
    return `${kind} ${source.url}`;
  }
  return kind === '' ? '未知来源' : kind;
}

async function applyAction(item, action, execute, timeoutMs) {
  const id = `${item.plugin}@${item.marketplace}`;
  const installArgs = ['plugin', 'install', id, '--scope', 'user', '--json', '-y'];
  const updateArgs = ['plugin', 'update', id, '--scope', 'user', '--json', '-y'];
  const uninstallArgs = ['plugin', 'uninstall', id, '--scope', 'user', '--json'];

  const runOne = async (args) => {
    const result = await execute(args);
    if (result.timedOut || result.code !== 0) {
      return {
        ok: false,
        detail: describeRunFailure(result, timeoutMs),
        command: `claude ${args.join(' ')}`,
        remedy: [
          `手动执行 claude ${args.join(' ')} 查看完整报错`,
          '确认 Claude Code 已登录，且对配置目录有写权限',
        ],
      };
    }
    return { ok: true, command: `claude ${args.join(' ')}` };
  };

  if (action === 'install') {
    return runOne(installArgs);
  }

  if (action === 'update') {
    const updated = await runOne(updateArgs);
    if (updated.ok) {
      return updated;
    }
    // update 失败时退化为重装：版本号没变但 CLI 认为没得升之类的情况。
    const removed = await runOne(uninstallArgs);
    if (!removed.ok) {
      return updated;
    }
    return runOne(installArgs);
  }

  const removed = await runOne(uninstallArgs);
  if (!removed.ok) {
    return removed;
  }
  return runOne(installArgs);
}

async function verifyInstalled(item, readState) {
  const state = await readState();
  if (!state.ok) {
    return {
      ok: false,
      detail: `安装后读状态失败：${state.problems.join('；')}`,
      remedy: [],
      state,
    };
  }

  const id = `${item.plugin}@${item.marketplace}`;
  const entry = state.plugins.find((candidate) => candidate.id === id) ?? null;
  if (entry === null) {
    return {
      ok: false,
      detail: `安装命令成功，但 ${id} 没有出现在 plugin list 里`,
      remedy: [`手动执行 claude plugin list 查看实际状态`, `必要时运行 claude plugin install ${id}`],
      state,
    };
  }
  if (entry.version !== item.version) {
    return {
      ok: false,
      detail: `装上的版本是 ${entry.version}，产物里是 ${item.version}`,
      remedy: ['确认 marketplace 指向产物里的副本', '必要时重跑启动脚本，或加 --replace-marketplace'],
      state,
    };
  }
  if (entry.installPath === null || !fs.existsSync(entry.installPath)) {
    return {
      ok: false,
      detail: `installPath 不存在：${entry.installPath ?? '（未提供）'}`,
      remedy: [`删除该插件后重装：claude plugin uninstall ${id}`],
      state,
    };
  }
  const actual = directoryHash(entry.installPath);
  if (actual !== item.sha256) {
    return {
      ok: false,
      detail: `安装目录的内容哈希是 ${actual ?? '无法计算'}，产物里是 ${item.sha256}`,
      remedy: [`删除该插件后重装：claude plugin uninstall ${id}`],
      state,
    };
  }
  return { ok: true, detail: `${item.version}，内容一致`, state };
}
