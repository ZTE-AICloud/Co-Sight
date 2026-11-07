<template>
  <div class="graph-template-designer" v-loading="loading">
    <!-- Main content area with GraphEditor components -->
    <div class="designer-content">
      <!-- Custom Toolbar -->
      <div class="custom-toolbar">
        <ToolBar
          ref="toolBarRef"
          :template-name="templateMeta.name"
          @undo="handleUndo"
          @redo="handleRedo"
          @zoom-in="handleZoomIn"
          @zoom-out="handleZoomOut"
          @fit-view="handleFitView"
          @set-connection-mode="handleSetConnectionMode"
          @delete="handleDelete"
          @export-json="handleExportJson"
          @go-back="goBack"
        />

        <!-- Right side buttons -->
        <div class="toolbar-actions">
          <el-button type="primary" @click="handleSaveTemplate" :loading="saving">
            {{ proxy.$t('public.save') }}
          </el-button>
        </div>
      </div>

      <!-- Canvas and PropertyPanel layout -->
      <div class="editor-layout">
        <!-- Graph Canvas -->
        <div class="canvas-container">
          <GraphCanvas
            ref="graphCanvasRef"
            @node-select="handleNodeSelect"
            @edge-select="handleEdgeSelect"
            @canvas-click="handleCanvasClick"
            @initialized="handleGraphInitialized"
          />

          <!-- Floating Add Entity Button (centered at bottom) -->
          <div class="floating-add-button">
            <el-button type="primary" @click="handleAddNodeDirectly" size="large" round>
              <el-icon><Plus /></el-icon>
              {{ proxy.$t('modules.kb.addEntity') }}
            </el-button>
          </div>

          <!-- Zoom Controller - 已隐藏，工具栏已有缩放功能 -->
          <!-- <div class="zoom-controller">
            <el-button :disabled="limitZoomIn" @click.stop="handleZoomIn">
              <i class="plx-ico-plus-sign-16 weight-bold" />
            </el-button>
            <el-button :disabled="limitZoomOut" @click.stop="handleZoomOut">
              <i class="plx-ico-minus-sign-16 weight-bold" />
            </el-button>
            <el-button @click.stop="handleFitView">
              <i class="vn-icon-full-screen weight-bold" />
            </el-button>
          </div> -->
        </div>

      </div>
    </div>

    <!-- Property Panel Drawer - 使用与RAG工作流一致的样式 -->
    <el-drawer
      v-model="showPropertyPanel"
      :title="selectionType === 'node' ? proxy.$t('modules.kb.entityConfig') : proxy.$t('modules.kb.relationshipConfig')"
      direction="rtl"
      size="601px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :wrapper-closable="false"
      destroy-on-close
    >
      <template #header>
        <div class="drawer-header">
          <div class="drawer-title">
            {{ selectionType === 'node' ? proxy.$t('modules.kb.entityConfig') : proxy.$t('modules.kb.relationshipConfig') }}
          </div>
        </div>
      </template>
      <PropertyPanel
        v-if="selectedNodeOrEdge"
        ref="propertyPanelRef"
        :selected-item="selectedNodeOrEdge"
        :item-type="selectionType"
        @update-properties="handlePropertiesUpdate"
      />
      <template #footer>
        <div class="drawer-footer">
          <el-button type="primary" @click="handleApplyProperties">
            {{ proxy.$t('public.confirm') }}
          </el-button>
          <el-button plain @click="handleCancelProperties">
            {{ proxy.$t('public.cancel') }}
          </el-button>
        </div>
      </template>
    </el-drawer>

    <!-- Template Info Dialog (仅用于编辑模式) -->
    <el-dialog
      v-model="templateInfoDialogVisible"
      :title="proxy.$t('modules.kb.templateInformation')"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form ref="templateFormRef" :model="templateForm" :rules="templateFormRules" label-width="120px">
        <el-form-item :label="proxy.$t('modules.kb.templateName')" prop="name">
          <el-input
            v-model="templateForm.name"
            :placeholder="proxy.$t('modules.kb.templateNamePlaceholder')"
            maxlength="100"
            show-word-limit
            clearable
          />
        </el-form-item>
        <el-form-item :label="proxy.$t('modules.kb.templateDescription')" prop="description" required>
          <el-input
            v-model="templateForm.description"
            type="textarea"
            :rows="4"
            :placeholder="proxy.$t('modules.kb.templateDescriptionPlaceholder')"
            maxlength="500"
            show-word-limit
            class="textarea-with-limit"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="handleConfirmTemplateInfo">{{ proxy.$t('modules.kb.confirm') }}</el-button>
        <el-button @click="handleCancelTemplateInfo">{{ proxy.$t('modules.kb.cancel') }}</el-button>
      </template>
    </el-dialog>

    <!-- Node Palette Dialog (removed, no longer needed) -->
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, getCurrentInstance, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import GraphCanvas from '@/features/graph/components/GraphEditor/GraphCanvas.vue'
import PropertyPanel from '@/features/graph/components/GraphEditor/PropertyPanel.vue'
import ToolBar from '@/features/graph/components/GraphEditor/ToolBar.vue'
import { createGraphSchemaTemplate, getGraphSchemaTemplateDetail, updateGraphSchemaTemplate } from '@/features/graph/api/knowledgeGraph'
import { generateUUID } from './lib/graph-template-common'
import { getFullCircleVertices } from '@/features/graph/components/GraphEditor/geometry'
import { getGraphPalette } from '@/features/graph/lib/nodeFactory'

