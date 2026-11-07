<template>
  <div class="graph-visualization" :class="{ 'is-fullscreen': fullscreen }">
    <!-- 工具条 + 摘要行（全屏时整体收进「查询与操作」浮层） -->
    <div
      class="graph-controls"
      :class="{ 'is-overlay': fullscreen && toolsOpen }"
      :role="fullscreen ? 'region' : undefined"
      :aria-label="fullscreen ? $t('modules.kb.graphFullscreenToolsRegion') : undefined"
      @click.stop
    >
      <GraphControls
        ref="controlsRef"
        :entity-types="availableEntityTypes"
        :edge-types="availableEdgeTypes"
        :selected-entity-types="selectedEntityTypes"
        :selected-edge-types="selectedEdgeTypes"
        :limit-value="limitValue"
        :depth-value="depthValue"
        :search-keyword="props.searchKeyword"
        :total-nodes="totalNodes"
        :total-edges="totalEdges"
        :zoom-level="zoomLevel"
        :entity-type-properties="entityTypePropertiesMap"
        :edge-type-properties="edgeTypePropertiesMap"
        :reset-token="props.resetToken"
        @entity-type-change="handleEntityTypeChange"
        @edge-type-change="handleEdgeTypeChange"
        @limit-change="handleLimitChange"
        @depth-change="handleDepthChange"
        @export="handleExport"
        @search-input="handleSearchInput"
        @search-clear="handleSearchClear"
        @execute-query="handleExecuteQuery"
        @query-type-change="handleQueryTypeChange"
        @advanced-open="closeTools"
        :refresh-graph="handleToolbarRefresh"
        :floating="fullscreen"
      />

      <!-- 摘要行：实体/关系数量 + 显示上限 + 关系名称开关 + 重置布局 -->
      <div class="graph-display-summary text-secondary">
        <div class="graph-display-meta">
          <i18n-t keypath="modules.kb.showingGraph" tag="span">
            <template #nodes><b>{{ totalNodes }}</b></template>
            <template #edges><b>{{ totalEdges }}</b></template>
          </i18n-t>
          <!-- 结果旁常驻「显示上限 N」，点击回到高级查询。 -->
          <el-button link type="primary" class="graph-limit-link" @click="openAdvancedQuery">
            {{ $t('modules.kb.graphDisplayLimit', { limit: limitValue }) }}
          </el-button>
        </div>
        <div class="graph-display-actions">
          <el-checkbox
            :model-value="edgeLabelDisplayMode === 'inline'"
            @change="toggleEdgeLabels"
          >
            {{ $t('modules.kb.relationNames') }}
          </el-checkbox>
          <el-button link @click="resetGraphLayout">
            {{ $t('modules.kb.resetLayout') }}
          </el-button>
          <!-- 添加实体与添加关系并列在摘要行右侧。 -->
          <div class="graph-create-actions" role="group" :aria-label="$t('modules.kb.graphCreateActions')">
            <el-button class="button-compact" type="primary" @click="openCreateDrawer">
              <Plus />{{ $t('modules.kb.createEntity') }}
            </el-button>
            <el-button class="button-compact" @click="openRelationDrawer()">
              <Link />{{ $t('modules.kb.addRelationship') }}
            </el-button>
          </div>
        </div>
        <!-- 截断提示单独占一行：摘要行与右侧操作保持同一行（紧凑浮层的排法）。 -->
        <span v-if="resultHasMore" class="graph-limit-notice text-caption">
          {{ $t('modules.kb.graphLimitNotice', { limit: limitValue }) }}
        </span>
      </div>
    </div>

    <!-- 图表容器 -->
    <div class="graph-container" ref="graphContainer" @click="handleContainerClick">
      <div v-if="!fullscreen" class="graph-canvas-hint text-caption">{{ $t('modules.kb.graphCanvasHint') }}</div>
      <div v-if="fullscreen" class="graph-fullscreen-context text-caption">
        {{ $t('modules.kb.graphFullscreenContext', { name: graphName, nodes: totalNodes, edges: totalEdges, limit: limitValue }) }}
      </div>
      <div class="graph-fullscreen-actions" @click.stop>
        <el-button
          v-if="fullscreen"
          class="button-compact"
          :aria-expanded="toolsOpen"
          @click="toolsOpen = !toolsOpen"
        >
          <Filter />{{ $t('modules.kb.graphFullscreenTools') }}
        </el-button>
        <el-button
          ref="fullscreenButton"
          class="button-compact"
          :aria-label="fullscreen ? $t('modules.kb.graphFullscreenExit') : $t('modules.kb.graphFullscreenView')"
          :title="fullscreen ? $t('modules.kb.graphFullscreenExit') : $t('modules.kb.graphFullscreenView')"
          @click="toggleFullscreen"
        >
          <component :is="fullscreen ? Close : FullScreen" />{{ fullscreen ? $t('modules.kb.graphFullscreenExit') : $t('modules.kb.graphFullscreenView') }}
        </el-button>
      </div>
      <!-- 左下角：缩略图、缩放、图例、连线配置 -->
      <div class="kg-bottom-left">
        <div v-if="thumbnailEnabled" class="kg-thumbnail-panel">
          <svg class="kg-thumbnail-svg" viewBox="0 0 260 150" preserveAspectRatio="none">
            <!-- 整体灰底：视图外节点区域 -->
            <rect class="kg-thumbnail-svg__bg" x="0.5" y="0.5" width="259" height="149" fill="#e8eaef" stroke="#dcdfe6" />
            <!-- 当前主画布视口：白底高亮（无蓝框） -->
            <rect
              v-if="clampedThumbnailViewportRect"
              class="kg-thumbnail-svg__viewport"
              :x="clampedThumbnailViewportRect.x"
              :y="clampedThumbnailViewportRect.y"
              :width="clampedThumbnailViewportRect.width"
              :height="clampedThumbnailViewportRect.height"
              fill="#ffffff"
            />
            <line
              v-for="edge in thumbnailSvgEdges"
              :key="edge.id"
              class="kg-thumbnail-svg__edge"
              :x1="edge.x1"
              :y1="edge.y1"
              :x2="edge.x2"
              :y2="edge.y2"
              stroke="#b0b7c3"
              stroke-width="1"
            />
            <circle
              v-for="node in thumbnailSvgNodes"
              :key="node.id"
              :cx="node.x"
              :cy="node.y"
              r="3"
              :fill="node.color"
            />
          </svg>
        </div>

        <div class="zoom-controls">
          <el-tooltip :content="t('modules.kb.thumbnail')" placement="top">
            <el-button size="small" class="zoom-btn zoom-btn--thumbnail" :class="{ 'is-active': thumbnailEnabled }" @click="toggleThumbnail">
              <img :src="thumbnailEnabled ? ThumbnailIconActive : ThumbnailIcon" alt="thumbnail" />
            </el-button>
          </el-tooltip>
          <div class="zoom-divider"></div>
          <el-tooltip :content="t('modules.kb.zoomOut')" placement="top">
            <el-button @click="zoomOut" size="small" class="zoom-btn">
              <img :src="ZoomInIcon" alt="zoom-out" />
            </el-button>
          </el-tooltip>

          <div class="zoom-select-wrap">
            <button type="button" class="zoom-select-btn" @click.stop="toggleZoomOptions">
              {{ zoomLevel }}%
            </button>
            <div v-show="zoomOptionsVisible" class="zoom-options">
              <button
                v-for="option in zoomPresetOptions"
                :key="option"
                type="button"
                class="zoom-option-btn"
                @click.stop="setZoomByPercent(option)"
              >
                {{ option }}%
              </button>
            </div>
          </div>

          <el-tooltip :content="t('modules.kb.zoomIn')" placement="top">
            <el-button @click="zoomIn" size="small" class="zoom-btn">
              <img :src="ZoomOutIcon" alt="zoom-in" />
            </el-button>
          </el-tooltip>
          <div class="zoom-divider"></div>
          <el-tooltip :content="t('modules.kb.reset')" placement="top">
            <el-button @click="resetZoom" size="small" class="zoom-btn">
              <img :src="ZoomResetIcon" alt="reset" />
            </el-button>
          </el-tooltip>
          <el-tooltip :content="t('modules.kb.center')" placement="top">
            <el-button @click="centerGraph" size="small" class="zoom-btn">
              <img :src="CenteredIcon" alt="center" />
            </el-button>
          </el-tooltip>
          <el-tooltip :content="t('modules.kb.fullScreen')" placement="top">
            <el-button size="small" class="zoom-btn" @click="fitView">
              <img :src="FullScreenIcon" alt="fullscreen" />
            </el-button>
          </el-tooltip>
          <div class="zoom-divider"></div>
          <el-tooltip :content="t('modules.kb.legend')" placement="top">
            <el-button size="small" class="zoom-btn" :class="{ 'is-active': legendVisible }" @click="toggleLegend">
              <img :src="legendVisible ? LegendIconActive : LegendIcon" alt="legend" />
            </el-button>
          </el-tooltip>
          <div class="line-config-wrap">
            <el-tooltip :content="t('modules.kb.lineConfig')" placement="top">
              <el-button
                size="small"
                class="zoom-btn"
                :class="{ 'is-active': lineModeOptionsVisible || edgeLabelDisplayMode === 'hover' }"
                @click.stop="toggleLineModeOptions"
              >
                <img :src="(lineModeOptionsVisible || edgeLabelDisplayMode === 'hover') ? AssemblyIpipelineIconActive : AssemblyIpipelineIcon" alt="line-config" />
              </el-button>
            </el-tooltip>
            <div v-show="lineModeOptionsVisible" class="line-mode-options" @click.stop>
              <el-radio-group v-model="edgeLabelDisplayMode" @change="handleEdgeLabelModeChange">
                <el-radio label="inline" value="inline">{{ t('modules.kb.edgeLabelInline') }}</el-radio>
                <el-radio label="hover" value="hover">{{ t('modules.kb.edgeLabelHover') }}</el-radio>
              </el-radio-group>
            </div>
          </div>
        </div>
      </div>

      <!-- 左下角图例（仅实体类型、颜色、数量）；全屏时隐藏 -->
      <div v-show="legendVisible && !fullscreen" class="legend">
        <div class="legend-header">
          <div class="legend-title">{{ t('modules.kb.entityTypes') }}</div>
          <button type="button" class="legend-close-btn" @click="legendVisible = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>
        <div v-for="item in entityLegendItems" :key="item.type" class="legend-item">
          <div class="legend-color" :style="{ background: item.color }"></div>
          <span>{{ item.type }}（{{ item.count }}）</span>
        </div>
      </div>

      <!-- 图谱画布：vis-network -->
      <div class="graph-vis-wrapper">
        <GraphCanvasVis
          ref="graphCanvasRef"
          :graph-data="graphDataCache"
          :color-map="colorMap"
          :edge-color-map="edgeColorMap"
          :graph-id="String(route.params?.id || '')"
          :reset-token="props.resetToken"
          :persistently-hidden-node-ids="persistentlyHiddenNodeIdsList"
          :entity-expand-state-map="entityExpandStateForCanvas"
          :edge-label-display-mode="edgeLabelDisplayMode"
          @node-click="handleNodeClickFromCanvas"
          @edge-click="handleEdgeClickFromCanvas"
          @container-click="handleContainerClickFromCanvas"
          @zoom-change="onVisZoomChange"
          @node-double-click="handleNodeDoubleClickFromCanvas"
          @edge-double-click="handleEdgeDoubleClickFromCanvas"
          @toggle-expand="handleToggleExpandFromCanvas"
          @after-drawing="handleCanvasAfterDrawing"
        />
      </div>

      <!-- 操作气泡卡片 - 点击触发 -->
      <div
        v-show="actionPopoverVisible && selectedEntity"
        class="action-popover"
        :style="{ left: actionPopoverPosition.x + 'px', top: actionPopoverPosition.y + 'px' }"
      >
        <el-tooltip :content="t('modules.kb.edit')" placement="top">
          <div class="action-btn" @click="handleEdit">
            <el-icon><Edit /></el-icon>
          </div>
        </el-tooltip>
        <el-tooltip :content="t('modules.kb.delete')" placement="top">
          <div class="action-btn" @click="handleDeleteNode">
            <el-icon><Delete /></el-icon>
          </div>
        </el-tooltip>
        <el-tooltip :content="t('modules.kb.addRelationship')" placement="top">
          <div class="action-btn" @click="handleAddEdge">
            <el-icon><Link /></el-icon>
          </div>
        </el-tooltip>
      </div>

      <!-- 边的操作气泡卡片 -->
      <div
        v-show="edgeActionPopoverVisible && selectedEdge"
        class="action-popover"
        :style="{ left: edgeActionPopoverPosition.x + 'px', top: edgeActionPopoverPosition.y + 'px' }"
      >
        <el-tooltip :content="t('modules.kb.edit')" placement="top">
          <div class="action-btn" @click="handleEditEdge">
            <el-icon><Edit /></el-icon>
          </div>
        </el-tooltip>
        <el-tooltip :content="t('modules.kb.delete')" placement="top">
          <div class="action-btn" @click="handleDeleteEdge">
            <el-icon><Delete /></el-icon>
          </div>
        </el-tooltip>
      </div>
    </div>

    <!-- 画布下方常驻实体类型图例（全屏时隐藏） -->
    <div v-if="!fullscreen" class="graph-legend-row text-caption" :aria-label="t('modules.kb.entityTypes')">
      <span v-for="item in entityLegendItems" :key="item.type">
        <i :style="{ background: item.color }" />{{ item.type }}
      </span>
    </div>

    <!-- 实体编辑抽屉：双击节点或气泡「编辑」打开 -->
    <GraphEntityDrawer
      v-model="editDrawerVisible"
      :entity="selectedEntity"
      :entity-type="selectedEntityTypeInfo"
      :property-defs="selectedEntityPropertyDefs"
      :relations="selectedEntityRelations"
      :saving="entityDrawerSaving"
      @save="handleEntityDrawerSave"
      @select="handleEntityDrawerSelect"
      @locate="handleEntityDrawerLocate"
      @add-relation="openRelationDrawer(selectedEntity)"
    />

    <!-- 新增实体抽屉：工具栏主按钮打开，不依赖选中节点 -->
    <GraphEntityCreateDrawer
      v-model="createDrawerVisible"
      :graph-name="graphName"
      :entity-types="availableEntityTypes"
      :type-tones="typeToneMap"
      :entities="graphDataCache.entities"
      :property-defs="createEntityPropertyDefs"
      :edge-types-for="getAvailableEdgeTypesForEntities"
      :saving="createEntitySaving"
      @create="handleCreateEntity"
    />

    <!-- 添加关系抽屉：摘要行、节点气泡与画布连线模式共用 -->
    <GraphRelationCreateDrawer
      v-model="relationDrawerVisible"
      :source-id="relationSourceId"
      :target-id="relationTargetId"
      :nodes="graphDataCache.entities"
      :edges="graphDataCache.edges"
      :type-tones="typeToneMap"
      :edge-types-for="getAvailableEdgeTypesForEntities"
      :saving="relationSaving"
      @save="handleRelationSave"
    />

    <!-- 查看抽屉 -->
    <el-drawer
      v-model="edgeDrawerVisible"
      :title="selectedEdge?.edge_id || selectedEdge?.id || t('modules.kb.relationshipDetails')"
      direction="rtl"
      size="450px"
    >
      <el-collapse v-model="edgeActiveCollapse" type="ghost">
        <el-collapse-item :title="t('modules.kb.basicInfo')" name="basic">
          <div class="drawer-section">
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.relationshipId') }}：</span>
              <span class="drawer-value">{{ selectedEdge?.edge_id || selectedEdge?.id }}</span>
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.relationshipType') }}：</span>
              <span class="drawer-value">{{ selectedEdge?.edge_type || selectedEdge?.class }}</span>
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.sourceNodeId') }}：</span>
              <span class="drawer-value">{{ selectedEdge?.source_id }}</span>
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.targetNodeId') }}：</span>
              <span class="drawer-value">{{ selectedEdge?.target_id }}</span>
            </div>
          </div>
        </el-collapse-item>

        <el-collapse-item :title="t('modules.kb.propertyInfo')" name="properties">
          <div class="drawer-section">
            <div v-if="selectedEdge?.properties && Object.keys(selectedEdge.properties).length > 0">
              <div v-for="(value, key) in selectedEdge.properties" :key="key" class="drawer-item">
                <span class="drawer-label">{{ key }}：</span>
                <span class="drawer-value">{{ value }}</span>
              </div>
            </div>
            <div v-else class="empty-hint">
              {{ t('modules.kb.noPropertyInfo') }}
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="handleCloseEdgeDrawer">{{ t('modules.kb.close') }}</el-button>
        </div>
      </template>
    </el-drawer>

    <!-- 边的编辑抽屉 -->
    <el-drawer
      v-model="edgeEditDrawerVisible"
      :title="t('modules.kb.editRelationship', { name: selectedEdge?.edge_id || selectedEdge?.id || t('modules.kb.relationshipType') })"
      :modal="false"
      direction="rtl"
      size="450px"
    >
      <el-collapse v-model="edgeEditActiveCollapse" type="ghost">
        <el-collapse-item :title="t('modules.kb.basicInfo')" name="basic">
          <div class="drawer-section">
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.relationshipId') }}：</span>
              <el-input
                v-model="edgeEditForm.edge_id"
                disabled
                :placeholder="t('modules.kb.relationshipIdPlaceholder')"
                size="small"
              />
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.relationshipType') }}：</span>
              <el-input
                v-model="edgeEditForm.class"
                disabled
                :placeholder="t('modules.kb.relationshipTypePlaceholder')"
                size="small"
              />
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.sourceNodeId') }}：</span>
              <el-input
                v-model="edgeEditForm.source_id"
                disabled
                :placeholder="t('modules.kb.sourceNodeIdPlaceholder')"
                size="small"
              />
            </div>
            <div class="drawer-item">
              <span class="drawer-label">{{ t('modules.kb.targetNodeId') }}：</span>
              <el-input
                v-model="edgeEditForm.target_id"
                disabled
                :placeholder="t('modules.kb.targetNodeIdPlaceholder')"
                size="small"
              />
            </div>
          </div>
        </el-collapse-item>

        <el-collapse-item :title="t('modules.kb.relationshipPropertyInfo')" name="properties">
          <div class="drawer-section">
            <div v-if="edgeEditForm.properties && Object.keys(edgeEditForm.properties).length > 0">
              <div v-for="(value, key) in edgeEditForm.properties" :key="key" class="drawer-item">
                <span class="drawer-label">{{ key }}：</span>
                <template v-if="getEdgePropertyDef(edgeEditForm.class, key)?.type === 'BOOLEAN'">
                  <el-select
                    v-model="edgeEditForm.properties[key]"
                    size="small"
                    clearable
                    class="boolean-select"
                    :placeholder="t('modules.kb.inputPlaceholder')"
                  >
                    <el-option label="true" value="true" />
                    <el-option label="false" value="false" />
                  </el-select>
                </template>
                <el-input
                  v-else
                  v-model="edgeEditForm.properties[key]"
                  :placeholder="t('modules.kb.inputPlaceholder')"
                  clearable
                  size="small"
                />
              </div>
            </div>
            <div v-else class="empty-hint">
              {{ t('modules.kb.noPropertyInfo') }}
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <template #footer>
        <div class="drawer-footer">
          <el-button type="primary" @click="handleConfirmEditEdge">{{ t('modules.kb.confirm') }}</el-button>
          <el-button @click="handleCancelEditEdge">{{ t('modules.kb.cancel') }}</el-button>
        </div>
      </template>
    </el-drawer>

  </div>
