import axios from '@/shared/api/client';

export function getSupportOperatorApi (params = {}) {
  const query = new URLSearchParams({ module: params.module || '' })
  for (const format of params.formats || []) {
    query.append('format', format)
  }
  if (params.keyword) {
    query.set('keyword', params.keyword)
  }
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/operators/available?${query.toString()}`)
};

export function uploadFileAndSplitConfigApi (kbaseId, params, config = {}) {
  return axios.post(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${kbaseId}/documents`, params, config)
};

export function getFileSizeInfoApi (config = {}) {
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/system/file-size-limits`, {
    ...config,
    params: { category: 1, ...(config.params || {}) }
  })
};



// 检查AIS环境 - 使用原生axios避免拦截器处理
export function checkAISEnvironmentApi () {
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/system/info`);
};

// 检查环境信息 - 用于获取DEPLOYED_BY等信息。
// 画布检索器抽屉据此决定是否提供「知识图谱检索」算子（okiv5 环境隐藏）。
export function checkEnvironmentApi () {
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/system/info`);
};
