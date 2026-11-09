/**
 * 把模块搬进产物：判定、构建、展开条目、打包期断言。
 *
 * ── 判定规则只有一条 ────────────────────────────────────────────────────
 *
 * `framework/docs/modules/<id>.artifact.json` 存在 ⇒ 这个模块进产物。
 * 没有硬编码的模块名单：将来加一个模块，只需要多这一个文件。反过来，
 * 有 `module.json` 却没有 `artifact.json` 的模块会被列进"未打进"那一栏打印出来——
 * 漏打一个模块这件事，必须有人看得见。
 *
 * ── 为什么打包时可以跑模块的构建，却不能随手跑 npm install ──────────────
 *
 * 构建（`vite build`）只往 `dist/` 里写字节，用的工具链在**模块自己的
 * `node_modules` 里**，是仓库本来就有的东西。而 `npm install` 会联网、会写
 * 模块的 lockfile、还可能触发 `prepare` / `postinstall`——cosight-viewer 的
 * `prepare` 会往本仓库 `.git/config` 里写 `core.hooksPath`，把 Gerrit 的
 * commit-msg 钩子静默关掉（它的 launch.json 里为此写了一大段警告）。
 *
 * 所以安装不是"打包脚本自己决定跑什么"，而是**清单用 `bundle.install` 显式声明
 * 哪些命令可以安全跑**（一般带 `--ignore-scripts`），并且只在断言发现缺件时才跑、
 * 补上就停。正常打包一次安装都不会执行；缺件时由清单作者挑好的那条命令来补，
 * 而不是让脚本猜一条可能改坏 checkout 的 `npm install`。
 *
 * ── 为什么在这里就要求零软链 ────────────────────────────────────────────
 *
 * 模块的 `node_modules` 由 npm 装的，`.bin/` 里天然是一堆符号链接（实测 15 条）。
 * 它们只服务于 `npm exec` 与 package script，运行期一条都用不到，而 Windows
 * 自带解压器不建软链。所以 `exclude` 里必须把它们去掉，并在打包机上断言
 * 整棵模块树零软链——这条错误如果留到用户机器上，表现是"某个包变成 0 字节文件"，
 * 和依赖缺失长得一样。
 */

import fs from 'node:fs';
import path from 'node:path';

import { resolveSpecForPackaging, readArtifactSpec, ARTIFACT_SPEC_FILE_NAME } from './artifact-spec.mjs';
import { inspectBuild, runBuild } from './module-build.mjs';
import { collectEntries } from './walk.mjs';

const MODULE_SPEC_SUFFIX = '.artifact.json';
const MODULE_MANIFEST_SUFFIX = '.module.json';

/**
 * 生成数据库模板的等待上限。
 *
 * `bundle.database` 目前不开放 `timeoutMs`：它跑的是模块自己的建库脚本，
 * 正常在几秒内结束；真要更久（远端迁移之类）就不该在打包期做。
 */
const DATABASE_TIMEOUT_MS = 120_000;

/**
 * 本机配置与密钥绝不能进包。
 *
 * `.env.example` 是给人看的模板，要留着；`.env`、`.env.local`、`.env.production`
 * 这类是某台机器上的真实取值。模块目录由同事维护，`include` 又常常是整棵子树，
 * 一条 `"include": ["server"]` 就可能把 `.env` 一起带走——所以在这里兜底。
 */
const ENV_FILE_PATTERN = /(?:^|\/)\.env(?:\.(?!example$)[^/]+)?$/;

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/**
 * 读 `docs/modules/` 下的全部装配态清单。
 *
 * @param {{modulesDocDir: string, repoRoot: string}} options
 * @returns {{specs: Array<ReturnType<typeof resolveSpecForPackaging>>, unbundledIds: string[]}}
 */
export function scanModuleBundles(options) {
  let names;
  try {
    names = fs.readdirSync(options.modulesDocDir);
  } catch (error) {
    throw new Error(`读不到模块清单目录 ${options.modulesDocDir}：${error.message}`, { cause: error });
  }

  const specs = names
    .filter((name) => name.endsWith(MODULE_SPEC_SUFFIX))
    .toSorted()
    .map((name) =>
      resolveSpecForPackaging(
        readArtifactSpec(path.join(options.modulesDocDir, name)),
        { repoRoot: options.repoRoot },
      ),
    );

  const bundled = new Set(specs.map((spec) => spec.id));
  const unbundledIds = names
    .filter((name) => name.endsWith(MODULE_MANIFEST_SUFFIX))
    .map((name) => name.replace(/\.module\.json$/, ''))
    .filter((id) => !bundled.has(id))
    .toSorted();

  const duplicate = specs.map((spec) => spec.id).filter((id, index, all) => all.indexOf(id) !== index);
  if (duplicate.length > 0) {
    throw new Error(`模块 ${duplicate.join(', ')} 有多份装配态清单，不知道该信哪一份。`);
  }

  return { specs, unbundledIds };
}

