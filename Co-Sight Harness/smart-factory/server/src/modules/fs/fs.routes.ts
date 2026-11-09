import { Router } from 'express';
import { fsController } from './fs.controller.js';

/**
 * 挂载点：/api/smart-factory/v1（fs/*）
 *
 * 只读：本机文件浏览给发送框选路径用，没有写入口。与 `/artifacts/*` 的分界 ——
 * artifacts 看的是智能体工作区里的产物（按 stage + agentId 解析），
 * fs 看的是**操作者本机**的任意文件（按绝对路径，整机可浏览）。
 *
 * ⚠️ `/fs/*` 无鉴权且可浏览整机，服务缺省监听全部地址，只应部署在可信网络；
 * 只需本机访问时设 `HOST=127.0.0.1`。
 *
 * `raw` 用路径分段（`/fs/raw/<绝对路径去掉开头 />`）而不是 `?path=`：
 * HTML 预览要在 iframe 里加载相对资源。查询串形态下 `./style.css` 会被解析成
 * `/fs/style.css`；分段形态下它自然落到 `/fs/raw/.../style.css`。
 */
export const fsRouter = Router();

fsRouter.get('/fs/roots', fsController.roots);
fsRouter.get('/fs/list', fsController.list);
fsRouter.get('/fs/read', fsController.read);
// Express 5：通配符必须具名；`req.params.splat` 是已解码的分段数组
fsRouter.get('/fs/raw/*splat', fsController.raw);
