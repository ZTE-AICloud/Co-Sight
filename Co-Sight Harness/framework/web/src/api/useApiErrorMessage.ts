import { useCallback } from 'react';

import { useI18n } from '../i18n/useI18n';
import { isApiNetworkError, isApiRequestError } from './errors';

/**
 * 把任意一个抛出来的东西变成一句人话。
 *
 * 三档，顺序不能颠倒：
 * 1. **服务端错误**——服务端给的是 messageKey（不是句子），交给 `tApi` 翻译。
 *    词表里没有这个键时 `tApi` 返回 null，此时退到通用的"服务内部错误"，
 *    而不是把 `error.not_found.something_new` 这种键名糊到界面上。
 * 2. **网络层错误**——请求压根没到服务端（后端没启动时全都是这一档）。
 *    它与服务端错误必须分开说，否则"后端没起"会显示成"服务内部错误"，
 *    用户会去查服务端日志。
 * 3. 其余——可能是渲染期抛的、也可能是我们自己的 bug，统一说"出错了"，
 *    细节留给控制台的堆栈。
 */
export function useApiErrorMessage(): (error: unknown) => string {
  const { t, tApi } = useI18n();

  return useCallback(
    (error: unknown): string => {
      if (isApiRequestError(error)) {
        return tApi(error.messageKey) ?? t('error.internal');
      }
      if (isApiNetworkError(error)) {
        return t('error.network');
      }
      return t('error.internal');
    },
    [t, tApi],
  );
}
