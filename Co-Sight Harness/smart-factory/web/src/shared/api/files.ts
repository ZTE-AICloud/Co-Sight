import { api } from './client';

/**
 * 用户上传的静态文件（封面图等）。
 *
 * 正本：`server/docs/05-openapi/5.02-file-openapi.yaml`；机制见
 * `server/docs/03-architecture/09-file.md`。首个使用方就是智能体封面图：
 * 上传后把返回的 `url` 写进 `Agent.icon`，展示层不用改（icon 本来就是一个 URL 字符串）。
 *
 * 两条后端约定要记住：
 *
 * - **字段名固定 `file`**，multipart/form-data；单文件上限由服务端配置
 *   （`FILES_MAX_FILE_BYTES`，缺省 10MB），超限是 413。前端不自己卡一个写死的上限 ——
 *   那个值可能被部署环境改大改小，交给后端判断才不会两边打架。
 * - **`url` 是相对路径**（`/api/smart-factory/v1/files/fil_…`），同源直接用；
 *   开发态经 vite 的 `/api` 代理打到后端，不要在前面拼主机名。
 */

/** 上传成功的响应（5.02 的 `FileUploaded`）。 */
export interface UploadedFile {
  /** 存储名，同时是读回时的 id：`fil_<uuid>` + 可选消毒扩展名 */
  name: string;
  /** 可直接塞进 `Agent.icon` 的相对地址 */
  url: string;
  /** 字节数 */
  size: number;
}

export const filesApi = {
  /**
   * 上传一个文件。multipart 字段名固定 `file`。
   *
   * 后缀与 Content-Type 由服务端按原文件名消毒后决定，原文件名不保留；
   * 图片类型的选择器约束是调用方的事（后端不做类型白名单，见 09-file.md §6）。
   */
  upload(file: File): Promise<UploadedFile> {
    const form = new FormData();
    form.append('file', file);
    return api.postForm<UploadedFile>('/smart-factory/v1/files', form);
  },
};
