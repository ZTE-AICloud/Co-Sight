/**
 * 产物里的模块：有哪些、清单有没有问题、声明过的文件还在不在。
 *
 * 这一段原先内联在 `start.mjs` 里，且**所有问题都只提示、不阻塞**。现在它是
 * 前置检查的一项（`modulesCheck`），默认阻塞：产物里带的模块是产品的一部分，
 * "专家页打不开"不能算可接受的降级（`--keep-going` 可以恢复旧语义）。
 *
 * 检查的深度刻意停在"不起进程就能确定"的范围：
 *   - `module.json` 在不在（服务端注册表只认它）；
 *   - `artifact.json` 能不能解析成运行时计划；
 *   - 启动命令里 node 入口文件在不在（挡"模块目录搬进来了、入口没构建"）；
 *   - 打包期承诺过的 `bundle.required` / `bundle.executable` 是否仍然成立
 *     （挡"产物被手工搬动过、少了一个 .so 或可执行位"）。
 */

import fs from 'node:fs';
import path from 'node:path';

import { resolveSpecForRuntime, scanArtifactSpecs, START_AFTER_FRAMEWORK } from '../artifact-spec.mjs';

/**
 * 判读产物里的模块。
 *
 * @param {{modulesDir: string|null, home: string, noModules?: boolean,
 *   frameworkUrl: string}} options
 */
export function describeModules(options) {
  const { modulesDir } = options;

  if (options.noModules === true) {
    return { line: '不拉起（--no-modules）', specs: [], plans: [], skipped: [], problems: [] };
  }
  if (modulesDir === null) {
    return { line: '仓库布局，由 pnpm dev:all 负责（这里只探活）', specs: [], plans: [], skipped: [], problems: [] };
  }

  const { specs, problems: scanProblems } = scanArtifactSpecs(modulesDir);
  const problems = scanProblems.map((item) => `${item.id}：${item.message}`);
  const plans = [];
  const skipped = [];
  // 平台跳过的模块仍留在注册表里（前端要知道"有这个东西，只是本机跑不了"），
  // 但探活时必须区别对待：它们根本没被拉起，探活必然 ECONNREFUSED，
  // 报出来就像模块坏了。这里把 id 与原因带出去，供启动后的小结使用。
  const platformSkips = [];
  const platform = `${process.platform}-${process.arch}`;

  for (const spec of specs) {
    let plan;
    try {
      plan = resolveSpecForRuntime(spec, {
        moduleDir: path.join(modulesDir, spec.id),
        dataDir: options.home,
        frameworkUrl: options.frameworkUrl,
      });
    } catch (error) {
      // 一份清单坏掉只影响这一个模块：记下来，别的照常解析（报告里会一起列出）。
      problems.push(`${spec.id}：清单无法用于启动：${error.message}`);
      continue;
    }

    // 模块可以声明自己支持哪些平台。一份包同时发 linux-x64 / win32-x64，
    // 在别的平台上这个模块不是"坏了"，而是"本就不适用"——跳过并说清楚。
    if (spec.platforms !== null && !spec.platforms.includes(platform)) {
      const note = `仅支持 ${spec.platforms.join(' + ')}，当前 ${platform}`;
      skipped.push(`${spec.id}（${note}）`);
      platformSkips.push({ id: spec.id, note });
      continue;
    }

    plans.push(plan);
    problems.push(...inspectBundledModule(spec, plan, modulesDir));
  }

  const line = specs.length === 0
    ? `（${path.basename(modulesDir)}/ 里没有可启动的模块）`
    : `${plans.length} 个：${plans.map((plan) => plan.id).join(', ')}` +
      (skipped.length === 0 ? '' : `；跳过 ${skipped.join('、')}`);

  return { line, specs, plans, skipped, platformSkips, problems };
}

/**
 * 一个模块目录是否还完整。
 *
 * 先查"能在不起进程的前提下确定"的启动前提，再核对打包期承诺过的文件清单。
 * 后者是"产物被搬坏"的最早信号：打包机上一一断言过，运行期再核一遍，
 * 才能发现中途丢文件/丢权限位的情况。
 */
