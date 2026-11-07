import axios from '@/shared/api/client'

// 新建知识库
export function createKnowledgeBase (params) {
  return axios.post(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases`, params)
}

// 按名称查同名知识库（建库前重名校验用，见 CreateKnowledgeBaseUnified.vue:handleCreate）。
//
// 走的就是列表页那条 `GET /knowledge-bases`（与 Knowledge.vue 的 getTableDataApi 同源，
// `categories: [1]` = 文档知识库）。⚠️ `keyword` 是**模糊匹配**（实测 `merge-verify`
// 能搜到 `merge-verify-kb`、`KB_20261013` 能搜到 `TestKB_20261013_084750`），
// 所以调用方必须再按 `name` **精确比对** —— 后端的判重是 `name = %s` 精确匹配
// （`backend/src/knowledge_base/repository/kbase.py:find_kbases_by_name`），
// 这里放宽成模糊命中会误报。
export function searchKbasesByName (name) {
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases`, {
    params: { categories: '1', page: 1, size: 50, keyword: name }
  })
}

// 删除文档知识库
export function deleteKnowledgeBase (id) {
  return axios.delete(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${id}`)
}

// 获取单个知识库信息
export function getKnowledgeBaseInfo (id) {
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${id}`)
}

// 修改单个知识库信息
export function updatedKnowledgeBaseInfo (id, data) {
  return axios.patch(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${id}`, data)
}

// 查询数据集
export function getDatasetList (params) {
  const { kbaseId, currentPage = 1, pageSize = 20, keyword = '', ...rest } = params || {}
  return axios.get(`${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${kbaseId}/chunks`, {
    params: { keyword, page: currentPage, size: pageSize, ...rest }
  })
}

// 搜索测试
export function getFileDatasetApi (fileId, params, config = {}) {
  const { kbaseId, currentPage = 1, pageSize = 10, keyword = '', ...rest } = params || {}
  return axios.get(
    `${process.env.VUE_APP_KBASE_BASE}/knowledge-bases/${kbaseId}/documents/${fileId}/chunks`,
    {
      params: { keyword, page: currentPage, size: pageSize, ...rest },
      ...config
    }
  )
}

// 仅限新建知识检索评测任务
