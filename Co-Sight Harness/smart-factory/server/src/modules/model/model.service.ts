import { config } from '../../config/index.js';
import { AppError, BadRequestError } from '../../shared/errors.js';
import { describeFrameworkNetworkError } from '../../shared/framework/client.js';
import { moduleTokenPath, readModuleToken } from '../../shared/framework/module-token.js';

/**
 * 框架模块面（Cosight）模型配置的唯一读取入口。
 *
 * 文档：`Cosight-Harness-开源/model-config-api.md`（基址、令牌、四道门、信封、字段表）。
 *
 * 三条刻意的取舍：
 *
 * 1. **对外只代理 `GET /models`（列表），不代理 `/active` 与 `/{id}`。** 后两个返回**明文密钥**，
 *    而列表响应最终会进浏览器；详情只由服务端在起 run 时读取，密钥经引擎上下文下发，永不进响应。
 * 2. **令牌每次现读文件，不缓存、不进环境变量。** 框架每个请求都重读该文件，换令牌立即生效；
 *    读文件也让令牌只存在于本进程内存里（不会被子进程继承）。
 * 3. **失败一律翻译成 502 + 人话。** 框架没起、令牌缺失、被四道门挡住都是「上游不可用」，
 *    不是本服务的 500；前端要把 message 直接显示给用户，所以中文要说清楚该查什么。
 */

/** 协议类型：框架直接给，**不从 provider 硬推**（model-config-api.md §6）。 */
export const MODEL_PROTOCOLS = ['anthropic', 'openai'] as const;
export type ModelProtocol = (typeof MODEL_PROTOCOLS)[number];

/**
 * 返回给前端的一条模型。
 *
 * 字段是框架列表响应的子集 + 改了两处命名：
 * - `label` 就是界面展示名（框架叫 `label`，旧前端叫 `displayName`）；
 * - 不带 `apiKey` / 掩码字段 —— 列表本来就没有，这里也不自己造。
 */
export interface ModelSummary {
  id: string;
  provider: string;
  protocol: ModelProtocol;
  /** 界面上显示的名称 */
  label: string;
  /** 发给供应商的 model 字段，不是显示名 */
  modelName: string;
  /** null = 用该供应商的官方地址，框架不做默认值推导 */
  baseUrl: string | null;
  hasApiKey: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ModelListResult {
  items: ModelSummary[];
  /** 当前生效模型；没有生效模型时为 null */
  activeId: string | null;
}

/** 起 run 时下发给引擎的运行配置：只含引擎用得上的三项，密钥不离开服务端进程。 */
export interface ModelRuntimeConfig {
  modelName: string;
  baseUrl: string | null;
  apiKey: string;
}

/** 起 run 时解析出的模型；会话必须有明确模型，不存在空模型回落。 */
export interface ResolvedRunModel {
  modelId: string;
  config: ModelRuntimeConfig;
}

/** 框架响应统一信封：`{ success, data, error, meta }`。 */
interface Envelope<T> {
  success?: boolean;
  data?: T;
  error?: { code?: string; message?: string } | null;
}

/** 框架列表里的一条：只声明本模块读的字段，其余原样忽略。 */
interface FrameworkModel {
  id?: unknown;
  provider?: unknown;
  protocol?: unknown;
  label?: unknown;
  modelName?: unknown;
  baseUrl?: unknown;
  hasApiKey?: unknown;
  isActive?: unknown;
  createdAt?: unknown;
  updatedAt?: unknown;
  /** 只有详情端点返回明文密钥；列表端点没有该字段。 */
  apiKey?: unknown;
}

interface FrameworkModelList {
  items?: unknown;
  activeId?: unknown;
}

/** 模块面在框架基址下的固定前缀（`MODULE_FACE_BASE_PATH`）。 */
const MODULE_FACE_PATH = '/api/framework/v1';
const MODELS_PATH = '/models';

function modelsUrl(): string {
  return `${config.frameworkBaseUrl.replace(/\/+$/, '')}${MODULE_FACE_PATH}${MODELS_PATH}`;
}

function upstreamError(message: string): AppError {
  return new AppError(502, 'FRAMEWORK_UNAVAILABLE', message);
}

/** 共享模块抛的是 BAD_GATEWAY；本模块的对外口径统一为 FRAMEWORK_UNAVAILABLE。 */
function frameworkToken(): string {
  try {
    return readModuleToken();
  } catch (error) {
    throw upstreamError(error instanceof Error ? error.message : '读取模块令牌失败');
  }
}

/** 只读消费方：不碰写接口，也不把令牌写进日志或响应。 */
export async function listModels(): Promise<ModelListResult> {
  const token = frameworkToken();
  const url = modelsUrl();

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(config.frameworkTimeoutMs),
    });
  } catch (error) {
    throw upstreamError(`请求框架模型列表失败（${url}）：${describeFrameworkNetworkError(error, config.frameworkTimeoutMs)}`);
  }

  // 401 的四种原因（没带 / 方案不对 / 令牌不对 / 文件缺失）框架刻意返回同一句话，
  // 这里也不猜，只把「查哪个文件」告诉用户。
  if (response.status === 401) {
    throw upstreamError(`框架拒绝了模块令牌（HTTP 401）：检查 ${moduleTokenPath()}`);
  }
  if (response.status === 403) {
    throw upstreamError('框架拒绝了请求（HTTP 403）：本服务只应通过 127.0.0.1 访问框架，且不能带 Origin 头');
  }
  if (!response.ok) {
    throw upstreamError(`框架返回 HTTP ${response.status}（${url}）`);
  }

  let body: Envelope<FrameworkModelList>;
  try {
    body = (await response.json()) as Envelope<FrameworkModelList>;
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw upstreamError(`框架模型列表不是合法 JSON：${reason}`);
  }

  if (body.success !== true) {
    const detail = body.error?.message ?? body.error?.code ?? 'UNKNOWN';
    throw upstreamError(`框架返回失败：${detail}`);
  }

  const data = body.data;
  if (data === null || typeof data !== 'object' || !Array.isArray(data.items)) {
    throw upstreamError('框架模型列表响应缺少 data.items');
  }

  const items = data.items.map(toSummary);
  const activeId = typeof data.activeId === 'string' && data.activeId !== '' ? data.activeId : null;
  return { items, activeId };
}