/**
 * 产物内"这个模块是不是新鲜"的判定与重建。
 *
 * 判据完全复用开发态那一套（`module-build.mjs`）：输入里有比产物新的就重建。
 * 复用而不是另写一份的理由很实际——`cosight-viewer` 的 dist 是 gitignore 的，
 * 开发态与装配态面对的是同一个陈旧问题，两套判据迟早会给出不同答案。
 *
 * 构建失败**不降级**为"用现有 dist 凑合"：那正是这条判据要防的故障
 * （用户拿到一份页面是几天前的包，只会以为功能没做）。
 *
 * @returns {Promise<{status: 'rebuilt'|'fresh'|'none', detail: string}>}
 */
async function ensureSingleBuild(spec, build, position, options) {
  const before = inspectBuild(build);
  if (!before.stale) {
    return { status: 'fresh', detail: before.detail ?? before.reason };
  }

  options.writeLine?.(`  ${spec.id} 的产物需要重建：${before.detail ?? before.reason}`);
  const result = await runBuild(build, {
    label: `${spec.id}:build${position === null ? '' : `[${position}]`}`,
    env: process.env,
  });
  if (!result.ok) {
    const why = result.spawnError
      ?? (result.timedOut ? `超时（${build.timeoutMs}ms）` : `退出码 ${result.code}`);
    throw new Error(
      `模块 ${spec.id} 构建失败${position === null ? '' : `（第 ${position + 1} 个构建）`}：${why}\n` +
        `  命令：${build.command.join(' ')}（在 ${build.cwd}）\n` +
        '  打包脚本不会替你安装依赖。请先在模块目录里按它自己的 README 装好依赖再打包。\n' +
        '  若构建依赖「从 schema / 接口描述生成出来的代码」（例如 Prisma Client），' +
        '请把生成命令也声明成 bundle.builds 里的一步，放在构建之前——生成物是 gitignore 的，' +
        '改过 schema 之后它不会自己更新，编译就会报「某个字段不存在」。',
    );
  }

  // 构建"退出码 0"不等于"产物真的更新了"：有的脚本在缺工具时会安静地跳过。
  // 所以再判一次陈旧，这次必须是最新的。
  const after = inspectBuild(build);
  if (after.stale) {
    throw new Error(
      `模块 ${spec.id} 的构建命令返回成功，但产物仍然是旧的：${after.detail ?? after.reason}。` +
        '请检查清单里的 outputs 是否指向真正的产物。',
    );
  }

  return {
    status: 'rebuilt',
    detail: `已重建（${((result.elapsedMs ?? 0) / 1000).toFixed(1)}s）`,
  };
}

export async function ensureModuleBuild(spec, options = {}) {
  if (spec.builds.length === 0) {
    return { status: 'none', detail: '清单未声明构建步骤，直接搬运现有文件' };
  }

  // 单构建保持原来的文案（日志读起来更顺）；多构建时逐条报，否则不知道是哪一步慢。
  const results = [];
  for (const [index, build] of spec.builds.entries()) {
    results.push(await ensureSingleBuild(spec, build, spec.builds.length === 1 ? null : index, options));
  }

  if (spec.builds.length === 1) {
    return results[0];
  }

  const rebuilt = results.filter((result) => result.status === 'rebuilt');
  return {
    status: rebuilt.length > 0 ? 'rebuilt' : 'fresh',
    detail: results.map((result, index) => `[${index}] ${result.detail}`).join('；'),
  };
}

/**
 * 缺失依赖的补救命令：按依赖根里"实际有哪个锁文件"选，而不是猜。
 *
 * `npm ci` 会先删掉 `node_modules` 再按锁文件重装，`npm install` 则会顺手改写
 * 锁文件——两个命令对模块工作区的后果不同，选错了要把模块的锁文件复原，
 * 所以这里只推荐与该根自己的锁文件配套的那条。
 */
