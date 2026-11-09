import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { config } from '../../config/index.js';
import { BadGatewayError } from '../errors.js';

/** 与框架同一形状：base64url，至少 16 个字符。形状校验同时保证令牌可安全放进请求头。 */
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,}$/;

/** 模块令牌文件位置；错误消息与 401 提示都指向它。 */
export function moduleTokenPath(): string {
  return join(config.cosightHome, '.module-token');
}

/**
 * 每个请求现读 `{cosightHome}/.module-token`：改文件立即生效，且不进环境变量、不进日志。
 *
 * 先验形状再交给 fetch：非法内容（换行、非 ASCII）若进了请求头，fetch 的校验错误会把内容带进消息。
 */
export function readModuleToken(): string {
  const path = moduleTokenPath();
  let raw: string;
  try {
    raw = readFileSync(path, 'utf8');
  } catch {
    // 不存在或不可读都按同一句可操作文案报出，不泄漏底层异常细节
    throw new BadGatewayError(`读取模块令牌失败：${path} 不存在或不可读`);
  }
  const token = raw.trim();
  if (token === '') {
    throw new BadGatewayError(`读取模块令牌失败：${path} 为空`);
  }
  if (!TOKEN_PATTERN.test(token)) {
    throw new BadGatewayError(
      `模块令牌 ${path} 内容非法：期望单行 base64url，至少 16 个字符`,
      'error.bad_gateway.module_token',
      { path },
    );
  }
  return token;
}
