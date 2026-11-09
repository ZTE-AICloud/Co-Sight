/**
 * 插件载荷的描述：五个插件分别是谁、什么版本、内容哈希是多少。
 *
 * 两种布局，同一套输出：
 *   - 产物布局：`<artifact>/plugins/index.json` 由打包脚本生成，带哈希，是权威来源；
 *   - 仓库布局：`scripts/artifact/plugins.json` 只写坐标（目录名 / 插件名 / 市场名），
 *     版本号与哈希现场从 `.claude-plugin/` 与插件目录读。
 *
 * 这里**只读**。安装、替换市场、写锁文件都在 `plugin-install.mjs`。
 *
 * 校验为什么严格：插件载荷是"从别人仓库拿来的代码"，它的清单与我们的坐标
 * 不一致时，装进去的会是一个名字对、内容不对的东西。宁可启动前失败。
 */

import fs from 'node:fs';
import path from 'node:path';

import { hashPluginDirectory } from './plugin-hash.mjs';

/** 目录名要能安全地拼进路径（清单是外部数据，不能直接信任）。 */
const SAFE_DIR_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function isSafeDirName(value) {
  return (
    typeof value === 'string' &&
    value !== '' &&
    value !== '.' &&
    value !== '..' &&
    SAFE_DIR_NAME.test(value)
  );
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim() !== '';
}

function readJsonFile(filePath) {
  let text;
  try {
    text = fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    return { ok: false, problem: `读不到 ${filePath}（${error.code ?? error.message}）` };
  }
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (error) {
    return { ok: false, problem: `${filePath} 不是合法 JSON（${error.message}）` };
  }
}

function normalizeRequires(value) {
  const bins = Array.isArray(value?.bins)
    ? value.bins.filter((bin) => isNonEmptyString(bin))
    : [];
  return { bins };
}

/**
 * 读一个插件目录自己的清单，并做交叉校验。
 *
 * 校验点：
 *   - `plugin.json` 的 `name` / `version` 必须存在且为非空字符串；
 *   - `marketplace.json` 必须存在、有 `name`、`plugins` 里有同名条目；
 *   - 两边都写版本时必须一致（写错的版本会让 `plugin update` 做出错误判断）。
 *
 * @param {string} pluginDir
 * @returns {{ok: boolean, plugin?: string, marketplace?: string, version?: string,
 *   requires?: {bins: string[]}, problems: string[]}}
 */
export function readPluginMetadata(pluginDir) {
  const problems = [];
  const pluginPath = path.join(pluginDir, '.claude-plugin', 'plugin.json');
  const marketplacePath = path.join(pluginDir, '.claude-plugin', 'marketplace.json');

  const pluginManifest = readJsonFile(pluginPath);
  if (!pluginManifest.ok) {
    return { ok: false, problems: [pluginManifest.problem] };
  }

  const plugin = pluginManifest.value?.name;
  const version = pluginManifest.value?.version;
  if (!isNonEmptyString(plugin)) {
    problems.push(`${pluginPath} 缺少 name`);
  }
  if (!isNonEmptyString(version)) {
    problems.push(`${pluginPath} 缺少 version`);
  }

  const marketplaceManifest = readJsonFile(marketplacePath);
  if (!marketplaceManifest.ok) {
    problems.push(marketplaceManifest.problem);
    return { ok: false, plugin, version, problems };
  }

  const marketplace = marketplaceManifest.value?.name;
  if (!isNonEmptyString(marketplace)) {
    problems.push(`${marketplacePath} 缺少 name`);
  }

  const entries = marketplaceManifest.value?.plugins;
  if (!Array.isArray(entries)) {
    problems.push(`${marketplacePath} 缺少 plugins 数组`);
  } else {
    const entry = entries.find((item) => item?.name === plugin);
    if (entry === undefined) {
      problems.push(`${marketplacePath} 的 plugins 里没有 ${plugin}`);
    } else if (isNonEmptyString(entry.version) && isNonEmptyString(version) && entry.version !== version) {
      problems.push(
        `${path.relative(pluginDir, marketplacePath)} 写的版本 ${entry.version} 与 plugin.json 的 ${version} 不一致`,
      );
    }
  }

  return {
    ok: problems.length === 0,
    plugin,
    marketplace,
    version,
    problems,
  };
}

