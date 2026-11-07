/**
 * Schema数据映射工具
 * 将API返回的schemaInfo数据转换为可视化所需的映射关系数据
 */

import { $t } from '@/app/i18n/i18n.js'

/**
 * 将schemaInfo数据映射为可视化所需的格式
 * @param {Object} schemaInfo - API返回的schema数据
 * @returns {Object} 映射后的数据，包含entity_meta和adjacency_map
 */
export function mapSchemaToVisualizationData(schemaInfo) {
  try {

    // 数据验证
    if (!schemaInfo || typeof schemaInfo !== 'object') {
      throw new Error('Invalid schemaInfo: must be an object')
    }

    // 尝试不同的数据结构
    let entities = schemaInfo.entities
    let edges = schemaInfo.edges

    // 如果直接是数组，可能是entities数组
    if (Array.isArray(schemaInfo)) {
      entities = schemaInfo
      edges = []
    }

    // 如果没有entities字段，尝试其他可能的字段名
    if (!entities) {
      entities = schemaInfo.entity_list || schemaInfo.entityTypes || []
    }

    if (!edges) {
      edges = schemaInfo.edge_list || schemaInfo.edgeTypes || schemaInfo.relations || []
    }


    if (!Array.isArray(entities)) {
      console.warn('entities不是数组，使用空数组:', entities)
      entities = []
    }

    if (!Array.isArray(edges)) {
      console.warn('edges不是数组，使用空数组:', edges)
      edges = []
    }

    // 生成entity_meta映射
    const entityMeta = generateEntityMeta(entities)

    // 生成adjacency_map映射
    const adjacencyMap = generateAdjacencyMap(edges, entities)


    return {
      entity_meta: entityMeta,
      adjacency_map: adjacencyMap
    }
  } catch (error) {
    console.error('Schema mapping error:', error)
    throw new Error(`Schema mapping failed: ${error.message}`)
  }
}

/**
 * 生成实体元数据映射
 * @param {Array} entities - 实体数组
 * @returns {Object} 以entity_type为key的实体元数据对象
 */
function generateEntityMeta(entities) {
  const entityMeta = {}

  entities.forEach(entity => {
    if (!entity.entity_type) {
      console.warn('Entity missing entity_type:', entity)
      return
    }

    entityMeta[entity.entity_type] = {
      entity_desc: entity.entity_desc || '',
      properties: entity.properties || []
    }
  })

  return entityMeta
}

/**
 * 生成邻接关系映射
 * @param {Array} edges - 边数组
 * @param {Array} entities - 实体数组
 * @returns {Object} 邻接关系映射对象
 */
