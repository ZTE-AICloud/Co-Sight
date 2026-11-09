/**
 * 模型配置仓储（需求 2.3）。
 *
 * 密钥走引用间接层（D26 = A）：
 *   明文 --写--> .credentials.yaml      （键：`model:<id>`）
 *   引用 --存--> model_configs.api_key_ref
 * 对外**只有掩码**，明文既不落库也不出网。
 *
 * 写入顺序是先密钥后数据库。反过来的话，一旦密钥写入失败，库里会留下一个
 * 指向不存在密钥的引用（静默坏数据）；而先写密钥再写库，最坏只是留下一个
 * 没人引用的密钥（无害，且可用 listRefs 清理）。
 */

import { asc, eq, ne } from 'drizzle-orm';

import {
  SECRET_MASK,
  type CreateModelConfigInput,
  type ModelConfig,
  type UpdateModelConfigInput,
} from 'harness-shared';

import type { CredentialStore } from '../credentials/store';
import { secretRef } from '../credentials/store';
import type { Database } from '../db/client';
import { modelConfigs, type ModelConfigRow } from '../db/schema';
import { newId } from '../lib/id';

function refFor(id: string): string {
  return secretRef('model', id);
}

function toModelConfig(row: ModelConfigRow): ModelConfig {
  return {
    id: row.id,
    provider: row.provider as ModelConfig['provider'],
    label: row.label,
    baseUrl: row.baseUrl,
    modelName: row.modelName,
    apiKeyMasked: row.apiKeyRef === null ? null : SECRET_MASK,
    hasApiKey: row.apiKeyRef !== null,
    isActive: row.isActive,
    temperature: row.temperature,
    topP: row.topP,
    maxOutputTokens: row.maxOutputTokens,
    contextWindow: row.contextWindow,
    timeoutSeconds: row.timeoutSeconds,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export class ModelConfigRepository {
  readonly #db: Database;
  readonly #credentials: CredentialStore;

  constructor(db: Database, credentials: CredentialStore) {
    this.#db = db;
    this.#credentials = credentials;
  }

  async list(): Promise<ModelConfig[]> {
    const rows = await this.#db
      .select()
      .from(modelConfigs)
      .orderBy(asc(modelConfigs.createdAt), asc(modelConfigs.id));
    return rows.map(toModelConfig);
  }

  async findById(id: string): Promise<ModelConfig | null> {
    const [row] = await this.#db
      .select()
      .from(modelConfigs)
      .where(eq(modelConfigs.id, id))
      .limit(1);
    return row === undefined ? null : toModelConfig(row);
  }

  async findActive(): Promise<ModelConfig | null> {
    const [row] = await this.#db
      .select()
      .from(modelConfigs)
      .where(eq(modelConfigs.isActive, true))
      .limit(1);
    return row === undefined ? null : toModelConfig(row);
  }

  async create(input: CreateModelConfigInput, now: Date = new Date()): Promise<ModelConfig> {
    const id = newId();
    const apiKeyRef = input.apiKey === null ? null : refFor(id);
    if (apiKeyRef !== null) {
      await this.#credentials.set(apiKeyRef, input.apiKey as string);
    }

    if (input.isActive) {
      await this.#clearActive();
    }

    const row: ModelConfigRow = {
      id,
      provider: input.provider,
      label: input.label,
      baseUrl: input.baseUrl,
      modelName: input.modelName,
      apiKeyRef,
      isActive: input.isActive,
      temperature: input.temperature,
      topP: input.topP,
      maxOutputTokens: input.maxOutputTokens,
      contextWindow: input.contextWindow,
      timeoutSeconds: input.timeoutSeconds,
      createdAt: now,
      updatedAt: now,
    };
    await this.#db.insert(modelConfigs).values(row);
    return toModelConfig(row);
  }

  async update(
    id: string,
    patch: UpdateModelConfigInput,
    now: Date = new Date(),
  ): Promise<ModelConfig | null> {
    const existing = await this.findById(id);
    if (existing === null) {
      return null;
    }

    const changes: Partial<ModelConfigRow> = { updatedAt: now };
    if (patch.provider !== undefined) {
      changes.provider = patch.provider;
    }
    if (patch.label !== undefined) {
      changes.label = patch.label;
    }
    if (patch.baseUrl !== undefined) {
      changes.baseUrl = patch.baseUrl;
    }
    if (patch.modelName !== undefined) {
      changes.modelName = patch.modelName;
    }
    if (patch.temperature !== undefined) {
      changes.temperature = patch.temperature;
    }
    if (patch.topP !== undefined) {
      changes.topP = patch.topP;
    }
    if (patch.maxOutputTokens !== undefined) {
      changes.maxOutputTokens = patch.maxOutputTokens;
    }
    if (patch.contextWindow !== undefined) {
      changes.contextWindow = patch.contextWindow;
    }
    if (patch.timeoutSeconds !== undefined) {
      changes.timeoutSeconds = patch.timeoutSeconds;
    }

    if (patch.apiKey !== undefined) {
      const ref = refFor(id);
      if (patch.apiKey === null) {
        await this.#credentials.delete(ref);
        changes.apiKeyRef = null;
      } else {
        await this.#credentials.set(ref, patch.apiKey);
        changes.apiKeyRef = ref;
      }
    }

    if (patch.isActive === true) {
      await this.#clearActive(id);
      changes.isActive = true;
    } else if (patch.isActive === false) {
      changes.isActive = false;
    }

    const rows = await this.#db
      .update(modelConfigs)
      .set(changes)
      .where(eq(modelConfigs.id, id))
      .returning();
    const [row] = rows;
    return row === undefined ? null : toModelConfig(row);
  }

  /** 删除配置，并连带清除其密钥，避免留下孤儿密钥。 */
  async deleteById(id: string): Promise<boolean> {
    const rows = await this.#db.delete(modelConfigs).where(eq(modelConfigs.id, id)).returning({
      id: modelConfigs.id,
    });
    if (rows.length === 0) {
      return false;
    }
    await this.#credentials.delete(refFor(id));
    return true;
  }

  async #clearActive(exceptId?: string): Promise<void> {
    const query = this.#db.update(modelConfigs).set({ isActive: false });
    await (exceptId === undefined ? query : query.where(ne(modelConfigs.id, exceptId)));
  }
}