/**
 * 读宿主侧插件清单（`scripts/artifact/plugins.json`）。
 *
 * 这是**我们的**文件，格式固定；形状不对说明仓库被动过，直接报出来。
 *
 * @param {string} manifestPath
 * @returns {{ok: boolean, plugins: Array<{id: string, dir: string, plugin: string,
 *   marketplace: string, requires: {bins: string[]}}>, problems: string[]}}
 */
export function loadHostManifest(manifestPath) {
  const parsed = readJsonFile(manifestPath);
  if (!parsed.ok) {
    return { ok: false, plugins: [], problems: [parsed.problem] };
  }

  const raw = parsed.value?.plugins;
  if (!Array.isArray(raw) || raw.length === 0) {
    return { ok: false, plugins: [], problems: [`${manifestPath} 缺少非空的 plugins 数组`] };
  }

  const problems = [];
  const plugins = [];
  const seen = new Set();

  for (const [index, item] of raw.entries()) {
    const where = `${manifestPath} 第 ${index + 1} 项`;
    if (!isSafeDirName(item?.dir)) {
      problems.push(`${where} 的 dir 不是安全的目录名：${String(item?.dir)}`);
      continue;
    }
    if (!isNonEmptyString(item?.plugin) || !isNonEmptyString(item?.marketplace)) {
      problems.push(`${where}（${item.dir}）缺少 plugin 或 marketplace`);
      continue;
    }
    if (seen.has(item.dir)) {
      problems.push(`${where} 的 dir 重复：${item.dir}`);
      continue;
    }
    seen.add(item.dir);
    plugins.push({
      id: item.dir,
      dir: item.dir,
      plugin: item.plugin,
      marketplace: item.marketplace,
      requires: normalizeRequires(item.requires),
    });
  }

  return { ok: problems.length === 0, plugins, problems };
}

function describeLine(plugins) {
  if (plugins.length === 0) {
    return '没有插件载荷';
  }
  const names = plugins.map((item) => `${item.plugin} ${item.version ?? '版本未知'}`);
  return `${plugins.length} 个：${names.join('、')}`;
}

function metadataProblemsFor(label, metadata, expected) {
  const problems = [];
  for (const problem of metadata.problems) {
    problems.push(`${label}：${problem}`);
  }
  if (metadata.ok) {
    if (metadata.plugin !== expected.plugin) {
      problems.push(`${label}：插件名是 ${metadata.plugin}，清单写的是 ${expected.plugin}`);
    }
    if (metadata.marketplace !== expected.marketplace) {
      problems.push(`${label}：市场名是 ${metadata.marketplace}，清单写的是 ${expected.marketplace}`);
    }
    if (isNonEmptyString(expected.version) && metadata.version !== expected.version) {
      problems.push(`${label}：版本是 ${metadata.version}，清单写的是 ${expected.version}`);
    }
  }
  return problems;
}

