/**
 * 模块注册表（C2 嵌入机制）。
 *
 * 扫描 `$COSIGHT_HOME/modules/<id>/module.json`，逐个用 `moduleManifestSchema` 解析，
 * 再用 `validateModuleManifest` 校验跨源约束（D24 = A）。**坏清单不会阻断启动**：
 * 它被收集进 `invalid` 一并返回，由前端提示"某模块清单不合法"。
 * 启动直接崩会把"某个可选模块写错了"升级为"整个平台起不来"，不成比例。
 *
 * v1 仓库里还没有任何模块（colleagues 的 task-center / smart-factory-ui 尚未接入），
 * 因此正常情况下这里返回空列表——这是预期状态，不是错误。
 */

import fs from 'node:fs';
import path from 'node:path';

import { moduleManifestSchema, validateModuleManifest } from 'harness-shared';
import type { ManifestIssue, ModuleManifest } from 'harness-shared';

import { isLoopbackHost } from '../http/loopback';
import { stripBom } from '../lib/text';

export interface InvalidModule {
  /** 清单文件路径，便于用户直接去改。 */
  file: string;
  issues: ManifestIssue[];
}

export interface ModuleScanResult {
  modules: ModuleManifest[];
  invalid: InvalidModule[];
}

function listManifestFiles(modulesDir: string): string[] {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(modulesDir, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return [];
    }
    throw error;
  }

  return entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(modulesDir, entry.name, 'module.json'))
    .filter((file) => fs.existsSync(file))
    .toSorted();
}

export function scanModules(modulesDir: string, hostOrigin: string): ModuleScanResult {
  const modules: ModuleManifest[] = [];
  const invalid: InvalidModule[] = [];

  for (const file of listManifestFiles(modulesDir)) {
    let parsed: unknown;
    try {
      // stripBom：Windows 记事本存出来的 module.json 带 BOM，JSON.parse 会直接抛，
      // 表现成"模块静默没注册"（见 lib/text.ts）。
      parsed = JSON.parse(stripBom(fs.readFileSync(file, 'utf8')));
    } catch (error) {
      invalid.push({
        file,
        issues: [
          {
            path: file,
            code: 'invalid_json',
            message: error instanceof Error ? error.message : '无法解析 JSON',
          },
        ],
      });
      continue;
    }

    const result = moduleManifestSchema.safeParse(parsed);
    if (!result.success) {
      invalid.push({
        file,
        issues: result.error.issues.map((issue) => ({
          path: issue.path.join('.'),
          code: issue.code,
          message: issue.message,
        })),
      });
      continue;
    }

    const issues = validateModuleManifest(result.data, hostOrigin);
    if (issues.length > 0) {
      invalid.push({ file, issues });
      continue;
    }

    modules.push(result.data);
  }

  return { modules, invalid };
}

/** IPv6 字面量在 URL 里必须带方括号；`hostnameFromHostHeader` 交出来的是裸地址。 */
function urlHostname(hostname: string): string {
  return hostname.includes(':') ? `[${hostname}]` : hostname;
}

/**
 * 把单个 URL 的回环主机名换成 `hostname`；不是回环就原样返回。
 *
 * 解析失败也原样返回：清单在扫描阶段已经过 schema 校验，这里不该成为新的失败点。
 */
function rebaseUrl(rawUrl: string, hostname: string): string {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return rawUrl;
  }
  if (!isLoopbackHost(url.hostname)) {
    return rawUrl;
  }
  url.hostname = urlHostname(hostname);
  return url.toString();
}

/** 与 `rebaseUrl` 相同，但输出纯源（不带尾斜杠），用于 `allowedOrigins`。 */
function rebaseOrigin(rawUrl: string, hostname: string): string {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return rawUrl;
  }
  if (!isLoopbackHost(url.hostname)) {
    return rawUrl;
  }
  url.hostname = urlHostname(hostname);
  return url.origin;
}

/**
 * 把清单里指向回环的地址换成**请求方访问宿主时用的主机名**。
 *
 * 为什么需要：清单只有一份静态文件，而打开页面的人可能在本机，也可能在同网段
 * 另一台机器上。`entry: http://localhost:4110/` 在本机上是对的；别人的浏览器
 * 解析 `localhost` 得到的是**他自己**的机器，于是 iframe 表现为「localhost 拒绝
 * 了我们的连接请求」。
 *
 * 三条边界：
 * 1. **只在请求主机名不是回环时改写。** 本机访问保持原样——`localhost` 与
 *    `127.0.0.1` 在浏览器里是不同的源，改写会让模块的 localStorage/cookie 换一份。
 * 2. **只改写回环地址。** 模块本来就部署在别的机器上（如 `http://192.168.1.9:5174`）
 *    时不动它。
 * 3. **落盘文件不动。** 这只是一次响应投影；`module.json` 仍是模块作者写的值，
 *    扫描与契约校验也都按原值进行（D24 的同源拒绝不会被这次改写绕过）。
 */
export function rebaseLoopbackManifests(
  result: ModuleScanResult,
  hostname: string,
): ModuleScanResult {
  return {
    ...result,
    modules: result.modules.map((manifest) => ({
      ...manifest,
      entry: rebaseUrl(manifest.entry, hostname),
      allowedOrigins: manifest.allowedOrigins.map((origin) => rebaseOrigin(origin, hostname)),
      ...(typeof manifest.healthcheck === 'string'
        ? { healthcheck: rebaseUrl(manifest.healthcheck, hostname) }
        : {}),
    })),
  };
}
