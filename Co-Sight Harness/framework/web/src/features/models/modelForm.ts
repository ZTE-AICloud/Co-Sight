/**
 * 模型表单的草稿、校验与请求体映射（纯逻辑，不碰 React 也不碰 i18n）。
 *
 * 抽成独立模块的理由不只是"组件要短"：这三件事里任何一件出错，表现都是**静默**的——
 * 留空映射成空串会让服务端返回一句没有指向的 422；数字少校验一次会让界面上显示 5
 * 而存下来的是别的东西；编辑时多送一个 `apiKey` 会把用户没打算改的密钥覆盖掉。
 * 所以它们被写成可以直接单测的纯函数，而测试断言的正是"序列化之后的请求体长什么样"。
 *
 * 契约（`framework/shared/src/contracts/model.ts`）是这里唯一的真相：
 * 默认值、上下限、三态密钥都从那边的 `sharedFields` 抄过来，改动只发生在注释里指出的
 * 那几处。
 */

import type {
  CreateModelConfigInput,
  ModelConfig,
  ModelProviderKind,
  UpdateModelConfigInput,
} from 'harness-shared';

import type { FieldIssue } from '../config/issues';
import { parseDecimal, parseHttpUrl, parsePositiveInteger } from '../config/parse';
import { EMPTY_SECRET, resolveSecret, type SecretDraft } from '../config/secret';

/**
 * 表单允许选择与保存的供应商。
 *
 * 产品约束：模型设置当前**只支持 Anthropic**，其他供应商类型不提供。新增与修改
 * 共用这一份清单——两处各写一遍的话，漏改的那一处会表现为"编辑时还能选回旧类型"。
 */
export const EDITABLE_PROVIDER_KINDS = ['anthropic'] as const satisfies readonly ModelProviderKind[];

/**
 * 表单的默认供应商。
 *
 * `noUncheckedIndexedAccess` 下 `EDITABLE_PROVIDER_KINDS[0]` 的类型是"可能是 undefined"，
 * 所以写成字面量；`ModelProviderKind` 的标注保证它必须仍是契约枚举的一员。
 */
const DEFAULT_PROVIDER: ModelProviderKind = 'anthropic';

/** 供应商是否受支持。旧数据（历史上可能存过其他类型）用它决定要不要收敛。 */
export function isEditableProvider(provider: ModelProviderKind): boolean {
  return (EDITABLE_PROVIDER_KINDS as readonly ModelProviderKind[]).includes(provider);
}

/** 与契约 `sharedFields` 的 `.default(...)` 一一对应。 */
const DEFAULT_TEMPERATURE = 0.7;
const DEFAULT_TOP_P = 1;
const DEFAULT_TIMEOUT_SECONDS = 120;

/** 契约里的上下限，校验与文案里的数字都从这里来。 */
const TEMPERATURE_RANGE = { min: 0, max: 2 } as const;
const TOP_P_RANGE = { min: 0, max: 1 } as const;
const TIMEOUT_MAX_SECONDS = 3600;

/** 契约里的长度上限（`label` / `modelName` / 密钥）。 */
const MAX_LABEL_LENGTH = 64;
const MAX_MODEL_NAME_LENGTH = 128;
const MAX_SECRET_LENGTH = 2048;

/**
 * 表单里的数字字段一律是 **string**（见 `TextField` 的注释）。
 *
 * 这不是"顺手用字符串凑合"：用户清空输入框、或敲到一半（`1.`）时没有合法的数字可以
 * 表示，存成 number 就得在"空"和"0"之间撒谎。空串在这里是**有含义**的值——
 * 可空字段表示 `null`，非空字段表示"用契约默认值"。
 */
export interface ModelDraft {
  provider: ModelProviderKind;
  label: string;
  modelName: string;
  baseUrl: string;
  secret: SecretDraft;
  isActive: boolean;
  temperature: string;
  topP: string;
  maxOutputTokens: string;
  contextWindow: string;
  timeoutSeconds: string;
}

/**
 * 能出错的字段名。
 *
 * 与 `ModelDraft` 的键刻意不同名（`apiKey` 而不是 `secret`）：错误是挂在**界面上
 * 那一栏**的，而界面上那一栏叫 "API 密钥"，`secret` 是它内部的数据结构。
 */
export type ModelField =
  | 'label'
  | 'modelName'
  | 'baseUrl'
  | 'apiKey'
  | 'temperature'
  | 'topP'
  | 'maxOutputTokens'
  | 'contextWindow'
  | 'timeoutSeconds';

/**
 * 落在界面「推理参数」区里的字段。
 *
 * 这块区域**默认是折起来的**，而校验照样会往这五个字段上挂错误——于是就有了一个
 * 只有这份清单才知道的问题：错误挂在折起来的地方，用户看不见。表单拿它决定
 * "提交失败时要不要把区域撑开"，测试拿它决定"哪些字段的报错得先展开才看得到"。
 *
 * 放这里而不是表单组件里，是因为它与 `ModelField` 是同一层的事实（哪些字段属于哪一组），
 * 将来往这组里加字段时，两处用法都能看见这份清单——分散写的话，漏更新的表现是
 * "某个字段报错时用户点了保存毫无反应"，极难从现象反推。
 */
