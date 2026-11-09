/**
 * 把五个插件从 Claude Code 里摘掉——安装的逆操作。
 *
 * 为什么值得一个脚本，而不是让用户照文档敲命令：
 *
 * 1. **要按顺序配对**。五个 `plugin uninstall` 之后还有五个 `marketplace remove`；
 *    漏掉后者，`~/.claude/plugins/marketplaces/<市场名>` 下就留着一份载荷副本，
 *    而且没有任何提示——目录还在，插件却已经不可用了。
 * 2. **顺序不能反**。先删市场会让已装插件的注册项变成指向空处的悬空条目。
 * 3. **不能整目录清**。`~/.claude/plugins/marketplaces` 下面是全机的插件市场，
 *    本机实测就有 `ecc`、`everything-claude-code` 这类别人的市场（各 110 MB）。
 *    所以只能按坐标精确删。
 *
 * 状态读取与安装共用 `plugin-install.mjs` 的 `readPluginState`：两边各写一份的话，
 * "装了什么"与"现在还剩什么"迟早会分叉。
 */

import fs from 'node:fs';
import path from 'node:path';

import { claudeConfigDir } from './checks/claude.mjs';
import { buildSpawnSpec, describeRunFailure, runProcess } from './cli-exec.mjs';
import {
  isInside,
  MARKETPLACES_SUBDIR,
  PLUGIN_COMMAND_TIMEOUT_MS,
  readPluginState,
} from './plugin-install.mjs';

/**
 * 本产品打进包的五个插件坐标。
 *
 * 与 `scripts/artifact/plugins.json` 是同一份数据，这里重复一遍是**故意的**：
 * 卸载必须能在插件载荷已经被删掉、或产物压根没解压完整的地方工作——那时包里
 * 没有 `plugins/index.json` 可以读，而 `~/.claude` 里躺着五个条目正等着清。
 *
 * 重复的代价由测试盯着：`tests/plugin-uninstall.test.mjs` 直接读 `plugins.json`
 * 逐项比对，改了一边忘了另一边是测试失败，不是静默漂移。
 */
export const BUNDLED_PLUGIN_COORDINATES = [
  { plugin: 'drive', marketplace: 'zte-ai-lab' },
  { plugin: 'agent-genesis', marketplace: 'agent-genesis' },
  { plugin: 'goldeval', marketplace: 'goldeval' },
  { plugin: 'skill-optimizer', marketplace: 'skillx' },
  { plugin: 'cosightbot', marketplace: 'cosightbot' },
];

/** Claude Code 的插件坐标写法。 */
const ID_SEPARATOR = '@';

/** `{plugin, marketplace}` → Claude Code 认的插件 id。 */
export function pluginIdOf(coordinate) {
  return `${coordinate.plugin}${ID_SEPARATOR}${coordinate.marketplace}`;
}

/**
 * 从一个插件 id 里取市场名。
 *
 * 用 `lastIndexOf`：插件名本身可能带 `@`（scoped 名），从第一个 `@` 切会把市场名切碎。
 */
function marketplaceOfPluginId(id) {
  const at = id.lastIndexOf(ID_SEPARATOR);
  return at === -1 ? '' : id.slice(at + 1);
}

/**
 * 算出"要摘掉什么"和"哪些不能摘"。纯函数：不碰文件系统，也不执行命令。
 *
 * 单独拆出来是为了让"别的插件还挂在同一个市场上"这种判断可以被直接测——
 * 它决定了要不要跳过某个市场，而跳过与否直接影响用户机器上**别人的**插件能不能用。
 *
 * @param {{coordinates?: Array<{plugin: string, marketplace: string}>,
 *   state: {plugins: Array<{id: string}>, marketplaces: Array<{name: string}>}}} input
 * @returns {{plugins: Array<{id: string, marketplace: string, present: boolean}>,
 *   marketplaces: Array<{name: string, present: boolean, foreign: string[]}>}}
 */
export function planRetirement({ coordinates = BUNDLED_PLUGIN_COORDINATES, state }) {
  const installedIds = new Set(state.plugins.map((entry) => entry.id));
  const registeredMarkets = new Set(state.marketplaces.map((entry) => entry.name));

  const plugins = coordinates.map((coordinate) => ({
    id: pluginIdOf(coordinate),
    marketplace: coordinate.marketplace,
    present: installedIds.has(pluginIdOf(coordinate)),
  }));

  const ourIds = new Set(plugins.map((item) => item.id));
  const marketNames = [...new Set(coordinates.map((coordinate) => coordinate.marketplace))];

  const marketplaces = marketNames.map((name) => ({
    name,
    present: registeredMarkets.has(name),
    /*
     * 不归我们、却挂在这个市场下的插件。有的话这个市场不能删：
     * `marketplace remove` 会把这个来源整个抽走，那些插件随后就装不回来了
     * ——我们卸载自己，不该顺手拆掉用户环境里的其它东西。
     */
    foreign: [...installedIds].filter(
      (id) => !ourIds.has(id) && marketplaceOfPluginId(id) === name,
    ),
  }));

  return { plugins, marketplaces };
}

/**
 * 目录体积（字节）。用于"删掉它你能省多少"这类汇报。
 *
 * 读不了就返回 0：体积只是报告里的一句附带信息，不该让卸载本身失败。
 * 软链按条目本身算，不跟进去——跟着走会在自引用软链上转圈。
 */
export function directorySize(target) {
  let stat;
  try {
    stat = fs.lstatSync(target);
  } catch {
    return 0;
  }
  if (!stat.isDirectory()) {
    return stat.size;
  }

  let total = 0;
  let entries;
  try {
    entries = fs.readdirSync(target, { withFileTypes: true });
  } catch {
    return 0;
  }
  for (const entry of entries) {
    total += directorySize(path.join(target, entry.name));
  }
  return total;
}