function installCommand(directory) {
  if (fs.existsSync(path.join(directory, 'package-lock.json'))) return 'npm ci';
  if (fs.existsSync(path.join(directory, 'pnpm-lock.yaml'))) return 'pnpm install';
  if (fs.existsSync(path.join(directory, 'yarn.lock'))) return 'yarn install';
  return 'npm install';
}

/** 路径含空白或引号时加引号，粘贴到 shell 里能直接用。 */
function shellPath(target) {
  return /[\s"']/.test(target) ? `"${target}"` : target;
}

/**
 * 依赖根里缺什么。空问题列表表示齐全。
 *
 * @returns {Array<{root: string, directory: string, problem: string, command: string|null}>}
 *   `directory` 同时用来判断哪个安装步骤与这处缺件相关；`command` 只在
 *   "装依赖能解决"时给出，缺 package.json 这类问题装什么都是猜，就留 `null`。
 */
function dependencyProblems(spec, moduleRoot) {
  // 依赖根默认是模块根；前后端各自装依赖的模块（例如 smart-factory 的 server/web）
  // 由清单列出多个根，逐棵核对。
  const roots = spec.dependencyRoots.length === 0 ? ['.'] : spec.dependencyRoots;
  const problems = [];

  for (const root of roots) {
    const directory = path.resolve(moduleRoot, root);
    const manifestPath = path.join(directory, 'package.json');
    if (!fs.existsSync(manifestPath)) {
      // 没有 package.json 时装什么都是猜的，不给命令。
      problems.push({ root, directory, problem: `${root}：缺少 package.json`, command: null });
      continue;
    }
    if (!fs.existsSync(path.join(directory, 'node_modules'))) {
      problems.push({
        root,
        directory,
        problem: `${root}：没有 node_modules`,
        command: `cd ${shellPath(directory)} && ${installCommand(directory)}`,
      });
      continue;
    }

    const dependencies = Object.keys(readJson(manifestPath).dependencies ?? {});
    const missing = dependencies.filter(
      (name) => !fs.existsSync(path.join(directory, 'node_modules', name, 'package.json')),
    );
    if (missing.length > 0) {
      problems.push({
        root,
        directory,
        problem: `${root}：缺 ${missing.join(', ')}`,
        command: `cd ${shellPath(directory)} && ${installCommand(directory)}`,
      });
    }
  }

  return problems;
}

/**
 * 模块的 `package.json` 里声明的每个运行期依赖，都必须真的在它的 `node_modules` 里。
 *
 * 这一条补的是"装依赖时用了 `--omit=optional` 或半路失败"留下的洞：
 * 打包机上一切正常（源码、dist 都在），用户机器上第一次 `require` 才炸。
 * 只查 `dependencies`：`devDependencies` 是构建期的事，不进产物。
 */
function assertDependenciesPresent(spec, moduleRoot) {
  const problems = dependencyProblems(spec, moduleRoot);
  if (problems.length === 0) {
    return;
  }

  const commands = problems
    .map((problem) => problem.command)
    .filter((command) => command !== null);
  const remedy = commands.length === 0
    ? ''
    : '\n  依赖必须由模块自己装好——打包脚本不会凭空猜安装命令（见 D34）。逐条执行：\n' +
      commands.map((line) => `    ${line}`).join('\n') +
      '\n  （模块 README 若还有额外步骤，以 README 为准。）';
  throw new Error(
    `模块 ${spec.id} 的依赖树不完整：\n  - ${problems.map((problem) => problem.problem).join('\n  - ')}${remedy}`,
  );
}

/** `bundle.executable` 里当前不存在的文件（可执行位的问题补装依赖也修不了，不算在内）。 */
function missingExecutables(spec) {
  return spec.executable.filter((item) => {
    const absolute = path.join(spec.moduleRoot, item);
    return !fs.existsSync(absolute) || !fs.statSync(absolute).isFile();
  });
}

/**
 * 构建根的 `node_modules` 是否整棵缺失。
 *
 * `dependencyRoots` 只覆盖**要随包发出去**的依赖根；构建工具（vite、tsc）落在
 * front-end 目录自己的 `node_modules` 里，从来没进过那个清单。只装了一半的树里，
 * 依赖断言全绿、构建却挂在 `Cannot find module 'vite'`——先补依赖能省掉这一趟。
 * 只认"该根声明了依赖却连 node_modules 都没有"：真有 node_modules 时不再逐个查
 * devDependencies，那是构建自己的事。
 */
function buildRootsMissingToolchain(spec) {
  return spec.builds.filter((build) => {
    const manifestPath = path.join(build.cwd, 'package.json');
    if (!fs.existsSync(manifestPath)) return false;
    let manifest;
    try {
      manifest = readJson(manifestPath);
    } catch {
      // 构建根自己会报 JSON 解析错，这里不抢它的台词。
      return false;
    }
    const declared =
      Object.keys(manifest.dependencies ?? {}).length +
      Object.keys(manifest.devDependencies ?? {}).length;
    return declared > 0 && !fs.existsSync(path.join(build.cwd, 'node_modules'));
  });
}

/** 手上有能自动补的缺件吗？没有就不跑安装步骤（正常打包一次都不联网）。 */
function needsRepair(spec) {
  return (
    dependencyProblems(spec, spec.moduleRoot).length > 0 ||
    missingExecutables(spec).length > 0 ||
    buildRootsMissingToolchain(spec).length > 0
  );
}

/** 当前缺件所在的位置（绝对路径）。 */
function repairTargets(spec) {
  return [
    ...missingExecutables(spec).map((item) => path.join(spec.moduleRoot, item)),
    ...buildRootsMissingToolchain(spec).map((build) => build.cwd),
    ...dependencyProblems(spec, spec.moduleRoot).map((problem) => problem.directory),
  ];
}

/** `target` 是否落在 `directory` 之内（含等于）。 */
function isInside(directory, target) {
  const relative = path.relative(directory, target);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * 按 `bundle.install` 补缺件。
 *
 * 只做清单**显式声明过**的步骤，不猜 `npm install`：cosight-viewer 的 `prepare`
 * 会往仓库 `.git/config` 里写 `core.hooksPath`，静默关掉 Gerrit 的 commit-msg 钩子
 * （见文件头）。清单作者最清楚哪些脚本能安全跑，所以由他在 `bundle.install` 里写，
 * 并且按顺序试、补上就停——最便宜的那条（补原生件）写在前面，整棵重装写在后面。
 *
 * 失败不在这里抛出：继续试后续步骤，最后仍缺的话由断言给出原来那条可复制的错误，
 * 用户看到的仍然是"缺什么、在哪补"，而不是一堆安装日志。
 */
async function repairBundle(spec, options) {
  if (options.fix === false || spec.install.length === 0 || !needsRepair(spec)) {
    return;
  }

  options.writeLine?.(`  ${spec.id}：依赖或原生件不全，按 bundle.install 自动补齐…`);
  for (const [index, step] of spec.install.entries()) {
    // 只跑与缺件位置相关的步骤：在没人缺东西的目录里重装一遍，
    // 既白等几分钟，又白白动一次别人的 checkout。
    const related = repairTargets(spec).some((target) => isInside(step.cwd, target));
    if (!related) {
      options.writeLine?.(`    跳过 ${step.command.join(' ')}（${step.cwd} 下没有缺件）`);
      continue;
    }
    options.writeLine?.(`    执行 ${step.command.join(' ')}（在 ${step.cwd}）…`);
    const result = await runBuild(step, { label: `${spec.id}:install[${index}]`, env: process.env });
    if (!result.ok) {
      const why = result.spawnError
        ?? (result.timedOut ? `超时（${step.timeoutMs}ms）` : `退出码 ${result.code}`);
      options.writeLine?.(`    ! 这一步没成功（${why}），继续下一步`);
      continue;
    }
    if (!needsRepair(spec)) {
      options.writeLine?.('    ✓ 已补齐');
      return;
    }
    options.writeLine?.('    · 还缺，继续下一步');
  }
}

/** 归档路径一律用 '/'，即使清单是在 Windows 上写的。 */
function toArchivePath(relative) {
  return relative.split(/[\\/]/).join('/');
}

/**
 * 原生件缺失时的补救提示。
 *
 * `bundle.executable` 往往是**按平台**才会装出来的东西（平台相关的原生可执行件、
 * Prisma 的 `binaryTargets` 生成物）。重装依赖（尤其 `npm ci`，它会先
 * 整个删掉 `node_modules`）会把它们一并清掉，于是同一份清单在"装完依赖"之后
 * 立刻又打包失败。模块若自带 `scripts/prepare-native-artifacts.mjs`（本仓库
 * smart-factory 的约定），直接把命令印在错误里，省掉一次翻文档。
 *
 * 脚本不存在时返回空串：没有约定就不猜，让清单作者自己决定怎么补。
 */
function prepareHint(spec) {
  const script = path.join(spec.moduleRoot, 'scripts', 'prepare-native-artifacts.mjs');
  if (!fs.existsSync(script)) {
    return '';
  }
  // 从仓库根执行时给相对路径（可直接复制），否则给绝对路径。
  const relative = path.relative(process.cwd(), script);
  const shown = relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative)
    ? toArchivePath(relative)
    : script;
  return (
    '\n  这类文件通常是按平台安装/生成的原生件，重装依赖（如 npm ci）后需要重新补齐。' +
    `\n  先在打包机上运行：node ${shown}` +
    '\n  （幂等，只补件、不装依赖；见 framework/docs/packaging.md §9）'
  );
}

/** 这个模块在产物里的顶层目录：`<base>/modules/<id>`。 */
function moduleDestination(spec, options) {
  return `${options.artifactBase}/${moduleDestinationRelative(spec, options)}`;
}

/**
 * 同上，但不带产物顶层目录。
 *
 * 读回校验的必需路径表是**相对产物根**的（`package.mjs` 统一加 `<base>/`），
 * 这里多带一层就会得到 `x/x/modules/...` 这种谁也看不懂的缺失报告。
 */
function moduleDestinationRelative(spec, options) {
  return `${toArchivePath(options.modulesSubdir)}/${spec.id}`;
}

/**
 * 读回校验用的必需路径。
 *
 * 只放"缺了就等于装配失败"的那几条：两份清单、include 里的单个文件、
 * 以及构建声明的产物。目录类 include 不在这里逐个展开——条目数已经在
 * `verifyArchive` 里逐个比对过，再列一遍只是同一件事写两次。
 */
function requiredPathsForModule(spec, options) {
  const destination = moduleDestinationRelative(spec, options);
  const required = [`${destination}/module.json`, `${destination}/${ARTIFACT_SPEC_FILE_NAME}`];

  for (const include of spec.include) {
    const absolute = path.join(spec.moduleRoot, include);
    if (fs.existsSync(absolute) && !fs.statSync(absolute).isDirectory()) {
      required.push(`${destination}/${toArchivePath(include)}`);
    }
  }

  for (const build of spec.builds) {
    for (const output of build.outputs) {
      const absolute = path.resolve(build.cwd, output);
      const relative = path.relative(spec.moduleRoot, absolute);
      // 产物写在模块目录之外是清单写错了；`resolveSpecForPackaging` 已经拦过
      // 构建目录，这里只防 outputs 里出现 `../..`。
      if (!relative.startsWith('..') && !path.isAbsolute(relative)) {
        required.push(`${destination}/${toArchivePath(relative)}`);
      }
    }
  }

  // 清单显式声明的"缺了就等于装配失败"的文件：构建产物里的原生件、
  // 生成的数据库模板、模块入口，都靠这一列钉住。
  for (const item of spec.required) {
    required.push(`${destination}/${toArchivePath(item)}`);
  }
  if (spec.database !== null) {
    required.push(`${destination}/${toArchivePath(spec.database.template)}`);
  }
  for (const asset of spec.assets) {
    // 目录 asset 与目录 include 同口径：collectEntries 不产出根目录条目，
    // 只钉文件（内容文件由 required 显式声明，如两个内置智能体的 agent.json）。
    const absolute = fs.existsSync(asset.from) && fs.lstatSync(asset.from).isDirectory();
    if (absolute) {
      continue;
    }
    required.push(`${destination}/${toArchivePath(asset.to)}`);
  }
  // 可执行件既要在，也要真的被 include 收进来（否则包里有清单、没文件）。
  for (const item of spec.executable) {
    required.push(`${destination}/${toArchivePath(item)}`);
  }

  return required;
}

/** 模块声明的可执行文件在产物里的路径（相对产物根，`package.mjs` 再加 `<base>/`）。 */
function executablePathsForModule(spec, options) {
  const destination = moduleDestinationRelative(spec, options);
  return spec.executable.map((item) => `${destination}/${toArchivePath(item)}`);
}

/**
 * 模块的源码目录必须真的在。
 *
 * 放在依赖断言之前，是为了让报错说到点子上：目录都不存在时，
 * 先查依赖只会得到"缺少 package.json"，而真正的原因是"这个模块没检出"。
 */
function requireModuleRoot(spec) {
  if (!fs.existsSync(spec.moduleRoot)) {
    throw new Error(
      `模块 ${spec.id} 的源码目录不存在：${spec.moduleRoot}\n` +
        '  装配态清单指向了一个没检出的模块。请先检出它，或删掉这份清单。',
    );
  }
}

function fileEntry(archivePath, absolute) {
  const stat = fs.statSync(absolute);
  return {
    path: archivePath,
    absPath: absolute,
    kind: 'file',
    mode: stat.mode & 0o7777,
    size: stat.size,
    read: () => fs.readFileSync(absolute),
  };
}

/**
 * 把一个模块展开成归档条目。
 *
 * `include` 里每一条都必须存在——写错一个路径就少搬一整个目录，而现象是
 * "用户点开某个页面 404"，排查时没人会想到是打包清单写错了。
 *
 * @param {ReturnType<typeof resolveSpecForPackaging>} spec
 * @param {{artifactBase: string, modulesSubdir: string, modulesDocDir: string, writeLine?: (line: string) => void}} options
 */
export function planModuleEntries(spec, options) {
  const moduleRoot = spec.moduleRoot;
  requireModuleRoot(spec);

  for (const exclude of spec.exclude) {
    if (!fs.existsSync(path.join(moduleRoot, exclude))) {
      // 不是错误：依赖装法不同时 .bin 之类的位置会变。但必须说出来——
      // 否则一条永远匹配不上的排除规则会安静地留在清单里。
      options.writeLine?.(`  ! ${spec.id} 的 exclude "${exclude}" 指向不存在的路径，这条规则没有生效`);
    }
  }

  const destination = moduleDestination(spec, options);
  const isExcluded = (relativeToModule) =>
    spec.exclude.some(
      (exclude) =>
        relativeToModule === exclude || relativeToModule.startsWith(`${exclude}/`),
    );

  const entries = [];

  for (const include of spec.include) {
    const absolute = path.join(moduleRoot, include);
    if (!fs.existsSync(absolute)) {
      throw new Error(
        `模块 ${spec.id} 的 bundle.include 里有不存在的路径：${include}（在 ${moduleRoot} 下）`,
      );
    }

    const archivePath = `${destination}/${toArchivePath(include)}`;
    const stat = fs.lstatSync(absolute);

    if (!stat.isDirectory()) {
      if (isExcluded(include)) {
        continue;
      }
      entries.push(fileEntry(archivePath, absolute));
      continue;
    }

    entries.push(
      ...collectEntries(absolute, {
        prefix: archivePath,
        prune: (relative) => isExcluded(`${toArchivePath(include)}/${toArchivePath(relative)}`),
      }),
    );
  }

  const symlinks = entries.filter((entry) => entry.kind === 'symlink');
  if (symlinks.length > 0) {
    throw new Error(
      `模块 ${spec.id} 的条目里有 ${symlinks.length} 条符号链接（Windows 解压后会是 0 字节文件）：\n` +
        `  - ${symlinks.slice(0, 5).map((entry) => entry.path).join('\n  - ')}\n` +
        `  请在 ${spec.id}.artifact.json 的 bundle.exclude 里把它们所在的目录排除掉。`,
    );
  }

  return entries;
}

/**
 * 清单里 `bundle.assets` 声明的文件或目录 → 归档条目。
 *
 * 用途是"模块目录里没有、但产物里必须有"的内容：打包期生成的数据库模板、
 * 仓库根的内置智能体定义目录等。`from` 相对仓库根（打包脚本已经解析成绝对路径），
 * `to` 落在模块目录内；`from` 是目录时整棵展开，`exclude` 按路径段名整树剔除。
 */
function assetEntries(spec, options) {
  const destination = moduleDestination(spec, options);
  return spec.assets.flatMap((asset) => {
    if (!fs.existsSync(asset.from)) {
      throw new Error(`模块 ${spec.id} 的 bundle.assets.from 不存在：${asset.from}`);
    }
    const prefix = `${destination}/${toArchivePath(asset.to)}`;
    if (!fs.lstatSync(asset.from).isDirectory()) {
      if (asset.exclude !== undefined) {
        throw new Error(`模块 ${spec.id} 的 bundle.assets.exclude 只对目录 asset 有意义：${asset.from}`);
        }
      return [fileEntry(prefix, asset.from)];
    }
    return collectEntries(asset.from, {
      prefix,
      // exclude 按段名匹配任何层级：命中段所在子树整棵剔除（walk 的 prune 对目录返回
      // true 即剪掉整棵子树，与 bundle.exclude 的语义对齐）。
      prune: (relative) => asset.exclude?.some((segment) => relative.split('/').includes(segment)) ?? false,
    });
  });
}

/**
 * 跑模块自己的建库脚本，产出一份**空库模板**放进产物。
 *
 * 为什么在打包机上生成，而不是让用户机器上第一次启动时建库：
 * 建库要 Prisma CLI，而 CLI 是开发依赖、体积不小；更重要的是"第一次启动要联网
 * 拉引擎/执行迁移"在离线机器上直接失败。模板是一份已经建好的空库，
 * 运行期只做一次文件拷贝。
 *
 * 生成目录在 `stagingDir` 下（打包脚本的临时区），**绝不写进模块源码树**：
 * 模块由同事维护，打包不该往他们的 checkout 里留文件。
 *
 * @returns {Promise<object|null>} 归档条目
 */
async function databaseEntry(spec, options) {
  if (spec.database === null) {
    return null;
  }
  if (typeof options.stagingDir !== 'string' || options.stagingDir.length === 0) {
    throw new Error(`模块 ${spec.id} 声明了 bundle.database，但打包脚本没有给出 stagingDir（内部错误）。`);
  }

  const staging = path.join(options.stagingDir, `${spec.id}-database`);
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging, { recursive: true });

  const databaseFile = path.join(staging, spec.database.file);
  options.writeLine?.(`  ${spec.id} 生成数据库模板…`);

  const result = await runBuild(
    {
      command: spec.database.command,
      cwd: spec.database.cwd,
      timeoutMs: DATABASE_TIMEOUT_MS,
      // 模块用自己的约定从 COSIGHT_HOME 推 DATABASE_URL（smart-factory 就是这样）；
      // 两个都给，是为了让"直接读 DATABASE_URL"的模块也能落在这个临时目录里。
      env: {
        COSIGHT_HOME: staging,
        DATABASE_URL: `file:${databaseFile.split(path.sep).join('/')}`,
      },
    },
    { label: `${spec.id}:database`, env: process.env },
  );

  if (!result.ok) {
    const why = result.spawnError
      ?? (result.timedOut ? `超时（${DATABASE_TIMEOUT_MS}ms）` : `退出码 ${result.code}`);
    throw new Error(
      `模块 ${spec.id} 生成数据库模板失败：${why}\n` +
        `  命令：${spec.database.command.join(' ')}（在 ${spec.database.cwd}）`,
    );
  }

  let size = 0;
  try {
    size = fs.statSync(databaseFile).size;
  } catch {
    throw new Error(
      `模块 ${spec.id} 的建库命令返回成功，但没有生成 ${databaseFile}。\n` +
        `  请检查 bundle.database.file（当前写的是 "${spec.database.file}"）是否与模块的库文件同名。`,
    );
  }
  if (size === 0) {
    throw new Error(`模块 ${spec.id} 生成的数据库模板是空文件：${databaseFile}`);
  }

  return fileEntry(`${moduleDestination(spec, options)}/${toArchivePath(spec.database.template)}`, databaseFile);
}

