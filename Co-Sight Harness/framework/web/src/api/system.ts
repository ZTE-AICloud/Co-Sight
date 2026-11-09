/**
 * 系统级接口：健康检查与模块清单。
 *
 * 两者放在一起是因为它们回答同一类问题——"这个部署现在长什么样"：
 * 数据目录在哪、服务端什么版本、有哪些模块挂上来了。这类信息由服务端给，
 * 前端**不猜**。用户配错 `COSIGHT_HOME` 时，设置页直接显示实际生效的路径，
 * 比让他去翻环境变量快得多。
 */

import type { ModuleManifest } from 'harness-shared';
import { useQuery } from '@tanstack/react-query';

import { requestData } from './client';

export interface HealthInfo {
  status: 'ok';
  version: string;
  uptimeSeconds: number;
  cosightHome: string;
  database: string;
}

/** 模块清单接口的返回：合法模块 + 不合法模块（后者带问题清单）。 */
export interface ModuleScanResult {
  modules: ModuleManifest[];
  invalid: {
    file: string;
    issues: { path: string; code: string; message: string }[];
  }[];
}

export const systemKeys = {
  health: ['system', 'health'] as const,
  modules: ['system', 'modules'] as const,
};

export const systemApi = {
  health: (signal?: AbortSignal) => requestData<HealthInfo>('/health', { signal }),
  modules: (signal?: AbortSignal) => requestData<ModuleScanResult>('/modules', { signal }),
};

export function useHealth() {
  return useQuery({
    queryKey: systemKeys.health,
    queryFn: ({ signal }) => systemApi.health(signal),
    // 健康检查不到就说明后端没起来，此时反复重试没有意义。
    retry: false,
  });
}

export function useModules() {
  return useQuery({
    queryKey: systemKeys.modules,
    queryFn: ({ signal }) => systemApi.modules(signal),
    // 模块清单只在启动时扫一次，运行期不会变（改动需要重启）。
    staleTime: Number.POSITIVE_INFINITY,
  });
}