/** 失败行的形状与 `plugin-install.mjs` 一致，好让 start.mjs 用同一个渲染函数。 */
function failure(plugin, command, detail, remedy) {
  return { plugin, command, detail, remedy };
}

function commandText(args) {
  return `claude ${args.join(' ')}`;
}

/**
 * 执行卸载。幂等：本来就没装的、本来就没注册的，都记为跳过而不是失败。
 *
 * @param {{coordinates?: Array<{plugin: string, marketplace: string}>, executable: string,
 *   configDir?: string, home?: string, platform?: string, run?: Function,
 *   readState?: Function, timeoutMs?: number, log?: (line: string) => void,
 *   dryRun?: boolean}} options
 * @returns {Promise<{ok: boolean, steps: Array<object>, failure: object|null}>}
 */
export async function retirePlugins(options) {
  const platform = options.platform ?? process.platform;
  const run = options.run ?? runProcess;
  const timeoutMs = options.timeoutMs ?? PLUGIN_COMMAND_TIMEOUT_MS;
  const log = options.log ?? (() => {});
  const coordinates = options.coordinates ?? BUNDLED_PLUGIN_COORDINATES;
  const dryRun = options.dryRun === true;
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

  const execute = async (args) => {
    const spec = buildSpawnSpec(options.executable, args, { platform });
    return run(spec, { timeoutMs });
  };

  const steps = [];

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
  log(
    `  状态来源：${state.source === 'cli' ? 'claude plugin list --json' : '~/.claude/plugins/*.json'}`,
  );

  /* 1) 插件。必须先于市场：反过来的话删市场会留下悬空的插件注册项。 */
  for (const item of planRetirement({ coordinates, state }).plugins) {
    if (!item.present) {
      steps.push({ kind: 'plugin', id: item.id, action: 'absent' });
      log(`  插件 ${item.id}：未安装，跳过`);
      continue;
    }

    const args = ['plugin', 'uninstall', item.id, '--scope', 'user', '--json'];
    if (dryRun) {
      steps.push({ kind: 'plugin', id: item.id, action: 'planned', command: commandText(args) });
      log(`  插件 ${item.id}：将卸载（--dry-run，未执行）`);
      continue;
    }

    const result = await execute(args);
    if (result.timedOut || result.code !== 0) {
      return {
        ok: false,
        steps,
        failure: failure(item.id, commandText(args), describeRunFailure(result, timeoutMs), [
          `手动执行 ${commandText(args)} 查看完整报错`,
          '确认 Claude Code 已登录，且对配置目录有写权限',
        ]),
      };
    }
    steps.push({ kind: 'plugin', id: item.id, action: 'removed' });
    log(`  插件 ${item.id}：已卸载`);
  }

  /* 2) 市场。卸载完再读一次状态：这时"还剩几个插件挂着"才是最终结果。 */
  if (!dryRun) {
    state = await readState();
    if (!state.ok) {
      return {
        ok: false,
        steps,
        failure: failure(null, null, `卸载后读状态失败：${state.problems.join('；')}`, [
          '手动执行 claude plugin list 查看实际状态',
        ]),
      };
    }
  }

  for (const market of planRetirement({ coordinates, state }).marketplaces) {
    if (!market.present) {
      steps.push({ kind: 'marketplace', name: market.name, action: 'absent' });
      log(`  市场 ${market.name}：未注册，跳过`);
      continue;
    }

    if (market.foreign.length > 0) {
      /*
       * 跳过而不是强删：这个市场里还有别人的插件。日志里点名，文档里也写了
       * 手动命令——用户确认那些插件不要了，自己删是被明确告知的选择。
       */
      steps.push({
        kind: 'marketplace',
        name: market.name,
        action: 'kept-in-use',
        foreign: market.foreign,
      });
      log(`  市场 ${market.name}：保留（还有别的插件挂在上面：${market.foreign.join(', ')}）`);
      continue;
    }

    const args = ['plugin', 'marketplace', 'remove', market.name, '--scope', 'user', '--json'];
    if (dryRun) {
      steps.push({
        kind: 'marketplace',
        name: market.name,
        action: 'planned',
        command: commandText(args),
      });
      log(`  市场 ${market.name}：将移除（--dry-run，未执行）`);
      continue;
    }

    const result = await execute(args);
    if (result.timedOut || result.code !== 0) {
      return {
        ok: false,
        steps,
        failure: failure(null, commandText(args), describeRunFailure(result, timeoutMs), [
          `手动执行 ${commandText(args)} 后重试`,
        ]),
      };
    }

    /*
     * CLI 只取消注册，未必删掉当初复制进去的那份载荷（`plugin-install.mjs` 的
     * `copyPayload` 写的）。不删的话，卸载完 `~/.claude` 里还留着几 MB 的副本
     * ——"卸载"就成了半件事。目录是我们自己复制进去的，位置也校验过在市场根之下。
     */
    const canonical = path.join(marketplacesRoot, market.name);
    let purgedBytes = 0;
    if (isInside(marketplacesRoot, canonical) && fs.existsSync(canonical)) {
      purgedBytes = directorySize(canonical);
      fs.rmSync(canonical, { recursive: true, force: true });
    }

    steps.push({ kind: 'marketplace', name: market.name, action: 'removed', purgedBytes });
    log(
      `  市场 ${market.name}：已移除${
        purgedBytes > 0 ? `（并清掉 ${canonical} 下的载荷副本）` : ''
      }`,
    );
  }

  return { ok: true, steps, failure: null };
}
