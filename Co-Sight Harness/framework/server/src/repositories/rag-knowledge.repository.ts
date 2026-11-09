/**
 * RAG 知识库跳转路由仓储（设置 → 知识库路由设置）。
 *
 * 最重要的不变量：**全局至多一条 `is_active = 1`**。它由两处共同保证：
 *
 * 1. 库里的部分唯一索引（`rag_knowledge_bases_active_uidx`）——最后一道兜底；
 * 2. 本文件的「先清后设」顺序——先 `UPDATE ... SET is_active = 0`，再设目标行。
 *    顺序反了会撞上第 1 条（两条同时为 1 的那一瞬间被拒），而且**做不到**
 *    「先设后清」：唯一索引不允许中间态存在。
 *
 * ## 为什么激活要包在事务里
 *
 * 先清后设是两条语句。不包事务时，两步之间模块面可能读到「一条生效的都没有」，
 * 而那会被误当成"用户还没配置"。事务把这段中间态挡在服务端内部；
 * 模块面只会看到切换前或切换后的完整状态。
 *
 * ## 删除生效项不自动补位
 *
 * 删完就是「当前没有生效的知识库」。自动把别的行提上来等于替用户改配置——
 * 他可能只是删错了想重加。模块侧本来就必须把 `null` 当正常态处理（见契约文件头）。
 *
 * ## 密码与 API Key 走引用间接层（D26，与模型密钥 / 代理令牌完全同形）
 *
 *   密码    明文 --写--> .credentials.yaml   （键：`rag-knowledge:<id>`）
 *   密码    引用 --存--> rag_knowledge_bases.password_ref
 *   API Key 明文 --写--> .credentials.yaml   （键：`rag-knowledge-api-key:<id>`）
 *   API Key 引用 --存--> rag_knowledge_bases.api_key_ref
 *
 * 对外**只有** `hasPassword` / `hasApiKey` + 固定掩码，明文既不落库也不出这条
 * 浏览器面。写入顺序是**先密钥后数据库**：反过来的话，库里的引用可能指向不存在
 * 的密钥（静默坏数据）；先写密钥最坏只留下一个没人引用的密钥，无害且可清理。
 */

import { asc, eq, ne } from 'drizzle-orm';

import {
  SECRET_MASK,
  type CreateRagKnowledgeBaseInput,
  type RagKnowledgeBase,
  type UpdateRagKnowledgeBaseInput,
} from 'harness-shared';

import type { CredentialStore } from '../credentials/store';
import { secretRef } from '../credentials/store';
import type { Database } from '../db/client';
import { ragKnowledgeBases, type RagKnowledgeRow } from '../db/schema';
import { newId } from '../lib/id';

function refFor(id: string): string {
  return secretRef('rag-knowledge', id);
}

/** API Key 的引用键。与登录密码分开，删行时两枚都要清。 */
function apiKeyRefFor(id: string): string {
  return secretRef('rag-knowledge-api-key', id);
}

/** 空串与全空白都归一到 `null`：读模型里 `username` 只有"有账号"与"没有账号"两态。 */
function normalizeUsername(value: string | null | undefined): string | null {
  const text = value?.trim() ?? '';
  return text === '' ? null : text;
}