export const ADVANCED_MODEL_FIELDS = [
  'temperature',
  'topP',
  'maxOutputTokens',
  'contextWindow',
  'timeoutSeconds',
] as const satisfies readonly ModelField[];

/**
 * 新建时的初值：数字栏预填契约默认值，其余留空。
 *
 * `isActive` 默认 `false`：全局同时只有一条「当前使用」，已有生效模型时，新建的
 * 一条悄悄顶掉它不是新建的语义。例外是**当前一条生效模型都没有**（首次配置，
 * 或所有模型都被停用）——此时新建的这条就是平台唯一的候选，开关由表单预设为开
 * （`ModelConfigForm` 的 `defaultActive`），免得保存完平台仍然没有可用模型。
 * 判断留在调用方，这里只接受一个入参。
 */
export function emptyModelDraft(options: { isActive?: boolean } = {}): ModelDraft {
  return {
    provider: DEFAULT_PROVIDER,
    label: '',
    modelName: '',
    baseUrl: '',
    secret: EMPTY_SECRET,
    isActive: options.isActive ?? false,
    temperature: String(DEFAULT_TEMPERATURE),
    topP: String(DEFAULT_TOP_P),
    maxOutputTokens: '',
    contextWindow: '',
    timeoutSeconds: String(DEFAULT_TIMEOUT_SECONDS),
  };
}

/**
 * 编辑时的初值。
 *
 * 密钥恒为空串（D26：明文读不到）。这不是"忘了填"，而是这个字段在编辑态下的
 * 唯一正确初值——旁边那句提示负责告诉用户"已配置，留空表示不修改"。
 */
export function draftFromModel(model: ModelConfig): ModelDraft {
  return {
    /*
     * 不受支持的旧供应商收敛到 Anthropic：表单只提供这一个选项，原值留着会让
     * 之后的「保存」把不受支持的类型重新发给服务端。
     */
    provider: isEditableProvider(model.provider) ? model.provider : DEFAULT_PROVIDER,
    label: model.label,
    modelName: model.modelName,
    baseUrl: model.baseUrl ?? '',
    secret: EMPTY_SECRET,
    isActive: model.isActive,
    temperature: String(model.temperature),
    topP: String(model.topP),
    maxOutputTokens: model.maxOutputTokens === null ? '' : String(model.maxOutputTokens),
    contextWindow: model.contextWindow === null ? '' : String(model.contextWindow),
    timeoutSeconds: String(model.timeoutSeconds),
  };
}

/**
 * 数字栏的范围，供输入框的 `min`/`max` 属性与校验共用一份。
 *
 * 只放有上限的三个：`maxOutputTokens` / `contextWindow` 在契约里没有上限，
 * 给它们编一个会凭空拦住用户的合法输入。
 */
export const MODEL_NUMBER_LIMITS = {
  temperature: TEMPERATURE_RANGE,
  topP: TOP_P_RANGE,
  timeoutSeconds: { min: 1, max: TIMEOUT_MAX_SECONDS },
};

/**
 * 提交前校验。只登记**出错**的字段，返回空对象表示可以提交。
 *
 * 上下限与长度上限都在这里挡，而不是等服务端返回 422："请求参数校验未通过"既不
 * 指向字段也不指向原因，用户只能一个一个字段试。
 */
export function validateModelDraft(draft: ModelDraft): Partial<Record<ModelField, FieldIssue>> {
  const issues: Partial<Record<ModelField, FieldIssue>> = {};

  const label = draft.label.trim();
  if (label === '') {
    issues.label = { kind: 'required' };
  } else if (label.length > MAX_LABEL_LENGTH) {
    issues.label = { kind: 'tooLong', max: MAX_LABEL_LENGTH };
  }

  const modelName = draft.modelName.trim();
  if (modelName === '') {
    issues.modelName = { kind: 'required' };
  } else if (modelName.length > MAX_MODEL_NAME_LENGTH) {
    issues.modelName = { kind: 'tooLong', max: MAX_MODEL_NAME_LENGTH };
  }

  if (draft.baseUrl.trim() !== '') {
    const url = parseHttpUrl(draft.baseUrl);
    if (url.issue !== null) {
      issues.baseUrl = url.issue;
    }
  }

  if (draft.secret.value.length > MAX_SECRET_LENGTH) {
    issues.apiKey = { kind: 'tooLong', max: MAX_SECRET_LENGTH };
  }

  /*
   * 数字栏用同一段循环处理：五个字段的解析函数不一样，但"空着合法、填错要报在哪一栏"
   * 这件事是一样的。写成五段 if 的话，将来加一个字段就会漏掉其中一段。
   */
  const numbers: [ModelField, FieldIssue | null][] = [
    [
      'temperature',
      parseDecimal(draft.temperature, TEMPERATURE_RANGE.min, TEMPERATURE_RANGE.max).issue,
    ],
    ['topP', parseDecimal(draft.topP, TOP_P_RANGE.min, TOP_P_RANGE.max).issue],
    ['timeoutSeconds', parsePositiveInteger(draft.timeoutSeconds, TIMEOUT_MAX_SECONDS).issue],
    ['maxOutputTokens', parsePositiveInteger(draft.maxOutputTokens).issue],
    ['contextWindow', parsePositiveInteger(draft.contextWindow).issue],
  ];

  for (const [field, issue] of numbers) {
    if (issue !== null) {
      issues[field] = issue;
    }
  }

  return issues;
}

