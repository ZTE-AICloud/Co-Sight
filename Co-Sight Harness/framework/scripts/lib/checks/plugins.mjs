/**
 * 插件载荷检查：五个插件是否齐全、清单是否自洽、产物是否完整。
 *
 * 它不安装任何东西，只看"我们打算装进去的东西对不对"。安装失败是下一阶段
 * （`ensurePlugins`）的事，两者的报错要能分开看：这里是"包不对"，那里是
 * "这台机器装不进去"。
 */

/**
 * 交付要求里点名的五个插件（源码目录名）。
 *
 * 之所以写死在宿主侧而不是从清单推导：用户要的就是这五个。清单少一个时
 * 应当失败，而不是安静地少装一个。
 */
export const EXPECTED_PLUGIN_DIRS = [
  'drive',
  'agent-genesis',
  'agent-evaluator',
  'skill-optimizer',
  'cosight-bot',
];

const REMEDY_LIMIT = 6;

function remedyFor(pluginReport, required) {
  const remedy = [];
  if (pluginReport.mode === 'artifact') {
    remedy.push('重新解压安装包：产物里的 plugins/index.json 必须与插件目录内容一致');
  } else {
    remedy.push('检查五个插件目录，以及 scripts/artifact/plugins.json 里的坐标');
  }
  if (required) {
    remedy.push('确认解压完整，或重新下载安装包');
  }
  remedy.push('临时跳过插件安装：--skip-plugins（模块仍会启动，依赖插件的能力不可用）');
  return remedy;
}

/**
 * @param {{pluginReport: {mode: string, plugins: Array<{dir: string, plugin: string,
 *   version?: string, files?: number}>, problems: string[], line: string},
 *   expectedDirs?: string[], required?: boolean}} options
 *   `required`：产物布局下插件载荷必需；仓库布局下允许为空（开发者自己管）。
 */
export function pluginsCheck(options) {
  const pluginReport = options.pluginReport;
  const expectedDirs = options.expectedDirs ?? EXPECTED_PLUGIN_DIRS;
  const required = options.required === true;

  return {
    id: 'plugins',
    label: '插件载荷',
    level: 'block',
    run: () => {
      const problems = [...pluginReport.problems];

      if (pluginReport.mode === 'none') {
        if (required) {
          problems.push('产物里没有 plugins/ 目录');
        }
      } else {
        const present = new Set(pluginReport.plugins.map((item) => item.dir));
        for (const dir of expectedDirs) {
          if (!present.has(dir)) {
            problems.push(`缺少插件 ${dir}`);
          }
        }
      }

      if (problems.length > 0) {
        const shown = problems.slice(0, REMEDY_LIMIT);
        if (problems.length > shown.length) {
          shown.push(`…另有 ${problems.length - shown.length} 处`);
        }
        return {
          ok: false,
          detail: `${problems.length} 处问题`,
          remedy: [...shown, ...remedyFor(pluginReport, required)],
          impact: '插件可能装不上或装错版本，专家页与依赖插件的能力不可用；启动已中止',
        };
      }

      if (pluginReport.mode === 'none') {
        return { ok: true, detail: pluginReport.line };
      }

      const fileCount = pluginReport.plugins.reduce((sum, item) => sum + (item.files ?? 0), 0);
      const where = pluginReport.mode === 'artifact' ? '产物' : '仓库';
      return {
        ok: true,
        detail: `${pluginReport.line}（${where}，共 ${fileCount} 个文件）`,
      };
    },
  };
}