</template>

<script setup>
/**
 * 知识图谱可视化组件
 * 画布由 GraphCanvasVis（vis-network）渲染，graphDataCache 与父组件数据保持同步。
 */

import { ref, onMounted, onBeforeUnmount, computed, watch, nextTick, getCurrentInstance } from 'vue'
import { Edit, Delete, Link, Close, Plus, FullScreen, Filter } from '@element-plus/icons-vue'


import ZoomInIcon from '@/assets/zoom-in-16.svg'
import ZoomOutIcon from '@/assets/zoom-out-16.svg'
import ZoomResetIcon from '@/assets/fonts/zoom-reset-16.svg'
import CenteredIcon from '@/assets/fonts/centered-16.svg'
import FullScreenIcon from '@/assets/fonts/full-screen-16.svg'
import ThumbnailIcon from '@/assets/thumbnail.svg'
import ThumbnailIconActive from '@/assets/thumbnail-active.svg'
import LegendIcon from '@/assets/legend-16.svg'
import LegendIconActive from '@/assets/legend-16-active.svg'
import AssemblyIpipelineIcon from '@/assets/assembly-ipipeline-16.svg'
import AssemblyIpipelineIconActive from '@/assets/assembly-ipipeline-16-active.svg'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { updateEntityApi, updateEdgeApi, deleteEntityApi, deleteEdgeApi, createEntityApi, createEdgeApi } from '@/features/graph/api/knowledgeGraph'
import { edgeLabelText } from '@/features/graph/lib/edge-label'
import GraphControls from './GraphControls.vue'
import GraphCanvasVis from './GraphCanvasVis.vue'
import GraphEntityDrawer from './GraphEntityDrawer.vue'
import GraphEntityCreateDrawer from './GraphEntityCreateDrawer.vue'
import GraphRelationCreateDrawer from './GraphRelationCreateDrawer.vue'
import { theme } from '@/shared/lib/theme'
import {
  assignEntityTones,
  ENTITY_TONE_FALLBACKS,
  ENTITY_TONE_SEQUENCE,
  ENTITY_TONE_TOKENS
} from '../lib/entity-tones'
import { resolveFullscreenEscape } from '../lib/graph-fullscreen'


// 国际化
const { t } = useI18n()

const props = defineProps({
  graphData: {
    type: Object,
    required: true,
    default: () => ({
      entities: [],
      edges: []
    })
  },
  entityTypes: {
    type: Array,
    default: () => []
  },
  edgeTypes: {
    type: Array,
    default: () => []
  },
  selectedEntityTypes: {
    type: Array,
    default: () => []
  },
  selectedEdgeTypes: {
    type: Array,
    default: () => []
  },
  limitValue: {
    type: Number,
    default: 100
  },
  depthValue: {
    type: Number,
    default: 10
  },
  schemaMapping: {
    type: Object,
    default: () => ({
      entity_meta: {},
      adjacency_map: {}
    })
  },
  searchKeyword: {
    type: String,
    default: ''
  },
  isManualQuery: {
    type: Boolean,
    default: false
  },
  lastQueryPayload: {
    type: Object,
    default: null
  },
  resetToken: {
    type: Number,
    default: 0
  },
  /** 图谱名称（新增实体抽屉副标题）。 */
  graphName: {
    type: String,
    default: ''
  },
  /** 详情页注入的「刷新知识图谱」实现；未注入时退回服务端刷新事件。 */
  refreshGraph: {
    type: Function,
    default: null
  },
  /** 后端 has_more —— 当前结果可能已被 Limit 截断。 */
  resultHasMore: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'refresh-graph-data',
  'entity-type-change',
  'edge-type-change',
  'limit-change',
  'depth-change',
  'export',
  'search-clear',
  'execute-query',
  'query-type-change',
  'fullscreen-change'
])

