/**
 * 模块面模型服务：把模型配置投影成"别的本机进程能直接用"的形状，**含明文密钥**。
 *
 * ## 为什么单独一个文件，而不是给 `ModelConfigRepository` 加个方法
 *
 * `repositories/model-config.repository.ts` 的核心价值是 `toModelConfig()` 那句
 * "Row 里根本没有明文字段可读"的**签名级**保证——浏览器面的"永不回传密钥"是靠
 * 这个结构性质守住的，不是靠路由自觉。往那个文件里塞一条返回明文的兄弟方法，
 * 后来人改浏览器面映射时就在同一个文件里，"顺手改错"的风险陡增。
 *
 * 所以两面的投影函数**物理分离**：浏览器面只有 `toModelConfig`，模块面只有这里的
 * `toModuleSummary` / `toModuleSecret`。没有共享的映射代码，也就没有一处改动能
 * 同时把两面弄坏。这是比注释更强的保证。
 *
 * ## 这里只需要既有能力
 *
 * 仓储的 `list/findById/findActive` 返回的 `ModelConfig` 已经带了 `hasApiKey`；
 * 引用键是确定性的 `model:<id>`（`secretRef('model', id)`），所以**不需要给仓储加
 * 任何方法，也不需要给 `SECRET_KINDS` 加值**。
 */

import type { CreateModelConfigInput, ModelConfig, UpdateModelConfigInput } from 'harness-shared';
import type {
  ModuleModelListResponse,
  ModuleModelSecret,
  ModuleModelSummary,
} from 'harness-shared/module-models';
import { protocolFromProvider } from 'harness-shared/module-models';

import type { CredentialStore } from '../credentials/store';
import { secretRef } from '../credentials/store';
import type { ModelConfigRepository } from '../repositories/model-config.repository';

/** 列表项投影：**不含**密钥，也不含 `apiKeyMasked`（掩码在模块面没有语义）。 */
function toModuleSummary(config: ModelConfig): ModuleModelSummary {
  return {
    id: config.id,
    provider: config.provider,
    protocol: protocolFromProvider(config.provider),
    label: config.label,
    modelName: config.modelName,
    baseUrl: config.baseUrl,
    hasApiKey: config.hasApiKey,
    isActive: config.isActive,
    createdAt: config.createdAt,
    updatedAt: config.updatedAt,
  };
}

export class ModuleModelService {
  readonly #models: ModelConfigRepository;
  readonly #credentials: CredentialStore;

  constructor(models: ModelConfigRepository, credentials: CredentialStore) {
    this.#models = models;
    this.#credentials = credentials;
  }

  async list(): Promise<ModuleModelListResponse> {
    const configs = await this.#models.list();
    return {
      items: configs.map(toModuleSummary),
      // 带上 activeId 让消费方一次调用就能预选中下拉项——否则它得先拉列表再拉
      // /active，而这两次调用之间"当前生效的模型被换掉"会产生一个真实的竞态。
      activeId: configs.find((config) => config.isActive)?.id ?? null,
    };
  }

  async findById(id: string): Promise<ModuleModelSecret | null> {
    const config = await this.#models.findById(id);
    return config === null ? null : this.#toSecret(config);
  }

  /**
   * 写操作：**直接转发给仓储，只在返回时换一套投影**。
   *
   * 不在这里重新实现"先落密钥再落库"的顺序、不重复校验、不做 `isActive` 的互斥——
   * 那些都在 `ModelConfigRepository` 里，是浏览器面正在用的同一份实现。
   * 服务这一层唯一的职责是"回什么形状"，所以它只有三行。
   *
   * 反过来说：任何一条**新增的业务规则**都该加在仓储上（两面同时生效），
   * 而不是加在这里（只有模块面生效，于是两面行为分叉且没人测得到）。
   */
  async create(input: CreateModelConfigInput): Promise<ModuleModelSecret> {
    return this.#toSecret(await this.#models.create(input));
  }

  async update(id: string, patch: UpdateModelConfigInput): Promise<ModuleModelSecret | null> {
    const config = await this.#models.update(id, patch);
    return config === null ? null : this.#toSecret(config);
  }

  async deleteById(id: string): Promise<boolean> {
    return this.#models.deleteById(id);
  }

  async findActive(): Promise<ModuleModelSecret | null> {
    const config = await this.#models.findActive();
    return config === null ? null : this.#toSecret(config);
  }

  #toSecret(config: ModelConfig): ModuleModelSecret {
    return {
      ...toModuleSummary(config),
      apiKey: this.#readApiKey(config),
      temperature: config.temperature,
      topP: config.topP,
      maxOutputTokens: config.maxOutputTokens,
      contextWindow: config.contextWindow,
      timeoutSeconds: config.timeoutSeconds,
    };
  }

  /**
   * 取明文密钥。没配过的返回 null，**不为此去读文件**。
   *
   * 已知的小竞态：`hasApiKey` 为真但与 `read()` 之间配置被删掉，这里会得到 null。
   * 单机单用户下无实际影响，消费方本来就必须处理 `apiKey === null` 这一支。
   */
  #readApiKey(config: ModelConfig): string | null {
    if (!config.hasApiKey) {
      return null;
    }
    return this.#credentials.read(secretRef('model', config.id));
  }
}