const { proxy } = getCurrentInstance() as any

const route = useRoute()
const router = useRouter()

// Template metadata
const templateMeta = reactive({
  id: '',
  name: '',
  description: ''
})

// Graph selection state - using ref for better reactivity
const selectedNodeOrEdge = ref<any>(null)
const selectionType = ref<'node' | 'edge' | null>(null)
const showPropertyPanel = ref(false)

// Graph initialization state
const graphInitialized = ref(false)
const pendingSchemaData = ref<any>(null)

// Component refs
const graphCanvasRef = ref()
const propertyPanelRef = ref()
const toolBarRef = ref()
const templateFormRef = ref()

// Dialog visibility
const templateInfoDialogVisible = ref(false)

// Template form
const templateForm = reactive({
  name: '',
  description: ''
})

// Template form validation rules
const templateFormRules = computed(() => ({
  name: [
    { required: true, message: proxy.$t('modules.kb.pleaseEnterTemplateName'), trigger: 'blur' },
    { min: 1, max: 100, message: proxy.$t('modules.kb.templateNameLengthError'), trigger: 'blur' },
    // 字符集与后端 `SCHEMA_NAME_PATTERN`（`^[a-zA-Z0-9_一-龥]+$`）对齐 ——
    // 弹窗（CreateKnowledgeGraphTemplateDialog）已同步收紧，这里是同一条规则的另一处
    // 入口（名称对话框 / 从弹窗带 query 进来的回填），漏了它用户换个入口又能输 `-`。
    {
      pattern: /^[\w\u4e00-\u9fa5]+$/,
      message: proxy.$t('modules.kb.templateNameCharsError'),
      trigger: ['blur', 'change']
    }
  ],
  description: [
    { required: true, message: proxy.$t('modules.kb.pleaseEnterTemplateDescription'), trigger: ['blur', 'change'] },
    { max: 500, message: proxy.$t('modules.kb.templateDescriptionLengthError'), trigger: 'change' }
  ]
}))

// Saving state
const saving = ref(false)

// Loading state
const loading = ref(false)

// Zoom control state
const limitZoomIn = ref(false)
const limitZoomOut = ref(false)

// Edit mode flag
const isEditMode = ref(false)

/**
 * Initialize from route parameters
 */
async function initFromRoute() {
  const templateId = route.params.templateId as string

  if (templateId && templateId !== 'new') {
    // Edit mode - load existing template
    templateMeta.id = templateId
    isEditMode.value = true
    await loadTemplateData(templateId)
  } else {
    // Create mode - generate new UUID
    templateMeta.id = generateUUID()
    isEditMode.value = false

    // Initialize name and description from query params if provided
    const queryName = route.query.templateName as string
    const queryDesc = route.query.templateDescription as string

    if (queryName) {
      templateMeta.name = queryName
      templateForm.name = queryName
    }

    if (queryDesc) {
      templateMeta.description = queryDesc
      templateForm.description = queryDesc
    }
  }

}

/**
 * Load template data from API
 */
async function loadTemplateData(schemaId: string) {
  try {
    loading.value = true

    const response = await getGraphSchemaTemplateDetail(schemaId)

    if (!response) {
      proxy.$message.error(proxy.$t('modules.kb.loadTemplateFailed'))
      return
    }

    // Update template metadata
    templateMeta.id = response.schema_id
    templateMeta.name = response.schema_name
    templateMeta.description = response.schema_desc || ''

    // Update form data
    templateForm.name = response.schema_name
    templateForm.description = response.schema_desc || ''


    // Convert schema data to graph data and render to canvas
    // Wait for graph to be initialized first
    if (graphInitialized.value) {
      await convertSchemaToGraph(response)
    } else {
      pendingSchemaData.value = response
    }

  } catch (error: any) {
    console.error('Failed to load template data:', error)
    const errorMsg = error.message
      ? `${proxy.$t('modules.kb.loadTemplateFailed')}: ${error.message}`
      : proxy.$t('modules.kb.loadTemplateFailed')
    proxy.$message.error(errorMsg)
  } finally {
    loading.value = false
  }
}

/**
 * Calculate grid layout positions for nodes
 */
function calculateGridLayout(entityCount: number): { cols: number; rows: number; spacingX: number; spacingY: number; marginX: number; marginY: number } {
  const cols = Math.ceil(Math.sqrt(entityCount))
  const rows = Math.ceil(entityCount / cols)
  const spacingX = 200 // Horizontal spacing between nodes
  const spacingY = 150 // Vertical spacing between nodes
  const marginX = 200
  const marginY = 200

  return { cols, rows, spacingX, spacingY, marginX, marginY }
}

/**
 * Calculate position for a node in grid layout
 */
function calculateNodePosition(index: number, cols: number, spacingX: number, spacingY: number, marginX: number, marginY: number): { x: number; y: number } {
  const col = index % cols
  const row = Math.floor(index / cols)
  const x = marginX + col * spacingX
  const y = marginY + row * spacingY
  return { x, y }
}



/**
 * Calculate full circle vertices for self-loop edge
 * 与 GraphCanvas.vue 中的 getFullCircleVertices 逻辑保持一致
 */
/**
 * Create a single node from entity
 */
