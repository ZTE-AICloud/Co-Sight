/**
 * 文件权限位在这套东西里只有两个问题：**能不能设**、**值可不可信**。
 *
 * 两个问题在 Windows 上都不报错——这才是麻烦的地方：
 *
 * 1. `statSync().mode` 在 Windows 上对普通文件恒为 `0o666`（只读文件为 `0o444`），
 *    `chmod` 也只能切换只读位。于是"令牌文件权限不是 0600"这条告警在 Windows 上
 *    **每次启动都会出现**，而它说的是一个那里根本不存在的权限模型——
 *    访问控制由 ACL 决定，POSIX 位只是它的一个投影。
 * 2. 部分非 POSIX 挂载（CIFS、某些网络盘）上 `chmod` 直接抛 `ENOSYS`。
 *    那里若让异常逃出去，"收紧权限失败"就会升级成"写不进令牌/密钥、服务起不来"。
 *
 * 两条判断都写成**纯函数**，是为了能在 Linux 上直接喂 `'win32'` 与 `0o666` 断言——
 * 这两种情形本机一个都复现不了，只有断言守得住（见 `tests/file-mode.test.ts`）。
 */

import fs from 'node:fs';

/** 密钥类文件的权限：仅所有者可读写。与 `config/paths.ts` 的 `CREDENTIALS_FILE_MODE` 同值。 */
export const SECRET_FILE_MODE = 0o600;

/**
 * 尽力把权限收紧到 `mode`。
 *
 * **权限收紧失败不该让服务起不来**——这与 `config/paths.ts` 的 `ensureDirectory`
 * 是同一个取舍，所以两处走同一个实现：那边原来只吞 `ENOSYS`，原子写那边连
 * `try` 都没有，同一件事写两遍必然会漂。
 *
 * 只吞 `ENOSYS`（"这个文件系统没有 chmod 这个概念"）。其余错误照抛：
 * 在 POSIX 上 chmod 失败通常是真问题（权限、只读挂载），静默放过会让人
 * 以为权限已经收紧了。
 */
export function chmodBestEffort(target: string, mode: number): void {
  try {
    fs.chmodSync(target, mode);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOSYS') {
      throw error;
    }
  }
}

/**
 * 这个平台上"权限位"是否值得比较。
 *
 * 只有 Windows 被排除，而且是按平台名判断而不是按"chmod 有没有报错"：
 * Windows 上 chmod **不报错**，它只是不产生 0600 这个结果。
 */
export function posixModeIsMeaningful(platform: NodeJS.Platform): boolean {
  return platform !== 'win32';
}

export type SecretFileModeCheck =
  | { status: 'ok' }
  | { status: 'absent' }
  | { status: 'not-applicable' }
  | { status: 'permissive'; mode: number };

/**
 * 判断一个密钥类文件（模块面令牌、凭据）的权限位该不该报警。
 *
 * `mode` 来自 `statSync().mode & 0o777`，文件不存在时调用方给 `null`
 * （见 `credentials/module-token.ts` 的 `fileMode()`）。
 *
 * 四分法的重点在 `not-applicable`：它和 `permissive` 读到的都是 `0o666`，
 * 但一个是"权限太宽，同机其他用户能读到"，另一个是"这台机器上这个数字没有意义"。
 * 合成一条就会变成每次启动都刷的假告警，而真告警会淹没在里面。
 */
export function checkSecretFileMode(mode: number | null, platform: NodeJS.Platform): SecretFileModeCheck {
  if (mode === null) {
    return { status: 'absent' };
  }
  if (!posixModeIsMeaningful(platform)) {
    return { status: 'not-applicable' };
  }
  return mode === SECRET_FILE_MODE ? { status: 'ok' } : { status: 'permissive', mode };
}
