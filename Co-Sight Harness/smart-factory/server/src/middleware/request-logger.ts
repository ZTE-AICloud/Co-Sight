import type { NextFunction, Request, Response } from 'express';

/**
 * 提取标识字段：键为 `id` 或以 `Id` 结尾，值限字符串。
 *
 * 白名单以外的字段一律不记，正文（content / prompt / answers 等）与密钥永不落日志。
 */
function pickIds(source: unknown): string {
  if (source === null || typeof source !== 'object') return '';
  return Object.entries(source)
    .filter(([key, value]) => (key === 'id' || key.endsWith('Id')) && typeof value === 'string')
    .map(([key, value]) => `${key}=${value as string}`)
    .join(' ');
}

/** 极简访问日志：方法 / 路径 / 标识 / 状态码 / 耗时。路径里不出现 id，标识只能从这里补。 */
export function requestLogger(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const startedAt = Date.now();

  res.on('finish', () => {
    const elapsed = Date.now() - startedAt;
    const ids = [pickIds(req.query), pickIds(req.body)].filter((part) => part !== '').join(' ');
    console.log(
      `[smart-factory] ${req.method} ${req.originalUrl}${ids === '' ? '' : ` ${ids}`} ${res.statusCode} ${elapsed}ms`,
    );
  });

  next();
}
