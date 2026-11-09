/**
 * Claude Code 插件安装包的纯逻辑：清单校验、排除规则、随包生成的安装脚本。
 *
 * 为什么要有这一层：插件目录是**别的团队的源码**（本仓库里的 agent-genesis 由
 * 插件团队维护），打包不应该往里面加文件，也不该假定它下个版本还长这样。
 * 所以这里只做两件事：
 *   1. 按 `.claude-plugin/plugin.json` 的声明校验插件确实完整（声明的 agent /
 *      skill 文件都在），而不是靠一张写死的文件清单；
 *   2. 在归档里**额外**放三个文件（install.sh / install.cmd / INSTALL.md），
 *      它们属于"包的装配件"，不进源码树。
 *
 * 排除规则只认"运行期不可能被读到的东西"（CI 缓存、本地过程产物、环境变量文件）。
 * 反过来，`tests/`、`evaluation/`、`knowledge/` 都要带上：`/selftest` 是插件
 * 自带的运行期功能，不是开发期测试。
 */

import fs from 'node:fs';
import path from 'node:path';

/**
 * 插件目录顶层的排除名单。
 *
 * `work/`、`output/`、`.agent-genesis/` 是 pipeline 的运行期过程产物（插件自己的
 * .gitignore 也忽略它们）；`.claude/` 与 `.env` 属于本机配置与密钥，**绝不能进包**。
 */
const TOP_LEVEL_EXCLUDED = new Set([
  '.agent-genesis',
  '.claude',
  '.git',
  '.pytest_cache',
  '__pycache__',
  'coverage',
  'node_modules',
  'output',
  'work',
]);

/**
 * 任意层级都排除的目录。
 *
 * 与顶层名单分开：`output` 只排除**顶层**那一个——knowledge/golden 下的
 * `output-snapshot/` 是 golden 样例资产，名字里带 output 但不是过程产物，
 * 用"任意层级的 output"会把样例池挖空。
 */
const ANY_LEVEL_EXCLUDED = new Set(['.git', '.pytest_cache', '__pycache__', 'node_modules']);

/** 编辑器与 Python 字节码的残留。 */
const EXCLUDED_FILE = /(?:^|\/)(?:\.DS_Store|Thumbs\.db|[^/]*\.py[co]|[^/]*\.log)$/;
/** `.env` 与 `.env.*` 一并排除；`.env.example` 是给人看的模板，要随包发出去。 */
const ENV_FILE = /(?:^|\/)\.env(?:\.(?!example$)[^/]+)?$/;

/**
 * 归档里要排除某个相对路径吗？
 *
 * 传入的是**相对插件根目录**的路径，目录与文件都过同一条规则：命中目录时
 * `collectEntries` 会整棵子树跳过，命中单个文件时只丢那一个。
 *
 * @param {string} relativePath 形如 `skills/harness-create/SKILL.md`
 * @returns {boolean}
 */
export function isExcluded(relativePath) {
  const segments = relativePath.split('/');
  if (TOP_LEVEL_EXCLUDED.has(segments[0])) {
    return true;
  }
  if (segments.some((segment) => ANY_LEVEL_EXCLUDED.has(segment))) {
    return true;
  }
  return EXCLUDED_FILE.test(relativePath) || ENV_FILE.test(relativePath);
}

/** 把清单里 `"./agents/x.md"` 这种写法归一成相对路径。 */
function normalizeManifestPath(value) {
  return typeof value === 'string' ? value.replace(/^\.\//, '') : '';
}

function readJsonFile(filePath, label) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`缺少 ${label}：${filePath}`);
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`${label} 不是合法 JSON：${reason}`, { cause: error });
  }
}

/** 清单里的路径数组 → 去掉 `./` 前缀的相对路径数组。 */
function manifestPathList(value) {
  return Array.isArray(value) ? value.map(normalizeManifestPath).filter(Boolean) : [];
}

