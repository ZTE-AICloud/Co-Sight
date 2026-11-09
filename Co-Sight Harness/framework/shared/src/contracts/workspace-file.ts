/**
 * 工作区文件浏览契约（会话区右侧边栏的「工作区文件」面板）。
 *
 * ## 为什么这几个接口在**浏览器面**，不在模块面
 *
 * 它们吐的是用户文件的内容。模块面那枚令牌已经能改平台配置，再把读文件内容挂上去，
 * 等于让"一枚泄漏的令牌"多一个能读走用户文件的用法，而且没有任何消费方需要它
 * （面板是框架自己的界面在用）。所以这一组只在 `/api/workspaces/*` 下，
 * `workspace-api.md` / `module-facing-api.md` 的端点表里**没有**它们。
 *
 * ## 路径口径：只有工作区相对路径
 *
 * 请求里**永远没有绝对路径**。根目录由服务端按工作区 id 从库里取（`Workspace.directory`），
 * 客户端只说"根下面的哪一段"。这一条比"传绝对路径再校验"窄得多，也正因为窄才安全：
 * 没有绝对路径，就没有"校验被写漏"这种可能。空串 = 根。
 *
 * 字段级说明见各自的 JSDoc。磁盘那一半的口径（realpath 后判包含、不跟随软链、
 * 四个上限）在 `docs/workspace-design.md` 的「只读浏览」一节。
 */

import { z } from 'zod';

/** 相对路径的长度上限。它最终会进一次 `path.join`，先用长度兜住荒谬的输入。 */
export const WORKSPACE_FILE_PATH_MAX_LENGTH = 1024;

/**
 * 三个上限。它们拦的都是**体积**，不是敏感性——面板会把工作区里任何 UTF-8 文本
 * 原样显示出来，包括用户自己放进去的凭据文件。
 *
 * 放在契约里而不是服务端内部，是因为它们**从响应里看得见**：`truncated` 什么时候
 * 为真、`413` 什么时候出现，都由这几个数决定。前端还要用它把"只显示了前面多少"
 * 说准（写死一个 512 KiB 迟早会和实现对不上）。
 *
 * 判定二进制用的"嗅探字节数"不在其中：它不影响任何客户端可见的结果。
 */
export const WORKSPACE_FILE_LIMITS = {
  /** 一层目录最多列多少项，超出置 `truncated`。 */
  maxEntries: 2000,
  /** 文本一次最多读多少字节，超出置 `truncated`。 */
  maxTextBytes: 512 * 1024,
  /** 图片最大多少字节，超出直接 `413`（base64 之后体积还要再涨 1/3）。 */
  maxImageBytes: 2 * 1024 * 1024,
} as const;

/**
 * 一个目录项的类型。
 *
 * `other` 是**刻意留的第三个值**，不是一个"其他情况"的垃圾桶：它装着所有
 * 面板点了也不会有反应的东西——软链、FIFO、socket、设备文件。合并进 `file`
 * 会让界面承诺一个做不到的"点开看看"。
 */
export const WORKSPACE_FILE_ENTRY_TYPES = ['file', 'directory', 'other'] as const;

export type WorkspaceFileEntryType = (typeof WORKSPACE_FILE_ENTRY_TYPES)[number];

export const workspaceFileEntrySchema = z.object({
  name: z.string(),
  type: z.enum(WORKSPACE_FILE_ENTRY_TYPES),
  /** 仅普通文件有；软链/目录/其他不报。 */
  size: z.number().int().nonnegative().optional(),
});

export type WorkspaceFileEntry = z.infer<typeof workspaceFileEntrySchema>;

/**
 * 一层目录的列表。
 *
 * `root` 是**服务端解析出来的**工作区目录绝对路径，不传就不知道列的是哪儿
 * （工作区可能没绑目录，或绑了一个用户手填的、框架不创建也不校验的路径）。
 *
 * `root === null` 表示"这个工作区还没绑目录"——那是**正常状态**，返回 `200`，
 * 与 `GET /workspaces/active` 没有当前工作区时返回 `data: null` 是同一条口径。
 * 它**不等于**"目录不存在"：后者是 `404`，因为那意味着用户以为文件还在。
 */
export const workspaceFileListingSchema = z.object({
  root: z.string().nullable(),
  /** 被列出的目录（工作区相对路径；根为空串）。 */
  path: z.string(),
  entries: z.array(workspaceFileEntrySchema),
  /** 条目数是否被上限截断。为 `true` 时列表**不是**这个目录的全部内容。 */
  truncated: z.boolean(),
});

export type WorkspaceFileListing = z.infer<typeof workspaceFileListingSchema>;

/**
 * 一个文本文件的一页。
 *
 * 本轮**不分页**：一次返回前 `WORKSPACE_FILE_LIMITS.maxTextBytes` 字节，
 * 超出的部分用 `truncated` 如实说出来。分页要一整套 offset/续读状态，
 * 而"看一眼工作区里的文件"这个场景里，超出几百 KiB 的文件本来就看不完。
 */
export const workspaceFileTextSchema = z.object({
  path: z.string(),
  /** 文件**完整**字节数（不是返回的 `text` 的长度）。 */
  size: z.number().int().nonnegative(),
  text: z.string(),
  truncated: z.boolean(),
});

export type WorkspaceFileText = z.infer<typeof workspaceFileTextSchema>;

/**
 * 一张图片。
 *
 * `dataUrl` 是 base64 内联，而不是给一个"裸二进制"端点：仓库的硬规矩是
 * **每个响应都是同一套信封**（`server/src/http/reply.ts` 文件头）。一个
 * `content-type: image/png` 的响应会让**出错时**前端读到一张读不懂的图，
 * 而不是一句人话。4/3 的体积代价由 `maxImageBytes` 上限兜住。
 */
export const workspaceFileImageSchema = z.object({
  path: z.string(),
  size: z.number().int().nonnegative(),
  contentType: z.string(),
  dataUrl: z.string(),
});

export type WorkspaceFileImage = z.infer<typeof workspaceFileImageSchema>;

/** 三个端点共用的查询串。`path` 省略或空串 = 工作区根。 */
export const workspaceFilePathQuerySchema = z.object({
  path: z.string().max(WORKSPACE_FILE_PATH_MAX_LENGTH).optional(),
});

export type WorkspaceFilePathQuery = z.infer<typeof workspaceFilePathQuerySchema>;
