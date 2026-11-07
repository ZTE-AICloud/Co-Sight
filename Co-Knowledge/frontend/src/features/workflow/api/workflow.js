import axios from '@/shared/api/client'

const WORKFLOW_BASE = process.env.VUE_APP_WORKFLOW_BASE
const workflows = `${WORKFLOW_BASE}/workflows`

// 获取高级编排配置（草稿）
export function getFlowConfig (appId, config = {}) {
  return axios.get(`${workflows}/${appId}/flow`, config)
}

// 获取**已发布快照**配置（对话测试实际运行的那份；草稿改动不影响它）
export function getPublishedFlowConfig (appId) {
  return axios.get(`${workflows}/${appId}/publication`)
}

// 画布「知识库」下拉：{ running: [...], dev: [...] }。
export function getAllStatusKbase (params = {}) {
  return axios.get(`${workflows}/knowledge-bases`, { params })
}

// 获取全部知识库列表（画布下拉的另一条历史路径）。
export function getAllKBList (params = {}) {
  return axios.get(`${workflows}/knowledge-bases`, { params })
}

// 校验高级编排配置
export function checkSaveFlowConfig (appId, params, config = {}) {
  return axios.post(`${workflows}/${appId}/validate`, params, { ...config })
}

// 保存高级编排配置
export function saveFlowConfig (appId, params, config = {}) {
  return axios.put(`${workflows}/${appId}/flow`, params, { ...config })
}

// 导出工作流
export function exportWorkFlow (appId) {
  return axios.get(`${workflows}/${appId}/export`, {
    responseType: 'blob'
  })
}

// 查询工作流列表
export function getFlowList (currentPage, pageSize, name = '') {
  return axios.get(workflows, {
    params: { page: currentPage, size: pageSize, keyword: name }
  })
}

// 创建工作流
export function createFlow (params) {
  return axios.post(workflows, params, {})
}

// 更新工作流
export function updateFlow (params) {
  const workflowId = params?.workFlowId || params?.workflowId || params?.appId
  return axios.patch(`${workflows}/${workflowId}`, params, {})
}

// 删除工作流
export function deleteFlowApi (workflowId) {
  return axios.delete(`${workflows}/${workflowId}`)
}

export function publishWorkFlow (appId) {
  return axios.post(`${workflows}/${appId}/publication`, null, {
    headers: {
      'auto-install': 'true'
    }
  })
}

/** 取消发布：只把 publishType 置 0，保留历史快照。 */
export function unpublishWorkFlow (appId) {
  return axios.delete(`${workflows}/${appId}/publication`)
}