/**
 * 读插件清单并做最小限度的可信校验。
 *
 * 只校验"打包能不能正确地进行"所必需的东西：名字/版本得能拼进文件名，
 * `marketplace.json` 得真的列出这个插件（否则装的时候 `install name@marketplace`
 * 会找不到目标——而这个错要到用户机器上才暴露）。
 *
 * @param {string} pluginDir 插件根目录
 * @returns {{name: string, version: string, marketplaceName: string, description: string,
 *   agents: string[], skills: string[], commands: string[], manifest: object}}
 */
export function readPluginMetadata(pluginDir) {
  const manifest = readJsonFile(
    path.join(pluginDir, '.claude-plugin', 'plugin.json'),
    '.claude-plugin/plugin.json',
  );
  const marketplace = readJsonFile(
    path.join(pluginDir, '.claude-plugin', 'marketplace.json'),
    '.claude-plugin/marketplace.json',
  );

  const name = manifest.name;
  if (typeof name !== 'string' || name.trim() === '') {
    throw new Error('.claude-plugin/plugin.json 缺少非空的 name');
  }
  const version = manifest.version;
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(version)) {
    throw new Error(`.claude-plugin/plugin.json 的 version 不是可用的版本号：${String(version)}`);
  }

  const marketplaceName = marketplace.name;
  if (typeof marketplaceName !== 'string' || marketplaceName.trim() === '') {
    throw new Error('.claude-plugin/marketplace.json 缺少非空的 name');
  }
  const listed = Array.isArray(marketplace.plugins)
    ? marketplace.plugins.some((plugin) => plugin?.name === name)
    : false;
  if (!listed) {
    throw new Error(`.claude-plugin/marketplace.json 的 plugins 里没有列出 ${name}`);
  }

  return {
    name,
    version,
    marketplaceName,
    description: typeof manifest.description === 'string' ? manifest.description : '',
    agents: manifestPathList(manifest.agents),
    skills: manifestPathList(manifest.skills),
    commands: manifestPathList(manifest.commands),
    manifest,
  };
}

/**
 * 当前 Claude Code 的插件发现规则与「清单里声明什么」之间的两处已知冲突。
 *
 * 这是**实测**结果（claude plugin details 的 Component inventory）：
 *  - `agents` 写成 `.md` 文件数组时会被校验接受，但安装后加载 0 个；
 *    把该字段整个去掉，默认 `agents/` 目录发现能加载全部。
 *  - `commands` 写成空数组时，CLI 会明确忽略默认 `commands/` 目录；
 *    去掉字段后 `commands/*.md` 才会被加载。
 *
 * 这两条都不是"配置写错"，而是清单字段与默认目录发现之间的取舍。打包默认
 * **忠实于源码**；只有显式传 `--compat-manifest` 时才在包内改写清单，
 * 并把改了什么写进 INSTALL.md 与打包输出。
 *
 * @param {object} manifest 原始 plugin.json
 * @returns {Array<{field: string, reason: string}>}
 */
export function manifestCompatAdjustments(manifest) {
  const adjustments = [];
  if (Array.isArray(manifest.agents) && manifest.agents.length > 0) {
    adjustments.push({
      field: 'agents',
      reason: '显式 agents 列表在当前 Claude Code 下加载 0 个；去掉该字段即按默认 agents/ 目录发现全部 agent',
    });
  }
  if (Array.isArray(manifest.commands) && manifest.commands.length === 0) {
    adjustments.push({
      field: 'commands',
      reason: '空 commands 数组会让 CLI 忽略默认 commands/ 目录；去掉该字段即恢复命令发现',
    });
  }
  return adjustments;
}

/** 按调整项生成包内清单（深拷贝一层即可：只删顶层字段）。 */
export function buildCompatibleManifest(manifest, adjustments) {
  const next = { ...manifest };
  for (const adjustment of adjustments) {
    delete next[adjustment.field];
  }
  return next;
}

/**
 * 包内清单文件的条目（覆盖源码里的那一份）。
 *
 * @param {string} base 归档根目录名
 * @param {object} manifest 已调整的清单
 */
export function manifestOverrideEntry(base, manifest) {
  const buffer = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return {
    path: archivePath(base, '.claude-plugin/plugin.json'),
    absPath: null,
    kind: 'file',
    mode: 0o644,
    size: buffer.length,
    read: () => buffer,
  };
}