// 路由
const route = useRoute()

// 获取实例
const { proxy } = getCurrentInstance()


function requestServerRefresh (payload = {}) {
  emit('refresh-graph-data', { refreshFromServer: true, ...payload })
}

/**
 * 图谱相关接口成功判定：
 * - 仅在明确返回失败时视为失败（success === false）
 * - API 2.0 的成功响应不带 success 字段，按成功处理
 */
function isGraphApiSuccess (response) {
  if (!response) {
    return false
  }
  if (response.success === false) {
    return false
  }
  return true
}

/** 新建关系成功后，用返回值保证即使查询被 limit 截断也能看到新边。 */
function buildEnsureEdgePayload (relation) {
  if (!relation?.edgeId || !relation?.edgeType || !relation?.sourceId || !relation?.targetId) {
    return []
  }
  return [{
    edge_id: relation.edgeId,
    edge_type: relation.edgeType,
    source_id: relation.sourceId,
    target_id: relation.targetId,
    properties: relation.properties || {}
  }]
}

/**
 * 本地画布实体数超过当前查询 limit 时，先提高 limit 再请求服务端，
 * 避免「已满 limit 条」时再增实体，刷新仍按旧 limit 截断导致新实体丢失。
 */
function bumpLimitFromLocalEntityCount () {
  const count = graphDataCache.value.entities?.length ?? 0
  const limit = Number(props.limitValue)
  const safeLimit = Number.isFinite(limit) ? limit : 0
  if (count > safeLimit) {
    emit('limit-change', count)
  }
}


function stopGraphLoading () {
  emit('refresh-graph-data', { stopLoading: true })
}


// 控制状态
const actionPopoverVisible = ref(false)
const selectedEntity = ref(null)
const zoomLevel = ref(100)
const zoomPresetOptions = [25, 50, 75, 100, 200]
const zoomOptionsVisible = ref(false)
const legendVisible = ref(false)
const lineModeOptionsVisible = ref(false)
const thumbnailEnabled = ref(false)
const thumbnailSvgNodes = ref([])
const thumbnailSvgEdges = ref([])
const thumbnailViewportRect = ref(null)

/** 缩略图尺寸（与 viewBox 一致），视口矩形裁剪在画布内 */
const THUMBNAIL_SVG_W = 260
const THUMBNAIL_SVG_H = 150

/** 将视口矩形限制在缩略图范围内，供白底高亮使用 */
const clampedThumbnailViewportRect = computed(() => {
  const v = thumbnailViewportRect.value
  if (!v) {
    return null
  }
  let x = Number(v.x)
  let y = Number(v.y)
  let w = Number(v.width)
  let h = Number(v.height)
  if (![x, y, w, h].every(Number.isFinite)) {
    return null
  }
  x = Math.max(0, x)
  y = Math.max(0, y)
  w = Math.max(0, w)
  h = Math.max(0, h)
  if (x >= THUMBNAIL_SVG_W || y >= THUMBNAIL_SVG_H) {
    return null
  }
  w = Math.min(w, THUMBNAIL_SVG_W - x)
  h = Math.min(h, THUMBNAIL_SVG_H - y)
  if (w < 1 || h < 1) {
    return null
  }
  return { x, y, width: w, height: h }
})

// 「关系名称」默认不勾选（悬浮边时才看标签）
const edgeLabelDisplayMode = ref('hover')
let thumbnailRefreshTimer = null
const actionPopoverPosition = ref({ x: 0, y: 0 })
const editDrawerVisible = ref(false)

// 搜索相关状态
const isSearchMode = ref(false)

// Vis 画布单击延迟（避免双击时第二次点击时气泡挡住，导致无法触发双击编辑）
const nodeClickDelayTimer = ref(null)
const edgeClickDelayTimer = ref(null)
const CLICK_DELAY_MS = 280

// 实体展开/收起状态管理
const entityExpandState = ref(new Map()) // 存储实体的展开/收起状态：key=entityId, value=isExpanded
/** 持久隐藏的节点 id（统一为 string，与 vis DataSet id 比对时一致） */
const hiddenNodeIds = ref(new Set())

/** 供 GraphCanvasVis 与 hiddenNodeIds 同步（Set 整体替换后触发更新） */
const persistentlyHiddenNodeIdsList = computed(() => [...hiddenNodeIds.value])

/** 供画布节点右上角展开/收起图标与 entityExpandState 同步 */
const entityExpandStateForCanvas = computed(() => {
  const m = {}
  entityExpandState.value.forEach((v, k) => {
    m[String(k)] = v !== false
  })
  return m
})

// 边相关状态
const selectedEdge = ref(null)
const edgeActionPopoverVisible = ref(false)
const edgeActionPopoverPosition = ref({ x: 0, y: 0 })
const edgeDrawerVisible = ref(false)
const edgeEditDrawerVisible = ref(false)
const edgeActiveCollapse = ref(['basic', 'properties'])
const edgeEditActiveCollapse = ref(['basic', 'properties'])
const edgeEditForm = ref({
  edge_id: '',
  class: '',
  rid: '',
  source_id: '',
  target_id: '',
  in: '',
  out: '',
  properties: {}
})

// 添加关系相关状态（抽屉内自选起点/终点）
const relationDrawerVisible = ref(false)
const relationSourceId = ref('')
const relationTargetId = ref('')
const relationSaving = ref(false)

const drawerVisibilityMap = {
  entityEdit: editDrawerVisible,
  edgeView: edgeDrawerVisible,
  edgeEdit: edgeEditDrawerVisible
}

function openExclusiveDrawer (targetDrawerKey) {
  Object.entries(drawerVisibilityMap).forEach(([drawerKey, drawerRef]) => {
    drawerRef.value = drawerKey === targetDrawerKey
  })
  relationDrawerVisible.value = false
}

// 添加边交互模式相关状态
const isAddingEdgeMode = ref(false) // 是否处于添加边模式
const connectableNodes = ref([]) // 可连接的节点列表
const sourceNodeForEdge = ref(null) // 起始节点
const targetNodeForEdge = ref(null) // 目标节点

// 批量更新标志（防止 watch 重复触发）

// 可用的实体类型和边类型
// 使用从父组件传递过来的props
const availableEntityTypes = computed(() => props.entityTypes || [])
const availableEdgeTypes = computed(() => props.edgeTypes || [])

const entityTypePropertiesMap = computed(() => {
  const entityMeta = props.schemaMapping?.entity_meta || {}
  const result = {}
  Object.keys(entityMeta).forEach(type => {
    result[type] = entityMeta[type]?.properties || []
  })
  return result
})

const edgeTypePropertiesMap = computed(() => {
  const adjacencyMap = props.schemaMapping?.adjacency_map || {}
  const result = {}
  Object.values(adjacencyMap).forEach(targetMap => {
    if (!targetMap) {
      return
    }
    Object.values(targetMap).forEach(edges => {
      if (!Array.isArray(edges)) {
        return
      }
      edges.forEach(edge => {
        if (!edge || !edge.edge_type) {
          return
        }
        const existing = result[edge.edge_type] || []
        const newProps = Array.isArray(edge.properties) ? edge.properties : []
        const merged = [...existing]
        newProps.forEach(prop => {
          const propName = prop?.property_name || prop?.name || prop?.code || prop?.prop
          if (!propName) {
            merged.push(prop)
            return
          }
          if (!merged.find(item => (item?.property_name || item?.name || item?.code || item?.prop) === propName)) {
            merged.push(prop)
          }
        })
        result[edge.edge_type] = merged
      })
    })
  })
  return result
})

// 图表引用
const graphContainer = ref(null)
const graphCanvasRef = ref(null)
const controlsRef = ref(null)

/* ── 窗口内沉浸画布（不调用浏览器原生全屏） ───────────────────────── */
const fullscreen = ref(false)
const toolsOpen = ref(false)
const fullscreenButton = ref(null)

function closeTools () {
  toolsOpen.value = false
}

function toggleFullscreen () {
  // 进出全屏按当前页面尺寸重排节点坐标并重新居中。
  // 只平移相机会让节点在大画布上仍挤在中间；
  // 这里让子组件回到基准布局再按新画布收拢 / 撑开。
  fullscreen.value = !fullscreen.value
  closeTools()
  emit('fullscreen-change', fullscreen.value)
  nextTick(() => {
    graphCanvasRef.value?.relayoutForViewport?.()
    fullscreenButton.value?.$el?.focus?.()
  })
}

function exitFullscreen () {
  if (fullscreen.value) {
    toggleFullscreen()
  }
}

/** 摘要行「显示上限」：打开高级查询抽屉，同时收起操作浮层。 */
function openAdvancedQuery () {
  closeTools()
  controlsRef.value?.openAdvanced()
}

/**
 * Esc 优先级：先让已打开的抽屉 / 弹窗自己关闭，
 * 再收起「查询与操作」浮层，最后退出沉浸画布。
 */