/**
 * 运行时契约（`module.json`）与装配态清单（`artifact.json`）本身也要进包。
 *
 * `module.json` 的真源在 `docs/modules/`，模块自己的目录里没有它；
 * `artifact.json` 在产物里的名字与仓库里不同（去掉 `<id>.` 前缀），
 * 所以两者都由这里生成，而不是从模块目录里捡。
 */
export function generatedModuleEntries(spec, options) {
  const destination = moduleDestination(spec, options);
  const manifestSource = path.join(options.modulesDocDir, `${spec.id}.module.json`);
  if (!fs.existsSync(manifestSource)) {
    throw new Error(`模块 ${spec.id} 有装配态清单，却没有 ${manifestSource}（运行时契约）。`);
  }

  return [
    fileEntry(`${destination}/module.json`, manifestSource),
    fileEntry(`${destination}/${ARTIFACT_SPEC_FILE_NAME}`, spec.file),
  ];
}

/**
 * 打包前的完整准备：判定 → 补缺件 → 构建 → 断言依赖 → 展开条目。
 *
 * 顺序是有意的：构建会改产物文件，必须发生在展开条目之前；
 * 依赖断言放在构建之后，因为构建本身也会读 `devDependencies` 之外的东西
 * （例如 vite 会去 `node_modules` 里找插件），先建再查能顺带证明工具链是好的。
 * 补缺件（`bundle.install`）放在最前面：构建要用工具链，缺的是工具链时先补，
 * 否则构建只会给出"找不到 vite"这种看不出根因的现象。
 *
 * @returns {Promise<{entries: Array<object>, builds: Array<{id: string, status: string, detail: string}>}>}
 */
