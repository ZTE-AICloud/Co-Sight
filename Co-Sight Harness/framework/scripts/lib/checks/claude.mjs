/**
 * 宿主工具链检查：Claude Code CLI、`~/.claude`、Python 3。
 *
 * 这三项是"插件能不能装进去、装进去能不能跑"的前提，任何一项不满足，
 * 后面的模块启动都没有意义——专家页、drive 的保护钩子都依赖插件。
 *
 * 检查全程只读：不建 `~/.claude`、不装插件。写操作在 `ensurePlugins()` 阶段。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  MIN_CLAUDE_VERSION,
  PROBE_TIMEOUT_MS,
  probePluginList,
  readClaudeVersion,
  resolveClaudeExecutable,
  VERSION_TIMEOUT_MS,
} from '../claude-cli.mjs';
import {
  buildSpawnSpec,
  describeRunFailure,
  lastLine,
  resolveExecutable,
  runProcess,
} from '../cli-exec.mjs';

/** 失败时点名的插件（用源码目录名，用户认得出来）。 */
export const PLUGIN_LABELS = [
  'drive',
  'agent-genesis',
  'agent-evaluator',
  'skill-optimizer',
  'cosight-bot',
];

const PYTHON_TIMEOUT_MS = 5_000;

function shortenHome(candidate, homeDir) {
  const prefix = homeDir.endsWith(path.sep) ? homeDir : `${homeDir}${path.sep}`;
  return candidate.startsWith(prefix) ? `~${candidate.slice(homeDir.length)}` : candidate;
}

function describeSearched(checked, homeDir) {
  const parts = [];
  if (checked.explicitPath !== null && checked.explicitPath !== undefined) {
    parts.push(`${checked.explicitPath}（--claude）`);
  }
  if (checked.pathDirs.length > 0) {
    parts.push(`PATH（${checked.pathDirs.length} 个目录）`);
  }
  for (const candidate of checked.fallbacks) {
    parts.push(shortenHome(candidate, homeDir));
  }
  return parts.join('、');
}

/**
 * Claude Code CLI 检查。
 *
 * @param {{explicit?: string|null, env?: NodeJS.ProcessEnv, platform?: string,
 *   homeDir?: string, pluginLabels?: string[], resolve?: Function,
 *   readVersion?: Function, probe?: Function}} [options]
 *   解析与探测函数可注入，单测才不必真的装一个 Claude Code。
 */
export function claudeCheck(options = {}) {
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const homeDir = options.homeDir ?? os.homedir();
  const explicit = options.explicit ?? null;
  const labels = options.pluginLabels ?? PLUGIN_LABELS;
  const resolve = options.resolve ?? resolveClaudeExecutable;
  const readVersion = options.readVersion ?? readClaudeVersion;
  const probe = options.probe ?? probePluginList;

  const impact = `无法把 ${labels.join(' / ')} 装进 Claude Code`;

  return {
    id: 'claude',
    label: 'Claude Code',
    level: 'block',
    run: async () => {
      const found = resolve({ explicit, env, platform, homeDir });

      if (found.path === null) {
        if (explicit !== null) {
          return {
            ok: false,
            detail: `未找到 --claude 指定的 ${explicit}`,
            remedy: [
              '去掉 --claude，让它按 PATH 与常见安装位置查找',
              '或把 --claude 改成正确的可执行文件路径',
            ],
            impact,
          };
        }
        return {
          ok: false,
          detail: '未找到',
          remedy: [
            `查过：${describeSearched(found.checked, homeDir)}`,
            '安装：npm install -g @anthropic-ai/claude-code',
            '或把已有的 claude 所在目录加入 PATH，或用 --claude <路径> 指定',
          ],
          impact,
        };
      }

      const version = await readVersion({ executable: found.path, platform });

      if (version.ok) {
        return { ok: true, detail: `${version.version}，${found.path}` };
      }

      if (version.reason === 'unparsable') {
        // 版本行格式变了但插件命令还在：放行，并把这一条降为提醒（D45）。
        // 报告里用 [WARN] 而不是 [OK]，让用户知道这里没被完整校验。
        const probeResult = await probe({ executable: found.path, platform, timeoutMs: PROBE_TIMEOUT_MS });
        if (probeResult.ok) {
          return {
            ok: false,
            level: 'warn',
            detail: `${found.path}（版本行无法解析，但 plugin list --json 可用，放行）`,
          };
        }
        return {
          ok: false,
          detail: `无法解析 ${found.path} --version 的输出：${lastLine(version.raw) || '（没有输出）'}`,
          remedy: [
            '手动运行 claude --version，确认这套 CLI 是 @anthropic-ai/claude-code',
            `插件命令也不可用：${describeProbeFailure(probeResult)}`,
          ],
          impact,
        };
      }

      if (version.reason === 'too-old') {
        return {
          ok: false,
          detail: `${version.version} 低于要求的 ${MIN_CLAUDE_VERSION}（${found.path}）`,
          remedy: [
            '升级：npm install -g @anthropic-ai/claude-code@latest',
            '或运行 claude update',
          ],
          impact,
        };
      }

      if (version.reason === 'not-claude') {
        return {
          ok: false,
          detail: `${found.path} 不是 Claude Code（--version 输出：${lastLine(version.raw)}）`,
          remedy: [
            '确认 PATH 里的 claude 指向 @anthropic-ai/claude-code',
            '或用 --claude <路径> 指定正确的可执行文件',
          ],
          impact,
        };
      }

      if (version.reason === 'timeout') {
        return {
          ok: false,
          detail: `${found.path} 在 ${Math.round(VERSION_TIMEOUT_MS / 1000)} 秒内没有返回 --version`,
          remedy: [
            '手动运行 claude --version 确认它能正常返回',
            '首次启动可能停在登录/引导界面，先完成一次交互式启动',
          ],
          impact,
        };
      }

      return {
        ok: false,
        detail: `${found.path} 执行 --version 失败（${lastLine(version.raw) || `退出码 ${version.code}`}）`,
        remedy: [
          '手动运行 claude --version 看看报什么错',
          '必要时重新安装：npm install -g @anthropic-ai/claude-code',
        ],
        impact,
      };
    },
  };
}