export function inspectBundledModule(spec, plan, modulesDir) {
  const problems = [];

  if (!fs.existsSync(path.join(modulesDir, spec.id, 'module.json'))) {
    problems.push(`${spec.id}：缺少 module.json（运行时契约），/api/modules 里看不到它`);
  }

  // prepare 与 services 都只核对 node 命令入口文件之外的"存在性"：
  // 别的程序（sh、cmd、二进制）无法可靠地判断"这个参数是文件还是开关"，
  // 猜错会把正常模块报成坏的。
  const checkCommand = (label, step) => {
    if (!fs.existsSync(step.cwd)) {
      problems.push(`${label} 的工作目录不存在：${step.cwd}`);
      return;
    }
    const [program, ...args] = step.command;
    if (program === process.execPath && args.length > 0 && !args[0].startsWith('-')) {
      const entry = path.resolve(step.cwd, args[0]);
      if (!fs.existsSync(entry)) {
        problems.push(`${label} 的入口文件不存在：${entry}`);
      }
    }
  };

  for (const step of plan.prepare) {
    checkCommand(`${spec.id}:${step.name}`, step);
  }
  for (const service of plan.services) {
    checkCommand(`${spec.id}:${service.name}`, service);
  }

  problems.push(...inspectDeclaredFiles(spec, modulesDir));

  return problems;
}

/**
 * `bundle.required` / `bundle.executable` 的落地核对。
 *
 * 这两个字段原先只被打包脚本读（"这些路径一定进了包"）。运行期读它不算重复：
 * 用户可能手工删过东西、解压器可能丢过权限位，而这两种坏法在启动时只表现为
 * 一个语焉不详的模块崩溃。
 */
function inspectDeclaredFiles(spec, modulesDir) {
  const problems = [];
  const moduleDir = path.join(modulesDir, spec.id);

  for (const relative of spec.bundle.required) {
    const stat = fs.statSync(path.join(moduleDir, relative), { throwIfNoEntry: false });
    if (stat === undefined || !stat.isFile() || stat.size === 0) {
      problems.push(`${spec.id}：声明为必需的路径不存在或为空：${relative}`);
    }
  }

  for (const relative of spec.bundle.executable) {
    const stat = fs.statSync(path.join(moduleDir, relative), { throwIfNoEntry: false });
    if (stat === undefined || !stat.isFile()) {
      problems.push(`${spec.id}：声明为可执行件的路径不存在：${relative}`);
      continue;
    }
    // Windows 上没有可执行位这个概念，chmod 也改不了它——只在 POSIX 上要求。
    if (process.platform !== 'win32' && (stat.mode & 0o111) === 0) {
      problems.push(
        `${spec.id}：${relative} 丢了可执行位（mode=${(stat.mode & 0o777).toString(8)}）`,
      );
    }
  }

  return problems;
}

/**
 * 前置检查项。`describeModules` 的结果里只要有 problem 就失败；`skipped`
 * （平台不支持的模块）不算失败——那是"本就不适用"，不是"缺失"。
 *
 * @param {{moduleReport: ReturnType<typeof describeModules>}} options
 */
export function modulesCheck(options) {
  const { moduleReport } = options;

  return {
    id: 'modules',
    label: '模块',
    level: 'block',
    run: () => {
      if (moduleReport.problems.length === 0) {
        return { ok: true, detail: moduleReport.line };
      }
      return {
        ok: false,
        detail: `${moduleReport.problems.length} 处问题（${moduleReport.line}）`,
        remedy: [
          ...moduleReport.problems.map((problem) => `修复或移除：${problem}`),
          '若只想启动框架本身，可加 --no-modules（模块不会出现在注册表里）',
        ],
        impact: '对应的模块不会被拉起，模块页面会显示"尚未接入"',
      };
    },
  };
}

/**
 * 按启动时机把计划分成两组。
 *
 * 顺序：立即可起的模块 → 框架 → 声明了 `startAfter: framework` 的模块。
 * 后者要回调框架（读工作区、读模型配置），框架没就绪时它们会启动失败，
 * 而失败信息看起来像模块自己的错。
 *
 * @param {ReturnType<typeof describeModules>['plans']} plans
 */
export function partitionPlans(plans) {
  return {
    immediate: plans.filter((plan) => plan.startAfter !== START_AFTER_FRAMEWORK),
    deferred: plans.filter((plan) => plan.startAfter === START_AFTER_FRAMEWORK),
  };
}
