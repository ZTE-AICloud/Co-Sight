/**
 * 知识图谱工具函数
 */

// 可用的实体类型和边类型（假数据）
export const availableEntityTypes = ['Term', 'Product', 'Business', 'Function', 'Concept']
export const availableEdgeTypes = ['Explain', 'Related', 'Contains', 'DependsOn', 'AssociatedWith']

// 实体类型和边类型的属性定义（假数据）
export const entityTypePropertiesMap = {
  Term: {
    name: { label: '名称', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  Product: {
    name: { label: '产品名称', type: 'text' },
    version: { label: '版本', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  Business: {
    name: { label: '业务名称', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  Function: {
    name: { label: '功能名称', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  Concept: {
    name: { label: '概念名称', type: 'text' },
    description: { label: '描述', type: 'text' }
  }
}

export const edgeTypePropertiesMap = {
  Explain: {
    name: { label: '关系名称', type: 'text' },
    description: { label: '描述', type: 'text' },
    explanation_type: { label: '解释类型', type: 'text' }
  },
  Related: {
    name: { label: '关系名称', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  Contains: {
    name: { label: '包含关系', type: 'text' },
    description: { label: '描述', type: 'text' }
  },
  DependsOn: {
    name: { label: '依赖关系', type: 'text' },
    strength: { label: '依赖强度', type: 'text' }
  },
  AssociatedWith: {
    name: { label: '关联名称', type: 'text' },
    association_type: { label: '关联类型', type: 'text' }
  }
}

/**
 * 生成唯一ID
 */
export function generateUniqueId(prefix = '') {
  const timestamp = Date.now()
  return `${prefix}${timestamp}`
}

/**
 * 生成RID
 */
export function generateRid(prefix = '#') {
  const timestamp = Date.now()
  return `${prefix}${timestamp}`
}

/**
 * 格式化时间戳
 */
export function formatTimestamp(timestamp) {
  if (!timestamp) {
    return '--'
  }

  const date = new Date(timestamp)
  if (isNaN(date.getTime())) {
    return '--'
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

/**
 * 计算实体类型颜色映射
 */
export function calculateColorMap(entityTypes) {
  const colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#f9ca24', '#6c5ce7', '#a29bfe', '#fd79a8', '#fdcb6e']
  const map = {}
  entityTypes.forEach((type, index) => {
    map[type] = colors[index % colors.length]
  })
  return map
}

/**
 * 计算边类型颜色映射
 */
export function calculateEdgeColorMap(edgeTypes) {
  const colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e']
  const map = {}
  edgeTypes.forEach((type, index) => {
    map[type] = colors[index % colors.length]
  })
  return map
}

/**
 * 导出知识图谱数据
 */
export function exportGraphData(graphData, nodePositionCache) {
  try {

    // 获取知识图谱名称（从props或使用默认名称）
    const graphName = graphData.schema_name || '知识图谱'

    // 生成时间戳
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)

    // 同步缓存的位置到实体数据（用于导出）
    let entitiesWithCachedPosition = 0
    const entitiesWithPosition = (graphData.entities || []).map(entity => {
      const cachedPosition = nodePositionCache.get(entity.entity_id)
      if (cachedPosition) {
        entitiesWithCachedPosition++
        // 返回包含最新位置的实体副本
        return {
          ...entity,
          x: Math.round(cachedPosition.x),
          y: Math.round(cachedPosition.y)
        }
      }
      // 返回实体副本，保持原有坐标（如果有）
      return { ...entity }
    })


    // 准备导出数据
    const exportData = {
      schema_name: graphName,
      export_time: new Date().toISOString(),
      entities: entitiesWithPosition,
      edges: graphData.edges || [],
      metadata: {
        total_entities: entitiesWithPosition.length,
        total_edges: graphData.edges?.length || 0,
        entities_with_position: entitiesWithCachedPosition,
        export_timestamp: timestamp,
        export_version: '1.0'
      }
    }

    // 验证数据完整性

    // 创建JSON字符串
    const jsonString = JSON.stringify(exportData, null, 2)

    // 创建Blob对象
    const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8' })

    // 创建下载链接
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${graphName}_${timestamp}.json`

    // 触发下载
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // 清理URL对象
    URL.revokeObjectURL(url)


    return true
  } catch (error) {
    console.error('❌ 导出失败:', error)
    throw error
  }
}

/**
 * 释放节点的固定位置（将孤立节点转换为可自由移动的节点）
 */
export function releaseNodeFixedPosition(entityId, nodePositionCache, graphData) {
  if (!entityId) {
    return
  }

  // 从位置缓存中移除
  nodePositionCache.delete(entityId)

  // 从原始数据中移除坐标信息
  const entity = graphData.entities.find(e => e.entity_id === entityId)
  if (entity) {
    delete entity.x
    delete entity.y
  }
}