function createSingleNodeFromEntity(entity: any, index: number, layout: any, entityTypeToNodeId: Map<string, string>): void {
  const { x, y } = calculateNodePosition(index, layout.cols, layout.spacingX, layout.spacingY, layout.marginX, layout.marginY)

  const nodeData = {
    entity_type: entity.entity_type,
    name: entity.entity_type,
    description: entity.entity_desc || '',
    properties: entity.properties || []
  }
  const node = addNodeDirectlyToGraph(x, y, nodeData)

  if (node) {
    entityTypeToNodeId.set(entity.entity_type, node.id)
  } else {
    console.error('Failed to create node for entity:', entity.entity_type)
  }
}

/**
 * Setup self-loop vertices in edge config
 */
function setupSelfLoopVerticesInConfig(edgeConfig: any, sourceNodeId: string, targetNodeId: string, savedVertices?: Array<{ x: number; y: number }>): void {

  if (graphCanvasRef.value?.graph) {
    const graph = graphCanvasRef.value.graph
    const sourceNode = graph.getCellById(sourceNodeId)

    if (sourceNode) {
      // 如果保存的vertices存在，使用保存的；否则重新计算
      if (savedVertices && savedVertices.length > 0) {
        edgeConfig.vertices = savedVertices
      } else {
        // 默认使用左侧端口
        edgeConfig.source = { cell: sourceNodeId, port: 'left' }
        edgeConfig.target = { cell: targetNodeId, port: 'left' }
        edgeConfig.vertices = getFullCircleVertices(sourceNode, 'left')
      }
    } else {
      console.warn('未找到源节点，无法计算vertices')
    }
  } else {
    console.warn('graph对象不存在，无法计算vertices')
  }
}

/**
 * Create edge configuration object
 */
function createEdgeConfig(sourceNodeId: string, targetNodeId: string, edge: any, savedVertices?: Array<{ x: number; y: number }>): any {

  // 判断是否为自闭环：source和target是同一个节点
  const isSelfLoop = sourceNodeId === targetNodeId

  // 如果是自闭环，强制使用 self-loop-edge 形状；否则根据方向确定形状
  let edgeShape = 'single-arrow-edge'
  if (isSelfLoop) {
    edgeShape = 'self-loop-edge'
  } else {
    const direction = edge.direction || 'one-way'
    if (direction === 'two-way') {
      edgeShape = 'double-arrow-edge'
    } else if (direction === 'self-loop') {
      edgeShape = 'self-loop-edge'
    }
  }

  const edgeStroke = getGraphPalette().templateEdgeStroke
  const edgeConfig: any = {
    shape: edgeShape,
    source: { cell: sourceNodeId },
    target: { cell: targetNodeId },
    connector: { name: 'smooth' },
    attrs: {
      line: {
        stroke: edgeStroke,
        strokeWidth: 2,
        fill: 'none',
        strokeLinejoin: 'round',
        strokeLinecap: 'round',
        targetMarker: {
          name: 'classic',
          size: 6,
          fill: edgeStroke,
          stroke: edgeStroke
        }
      }
    },
    data: {
      edge_type: edge.edge_type,
      edge_desc: edge.edge_desc || '',
      direction: edge.direction || 'one-way',
      source_entity: edge.source_entity,
      target_entity: edge.target_entity,
      properties: edge.properties || [],
      // 浅色主题原色：主题切换时 GraphCanvas 用它还原 #0077FF
      lightStroke: '#0077FF'
    }
  }

  // 如果是自闭环，需要添加vertices
  if (isSelfLoop) {
    setupSelfLoopVerticesInConfig(edgeConfig, sourceNodeId, targetNodeId, savedVertices)
  }

  return edgeConfig
}

/**
 * Create nodes from entities
 */
function createNodesFromEntities(entities: any[], entityTypeToNodeId: Map<string, string>): void {
  const layout = calculateGridLayout(entities.length)

  entities.forEach((entity, index) => {
    createSingleNodeFromEntity(entity, index, layout, entityTypeToNodeId)
  })

}

/**
 * Setup self-loop vertices on created graph edge
 */
function setupSelfLoopVerticesOnEdge(graphEdge: any, sourceNodeId: string, targetNodeId: string): void {

  // 使用 graphEdge 的方法获取 graph 对象
  const graph = graphEdge.model?.graph

  if (graph) {
    const sourceNode = graph.getCellById(sourceNodeId)

    if (sourceNode) {
      const vertices = getFullCircleVertices(sourceNode, 'left')

      // 设置source和target端口
      graphEdge.setSource({ cell: sourceNodeId, port: 'left' })
      graphEdge.setTarget({ cell: targetNodeId, port: 'left' })

      // 设置vertices
      graphEdge.setVertices(vertices)
    } else {
      console.warn('未找到源节点')
    }
  } else {
    console.warn('无法通过edge.model.graph获取graph对象')
  }
}

/**
 * Create a single edge from relationship
 */
