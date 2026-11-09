/**
 * 统一 API 响应信封（对应用户规则「API 响应格式」）。
 *
 * 每个响应恒含四段：状态指示（success）、数据（data）、错误（error）、元信息（meta）。
 * 未分页时 meta 为 null 而非缺省，客户端无需做 `'meta' in res` 判断。
 */

import type { ApiError } from './errors';

export interface PageMeta {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  hasMore: boolean;
}

export interface ApiSuccess<T> {
  success: true;
  data: T;
  error: null;
  meta: PageMeta | null;
}

export interface ApiFailure {
  success: false;
  data: null;
  error: ApiError;
  meta: PageMeta | null;
}

export type ApiResponse<T> = ApiSuccess<T> | ApiFailure;

export function ok<T>(data: T, meta: PageMeta | null = null): ApiSuccess<T> {
  return { success: true, data, error: null, meta };
}

export function fail(error: ApiError, meta: PageMeta | null = null): ApiFailure {
  return { success: false, data: null, error, meta };
}

export function buildPageMeta(total: number, page: number, pageSize: number): PageMeta {
  const safePageSize = Math.max(1, pageSize);
  const totalPages = total === 0 ? 0 : Math.ceil(total / safePageSize);
  return {
    page,
    pageSize: safePageSize,
    total,
    totalPages,
    hasMore: page * safePageSize < total,
  };
}

/** 分页列表的统一载荷形状。 */
export interface Paged<T> {
  items: T[];
}
