import axios from '@/shared/api/client'
import { KBASE_BASE } from '@/shared/api/endpoints'
import { $t } from '@/app/i18n/i18n.js'

// 处理上传响应的辅助函数
// 拦截器对非 2xx/problem 一律 reject，进到这里的只有成功体。
function handleUploadResponse (response) {
  const responseData = response?.data || response || {}
  if (responseData.success === false || responseData.message) {
    return handleDataError(responseData)
  }
  return handleSuccessResponse(responseData)
}

// 处理数据错误
function handleDataError (responseData) {
  return {
    success: false,
    message: responseData.message,
    data: {
      successCount: responseData?.successCount || 0,
      failedCount: responseData?.failedCount || 0,
      failedDetails: responseData?.failedDetails || []
    }
  }
}

// 处理成功响应
function handleSuccessResponse (responseData) {
  return {
    success: true,
    data: {
      successCount: responseData?.successCount || 0,
      failedCount: responseData?.failedCount || 0,
      failedDetails: responseData?.failedDetails || []
    }
  }
}

// 处理上传错误
function handleUploadError (error) {
  // 由于使用了validateStatus: true，正常情况下不应该进入这里
  // 这里只处理真正的网络错误（如超时、断网等）
  console.error('网络错误或超时:', error)

  let errorMessage = $t('modules.commonUi.knowledgeGraphApi.networkFailed')
  if (error.code === 'ECONNABORTED') {
    errorMessage = $t('modules.commonUi.knowledgeGraphApi.timeout')
  } else if (error?.detail || error?.message) {
    errorMessage = error.detail || error.message
  }

  // 返回统一的错误格式，不抛出异常
  return Promise.resolve({
    success: false,
    message: errorMessage,
    data: {
      successCount: 0,
      failedCount: 1,
      failedDetails: [errorMessage]
    }
  })
}

// 知识库/图谱库列表：GET /knowledge-bases（筛选/分页/排序走查询参数）
export function knowledgeGraphListApi (params = {}, config = {}) {
  const query = {
    page: params.currentPage ?? params.page ?? params.pageNum ?? 1,
    size: params.pageSize ?? params.size ?? 10
  }
  if (params.keyword) {
    query.keyword = params.keyword
  }
  if (params.categories) {
    query.categories = [].concat(params.categories).join(',')
  }
  if (params.embeddingModel) {
    query.embeddingModel = params.embeddingModel
  }
  const orderList = params.orderList || []
  if (orderList.length) {
    query.sort = orderList
      .filter(item => item && item.key)
      .map(item => `${item.key}:${item.ascending === false ? 'desc' : 'asc'}`)
      .join(',')
  }
  return axios.get(`${KBASE_BASE}/knowledge-bases`, { ...config, params: query })
}

// 分类汇总：GET /knowledge-bases/stats
// 文档知识库列表页与知识图谱列表页的指标卡都用它，替代「按 size=500 把全量列表拉回来自己数」。
// 返回 `{categories: [{category, total, fileTotal, statusCounts}]}`；
// 状态分类（就绪/进行中/失败）在前端做，见 views/kBase/lib/overview-stats.ts。
export function knowledgeBaseStatsApi (params = {}, config = {}) {
  const query = {}
  if (params.categories) {
    query.categories = [].concat(params.categories).join(',')
  }
  return axios.get(`${KBASE_BASE}/knowledge-bases/stats`, { ...config, params: query })
}

// 新建知识图谱

// 查询文件上传限制（大小与数量）
// 入参: category(number)
export function getKbaseFileLimitApi (category, config = {}) {
  return axios.get(`${KBASE_BASE}/system/file-size-limits`, { ...config, params: { category } })
}

// 删除知识库（DELETE /knowledge-bases/{id}）
export function deleteKnowledgeGraphApi (id, config = {}) {
  return axios.delete(`${KBASE_BASE}/knowledge-bases/${id}`, config)
}

// 修改知识图谱

// 知识图谱基本信息（GET /knowledge-bases/{kb_id}/graph）
export function getKnowledgeGraphBasicInfoApi (kbId, config = {}) {
  return axios.get(`${KBASE_BASE}/knowledge-bases/${kbId}/graph`, {
    ...config,
    skipErrorHandler: true // 跳过错误处理，避免知识库不存在时弹出错误提示
  })
}

/**
 * 生成知识图谱
 * @param {File[]} files - 语料文件列表
 * @param {Object} data - 生成参数
 * @param {string} data.operatorId - 算子ID
 * @param {string} data.kbId - 知识库ID
 * @param {string} data.schemaId - 知识图谱模版ID
 * @returns {Promise}
 */

/**
 * 获取算子列表
 * @returns {Promise}
 */
