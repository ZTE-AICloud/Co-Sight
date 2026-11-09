/**
 * 模块面令牌（`$COSIGHT_HOME/.module-token`）。
 *
 * 它解决的是一个很具体的问题：**别的本机进程怎么从框架拿到模型配置（含明文密钥）**。
 * 浏览器面（`/api/models/*`）永远不回传密钥——那条契约由 `tests/api-model.test.ts`
 * 钉死，一个字都不松。于是需要一个只对本机进程开放的口子，令牌就是那个口子的门。
 *
 * ## 它挡得住什么，挡不住什么（这段话比实现更重要）
 *
 * **挡得住**：浏览器里跑的代码。页面读不到本机文件，所以拿不到令牌，也就拿不到密钥。
 * 这是令牌存在的**全部**理由。
 *
 * **挡不住**：同机同用户的其他进程。它们可以**直接读** `$COSIGHT_HOME/.credentials.yaml`
 * （文件 0600 挡的是"属主 vs 其他人"，不是同 UID 的进程），根本不需要走 HTTP。
 * 所以这枚令牌**不是访问控制边界**，只是"给消费方一个显式、可撤销的 opt-in 契约"。
 * 把它说成访问控制会给出错误的安全感——`bridge/session.ts` 的文件头有同样的告诫。
 *
 * ## 三条实现约束
 *
 * 1. **文件 0600、父目录 0700**，落盘走 `lib/atomic-file.ts`（0600 先于写入 → fsync → rename）。
 * 2. **重启不轮换**。文件存在就原样沿用。每次重启换一枚新令牌等于把它退化成"启动期
 *    随机数"，那这个文件就白存在了，模块也没法长跑。
 * 3. **每次校验重读文件，不缓存**。热轮换才有意义：运维改完文件，模块下次拿 401
 *    重读即可生效，不用重启框架。这也与 `CredentialStore.read()` 的既有习惯一致。
 *
 * 本模块**永远不把令牌写进日志**，也不在错误信息里回显令牌内容。
 */

import crypto from 'node:crypto';
import fs from 'node:fs';

import { credentialsFileMode } from '../config/paths';
import { readFileIfExists, writeFileAtomicSync } from '../lib/atomic-file';

/** 32 字节 = 256 位熵，与 `bridge/session.ts` 的会话 id 同一原语与强度。 */
export const MODULE_TOKEN_BYTES = 32;

/**
 * 合法令牌的形状：base64url，至少 16 个字符。
 *
 * 下限取 16（而不是写死生成的 43）是给运维留的自定义余地——想用自选的密钥
 * 就自己写进去，只要能过这个形状检查。上限不设，但显然应当是个高熵字符串。
 */
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,}$/;

export class ModuleTokenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ModuleTokenError';
  }
}

function generateToken(): string {
  return crypto.randomBytes(MODULE_TOKEN_BYTES).toString('base64url');
}

export class ModuleTokenStore {
  readonly #filePath: string;

  constructor(filePath: string) {
    this.#filePath = filePath;
  }

  get filePath(): string {
    return this.#filePath;
  }

  /**
   * 启动时调一次：文件不在就生成，在就原样沿用（**不轮换**）。
   *
   * 文件存在但内容非法时**抛错**，不静默覆盖。这与 `CredentialStore.#load()` 的
   * 既有原则一致——"看不懂的文件必须报错而不是当作空集合，否则下一次写入会把
   * 用户原有的内容整体覆盖掉，造成静默数据丢失"。让启动失败、并在错误信息里
   * 点名文件与期望格式，比让模块面悄悄 401 一切要好排查得多。
   */
  ensure(): string {
    const existing = this.read();
    if (existing !== null) {
      return existing;
    }
    const token = generateToken();
    writeFileAtomicSync(this.#filePath, `${token}\n`, credentialsFileMode());
    return token;
  }

  /**
   * 读当前令牌；文件不存在返回 null。
   *
   * 内容非法（空、含空白、非 base64url 字符）时抛 `ModuleTokenError`，
   * 不把它当成一个合法令牌返回。
   */
  read(): string | null {
    const raw = readFileIfExists(this.#filePath);
    if (raw === null) {
      return null;
    }
    const token = raw.trim();
    if (!TOKEN_PATTERN.test(token)) {
      throw new ModuleTokenError(
        `模块面令牌文件内容非法：${this.#filePath}（期望单行 base64url，至少 16 个字符）`,
      );
    }
    return token;
  }

  /** 文件的权限位；文件不存在返回 null。 */
  fileMode(): number | null {
    try {
      return fs.statSync(this.#filePath).mode & 0o777;
    } catch {
      return null;
    }
  }

  /**
   * 校验候选令牌。**失败一律返回 false，绝不抛异常**——fail closed 这条性质
   * 不该依赖调用方记得写 try/catch。
   *
   * 先比长度再 `timingSafeEqual`：长度不等直接短路。长度本身不是秘密（格式是公开的），
   * 而且 `timingSafeEqual` 对不等长的 buffer 会**抛异常**，必须先挡。
   *
   * 常量时间比较的定位要说清楚：主控制是"令牌从不进浏览器"，不是这个函数。
   * 回环上的时序攻击要跨网络噪声采样几百次，实际不可行；用 `timingSafeEqual`
   * 的成本是零所以用，但**不能**把它写成"防住了时序攻击"而让人以为这里是防线。
   */
  verify(candidate: string): boolean {
    let stored: string | null;
    try {
      stored = this.read();
    } catch {
      // 文件读了但内容非法 → 没有可比对的基准，判为不通过。
      return false;
    }
    if (stored === null) {
      return false;
    }

    const expected = Buffer.from(stored, 'utf8');
    const provided = Buffer.from(candidate, 'utf8');
    if (expected.length !== provided.length) {
      return false;
    }
    return crypto.timingSafeEqual(expected, provided);
  }

  /** 重新生成并落盘，返回新令牌。旧令牌**立即失效**（没有双活窗口）。 */
  rotate(): string {
    const token = generateToken();
    writeFileAtomicSync(this.#filePath, `${token}\n`, credentialsFileMode());
    return token;
  }

  /** 删除令牌文件（幂等）。此后模块面一律 401，直到新的令牌被写回。 */
  revoke(): void {
    fs.rmSync(this.#filePath, { force: true });
  }
}