function describeFromIndex(pluginsDir) {
  const indexPath = path.join(pluginsDir, 'index.json');
  const parsed = readJsonFile(indexPath);
  if (!parsed.ok) {
    return { mode: 'artifact', plugins: [], problems: [parsed.problem], line: '没有可用的插件载荷' };
  }

  const raw = parsed.value?.plugins;
  if (!Array.isArray(raw) || raw.length === 0) {
    return {
      mode: 'artifact',
      plugins: [],
      problems: [`${indexPath} 缺少非空的 plugins 数组`],
      line: '没有可用的插件载荷',
    };
  }

  const problems = [];
  const plugins = [];

  for (const [index, item] of raw.entries()) {
    const label = `插件 ${String(item?.dir ?? index + 1)}`;
    if (!isSafeDirName(item?.dir)) {
      problems.push(`${indexPath} 第 ${index + 1} 项的 dir 不是安全的目录名`);
      continue;
    }

    const dir = path.join(pluginsDir, item.dir);
    if (!fs.existsSync(dir)) {
      problems.push(`${label}：产物里缺少目录 plugins/${item.dir}`);
      continue;
    }

    const metadata = readPluginMetadata(dir);
    const expected = {
      plugin: item.plugin,
      marketplace: item.marketplace,
      version: item.version,
    };
    problems.push(...metadataProblemsFor(label, metadata, expected));
    if (!metadata.ok) {
      continue;
    }

    let hash;
    try {
      hash = hashPluginDirectory(dir);
    } catch (error) {
      problems.push(`${label}：${error.message}`);
      continue;
    }
    if (isNonEmptyString(item.sha256) && hash.sha256 !== item.sha256) {
      problems.push(
        `${label}：内容哈希是 ${hash.sha256}，index.json 写的是 ${item.sha256}（载荷被改动或不完整）`,
      );
      continue;
    }
    if (Number.isInteger(item.files) && hash.files !== item.files) {
      problems.push(`${label}：文件数 ${hash.files} 与 index.json 的 ${item.files} 不一致`);
      continue;
    }

    plugins.push({
      id: item.dir,
      dir: item.dir,
      plugin: metadata.plugin,
      marketplace: metadata.marketplace,
      version: metadata.version,
      sha256: hash.sha256,
      files: hash.files,
      requires: normalizeRequires(item.requires),
      path: dir,
    });
  }

  return { mode: 'artifact', plugins, problems, line: describeLine(plugins) };
}

function describeFromManifest(manifestPath, sourceRoot) {
  const manifest = loadHostManifest(manifestPath);
  if (!manifest.ok) {
    return { mode: 'repo', plugins: [], problems: manifest.problems, line: '没有可用的插件载荷' };
  }

  const problems = [];
  const plugins = [];

  for (const item of manifest.plugins) {
    const label = `插件 ${item.dir}`;
    const dir = path.join(sourceRoot, item.dir);
    if (!fs.existsSync(dir)) {
      problems.push(`${label}：仓库里缺少目录 ${dir}`);
      continue;
    }

    const metadata = readPluginMetadata(dir);
    const expected = { plugin: item.plugin, marketplace: item.marketplace, version: undefined };
    problems.push(...metadataProblemsFor(label, metadata, expected));
    if (!metadata.ok) {
      continue;
    }

    let hash;
    try {
      hash = hashPluginDirectory(dir);
    } catch (error) {
      problems.push(`${label}：${error.message}`);
      continue;
    }

    plugins.push({
      ...item,
      plugin: metadata.plugin,
      marketplace: metadata.marketplace,
      version: metadata.version,
      sha256: hash.sha256,
      files: hash.files,
      path: dir,
      requires: item.requires,
    });
  }

  return { mode: 'repo', plugins, problems, line: describeLine(plugins) };
}

/**
 * 汇总插件载荷。
 *
 * @param {{pluginsDir?: string|null, manifestPath?: string|null, sourceRoot?: string}} options
 *   `pluginsDir` 是产物里的 `plugins/`；存在就按产物布局校验。
 *   `manifestPath` 是仓库里的 `scripts/artifact/plugins.json`，`sourceRoot` 是仓库根。
 */
export function describePlugins(options = {}) {
  const pluginsDir = options.pluginsDir ?? null;
  const manifestPath = options.manifestPath ?? null;
  const sourceRoot = options.sourceRoot ?? null;

  if (pluginsDir !== null && fs.existsSync(pluginsDir)) {
    return describeFromIndex(pluginsDir);
  }
  if (manifestPath !== null && sourceRoot !== null && fs.existsSync(manifestPath)) {
    return describeFromManifest(manifestPath, sourceRoot);
  }
  return {
    mode: 'none',
    plugins: [],
    problems: [],
    line: '没有插件载荷（仓库布局下由开发者自行管理，启动时跳过安装）',
  };
}
