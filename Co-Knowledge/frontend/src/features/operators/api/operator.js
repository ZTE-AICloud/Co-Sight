import axios from '@/shared/api/client';

const BASE = process.env.VUE_APP_KBASE_BASE
const operators = `${BASE}/operators`

// 创建算子（上传算子包）
export function createOperatorApi (params) {
  return axios.post(operators, params);
};

// 导出算子包
export function exportOperatorApi (operatorId) {
  return axios.get(`${operators}/${operatorId}/export`, {
    responseType: 'blob'
  });
};

// 删除算子
export function deleteOperatorApi (operatorId) {
  return axios.delete(`${operators}/${operatorId}`)
};

// 发布算子
export function publishOperatorApi (operatorId) {
  return axios.post(`${operators}/${operatorId}/publish`)
};

// 取消发布算子
export function unPublishOperatorApi (operatorId) {
  return axios.delete(`${operators}/${operatorId}/publish`)
};

// 设为公开 / 取消公开
export function publicOperatorApi (operatorId) {
  return axios.put(`${operators}/${operatorId}/visibility`, { public: true })
};

export function unPublicOperatorApi (operatorId) {
  return axios.put(`${operators}/${operatorId}/visibility`, { public: false })
};

// 获取算子类型
export function getOperatorTypeApi () {
  return axios.get(`${operators}/types`)
};

// 查询算子列表（分页 / 关键字 / 模块 / 可见性 / 格式）
export function queryOperatorListApi (params, config = {}) {
  const {
    currentPage = 1,
    pageSize = 20,
    keyword = '',
    module = '',
    visibleRange,
    visibility,
    format
  } = params || {}
  return axios.get(operators, {
    ...config,
    params: {
      page: currentPage,
      size: pageSize,
      keyword,
      module,
      visibility: visibility ?? visibleRange,
      format
    }
  })
}

// 下载算子模板
export function exportOperatorTemplateApi (params) {
  return axios.get(`${operators}/template`, {
    params: { type: params?.operatorType },
    responseType: 'blob'
  });
};