function handleFullscreenKey (event) {
  if (event.key !== 'Escape' || event.defaultPrevented) {
    return
  }
  const overlayOpen = [...document.querySelectorAll('.el-drawer,.el-dialog,.el-message-box,.el-select__popper')]
    .some(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
  const action = resolveFullscreenEscape({ fullscreen: fullscreen.value, toolsOpen: toolsOpen.value, overlayOpen })
  if (action === 'close-tools') {
    closeTools()
  } else if (action === 'exit') {
    toggleFullscreen()
  }
}

// Schema映射相关变量



// 增量更新方案：本地缓存和操作队列
// 本地缓存的图谱数据（用于增量更新）
const graphDataCache = ref({
  entities: [],
  edges: []
})

// 操作队列（存储待提交的操作）
const operationQueue = ref([])

// 批量处理状态（用于防止在批量处理时触发重新渲染）
const isBatchProcessing = ref(false)

// 操作类型定义
const OperationType = {
  ADD_ENTITY: 'addEntity',
  EDIT_ENTITY: 'editEntity',
  DELETE_ENTITY: 'deleteEntity',
  ADD_EDGE: 'addEdge',
  EDIT_EDGE: 'editEdge',
  DELETE_EDGE: 'deleteEdge'
}


// 计算属性：与画布 group 一致，使用 entity_type || class / edge_type || class
const entityTypes = computed(() => {
  const types = new Set()
  props.graphData.entities?.forEach(entity => {
    const t = entity.entity_type || entity.class
    if (t) {
      types.add(t)
    }
  })
  return Array.from(types)
})

const edgeTypes = computed(() => {
  const types = new Set()
  props.graphData.edges?.forEach(edge => {
    const t = edge.edge_type || edge.class
    if (t) {
      types.add(t)
    }
  })
  return Array.from(types)
})

// 实体类型配色：--rs-tone-* 五个语义色按模板实体类型顺序轮转。
// 类型 → tone 名由 lib/entity-tones 统一分配（画布 / 图例 / 基本信息页共用）。
// canvas 不解析 CSS 变量，所以色值在主题切换时重新读取令牌的实际值。
function readToneColor (token, fallback) {
  if (typeof document === 'undefined' || !document.documentElement) {
    return fallback
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim()
  return value || fallback
}

const typeToneMap = computed(() => assignEntityTones(
  props.entityTypes && props.entityTypes.length ? props.entityTypes : [],
  entityTypes.value
))

const tonePalette = computed(() => {
  // 主题切换 → theme 变化 → 重新读取令牌（浅色 #8045ff / 深色 #bb9aff）
  void theme.value
  const palette = {}
  ENTITY_TONE_SEQUENCE.forEach((tone) => {
    palette[tone] = readToneColor(ENTITY_TONE_TOKENS[tone], ENTITY_TONE_FALLBACKS[tone])
  })
  return palette
})

// 图例与画布颜色一致：type → tone → 当前主题的实际色值
const colorMap = computed(() => {
  const map = {}
  Object.keys(typeToneMap.value).forEach((type) => {
    map[type] = tonePalette.value[typeToneMap.value[type]]
  })
  return map
})

/* ── 实体编辑抽屉 ──────────────────────────────────────────── */
const entityDrawerSaving = ref(false)

function entityKey (entity) {
  return entity?.entity_id ?? entity?.id
}

const selectedEntityTypeName = computed(() =>
  selectedEntity.value?.entity_type || selectedEntity.value?.class || ''
)

const selectedEntityTypeInfo = computed(() => ({
  name: selectedEntityTypeName.value || t('modules.kb.entityType'),
  tone: typeToneMap.value[selectedEntityTypeName.value] || 'blue'
}))

const selectedEntityPropertyDefs = computed(() => {
  const meta = props.schemaMapping?.entity_meta || {}
  const type = selectedEntityTypeName.value
  let list = meta[type]?.properties
  if (!list && type) {
    const matched = Object.keys(meta).find((key) => String(key).toLowerCase() === String(type).toLowerCase())
    list = matched ? meta[matched]?.properties : []
  }
  const defs = {}
  ;(Array.isArray(list) ? list : []).forEach((def) => {
    if (def?.name) {
      defs[def.name] = def
    }
  })
  return defs
})

const selectedEntityRelations = computed(() => {
  const entity = selectedEntity.value
  if (!entity) {
    return []
  }
  const id = String(entityKey(entity))
  const entities = graphDataCache.value.entities || []
  const edges = graphDataCache.value.edges || []
  return edges
    .filter((edge) => {
      const source = String(edge.source_id ?? edge.source ?? '')
      const target = String(edge.target_id ?? edge.target ?? '')
      return source === id || target === id
    })
    .map((edge) => {
      const outgoing = String(edge.source_id ?? edge.source ?? '') === id
      const peerId = outgoing ? (edge.target_id ?? edge.target) : (edge.source_id ?? edge.source)
      const peer = entities.find((item) => String(entityKey(item)) === String(peerId))
      if (!peer) {
        return null
      }
      return {
        id: edge.edge_id ?? edge.id,
        direction: outgoing ? t('modules.kb.entityRelationOutgoing') : t('modules.kb.entityRelationIncoming'),
        label: edgeLabelText(edge),
        peer: {
          ...peer,
          name: peer.properties?.name || peer.entity_name || peer.entity_id
        }
      }
    })
    .filter(Boolean)
})

/* ── 新增实体抽屉 ──────────────────────────────────────────── */
const createDrawerVisible = ref(false)
const createEntitySaving = ref(false)

const createEntityPropertyDefs = computed(() => {
  const meta = props.schemaMapping?.entity_meta || {}
  const defs = {}
  Object.keys(meta).forEach((type) => {
    defs[type] = Array.isArray(meta[type]?.properties) ? meta[type].properties : []
  })
  return defs
})

function openCreateDrawer () {
  editDrawerVisible.value = false
  createDrawerVisible.value = true
}

/** 工具栏「刷新知识图谱」：优先用详情页的实现（带加载态与查询条件保持）。 */
function handleToolbarRefresh () {
  if (typeof props.refreshGraph === 'function') {
    return props.refreshGraph()
  }
  requestServerRefresh()
  return Promise.resolve()
}

/**
 * 刷新后按当前画布重新收拢节点坐标。
 * 位置缓存保存的是「收拢前」的基准布局（避免小窗口布局被持久化），刷新时物理已关闭，
 * 不重新收拢就会按基准坐标铺满/超出画布；preserveView 保留用户当前的缩放与平移。
 */
async function restoreLayoutAfterRefresh () {
  await nextTick()
  graphCanvasRef.value?.compactLayoutToFit?.(true)
}

defineExpose({ restoreLayoutAfterRefresh, toggleFullscreen, exitFullscreen, closeTools, fitView, fitViewImmediate })

async function handleCreateEntity (payload) {
  if (!payload || createEntitySaving.value) {
    return
  }
  const kbId = getKnowledgeBaseId()
  if (!kbId) {
    return
  }
  const relation = payload.relation
  const edgeInfo = relation
    ? {
      edgeId: relation.edgeId,
      edgeType: relation.edgeType,
      currentEntityId: relation.peerId,
      direction: relation.direction,
      properties: relation.properties || {}
    }
    : null
  createEntitySaving.value = true
  try {
    // 失败时保留抽屉与已填内容；错误提示由 axios 拦截器统一给出
    const response = await createEntityApi(
      kbId,
      payload.entityId,
      payload.entityType,
      payload.properties,
      edgeInfo
    ).catch((err) => ({
      success: false,
      message: err?.msg ?? err?.message ?? t('modules.kb.entityCreateFailed')
    }))
    if (!isGraphApiSuccess(response)) {
      return
    }
    createDrawerVisible.value = false
    applyCreatedEntity(payload)
    proxy.$message.success(
      relation ? t('modules.kb.createEntitySuccessWithRelation') : t('modules.kb.createEntitySuccess')
    )
  } finally {
    createEntitySaving.value = false
  }
}

/** 创建成功后先增量落到当前画布，再由服务端刷新校正（与旧「增加实体」同一套路径）。 */
function applyCreatedEntity (payload) {
  const relation = payload.relation
  const entityData = {
    entity_id: payload.entityId,
    entity_type: payload.entityType,
    entity_name: payload.entityName,
    properties: payload.properties
  }

  isBatchProcessing.value = true
  const referenceId = relation?.peerId || selectedEntity.value?.entity_id || ''
  const position = graphCanvasRef.value?.addNode?.(entityData, referenceId || undefined)
  if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
    entityData.x = position.x
    entityData.y = position.y
  }
  graphDataCache.value.entities.push({ ...entityData })
  operationQueue.value.push({
    type: OperationType.ADD_ENTITY,
    data: { entity: entityData }
  })

  const ensureEdges = []
  if (relation) {
    const edgeData = {
      edge_id: relation.edgeId,
      edge_type: relation.edgeType,
      source_id: relation.sourceId,
      target_id: relation.targetId,
      properties: relation.properties || {}
    }
    graphDataCache.value.edges.push({ ...edgeData })
    graphCanvasRef.value?.addEdge?.(edgeData)
    operationQueue.value.push({
      type: OperationType.ADD_EDGE,
      data: { edge: edgeData }
    })
    ensureEdges.push({ ...edgeData })
  }

  // 新实体必须可见：清掉客户端搜索条件
  emit('search-clear')
  bumpLimitFromLocalEntityCount()
  requestServerRefresh({ ensureEntity: entityData, ensureEdges })
  isBatchProcessing.value = false

  nextTick(() => {
    const id = payload.entityId
    graphCanvasRef.value?.selectNodes?.([id])
    graphCanvasRef.value?.focusNode?.(id)
    selectedEntity.value = entityData
  })
}

const edgeColorMap = computed(() => {
  const map = {}
  const schemaOrder = props.edgeTypes && props.edgeTypes.length ? props.edgeTypes : []
  const fromData = edgeTypes.value
  schemaOrder.forEach((schemaType) => {
    const matched = fromData.find((t) => t === schemaType || String(t).toLowerCase() === String(schemaType).toLowerCase())
    if (matched) {
      map[matched] = '#9aa0a6'
    }
  })
  fromData.forEach((t) => {
    if (!(t in map)) {
      map[t] = '#9aa0a6'
    }
  })
  return map
})

const entityLegendItems = computed(() => {
  const countMap = new Map()
  const entitiesList = graphDataCache.value?.entities || []
  entitiesList.forEach((entity) => {
    const type = entity.entity_type || entity.class || 'Unknown'
    countMap.set(type, (countMap.get(type) || 0) + 1)
  })
  return Object.keys(colorMap.value).map((type) => ({
    type,
    color: colorMap.value[type],
    count: countMap.get(type) || 0
  }))
})

const totalNodes = computed(() => props.graphData.entities?.length || 0)
const totalEdges = computed(() => props.graphData.edges?.length || 0)


// 控制面板事件处理函数
function handleEntityTypeChange(types) {
  emit('entity-type-change', types)
}

function handleEdgeTypeChange(types) {
  emit('edge-type-change', types)
}

function handleLimitChange(value) {
  emit('limit-change', value)
}

function handleDepthChange(value) {
  emit('depth-change', value)
}

function handleExport() {
  emit('export')
}

function handleSearchInput(keyword) {
  // 触发搜索
  performEntitySearch(keyword)
  // 通知父组件更新搜索关键词，保持输入框的值
  emit('search-input', keyword)
}

function handleSearchClear() {
  clearSearch()
  emit('search-clear')
}

function handleExecuteQuery(payload) {
  emit('execute-query', payload)
}

function handleQueryTypeChange(queryType) {
  emit('query-type-change', queryType)
}




















// 处理添加边模式下的节点点击
function handleNodeClickInEdgeMode(d) {

  // 检查是否点击了起始节点
  if (d.id === sourceNodeForEdge.value?.entity_id) {
    return
  }

  // 检查是否点击了可连接的节点
  if (connectableNodes.value.includes(d.id)) {

    // 保存目标节点
    targetNodeForEdge.value = d.data

    // 打开添加边抽屉
    openAddEdgeDrawer()

    // 注意：不退出连线模式，保持相关实体显示状态
  }
}

















// ========== 边相关函数 ==========


// 关闭边的操作气泡卡片
function closeEdgeActionPopover() {
  edgeActionPopoverVisible.value = false
}


// 修改边
function handleEditEdge() {
  closeEdgeActionPopover()

  if (!selectedEdge.value) {
    return
  }

  // 复制当前边数据到编辑表单
  edgeEditForm.value = {
    edge_id: selectedEdge.value.edge_id || selectedEdge.value.id || '',
    class: selectedEdge.value.edge_type || selectedEdge.value.class || '',
    rid: selectedEdge.value.rid || '',
    source_id: selectedEdge.value.source_id || '',
    target_id: selectedEdge.value.target_id || '',
    in: selectedEdge.value.in || '',
    out: selectedEdge.value.out || '',
    properties: JSON.parse(JSON.stringify(selectedEdge.value.properties || {}))
  }

  openExclusiveDrawer('edgeEdit')
}

// 关闭边查看抽屉
function handleCloseEdgeDrawer() {
  edgeDrawerVisible.value = false
}

// 确定编辑边
async function handleConfirmEditEdge() {

  if (!selectedEdge.value) {
    console.error('❌ selectedEdge.value 为空，无法编辑边')
    return
  }

  const edgeId = selectedEdge.value.edge_id || selectedEdge.value.id
  const edgeType = selectedEdge.value.edge_type || selectedEdge.value.class
  // 转换BOOLEAN属性值
  const properties = convertBooleanProperties(edgeEditForm.value.properties, getEdgePropertyDef, edgeType)


  try {
    // 获取知识库ID
    const kbId = route.params.id || props.graphData.kbId
    if (!kbId) {
      console.error('❌ 无法获取知识库ID')
      proxy.$message.error(proxy.$t('modules.kb.cannotGetKbId'))
      return
    }

    // 调用后端API更新边
    const response = await updateEdgeApi(kbId, edgeId, edgeType, properties)

    // 检查API响应；成功与失败均触发查询更新数据
    if (response && response.success) {
      proxy.$message.success(proxy.$t('modules.kb.edgeUpdateSuccess'))

      // 1. 找到本地对应的边并更新属性
      const edge = props.graphData.edges.find(e => (e.edge_id || e.id) === edgeId)
      const updatedEdge = edge
        ? {
          ...edge,
          properties: { ...edgeEditForm.value.properties },
          edge_type: edgeEditForm.value.class,
          class: edgeEditForm.value.class
        }
        : null

      if (edge) {
        edge.properties = { ...edgeEditForm.value.properties }
      }

      // 2. 通知父组件同步数据
      if (updatedEdge && graphCanvasRef.value?.updateEdge) {
        const idx = graphDataCache.value.edges.findIndex((e) => (e.edge_id || e.id) === edgeId)
        if (idx >= 0) {
          graphDataCache.value.edges[idx] = updatedEdge
        }
        graphCanvasRef.value.updateEdge(updatedEdge)
        emit('refresh-graph-data', { incremental: true, updatedEdges: [updatedEdge] })
      } else {
        emit('refresh-graph-data', {
          entities: props.graphData.entities,
          edges: props.graphData.edges,
          edgeName: edgeId
        })
        requestServerRefresh()
      }

      // 3. 关闭编辑抽屉
      edgeEditDrawerVisible.value = false
    } else {
      console.error('边更新失败:', response)
      const errorMsg = response?.message || proxy.$t('modules.kb.edgeUpdateFailed')
      proxy.$message.error(errorMsg)
      requestServerRefresh()
    }
  } catch (error) {
    // axios 拦截器已统一提示，这里只留日志，避免双 toast
    console.error('调用边更新API失败:', error)
    requestServerRefresh()
  }
}

// 取消编辑边
function handleCancelEditEdge() {
  edgeEditDrawerVisible.value = false
}


// 搜索相关辅助函数
/**
 * 搜索框输入时的**本地**副作用。
 *
 * 真正的实体检索由详情页在点「查询」时发给后端（``graph/query`` 的 ``keyword``），
 * 这里不做本地匹配：按**已加载的**实体按名称过滤看不到 ID / 描述，也搜不到分页之外
 * 的数据，还会在后端其实能搜到时给出相反的提示。
 * 这里只保留「点画布空白处清空搜索」的状态维护。
 */
function performEntitySearch(keyword) {
  if (!keyword || keyword.trim() === '') {
    clearSearch()
    return
  }

  // 关闭所有编辑框（节点和边的编辑框）
  closeActionPopover()
  closeEdgeActionPopover()

  isSearchMode.value = true
}


function clearSearch() {
  isSearchMode.value = false

}

// 处理容器点击事件
function handleContainerClick(event) {
  zoomOptionsVisible.value = false
  lineModeOptionsVisible.value = false
  closeTools()
  // 如果点击的是空白区域（不是节点或边）
  if (event.target === graphContainer.value) {
    // 清除搜索模式
    if (isSearchMode.value) {
      clearSearch()
      // 通知父组件清除搜索关键词
      emit('search-clear')
    }

    // 退出连线模式
    if (isAddingEdgeMode.value) {
      exitAddingEdgeMode()
    }
  }
}

// ---------- vis 画布事件（方案 C）----------
function toContainerPosition(pos) {
  const rect = graphContainer.value?.getBoundingClientRect()
  if (!rect || pos == null) {
    return { x: pos?.x ?? 0, y: pos?.y ?? 0 }
  }
  return { x: pos.x - rect.left, y: pos.y - rect.top }
}

function handleNodeClickFromCanvas(entity, pos) {
  if (isAddingEdgeMode.value) {
    handleNodeClickInEdgeMode({ id: entity.entity_id || entity.id, data: entity })
    return
  }
  if (nodeClickDelayTimer.value) {
    clearTimeout(nodeClickDelayTimer.value)
    nodeClickDelayTimer.value = null
  }
  selectedEntity.value = entity
  actionPopoverPosition.value = toContainerPosition(pos)
  nodeClickDelayTimer.value = setTimeout(() => {
    nodeClickDelayTimer.value = null
    actionPopoverVisible.value = true
    edgeActionPopoverVisible.value = false
    graphCanvasRef.value?.selectNodes?.([entity.entity_id || entity.id])
  }, CLICK_DELAY_MS)
}

function handleEdgeClickFromCanvas(edge, pos) {
  if (edgeClickDelayTimer.value) {
    clearTimeout(edgeClickDelayTimer.value)
    edgeClickDelayTimer.value = null
  }
  selectedEdge.value = edge
  edgeActionPopoverPosition.value = toContainerPosition(pos)
  edgeClickDelayTimer.value = setTimeout(() => {
    edgeClickDelayTimer.value = null
    edgeActionPopoverVisible.value = true
    actionPopoverVisible.value = false
    const sourceId = edge.source_id || edge.source
    const targetId = edge.target_id || edge.target
    if (sourceId && targetId) {
      graphCanvasRef.value?.selectNodes?.([sourceId, targetId])
    }
  }, CLICK_DELAY_MS)
}

function handleContainerClickFromCanvas() {
  zoomOptionsVisible.value = false
  lineModeOptionsVisible.value = false
  closeTools()
  if (nodeClickDelayTimer.value) {
    clearTimeout(nodeClickDelayTimer.value)
    nodeClickDelayTimer.value = null
  }
  if (edgeClickDelayTimer.value) {
    clearTimeout(edgeClickDelayTimer.value)
    edgeClickDelayTimer.value = null
  }
  if (isSearchMode.value) {
    clearSearch()
    emit('search-clear')
  }
  if (isAddingEdgeMode.value) {
    exitAddingEdgeMode()
  }
  actionPopoverVisible.value = false
  edgeActionPopoverVisible.value = false
  graphCanvasRef.value?.selectNodes?.([])
}

function onVisZoomChange(scale) {
  if (Number.isFinite(scale)) {
    zoomLevel.value = Math.round(scale * 100)
  }
  if (thumbnailEnabled.value) {
    nextTick(() => {
      refreshThumbnailSnapshot()
    })
  }
}

function toggleLegend() {
  legendVisible.value = !legendVisible.value
}

function toggleZoomOptions() {
  zoomOptionsVisible.value = !zoomOptionsVisible.value
  lineModeOptionsVisible.value = false
}

function toggleLineModeOptions() {
  lineModeOptionsVisible.value = !lineModeOptionsVisible.value
  zoomOptionsVisible.value = false
}

function setEdgeLabelMode(mode) {
  edgeLabelDisplayMode.value = mode === 'hover' ? 'hover' : 'inline'
  if (graphCanvasRef.value?.setEdgeLabelMode) {
    graphCanvasRef.value.setEdgeLabelMode(edgeLabelDisplayMode.value)
  }
  lineModeOptionsVisible.value = false
}

function handleEdgeLabelModeChange(mode) {
  setEdgeLabelMode(mode)
}

/** 摘要行的「关系名称」开关：勾选 = 连线旁常显标签，取消 = 悬停显示。 */
function toggleEdgeLabels(value) {
  setEdgeLabelMode(value ? 'inline' : 'hover')
}

/** 摘要行的「重置布局」：回到 100% 并适配视口。 */
function resetGraphLayout() {
  resetZoom()
  fitView()
}

function handleCanvasAfterDrawing() {
  if (!thumbnailEnabled.value) {
    return
  }
  nextTick(() => {
    refreshThumbnailSnapshot()
  })
}

watch(edgeLabelDisplayMode, (mode) => {
  if (graphCanvasRef.value?.setEdgeLabelMode) {
    graphCanvasRef.value.setEdgeLabelMode(mode)
  }
})

function clearThumbnailSnapshot() {
  thumbnailSvgNodes.value = []
  thumbnailSvgEdges.value = []
  thumbnailViewportRect.value = null
}

function applyZoomScale(scale) {
  if (graphCanvasRef.value?.setZoomScale) {
    graphCanvasRef.value.setZoomScale(scale)
  }
}

function setZoomByPercent(percent) {
  const p = Number(percent)
  if (!Number.isFinite(p) || p <= 0) {
    return
  }
  zoomOptionsVisible.value = false
  applyZoomScale(p / 100)
}

function refreshThumbnailSnapshot() {
  if (!thumbnailEnabled.value) {
    return
  }
  if (!graphCanvasRef.value?.getNetwork) {
    return
  }
  const network = graphCanvasRef.value.getNetwork()
  const bodyNodes = network?.body?.nodes || {}
  const bodyEdges = network?.body?.edges || {}
  if (!network || !bodyNodes) {
    return
  }

  const rawNodes = Object.keys(bodyNodes).map((id) => {
    const node = bodyNodes[id]
    const hidden = node?.options?.hidden === true
    const x = Number(node?.x)
    const y = Number(node?.y)
    const entity = (graphDataCache.value.entities || []).find((e) => String(e.entity_id || e.id) === String(id))
    const type = entity?.entity_type || entity?.class
    return {
      id,
      x,
      y,
      hidden,
      color: colorMap.value[type] || '#cccccc'
    }
  }).filter((node) => !node.hidden && Number.isFinite(node.x) && Number.isFinite(node.y))

  if (!rawNodes.length) {
    clearThumbnailSnapshot()
    return
  }

  const minX = Math.min(...rawNodes.map((node) => node.x))
  const maxX = Math.max(...rawNodes.map((node) => node.x))
  const minY = Math.min(...rawNodes.map((node) => node.y))
  const maxY = Math.max(...rawNodes.map((node) => node.y))
  const pad = 8
  const width = 260
  const height = 150
  const graphWidth = Math.max(1, maxX - minX)
  const graphHeight = Math.max(1, maxY - minY)
  const scale = Math.min((width - pad * 2) / graphWidth, (height - pad * 2) / graphHeight)
  const offsetX = (width - graphWidth * scale) / 2 - minX * scale
  const offsetY = (height - graphHeight * scale) / 2 - minY * scale
  const mapX = (x) => x * scale + offsetX
  const mapY = (y) => y * scale + offsetY

  thumbnailSvgNodes.value = rawNodes.map((node) => ({
    id: node.id,
    x: mapX(node.x),
    y: mapY(node.y),
    color: node.color
  }))

  thumbnailSvgEdges.value = Object.keys(bodyEdges).map((id) => {
    const edge = bodyEdges[id]
    if (edge?.options?.hidden === true) {
      return null
    }
    const from = edge?.from
    const to = edge?.to
    const x1 = Number(from?.x)
    const y1 = Number(from?.y)
    const x2 = Number(to?.x)
    const y2 = Number(to?.y)
    return {
      id,
      x1: mapX(x1),
      y1: mapY(y1),
      x2: mapX(x2),
      y2: mapY(y2)
    }
  }).filter((edge) => edge && [edge.x1, edge.y1, edge.x2, edge.y2].every(Number.isFinite))

  const view = typeof network.getViewPosition === 'function' ? network.getViewPosition() : null
  const zoomScale = typeof network.getScale === 'function' ? network.getScale() : 1
  const containerWidth = graphContainer.value?.clientWidth || 0
  const containerHeight = graphContainer.value?.clientHeight || 0
  if (view && Number.isFinite(zoomScale) && zoomScale > 0 && containerWidth > 0 && containerHeight > 0) {
    const halfW = (containerWidth / zoomScale) / 2
    const halfH = (containerHeight / zoomScale) / 2
    thumbnailViewportRect.value = {
      x: mapX(view.x - halfW),
      y: mapY(view.y - halfH),
      width: Math.max(1, containerWidth * scale / zoomScale),
      height: Math.max(1, containerHeight * scale / zoomScale)
    }
  } else {
    thumbnailViewportRect.value = null
  }
}

function toggleThumbnail() {
  thumbnailEnabled.value = !thumbnailEnabled.value
  if (!thumbnailEnabled.value) {
    clearThumbnailSnapshot()
    if (thumbnailRefreshTimer) {
      clearInterval(thumbnailRefreshTimer)
      thumbnailRefreshTimer = null
    }
    return
  }
  nextTick(() => {
    refreshThumbnailSnapshot()
    setTimeout(() => {
      refreshThumbnailSnapshot()
    }, 0)
    setTimeout(() => {
      refreshThumbnailSnapshot()
    }, 300)
    if (thumbnailRefreshTimer) {
      clearInterval(thumbnailRefreshTimer)
      thumbnailRefreshTimer = null
    }
    thumbnailRefreshTimer = setInterval(() => {
      refreshThumbnailSnapshot()
    }, 800)
  })
}

function handleToggleExpandFromCanvas(nodeId) {
  const entity = graphDataCache.value.entities.find(
    (e) => String(e.entity_id || e.id) === String(nodeId)
  )
  if (entity) {
    toggleEntityExpand(entity, { stopPropagation: () => {} })
  }
}

function handleNodeDoubleClickFromCanvas(entity) {
  if (!entity) {
    return
  }
  if (nodeClickDelayTimer.value) {
    clearTimeout(nodeClickDelayTimer.value)
    nodeClickDelayTimer.value = null
  }
  selectedEntity.value = entity
  actionPopoverVisible.value = false
  edgeActionPopoverVisible.value = false
  openExclusiveDrawer('entityEdit')
}

function handleEdgeDoubleClickFromCanvas(edge) {
  if (!edge) {
    return
  }
  if (edgeClickDelayTimer.value) {
    clearTimeout(edgeClickDelayTimer.value)
    edgeClickDelayTimer.value = null
  }
  selectedEdge.value = edge
  edgeEditForm.value = {
    edge_id: edge.edge_id || edge.id || '',
    class: edge.edge_type || edge.class || '',
    rid: edge.rid || '',
    source_id: edge.source_id || edge.source || '',
    target_id: edge.target_id || edge.target || '',
    in: edge.in || '',
    out: edge.out || '',
    properties: JSON.parse(JSON.stringify(edge.properties || {}))
  }
  actionPopoverVisible.value = false
  edgeActionPopoverVisible.value = false
  openExclusiveDrawer('edgeEdit')
}


// 删除边
async function handleDeleteEdge() {
  closeEdgeActionPopover()

  if (!selectedEdge.value) {
    return
  }

  const edgeId = selectedEdge.value.edge_id || selectedEdge.value.id
  const edgeType = selectedEdge.value.edge_type || selectedEdge.value.class

  try {
    await proxy.$confirm(
      proxy.$t('modules.kb.deleteEdgeConfirm', { name: edgeId }),
      proxy.$t('modules.kb.delete'),
      { type: 'warning' }
    )
  } catch {
    return
  }

  try {
    const kbId = getKnowledgeBaseId()
    if (!kbId) {
      return
    }


    // 调用后端删除边接口
    const response = await deleteEdgeApi(kbId, edgeId, edgeType)

    // 检查API响应
    if (isGraphApiSuccess(response)) {
      await handleEdgeDeleteSuccess(edgeId)
    } else {
      handleEdgeDeleteFailure(response)
    }
  } catch (error) {
    handleEdgeDeleteError(error)
  }
}

// 获取知识库ID
function getKnowledgeBaseId() {
  const kbId = route.params.id || props.graphData.kbId
  if (!kbId) {
    console.error('❌ 无法获取知识库ID')
    proxy.$message.error(proxy.$t('modules.kb.cannotGetKbId'))
    return null
  }
  return kbId
}

// 处理边删除成功
async function handleEdgeDeleteSuccess(edgeId) {

  // 关闭操作气泡卡片
  closeEdgeActionPopover()

  requestServerRefresh({ deletedEdgeId: edgeId })
}


// 处理边删除失败
function handleEdgeDeleteFailure(response) {
  console.error('边删除失败:', response)
  const errorMsg = response?.message || proxy.$t('modules.kb.edgeDeleteFailed')
  proxy.$message.error(errorMsg)
}

// 处理边删除错误（axios 拦截器已统一提示，这里只留日志，避免双 toast）
function handleEdgeDeleteError(error) {
  console.error('调用边删除API失败:', error)
}

// 缩放控制（vis 画布）
function zoomIn() {
  if (graphCanvasRef.value?.zoomIn) {
    graphCanvasRef.value.zoomIn()
  }
}

function zoomOut() {
  if (graphCanvasRef.value?.zoomOut) {
    graphCanvasRef.value.zoomOut()
  }
}

function resetZoom() {
  if (graphCanvasRef.value?.resetZoom) {
    graphCanvasRef.value.resetZoom()
  }
}

/**
 * 居中：保持当前缩放，仅平移使图心（节点包围盒中心）对准视口中心，便于在放大后找回图心。
 * 与 fitView（全屏适配）不同，不会改变缩放比例。
 */
function centerGraph() {
  if (!graphCanvasRef.value?.getNetwork) {
    return
  }
  const network = graphCanvasRef.value.getNetwork()
  if (!network) {
    return
  }
  const posMap = network.getPositions()
  const keys = Object.keys(posMap || {})
  if (keys.length === 0) {
    return
  }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  keys.forEach((k) => {
    const p = posMap[k]
    if (!p) {
      return
    }
    const x = typeof p.x === 'number' ? p.x : Number(p.x)
    const y = typeof p.y === 'number' ? p.y : Number(p.y)
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return
    }
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  })
  if (!Number.isFinite(minX)) {
    return
  }
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  network.moveTo({
    position: { x: cx, y: cy },
    animation: true
  })
  nextTick(() => {
    handleCanvasAfterDrawing()
  })
}