/**
 * 归档文件名与落盘路径。
 *
 * 后缀 `-plugin` 是刻意加的：同一个 `.package/` 里还放框架自己的产物，
 * 两者一旦重名，最先丢的是"这份包到底是什么"。
 *
 * @param {string} packageDir 产物目录
 * @param {string} name 插件名
 * @param {string} version 插件版本
 */
export function pluginArchivePaths(packageDir, name, version) {
  const base = `${name}-${version}`;
  return {
    base,
    tarball: path.join(packageDir, `${base}-plugin.tar.gz`),
    zip: path.join(packageDir, `${base}-plugin.zip`),
    manifest: path.join(packageDir, `${base}-plugin.manifest.txt`),
  };
}

/** 归档根的 POSIX 形式（tar/zip 里一律用 `/`，不随打包平台变化）。 */
function archivePath(base, relative) {
  return `${base}/${relative}`;
}

/**
 * 包里**必须**存在的条目（不含随包生成的装配件）。
 *
 * 来源分两类：清单里声明的 agent / skill / command 文件（声明了就必须在），
 * 以及 Claude Code 认的几个固定位置。写死一份"agent-genesis 的文件列表"
 * 会在插件下次改结构时变成一句假话，所以前者从清单推导。
 *
 * @param {{agents: string[], skills: string[], commands: string[]}} metadata
 */
export function declaredPluginPaths(metadata) {
  return [
    'README.md',
    ...metadata.agents,
    // 清单里的 skill 写的是**目录**（`./skills/harness-create`）；真正被加载的是
    // 目录下的 SKILL.md。只检查目录存在没有意义——空目录也能通过。
    ...metadata.skills.map((directory) => `${directory}/SKILL.md`),
    ...metadata.commands,
  ];
}

/** 随包生成、不属于插件源码的三个装配件。 */
export const GENERATED_PLUGIN_FILES = ['install.sh', 'install.cmd', 'INSTALL.md'];

/**
 * 生成安装脚本与说明。
 *
 * 这些文件放在归档根目录（与 `.claude-plugin/` 同级），安装基准就是包根目录。
 * 插件源码树里另有一份 `scripts/install.sh`，面向的是仓库 checkout，
 * 两者路径基准不同——安装包里以这里生成的为准。
 *
 * @param {{name: string, version: string, marketplaceName: string, description: string}} metadata
 * @param {Array<{field: string, reason: string}>} [adjustments] 包内清单做的兼容调整
 * @returns {Array<{relative: string, mode: number, content: string}>}
 */
export function renderGeneratedFiles(metadata, adjustments = []) {
  return [
    { relative: 'install.sh', mode: 0o755, content: renderInstallSh(metadata) },
    { relative: 'install.cmd', mode: 0o755, content: renderInstallCmd(metadata) },
    { relative: 'INSTALL.md', mode: 0o644, content: renderInstallMd(metadata, adjustments) },
  ];
}

/**
 * 把生成的文件转成归档条目。
 *
 * 条目形状与 `collectEntries` 的产出一致，`writeTar` / `writeZip` 不必区分
 * "来自磁盘"还是"生成的内存内容"。
 *
 * @param {string} base 归档根目录名
 * @param {ReturnType<typeof readPluginMetadata>} metadata
 * @param {Array<{field: string, reason: string}>} [adjustments]
 */
export function generatedPluginEntries(base, metadata, adjustments = []) {
  return renderGeneratedFiles(metadata, adjustments).map(({ relative, mode, content }) => {
    const buffer = Buffer.from(content, 'utf8');
    return {
      path: archivePath(base, relative),
      absPath: null,
      kind: 'file',
      mode,
      size: buffer.length,
      read: () => buffer,
    };
  });
}

/** 哪些条目必须带着可执行位（解压后能直接 `bash install.sh`）。 */
export function executablePluginPaths(base) {
  return [archivePath(base, 'install.sh'), archivePath(base, 'install.cmd')];
}