function toRecord(row: RagKnowledgeRow): RagKnowledgeBase {
  return {
    id: row.id,
    name: row.name,
    routeUrl: row.routeUrl,
    username: row.username,
    passwordMasked: row.passwordRef === null ? null : SECRET_MASK,
    hasPassword: row.passwordRef !== null,
    apiKeyMasked: row.apiKeyRef === null ? null : SECRET_MASK,
    hasApiKey: row.apiKeyRef !== null,
    description: row.description,
    isActive: row.isActive,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export class RagKnowledgeRepository {
  readonly #db: Database;
  readonly #credentials: CredentialStore;

  constructor(db: Database, credentials: CredentialStore) {
    this.#db = db;
    this.#credentials = credentials;
  }

  async list(): Promise<RagKnowledgeBase[]> {
    const rows = await this.#db
      .select()
      .from(ragKnowledgeBases)
      .orderBy(asc(ragKnowledgeBases.createdAt), asc(ragKnowledgeBases.id));
    return rows.map(toRecord);
  }

  async findById(id: string): Promise<RagKnowledgeBase | null> {
    const [row] = await this.#db
      .select()
      .from(ragKnowledgeBases)
      .where(eq(ragKnowledgeBases.id, id))
      .limit(1);
    return row === undefined ? null : toRecord(row);
  }

  /** 当前生效的一条；没有则 `null`（调用方应把它当正常态，不要当错误）。 */
  async findActive(): Promise<RagKnowledgeBase | null> {
    const [row] = await this.#db
      .select()
      .from(ragKnowledgeBases)
      .where(eq(ragKnowledgeBases.isActive, true))
      .limit(1);
    return row === undefined ? null : toRecord(row);
  }

  async create(
    input: CreateRagKnowledgeBaseInput,
    now: Date = new Date(),
  ): Promise<RagKnowledgeBase> {
    const id = newId();
    const password = input.password ?? null;
    const apiKey = input.apiKey ?? null;
    // 先写密钥再写库（见文件头）；引用只在真写了密钥时才有值。
    let passwordRef: string | null = null;
    if (password !== null) {
      passwordRef = refFor(id);
      await this.#credentials.set(passwordRef, password);
    }
    let apiKeyRef: string | null = null;
    if (apiKey !== null) {
      apiKeyRef = apiKeyRefFor(id);
      await this.#credentials.set(apiKeyRef, apiKey);
    }

    const row: RagKnowledgeRow = {
      id,
      name: input.name,
      routeUrl: input.routeUrl,
      username: normalizeUsername(input.username),
      passwordRef,
      apiKeyRef,
      description: input.description ?? null,
      isActive: input.isActive ?? false,
      createdAt: now,
      updatedAt: now,
    };

    if (!row.isActive) {
      await this.#db.insert(ragKnowledgeBases).values(row);
      return toRecord(row);
    }

    // 新增即生效：与激活走同一条「先清后设」路径，否则直接违反部分唯一索引。
    await this.#db.transaction(async (tx) => {
      await tx.update(ragKnowledgeBases).set({ isActive: false });
      await tx.insert(ragKnowledgeBases).values(row);
    });
    return toRecord(row);
  }

  async update(
    id: string,
    patch: UpdateRagKnowledgeBaseInput,
    now: Date = new Date(),
  ): Promise<RagKnowledgeBase | null> {
    const existing = await this.findById(id);
    if (existing === null) {
      return null;
    }

    const changes: Partial<RagKnowledgeRow> = { updatedAt: now };
    if (patch.name !== undefined) {
      changes.name = patch.name;
    }
    if (patch.routeUrl !== undefined) {
      changes.routeUrl = patch.routeUrl;
    }
    if (patch.username !== undefined) {
      changes.username = normalizeUsername(patch.username);
    }
    if (patch.description !== undefined) {
      changes.description = patch.description;
    }
    if (patch.password !== undefined) {
      const ref = refFor(id);
      if (patch.password === null) {
        await this.#credentials.delete(ref);
        changes.passwordRef = null;
      } else {
        await this.#credentials.set(ref, patch.password);
        changes.passwordRef = ref;
      }
    }
    if (patch.apiKey !== undefined) {
      const ref = apiKeyRefFor(id);
      if (patch.apiKey === null) {
        await this.#credentials.delete(ref);
        changes.apiKeyRef = null;
      } else {
        await this.#credentials.set(ref, patch.apiKey);
        changes.apiKeyRef = ref;
      }
    }
    if (patch.isActive !== undefined) {
      changes.isActive = patch.isActive;
    }

    if (patch.isActive === true) {
      const [row] = await this.#db.transaction(async (tx) => {
        await tx
          .update(ragKnowledgeBases)
          .set({ isActive: false })
          .where(ne(ragKnowledgeBases.id, id));
        return tx
          .update(ragKnowledgeBases)
          .set(changes)
          .where(eq(ragKnowledgeBases.id, id))
          .returning();
      });
      return row === undefined ? null : toRecord(row);
    }

    const [row] = await this.#db
      .update(ragKnowledgeBases)
      .set(changes)
      .where(eq(ragKnowledgeBases.id, id))
      .returning();
    return row === undefined ? null : toRecord(row);
  }

  /** `false` 表示这一行本来就不存在（路由据此回 404）。连带清掉密码与 API Key，不留孤儿密钥。 */
  async deleteById(id: string): Promise<boolean> {
    const rows = await this.#db
      .delete(ragKnowledgeBases)
      .where(eq(ragKnowledgeBases.id, id))
      .returning({ id: ragKnowledgeBases.id });
    if (rows.length === 0) {
      return false;
    }
    await this.#credentials.delete(refFor(id));
    await this.#credentials.delete(apiKeyRefFor(id));
    return true;
  }
}