/** 全屏适配：缩放并平移，使全部节点进入视野（vis-network 的 fit） */
function fitView() {
  if (graphCanvasRef.value?.fit) {
    graphCanvasRef.value.fit()
  }
}

/** 查询结果落定后的无动画适配（见 GraphCanvasVis.fitImmediate 的说明）。 */
function fitViewImmediate() {
  if (graphCanvasRef.value?.fitImmediate) {
    graphCanvasRef.value.fitImmediate()
  }
}


// 关闭操作气泡卡片
function closeActionPopover() {
  actionPopoverVisible.value = false
}


// 修改节点
function handleEdit() {
  closeActionPopover()

  if (!selectedEntity.value) {
    return
  }

  // 打开编辑抽屉
  openExclusiveDrawer('entityEdit')
}




// 确定编辑
/** 实体编辑抽屉保存：payload = { name, description, properties }（properties 已按模板类型解析） */
async function handleEntityDrawerSave (payload) {
  if (!selectedEntity.value || !payload) {
    return
  }

  const entityId = selectedEntity.value.entity_id || selectedEntity.value.id
  const entityType = selectedEntity.value.entity_type || selectedEntity.value.class
  const properties = payload.properties || {}

  try {
    const kbId = getKnowledgeBaseId()
    if (!kbId) {
      return
    }

    entityDrawerSaving.value = true
    const response = await updateEntityApi(kbId, entityId, entityType, properties)

    if (isGraphApiSuccess(response)) {
      handleEntityUpdateSuccess(properties)
    } else {
      handleEntityUpdateFailure(response)
    }
  } catch (error) {
    handleEntityUpdateError(error)
  } finally {
    entityDrawerSaving.value = false
  }
}