function createSingleEdgeFromRelationship(edge: any, index: number, entityTypeToNodeId: Map<string, string>): void {

  const sourceNodeId = entityTypeToNodeId.get(edge.source_entity)
  const targetNodeId = entityTypeToNodeId.get(edge.target_entity)

  if (!sourceNodeId || !targetNodeId) {
    console.warn('Source or target node not found for edge:', edge)
    console.warn('Available entity types:', Array.from(entityTypeToNodeId.keys()))
    return
  }


  try {
    // 如果edge是从exportForSchema导出的，可能包含vertices（自闭环需要）
    // 注意：从API返回的schema可能没有vertices，这种情况下会自动计算
    const savedVertices = edge.vertices
    const edgeConfig = createEdgeConfig(sourceNodeId, targetNodeId, edge, savedVertices)

    const graphEdge = graphCanvasRef.value.addEdge(edgeConfig)

    if (graphEdge) {

      // 如果是自闭环，需要手动计算并设置vertices
      if (sourceNodeId === targetNodeId) {
        setupSelfLoopVerticesOnEdge(graphEdge, sourceNodeId, targetNodeId)
      }
    } else {
      console.error('Failed to create edge:', edge)
    }
  } catch (err) {
    console.error('Error creating edge:', err)
  }
}

/**
 * Create edges from schema relationships
 */
function createEdgesFromRelationships(edges: any[], entityTypeToNodeId: Map<string, string>): void {
  if (!edges || edges.length === 0) {
    return
  }

  if (!graphCanvasRef.value) {
    console.error('GraphCanvas ref not available for edge creation')
    return
  }


  edges.forEach((edge: any, index: number) => {
    createSingleEdgeFromRelationship(edge, index, entityTypeToNodeId)
  })
}

/**
 * Convert schema data to graph nodes and edges
 */
async function convertSchemaToGraph(schema: any) {

  if (!graphCanvasRef.value) {
    console.error('Graph canvas ref not available')
    return
  }

  try {
    graphCanvasRef.value.clearCanvas()
    await new Promise(resolve => setTimeout(resolve, 300))

    const { entities, edges } = schema

    if (!entities || entities.length === 0) {
      console.warn('No entities in schema')
      return
    }

    const entityTypeToNodeId = new Map<string, string>()
    createNodesFromEntities(entities, entityTypeToNodeId)

    await new Promise(resolve => setTimeout(resolve, 200))
    createEdgesFromRelationships(edges, entityTypeToNodeId)

  } catch (error: any) {
    console.error('Failed to convert schema to graph:', error)
    console.error('Error stack:', error?.stack)
    throw error
  }
}

/**
 * Add node at specific position using GraphCanvas's addNode method
 */
function addNodeDirectlyToGraph(x: number, y: number, nodeData: any) {
  if (!graphCanvasRef.value) {
    console.error('GraphCanvas ref not available')
    return null
  }

  // Use GraphCanvas's addNode method and manually set position
  const node = graphCanvasRef.value.addNode('entity')

  if (node) {
    // Set position
    node.setPosition(x, y)

    // Update node data
    node.setData(nodeData)

    // Update node label
    node.setAttrs({
      label: {
        text: nodeData.entity_type || nodeData.name || 'Entity'
      }
    })

  }

  return node
}

/**
 * Go back to template list
 */
function goBack() {

  const targetQuery = {
    subTab: 'knowledgeGraphTemplate'
  }

  // 使用 router.replace 而不是 router.push，避免历史记录问题
  // 同时确保参数正确传递
  // 图谱知识库是独立页面（/graph）；subTab 是子页签私有参数。
  const targetPath = '/graph'

  router.replace({
    path: targetPath,
    query: targetQuery
  }).then(() => {

    // 验证参数是否正确传递（只验 subTab）
    if (router.currentRoute.value.query.subTab !== targetQuery.subTab) {
      console.warn('警告：路由参数 subTab 不匹配！期望:', targetQuery.subTab, '实际:', router.currentRoute.value.query.subTab)
    }

  }).catch((error) => {
    console.error('路由跳转失败:', error)
    // 如果路由跳转失败，用 router.resolve 生成完整 href 后整页跳转。
    // 不能直接拼 `targetPath + '?subTab=...'`：本应用是 hash 路由，query 必须落在 `#`
    // 之后才能被路由读到（window.location.search 恒为空）；resolve().href 会按当前
    // history 模式与 BASE_URL 拼出正确形式（hash 模式为 `#/knowledge?tab=...`）。
    window.location.href = router.resolve({ path: targetPath, query: targetQuery }).href
  })
}

/**
 * Handle confirm template info (仅用于编辑模式)
 */
async function handleConfirmTemplateInfo() {
  if (!templateFormRef.value) {
    return
  }

  try {
    await templateFormRef.value.validate()

    // Update template metadata
    templateMeta.name = templateForm.name
    templateMeta.description = templateForm.description

    templateInfoDialogVisible.value = false

    proxy.$message.success(proxy.$t('modules.kb.templateInfoUpdated'))
  } catch (error) {
    console.error('Form validation failed:', error)
  }
}

/**
 * Handle cancel template info dialog (仅用于编辑模式)
 */
function handleCancelTemplateInfo() {
  templateInfoDialogVisible.value = false
}

/**
 * Handle add node directly (without palette dialog)
 * Adds a default entity node to the center of canvas
 */
function handleAddNodeDirectly() {
  if (graphCanvasRef.value) {
    // Add a default entity node (you can customize the node type)
    graphCanvasRef.value.addNode('entity')
  }
}

/**
 * Handle node selection
 */
function handleNodeSelect(node: any) {

  selectionType.value = 'node'
  selectedNodeOrEdge.value = node
  showPropertyPanel.value = true

}

/**
 * Handle edge selection
 */