function renderInstallSh({ name, version, marketplaceName }) {
  return `#!/usr/bin/env bash
# ${name} v${version} — Claude Code 插件安装包安装脚本
#
# 用法：
#   bash install.sh                 安装到用户级（scope=user）
#   bash install.sh --scope=project 安装到当前项目
#   bash install.sh --uninstall     卸载
#   bash install.sh --dry-run       只打印将要执行的命令
#
# 安装基准目录就是本脚本所在目录（即解压出来的包根目录）。
set -euo pipefail

HERE="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="${name}"
MARKETPLACE_NAME="${marketplaceName}"
SCOPE="user"
MODE="install"

for arg in "$@"; do
  case "$arg" in
    --scope=*)   SCOPE="\${arg#--scope=}" ;;
    --uninstall) MODE="uninstall" ;;
    --dry-run)   MODE="dry-run" ;;
    --help)
      sed -n '2,11p' "$0"
      exit 0
      ;;
    *)
      printf '[%s] 未知参数：%s\\n' "$PLUGIN_NAME" "$arg" >&2
      exit 1
      ;;
  esac
done

case "$SCOPE" in
  user|project|local) ;;
  *)
    printf '[%s] scope 只能是 user / project / local，收到：%s\\n' "$PLUGIN_NAME" "$SCOPE" >&2
    exit 1
    ;;
esac

say() { printf '[%s] %s\\n' "$PLUGIN_NAME" "$*"; }
run() {
  if [ "$MODE" = "dry-run" ]; then
    printf '  [dry-run] %s\\n' "$*"
  else
    "$@"
  fi
}

if [ ! -f "$HERE/.claude-plugin/plugin.json" ] || [ ! -f "$HERE/.claude-plugin/marketplace.json" ]; then
  say "包不完整：缺 .claude-plugin/plugin.json 或 marketplace.json"
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  say "未找到 claude CLI。请在 Claude Code 会话里手动执行："
  printf '    /plugin marketplace add %s\\n' "$HERE"
  printf '    /plugin install %s@%s\\n' "$PLUGIN_NAME" "$MARKETPLACE_NAME"
  exit 0
fi

if [ "$MODE" = "uninstall" ]; then
  run claude plugin uninstall "$PLUGIN_NAME@$MARKETPLACE_NAME" || say "插件可能未安装，继续"
  run claude plugin marketplace remove "$MARKETPLACE_NAME" || say "marketplace 可能未注册"
  say "卸载完成。"
  exit 0
fi

run claude plugin validate "$HERE" || say "validate 有警告，继续安装"
run claude plugin marketplace add "$HERE" || say "marketplace 可能已注册，继续"
run claude plugin install "$PLUGIN_NAME@$MARKETPLACE_NAME" --scope "$SCOPE"

say "安装完成（scope=$SCOPE）。重启 Claude Code 会话后生效。"
`;
}

function renderInstallCmd({ name, version, marketplaceName }) {
  return `@echo off
rem ${name} v${version} — Claude Code 插件安装包安装脚本（Windows）
rem
rem 用法：
rem   install.cmd            安装到用户级（scope=user）
rem   install.cmd project    安装到当前项目（project / local）
rem
rem 安装基准目录就是本脚本所在目录（即解压出来的包根目录）。
setlocal

set "HERE=%~dp0"
if "%HERE:~-1%"=="\\" set "HERE=%HERE:~0,-1%"
set "PLUGIN_NAME=${name}"
set "MARKETPLACE_NAME=${marketplaceName}"
set "SCOPE=%~1"
if "%SCOPE%"=="" set "SCOPE=user"

if not exist "%HERE%\\.claude-plugin\\plugin.json" goto :incomplete
if not exist "%HERE%\\.claude-plugin\\marketplace.json" goto :incomplete

where claude >nul 2>nul
if errorlevel 1 goto :no_cli

claude plugin validate "%HERE%"
claude plugin marketplace add "%HERE%"
if errorlevel 1 echo [%PLUGIN_NAME%] marketplace 可能已注册，继续
claude plugin install %PLUGIN_NAME%@%MARKETPLACE_NAME% --scope %SCOPE%
if errorlevel 1 goto :failed

echo [%PLUGIN_NAME%] 安装完成（scope=%SCOPE%）。重启 Claude Code 会话后生效。
exit /b 0

:incomplete
echo [%PLUGIN_NAME%] 包不完整：缺 .claude-plugin\\plugin.json 或 marketplace.json
exit /b 1

:no_cli
echo [%PLUGIN_NAME%] 未找到 claude CLI。请在 Claude Code 会话里手动执行：
echo     /plugin marketplace add %HERE%
echo     /plugin install %PLUGIN_NAME%@%MARKETPLACE_NAME%
exit /b 0

:failed
echo [%PLUGIN_NAME%] 安装失败，请检查上面的输出。
exit /b 1
`.replaceAll('\n', '\r\n');
}

