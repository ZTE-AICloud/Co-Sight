/**
 * 模块清单契约（C2 嵌入机制；D24 = A 跨源要求）。
 *
 * 一个模块 = 一个可以独立开发、独立部署的前端，通过 iframe 挂进框架。
 * 模块在仓库里放一份 `module.json`（逐个字段对应本 schema），框架扫描后才知道
 * 该把哪个 capability 挂到哪条路由、允许从哪个源加载。
 *
 * D24 = A 的两条硬约束由 `validateModuleManifest` 强制：
 *  1. 模块必须跑在与宿主**不同**的源上，否则 `sandbox` 等同形同虚设；
 *  2. 实际加载的 entry 源必须在 `allowedOrigins` 白名单内。
 */

import { z } from 'zod';

import { SUPPORTED_LOCALES, type Locale } from '../locale';
import { httpUrlSchema } from './primitives';

/** 框架已知的插槽能力；导航项与卡片跳转都按这个枚举寻址。 */
export const MODULE_CAPABILITIES = [
  'conversation',
  'history',
  'experts',
  'agent-dev',
  'agent-eval',
  'knowledge',
  'observability',
] as const;

export type ModuleCapability = (typeof MODULE_CAPABILITIES)[number];

export const MODULE_MANIFEST_SCHEMA_VERSION = 1;

const localizedTextShape = Object.fromEntries(
  SUPPORTED_LOCALES.map((locale) => [locale, z.string().min(1)]),
) as Record<Locale, z.ZodString>;

export const localizedTextSchema = z.object(localizedTextShape);

/**
 * 模块内页面路径：同一个模块前端往往有多个页面（smart-factory 的"/"与"/agents"），
 * 而 `entry` 只能指向其中一个。声明了它，宿主就把 iframe 落到 `entry` 的这个路径上。
 *
 * 只接受**同源绝对路径**：
 * - 必须以单个 `/` 开头——`//evil.example` 在 URL 解析里是协议相对地址，会把 iframe
 *   指到白名单之外的源，正是 D24 要挡的事；
 * - 不许反斜杠与空白——`/\evil.example` 在部分解析器里会被折成 `//evil.example`，
 *   而带空白的路径只会变成一个永远打不开的地址。
 */
const moduleEntryPathSchema = z
  .string()
  .regex(/^\/(?!\/)[^\s\\]*$/, '模块内路径必须以单个 / 开头，且不含空白或反斜杠');

export const moduleMountSchema = z.object({
  capability: z.enum(MODULE_CAPABILITIES),
  /** 宿主侧路由前缀，必须以 `/` 开头。 */
  path: z.string().regex(/^\//, '宿主路由必须以 / 开头'),
  /** 该能力在模块前端里的页面路径（可选，缺省 = 直接用 `entry`）。 */
  entryPath: moduleEntryPathSchema.optional(),
});

export type ModuleMount = z.infer<typeof moduleMountSchema>;

export const moduleManifestSchema = z.object({
  schemaVersion: z.literal(MODULE_MANIFEST_SCHEMA_VERSION),
  /** 稳定标识；同时是 URL 上的模块名。 */
  id: z.string().regex(/^[a-z][a-z0-9-]{1,62}$/, '只允许小写字母、数字与连字符'),
  name: localizedTextSchema,
  description: localizedTextSchema,
  version: z.string().regex(/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/),
  /** 模块前端入口，绝对 URL。 */
  entry: httpUrlSchema,
  /** 允许作为 iframe src 的源白名单，至少一项。 */
  allowedOrigins: z.array(httpUrlSchema).min(1),
  mounts: z.array(moduleMountSchema).min(1),
  icon: z.string().nullable().default(null),
  healthcheck: httpUrlSchema.nullable().default(null),
});

export type ModuleManifest = z.infer<typeof moduleManifestSchema>;

export function originOf(url: string): string {
  return new URL(url).origin;
}

export interface ManifestIssue {
  path: string;
  code: string;
  message: string;
}

/**
 * 校验清单的自洽性与 D24 = A 的跨源要求。
 * `hostOrigin` 由框架在启动时给出（当前页面源）。
 * 返回空数组表示通过。
 */
export function validateModuleManifest(
  manifest: ModuleManifest,
  hostOrigin: string,
): ManifestIssue[] {
  const issues: ManifestIssue[] = [];
  const allowed = manifest.allowedOrigins.map(originOf);
  const entryOrigin = originOf(manifest.entry);

  if (!allowed.includes(entryOrigin)) {
    issues.push({
      path: 'entry',
      code: 'origin_not_allowed',
      message: `entry 的源 ${entryOrigin} 不在 allowedOrigins 内`,
    });
  }

  if (entryOrigin === hostOrigin) {
    issues.push({
      path: 'entry',
      code: 'same_origin_as_host',
      message:
        `模块与宿主同源（${hostOrigin}）。D24 要求模块独立部署，` +
        '同源会使 iframe sandbox 失去隔离意义。',
    });
  }

  const seenOrigins = new Set<string>();
  manifest.allowedOrigins.forEach((raw, index) => {
    let normalized: string;
    try {
      normalized = originOf(raw);
    } catch {
      issues.push({
        path: `allowedOrigins.${index}`,
        code: 'invalid_url',
        message: `${raw} 不是合法 URL`,
      });
      return;
    }
    // 白名单项必须"就是源"——带路径的项会让允许范围变得难以推理。
    if (normalized !== raw.replace(/\/$/, '')) {
      issues.push({
        path: `allowedOrigins.${index}`,
        code: 'not_a_bare_origin',
        message: `${raw} 应写成纯源（如 ${normalized}），不要带路径或查询串`,
      });
    }
    if (seenOrigins.has(normalized)) {
      issues.push({
        path: `allowedOrigins.${index}`,
        code: 'duplicate',
        message: `${normalized} 重复声明`,
      });
    }
    seenOrigins.add(normalized);
  });

  const seenCapabilities = new Set<ModuleCapability>();
  manifest.mounts.forEach((mount, index) => {
    if (seenCapabilities.has(mount.capability)) {
      issues.push({
        path: `mounts.${index}.capability`,
        code: 'duplicate',
        message: `${mount.capability} 被重复挂载`,
      });
    }
    seenCapabilities.add(mount.capability);
  });

  return issues;
}

/** 同 capability 有多个模块声明时，取 version 更高者，version 相同则按 id 字典序。 */
export function pickModuleForCapability(
  manifests: readonly ModuleManifest[],
  capability: ModuleCapability,
): ModuleManifest | null {
  const candidates = manifests.filter((manifest) =>
    manifest.mounts.some((mount) => mount.capability === capability),
  );
  if (candidates.length === 0) {
    return null;
  }
  const [best] = candidates.toSorted((a, b) => {
    const byVersion = compareSemver(b.version, a.version);
    return byVersion !== 0 ? byVersion : a.id.localeCompare(b.id);
  });
  return best ?? null;
}

/** 只比较 major.minor.patch，忽略 prerelease/build 后缀。 */
function parseSemver(value: string): number[] {
  const [core = '0'] = value.split(/[-+]/, 1);
  return core.split('.').map((part) => Number.parseInt(part, 10) || 0);
}

function compareSemver(left: string, right: string): number {
  const a = parseSemver(left);
  const b = parseSemver(right);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}
