import { join } from 'node:path';
import { BadRequestError } from '../errors.js';
import type { InstanceStage } from '../types/index.js';

/**
 * 单段目录名：全小写字母或数字开头、总长 1–64，已排除空串、路径分隔、`..`、隐藏目录与绝对路径。
 *
 * 只放行小写：大小写不敏感的 Windows 上 `Demo` 与 `demo` 会指向同一目录，收紧后跨平台行为一致。
 */
const AGENT_ID_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/;

/** Windows 保留设备名（带扩展名的变体如 `con.txt` 同样不可用）；前缀命中如 `console`、`com10` 不在列。 */
const WINDOWS_RESERVED_PATTERN = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/;

/** 形态判定的非抛出版本：启动收养拿它筛目录名（不匹配的目录名不该被收成智能体）。 */
export function isAgentId(value: unknown): value is string {
  return typeof value === 'string' && AGENT_ID_PATTERN.test(value);
}

/** agentId 参与路径拼接，形态校验是唯一的安全边界。 */
export function assertAgentId(agentId: unknown): asserts agentId is string {
  if (!isAgentId(agentId)) {
    throw new BadRequestError(`agentId 形态非法：${JSON.stringify(agentId)}`);
  }
  if (WINDOWS_RESERVED_PATTERN.test(agentId)) {
    throw new BadRequestError(`agentId 不能是 Windows 保留名：${JSON.stringify(agentId)}`);
  }
  if (agentId.endsWith('.')) {
    throw new BadRequestError(`agentId 不能以点结尾：${JSON.stringify(agentId)}`);
  }
}

/**
 * 相对路径校验：产物浏览的唯一安全边界，与 assertAgentId 同级。
 *
 * 逐段拒绝空段、`.`、`..`、反斜杠与 NUL（点开头的普通文件如 `.gitignore` 放行）；
 * 调用方还要做一次 resolve 后的前缀检查（双保险）。
 */
export function assertRelativePath(path: unknown): asserts path is string {
  if (typeof path !== 'string' || path === '') {
    throw new BadRequestError('path 必填（stage 根内相对路径）');
  }
  const ok = path.split('/').every((segment) => {
    return segment.length > 0 && segment !== '.' && segment !== '..' && !segment.includes('\\') && !segment.includes('\u0000');
  });
  if (!ok) {
    throw new BadRequestError(`path 非法：${JSON.stringify(path)}`);
  }
}

/** 模块根在各工作区目录下的固定目录名。 */
const MODULE_DIR = '.smart-factory';

/** agentRoot = `<workspace.directory>/.smart-factory/agents/{agentId}`；只拼路径，不查存在性。 */
export function agentRoot(workspaceDir: string, agentId: string): string {
  assertAgentId(agentId);
  return join(workspaceDir, MODULE_DIR, 'agents', agentId);
}

const NON_RUNTIME_STAGES = new Set<InstanceStage>(['development', 'preview', 'evaluation']);

/**
 * development / preview / evaluation 的 cwd；目录名与 stage 逐字一致。
 *
 * runtime 的 cwd 落在开发产物的嵌套版本目录里，必须按产物定位，见 materialize.ts。
 * 运行时再校验一次枚举：stage 可能来自库里的旧行，不能让任意字符串参与路径拼接。
 */
export function stageDir(agentRootDir: string, stage: Exclude<InstanceStage, 'runtime'>): string {
  if (!NON_RUNTIME_STAGES.has(stage)) {
    throw new BadRequestError(`stage 取值非法：${JSON.stringify(stage)}`);
  }
  return join(agentRootDir, stage);
}

/** 物化标记目录：不属于任何 stage 根，产物浏览不可见。 */
export function stateDir(agentRootDir: string): string {
  return join(agentRootDir, '.state');
}