function handleEdgeSelect(edge: any) {
  selectionType.value = 'edge'
  selectedNodeOrEdge.value = edge
  showPropertyPanel.value = true
}

/**
 * Handle canvas click (deselect)
 */
function handleCanvasClick() {

  selectionType.value = null
  selectedNodeOrEdge.value = null
  showPropertyPanel.value = false

}

/**
 * Handle graph initialized
 */
async function handleGraphInitialized() {
  graphInitialized.value = true

  // Wait a bit to ensure graph is fully ready
  await new Promise(resolve => setTimeout(resolve, 100))

  // If there's pending schema data, load it now
  if (pendingSchemaData.value) {
    await convertSchemaToGraph(pendingSchemaData.value)
    pendingSchemaData.value = null
  }
}

/**
 * Handle properties update from PropertyPanel
 */
function handlePropertiesUpdate(payload: any) {
  if (!graphCanvasRef.value) {
    return
  }

  const { type, id, data } = payload

  if (type === 'node') {
    graphCanvasRef.value.updateNodeProperties(id, data)
  } else if (type === 'edge') {
    graphCanvasRef.value.updateEdgeProperties(id, data)
  }
}

/**
 * Handle apply properties button click
 */
function handleApplyProperties() {
  if (propertyPanelRef.value && propertyPanelRef.value.applyChanges) {
    propertyPanelRef.value.applyChanges()
      .then(() => {
        proxy.$message.success(proxy.$t('modules.kb.configSaved'))
        showPropertyPanel.value = false
      })
      .catch((error: any) => {
        // 错误消息已在 PropertyPanel 中显示，这里只记录日志
        console.error('保存配置失败:', error)
        // 不再显示通用的错误消息，因为 PropertyPanel 已经显示了具体的错误信息
      })
  }
}

/**
 * Handle cancel properties button click
 */
function handleCancelProperties() {
  showPropertyPanel.value = false
}

/**
 * Handle toolbar actions
 */
function handleUndo() {
  graphCanvasRef.value?.undo()
}

function handleRedo() {
  graphCanvasRef.value?.redo()
}

function handleZoomIn() {
  if (graphCanvasRef.value) {
    // 获取当前缩放级别
    const currentZoom = graphCanvasRef.value.graph?.zoom?.() || 1
    if (currentZoom >= 3) {
      limitZoomIn.value = true
      return
    }
    limitZoomIn.value = false
    limitZoomOut.value = false
    graphCanvasRef.value.zoomIn()
  }
}

function handleZoomOut() {
  if (graphCanvasRef.value) {
    // 获取当前缩放级别
    const currentZoom = graphCanvasRef.value.graph?.zoom?.() || 1
    if (currentZoom <= 0.5) {
      limitZoomOut.value = true
      return
    }
    limitZoomIn.value = false
    limitZoomOut.value = false
    graphCanvasRef.value.zoomOut()
  }
}

function handleFitView() {
  limitZoomIn.value = false
  limitZoomOut.value = false
  graphCanvasRef.value?.fitView()
}

function handleSetConnectionMode(mode: 'single' | 'double' | 'self' | null) {
  graphCanvasRef.value?.setConnectionMode(mode)
}

/**
 * Handle delete selected elements
 */
function handleDelete() {

  if (!graphCanvasRef.value) {
    console.error('graphCanvasRef.value is null')
    return
  }

  // 使用 GraphCanvas 暴露的删除方法
  const deletedCount = graphCanvasRef.value.deleteSelectedCells()


  if (deletedCount === 0) {
    proxy.$message.warning(proxy.$t('modules.kb.pleaseSelectElementsToDelete'))
    return
  }

  proxy.$message.success(proxy.$t('modules.kb.elementsDeleted', { count: deletedCount }))
}

/**
 * Handle export JSON
 * 导出数据格式与创建/更新模板时的body格式一致
 */
function handleExportJson() {
  if (!graphCanvasRef.value) {
    proxy.$message.error(proxy.$t('modules.kb.canvasNotInitialized'))
    return
  }

  try {
    // 使用与创建/更新模板相同的格式构建导出数据
    const exportData = buildSchemaFromGraph()

    // 转换为 JSON 字符串
    const jsonString = JSON.stringify(exportData, null, 2)

    // 创建 Blob 对象
    const blob = new Blob([jsonString], { type: 'application/json' })

    // 创建下载链接
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url

    // 设置文件名（使用模板名称，如果没有则使用默认名称）
    const fileName = templateMeta.name
      ? `${templateMeta.name}_${new Date().getTime()}.json`
      : `graph_template_${new Date().getTime()}.json`
    link.download = fileName

    // 触发下载
    document.body.appendChild(link)
    link.click()

    // 清理
    document.body.removeChild(link)
    URL.revokeObjectURL(url)

    proxy.$message.success(proxy.$t('modules.kb.exportJsonSuccess'))
  } catch (error: any) {
    console.error('导出 JSON 失败:', error)
    const errorMsg = error.message
      ? `${proxy.$t('modules.kb.exportJsonFailed')}: ${error.message}`
      : proxy.$t('modules.kb.exportJsonFailed')
    proxy.$message.error(errorMsg)
  }
}

/**
 * Build entities array and node id mapping from nodes
 */