// 处理实体更新成功
function handleEntityUpdateSuccess (properties) {
  proxy.$message.success(proxy.$t('modules.kb.entityUpdateSuccess'))

  // 关闭编辑抽屉
  editDrawerVisible.value = false

  if (!selectedEntity.value) {
    return
  }

  const updatedEntity = {
    ...selectedEntity.value,
    properties: { ...properties }
  }
  const idx = graphDataCache.value.entities.findIndex(
    (e) => (e.entity_id || e.id) === (updatedEntity.entity_id || updatedEntity.id)
  )
  if (idx >= 0) {
    graphDataCache.value.entities[idx] = updatedEntity
  }
  selectedEntity.value = updatedEntity

  if (graphCanvasRef.value?.updateNode) {
    graphCanvasRef.value.updateNode(updatedEntity)
    emit('refresh-graph-data', { incremental: true, updatedEntities: [updatedEntity] })
  } else {
    requestServerRefresh({ ensureEntity: updatedEntity })
  }
}


// 处理实体更新失败
function handleEntityUpdateFailure(response) {
  console.error('实体更新失败:', response)
  const errorMsg = response?.detail || response?.message || proxy.$t('modules.kb.entityUpdateFailed')
  proxy.$message.error(errorMsg)
  requestServerRefresh()
  stopGraphLoading()
}

// 处理实体更新错误
function handleEntityUpdateError(error) {
  // axios 拦截器已统一提示，这里只留日志，避免双 toast
  console.error('调用实体更新API失败:', error)
  requestServerRefresh()
  stopGraphLoading()
}

/** 抽屉内点击关联实体：切换当前编辑对象（画布同步选中） */
function handleEntityDrawerSelect (peer) {
  if (!peer) {
    return
  }
  selectedEntity.value = peer
  graphCanvasRef.value?.selectNodes?.([peer.entity_id || peer.id])
}

/** 抽屉底部「定位实体」：关闭抽屉并居中到该节点 */
function handleEntityDrawerLocate () {
  const entity = selectedEntity.value
  if (!entity) {
    return
  }
  const id = entity.entity_id || entity.id
  editDrawerVisible.value = false
  graphCanvasRef.value?.selectNodes?.([id])
  graphCanvasRef.value?.focusNode?.(id)
}



// 删除节点
async function handleDeleteNode() {
  closeActionPopover()

  if (!selectedEntity.value) {
    return
  }

  const entityId = selectedEntity.value.entity_id
  const entityType = selectedEntity.value.class || selectedEntity.value.entity_type

  try {
    await proxy.$confirm(
      proxy.$t('modules.kb.deleteEntityConfirm', {
        name: selectedEntity.value.entity_name || entityId
      }),
      proxy.$t('modules.kb.delete'),
      { type: 'warning' }
    )
  } catch {
    return
  }

  try {
    const kbId = getKnowledgeBaseId()
    if (!kbId) {
      return
    }


    // 调用后端删除实体接口
    const response = await deleteEntityApi(kbId, entityId, entityType)

    // 检查API响应
    if (isGraphApiSuccess(response)) {
      await handleNodeDeleteSuccess()
    } else {
      handleNodeDeleteFailure(response)
    }
  } catch (error) {
    handleNodeDeleteError(error)
  }
}

// 处理节点删除成功
async function handleNodeDeleteSuccess() {

  // 关闭操作气泡卡片
  closeActionPopover()

  requestServerRefresh({ deletedEntityId: selectedEntity.value?.entity_id })
}


// 处理节点删除失败
function handleNodeDeleteFailure(response) {
  console.error('实体删除失败:', response)
  const errorMsg = response?.message || proxy.$t('modules.kb.entityDeleteFailed')
  proxy.$message.error(errorMsg)
}

// 处理节点删除错误（axios 拦截器已统一提示，这里只留日志，避免双 toast）
function handleNodeDeleteError(error) {
  console.error('调用实体删除API失败:', error)
}



// 根据边类型和属性名获取属性定义
function getEdgePropertyDef(edgeType, propName) {
  if (!edgeType || !propName) {
    return null
  }
  const adjacencyMap = props.schemaMapping?.adjacency_map || {}
  for (const sourceMap of Object.values(adjacencyMap)) {
    for (const edges of Object.values(sourceMap)) {
      if (Array.isArray(edges)) {
        const found = edges.find(e => e.edge_type === edgeType)
        if (found) {
          const propsArr = found.properties || []
          return propsArr.find(p => p.name === propName) || null
        }
      }
    }
  }
  return null
}

