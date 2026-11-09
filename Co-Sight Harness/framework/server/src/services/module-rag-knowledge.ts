/**
 * 模块面知识库服务：把路由记录投影成"别的本机进程能直接用"的形状，`/active` **含明文密码**。
 *
 * ## 为什么单独一个文件，而不是给仓储加个方法
 *
 * 与 `services/module-models.ts` 同一条理由：`repositories/rag-knowledge.repository.ts`
 * 的 `toRecord()` 是浏览器面"永不回传明文密码"的**签名级**保证——Row 里根本没有可读的
 * 明文字段。往那个文件里塞一条返回明文的兄弟方法，后来人改浏览器面映射时就在同一个
 * 文件里，"顺手改错"的风险陡增。所以两面的投影函数**物理分离**。
 *
 * ## 只有 `/active` 出明文
 *
 * 与模型面一致：列表返回 `ModuleRagKnowledgeSummary`（只有 `hasPassword`），明文只从
 * `GET /active` 一条路由出去。泄漏面因此是固定的一条，而不是"每个返回知识库的地方"。
 *
 * ## 已知的小竞态
 *
 * `hasPassword` 为真但与 `read()` 之间配置被删掉，这里会得到 null。单机单用户下
 * 无实际影响，消费方本来就必须处理 `password === null` 这一支。
 *
 * ## API Key 的两层
 *
 * 路由自己配的 Key 优先；没配时回落到服务端默认（`COSIGHT_KNOWLEDGE_API_KEY` /
 * `CO_KNOWLEDGE_API_KEY`）。消费方拿到的 `apiKey` 永远是**生效的那一枚**，
 * 不需要自己判断该用哪一层——默认值只在服务端内存里，不落库也不进浏览器面。
 */

import type { RagKnowledgeBase } from 'harness-shared';
import type {
  ModuleRagKnowledgeSecret,
  ModuleRagKnowledgeSummary,
} from 'harness-shared/module-rag-knowledge';

import type { CredentialStore } from '../credentials/store';
import { secretRef } from '../credentials/store';
import type { RagKnowledgeRepository } from '../repositories/rag-knowledge.repository';

/** 列表项投影：**不含**密码，也不含 `passwordMasked`（掩码在模块面没有语义）。 */
function toSummary(record: RagKnowledgeBase): ModuleRagKnowledgeSummary {
  return {
    id: record.id,
    name: record.name,
    routeUrl: record.routeUrl,
    username: record.username,
    hasPassword: record.hasPassword,
    hasApiKey: record.hasApiKey,
    description: record.description,
    isActive: record.isActive,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
  };
}

export class ModuleRagKnowledgeService {
  readonly #repo: RagKnowledgeRepository;
  readonly #credentials: CredentialStore;
  /** 服务端预置的默认 API Key；null = 没配。只在内存里，不落库。 */
  readonly #defaultApiKey: string | null;

  constructor(
    repo: RagKnowledgeRepository,
    credentials: CredentialStore,
    defaultApiKey: string | null = null,
  ) {
    this.#repo = repo;
    this.#credentials = credentials;
    this.#defaultApiKey = defaultApiKey;
  }

  async list(): Promise<ModuleRagKnowledgeSummary[]> {
    const records = await this.#repo.list();
    return records.map(toSummary);
  }

  async findActive(): Promise<ModuleRagKnowledgeSecret | null> {
    const record = await this.#repo.findActive();
    return record === null ? null : this.#toSecret(record);
  }

  #toSecret(record: RagKnowledgeBase): ModuleRagKnowledgeSecret {
    return {
      ...toSummary(record),
      password: this.#readPassword(record),
      apiKey: this.#readApiKey(record),
    };
  }

  /** 取明文密码。没配过的返回 null，**不为此去读文件**。 */
  #readPassword(record: RagKnowledgeBase): string | null {
    if (!record.hasPassword) {
      return null;
    }
    return this.#credentials.read(secretRef('rag-knowledge', record.id));
  }

  /**
   * 取生效的明文 API Key：路由自己的优先，没配（或密钥文件里读不到）时回落默认。
   *
   * 回落到默认这一步放在这里而不是仓储里：默认值属于**服务端配置**，不是这条
   * 路由的数据，写进库会让"改了环境变量却不生效"（旧值已被复制到每一行）。
   */
  #readApiKey(record: RagKnowledgeBase): string | null {
    if (!record.hasApiKey) {
      return this.#defaultApiKey;
    }
    return (
      this.#credentials.read(secretRef('rag-knowledge-api-key', record.id)) ?? this.#defaultApiKey
    );
  }
}