function buildEntitiesAndMapping(nodes: any[]): { entities: any[]; nodeIdToEntityType: Map<string, string> } {
  if (!nodes || nodes.length === 0) {
    throw new Error(proxy.$t('modules.kb.atLeastOneEntityRequired'))
  }

  const nodeIdToEntityType = new Map<string, string>()
  const entities = nodes.map((node: any) => {
    const nodeData = node.data || {}
    const entityType = nodeData.entity_type || nodeData.name || 'Entity'
    const properties = nodeData.properties || []

    if (properties.length === 0) {
      throw new Error(proxy.$t('modules.kb.entityMustHaveProperty', { entityType }))
    }

    nodeIdToEntityType.set(node.id, entityType)
    return {
      entity_type: entityType,
      entity_desc: nodeData.description || '',
      properties: properties.map((prop: any) => ({
        name: prop.name || '',
        type: prop.type || 'STRING',
        desc: prop.desc || '',
        is_embedding: !!prop.is_embedding,
        is_index: !!prop.is_index,
        is_primary: !!prop.is_primary
      }))
    }
  })

  return { entities, nodeIdToEntityType }
}

/**
 * Convert property to schema format
 */
function convertPropertyToSchemaFormat(prop: any): any {
  return {
    name: prop.name || '',
    type: prop.type || 'STRING',
    desc: prop.desc || '',
    is_embedding: !!prop.is_embedding,
    is_index: !!prop.is_index
  }
}

/**
 * Get edge direction from shape
 */
function getEdgeDirection(edge: any, edgeData: any): string {
  if (edge.shape === 'double-arrow-edge') {
    return 'two-way'
  }
  if (edge.shape === 'self-loop-edge') {
    return 'self-loop'
  }
  return edgeData.direction || 'one-way'
}

/**
 * Build edge from graph edge data
 */
function buildEdgeFromGraphEdge(edge: any, nodeIdToEntityType: Map<string, string>): any {
  const edgeData = edge.data || {}
  const sourceEntity = nodeIdToEntityType.get(edge.source?.cell || edge.source)
  const targetEntity = nodeIdToEntityType.get(edge.target?.cell || edge.target)

  if (!sourceEntity || !targetEntity) {
    throw new Error(proxy.$t('modules.kb.edgeSourceOrTargetNotFound'))
  }

  return {
    edge_type: edgeData.edge_type || 'RelatedTo',
    edge_desc: edgeData.edge_desc || '',
    direction: getEdgeDirection(edge, edgeData),
    source_entity: sourceEntity,
    target_entity: targetEntity,
    properties: (edgeData.properties || []).map(convertPropertyToSchemaFormat)
  }
}

/**
 * Build edges array from graph edges
 */
function buildEdgesFromGraphEdges(edges: any[], nodeIdToEntityType: Map<string, string>): any[] {
  return edges?.map((edge: any) => buildEdgeFromGraphEdge(edge, nodeIdToEntityType)) || []
}

/**
 * Build GraphSchemaCreateRequestDTO from canvas data
 */
function buildSchemaFromGraph(): any {
  if (!graphCanvasRef.value) {
    throw new Error(proxy.$t('modules.kb.graphCanvasNotInitialized'))
  }

  const graphData = graphCanvasRef.value.exportForSchema()
  const { nodes, edges } = graphData
  const { entities, nodeIdToEntityType } = buildEntitiesAndMapping(nodes)
  const edgesData = buildEdgesFromGraphEdges(edges, nodeIdToEntityType)

  return {
    schema_id: templateMeta.id,
    schema_name: templateMeta.name,
    schema_desc: templateMeta.description,
    entities,
    edges: edgesData
  }
}

/**
 * Validate entity properties
 */
function validateEntityProperties(entity: any, index: number, errors: string[]): void {
  entity.properties.forEach((prop: any, propIndex: number) => {
    if (!prop.name?.trim()) {
      errors.push(proxy.$t('modules.kb.propertyNameRequiredWithIndex', {
        parentType: 'Entity',
        parentIndex: index + 1,
        propIndex: propIndex + 1
      }))
    }
    if (!prop.type?.trim()) {
      errors.push(proxy.$t('modules.kb.propertyTypeRequiredWithIndex', {
        parentType: 'Entity',
        parentIndex: index + 1,
        propIndex: propIndex + 1
      }))
    }
  })
}

/**
 * Validate entities
 */
function validateEntities(entities: any[], errors: string[]): void {
  if (!entities?.length) {
    errors.push(proxy.$t('modules.kb.atLeastOneEntityRequired'))
    return
  }
  entities.forEach((entity: any, index: number) => {
    if (!entity.entity_type?.trim()) {
      errors.push(proxy.$t('modules.kb.entityTypeRequiredWithIndex', { index: index + 1 }))
    }
    if (!entity.properties?.length) {
      errors.push(proxy.$t('modules.kb.entityPropertyRequiredWithIndex', { index: index + 1 }))
    } else {
      validateEntityProperties(entity, index, errors)
    }
  })
}

/**
 * Validate edge properties
 */
function validateEdgeProperties(edge: any, index: number, errors: string[]): void {
  edge.properties.forEach((prop: any, propIndex: number) => {
    if (!prop.name?.trim()) {
      errors.push(proxy.$t('modules.kb.propertyNameRequiredWithIndex', {
        parentType: 'Edge',
        parentIndex: index + 1,
        propIndex: propIndex + 1
      }))
    }
    if (!prop.type?.trim()) {
      errors.push(proxy.$t('modules.kb.propertyTypeRequiredWithIndex', {
        parentType: 'Edge',
        parentIndex: index + 1,
        propIndex: propIndex + 1
      }))
    }
  })
}