// 转换BOOLEAN属性值（用于下发到后端）
function convertBooleanProperties(properties, propDefGetter, typeOrEntityType) {
  if (!properties) {
    return {}
  }
  const result = { ...properties }
  Object.keys(result).forEach(key => {
    const propDef = propDefGetter(typeOrEntityType, key)
    if (propDef?.type === 'BOOLEAN') {
      if (result[key] === 'true') {
        result[key] = true
      } else if (result[key] === 'false') {
        result[key] = false
      } else if (result[key] === '') {
        result[key] = null
      }
    }
  })
  return result
}

// 根据实体类型A和B获取可用的边类型
function getAvailableEdgeTypesForEntities(entityTypeA, entityTypeB) {

  if (!props.schemaMapping || !props.schemaMapping.adjacency_map) {
    console.warn('🔗 没有找到映射数据')
    return []
  }

  const adjacencyMap = props.schemaMapping.adjacency_map

  const edgeTypes = []

  if (adjacencyMap[entityTypeA] && adjacencyMap[entityTypeA][entityTypeB]) {
    adjacencyMap[entityTypeA][entityTypeB].forEach(edge => {
      edgeTypes.push({
        edge_type: edge.edge_type,
        edge_desc: edge.edge_desc,
        direction: edge.direction,
        properties: edge.properties || []
      })
    })
  }

  return edgeTypes
}


/** 打开「添加关系」抽屉；node 为空时由抽屉内自选起点。 */
function openRelationDrawer (node = selectedEntity.value) {
  closeActionPopover()
  exitAddingEdgeMode()
  // 同一时间只留一个抽屉：实体/边抽屉开着时先收起（实体抽屉的「添加关系」在未保存时禁用）
  editDrawerVisible.value = false
  edgeDrawerVisible.value = false
  edgeEditDrawerVisible.value = false
  relationSourceId.value = String(node?.entity_id ?? node?.id ?? '')
  relationTargetId.value = ''
  relationDrawerVisible.value = true
}

// 节点气泡「添加关系」：以当前选中实体为起点
function handleAddEdge () {
  if (!selectedEntity.value) {
    return
  }
  openRelationDrawer(selectedEntity.value)
}

/** 画布连线模式（点击起点再点终点）完成后打开同一个抽屉，两端预填。 */
function openAddEdgeDrawer () {
  if (!sourceNodeForEdge.value || !targetNodeForEdge.value) {
    return
  }
  closeActionPopover()
  relationSourceId.value = String(sourceNodeForEdge.value.entity_id ?? '')
  relationTargetId.value = String(targetNodeForEdge.value.entity_id ?? '')
  relationDrawerVisible.value = true
  exitAddingEdgeMode()
}

/** 创建关系（真实 createEdgeApi）；成功后带新边刷新，避免 limit 截断时看不到。 */
async function handleRelationSave (relation) {
  if (!relation || relationSaving.value) {
    return
  }
  const kbId = getKnowledgeBaseId()
  if (!kbId) {
    return
  }
  relationSaving.value = true
  try {
    const response = await createEdgeApi(
      kbId,
      relation.edgeId,
      relation.edgeType,
      relation.properties,
      relation.sourceId,
      relation.targetId
    )
    if (!isGraphApiSuccess(response)) {
      proxy.$message.error(response?.message || proxy.$t('modules.kb.edgeCreateFailed'))
      return
    }
    proxy.$message.success(proxy.$t('modules.kb.edgeCreateSuccess'))
    relationDrawerVisible.value = false
    requestServerRefresh({ ensureEdges: buildEnsureEdgePayload(relation) })
  } catch (error) {
    proxy.$message.error(`${proxy.$t('modules.kb.edgeCreateFailed')}：${error.message || proxy.$t('modules.kb.networkError')}`)
  } finally {
    relationSaving.value = false
  }
}



// 退出添加边模式
function exitAddingEdgeMode() {
  isAddingEdgeMode.value = false
  sourceNodeForEdge.value = null
  targetNodeForEdge.value = null
  connectableNodes.value = []
}
// 导出功能已移至 handleExport 函数




// 监听数据变化
watch(() => props.graphData, (newData) => {

  // 增量更新方案：如果正在批量处理，不触发重新渲染
  if (isBatchProcessing.value) {
    // 更新本地缓存，但不触发渲染
    if (newData) {
      graphDataCache.value = {
        entities: [...(newData.entities || [])],
        edges: [...(newData.edges || [])]
      }
    }
    return
  }

  // 更新本地缓存
  if (newData) {
    graphDataCache.value = {
      entities: [...(newData.entities || [])],
      edges: [...(newData.edges || [])]
    }
  }

  // 数据已同步到 graphDataCache，由 GraphCanvasVis 根据缓存自动渲染
}, { deep: true })

watch(
  () => [graphDataCache.value.entities?.length, graphDataCache.value.edges?.length],
  () => {
    if (thumbnailEnabled.value) {
      nextTick(() => {
        refreshThumbnailSnapshot()
      })
    }
  }
)

// 监听搜索关键词变化
watch(() => props.searchKeyword, (newKeyword) => {
  performEntitySearch(newKeyword)
})

// ==================== 实体展开/收起功能函数 ====================

/**
 * 递归获取指定实体的所有出向子实体（子孙节点）
 * @param {string} entityId - 起始实体 ID
 * @param {Array} edges - 边数组
 * @param {Array} entities - 实体数组
 * @returns {Array} 所有出向子实体数组
 */
function getOutgoingDescendants(entityId, edges, entities) {
  const descendants = []
  const visited = new Set()

  function dfs(currentId) {
    const cur = String(currentId)
    if (visited.has(cur)) {
      return
    }
    visited.add(cur)

    const outgoingEdges = edges.filter(e => {
      const sourceId = e.source_id || e.source
      return String(sourceId) === cur
    })

    outgoingEdges.forEach(edge => {
      const targetId = edge.target_id || edge.target
      const tStr = String(targetId)
      if (!visited.has(tStr)) {
        const targetEntity = entities.find(e => {
          const eid = e.entity_id || e.id
          return String(eid) === tStr
        })
        if (targetEntity) {
          descendants.push(targetEntity)
          dfs(targetId)
        }
      }
    })
  }

  dfs(entityId)
  return descendants
}

/** 是否存在以该 id 为 source 的出向边（用于展开后中间节点显示减号） */
function hasOutgoingEdgeFrom (nodeId, edges) {
  const sid = String(nodeId)
  return edges.some((e) => String(e.source_id || e.source) === sid)
}

/**
 * 收起实体的出向子实体
 * @param {Object} entity - 要收起的实体对象
 */
function collapseEntity(entity) {
  if (!entity) {
    return
  }

  const entityId = entity.entity_id || entity.id
  const edges = graphDataCache.value.edges || []
  const entities = graphDataCache.value.entities || []

  // 获取所有出向子孙实体
  const descendants = getOutgoingDescendants(entityId, edges, entities)


  descendants.forEach(desc => {
    const descId = String(desc.entity_id || desc.id)
    hiddenNodeIds.value.add(descId)
  })

  hiddenNodeIds.value = new Set(hiddenNodeIds.value)

  entityExpandState.value.set(entityId, false)
  entityExpandState.value = new Map(entityExpandState.value)

  if (graphCanvasRef.value) {
    updateNodeVisibility()
  }

  proxy.$message.success(proxy.$t('modules.kb.collapseSuccess'))
}

/**
 * 展开实体的出向子实体（整棵出向子树全部展示，不做分层）
 * @param {Object} entity - 要展开的实体对象
 */
function expandEntity(entity) {
  if (!entity) {
    return
  }

  const entityId = entity.entity_id || entity.id
  const edges = graphDataCache.value.edges || []
  const entities = graphDataCache.value.entities || []

  const allDescendants = getOutgoingDescendants(entityId, edges, entities)

  allDescendants.forEach((desc) => {
    const id = String(desc.entity_id || desc.id)
    hiddenNodeIds.value.delete(id)
  })

  hiddenNodeIds.value = new Set(hiddenNodeIds.value)

  entityExpandState.value.set(entityId, true)

  // 子树全部可见时，仍有出向边的中间节点也应为「已展开」，右上角显示减号
  allDescendants.forEach((desc) => {
    const nid = desc.entity_id || desc.id
    if (hasOutgoingEdgeFrom(nid, edges)) {
      entityExpandState.value.set(nid, true)
    }
  })

  entityExpandState.value = new Map(entityExpandState.value)

  if (graphCanvasRef.value) {
    updateNodeVisibility()
  }

  proxy.$message.success(proxy.$t('modules.kb.expandSuccess'))
}

/**
 * 切换实体的展开/收起状态
 * @param {Object} entity - 实体对象
 * @param {Event} event - 点击事件
 */
function toggleEntityExpand(entity, event) {
  if (!entity) {
    return
  }

  event.stopPropagation() // 阻止事件冒泡，避免触发节点点击

  const entityId = entity.entity_id || entity.id
  const isExpanded = entityExpandState.value.get(entityId) !== false // 默认是展开的

  if (isExpanded) {
    collapseEntity(entity)
  } else {
    expandEntity(entity)
  }
}

/**
 * 同步画布可见性：须在 nextTick 执行，以便子组件已收到 persistentlyHiddenNodeIds；
 * 具体逻辑在 GraphCanvasVis.syncVisibilityFromHiddenProps（含悬浮一跳与 network.redraw）。
 */
function updateNodeVisibility() {
  if (!graphCanvasRef.value) {
    return
  }
  nextTick(() => {
    graphCanvasRef.value?.syncVisibilityFromHiddenProps?.()
  })
}

// ==================== 实体展开/收起功能函数结束 ====================

// 生命周期
onMounted(() => {
  // 初始化本地缓存（增量更新方案）
  if (props.graphData) {
    graphDataCache.value = {
      entities: [...(props.graphData.entities || [])],
      edges: [...(props.graphData.edges || [])]
    }
  }
  document.addEventListener('keydown', handleFullscreenKey)
})

onBeforeUnmount(() => {
  if (thumbnailRefreshTimer) {
    clearInterval(thumbnailRefreshTimer)
    thumbnailRefreshTimer = null
  }
  document.removeEventListener('keydown', handleFullscreenKey)
  clearThumbnailSnapshot()
})
</script>

<style lang="less" scoped>
.graph-visualization {
  display: flex;
  flex-direction: column;
  // 撑满详情页 tab 内容区；高度由父级 flex 决定，控制面板之外的剩余空间给画布
  height: 100%;
  min-height: 0;
  background: transparent;
}

/* ── 工具条 + 摘要行一组，全屏时整体收进「查询与操作」浮层 ────────── */
.graph-controls {
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  min-width: 0;
}

.graph-visualization.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 100;
  width: 100%;
  height: 100dvh;
  padding: 0;
  gap: 0;
  background: var(--rs-canvas-bg, #f8fafd);
}

.graph-visualization.is-fullscreen .graph-controls {
  display: none;
}