function generateAdjacencyMap(edges, entities = []) {
  const adjacencyMap = {}

  // 获取所有实体类型列表
  const entityTypes = entities
    .filter(entity => entity && entity.entity_type)
    .map(entity => entity.entity_type)

  edges.forEach(edge => {
    if (!edge.edge_type) {
      console.warn('Edge missing edge_type field:', edge)
      return
    }

    // 创建边对象
    const edgeObject = {
      edge_type: edge.edge_type,
      edge_desc: edge.edge_desc || '',
      properties: edge.properties || []
    }

    // 检查边是否有 source_entity 和 target_entity 字段
    const hasSourceAndTarget = edge.source_entity && edge.target_entity

    if (hasSourceAndTarget) {
      // 如果边有 source_entity 和 target_entity 字段，按照原来的逻辑处理
      const sourceEntity = edge.source_entity
      const targetEntity = edge.target_entity

      // 初始化源实体的邻接关系
      if (!adjacencyMap[sourceEntity]) {
        adjacencyMap[sourceEntity] = {}
      }

      // 初始化目标实体的邻接关系（如果源实体和目标实体不同）
      if (sourceEntity !== targetEntity) {
        if (!adjacencyMap[targetEntity]) {
          adjacencyMap[targetEntity] = {}
        }
      }

      // 处理源实体到目标实体的关系
      if (!adjacencyMap[sourceEntity][targetEntity]) {
        adjacencyMap[sourceEntity][targetEntity] = []
      }

      // 添加方向信息
      const sourceToTargetEdge = {
        ...edgeObject,
        direction: 'out'
      }
      adjacencyMap[sourceEntity][targetEntity].push(sourceToTargetEdge)

      // 如果源实体和目标实体不同，添加反向关系
      if (sourceEntity !== targetEntity) {
        if (!adjacencyMap[targetEntity][sourceEntity]) {
          adjacencyMap[targetEntity][sourceEntity] = []
        }

        const targetToSourceEdge = {
          ...edgeObject,
          direction: 'in'
        }
        adjacencyMap[targetEntity][sourceEntity].push(targetToSourceEdge)
      }
    } else {
      // 如果边没有 source_entity 和 target_entity 字段，认为任何节点都可以和任何节点连接

      // 为所有实体类型对创建关系映射（包括自己到自己）
      entityTypes.forEach(sourceEntity => {
        // 初始化源实体的邻接关系
        if (!adjacencyMap[sourceEntity]) {
          adjacencyMap[sourceEntity] = {}
        }

        entityTypes.forEach(targetEntity => {
          // 初始化目标实体的邻接关系
          if (!adjacencyMap[targetEntity]) {
            adjacencyMap[targetEntity] = {}
          }

          // 处理源实体到目标实体的关系
          if (!adjacencyMap[sourceEntity][targetEntity]) {
            adjacencyMap[sourceEntity][targetEntity] = []
          }

          // 添加方向信息
          const sourceToTargetEdge = {
            ...edgeObject,
            direction: 'out'
          }
          adjacencyMap[sourceEntity][targetEntity].push(sourceToTargetEdge)

          // 如果源实体和目标实体不同，添加反向关系
          if (sourceEntity !== targetEntity) {
            if (!adjacencyMap[targetEntity][sourceEntity]) {
              adjacencyMap[targetEntity][sourceEntity] = []
            }

            const targetToSourceEdge = {
              ...edgeObject,
              direction: 'in'
            }
            adjacencyMap[targetEntity][sourceEntity].push(targetToSourceEdge)
          }
        })
      })
    }
  })

  return adjacencyMap
}

/**
 * 验证映射后的数据格式
 * @param {Object} mappedData - 映射后的数据
 * @returns {boolean} 验证结果
 */
export function validateMappedData(mappedData) {
  try {
    if (!mappedData || typeof mappedData !== 'object') {
      return false
    }

    if (!mappedData.entity_meta || typeof mappedData.entity_meta !== 'object') {
      return false
    }

    if (!mappedData.adjacency_map || typeof mappedData.adjacency_map !== 'object') {
      return false
    }

    // 验证entity_meta结构
    for (const [entityType, entityData] of Object.entries(mappedData.entity_meta)) {
      if (typeof entityType !== 'string' || typeof entityData !== 'object') {
        return false
      }

      // entity_desc 允许为空字符串
      if (!('entity_desc' in entityData)) {
        return false
      }

      if (!Array.isArray(entityData.properties)) {
        return false
      }
    }

    // 验证adjacency_map结构
    for (const [sourceEntity, targets] of Object.entries(mappedData.adjacency_map)) {
      if (typeof sourceEntity !== 'string' || typeof targets !== 'object') {
        return false
      }

      for (const [targetEntity, edges] of Object.entries(targets)) {
        if (typeof targetEntity !== 'string' || !Array.isArray(edges)) {
          return false
        }
      }
    }

    return true
  } catch (error) {
    console.error('Data validation error:', error)
    return false
  }
}

/**
 * 获取实体类型列表
 * @param {Object} mappedData - 映射后的数据
 * @returns {Array} 实体类型数组
 */
export function getEntityTypes(mappedData) {
  if (!mappedData || !mappedData.entity_meta) {
    return []
  }
  return Object.keys(mappedData.entity_meta)
}

/**
 * 获取指定实体的属性列表
 * @param {Object} mappedData - 映射后的数据
 * @param {string} entityType - 实体类型
 * @returns {Array} 属性数组
 */
export function getEntityProperties(mappedData, entityType) {
  if (!mappedData || !mappedData.entity_meta || !mappedData.entity_meta[entityType]) {
    return []
  }
  return mappedData.entity_meta[entityType].properties || []
}

/**
 * 获取指定实体类型的关系列表
 * @param {Object} mappedData - 映射后的数据
 * @param {string} entityType - 实体类型
 * @returns {Object} 关系映射对象
 */