/**
 * Validate edges
 */
function validateEdges(edges: any[], errors: string[]): void {
  if (!edges?.length) {
    return
  }
  edges.forEach((edge: any, index: number) => {
    if (!edge.edge_type?.trim()) {
      errors.push(proxy.$t('modules.kb.edgeTypeRequiredWithIndex', { index: index + 1 }))
    }
    if (!edge.source_entity?.trim()) {
      errors.push(proxy.$t('modules.kb.edgeSourceEntityRequiredWithIndex', { index: index + 1 }))
    }
    if (!edge.target_entity?.trim()) {
      errors.push(proxy.$t('modules.kb.edgeTargetEntityRequiredWithIndex', { index: index + 1 }))
    }
    if (edge.properties?.length) {
      validateEdgeProperties(edge, index, errors)
    }
  })
}

/**
 * Validate schema data before submission
 */
function validateSchema(schema: any): { valid: boolean; errors: string[] } {
  const errors: string[] = []
  if (!schema.schema_name?.trim()) {
    errors.push(proxy.$t('modules.kb.templateNameRequired'))
  }
  validateEntities(schema.entities, errors)
  validateEdges(schema.edges, errors)
  return { valid: errors.length === 0, errors }
}

// 检查模板名称并验证 schema
function checkAndValidateSchema(schema: any): boolean {
  if (!templateMeta.name || templateMeta.name.trim() === '') {
    templateForm.name = templateMeta.name
    templateForm.description = templateMeta.description
    templateInfoDialogVisible.value = true
    proxy.$message.warning(proxy.$t('modules.kb.pleaseEnterTemplateName'))
    return false
  }

  const validation = validateSchema(schema)
  if (!validation.valid) {
    const errorMessage = validation.errors.join('\n')
    proxy.$message.error(`${proxy.$t('modules.kb.schemaValidationFailed')}:\n${errorMessage}`)
    return false
  }
  return true
}

// 调用 API 保存模板
async function saveTemplateApi(schema: any) {

  if (isEditMode.value) {
    const response = await updateGraphSchemaTemplate(schema)
    return response
  } else {
    const response = await createGraphSchemaTemplate(schema)
    return response
  }
}

// 处理保存成功
function handleSaveSuccess(response: any) {
  if (!response) {
    handleSaveFailure()
    return
  }

  const successMsg = isEditMode.value
    ? proxy.$t('modules.kb.graphTemplateUpdateSuccess')
    : proxy.$t('modules.kb.graphTemplateCreateSuccess')
  proxy.$message.success(successMsg)

  // Navigate back to knowledge graph template list page
  setTimeout(() => {
    router.replace({
      path: '/graph',
      query: {
        subTab: 'knowledgeGraphTemplate'
      }
    })
  }, 1000)
}

// 处理保存失败
function handleSaveFailure() {
  const errorMsg = isEditMode.value
    ? proxy.$t('modules.kb.graphTemplateUpdateFailed')
    : proxy.$t('modules.kb.graphTemplateCreateFailed')
  proxy.$message.error(errorMsg)
}

// 处理保存错误
function handleSaveError(error: any) {
  console.error('Failed to save template:', error)

  if (error instanceof Error || error?.message) {
    const errorMessage = error.message || String(error)
    proxy.$message.error(errorMessage)
    return
  }

  const errorMsg = error?.msg || error?.message ||
    (isEditMode.value
      ? proxy.$t('modules.kb.graphTemplateUpdateFailed')
      : proxy.$t('modules.kb.graphTemplateCreateFailed'))

  if (!error?.msg && !error?.message) {
    proxy.$message.error(errorMsg)
  }
}

/**
 * Handle save template button click
 */
async function handleSaveTemplate() {
  try {
    saving.value = true

    const schema = buildSchemaFromGraph()
    if (!checkAndValidateSchema(schema)) {
      saving.value = false
      return
    }

    const response = await saveTemplateApi(schema)
    handleSaveSuccess(response)
  } catch (error: any) {
    handleSaveError(error)
  } finally {
    saving.value = false
  }
}

// Initialize on mount
onMounted(async () => {

  await initFromRoute()
  // 不再自动弹出对话框，因为模板信息已经在列表页面填写完成

})
</script>

