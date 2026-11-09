/**
 * 宿主机环境检查：数据目录、配置文件、前端产物、磁盘空间。
 *
 * 这四项共同点是**只读探测**：不建目录、不写文件。真正建目录与生成配置在
 * `--init` / `--install` 阶段，与这里刻意分开——`--self-check` 跑完不该在磁盘上
 * 留下任何痕迹。
 */

import fs from 'node:fs';
import path from 'node:path';

// 刻意不引 `../project.mjs`：那份文件只服务于打包、**不进产物**，
// 而本检查会随 start.mjs 一起发给用户。格式化的纯函数放在会被打进产物的 format.mjs。
import { humanSize } from '../format.mjs';

/** 低于这个可用空间时提醒（不阻塞）。模块首次启动要建数据库。 */
export const MIN_FREE_BYTES = 512 * 1024 * 1024;

/**
 * 数据目录能否就位。
 *
 * 目录不存在但上级可写也算通过——启动时会建。这条判定必须与 `runInit`
 * 的能力一致：这里判"不可写"而 `runInit` 其实能建，会让用户白改权限。
 */
export function inspectDataDir(homeDir) {
  if (fs.existsSync(homeDir)) {
    if (!fs.statSync(homeDir).isDirectory()) {
      return { ok: false, line: `${homeDir}（存在，但不是目录）` };
    }
    try {
      fs.accessSync(homeDir, fs.constants.W_OK);
      return { ok: true, line: `${homeDir}（已存在且可写）` };
    } catch {
      return { ok: false, line: `${homeDir}（存在但当前用户不可写）` };
    }
  }

  const parent = path.dirname(homeDir);
  if (!fs.existsSync(parent)) {
    return { ok: true, line: `${homeDir}（尚未创建，上级目录也不存在，启动时会一并创建）` };
  }
  try {
    fs.accessSync(parent, fs.constants.W_OK);
    return { ok: true, line: `${homeDir}（尚未创建，上级目录可写，启动时会创建）` };
  } catch {
    return { ok: false, line: `${homeDir}（尚未创建，且上级目录 ${parent} 不可写）` };
  }
}

/** @param {{home: string}} options */
export function dataDirCheck(options) {
  return {
    id: 'dataDir',
    label: '数据目录',
    level: 'block',
    run: () => {
      const result = inspectDataDir(options.home);
      if (result.ok) {
        return { ok: true, detail: result.line };
      }
      return {
        ok: false,
        detail: result.line,
        remedy: [
          `确认当前用户对 ${options.home} 或它的上级目录有写权限`,
          '不要用 sudo 运行本程序：那会让数据目录归 root，之后普通用户反而用不了',
        ],
        impact: '会话、模块清单与数据库都落在这个目录，起服务时必然写盘失败',
      };
    },
  };
}

/**
 * 配置文件。
 *
 * `config.error` 由 `loadConfigFile` 在解析失败时填入——解析错误不能让
 * `main()` 在检查报告之前抛出去，否则用户只看到一句"启动失败"，看不到
 * 同一次运行里其他检查的结论。
 *
 * @param {{config: {disabled: boolean, exists: boolean, filePath: string,
 *   entryCount: number, applied: string[], error?: Error|null}}} options
 */
export function configCheck(options) {
  const { config } = options;

  return {
    id: 'config',
    label: '配置文件',
    level: 'block',
    run: () => {
      if (config.disabled) {
        return { ok: true, detail: '（已用 --no-config 关闭）' };
      }

      if (config.error !== undefined && config.error !== null) {
        return {
          ok: false,
          detail: `${config.filePath} 解析失败：${config.error.message}`,
          remedy: [
            '按「KEY=VALUE」修正该文件（模板见 cosight.env.example）',
            '或先用 --no-config 跳过它，只使用环境变量',
          ],
          impact: '配置没有一条能生效，服务端会按默认值运行——通常不是用户想要的那套',
        };
      }

      if (config.exists) {
        return {
          ok: true,
          detail:
            `${config.filePath}（${config.entryCount} 条，生效 ${config.applied.length} 条，` +
            '其余被真实环境变量覆盖）',
        };
      }

      return { ok: true, detail: `${config.filePath}（不存在，将只用环境变量与默认值）` };
    },
  };
}

/**
 * 前端静态产物。
 *
 * `webDir === null` 是"只提供 API"的合法状态，不该显示成"目录不存在"。
 *
 * @param {{webDir: string|null}} options
 */
export function webDistCheck(options) {
  const { webDir } = options;

  return {
    id: 'webDist',
    label: '前端产物',
    level: 'block',
    run: () => {
      if (webDir === null) {
        return { ok: true, detail: '（未指定，仅提供 API）' };
      }
      if (fs.existsSync(webDir)) {
        return { ok: true, detail: webDir };
      }
      return {
        ok: false,
        detail: `${webDir} 不存在`,
        remedy: [
          '在仓库根执行 `pnpm build` 构建前端，再重新打包',
          '如果这是解压后的产物，说明包不完整，请重新获取发布包',
        ],
        impact: '服务端只能提供 API，浏览器打开首页会是 404',
      };
    },
  };
}

/** 从目标路径向上找到第一个真实存在的目录（数据目录可能还没建）。 */
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

/**
 * 磁盘空间：只提醒、不阻塞。
 *
 * 拿不到可用空间时也算通过——这条是"提前告知"，不是启动前提，
 * 不该因为某个文件系统不支持 statfs 就把用户挡在门外。
 *
 * @param {{home: string, minFreeBytes?: number}} options
 */
export function diskSpaceCheck(options) {
  const minFreeBytes = options.minFreeBytes ?? MIN_FREE_BYTES;

  return {
    id: 'disk',
    label: '磁盘空间',
    level: 'warn',
    run: () => {
      if (typeof fs.statfsSync !== 'function') {
        return { ok: true, detail: '（当前 Node 不支持 statfs，跳过）' };
      }

      let stats;
      try {
        stats = fs.statfsSync(nearestExisting(options.home));
      } catch (error) {
        return { ok: true, detail: `（无法读取可用空间：${error.message}）` };
      }

      const freeBytes = Number(stats.bsize) * Number(stats.bavail);
      const detail = `可用 ${humanSize(freeBytes)}（建议预留 ${humanSize(minFreeBytes)} 以上）`;

      return freeBytes >= minFreeBytes
        ? { ok: true, detail }
        : {
            ok: false,
            detail,
            remedy: ['清理该分区，或把数据目录（--home）放到空间更充裕的位置'],
            impact: '模块首次启动要建数据库；空间不足时会在运行中写失败',
          };
    },
  };
}
