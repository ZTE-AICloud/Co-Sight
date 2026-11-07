import axios from '@/shared/api/client'
import { KBASE_BASE } from '@/shared/api/endpoints'

/**
 * 模型注册与管理（`{KBASE_BASE}/models`）。
 *
 * 三条与后端约定好的形状，改动前先对一下 `backend/src/model/`：
 *
 * 1. **前缀只在 `endpoints.js` 写一次**。这里 import `KBASE_BASE`，不写字面量。
 * 2. 列表返回 `{ items, total, page, pageSize }` —— 列表接口
 *    的 `returnStructFun` 读的就是这两个字段名。
 * 3. **`apiKey` 永远是脱敏值**（`apiKeyMasked`），明文只在提交时上行。
 *    编辑时那个框留空 = 不改动库里那把 key（后端按此语义实现）。
 */

export function queryModelsApi (params, config = {}) {
  return axios.get(`${KBASE_BASE}/models`, { params, ...config })
}

export function getModelApi (modelId, config = {}) {
  return axios.get(`${KBASE_BASE}/models/${modelId}`, config)
}

/** 思考预置目录 + 当前模型名的自动匹配结果（只读） */
export function getThinkingPresetsApi (params = {}, config = {}) {
  return axios.get(`${KBASE_BASE}/models/thinking-presets`, { params, ...config })
}

export function createModelApi (data, config = {}) {
  return axios.post(`${KBASE_BASE}/models`, data, config)
}

export function updateModelApi (modelId, data, config = {}) {
  return axios.put(`${KBASE_BASE}/models/${modelId}`, data, config)
}

export function deleteModelApi (modelId, config = {}) {
  return axios.delete(`${KBASE_BASE}/models/${modelId}`, config)
}

/** 测已保存的行（后端用库里那把 key，前端不用再传） */
export function testModelApi (modelId, data = {}, config = {}) {
  return axios.post(`${KBASE_BASE}/models/${modelId}/test`, data, config)
}

/** 测**还没保存**的表单配置（新建向导用） */
export function testModelConfigApi (data, config = {}) {
  return axios.post(`${KBASE_BASE}/models/test`, data, config)
}
