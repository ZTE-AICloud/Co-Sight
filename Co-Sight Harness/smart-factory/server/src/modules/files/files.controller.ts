import type { NextFunction, Request, Response } from 'express';
import multer, { MulterError } from 'multer';
import { config } from '../../config/index.js';
import { BadRequestError, PayloadTooLargeError } from '../../shared/errors.js';
import { requireString } from '../../shared/validate.js';
import { filesRoot, filesService } from './files.service.js';

const MAX_MB = Math.floor(config.filesMaxFileBytes / 1024 / 1024);

/** multipart 解析：落盘到 files/（multer 自建目录），超限 413，字段/报文不对 400。 */
const upload = multer({
  dest: filesRoot(),
  limits: { fileSize: config.filesMaxFileBytes },
});

/** multer 的错误语义在这里翻译成领域错误；业务规则不进 HTTP 适配层。 */
export function uploadSingleFile(req: Request, res: Response, next: NextFunction): void {
  upload.single('file')(req, res, (err) => {
    if (!err) {
      if (!req.file)
        return next(
          new BadRequestError('file 必填（multipart 字段名 file）', 'error.bad_request.file_required'),
        );
      return next();
    }
    if (err instanceof MulterError) {
      if (err.code === 'LIMIT_FILE_SIZE') {
        return next(
          new PayloadTooLargeError(`单文件超过大小上限（${MAX_MB}MB）`, 'error.payload_too_large.file', {
            max: `${MAX_MB}MB`,
          }),
        );
      }
      return next(new BadRequestError(`上传被拒：${err.code}`));
    }
    return next(err);
  });
}

/** HTTP 适配：取参 → service → 组装响应；业务规则不在这里。 */
export const filesController = {
  async upload(req: Request, res: Response): Promise<void> {
    const file = req.file!;
    res.json(await filesService.saveUploaded(file.path, file.originalname, file.size));
  },

  async get(req: Request, res: Response, next: NextFunction): Promise<void> {
    const { absolutePath, contentType } = filesService.readStored(requireString(req.params.fileId, 'fileId'));
    // dotfiles: 'allow' 与 /artifacts/download 同口径；nosniff 防内容嗅探改道
    res.type(contentType).set('X-Content-Type-Options', 'nosniff');
    res.sendFile(absolutePath, { dotfiles: 'allow' }, (err) => next(err));
  },
};