.graph-visualization.is-fullscreen .graph-controls.is-overlay {
  display: flex;
  position: absolute;
  top: 56px;
  right: 18px;
  z-index: 6;
  width: min(700px, calc(100% - 36px));
  max-height: calc(100dvh - 140px);
  overflow: auto;
  padding: 12px;
  --el-component-size: 32px;
  gap: 8px;
  border: 1px solid var(--rs-border, #e5ebf4);
  border-radius: var(--rs-radius, 8px);
  background: var(--rs-bg-card, #fff);
  box-shadow: 0 8px 28px #10224918;
}

/* 浮层内控件收紧并右对齐，刷新反馈不撑开面板。 */
.graph-controls.is-overlay :deep(.controls-wrapper) {
  margin-top: 0;
}

.graph-controls.is-overlay :deep(.controls-row) {
  justify-content: flex-end;
  gap: 8px;
}

.graph-controls.is-overlay :deep(.controls-left),
.graph-controls.is-overlay :deep(.controls-right) {
  gap: 8px;
  padding-left: 0;
  padding-right: 0;
}

.graph-controls.is-overlay :deep(.control-search) {
  width: 240px;
}

.graph-controls.is-overlay :deep(.control-type) {
  width: 140px;
}

.graph-controls.is-overlay :deep(.control-button) {
  height: 32px;
  padding: 6px 12px;
  font-size: var(--rs-font-size-secondary, 13px);
}

.graph-controls.is-overlay :deep(.button-compact),
.graph-controls.is-overlay :deep(.graph-data-actions .table-refresh-control > .el-button) {
  height: 32px;
  padding: 6px 12px;
  font-size: var(--rs-font-size-secondary, 13px);
}

.graph-controls.is-overlay :deep(.el-checkbox) {
  height: 32px;
  margin-right: 0;
}

.graph-controls.is-overlay .graph-display-summary {
  height: auto;
  margin: 8px 0 0;
  gap: 8px;
}

.graph-controls.is-overlay .graph-display-meta {
  gap: 6px 10px;
}

.graph-controls.is-overlay .graph-display-actions {
  gap: 8px;
}

.graph-visualization.is-fullscreen .graph-container {
  border: 0;
  border-radius: 0;
}

.graph-fullscreen-actions {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 7;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: calc(100% - 36px);
}

.graph-fullscreen-actions .el-button {
  background: var(--rs-bg-card, #fff);
}

/* 画布右上角有按钮时，左下角提示文字让出宽度。 */
.graph-container:has(.graph-fullscreen-actions) .graph-canvas-hint {
  max-width: calc(100% - 170px);
}

.graph-fullscreen-context {
  position: absolute;
  top: 22px;
  left: 18px;
  z-index: 5;
  max-width: calc(100% - 300px);
  overflow: hidden;
  color: var(--rs-text-3, #8794ae);
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
}

.graph-display-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 10px 4px 14px;
  color: var(--rs-text-2, #536383);
  font-size: 13px;
}

.graph-display-summary b {
  color: var(--rs-text, #0c1538);
}

.graph-display-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  min-width: 0;
}

.graph-limit-link {
  padding: 0;
}

.graph-limit-notice {
  flex-basis: 100%;
  color: var(--rs-text-3, #8794ae);
}

.graph-display-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 16px;
}

/* 摘要行右侧的建图操作（添加关系；添加实体仍在工具栏） */
.graph-create-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  padding-left: 14px;
  border-left: 1px solid var(--rs-border);
}

@media (max-width: 700px) {
  .graph-create-actions {
    padding-left: 0;
    border-left: 0;
  }
}

.graph-legend-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px;
  padding: 12px 4px 0;
  color: var(--rs-text-2, #536383);
  flex-shrink: 0;
}

.graph-legend-row span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.graph-legend-row i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}


.vn-select{
  width: 10vw;
  min-width: 248px;
}

.graph-container {
  position: relative;
  // 宽度跟随内容区（97.5vw 会忽略左栏和页面内边距 → 横向滚动条）；
  // 高度由 flex 吃掉控制面板之外的剩余空间（76vh 写死会和面板高度相加超出容器）
  flex: 1 1 auto;
  min-height: 0;
  background-color: var(--rs-canvas-bg, #f8fafd);
  background-image: radial-gradient(var(--rs-canvas-dot, #dbe3ef) 0.8px, transparent 0.8px);
  background-size: 20px 20px;
  width: 100%;
  border-radius: var(--rs-radius, 8px);
  border: 1px solid var(--rs-border, #e5ebf4);
  overflow: hidden;

  .graph-vis-wrapper {
    width: 100%;
    height: 100%;
  }

  .kg-bottom-left {
    position: absolute;
    left: 18px;
    bottom: 18px;
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .kg-thumbnail-panel {
    width: 260px;
    height: 150px;
    background: var(--rs-bg-soft);
    border-radius: 4px;
    border: 1px solid var(--rs-border);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    overflow: hidden;
  }

  .kg-thumbnail-svg {
    width: 100%;
    height: 100%;
    display: block;
  }

  .legend {
    position: absolute;
    left: 20px;
    top: 20px;
    background: color-mix(in srgb, var(--rs-bg-card) 95%, transparent);
    padding: 12px;
    border-radius: 3px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    z-index: 100;
    min-width: 190px;

    .legend-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 8px;
    }

    .legend-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--rs-text);
    }

    .legend-close-btn {
      border: none;
      background: transparent;
      color: var(--rs-text-3);
      cursor: pointer;
      font-size: 14px;
      width: 20px;
      height: 20px;
      line-height: 20px;
      text-align: center;
      border-radius: 4px;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    .legend-close-btn:hover {
      background: var(--rs-bg-hover);
      color: var(--rs-text-2);
    }

    .legend-item {
      display: flex;
      align-items: center;
      margin-bottom: 8px;

      &:last-child {
        margin-bottom: 0;
      }

      .legend-color {
        width: 20px;
        height: 20px;
        border-radius: 50%;
        margin-right: 8px;
        border: 2px solid var(--rs-bg-card);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
      }

      span {
        font-size: 12px;
        color: var(--rs-text-2);
      }
    }

  }

  /* 与 .canvas-controls 一致：白底、1px 边框、4px 内距的小圆角胶囊 */
  .zoom-controls {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--rs-bg-card, #fff);
    padding: 4px;
    border: 1px solid var(--rs-border, #e5ebf4);
    border-radius: var(--rs-radius, 8px);
    box-shadow: 0 3px 12px rgba(16, 34, 73, 0.03);
  }

  .zoom-btn {
    padding: 4px;
    border: none;
    background: transparent;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background-color 0.2s;
    border-radius: 4px;
    width: 28px;
    height: 30px;

    &:hover {
      background-color: var(--rs-bg-hover, #f5f9ff);
    }

    &:active {
      background-color: var(--rs-bg-selected, #edf5ff);
    }

    &.is-active {
      border: none !important;
      outline: none;
      box-shadow: none !important;
      background: var(--rs-bg-selected, #edf5ff);
    }

    img {
      width: 16px;
      height: 16px;
      display: block;
    }
  }

  .zoom-divider {
    width: 1px;
    height: 18px;
    background-color: var(--rs-border, #e5ebf4);
    margin: 0 4px;
    flex-shrink: 0;
  }

  .zoom-select-wrap {
    position: relative;
  }

  /* 缩放比例是纯文本（不是带框下拉），点击仍可展开预设比例 */
  .zoom-select-btn {
    height: 30px;
    min-width: 48px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--rs-text-2, #536383);
    cursor: pointer;
    font-size: 12px;
    padding: 0 6px;

    &:hover {
      background: var(--rs-bg-hover, #f5f9ff);
    }
  }

  .zoom-options {
    position: absolute;
    left: 0;
    bottom: calc(100% + 4px);
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--rs-bg-card, #fff);
    border: 1px solid var(--rs-border, #dcdfe6);
    border-radius: 6px;
    padding: 6px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  }

  .zoom-option-btn {
    border: 0;
    background: transparent;
    font-size: 12px;
    color: var(--rs-text-2, #606266);
    cursor: pointer;
    text-align: left;
    padding: 4px 8px;
    border-radius: 4px;
  }

  .zoom-option-btn:hover {
    background: var(--rs-bg-hover, #f5f7fa);
  }

  .line-config-wrap {
    position: relative;
  }

  .line-mode-options {
    position: absolute;
    left: 0;
    bottom: calc(100% + 4px);
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--rs-bg-card, #fff);
    border: 1px solid var(--rs-border, #dcdfe6);
    border-radius: 6px;
    padding: 6px 6px 6px 16px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    min-width: 120px;
    :deep(.el-radio-group) {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    :deep(.el-radio) {
      margin-right: 0;
      height: 24px;
      line-height: 24px;
    }
  }

  :deep(.node) {
    cursor: pointer;
    transition: all 0.3s ease;

    circle {
      transition: all 0.2s ease;
    }

    text {
      pointer-events: none;
      user-select: none;
    }
  }

  :deep(.link) {
    transition: all 0.3s ease;
  }
}

:deep(.el-tabs__header) {
    margin:  0px 0px;
  }

// 操作气泡卡片样式
.action-popover {
  position: absolute;
  display: flex;
  gap: 8px;
  padding: 8px;
  background: var(--rs-bg-card);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 1001;

  .action-btn {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s;
    background: var(--rs-bg-hover);

    &:hover {
      background: var(--rs-primary);
      transform: scale(1.1);

      :deep(.el-icon) {
        color: #fff;
      }
    }

    :deep(.el-icon) {
      font-size: 18px;
      color: var(--rs-text-2);
      transition: color 0.2s;
    }
  }
}

// 抽屉样式
:deep(.el-drawer) {
  .el-drawer__header {
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--rs-border);
  }

  .el-drawer__body {
    padding: 20px;
  }

  .el-drawer__footer {
    padding: 16px 20px;
    border-top: 1px solid var(--rs-border);
    text-align: right;
  }

  // 折叠框内容缩进
  .el-collapse-item__wrap {
    padding-left: 20px !important;
  }

  .el-collapse-item__content {
    padding-left: 20px !important;
  }

  .vn-drawer__body {
    color: var(--vn-color-gray-light-9);
    flex: 1;
    overflow: auto;
    /* padding: 16px 16px 24px; */
  }
}

.drawer-section {
  padding-left: 20px;

  .drawer-item {
    padding: 8px 0;
    display: flex;
    align-items: center;
    gap: 8px;

    .drawer-label {
      font-weight: 600;
      color: var(--rs-text);
      font-size: 14px;
      min-width: 100px;
      flex-shrink: 0;
    }

    .drawer-value {
      color: var(--rs-text-2);
      font-size: 14px;
      word-break: break-word;
      flex: 1;
    }

    :deep(.el-input) {
      flex: 1;
    }

    :deep(.el-select) {
      flex: 1;
    }

    .boolean-select {
      width: 120px;
    }
  }

  .empty-hint {
    text-align: center;
    color: var(--rs-text-3);
    font-size: 14px;
    padding: 20px 0;
  }

}


.drawer-footer {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding: 16px 0;
}

/* 工具栏/摘要/画布/图例的纵向节奏：
   页签内容顶 +16 → 工具栏 40 → +16 → 摘要 32 → +16 → 画布 flex → +16 → 图例 19.2 */
.graph-display-summary {
  min-height: 32px;
  margin: 16px 0;
  padding: 0;
  align-items: center;
}

.graph-legend-row {
  margin-top: 16px;
  padding: 0 4px;
}

.graph-canvas-hint {
  position: absolute;
  left: 18px;
  top: 16px;
  z-index: 5;
  padding: 3px 6px;
  border-radius: 4px;
  color: var(--rs-text-3, #8794ae);
  background: color-mix(in srgb, var(--rs-canvas-bg, #f8fafd) 85%, transparent);
  pointer-events: none;
}

@media (max-width: 700px) {
  .graph-container {
    min-height: 420px;
  }

  .graph-fullscreen-actions {
    top: 10px;
    right: 10px;
  }

  /* 窄屏内容区被侧栏挤得很窄，提示文字让不出 170px；直接隐藏，避免竖排换行。 */
  .graph-container:has(.graph-fullscreen-actions) .graph-canvas-hint {
    display: none;
  }

  .graph-fullscreen-context {
    top: 56px;
    left: 12px;
    max-width: calc(100% - 24px);
  }

  .graph-visualization.is-fullscreen .graph-controls.is-overlay {
    top: 84px;
    right: 10px;
    width: calc(100% - 20px);
  }

  .graph-controls.is-overlay :deep(.control-search) {
    width: 100%;
  }
}
</style>