/** 解析好的值；`undefined` 只在"这一栏是空的"时出现。 */
export interface ParsedModelDraft {
  label: string;
  modelName: string;
  baseUrl: string | null;
  temperature: number | undefined;
  topP: number | undefined;
  maxOutputTokens: number | null;
  contextWindow: number | null;
  timeoutSeconds: number | undefined;
}

/**
 * 草稿 → 值。
 *
 * 调用前必须已经过 `validateModelDraft`：这里的 `undefined` 只表示"没填"。
 * 字符串字段一律 trim，与服务端 schema 的 `.trim()` 对齐——不然界面上看到的
 * （带尾部空格的）名字和存下来的会是两个不同的字符串。
 */
export function parseModelDraft(draft: ModelDraft): ParsedModelDraft {
  return {
    label: draft.label.trim(),
    modelName: draft.modelName.trim(),
    baseUrl: parseHttpUrl(draft.baseUrl).value,
    temperature: parseDecimal(draft.temperature, TEMPERATURE_RANGE.min, TEMPERATURE_RANGE.max).value,
    topP: parseDecimal(draft.topP, TOP_P_RANGE.min, TOP_P_RANGE.max).value,
    maxOutputTokens: parsePositiveInteger(draft.maxOutputTokens).value ?? null,
    contextWindow: parsePositiveInteger(draft.contextWindow).value ?? null,
    timeoutSeconds: parsePositiveInteger(draft.timeoutSeconds, TIMEOUT_MAX_SECONDS).value,
  };
}

/**
 * 新建的请求体。
 *
 * 契约里所有非可空字段在**类型上**都是必填的（`.default()` 让它们从可选变成必填），
 * 所以空白栏在这里落到契约默认值上，而不是被丢掉：丢掉的字段服务端同样会用默认值，
 * 但那样请求体里就出现"这个键有时候在、有时候不在"，读起来要多想一步。
 *
 * 密钥留空 → `null`（不设置）。**不是空串**：服务端是 `min(1)`，空串直接 422。
 */
export function modelCreatePayload(draft: ModelDraft): CreateModelConfigInput {
  const parsed = parseModelDraft(draft);
  return {
    provider: isEditableProvider(draft.provider) ? draft.provider : DEFAULT_PROVIDER,
    label: parsed.label,
    modelName: parsed.modelName,
    baseUrl: parsed.baseUrl,
    isActive: draft.isActive,
    temperature: parsed.temperature ?? DEFAULT_TEMPERATURE,
    topP: parsed.topP ?? DEFAULT_TOP_P,
    timeoutSeconds: parsed.timeoutSeconds ?? DEFAULT_TIMEOUT_SECONDS,
    maxOutputTokens: parsed.maxOutputTokens,
    contextWindow: parsed.contextWindow,
    apiKey: resolveSecret(draft.secret, 'create'),
  };
}

/**
 * 编辑的请求体（`PATCH`，只送要改的字段）。
 *
 * 空栏的两种含义在这里分岔，这是本文件最容易写错的一处：
 *
 * - **可空字段**（`baseUrl` / `maxOutputTokens` / `contextWindow`）空着就是 `null`，
 *   因为契约里 `null` 本身是一个有意义的值（"用官方地址"、"不限制"），用户删掉
 *   内容就是在表达它；
 * - **非可空字段**（温度、Top P、超时）空着就**整个键不送**，表示"保持原值"。
 *   它们没有 `null` 可表达，硬要送一个数字就等于替用户做主——而"用户清空了这一栏"
 *   最合理的解读是"别动它"，不是"改成 0"。
 *
 * `apiKey` 为 `undefined` 时这个键会从序列化结果里消失，服务端据此保持原密钥；
 * 这正是 D26 三态里的第一态，用例专门断言请求体里**没有**这个键。
 */
export function modelUpdatePayload(draft: ModelDraft): UpdateModelConfigInput {
  const parsed = parseModelDraft(draft);
  const apiKey = resolveSecret(draft.secret, 'edit');

  return {
    provider: isEditableProvider(draft.provider) ? draft.provider : DEFAULT_PROVIDER,
    label: parsed.label,
    modelName: parsed.modelName,
    baseUrl: parsed.baseUrl,
    isActive: draft.isActive,
    maxOutputTokens: parsed.maxOutputTokens,
    contextWindow: parsed.contextWindow,
    ...(parsed.temperature === undefined ? {} : { temperature: parsed.temperature }),
    ...(parsed.topP === undefined ? {} : { topP: parsed.topP }),
    ...(parsed.timeoutSeconds === undefined ? {} : { timeoutSeconds: parsed.timeoutSeconds }),
    ...(apiKey === undefined ? {} : { apiKey }),
  };
}
