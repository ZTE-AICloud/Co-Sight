/**
 * 文件大小限制的解析与统计纯函数：maxSizeMap 归一化 / 取后缀白名单 / 合计文件大小。
 *
 * 零 Vue 依赖：不读组件状态 / i18n，可在 Node 里直接单测。
 */

/**
 * 「单次上传的文件大小总量」上限（MB）。
 *
 * 真值来自 **nginx**：`frontend/nginx.conf` 的 `client_max_body_size 650m`（注释说明它
 * 是为了让超大文件走到业务侧的友好 JSON 错误、而不是 nginx 默认 1MB 的 HTML 413）。
 * 后端 `/file/size_limit` 只给「单类型上限 + 文件个数」，**没有总量字段**，所以这个数
 * 只能由前端持有；集中为单一常量：**校验用它、提示文案也用它**，避免两处各自漂移。
 */
export const TOTAL_UPLOAD_SIZE_MB = 650

/** `calculateTotalFileSize` 的最小入参：上传项自身或它的 `raw` File 带 `size` 即可。 */
export interface SizedFileLike {
  /** 字节数 */
  size?: number | null
  /** 原始 File（本地上传时有；数据集管理导入的项没有 raw） */
  raw?: { size?: number | null } | null
}

// 将对象的键转换为小写（与AddData.vue保持一致）
export function convertKeysToLower(obj: Record<string, number>): Record<string, number> {
  const lowerCaseObj: Record<string, number> = {};
  for (const [key, value] of Object.entries(obj)) {
    lowerCaseObj[key] = value as number;
  }
  return lowerCaseObj;
}

// 获取对象的键作为文件扩展名列表
export function getFileExtensions(obj: Record<string, number>): string[] {
  return Object.keys(obj);
}

// 计算文件总大小
export function calculateTotalFileSize(files: SizedFileLike[]): number {
  let totalSize = 0;
  files.forEach((item: any) => {
    totalSize += item.size || item.raw?.size || 0;
  });
  return totalSize;
}