function renderInstallMd({ name, version, marketplaceName }, adjustments) {
  const compatSection =
    adjustments.length === 0
      ? ''
      : `
## 包内清单的兼容调整

本包的 \`.claude-plugin/plugin.json\` 与插件源码树里的那份**不完全相同**：
打包时按当前 Claude Code 的插件发现规则去掉了下列字段（源码未改动）。

${adjustments.map((item) => `- \`${item.field}\`：${item.reason}`).join('\n')}

升级插件、或插件方修正清单后，重新打包即可；届时这一节会自动消失。
`;

  return `# ${name} v${version} 插件安装包

解压后本目录可直接作为 Claude Code 的 marketplace 安装源。

## 目录

- \`.claude-plugin/\` — 插件与 marketplace 清单（安装入口）
- \`agents/\` \`skills/\` \`commands/\` \`hooks/\` — 插件本体
- \`phase/\` \`knowledge/\` \`schemas/\` \`rules/\` \`templates/\` — pipeline 运行时依赖
- \`scripts/\` — 门禁与工具脚本
- \`tests/\` \`evaluation/\` — \`/selftest\` 与评测用例
- \`install.sh\` / \`install.cmd\` — 随包生成的安装脚本

## 环境要求

- Claude Code CLI（\`claude\` 在 PATH 中）
- Python 3（\`hooks/\` 与部分 \`scripts/\` 是 Python）
- Linux / macOS 下部分脚本需要 bash

## 安装

Linux / macOS：

\`\`\`bash
tar -xzf ${name}-${version}-plugin.tar.gz
cd ${name}-${version}
bash install.sh
\`\`\`

Windows（解压 zip 后在命令提示符中）：

\`\`\`bat
cd ${name}-${version}
install.cmd
\`\`\`

安装范围默认 \`user\`；项目级用 \`bash install.sh --scope=project\`，
Windows 用 \`install.cmd project\`。

### 安装脚本做了什么

1. 校验 \`.claude-plugin/plugin.json\` 与 \`.claude-plugin/marketplace.json\`；
2. \`claude plugin marketplace add <本目录>\`（本目录即 marketplace）；
3. \`claude plugin install ${name}@${marketplaceName} --scope user\`。

### 没有 claude CLI 时手动安装

在 Claude Code 会话中执行：

\`\`\`
/plugin marketplace add /绝对路径/${name}-${version}
/plugin install ${name}@${marketplaceName}
\`\`\`

## 验证

\`\`\`bash
claude plugin validate .
claude plugin list
\`\`\`

重启 Claude Code 会话后应能看到 \`${name}@${marketplaceName}\`。

## 卸载

\`\`\`bash
bash install.sh --uninstall
\`\`\`

或：

\`\`\`bash
claude plugin uninstall ${name}@${marketplaceName}
claude plugin marketplace remove ${marketplaceName}
\`\`\`

${compatSection}
## 说明

- 本包根目录的 \`install.sh\` / \`install.cmd\` 是随包生成的，安装基准就是包根目录。
- 插件源码里的 \`scripts/install.sh\` 面向仓库 checkout（同时支持 Codex 平台），
  与安装包的路径基准不同；从安装包安装时请用包根目录的这一份。
`;
}