export async function getOperatorListApi (operatorType = 'graph_extract', config = {}) {
  // 取全量：建图/改图的下拉要列出该模块所有算子，只取第一页会在算子超过 500 个时
  // 静默漏掉。首屏用 total 判断是否还要翻页（后端对 size 另有上限时靠 items 累计兜底）。
  const pageSize = 500 // eslint-disable-line no-magic-numbers
  const maxPages = 20 // eslint-disable-line no-magic-numbers
  const items = []
  let total = Infinity
  let page = 1
  while (items.length < total && page <= maxPages) {
    const res = await axios.get(`${KBASE_BASE}/operators`, {
      ...config,
      params: { module: operatorType, page, size: pageSize }
    })
    const chunk = res?.items || []
    total = Number(res?.total ?? chunk.length)
    if (!chunk.length) {
      break
    }
    items.push(...chunk)
    page += 1
  }
  return items
}

// 获取知识图谱模版列表
export function knowledgeGraphTemplateListApi (params, config = {}) {
  // 该接口不需要任何查询参数，直接返回所有数据
  return axios.get(`${KBASE_BASE}/graph-schemas`, config)
}

// 获取大模型列表
export function getLlmListApi (config = {}) {
  return axios.get(`${KBASE_BASE}/system/llm-models`, config)
}

// 生成知识图谱
export function extractKnowledgeGraphApi (formData, config = {}) {
  const headers = { ...config.headers || {}, 'Content-Type': 'multipart/form-data' }
  return axios.post(`${KBASE_BASE}/graph-extractions`, formData, { ...config, headers })
}

// 删除知识图谱模版
export function deleteKnowledgeGraphTemplateApi (schemaId, config = {}) {
  return axios.delete(`${KBASE_BASE}/graph-schemas/${schemaId}`, config)
}

// 上传知识图谱模版文件
export function uploadKnowledgeGraphTemplateApi (file, config = {}) {
  const formData = new FormData()
  formData.append('schema_file', file)

  return axios.post(`${KBASE_BASE}/graph-schemas/import`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    timeout: 300000, // 5分钟超时
    validateStatus () {
      // 让所有HTTP状态码都被视为成功，避免axios拦截器捕获错误
      return true
    },
    ...config
  }).then(handleUploadResponse)
    .catch(handleUploadError)
}

/**
 * 获取知识图谱文件列表
 * @param {string} kbaseId - 知识库ID
 * @param {object} params - 查询参数
 * @param {number} params.currentPage - 当前页
 * @param {number} params.pageSize - 每页大小
 * @param {string} params.keyword - 关键字
 * @returns {Promise}
 */
export function getKnowledgeGraphFileListApi (kbaseId, params = {}, config = {}) {
  const defaultParams = {
    currentPage: 1,
    pageSize: 50,
    keyword: ''
  }

  const requestParams = { ...defaultParams, ...params }

  return axios.get(`${KBASE_BASE}/knowledge-bases/${kbaseId}/documents`, {
    ...config,
    params: {
      keyword: requestParams.keyword || '',
      page: requestParams.currentPage || requestParams.page || 1,
      size: requestParams.pageSize || requestParams.size || 50
    }
  })
}

// 更新知识图谱（PUT /knowledge-bases/{id}/graph）
export function updateKnowledgeGraphExtractApi (kbId, formData, config = {}) {
  return axios.put(`${KBASE_BASE}/knowledge-bases/${kbId}/graph`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      ...config.headers
    },
    ...config
  })
}

/**
 * 获取图谱可视化数据
 * @param {string} kbId - 知识库ID
 * @param {number} limit - 限制数量，默认100
 * @param {number} depth - 深度，默认10
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */

/**
 * 查询图谱数据（按条件查询）
 * @param {string} kbId - 知识库ID
 * @param {number} limit - 限制数量
 * @param {number} depth - 深度
 * @param {string} direction - 方向
 * @param {string} queryType - 查询模式 (entity/relation/subgraph)
 * @param {Array} filters - 查询过滤条件
 * @param {string} keyword - 实体搜索关键字（名称 / 实体 ID / 描述，模糊匹配）
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function getGraphQueryApi (kbId, limit = 100, depth = 10, direction = 'both', queryType = '', filters = [], keyword = '', config = {}) { // eslint-disable-line no-magic-numbers
  let mappedQueryType = queryType
  if (queryType === 'relation') {
    mappedQueryType = 'edge'
  } else if (queryType === 'subgraph') {
    mappedQueryType = 'sub_graph'
  }

  const requestBody = {
    limit,
    depth,
    direction,
    query_type: mappedQueryType,
    filters
  }
  // 只有非空才带这个键：后端对 `keyword: ""` 也是「不过滤」，但少一个键能让
  // 抓包一眼看出「这次搜索到底有没有生效」。
  if (String(keyword || '').trim()) {
    requestBody.keyword = String(keyword).trim()
  }

  return axios.post(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/query`, requestBody, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

/**
 * 更新实体属性
 * @param {string} kbId - 知识库ID
 * @param {string} entityId - 实体ID
 * @param {string} entityType - 实体类型
 * @param {Object} properties - 实体属性
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function updateEntityApi (kbId, entityId, entityType, properties, config = {}) {
  const requestBody = { entityType, properties }

  return axios.patch(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/entities/${encodeURIComponent(entityId)}`, requestBody, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

/**
 * 删除实体
 * @param {string} kbId - 知识库ID
 * @param {string} entityId - 实体ID
 * @param {string} entityType - 实体类型
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function deleteEntityApi (kbId, entityId, entityType, config = {}) {
  return axios.delete(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/entities/${encodeURIComponent(entityId)}`, {
    params: { entityType },
    ...config
  })
}

/**
 * 更新边属性
 * @param {string} kbId - 知识库ID
 * @param {string} edgeId - 边ID
 * @param {string} edgeType - 边类型
 * @param {Object} properties - 边属性
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function updateEdgeApi (kbId, edgeId, edgeType, properties, config = {}) {
  const requestBody = { edgeType, properties }

  return axios.patch(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/edges/${encodeURIComponent(edgeId)}`, requestBody, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

/**
 * 删除边
 * @param {string} kbId - 知识库ID
 * @param {string} edgeId - 边ID
 * @param {string} edgeType - 边类型
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function deleteEdgeApi (kbId, edgeId, edgeType, config = {}) {
  return axios.delete(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/edges/${encodeURIComponent(edgeId)}`, {
    params: { edgeType },
    ...config
  })
}

/**
 * 创建边API
 * @param {string} kbId - 知识库ID
 * @param {string} edgeId - 边ID
 * @param {string} edgeType - 边类型
 * @param {Object} properties - 边属性
 * @param {string} sourceId - 起始实体ID
 * @param {string} targetId - 目标实体ID
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function createEdgeApi (kbId, edgeId, edgeType, properties, sourceId, targetId, config = {}) {
  const requestBody = {
    kbId,
    edgeId,
    edgeType,
    properties,
    sourceId,
    targetId
  }

  return axios.post(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/edges`, requestBody, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

/**
 * 创建实体API
 * @param {string} kbId - 知识库ID
 * @param {string} entityId - 实体ID
 * @param {string} entityType - 实体类型
 * @param {Object} properties - 实体属性
 * @param {Object} edgeInfo - 边信息（可选）
 * @param {Object} config - 请求配置
 * @returns {Promise}
 */
export function createEntityApi (kbId, entityId, entityType, properties, edgeInfo = null, config = {}) {
  const requestBody = {
    kbId,
    entityId,
    entityType,
    properties
  }

  // 如果有边信息，添加到请求体中
  if (edgeInfo) {
    requestBody.edgeInfo = edgeInfo
  }

  return axios.post(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/entities`, requestBody, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

// 导入知识图谱数据
export function importKnowledgeGraphApi (file, config = {}) {
  const formData = new FormData()
  formData.append('file', file)

  return axios.post(`${KBASE_BASE}/graph-imports`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
      ...config.headers
    },
    ...config
  })
}

/**
 * 获取LLM选项列表
 * @returns {Promise} API响应
 */
export function getLlmOptionsApi () {
  return axios.get(`${KBASE_BASE}/system/llm-models`);
}

/**
 * Create graph schema template
 * @param {Object} data - Schema data
 * @param {string} data.schema_id - Schema ID (optional, auto-generated if not provided)
 * @param {string} data.schema_name - Schema name (required)
 * @param {string} data.schema_desc - Schema description (optional)
 * @param {Array} data.entities - Entity definitions (required, non-empty)
 * @param {Array} data.edges - Edge definitions (required, non-empty)
 * @param {Object} config - Request configuration
 * @returns {Promise} API response
 */
export function createGraphSchemaTemplate (data, config = {}) {
  return axios.post(`${KBASE_BASE}/graph-schemas`, data, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}

/**
 * Export graph knowledge base
 * @param {string} kbId - Knowledge base ID
 * @param {Object} config - Request configuration
 * @returns {Promise} API response (blob)
 */
export function exportGraphKnowledgeBaseApi (kbId, config = {}) {
  return axios.get(`${KBASE_BASE}/knowledge-bases/${kbId}/graph/export`, {
    ...config,
    responseType: 'blob' // 重要：设置为 blob 以接收文件流
  })
}

/**
 * Get graph schema template detail
 * @param {string} schemaId - Schema ID
 * @param {Object} config - Request configuration
 * @returns {Promise} API response
 */
export function getGraphSchemaTemplateDetail (schemaId, config = {}) {
  return axios.get(`${KBASE_BASE}/graph-schemas/${schemaId}`, {
    ...config
  })
}

/**
 * Update graph schema template
 * @param {Object} data - Schema data
 * @param {string} data.schema_id - Schema ID (required)
 * @param {string} data.schema_name - Schema name (required)
 * @param {string} data.schema_desc - Schema description (optional)
 * @param {Array} data.entities - Entity definitions (required, non-empty)
 * @param {Array} data.edges - Edge definitions (optional)
 * @param {Object} config - Request configuration
 * @returns {Promise} API response
 */
export function updateGraphSchemaTemplate (data, config = {}) {
  return axios.patch(`${KBASE_BASE}/graph-schemas/${data.schema_id}`, data, {
    headers: {
      'Content-Type': 'application/json',
      ...config.headers
    },
    ...config
  })
}