<style lang="less" scoped>
.graph-template-designer {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  margin: 0;
  padding: 0;
  background: var(--rs-bg-soft);
  overflow: hidden;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  /* 全屏编辑器要盖住左栏：侧栏里的 promo 卡带 z-index:1，不给根节点
     显式层级时它会从画布下方透出来。 */
  z-index: 100;
  bottom: 0;

  .designer-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-height: 0; // 确保 flex 子元素可以收缩

    .custom-toolbar {
      display: flex;
      align-items: center;
      background: var(--rs-bg-card);
      border-bottom: 0px solid var(--rs-border-soft);
      position: relative;
      flex-shrink: 0; // 工具栏不收缩

      :deep(.toolbar) {
        flex: 1;
      }

      .toolbar-actions {
        position: absolute;
        right: 16px;
        display: flex;
        gap: 12px;
        align-items: center;
      }
    }

    .editor-layout {
      flex: 1;
      display: flex;
      overflow: hidden;
      min-height: 0; // 确保 flex 子元素可以收缩

      .canvas-container {
        flex: 1;
        background: var(--rs-bg-card);
        position: relative;
        min-width: 0; // 确保 flex 子元素可以收缩
        min-height: 0; // 确保 flex 子元素可以收缩

        // 确保 GraphCanvas 组件填充容器
        :deep(.graph-canvas) {
          width: 100%;
          height: 100%;
        }

        :deep(.x6-container) {
          width: 100%;
          height: 100%;
        }

        .floating-add-button {
          position: absolute;
          bottom: 40px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 100;

          .el-button {
            box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
            font-size: 14px;
            padding: 12px 24px;

            &:hover {
              box-shadow: 0 6px 16px rgba(64, 158, 255, 0.4);
              transform: translateY(-2px);
              transition: all 0.3s ease;
            }
          }
        }

        // 缩放控制器样式 - 与RAG工作流一致
        .zoom-controller {
          position: absolute;
          z-index: 5;
          margin: 32px;
          box-shadow: 0 0 2px 1px rgb(0 0 0 / 8%);
          bottom: 0;
          right: 0;
          background: var(--rs-bg-card);
          border-radius: 4px;

          .el-button {
            min-width: 26px;
            border: none;
            padding: 0 5px;

            &+.el-button {
              margin-left: 0;
            }

            & > span {
              min-width: 0 !important;
            }
          }

          .weight-bold {
            font-weight: bold;
          }
        }
      }
    }
  }
}

// 抽屉样式 - 与目标设计对齐
:deep(.el-drawer) {
  .el-drawer__header {
    margin-bottom: 0;
    padding: 16px 24px;
    border-bottom: 1px solid var(--rs-border-soft);
    background-color: var(--rs-bg-card);
  }

  .el-drawer__body {
    padding: 0;
    overflow-y: auto;
    background-color: var(--rs-bg-card);
  }

  .el-drawer__footer {
    padding: 12px 24px;
    border-top: 1px solid var(--rs-border-soft);
    background-color: var(--rs-bg-card);
  }
}

.drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;

  .drawer-title {
    font-size: 16px;
    font-weight: bold;
    color: var(--rs-text);
  }
}

.drawer-footer {
  display: flex;
  justify-content: flex-start;
  gap: 8px;

  // 清除所有按钮的 margin，确保使用 gap 控制间距
  :deep(.el-button),
  :deep(.vn-button) {
    min-width: 80px;
    height: 32px;
    padding: 4px 15px;
    font-size: 14px;
    border-radius: 2px;
    margin: 0 !important;
  }

  // 确保相邻按钮之间没有额外的 margin-left
  :deep(.el-button + .el-button),
  :deep(.vn-button + .vn-button) {
    margin-left: 0 !important;
  }

  :deep(.el-button--primary) {
    background-color: var(--rs-primary);
    border-color: var(--rs-primary);

    &:hover {
      background-color: var(--rs-primary-hover);
      border-color: var(--rs-primary-hover);
    }

    &:active {
      background-color: var(--rs-primary);
      border-color: var(--rs-primary);
    }
  }

  :deep(.el-button--default),
  :deep(.el-button.is-plain) {
    color: var(--rs-text-2);
    border-color: var(--rs-border);
    background-color: var(--rs-bg-card);

    &:hover {
      color: var(--rs-primary-hover);
      border-color: var(--rs-primary-hover);
    }
  }
}

// 修改 textarea 字符计数显示位置，使其显示在输入框下方，避免与内容重叠
:deep(.el-form-item) {
  // 确保表单项容器允许溢出显示
  overflow: visible !important;

  // 为包含 textarea 的表单项添加底部间距
  .vn-textarea,
  .el-textarea {
    position: relative !important;
    margin-bottom: 20px !important; // 为字符计数预留空间
    overflow: visible !important; // 确保字符计数可以显示在容器外

    // 确保 textarea 内部有足够的底部 padding，避免内容与字符计数重叠
    .el-textarea__inner {
      padding-bottom: 25px !important;
    }

    // 字符计数样式 - 使用多种选择器确保覆盖
    .vn-input__count,
    .el-input__count {
      background: var(--rs-bg-card) !important;
      color: var(--rs-text-3) !important;
      font-size: 12px !important;
      line-height: 14px !important;
      position: absolute !important;
      right: 8px !important;
      bottom: -19px !important;
      z-index: 10 !important;
    }
  }

  // 确保 el-input__wrapper 也允许溢出
  .vn-textarea .el-input__wrapper,
  .el-textarea .el-input__wrapper {
    overflow: visible !important;
  }
}

// 全局覆盖 Element Plus 的默认样式（针对 textarea）
:deep(.vn-textarea .vn-input__count),
:deep(.vn-textarea .el-input__count),
:deep(.el-textarea .vn-input__count),
:deep(.el-textarea .el-input__count),
:deep(.el-form-item .el-textarea .el-input__count),
:deep(.el-form-item .vn-textarea .el-input__count) {
  bottom: -19px !important;
  right: 8px !important;
  position: absolute !important;
  background: var(--rs-bg-card) !important;
  color: var(--rs-text-3) !important;
  font-size: 12px !important;
  line-height: 14px !important;
  z-index: 10 !important;
}

// 针对 el-form-item__content 容器
:deep(.el-form-item__content) {
  overflow: visible !important;

  .vn-textarea,
  .el-textarea {
    overflow: visible !important;
  }
}
</style>
