/**
 * Agent 代理表单的草稿、校验与请求体映射（纯逻辑，不碰 React 也不碰 i18n）。
 *
 * 与 `models/modelForm.ts` 分成两份而不是合成一个"通用配置表单"：两份的
 * **空值语义**不同——模型的数字栏留空有"不限制"（`null`）这一档，代理的三个额度
 * 栏留空只能表示"用默认值"。把它们塞进一个泛型组件，就得在每个字段上再挂一个
 * "空的时候表示什么"的开关，读起来比两份各自直白更难。
 *
 * 契约（`framework/shared/src/contracts/agent-proxy.ts`）是这里唯一的真相。
 */

import type {
  AgentProxyConfig,
  SecurityAnalyzer,
  UpdateAgentProxyInput,
} from 'harness-shared';

import type { FieldIssue } from '../config/issues';
import { parseHttpUrl, parsePositiveInteger } from '../config/parse';
import { EMPTY_SECRET, resolveSecret, type SecretDraft } from '../config/secret';

/** 契约里的上限。 */
const MAX_ITERATIONS_MAX = 1000;
const PARALLELISM_MAX = 64;
const TIMEOUT_MAX_SECONDS = 86400;

/** 契约里的长度上限。 */
const MAX_NAME_LENGTH = 64;
const MAX_DESCRIPTION_LENGTH = 500;
const MAX_AGENT_TYPE_LENGTH = 64;
/** 令牌长度上限（`token` 与模型的 `apiKey` 同为 2048）。 */
const MAX_SECRET_LENGTH = 2048;

/**
 * 表单里的数字字段一律是 **string**（理由见 `TextField` 的注释与 `ModelDraft`）。
 *
 * 代理这边三个额度栏在契约里都**不可为空**，所以空串的含义只有一种："用默认值"。
 * 即便如此也不能存成 number：用户把「并行度」清空时，那就是一次没有合法数字可
 * 表示的中间状态，存成 0 会在提交前就替用户填上一个必然被服务端驳回的值。
 */
export interface AgentProxyDraft {
  name: string;
  description: string;
  agentType: string;
  endpoint: string;
  token: SecretDraft;
  maxIterations: string;
  parallelism: string;
  timeoutSeconds: string;
  enabled: boolean;
  isDefault: boolean;
  memoryEnabled: boolean;
  condensationEnabled: boolean;
  securityAnalyzer: SecurityAnalyzer;
}

/**
 * 能出错的字段名。
 *
 * 开关与安全分析器不在这里：它们只能取有限几个值，界面上根本敲不出非法输入
 * （`<select>` 与 `role="switch"`），为它们各留一条"不可能发生"的错误分支，
 * 只会让真正的分支看起来也是可选的。
 */
export type AgentProxyField =
  | 'name'
  | 'description'
  | 'agentType'
  | 'endpoint'
  | 'token'
  | 'maxIterations'
  | 'parallelism'
  | 'timeoutSeconds';

/**
 * 编辑时的初值。
 *
 * 只有这一种初值：代理配置由接口写入，界面上没有"新增"形态（见
 * `AgentProxySettingsPanel` 的文件头），所以这里不需要一份"空白草稿"。
 *
 * 令牌恒为空串（D26：明文读不到），"已配置"由旁边的提示语表达；`extra` 不进草稿，
 * 因为它在这个表单里是只读的（见 `AgentProxyConfigForm` 的 `ExtraReadonly`）。
 */
export function draftFromAgentProxy(proxy: AgentProxyConfig): AgentProxyDraft {
  return {
    name: proxy.name,
    description: proxy.description ?? '',
    agentType: proxy.agentType,
    endpoint: proxy.endpoint ?? '',
    token: EMPTY_SECRET,
    maxIterations: String(proxy.maxIterations),
    parallelism: String(proxy.parallelism),
    timeoutSeconds: String(proxy.timeoutSeconds),
    enabled: proxy.enabled,
    isDefault: proxy.isDefault,
    memoryEnabled: proxy.memoryEnabled,
    condensationEnabled: proxy.condensationEnabled,
    securityAnalyzer: proxy.securityAnalyzer,
  };
}

/** 数字栏的范围，供输入框的 `min`/`max` 与校验共用一份。 */
export const AGENT_PROXY_NUMBER_LIMITS = {
  maxIterations: { min: 1, max: MAX_ITERATIONS_MAX },
  parallelism: { min: 1, max: PARALLELISM_MAX },
  timeoutSeconds: { min: 1, max: TIMEOUT_MAX_SECONDS },
};

/**
 * 提交前校验。只登记**出错**的字段，返回空对象表示可以提交。
 *
 * `description` 只校验上限、不校验是否为空：它是可空的（`null` = 没有描述）。
 */
