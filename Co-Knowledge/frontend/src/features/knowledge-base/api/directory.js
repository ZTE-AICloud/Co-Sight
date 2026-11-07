import axios from '@/shared/api/client'

const BASE = process.env.VUE_APP_KBASE_BASE

// 目录列表：GET /knowledge-bases/{kbId}/directories
export function getDescendantsDirectoryList (params, config = {}) {
  const { kbaseId, ...rest } = params || {}
  return axios.get(`${BASE}/knowledge-bases/${kbaseId}/directories`, {
    params: {
      type: 'folder',
      sort: true,
      ...rest
    },
    ...config
  })
}

// 创建目录：POST /knowledge-bases/{kbId}/directories
export function createDirectory (params, data) {
  const { kbaseId, parentId } = params || {}
  return axios.post(`${BASE}/knowledge-bases/${kbaseId}/directories`, {
    parentId,
    ...(data || {})
  })
}

// 重命名目录：PATCH /knowledge-bases/{kbId}/directories/{id}
export function updateDirectory (kBaseId, id, data) {
  return axios.patch(`${BASE}/knowledge-bases/${kBaseId}/directories/${id}`, data)
}

// 删除目录（保留文档，文档移到 Default）：DELETE /knowledge-bases/{kbId}/directories/{id}
export function deleteDirectory (kBaseId, id) {
  return axios.delete(`${BASE}/knowledge-bases/${kBaseId}/directories/${id}`)
}

// 批量移动文档到目录：PATCH /knowledge-bases/{kbId}/documents
export function moveDocuments (kBaseId, ids, parentId) {
  return axios.patch(`${BASE}/knowledge-bases/${kBaseId}/documents`, { ids, parentId })
}

// 删除文件（文档）：DELETE /knowledge-bases/{kbId}/documents/{id}
export function deleteFile (kBaseId, id) {
  return axios.delete(`${BASE}/knowledge-bases/${kBaseId}/documents/${id}`)
}

// 重新解析失败文档：POST /knowledge-bases/{kbId}/documents/{id}/retry
// 后端只接受 status=2（解析失败）的文档；成功返回 202 + {fileId, taskId}。
export function retryFile (kBaseId, id) {
  return axios.post(`${BASE}/knowledge-bases/${kBaseId}/documents/${id}/retry`)
}

// 下载原文件：GET /knowledge-bases/{kbId}/documents/{fileId}/content
export function downloadFileOut (params) {
  const { kbaseId, fileId } = params || {}
  return axios({
    url: `${BASE}/knowledge-bases/${kbaseId}/documents/${fileId}/content`,
    method: 'get',
    responseType: 'blob'
  })
}

/**
 * 整库文件分页：GET /knowledge-bases/{kbId}/documents
 *
 * pageSize 上限是后端 `directory_service.MAX_PAGE_SIZE = 100`，超过会回 0004。
 */
export function getAllFilesPageApi (kbaseId, params = {}, config = {}) {
  const { currentPage = 1, pageSize = 50, keyword = '' } = params || {}
  return axios.get(
    `${BASE}/knowledge-bases/${encodeURIComponent(kbaseId)}/documents`,
    {
      params: { page: currentPage, size: pageSize, keyword },
      ...config
    }
  )
}