/** 框架侧模型详情 404/422：这个 id 指向的模型已被删除或从未存在。 */
class ModelNotFoundError extends BadRequestError {
  constructor(modelId: string) {
    super('所选模型不存在或已删除，请重新选择模型', 'error.bad_request.model_not_found', { modelId });
  }
}

/**
 * 会话模型 → 起 run 用的模型配置。
 *
 * 会话必须显式绑定模型：没有模型、模型不存在、协议不符或没有密钥都直接报错，
 * 不再回落到工作区默认模型、框架 active 或本机配置。全程只读框架，不写回。
 *
 * 「会话里的模型被删掉了」与「刚选了一个不存在的模型」是两种场景，前者用户没做错任何事、
 * 只需要换一个模型，所以换成 `session_model_missing` 这个键，前端据此引导重选；
 * 模型 id 只留在 `params` 里备查，不进给人看的话。
 */
export async function resolveRunModel(modelId: string): Promise<ResolvedRunModel> {
  if (modelId === '') throw new BadRequestError('会话没有模型，请先选择模型', 'error.bad_request.session_no_model');
  try {
    return { modelId, config: await resolveModelConfig(modelId) };
  } catch (error) {
    if (error instanceof ModelNotFoundError) {
      throw new BadRequestError(
        '会话使用的模型已被删除，请重新选择模型',
        'error.bad_request.session_model_missing',
        { modelId },
      );
    }
    throw error;
  }
}

/**
 * 模型 id → 起 run 用的运行配置；空串是调用错误。
 *
 * 详情含明文密钥，只允许服务端调用：404 / 422 视为模型已不存在，
 * 其余非 2xx 与网络异常沿用本模块的 502 人话；错误里不拼响应体，也不回显密钥。
 */
