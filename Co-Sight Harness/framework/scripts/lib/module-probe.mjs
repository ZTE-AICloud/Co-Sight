/**
 * 模块注册表的**只读探活**。
 *
 * 边界说明（重要）：模块是独立部署的独立前端，运行时清单契约里**没有"启动命令"字段**，
 * 只有 `entry`（前端入口 URL）、`capability`、`healthcheck`（可为 null）。
 * 所以这里能做的只有两件事：把已注册的模块列出来，以及按清单里声明的
 * healthcheck 地址探活。
 *
 * **本文件不负责拉起模块。** 启动方式登记在旁挂的清单里，按场景分成两份：
 *
 *   `docs/modules/<id>.launch.json`    → `dev-all.mjs`（开发编排）
 *   `docs/modules/<id>.artifact.json`  → `start.mjs`（装配态，见 D41）
 *
 * 运行时契约因此保持原样，`/api/modules` 也不会把 shell 命令发给浏览器。
 * `start.mjs` 拉起模块之后仍然回到这里做一次复核探活——所以"探活"这件事
 * 在两种布局下都存在，区别只是谁负责把进程起起来。
 *
 * 这也是 `healthcheck` 字段在全仓库的**第一个消费点**：在此之前它只被 schema
 * 声明、没有任何读取方。
 *
 * 刻意不复用 harness-shared 的 `moduleManifestSchema`：scripts/ 不是工作区包，
 * 而共享层是"不构建、直接导出 src/*.ts"的 TypeScript 源码，.mjs 里 import 不了。
 * 契约校验的唯一真相仍在服务端的 registry（`/api/modules` 会把非法清单报出来）；
 * 这里只解析输出所需的那几个字段，清单合法性判断不在这里重复一份。
 */

import fs from 'node:fs';
import path from 'node:path';

import { httpGet } from './runtime.mjs';
import { stripBom } from './text.mjs';

/** 单个 healthcheck 的超时。取 2s：本机/内网服务要么秒回，要么就是没起。 */
const PROBE_TIMEOUT_MS = 2000;

/**
 * @param {string} modulesDir 通常是 `$COSIGHT_HOME/modules`
 * @returns {Array<{dir: string, file: string, hasFile: boolean, id: string, label: string, entry: string|null, healthcheck: string|null, problem: string|null}>}
 */
export function scanModuleManifests(modulesDir) {
  let dirents;
  try {
    dirents = fs.readdirSync(modulesDir, { withFileTypes: true });
  } catch (error) {
    // 目录不存在是**正常状态**：还没装任何模块。不当成错误。
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  }

  return dirents
    .filter((dirent) => dirent.isDirectory())
    .map((dirent) => dirent.name)
    .toSorted()
    .map((name) => readManifest(modulesDir, name));
}

function readManifest(modulesDir, dirName) {
  const file = path.join(modulesDir, dirName, 'module.json');
  const base = {
    dir: dirName,
    file,
    hasFile: false,
    id: dirName,
    label: dirName,
    entry: null,
    healthcheck: null,
    problem: null,
  };

  let parsed;
  try {
    // stripBom：Windows 记事本存出来的 module.json 带 BOM，JSON.parse 会直接抛，
    // 用户看到的是"这个模块没被探到"（见 lib/text.mjs）。
    parsed = JSON.parse(stripBom(fs.readFileSync(file, 'utf8')));
  } catch (error) {
    // 坏清单不该让启动脚本失败：模块是可选的，一个模块写错了
    // 不该升级成"框架起不来"。
    const missing = error.code === 'ENOENT';
    return {
      ...base,
      hasFile: !missing,
      problem: missing ? '没有 module.json' : `清单无法解析：${error.message}`,
    };
  }

  const id = typeof parsed.id === 'string' && parsed.id !== '' ? parsed.id : dirName;
  return {
    ...base,
    hasFile: true,
    id,
    label: pickLocalizedText(parsed.name) ?? id,
    entry: typeof parsed.entry === 'string' ? parsed.entry : null,
    healthcheck: typeof parsed.healthcheck === 'string' && parsed.healthcheck !== '' ? parsed.healthcheck : null,
    problem: null,
  };
}

/** 清单里的 name/description 是多语言对象；挑一个能给人看的即可。 */
function pickLocalizedText(value) {
  if (typeof value !== 'object' || value === null) {
    return null;
  }
  for (const locale of ['zh-CN', 'en']) {
    if (typeof value[locale] === 'string' && value[locale] !== '') {
      return value[locale];
    }
  }
  const first = Object.values(value).find((item) => typeof item === 'string' && item !== '');
  return typeof first === 'string' ? first : null;
}

/**
 * 逐个探活。全部并发发出，整体耗时约等于最慢的那一个而不是累加。
 *
 * @param {ReturnType<typeof scanModuleManifests>} manifests
 * @param {{platformSkipped?: Map<string, string>}} [options]
 *   `platformSkipped`：模块 id → 不适用原因。这些模块本次启动根本没被拉起
 *   （清单 `platforms` 不含当前平台），探活必然失败，所以不探、直接按"本平台不适用"报告。
 * @returns {Promise<Array<{manifest: object, status: 'registered'|'reachable'|'unhealthy'|'unreachable'|'skipped', detail: string}>>}
 */
export async function probeModules(manifests, options = {}) {
  const platformSkipped = options.platformSkipped ?? new Map();
  return Promise.all(
    manifests.map(async (manifest) => {
      const skipReason = platformSkipped.get(manifest.id);
      if (skipReason !== undefined) {
        return { manifest, status: 'skipped', detail: skipReason };
      }
      if (manifest.problem !== null) {
        return { manifest, status: 'registered', detail: manifest.problem };
      }
      if (manifest.healthcheck === null) {
        return { manifest, status: 'registered', detail: '已注册，清单未声明 healthcheck' };
      }

      const result = await httpGet(manifest.healthcheck, PROBE_TIMEOUT_MS);
      if (result.status >= 200 && result.status < 300) {
        return { manifest, status: 'reachable', detail: `可达（HTTP ${result.status}）` };
      }
      if (result.status !== 0) {
        return { manifest, status: 'unhealthy', detail: `有响应但非 2xx（HTTP ${result.status}）` };
      }
      // httpGet 已经把 undici 的 "fetch failed" 展开成带 errno 的说明，
      // 这里只补一个更贴近用户心智的说法。
      const reason = result.error?.includes('TimeoutError') ? '探活超时' : result.error;
      return { manifest, status: 'unreachable', detail: `不可达（${reason ?? '未知原因'}）` };
    }),
  );
}

/** 把探活结果渲染成给人看的行。探活只报告，不影响退出码。 */
export function formatProbeReport(results) {
  if (results.length === 0) {
    return ['  未注册任何模块（$COSIGHT_HOME/modules 为空或不存在）—— 框架本身不受影响。'];
  }

  const lines = [];
  for (const { manifest, status, detail } of results) {
    // `skipped` 单独一个记号：它不是"没起来"，而是"本平台用不上"，
    // 和 `—`（注册了但没探到）混在一起会让人以为模块坏了。
    const marker = status === 'reachable' ? '✓' : status === 'skipped' ? '·' : '—';
    lines.push(`  ${marker} ${manifest.id}（${manifest.label}）：${detail}`);
    if (manifest.entry !== null) {
      lines.push(`      入口 ${manifest.entry}`);
    }
    // 只在本目录里确实有清单文件时才打印它的路径，否则等于指着一个不存在的文件。
    if (manifest.hasFile) {
      lines.push(`      清单 ${manifest.file}`);
    }
  }
  return lines;
}