function describeProbeFailure(result) {
  if (result.reason === 'timeout') {
    return 'plugin list --json 超时';
  }
  if (result.reason === 'exit') {
    return `plugin list --json 退出码 ${result.code}`;
  }
  if (result.reason === 'unparsable-json') {
    return 'plugin list --json 的输出不是 JSON';
  }
  return result.message ?? 'plugin list --json 无法执行';
}

/**
 * `~/.claude`（或 `$CLAUDE_CONFIG_DIR`）。
 *
 * @param {{env?: NodeJS.ProcessEnv, homeDir?: string}} [options]
 */
export function claudeConfigDir(options = {}) {
  const env = options.env ?? process.env;
  const homeDir = options.homeDir ?? os.homedir();
  const configured = (env['CLAUDE_CONFIG_DIR'] ?? '').trim();
  return configured === '' ? path.join(homeDir, '.claude') : path.resolve(configured);
}

function nearestExisting(target) {
  let current = path.resolve(target);
  for (;;) {
    if (fs.existsSync(current)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return current;
    }
    current = parent;
  }
}

/** 只读地判断"这个目录能不能写"；不存在时看最近的已存在上级。 */
function inspectWritable(dir) {
  const stat = fs.statSync(dir, { throwIfNoEntry: false });
  if (stat !== undefined) {
    if (!stat.isDirectory()) {
      return { ok: false, detail: `${dir}（存在，但不是目录）` };
    }
    try {
      fs.accessSync(dir, fs.constants.W_OK);
      return { ok: true, detail: `${dir}（已存在且可写）` };
    } catch {
      return { ok: false, detail: `${dir}（存在但当前用户不可写）` };
    }
  }

  const ancestor = nearestExisting(path.dirname(dir));
  try {
    fs.accessSync(ancestor, fs.constants.W_OK);
    return { ok: true, detail: `${dir}（尚未创建，${ancestor} 可写，首次安装时创建）` };
  } catch {
    return { ok: false, detail: `${dir}（尚未创建，且 ${ancestor} 不可写）` };
  }
}

/**
 * Claude 状态目录检查。不创建它——创建属于安装阶段。
 *
 * @param {{env?: NodeJS.ProcessEnv, homeDir?: string}} [options]
 */
export function claudeDirCheck(options = {}) {
  const env = options.env ?? process.env;
  const homeDir = options.homeDir ?? os.homedir();
  const dir = claudeConfigDir({ env, homeDir });

  return {
    id: 'claudeDir',
    label: 'Claude 目录',
    level: 'block',
    run: () => {
      const state = inspectWritable(dir);
      if (state.ok) {
        return { ok: true, detail: state.detail };
      }
      return {
        ok: false,
        detail: state.detail,
        remedy: [
          `确认当前用户对 ${dir} 或它的上级目录有写权限`,
          '不要用 sudo 运行本程序：装好的插件会归 root，之后普通用户反而用不了',
        ],
        impact: '插件无法安装或更新，Claude Code 也读不到它们',
      };
    },
  };
}