export function validateAgentProxyDraft(
  draft: AgentProxyDraft,
): Partial<Record<AgentProxyField, FieldIssue>> {
  const issues: Partial<Record<AgentProxyField, FieldIssue>> = {};

  const name = draft.name.trim();
  if (name === '') {
    issues.name = { kind: 'required' };
  } else if (name.length > MAX_NAME_LENGTH) {
    issues.name = { kind: 'tooLong', max: MAX_NAME_LENGTH };
  }

  if (draft.description.trim().length > MAX_DESCRIPTION_LENGTH) {
    issues.description = { kind: 'tooLong', max: MAX_DESCRIPTION_LENGTH };
  }

  const agentType = draft.agentType.trim();
  if (agentType === '') {
    issues.agentType = { kind: 'required' };
  } else if (agentType.length > MAX_AGENT_TYPE_LENGTH) {
    issues.agentType = { kind: 'tooLong', max: MAX_AGENT_TYPE_LENGTH };
  }

  if (draft.endpoint.trim() !== '') {
    const endpoint = parseHttpUrl(draft.endpoint);
    if (endpoint.issue !== null) {
      issues.endpoint = endpoint.issue;
    }
  }

  if (draft.token.value.length > MAX_SECRET_LENGTH) {
    issues.token = { kind: 'tooLong', max: MAX_SECRET_LENGTH };
  }

  // 三个额度栏用同一张表处理（同 `validateModelDraft`）：漏掉其中一个的话，
  // 界面上会显示一个服务端根本不接受的数字，而错误要等 422 才出现。
  const numbers: [AgentProxyField, FieldIssue | null][] = [
    [
      'maxIterations',
      parsePositiveInteger(draft.maxIterations, MAX_ITERATIONS_MAX).issue,
    ],
    ['parallelism', parsePositiveInteger(draft.parallelism, PARALLELISM_MAX).issue],
    [
      'timeoutSeconds',
      parsePositiveInteger(draft.timeoutSeconds, TIMEOUT_MAX_SECONDS).issue,
    ],
  ];

  for (const [field, issue] of numbers) {
    if (issue !== null) {
      issues[field] = issue;
    }
  }

  return issues;
}

interface ParsedAgentProxyDraft {
  name: string;
  description: string | null;
  agentType: string;
  endpoint: string | null;
  maxIterations: number | undefined;
  parallelism: number | undefined;
  timeoutSeconds: number | undefined;
}

/**
 * 草稿 → 值。调用前必须已经过 `validateAgentProxyDraft`。
 *
 * 字符串字段同样 trim，与服务端 schema 的 `.trim()` 对齐。
 */
function parseAgentProxyDraft(draft: AgentProxyDraft): ParsedAgentProxyDraft {
  const description = draft.description.trim();
  return {
    name: draft.name.trim(),
    // 空描述写 `null` 而不是空串：契约里 `description` 是 `nullable`，
    // 空串会被服务端原样存下来，列表里就会出现一条"有描述但看不见"的配置。
    description: description === '' ? null : description,
    agentType: draft.agentType.trim(),
    endpoint: parseHttpUrl(draft.endpoint).value,
    maxIterations: parsePositiveInteger(draft.maxIterations, MAX_ITERATIONS_MAX).value,
    parallelism: parsePositiveInteger(draft.parallelism, PARALLELISM_MAX).value,
    timeoutSeconds: parsePositiveInteger(draft.timeoutSeconds, TIMEOUT_MAX_SECONDS).value,
  };
}

/**
 * 编辑的请求体（`PATCH`，只送要改的字段）。
 *
 * 两处刻意省略的键，省略本身就是语义：
 *
 * - `extra` **整个不送**。它在界面上只读，而 `PATCH` 里 `undefined` 才是"别动它"——
 *   送一个 `{}` 会把模块自己写进去的键全部抹掉，且不可恢复。
 * - `token` 为 `undefined` 时这个键会从序列化结果里消失，服务端据此保持原令牌
 *   （D26 三态里的第一态）。
 *
 * 额度栏留空同样是"不送这个键"而不是送默认值：用户把「并行度」清空后按下保存，
 * 最合理的解读是"别动它"，而不是"改回 4"。
 */
export function agentProxyUpdatePayload(draft: AgentProxyDraft): UpdateAgentProxyInput {
  const parsed = parseAgentProxyDraft(draft);
  const token = resolveSecret(draft.token, 'edit');

  return {
    name: parsed.name,
    description: parsed.description,
    agentType: parsed.agentType,
    endpoint: parsed.endpoint,
    enabled: draft.enabled,
    isDefault: draft.isDefault,
    memoryEnabled: draft.memoryEnabled,
    condensationEnabled: draft.condensationEnabled,
    securityAnalyzer: draft.securityAnalyzer,
    ...(parsed.maxIterations === undefined ? {} : { maxIterations: parsed.maxIterations }),
    ...(parsed.parallelism === undefined ? {} : { parallelism: parsed.parallelism }),
    ...(parsed.timeoutSeconds === undefined ? {} : { timeoutSeconds: parsed.timeoutSeconds }),
    ...(token === undefined ? {} : { token }),
  };
}