export async function prepareModuleBundles(options) {
  const { specs, unbundledIds } = scanModuleBundles(options);
  const entries = [];
  const builds = [];
  const requiredPaths = [];
  const executablePaths = [];
  const platforms = [];
  const seenPaths = new Set();

  for (const spec of specs) {
    requireModuleRoot(spec);
    // 缺件先按清单声明的步骤补一轮；补不上再让下面的断言带着可复制的命令失败。
    await repairBundle(spec, options);
    assertDependenciesPresent(spec, spec.moduleRoot);

    // 可执行件在源码里就得是可执行的。Windows 上没有 Unix 权限位，
    // 只检查文件存在；Linux/macOS 上顺手把"解压后跑不起来"提前挡掉。
    for (const item of spec.executable) {
      const absolute = path.join(spec.moduleRoot, item);
      if (!fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
        throw new Error(
          `模块 ${spec.id} 的 bundle.executable 指向不存在的文件：${item}${prepareHint(spec)}`,
        );
      }
      if (process.platform !== 'win32' && (fs.statSync(absolute).mode & 0o111) === 0) {
        throw new Error(
          `模块 ${spec.id} 的 bundle.executable 文件没有可执行位：${item}（mode=${(fs.statSync(absolute).mode & 0o777).toString(8)}）`,
        );
      }
    }

    const build = await ensureModuleBuild(spec, { writeLine: options.writeLine });
    builds.push({ id: spec.id, ...build });
    platforms.push({ id: spec.id, platforms: spec.platforms });

    const moduleEntries = [
      ...generatedModuleEntries(spec, options),
      ...planModuleEntries(spec, options),
      ...assetEntries(spec, options),
    ];
    const database = await databaseEntry(spec, options);
    if (database !== null) {
      moduleEntries.push(database);
    }

    const leakedEnv = moduleEntries.find((entry) => ENV_FILE_PATTERN.test(entry.path));
    if (leakedEnv !== undefined) {
      throw new Error(
        `模块 ${spec.id} 会把本机环境变量文件打进产物：${leakedEnv.path}\n` +
          '  请在 bundle.exclude 里排除 .env（模板 .env.example 可以保留）。',
      );
    }

    // 同一条路径只能有一个来源。include 与 assets/database 打到同一处时，
    // 后者会被静默覆盖——那是最难查的一类"包里的文件不是我以为的那份"。
    const modulePaths = new Set();
    for (const entry of moduleEntries) {
      if (modulePaths.has(entry.path) || seenPaths.has(entry.path)) {
        throw new Error(`模块 ${spec.id} 有两条来源写出了同一个路径：${entry.path}`);
      }
      modulePaths.add(entry.path);
      seenPaths.add(entry.path);
    }

    // 必需路径表是相对产物根的，而条目带 `<base>/` 前缀；比较前先归一。
    const basePrefix = `${options.artifactBase}/`;
    const modulePathsRelative = new Set(
      [...modulePaths].map((item) => (item.startsWith(basePrefix) ? item.slice(basePrefix.length) : item)),
    );
    const moduleRequired = requiredPathsForModule(spec, options);
    const missingRequired = moduleRequired.filter((item) => !modulePathsRelative.has(item));
    if (missingRequired.length > 0) {
      throw new Error(
        `模块 ${spec.id} 声明了必需的路径，但它们没有被搬进产物：\n  - ${missingRequired.join('\n  - ')}\n` +
          '  请检查 bundle.include / bundle.assets / bundle.executable 是否覆盖了这些文件。',
      );
    }

    entries.push(...moduleEntries);
    requiredPaths.push(...moduleRequired);
    executablePaths.push(...executablePathsForModule(spec, options));
  }

  return { entries, builds, unbundledIds, requiredPaths, executablePaths, platforms };
}