/**
 * 哪些插件声明需要某个命令。
 *
 * `requires` 来自宿主侧清单（`scripts/artifact/plugins.json`），不是插件自己的
 * 文件——这样插件升级换实现时，我们不用跟着改别人的仓库。
 *
 * @param {Array<{id?: string, dir?: string, plugin?: string,
 *   requires?: {bins?: string[]}}>} plugins
 * @param {string} bin
 */
export function pluginsRequiring(plugins, bin) {
  return plugins
    .filter((plugin) => Array.isArray(plugin.requires?.bins) && plugin.requires.bins.includes(bin))
    .map((plugin) => plugin.id ?? plugin.dir ?? plugin.plugin ?? '未知插件');
}

function parsePythonVersion(raw) {
  const match = /python\s+([\d.]+)/i.exec(raw);
  return match === null ? null : match[1];
}

/**
 * Python 3 检查：只在产物里的插件声明了 `requires.bins: ["python3"]` 时才做。
 *
 * 只找文件还不够：Windows 上常见的"应用商店别名"是一个占位符，`--version`
 * 会以非零码退出。所以这里实际跑一次。
 *
 * @param {{plugins?: Array<{id?: string, requires?: {bins?: string[]}}>,
 *   env?: NodeJS.ProcessEnv, platform?: string, homeDir?: string,
 *   resolve?: Function, run?: Function}} [options]
 */
export function pythonCheck(options = {}) {
  const plugins = options.plugins ?? [];
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const homeDir = options.homeDir ?? os.homedir();
  const resolve = options.resolve ?? resolveExecutable;
  const run = options.run ?? runProcess;

  return {
    id: 'python3',
    label: 'Python 3',
    level: 'block',
    run: async () => {
      const requesters = pluginsRequiring(plugins, 'python3');
      if (requesters.length === 0) {
        return { ok: true, detail: '（产物里的插件没有声明需要 python3，跳过）' };
      }

      const who = requesters.join('、');
      const found = resolve('python3', { env, platform, homeDir });

      if (found.path === null) {
        return {
          ok: false,
          detail: `未找到 python3（${who} 的脚本/hooks 需要）`,
          // 提示必须按平台分开写：Windows 的 Python 安装包只生成 `python.exe`
          // 与 `py.exe`，**不会**生成 `python3.exe`。告诉 Windows 用户"勾选
          // Add python.exe to PATH"是一句做了也没用的话——插件 hooks 里写死的
          // 就是 `python3`，PATH 上没有这个名字照样拦。
          remedy:
            platform === 'win32'
              ? [
                  '安装 Python 3（python.org 安装包），勾选「Add python.exe to PATH」',
                  'Windows 只提供 python.exe：到 Python 安装目录复制一份 python3.exe（同一个 exe，改名即可识别），或放一个 python3.cmd 转发到 python.exe',
                  '装完重开终端，再跑一次 install.cmd',
                ]
              : [
                  '安装 Python 3，并确保 python3 在 PATH 中',
                  '装完重开终端，再跑一次 install.sh',
                ],
          impact: `${who} 的脚本/hooks 会在触发时报错，相关保护与流程不生效`,
        };
      }

      const result = await run(buildSpawnSpec(found.path, ['--version'], { platform }), {
        timeoutMs: PYTHON_TIMEOUT_MS,
      });
      const raw = [result.stdout, result.stderr]
        .filter((text) => typeof text === 'string' && text.trim() !== '')
        .join(' ')
        .trim();

      if ((result.error !== null && result.error !== undefined) || result.timedOut || result.code !== 0) {
        return {
          ok: false,
          detail: `${found.path} 存在但 --version 没跑通（${describeRunFailure(result, PYTHON_TIMEOUT_MS)}）`,
          remedy: [
            '确认它是真正的 Python 3，而不是应用商店的占位别名',
            '必要时重新安装 Python 3，或调整 PATH 中 Python 的位置',
          ],
          impact: `${who} 的脚本/hooks 会在触发时报错，相关保护与流程不生效`,
        };
      }

      const version = parsePythonVersion(raw) ?? lastLine(raw, 40);
      return { ok: true, detail: `${version}，${found.path}（${who} 的脚本/hooks 需要）` };
    },
  };
}
