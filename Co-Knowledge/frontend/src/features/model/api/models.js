import axios from '@/shared/api/client'

const KBASE_BASE = process.env.VUE_APP_KBASE_BASE

// 获取向量模型列表
export function getModelList () {
  return axios.get(`${KBASE_BASE}/system/embedding-models`, {})
}

// 获取大模型下拉选项
//
// `/system/llm-models` 的规范形状是 `{value, label}`；画布三个抽屉历史上吃的是
// `{modelValue, nameZh}`，在 API 层做一次适配，避免改三个视图与它们的模板。
export function getLLMModel () {
  return axios.get(`${KBASE_BASE}/system/llm-models`, {}).then(list =>
    (Array.isArray(list) ? list : []).map(item => ({
      modelValue: item.value,
      nameZh: item.label
    })))
}

// 获取重排模型下拉选项（`/system/rerank-models` → `[{value, label, isDefault}]`）。
// 与运行期解析同源：画布上能选的，就是模型注册表里启用的那些。
export function getRerankModels () {
  return axios.get(`${KBASE_BASE}/system/rerank-models`, {}).then(list =>
    (Array.isArray(list) ? list : []))
}
