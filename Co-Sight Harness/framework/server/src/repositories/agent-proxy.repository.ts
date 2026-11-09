/**
 * Agent 代理配置仓储（需求 2.3-1）。
 *
 * 与模型配置同构：令牌走 `.credentials.yaml` 引用间接层，对外只回掩码。
 * 由于两者除了字段名之外逻辑完全一致，这里刻意**不再抽一层泛型基类**——
 * 字段映射本来就不同，抽象化换来的只是间接层，而非更少的代码。
 */

import { asc, eq, ne } from 'drizzle-orm';

import {
  SECRET_MASK,
  type AgentProxyConfig,
  type CreateAgentProxyInput,
  type SecurityAnalyzer,
  type UpdateAgentProxyInput,
} from 'harness-shared';

import { secretRef, type CredentialStore } from '../credentials/store';
import type { Database } from '../db/client';
import { agentProxyConfigs, type AgentProxyConfigRow } from '../db/schema';
import { newId } from '../lib/id';

function refFor(id: string): string {
  return secretRef('agent-proxy', id);
}

function toAgentProxy(row: AgentProxyConfigRow): AgentProxyConfig {
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    agentType: row.agentType,
    endpoint: row.endpoint,
    enabled: row.enabled,
    isDefault: row.isDefault,
    maxIterations: row.maxIterations,
    parallelism: row.parallelism,
    timeoutSeconds: row.timeoutSeconds,
    memoryEnabled: row.memoryEnabled,
    condensationEnabled: row.condensationEnabled,
    securityAnalyzer: row.securityAnalyzer as SecurityAnalyzer,
    tokenMasked: row.tokenRef === null ? null : SECRET_MASK,
    hasToken: row.tokenRef !== null,
    extra: row.extra,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export class AgentProxyRepository {
  readonly #db: Database;
  readonly #credentials: CredentialStore;

  constructor(db: Database, credentials: CredentialStore) {
    this.#db = db;
    this.#credentials = credentials;
  }

  async list(): Promise<AgentProxyConfig[]> {
    const rows = await this.#db
      .select()
      .from(agentProxyConfigs)
      .orderBy(asc(agentProxyConfigs.createdAt), asc(agentProxyConfigs.id));
    return rows.map(toAgentProxy);
  }

  async findById(id: string): Promise<AgentProxyConfig | null> {
    const [row] = await this.#db
      .select()
      .from(agentProxyConfigs)
      .where(eq(agentProxyConfigs.id, id))
      .limit(1);
    return row === undefined ? null : toAgentProxy(row);
  }

  async findDefault(): Promise<AgentProxyConfig | null> {
    const [row] = await this.#db
      .select()
      .from(agentProxyConfigs)
      .where(eq(agentProxyConfigs.isDefault, true))
      .limit(1);
    return row === undefined ? null : toAgentProxy(row);
  }

  async create(input: CreateAgentProxyInput, now: Date = new Date()): Promise<AgentProxyConfig> {
    const id = newId();
    const tokenRef = input.token === null ? null : refFor(id);
    if (tokenRef !== null) {
      await this.#credentials.set(tokenRef, input.token as string);
    }

    if (input.isDefault) {
      await this.#clearDefault();
    }

    const row: AgentProxyConfigRow = {
      id,
      name: input.name,
      description: input.description,
      agentType: input.agentType,
      endpoint: input.endpoint,
      enabled: input.enabled,
      isDefault: input.isDefault,
      maxIterations: input.maxIterations,
      parallelism: input.parallelism,
      timeoutSeconds: input.timeoutSeconds,
      memoryEnabled: input.memoryEnabled,
      condensationEnabled: input.condensationEnabled,
      securityAnalyzer: input.securityAnalyzer,
      tokenRef,
      extra: { ...input.extra },
      createdAt: now,
      updatedAt: now,
    };
    await this.#db.insert(agentProxyConfigs).values(row);
    return toAgentProxy(row);
  }

  async update(
    id: string,
    patch: UpdateAgentProxyInput,
    now: Date = new Date(),
  ): Promise<AgentProxyConfig | null> {
    const existing = await this.findById(id);
    if (existing === null) {
      return null;
    }

    const changes: Partial<AgentProxyConfigRow> = { updatedAt: now };
    if (patch.name !== undefined) {
      changes.name = patch.name;
    }
    if (patch.description !== undefined) {
      changes.description = patch.description;
    }
    if (patch.agentType !== undefined) {
      changes.agentType = patch.agentType;
    }
    if (patch.endpoint !== undefined) {
      changes.endpoint = patch.endpoint;
    }
    if (patch.enabled !== undefined) {
      changes.enabled = patch.enabled;
    }
    if (patch.maxIterations !== undefined) {
      changes.maxIterations = patch.maxIterations;
    }
    if (patch.parallelism !== undefined) {
      changes.parallelism = patch.parallelism;
    }
    if (patch.timeoutSeconds !== undefined) {
      changes.timeoutSeconds = patch.timeoutSeconds;
    }
    if (patch.memoryEnabled !== undefined) {
      changes.memoryEnabled = patch.memoryEnabled;
    }
    if (patch.condensationEnabled !== undefined) {
      changes.condensationEnabled = patch.condensationEnabled;
    }
    if (patch.securityAnalyzer !== undefined) {
      changes.securityAnalyzer = patch.securityAnalyzer;
    }
    if (patch.extra !== undefined) {
      changes.extra = { ...patch.extra };
    }

    if (patch.token !== undefined) {
      const ref = refFor(id);
      if (patch.token === null) {
        await this.#credentials.delete(ref);
        changes.tokenRef = null;
      } else {
        await this.#credentials.set(ref, patch.token);
        changes.tokenRef = ref;
      }
    }

    if (patch.isDefault === true) {
      await this.#clearDefault(id);
      changes.isDefault = true;
    } else if (patch.isDefault === false) {
      changes.isDefault = false;
    }

    const rows = await this.#db
      .update(agentProxyConfigs)
      .set(changes)
      .where(eq(agentProxyConfigs.id, id))
      .returning();
    const [row] = rows;
    return row === undefined ? null : toAgentProxy(row);
  }

  async deleteById(id: string): Promise<boolean> {
    const rows = await this.#db
      .delete(agentProxyConfigs)
      .where(eq(agentProxyConfigs.id, id))
      .returning({ id: agentProxyConfigs.id });
    if (rows.length === 0) {
      return false;
    }
    await this.#credentials.delete(refFor(id));
    return true;
  }

  async #clearDefault(exceptId?: string): Promise<void> {
    const query = this.#db.update(agentProxyConfigs).set({ isDefault: false });
    await (exceptId === undefined ? query : query.where(ne(agentProxyConfigs.id, exceptId)));
  }
}
