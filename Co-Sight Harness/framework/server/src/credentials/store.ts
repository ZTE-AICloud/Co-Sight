/**
 * 密钥存储（D26 = A）。
 *
 * 明文密钥只存在于 `$COSIGHT_HOME/.credentials.yaml`，数据库里只存引用键。
 * 这样 sqlite.db 可以随意备份、拷贝、贴进 issue，都不会带出密钥。
 *
 * 三条实现约束：
 * 1. **文件 0600、父目录 0700**。临时文件以 0600 创建，而不是创建后再 chmod——
 *    后者会留下一个短暂的世界可读窗口。
 * 2. **原子写**：写临时文件 → fsync → rename。rename 在同一文件系统内是原子的，
 *    进程中途被杀不会留下半截 YAML。
 * 3. **进程内串行**：写操作挂在一条 promise 链上，避免同进程内两次并发写互相覆盖。
 *    跨进程并发（同时起两个 server）未做文件锁，v1 不支持多实例。
 *
 * 本模块**永远不把密钥写进日志**，也不在错误信息里回显密钥内容。
 */

import fs from 'node:fs';

import { parse, stringify } from 'yaml';

import { credentialsFileMode } from '../config/paths';
import { writeFileAtomicSync } from '../lib/atomic-file';

/**
 * 密钥引用键的类别前缀。
 *
 * `rag-knowledge` = 打开知识库页面的登录密码；`rag-knowledge-api-key` = 模块
 * 访问知识服务的 Agent API Key（`CO_KNOWLEDGE_API_KEY`）。两者是**同一行的两枚
 * 独立密钥**。
 */
export const SECRET_KINDS = [
  'model',
  'agent-proxy',
  'rag-knowledge',
  'rag-knowledge-api-key',
] as const;

export type SecretKind = (typeof SECRET_KINDS)[number];

/** 构造引用键；数据库里存的就是这个字符串。 */
export function secretRef(kind: SecretKind, entityId: string): string {
  return `${kind}:${entityId}`;
}

interface CredentialsFileShape {
  version: number;
  secrets: Record<string, string>;
}

const FILE_VERSION = 1;

export class CredentialsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CredentialsError';
  }
}

export class CredentialStore {
  readonly #filePath: string;

  /** 写操作串行链；见文件头第 3 条。 */
  #writeChain: Promise<void> = Promise.resolve();

  constructor(filePath: string) {
    this.#filePath = filePath;
  }

  get filePath(): string {
    return this.#filePath;
  }

  /** 读取密钥明文；不存在返回 null。 */
  read(ref: string): string | null {
    return this.#load().secrets[ref] ?? null;
  }

  has(ref: string): boolean {
    return this.read(ref) !== null;
  }

  /** 写入或覆盖。值必须是已去除首尾空白的非空字符串。 */
  async set(ref: string, value: string): Promise<void> {
    const normalized = value.trim();
    if (normalized === '') {
      throw new CredentialsError('密钥不能为空');
    }
    await this.#mutate((secrets) => {
      secrets[ref] = normalized;
    });
  }

  /** 删除；键不存在时静默通过（幂等）。 */
  async delete(ref: string): Promise<void> {
    await this.#mutate((secrets) => {
      delete secrets[ref];
    });
  }

  /** 只列出引用键，绝不返回明文。 */
  listRefs(): string[] {
    return Object.keys(this.#load().secrets).toSorted();
  }

  async #mutate(change: (secrets: Record<string, string>) => void): Promise<void> {
    const next = this.#writeChain.then(() => {
      const current = this.#load();
      const secrets: Record<string, string> = { ...current.secrets };
      change(secrets);
      this.#write({ version: FILE_VERSION, secrets });
    });
    // 无论本次成败，都不让链条断掉，否则后续写会永久 reject。
    this.#writeChain = next.catch(() => undefined);
    return next;
  }

  #load(): CredentialsFileShape {
    let raw: string;
    try {
      raw = fs.readFileSync(this.#filePath, 'utf8');
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return { version: FILE_VERSION, secrets: {} };
      }
      throw new CredentialsError(`无法读取密钥文件：${this.#filePath}`);
    }

    let parsed: unknown;
    try {
      parsed = parse(raw);
    } catch {
      throw new CredentialsError(`密钥文件不是合法 YAML：${this.#filePath}`);
    }

    // 数组也是 object，但绝不是我们写的文件。这类"看不懂的文件"必须报错而不是
    // 当作空集合——否则下一次 set() 会把用户原有的内容整体覆盖掉，造成静默数据丢失。
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new CredentialsError(`密钥文件结构非法：${this.#filePath}`);
    }

    const shape = parsed as Partial<CredentialsFileShape>;
    const secrets = shape.secrets;
    // 键缺失 = 全新的空文件，可以接受；键存在但不是对象 = 文件被写坏了，报错。
    if (secrets === undefined || secrets === null) {
      return { version: FILE_VERSION, secrets: {} };
    }
    if (typeof secrets !== 'object' || Array.isArray(secrets)) {
      throw new CredentialsError(`密钥文件的 secrets 段结构非法：${this.#filePath}`);
    }

    // 逐项校验：非字符串的值一律丢弃，避免把 YAML 里的意外结构当成密钥用。
    const clean: Record<string, string> = {};
    for (const [key, value] of Object.entries(secrets)) {
      if (typeof value === 'string') {
        clean[key] = value;
      }
    }
    return { version: FILE_VERSION, secrets: clean };
  }

  #write(payload: CredentialsFileShape): void {
    // 落盘纪律（0600 先于写入、fsync 后 rename、rename 后补 chmod）统一在
    // `lib/atomic-file.ts` 里，与模块面令牌文件共用同一份实现。
    writeFileAtomicSync(this.#filePath, stringify(payload), credentialsFileMode());
  }
}