export async function resolveModelConfig(modelId: string): Promise<ModelRuntimeConfig> {
  if (modelId === '') throw new BadRequestError('模型 id 不能为空', 'error.bad_request.required', { name: 'modelId' });

  const token = frameworkToken();
  const url = `${config.frameworkBaseUrl.replace(/\/+$/, '')}${MODULE_FACE_PATH}${MODELS_PATH}/${encodeURIComponent(modelId)}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(config.frameworkTimeoutMs),
    });
  } catch (error) {
    throw upstreamError(`请求框架模型详情失败（${url}）：${describeFrameworkNetworkError(error, config.frameworkTimeoutMs)}`);
  }

  if (response.status === 404 || response.status === 422) {
    throw new ModelNotFoundError(modelId);
  }
  if (response.status === 401) {
    throw upstreamError(`框架拒绝了模块令牌（HTTP 401）：检查 ${moduleTokenPath()}`);
  }
  if (response.status === 403) {
    throw upstreamError('框架拒绝了请求（HTTP 403）：本服务只应通过 127.0.0.1 访问框架，且不能带 Origin 头');
  }
  if (!response.ok) {
    throw upstreamError(`框架返回 HTTP ${response.status}（${url}）`);
  }

  let body: Envelope<FrameworkModel>;
  try {
    body = (await response.json()) as Envelope<FrameworkModel>;
  } catch {
    throw upstreamError('框架模型详情不是合法 JSON');
  }
  if (body.success !== true || body.data === null || typeof body.data !== 'object') {
    throw upstreamError('框架模型详情响应缺少 data');
  }

  const detail = body.data;
  /** 详情里能拿到展示名，就用它；拿不到才退回一句不含 id 的泛称。 */
  const label = stringOf(detail.label) || stringOf(detail.modelName) || '所选模型';
  if (detail.protocol !== 'anthropic') {
    const protocol = String(detail.protocol);
    throw new BadRequestError(
      `模型「${label}」的协议是 ${protocol}，当前引擎只支持 anthropic`,
      'error.bad_request.model_protocol',
      { label, modelId, protocol },
    );
  }

  const apiKey = typeof detail.apiKey === 'string' ? detail.apiKey : '';
  if (apiKey === '') {
    throw new BadRequestError(`模型「${label}」没有配置 API 密钥`, 'error.bad_request.model_no_key', { label, modelId });
  }

  const modelName = typeof detail.modelName === 'string' ? detail.modelName : '';
  if (modelName === '') {
    throw new BadRequestError(`模型「${label}」没有配置 modelName，无法下发引擎`, 'error.bad_request.model_no_name', { label, modelId });
  }

  return {
    modelName,
    baseUrl: typeof detail.baseUrl === 'string' && detail.baseUrl !== '' ? detail.baseUrl : null,
    apiKey,
  };
}

/**
 * 入参模型必须当前引擎跑得起来：非空、存在、anthropic 协议、已配密钥。
 *
 * 只读列表，不取详情（避免密钥进入调用方）；`field` 只用在「必填」这一条上，
 * 指明是哪个入参为空（`modelId` / `init.modelId`）。
 * 列表不可用时由 `listModels` 抛 502，与 `GET /models/list` 同一口径。
 *
 * 四条错误都带**具体**的 messageKey：只给默认的 `error.bad_request.default` 时，
 * 前端翻出来一律是「请求格式不正确」，协议不符 / 缺密钥这些能动手的原因全被吞掉。
 */
export async function assertModelRunnable(modelId: string, field = 'modelId'): Promise<void> {
  if (modelId === '') {
    throw new BadRequestError(`${field} 必填`, 'error.bad_request.required', { name: field });
  }

  const { items } = await listModels();
  const model = items.find((item) => item.id === modelId);
  if (!model) {
    throw new BadRequestError('所选模型不存在或已删除，请重新选择模型', 'error.bad_request.model_not_found', { modelId });
  }
  /** 文案用展示名，模型 id 只留 `params` 备查：uuid 对用户没有意义。 */
  const label = model.label || '所选模型';
  if (model.protocol !== 'anthropic') {
    throw new BadRequestError(
      `模型「${label}」的协议是 ${model.protocol}，当前引擎只支持 anthropic`,
      'error.bad_request.model_protocol',
      { modelId, label, protocol: model.protocol },
    );
  }
  if (model.hasApiKey !== true) {
    throw new BadRequestError(`模型「${label}」没有配置 API 密钥`, 'error.bad_request.model_no_key', { modelId, label });
  }
}

/**
 * 框架记录 → 前端记录。字段缺失按「空值」兜，**协议不合法则整条跳过**：
 * 协议决定用哪套 SDK，猜错会把 OpenAI 兼容端点拿 Anthropic SDK 去打（§6），
 * 与其给一个会静默出错的选项，不如让这条模型不出现在下拉里。
 */
function toSummary(raw: unknown): ModelSummary {
  const record = (raw ?? {}) as FrameworkModel;
  const protocol = record.protocol;
  if (!isProtocol(protocol)) {
    throw upstreamError(`框架返回了无法识别的协议：${String(protocol)}`);
  }

  return {
    id: stringOf(record.id),
    provider: stringOf(record.provider),
    protocol,
    label: stringOf(record.label) || stringOf(record.modelName),
    modelName: stringOf(record.modelName),
    baseUrl: typeof record.baseUrl === 'string' && record.baseUrl !== '' ? record.baseUrl : null,
    hasApiKey: record.hasApiKey === true,
    isActive: record.isActive === true,
    createdAt: stringOf(record.createdAt),
    updatedAt: stringOf(record.updatedAt),
  };
}

function stringOf(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function isProtocol(value: unknown): value is ModelProtocol {
  return (MODEL_PROTOCOLS as readonly unknown[]).includes(value);
}

export const modelService = { listModels };