export function getEntityRelations(mappedData, entityType) {
  if (!mappedData || !mappedData.adjacency_map || !mappedData.adjacency_map[entityType]) {
    return {}
  }
  return mappedData.adjacency_map[entityType]
}

/**
 * 检查两个实体类型之间是否存在关系
 * @param {Object} mappedData - 映射后的数据
 * @param {string} sourceType - 源实体类型
 * @param {string} targetType - 目标实体类型
 * @returns {boolean} 是否存在关系
 */
export function hasRelation(mappedData, sourceType, targetType) {
  if (!mappedData || !mappedData.adjacency_map || !mappedData.adjacency_map[sourceType]) {
    return false
  }
  return mappedData.adjacency_map[sourceType][targetType] &&
         mappedData.adjacency_map[sourceType][targetType].length > 0
}

/**
 * 获取两个实体类型之间的边类型列表
 * @param {Object} mappedData - 映射后的数据
 * @param {string} sourceType - 源实体类型
 * @param {string} targetType - 目标实体类型
 * @returns {Array} 边类型数组
 */
export function getEdgeTypes(mappedData, sourceType, targetType) {
  if (!hasRelation(mappedData, sourceType, targetType)) {
    return []
  }
  return mappedData.adjacency_map[sourceType][targetType].map(edge => edge.edge_type)
}

/**
 * 处理schemaInfo数据，生成映射关系
 * @param {Object} schemaInfoData - schemaInfo数据
 * @returns {Object} 映射后的数据
 */
export function processSchemaInfo(schemaInfoData) {
  try {

    // 使用mapSchemaToVisualizationData进行映射
    const mappedData = mapSchemaToVisualizationData(schemaInfoData)

    // 验证映射结果
    if (!validateMappedData(mappedData)) {
      throw new Error('Schema映射数据验证失败')
    }

    return mappedData

  } catch (error) {
    console.error('processSchemaInfo处理失败:', error)
    throw error
  }
}

/**
 * 验证schemaInfo数据格式
 * @param {Object} schemaInfoData - schemaInfo数据
 * @returns {Object} 验证结果
 */
export function validateSchemaInfo(schemaInfoData) {
  const errors = []
  const warnings = []

  try {
    if (!schemaInfoData) {
      errors.push($t('modules.knowledgeGraphStudio.schemaValidation.empty'))
      return { valid: false, errors, warnings }
    }

    if (!schemaInfoData.entities || !Array.isArray(schemaInfoData.entities)) {
      errors.push($t('modules.knowledgeGraphStudio.schemaValidation.entitiesInvalid'))
    }

    if (!schemaInfoData.edges || !Array.isArray(schemaInfoData.edges)) {
      errors.push($t('modules.knowledgeGraphStudio.schemaValidation.edgesInvalid'))
    }

    // 检查实体数据格式
    if (schemaInfoData.entities) {
      schemaInfoData.entities.forEach((entity, index) => {
        if (!entity.entity_type) {
          errors.push($t('modules.knowledgeGraphStudio.schemaValidation.entityMissingType', { index }))
        }
        if (!entity.properties || !Array.isArray(entity.properties)) {
          warnings.push(`实体${entity.entity_type || index}的properties字段格式可能不正确`)
        }
      })
    }

    // 检查边数据格式
    if (schemaInfoData.edges) {
      schemaInfoData.edges.forEach((edge, index) => {
        if (!edge.edge_type) {
          errors.push($t('modules.knowledgeGraphStudio.schemaValidation.edgeMissingType', { index }))
        }
        // if (!edge.source_entity || !edge.target_entity) {
        //   errors.push(`边${index}缺少source_entity或target_entity字段`)
        // }
      })
    }

    return {
      valid: errors.length === 0,
      errors,
      warnings
    }

  } catch (error) {
    errors.push($t('modules.knowledgeGraphStudio.schemaValidation.processFailed', { message: error.message }))
    return { valid: false, errors, warnings }
  }
}

export default {
  mapSchemaToVisualizationData,
  validateMappedData,
  getEntityTypes,
  getEntityProperties,
  getEntityRelations,
  hasRelation,
  getEdgeTypes,
  processSchemaInfo,
  validateSchemaInfo
}
