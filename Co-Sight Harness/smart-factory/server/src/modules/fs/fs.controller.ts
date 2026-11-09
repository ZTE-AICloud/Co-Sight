import type { NextFunction, Request, Response } from 'express';
import { fsService } from './fs.service.js';

/** HTTP 适配：取参 → service → 组装响应；路径校验在 `shared/workspace/local-path.ts`。 */
export const fsController = {
  async roots(_req: Request, res: Response): Promise<void> {
    res.json(await fsService.roots());
  },

  async list(req: Request, res: Response): Promise<void> {
    res.json(await fsService.list({ path: req.query.path }));
  },

  async read(req: Request, res: Response): Promise<void> {
    res.json(await fsService.read({ path: req.query.path }));
  },

  /**
   * 原始字节流。路径走**路径分段**而不是 `?path=`：HTML 预览要在 iframe 里加载相对资源，
   * 只有分段形态才能让 `./style.css` 自然落到 `/fs/raw/.../style.css`（见 `fs.routes.ts`）。
   */
  async raw(req: Request, res: Response, next: NextFunction): Promise<void> {
    const splat: unknown = req.params.splat;
    const segments: string[] = Array.isArray(splat)
      ? splat.filter((segment): segment is string => typeof segment === 'string')
      : typeof splat === 'string'
        ? [splat]
        : [];
    // `~/...` 原样交给 local-path 展开（它只认 `~` 开头，不能在前面补 `/`）；
    // Windows 盘符（`C:/...`）同样不能补前导 `/`，否则会变成 `/C:/...` 而解析失败。
    const joined = segments.join('/');
    const isDrivePath = /^[A-Za-z]:([/\\]|$)/u.test(joined);
    const real = await fsService.raw({
      path: joined.startsWith('~') || isDrivePath ? joined : `/${joined}`,
    });

    res.set({
      // 文档类资源靠 CSP sandbox 隔离脚本能力；图片等非文档资源会忽略这一条
      'Content-Security-Policy':
        'sandbox allow-scripts allow-forms allow-popups allow-downloads',
      'Content-Disposition': 'inline',
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'no-store',
    });
    // dotfiles: 'allow' 必须带：产物路径常有 .smart-factory 这类点段（见 artifact.controller.ts）
    res.sendFile(real, { dotfiles: 'allow' }, (err) => {
      // 成功时不要继续往下走：响应已经发完，再 next() 会落到 404 处理器
      if (err !== undefined) next(err);
    });
  },
};
