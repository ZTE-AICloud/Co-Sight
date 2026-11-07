<template>
  <div ref="wrapperRef" class="graph-canvas-vis">
    <div ref="containerRef" class="graph-canvas-vis-core" />
    <div
      v-if="edgeHoverPopover.visible"
      class="graph-canvas-vis__edge-popover"
      :style="{
        left: edgeHoverPopover.left + 'px',
        top: edgeHoverPopover.top + 'px'
      }"
    >
      <div class="graph-canvas-vis__edge-popover-content">
        {{ edgeHoverPopover.label }}
      </div>
    </div>
    <div class="graph-canvas-vis__expand-layer" aria-hidden="true">
      <div
        v-for="item in expandIconItems"
        :key="item.nodeId"
        class="node-expand-fab-group"
        :style="{
          left: item.left + 'px',
          top: item.top + 'px'
        }"
      >
        <button
          type="button"
          class="node-expand-fab"
          :style="{
            width: item.sizePx + 'px',
            height: item.sizePx + 'px'
          }"
          :title="item.expanded ? t('modules.kb.collapseChildren') : t('modules.kb.expandChildren')"
          @click.stop="handleExpandIconClick(item.nodeId, $event)"
        >
          <img
            :src="item.expanded ? RemoveIcon : AddIcon"
            :alt="item.expanded ? 'collapse' : 'expand'"
            class="node-expand-fab__img"
            :style="{ width: item.imgSizePx + 'px', height: item.imgSizePx + 'px' }"
          />
        </button>
        <span
          v-if="!item.expanded && item.collapsedHiddenCount > 0"
          class="node-expand-fab__count"
          :style="{
            fontSize: item.badgeFontPx + 'px',
            padding: '0 ' + item.badgePadX + 'px',
            minHeight: item.badgeMinH + 'px',
            lineHeight: item.badgeMinH + 'px'
          }"
        >{{ item.collapsedHiddenCount }}</span>
      </div>
    </div>
  </div>
</template>

<script>
/**
 * 基于 vis-network 的图谱画布（方案 C）
 * - 添加实体/关系后仅 DataSet.add，不整图刷新
 * - 由 vis-network 物理布局保证节点均匀分布
 * - 支持坐标持久化（按 graphId 存 localStorage）
 * 六项行为：① 第二次进入可拖动 ② zoom 与视图同步 ③ 只拖当前节点 ④ 双击打开编辑 ⑤ 悬浮高亮（出向闭包 ∪ 入向闭包及诱导边）、其余降透明度遮罩 ⑥ 仅空白拖动平移
 */
import { ref, watch, onMounted, onBeforeUnmount, computed, nextTick as vueNextTick, defineExpose } from 'vue'
import { useI18n } from 'vue-i18n'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'
import 'vis-network/styles/vis-network.css'
import AddIcon from '@/assets/fonts/add-16.svg'
import RemoveIcon from '@/assets/fonts/remove-16.svg'
import { THEME_CHANGE_EVENT } from '@/shared/lib/theme'
import { separateOverlappingLabels } from '@/features/graph/lib/label-layout'
import { edgeInlineLabel, edgeLabelText } from '@/features/graph/lib/edge-label'
import { LAYOUT_FIT_DEFAULTS, resolveLayoutFit } from '@/features/graph/lib/layout-fit'

/** 将实体类型解析为 colorMap 中的规范 key，保证与图例颜色一致 */
function resolveGroupKey (type, colorMap) {
  if (!type) {
    return 'default'
  }
  const cm = colorMap || {}
  if (cm[type]) {
    return type
  }
  const lower = String(type).toLowerCase()
  const key = Object.keys(cm).find((k) => String(k).toLowerCase() === lower)
  return key || type
}

function getPositionStorageKey (graphId) {
  return graphId ? `kg_positions_${graphId}` : null
}

/** 边数超过此阈值时关闭力导向布局，改用网格初始布局，避免主线程长时间卡死 */
const EDGE_COUNT_PHYSICS_THRESHOLD = 500

/** 节点数超过此阈值同样关闭力导向：节点多边少的图（如星型/树）照样会把主线程打满 */
const NODE_COUNT_PHYSICS_THRESHOLD = 200

/** 边数超过此阈值时降低渲染成本：贝塞尔曲线切直线、关闭悬停高亮重算，缓解大数据量下的交互卡死 */
const EDGE_COUNT_RENDER_THRESHOLD = 800

/** 节点数超过此阈值同样降级渲染（关闭悬停重算），与边阈值取「或」 */
const NODE_COUNT_RENDER_THRESHOLD = 300

/**
 * 节点重叠微调的规模上限。该算法是 O(n²·16)：每个节点都要扫全图位置、最多推 16 轮，
 * 且每轮会触发 DataSet 更新/重绘。500 节点实测能把主线程锁死数分钟（页面无响应）。
 * 大图本来就用网格布局或历史坐标缓存，不做这一步也不会重叠，直接跳过。
 */
const MAX_OVERLAP_RESOLVE_NODES = 120

/**
 * 展开按钮的最小缩放级别：再小按钮已经看不清，且视口内会塞进几百个 DOM 按钮，
 * 每帧重建反而成为卡顿源（大图缩放到全局时必然发生）。
 */
const MIN_EXPAND_ICON_SCALE = 0.35

/** 展开按钮视口裁剪的外扩像素（让按钮在边缘滑入滑出时不闪） */
const EXPAND_ICON_VIEWPORT_MARGIN_PX = 8

/** 平行边扇形曲率基准与每档增量（roundness = 基准 + 增量 × t，t∈[0,1] 按奇偶分组内序号铺开） */
const PARALLEL_EDGE_ROUNDNESS_BASE = 0.1
const PARALLEL_EDGE_ROUNDNESS_STEP = 0.25
const PARALLEL_EDGE_ROUNDNESS_DECIMALS = 3
/**
 * 画布配色全部读设计系统的 --rs-* 令牌，
 * 浅色 / 深色各一套。令牌值在 init 与主题切换时缓存一次，避免逐帧 getComputedStyle。
 */
const GRAPH_VIS_COLOR_FALLBACKS = {
  light: {
    canvasBackground: '#f8fafd',
    edgeNormal: '#8faedc',
    edgeHover: '#1677ff',
    edgeSelected: '#1677ff',
    nodeLabel: '#536383',
    edgeLabel: '#8794ae',
    defaultNode: '#1677ff',
    card: '#ffffff'
  },
  dark: {
    canvasBackground: '#121b29',
    edgeNormal: '#7290b7',
    edgeHover: '#6aa9ff',
    edgeSelected: '#6aa9ff',
    nodeLabel: '#b3c0d5',
    edgeLabel: '#8f9fb8',
    defaultNode: '#78b3ff',
    card: '#192230'
  }
}

function readCssVar (name, fallback) {
  if (typeof document === 'undefined' || !document.documentElement) {
    return fallback
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function isDarkTheme () {
  return typeof document !== 'undefined' &&
    !!document.documentElement &&
    document.documentElement.classList.contains('dark')
}

let cachedGraphVisColors = null

function refreshGraphVisColors () {
  const palette = GRAPH_VIS_COLOR_FALLBACKS[isDarkTheme() ? 'dark' : 'light']
  cachedGraphVisColors = {
    canvasBackground: readCssVar('--rs-canvas-bg', palette.canvasBackground),
    edgeNormal: readCssVar('--rs-edge', palette.edgeNormal),
    edgeHover: readCssVar('--rs-primary', palette.edgeHover),
    edgeSelected: readCssVar('--rs-primary', palette.edgeSelected),
    nodeLabel: readCssVar('--rs-text-2', palette.nodeLabel),
    edgeLabel: readCssVar('--rs-text-3', palette.edgeLabel),
    defaultNode: readCssVar('--rs-tone-blue', palette.defaultNode),
    card: readCssVar('--rs-bg-card', palette.card)
  }
  return cachedGraphVisColors
}

function getGraphVisColors () {
  return cachedGraphVisColors || refreshGraphVisColors()
}

/** 普通边 1.4px；命中/选中的相关边 2px */
const EDGE_NORMAL_WIDTH = 1.4
const EDGE_ACTIVE_WIDTH_DELTA = 0.6
/** 边标签 12px（--rs-font-size-caption），节点名 13px（--rs-font-size-secondary） */
const NODE_LABEL_FONT_SIZE = 13
const NODE_NAME_FONT_SIZE = 13
const EDGE_LABEL_FONT_SIZE = 12

/* 节点几何与字号：100% 缩放时的基准尺寸 */
const NODE_DOT_RADIUS = 23
const NODE_HALO_RADIUS = 31
const NODE_INITIAL_FONT_SIZE = 14
const NODE_INITIAL_BASELINE_Y = 5
const NODE_NAME_OFFSET_Y = 44
const NODE_BORDER_WIDTH = 1.5
const NODE_FILL_OPACITY = 0.13
const NODE_HALO_FILL_OPACITY = 0.6
const NODE_HALO_STROKE_OPACITY = 0.4
const NODE_HALO_STROKE_WIDTH = 2
const NODE_HALO_SELECTED_STROKE_WIDTH = 3
const NODE_NAME_OUTLINE_WIDTH = 4
/**
 * 箭头约 11px：vis 的 length = 15 * scaleFactor + 3 * width。
 * 7px（0.2）实测太小看不清；同时配合 arrowStrikethrough=false，
 * 让箭头画在节点外沿而不是被节点圆盖住根部。
 */
const EDGE_ARROW_SCALE_FACTOR = 0.45
/** 图标相对节点外沿的额外偏移（画布坐标，与 nodes.size 一致量纲） */
const NODE_EXPAND_ICON_PAD = 4
/** 缩放为 100% 时，内层 SVG 图标基准边长（屏幕 px）；外层按钮 = 内层 + 2（每边各多 1px 留白） */
const EXPAND_ICON_BASE_PX = 16
const EXPAND_ICON_MIN_PX = 3
// 放大时需要继续按比例增长；原上限 28 在较高缩放下会过早触顶，造成“放大不变大”的观感
const EXPAND_ICON_MAX_PX = 64

function clampExpandIconSizePx (viewScale) {
  const s = Number.isFinite(viewScale) && viewScale > 0 ? viewScale : 1
  const raw = EXPAND_ICON_BASE_PX * s
  return Math.min(EXPAND_ICON_MAX_PX, Math.max(EXPAND_ICON_MIN_PX, raw))
}

export default {
  name: 'GraphCanvasVis',
  props: {
    graphData: {
      type: Object,
      default: () => ({ entities: [], edges: [] })
    },
    colorMap: {
      type: Object,
      default: () => ({})
    },
    edgeColorMap: {
      type: Object,
      default: () => ({})
    },
    graphId: {
      type: String,
      default: ''
    },
    resetToken: {
      type: Number,
      default: 0
    },
    /** 因「收起出向子实体」而需持久隐藏的节点 id（与父组件 hiddenNodeIds 同步，string[]） */
    persistentlyHiddenNodeIds: {
      type: Array,
      default: () => []
    },
    /** 实体展开状态：key 为节点 id（string），value 为 true 表示展开（显示减号） */
    entityExpandStateMap: {
      type: Object,
      default: () => ({})
    },
    /** 边标签展示模式：inline=常显；hover=仅悬浮边显示（默认 hover） */
    edgeLabelDisplayMode: {
      type: String,
      default: 'hover'
    }
  },
  emits: ['node-click', 'edge-click', 'container-click', 'zoom-change', 'node-double-click', 'edge-double-click', 'toggle-expand', 'after-drawing'],
  setup (props, { emit }) {
    const { t } = useI18n()
    const wrapperRef = ref(null)
    const containerRef = ref(null)
    let network = null
    let panCleanup = null
    const nodesDataSet = new DataSet([])
    const edgesDataSet = new DataSet([])
    /** 节点 id → 实体名（自绘标签用；不放进 vis label，避免 labelModule 再量一遍） */
    let nodeNameById = new Map()
    /** 节点自绘用的颜色/字体缓存（init 与主题切换时刷新） */
    let nodePaint = null

    // ============ 邻接表缓存（大数据量展开/收起子孙计算专用） ============
    // 以 String(id) 为 key 的出向邻接表，避免闭包 BFS 每次都对全量边做线性扫描（O(E) per 节点 → O(V×E)）
    let outgoingAdjacency = new Map()
    let adjacencyDirty = true
    // 大图渲染降级开关是否已应用（null=未初始化），避免重复 setOptions 触发无谓重绘
    let renderReductionApplied = null
    // 平行边分组缓存：key 为边 id，value 为 { idx, count }（同一对 from→to 之间的第 idx 条 / 共 count 条）。
    // 用于给平行边逐边定制曲率，避免 vis-network 将它们渲染成完全重叠的一条线
    let parallelEdgeMap = new Map()

    const entities = computed(() => props.graphData?.entities || [])
    const edges = computed(() => props.graphData?.edges || [])

    const expandIconItems = ref([])
    /** 当前鼠标悬浮的节点 id（用于收起/展开后立刻按「闭包高亮 + 持久隐藏」重算，无需再次悬浮） */
    const hoveredNodeIdRef = ref(null)
    const selectedNodeIdRef = ref(null)
    const hoveredEdgeIdRef = ref(null)
    const edgeLabelModeRef = ref(props.edgeLabelDisplayMode || 'hover')
    const edgeHoverPopover = ref({
      visible: false,
      label: '',
      left: 0,
      top: 0
    })

    // 大图缩放期间临时隐藏边（见 network.on('zoom')）。状态只在本组件内，
    // 恢复时统一走 applyPersistentVisibility，避免与持久隐藏/高亮互相覆盖。
    let zoomEdgesHidden = false
    let zoomEdgeRestoreTimer = null
    function hideEdgesDuringZoom () {
      if (!renderReductionApplied || zoomEdgesHidden || !network) {
        return
      }
      zoomEdgesHidden = true
      const updates = []
      edgesDataSet.forEach((edge) => {
        if (!edge.hidden) {
          updates.push({ id: edge.id, hidden: true })
        }
      })
      if (updates.length) {
        edgesDataSet.update(updates)
      }
    }
    function scheduleRestoreEdgesAfterZoom () {
      if (!zoomEdgesHidden) {
        return
      }
      if (zoomEdgeRestoreTimer) {
        clearTimeout(zoomEdgeRestoreTimer)
      }
      zoomEdgeRestoreTimer = setTimeout(() => {
        zoomEdgeRestoreTimer = null
        zoomEdgesHidden = false
        applyCurrentVisibilityState()
        if (network) {
          network.redraw()
        }
        scheduleUpdateExpandOverlays()
      }, 180)
    }

    let expandOverlayRafScheduled = false
    // 展开按钮的静态信息缓存：拓扑（边）、展开态、持久隐藏变化时才重建；
    // 每帧只做位置换算 + 视口裁剪，避免 O(n·(V+E)) 的闭包 DFS 把主线程打满。
    let overlayStaticDirty = true
    let overlayStaticItems = []
    function scheduleUpdateExpandOverlays () {
      if (expandOverlayRafScheduled) {
        return
      }
      expandOverlayRafScheduled = true
      requestAnimationFrame(() => {
        expandOverlayRafScheduled = false
        updateExpandOverlays()
      })
    }

    function ensureOverlayStaticItems () {
      if (!overlayStaticDirty) {
        return
      }
      const hidden = new Set((props.persistentlyHiddenNodeIds || []).map(String))
      const outgoingSources = new Set()
      edges.value.forEach((e) => {
        outgoingSources.add(String(e.source_id || e.source))
      })
      const m = props.entityExpandStateMap || {}
      const items = []
      nodesDataSet.getIds().forEach((nodeId) => {
        const sid = String(nodeId)
        if (!outgoingSources.has(sid)) {
          return
        }
        if (hidden.has(sid)) {
          return
        }
        const outClosure = getOutgoingClosureNodeIds(sid)
        outClosure.delete(sid)
        let collapsedHiddenCount = 0
        outClosure.forEach((id) => {
          if (hidden.has(id)) {
            collapsedHiddenCount++
          }
        })
        items.push({
          nodeId: sid,
          expanded: m[sid] !== false,
          collapsedHiddenCount
        })
      })
      overlayStaticItems = items
      overlayStaticDirty = false
    }

    function updateExpandOverlays () {
      if (!network || !containerRef.value) {
        expandIconItems.value = []
        return
      }
      const viewScale = network.getScale() || 1
      // 缩放过小时按钮不可用，且全图节点都在视口内 → 每帧重建上千个 DOM 按钮，
      // 正是大图缩到全局时卡死的主因。直接不渲染。
      if (viewScale < MIN_EXPAND_ICON_SCALE) {
        if (expandIconItems.value.length) {
          expandIconItems.value = []
        }
        return
      }
      // 静态信息（哪些节点有展开按钮、展开态、收起后的隐藏数）只在拓扑/展开态变化时重算；
      // 不要每帧对每个节点跑一次出向闭包 DFS：500 节点时单帧就是几十万次操作。
      ensureOverlayStaticItems()
      const positions = network.getPositions()
      const rect = containerRef.value.getBoundingClientRect()
      const corner = NODE_DOT_RADIUS * Math.SQRT1_2 + NODE_EXPAND_ICON_PAD
      const imgSizePx = clampExpandIconSizePx(viewScale)
      const sizePx = imgSizePx + 2
      const half = sizePx / 2
      const margin = sizePx + EXPAND_ICON_VIEWPORT_MARGIN_PX
      const items = []
      overlayStaticItems.forEach((staticItem) => {
        const sid = staticItem.nodeId
        const pos = positions[sid]
        if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
          return
        }
        const dom = network.canvasToDOM({ x: pos.x + corner, y: pos.y - corner })
        // 视口裁剪：屏幕外的按钮不渲染、也不参与每帧 diff
        if (dom.x < -margin || dom.y < -margin ||
            dom.x > rect.width + margin || dom.y > rect.height + margin) {
          return
        }
        const badgeFontPx = Math.max(9, Math.round(sizePx * 0.5))
        const badgePadX = Math.max(6, Math.round(sizePx * 0.22))
        const badgeMinH = Math.max(sizePx * 0.85, badgeFontPx + 4)
        items.push({
          nodeId: sid,
          left: dom.x - half,
          top: dom.y - half,
          sizePx,
          imgSizePx,
          expanded: staticItem.expanded,
          collapsedHiddenCount: staticItem.collapsedHiddenCount,
          badgeFontPx,
          badgePadX,
          badgeMinH
        })
      })
      expandIconItems.value = items
    }

    function handleExpandIconClick (nodeId, ev) {
      ev?.stopPropagation?.()
      emit('toggle-expand', nodeId)
    }

    function refreshExpandOverlay () {
      scheduleUpdateExpandOverlays()
    }

    /**
     * 按 props.persistentlyHiddenNodeIds 同步节点/边 hidden，并强制重绘。
     * 若正悬浮在某节点上，则保持「出向/入向闭包高亮」逻辑并与持久隐藏合并（否则收起/展开后需再次悬浮才刷新）。
     */
    function syncVisibilityFromHiddenProps () {
      if (!network) {
        return
      }
      applyCurrentVisibilityState()
      network.redraw()
      scheduleUpdateExpandOverlays()
      emit('after-drawing')
    }

    function getNetwork () {
      return network
    }

    function loadPositionCache () {
      const key = getPositionStorageKey(props.graphId)
      if (!key) {
        return {}
      }
      try {
        const raw = localStorage.getItem(key)
        if (!raw) {
          return {}
        }
        const data = JSON.parse(raw)
        return data && typeof data === 'object' ? data : {}
      } catch {
        return {}
      }
    }

    function savePositionCache (positions) {
      const key = getPositionStorageKey(props.graphId)
      if (!key || !positions || Object.keys(positions).length === 0) {
        return
      }
      try {
        localStorage.setItem(key, JSON.stringify(positions))
      } catch (e) {
        console.warn('保存图谱坐标失败', e)
      }
    }

    function clearPositionCache () {
      const key = getPositionStorageKey(props.graphId)
      if (!key) {
        return
      }
      try {
        localStorage.removeItem(key)
      } catch (e) {
        console.warn('清除图谱坐标缓存失败', e)
      }
    }

    /**
     * 节点显示名：属性里的 name（与实体编辑抽屉同源）优先，其次 entity_name，最后回退 id。
     * 后端 entity_name 可能存的是 `ent_xxx` 这类标识，直接当标签会看不出实体是谁。
     */
    function resolveEntityDisplayName (entity, id) {
      const properties = entity?.properties
      const propertyName = properties && typeof properties === 'object' && !Array.isArray(properties)
        ? properties.name
        : ''
      return String(propertyName || entity?.entity_name || entity?.entity_id || id || '').trim()
    }

    function entityToVisNode (entity, positionCache) {
      const id = entity.entity_id || entity.id
      const name = resolveEntityDisplayName(entity, id)
      nodeNameById.set(String(id), name)
      const rawType = entity.entity_type || entity.class || ''
      const group = resolveGroupKey(rawType, props.colorMap) || 'default'
      const pos = positionCache[id] || (entity.x != null && entity.y != null ? { x: entity.x, y: entity.y } : null)
      const node = {
        id,
        // 名称由 ctxRenderer 自绘（单行、带描边）；vis 的 label 留空，避免再量一遍
        label: '',
        group,
        shape: 'custom',
        size: NODE_DOT_RADIUS,
        ctxRenderer: drawPrototypeNode,
        font: buildNodeFont()
      }
      if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
        node.x = pos.x
        node.y = pos.y
        // 不设置 fixed，保证第二次进入或稳定后节点可拖动，且只拖当前节点（问题 1、3）
      }
      return node
    }

    function buildDefaultEdgeColor (opacity = 1) {
      const colors = getGraphVisColors()
      return {
        color: colors.edgeNormal,
        highlight: colors.edgeSelected,
        hover: colors.edgeHover,
        inherit: false,
        opacity
      }
    }

    // 浏览器可能把 rgba() 序列化成 hsla()（见 --rs-graph-edge-muted）；
    // 用 canvas 的 fillStyle 统一归一化成 #rrggbb / rgba()，再做 alpha 计算。
    let colorNormalizeCtx = null
    function normalizeCssColor (value) {
      if (typeof document === 'undefined') {
        return value
      }
      try {
        if (!colorNormalizeCtx) {
          colorNormalizeCtx = document.createElement('canvas').getContext('2d')
        }
        if (!colorNormalizeCtx) {
          return value
        }
        colorNormalizeCtx.fillStyle = '#000000'
        colorNormalizeCtx.fillStyle = value
        return colorNormalizeCtx.fillStyle
      } catch (e) {
        return value
      }
    }

    /** #rgb / #rrggbb / rgb() / rgba() → rgba()，保留主题 token 的 alpha */
    function colorToRgba (color, opacity = 1) {
      const text = String(normalizeCssColor(color) || '').trim()
      const alpha = Math.max(0, Math.min(1, opacity))
      const hexMatch = text.match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/)
      if (hexMatch) {
        const normalized = hexMatch[1].length === 3
          ? hexMatch[1].split('').map((x) => `${x}${x}`).join('')
          : hexMatch[1]
        const r = parseInt(normalized.slice(0, 2), 16)
        const g = parseInt(normalized.slice(2, 4), 16)
        const b = parseInt(normalized.slice(4, 6), 16)
        return `rgba(${r}, ${g}, ${b}, ${alpha})`
      }
      const rgbMatch = text.match(/^rgba?\(([^)]+)\)$/)
      if (rgbMatch) {
        const parts = rgbMatch[1].split(',').map((part) => Number(part.trim()))
        if (parts.length >= 3 && parts.slice(0, 3).every(Number.isFinite)) {
          const baseAlpha = parts.length >= 4 && Number.isFinite(parts[3]) ? parts[3] : 1
          return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${baseAlpha * alpha})`
        }
      }
      return `rgba(0, 0, 0, ${alpha})`
    }

    /** 刷新节点自绘的缓存颜色/字体（init 与主题切换时调用，避免逐帧读 CSS） */
    function refreshNodePaint () {
      const colors = getGraphVisColors()
      nodePaint = {
        fontFamily: readCssVar('--rs-font-family', 'sans-serif'),
        canvasBg: colors.canvasBackground,
        nameColor: colors.nodeLabel,
        haloFill: colorToRgba(colors.card, NODE_HALO_FILL_OPACITY),
        fallbackTone: colors.defaultNode
      }
      return nodePaint
    }

    function getNodePaint () {
      return nodePaint || refreshNodePaint()
    }

    function firstChar (text) {
      const chars = Array.from(String(text || '').trim())
      return chars.length ? chars[0] : ''
    }

    /**
     * 把连线/箭头的端点统一裁到「节点圆外沿」。
     *
     * 自定义形状（ctxRenderer）默认走 ShapeBase._distanceToBorder 的**外接矩形**：
     * 横/竖边接在圆上，斜边停在外接矩形边界（比圆远 ~9px），箭头和圆之间会留缝。
     * 这里按固定半径覆盖，四个方向都在圆上收口。
     */
    function applyNodeBorderClip () {
      const nodes = network?.body?.nodes
      if (!nodes) {
        return
      }
      Object.values(nodes).forEach((node) => {
        if (node.__rsCircleBorderClip) {
          return
        }
        node.distanceToBorder = () => NODE_DOT_RADIUS + NODE_BORDER_WIDTH
        node.__rsCircleBorderClip = true
      })
    }

    /**
     * 节点样式：半透明同色填充 + 1.5px 同色描边 + 居中首字 + 节点名。
     * 悬浮/选中时额外画一圈 40% 透明度的同色光环（`.graph-node-halo`）。
     * 用 ctxRenderer 自绘而非 vis 的 dot，才能同时画出「首字」和光环。
     */
    function drawPrototypeNode ({ ctx, id, x, y, state, style }) {
      const paint = getNodePaint()
      const tone = style.borderColor || paint.fallbackTone
      const opacity = Number.isFinite(style.opacity) ? style.opacity : 1
      const name = nodeNameById.get(String(id)) || ''
      const initial = firstChar(name)
      const selected = !!state?.selected
      const hover = !!state?.hover

      ctx.save()
      ctx.globalAlpha = opacity

      // 光环底色（.graph-node-halo：--rs-bg-card 60%），让节点从连线上“浮”出来
      ctx.beginPath()
      ctx.arc(x, y, NODE_HALO_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = paint.haloFill
      ctx.fill()
      if (hover || selected) {
        ctx.beginPath()
        ctx.arc(x, y, NODE_HALO_RADIUS, 0, Math.PI * 2)
        ctx.strokeStyle = colorToRgba(tone, NODE_HALO_STROKE_OPACITY)
        ctx.lineWidth = selected ? NODE_HALO_SELECTED_STROKE_WIDTH : NODE_HALO_STROKE_WIDTH
        ctx.stroke()
      }

      // 节点本体：先用不透明底色铺满，再叠浅色填充 + 同色描边。
      // vis 的连线是从**源节点圆心**画起的（drawArrows 只把 toPoint 移到箭头尾部，
      // 源点永远是 center）；13% 半透明填充会让线透过节点内部，看起来像从圆心出发。
      ctx.beginPath()
      ctx.arc(x, y, NODE_DOT_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = paint.canvasBg
      ctx.fill()

      ctx.beginPath()
      ctx.arc(x, y, NODE_DOT_RADIUS, 0, Math.PI * 2)
      ctx.fillStyle = colorToRgba(tone, NODE_FILL_OPACITY)
      ctx.fill()
      ctx.strokeStyle = tone
      ctx.lineWidth = NODE_BORDER_WIDTH
      ctx.stroke()

      // 居中首字（.node-initial：14px / 600）
      if (initial) {
        ctx.fillStyle = tone
        ctx.font = `600 ${NODE_INITIAL_FONT_SIZE}px ${paint.fontFamily}`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'alphabetic'
        ctx.fillText(initial, x, y + NODE_INITIAL_BASELINE_Y)
      }
      ctx.restore()

      return {
        // 节点名画在箭头之上（名称压在连线之上）；4px 画布底色描边保证压线时仍可读
        drawExternalLabel: () => {
          if (!name) {
            return
          }
          ctx.save()
          ctx.globalAlpha = opacity
          ctx.font = `${NODE_NAME_FONT_SIZE}px ${paint.fontFamily}`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'alphabetic'
          ctx.lineJoin = 'round'
          ctx.lineWidth = NODE_NAME_OUTLINE_WIDTH
          ctx.strokeStyle = paint.canvasBg
          ctx.strokeText(name, x, y + NODE_NAME_OFFSET_Y)
          ctx.fillStyle = paint.nameColor
          ctx.fillText(name, x, y + NODE_NAME_OFFSET_Y)
          ctx.restore()
        },
        nodeDimensions: {
          width: NODE_DOT_RADIUS * 2,
          height: NODE_DOT_RADIUS * 2
        }
      }
    }

    function buildNodeFont (opacity = 1) {
      return {
        color: colorToRgba(getGraphVisColors().nodeLabel, opacity),
        size: NODE_LABEL_FONT_SIZE
      }
    }

    function buildEdgeFont (showInline, opacity = 1) {
      const colors = getGraphVisColors()
      if (!showInline) {
        return {
          align: 'horizontal',
          size: 0,
          color: colorToRgba(colors.nodeLabel, opacity),
          background: 'none',
          strokeWidth: 0,
          strokeColor: 'transparent'
        }
      }
      return {
        // 关系名称是水平文本（不随连线旋转）
        align: 'horizontal',
        size: EDGE_LABEL_FONT_SIZE,
        color: colorToRgba(colors.edgeLabel, opacity),
        background: colorToRgba(colors.canvasBackground, opacity),
        strokeWidth: 4,
        strokeColor: colorToRgba(colors.canvasBackground, opacity)
      }
    }

    function buildEmphasizedEdgeColor (state, opacity = 1) {
      const colors = getGraphVisColors()
      const activeColor = state === 'selected' ? colors.edgeSelected : colors.edgeHover
      return {
        color: activeColor,
        highlight: activeColor,
        hover: activeColor,
        inherit: false,
        opacity
      }
    }

    function edgeToVisEdge (edge) {
      const id = edge.edge_id || edge.id
      const showInline = edgeLabelModeRef.value !== 'hover'
      const result = {
        id,
        from: edge.source_id || edge.source,
        to: edge.target_id || edge.target,
        label: showInline ? edgeInlineLabel(edge) : '',
        arrows: { to: { enabled: true, scaleFactor: EDGE_ARROW_SCALE_FACTOR } },
        // 默认 true 会把箭头画到节点边界内、被节点圆/光环盖住根部；
        // false 让连线停在箭头 core 处，箭头完整露在节点外侧。
        arrowStrikethrough: false,
        width: EDGE_NORMAL_WIDTH,
        color: buildDefaultEdgeColor(),
        font: buildEdgeFont(showInline)
      }
      // 同一对节点间的平行边：vis-network 会给它们完全相同的几何路径导致完全重叠，
      // 这里逐边定制曲率（交替 curvedCW/curvedCCW + roundness 铺开）形成对称扇形，使其可辨识
      const parallel = parallelEdgeMap.get(id)
      if (parallel && parallel.count > 1) {
        const { idx, count } = parallel
        const dir = idx % 2 === 0 ? 'curvedCW' : 'curvedCCW'
        const groupIdx = Math.floor(idx / 2)
        const groupSize = Math.ceil(count / 2)
        const t = groupIdx / Math.max(1, groupSize - 1)
        result.smooth = {
          enabled: true,
          type: dir,
          roundness: +(PARALLEL_EDGE_ROUNDNESS_BASE + PARALLEL_EDGE_ROUNDNESS_STEP * t).toFixed(PARALLEL_EDGE_ROUNDNESS_DECIMALS)
        }
      }
      return result
    }

    function edgeDisplayLabel (edgeId) {
      return edgeInlineLabel(resolveBackendEdge(edgeId))
    }

    /** 悬浮模式下气泡内展示完整标签（不截断），由样式控制宽度与最多三行 */
    function edgeHoverPopoverFullLabel (edgeId) {
      return edgeLabelText(resolveBackendEdge(edgeId), Number.POSITIVE_INFINITY)
    }

    function applyEdgeLabelDisplayMode (mode = edgeLabelModeRef.value) {
      const hoverMode = mode === 'hover'
      // ⚠️ 必须批量：vis-network 每条 DataSet 事件都会整图重绘，逐边 update 的代价是
      // O(E × 全图重绘)。实测 1618 条边时逐条更新会阻塞主线程 100 秒（每次查询/数据同步都触发）。
      const updates = []
      edgesDataSet.forEach((edge) => {
        const label = hoverMode ? '' : edgeDisplayLabel(edge.id)
        // 标签没变就不提交：limit 不变的重查、hover 模式下同步数据都不会产生任何更新
        if (String(edge.label || '') === String(label || '')) {
          return
        }
        updates.push({
          id: edge.id,
          label,
          font: buildEdgeFont(!hoverMode)
        })
      })
      if (updates.length) {
        edgesDataSet.update(updates)
      }
      if (hoverMode && hoveredEdgeIdRef.value != null && edgesDataSet.get(hoveredEdgeIdRef.value)) {
        edgesDataSet.update({
          id: hoveredEdgeIdRef.value,
          label: edgeDisplayLabel(hoveredEdgeIdRef.value),
          font: buildEdgeFont(false)
        })
      }
      if (network) {
        network.redraw()
      }
    }

    function setEdgeLabelMode (mode) {
      edgeLabelModeRef.value = mode === 'hover' ? 'hover' : 'inline'
      hoveredEdgeIdRef.value = null
      edgeHoverPopover.value = {
        visible: false,
        label: '',
        left: 0,
        top: 0
      }
      applyEdgeLabelDisplayMode(edgeLabelModeRef.value)
    }

    function updateEdgeHoverPopover (edgeId, domPoint) {
      if (!wrapperRef.value || !domPoint) {
        edgeHoverPopover.value = {
          visible: false,
          label: '',
          left: 0,
          top: 0
        }
        return
      }
      const label = edgeHoverPopoverFullLabel(edgeId)
      if (!label) {
        edgeHoverPopover.value = {
          visible: false,
          label: '',
          left: 0,
          top: 0
        }
        return
      }
      edgeHoverPopover.value = {
        visible: true,
        label,
        left: domPoint.x,
        top: Math.max(8, domPoint.y - 12)
      }
    }

    function resolveBackendEdge (visEdgeId) {
      return edges.value.find((e) => String(e.edge_id || e.id) === String(visEdgeId))
    }

    function buildGroupsOption () {
      const groups = {}
      const cm = props.colorMap || {}
      Object.keys(cm).forEach((type) => {
        const base = cm[type]
        const config = {
          // 圆形节点是「浅色填充 + 同色描边」，不是整块实心色。
          color: {
            background: colorToRgba(base, 0.13),
            border: base,
            highlight: { background: colorToRgba(base, 0.22), border: base },
            hover: { background: colorToRgba(base, 0.18), border: base }
          },
          font: buildNodeFont()
        }
        groups[type] = config
        const lower = String(type).toLowerCase()
        if (lower !== type && !groups[lower]) {
          groups[lower] = config
        }
      })
      if (!groups.default) {
        const fallback = getGraphVisColors().defaultNode
        groups.default = {
          color: {
            background: colorToRgba(fallback, 0.13),
            border: fallback,
            highlight: { background: colorToRgba(fallback, 0.22), border: fallback },
            hover: { background: colorToRgba(fallback, 0.18), border: fallback }
          },
          font: buildNodeFont()
        }
      }
      return groups
    }

    /** 以 edges.value 重建出向邻接表缓存（仅当数据发生变更时调用，见 syncDataToVis） */
    function rebuildAdjacency () {
      outgoingAdjacency = new Map()
      overlayStaticDirty = true
      edges.value.forEach((e) => {
        const from = String(e.source_id || e.source)
        const to = String(e.target_id || e.target)
        if (!outgoingAdjacency.has(from)) {
          outgoingAdjacency.set(from, new Set())
        }
        outgoingAdjacency.get(from).add(to)
      })
      adjacencyDirty = false
    }

    function ensureAdjacency () {
      if (adjacencyDirty) {
        rebuildAdjacency()
      }
    }

    /** 以 edges.value 重建平行边分组缓存：同一对 source→target 之间的边，记录各边序号 idx 与组大小 count */
    function rebuildParallelEdgeMap () {
      const groups = new Map()
      edges.value.forEach((e) => {
        const key = `${String(e.source_id || e.source)}|${String(e.target_id || e.target)}`
        if (!groups.has(key)) {
          groups.set(key, [])
        }
        groups.get(key).push(e)
      })
      parallelEdgeMap = new Map()
      groups.forEach((group) => {
        if (group.length < 2) {
          return
        }
        group.forEach((e, i) => {
          parallelEdgeMap.set(e.edge_id || e.id, { idx: i, count: group.length })
        })
      })
    }

    /**
     * 从 startId 沿有向边 source→target 递归可达的所有节点（含起点，环用 visited 截断）。
     * 基于邻接表缓存 BFS，避免对全量边线性扫描（原 O(V×E)，现 O(V+E) 摊还）。
     */
    function getOutgoingClosureNodeIds (startId) {
      ensureAdjacency()
      const result = new Set()
      const stack = [String(startId)]
      const seen = new Set()
      while (stack.length) {
        const id = stack.pop()
        if (seen.has(id)) {
          continue
        }
        seen.add(id)
        result.add(id)
        const targets = outgoingAdjacency.get(id)
        if (targets) {
          targets.forEach((t) => {
            if (!seen.has(t)) {
              stack.push(t)
            }
          })
        }
      }
      return result
    }

    /**
     * 与 centerNodeId 直接相连的边（source 或 target 命中）。
     * 与 `.graph-edge.related` 口径一致：只加深关系线，不遮挡其它节点/边。
     */
    function getIncidentEdgeIdSet (centerNodeId) {
      const center = String(centerNodeId)
      const edgeIds = new Set()
      edges.value.forEach((e) => {
        const from = String(e.source_id || e.source)
        const to = String(e.target_id || e.target)
        if (from === center || to === center) {
          edgeIds.add(String(e.edge_id || e.id))
        }
      })
      return edgeIds
    }

    function getPersistentHiddenSet () {
      return new Set((props.persistentlyHiddenNodeIds || []).map(String))
    }

    /** 恢复为「仅持久隐藏」下的全图可见性（所有节点/边不透明） */
    function applyPersistentVisibility () {
      const hidden = getPersistentHiddenSet()
      // 批量提交：逐条 update 在 500 节点/1600 边的图上每次点击都会触发上千次重绘
      const nodeUpdates = []
      nodesDataSet.forEach((node) => {
        const h = hidden.has(String(node.id))
        nodeUpdates.push({ id: node.id, hidden: h, opacity: 1, font: buildNodeFont() })
      })
      if (nodeUpdates.length) {
        nodesDataSet.update(nodeUpdates)
      }
      const labelVisible = edgeLabelModeRef.value !== 'hover'
      const edgeUpdates = []
      edgesDataSet.forEach((edge) => {
        const hideEdge = hidden.has(String(edge.from)) || hidden.has(String(edge.to))
        edgeUpdates.push({
          id: edge.id,
          hidden: hideEdge,
          width: EDGE_NORMAL_WIDTH,
          color: buildDefaultEdgeColor(),
          font: buildEdgeFont(labelVisible)
        })
      })
      if (edgeUpdates.length) {
        edgesDataSet.update(edgeUpdates)
      }
    }

    /**
     * 焦点节点（选中/悬浮）：只把与之直接相连的关系线加粗并换成强调色；
     * 其它节点与边保持原样——不隐藏也不降低透明度。
     */
    function applyNodeFocusVisibility (centerNodeId, state) {
      const edgeIds = getIncidentEdgeIdSet(centerNodeId)
      const hidden = getPersistentHiddenSet()
      // 批量提交：点击/悬浮一次要扫全图，逐条 update 会让大图每次点击卡数百毫秒
      const nodeUpdates = []
      nodesDataSet.forEach((node) => {
        const h = hidden.has(String(node.id))
        nodeUpdates.push({ id: node.id, hidden: h, opacity: 1, font: buildNodeFont() })
      })
      if (nodeUpdates.length) {
        nodesDataSet.update(nodeUpdates)
      }
      const labelVisible = edgeLabelModeRef.value !== 'hover'
      const defaultColor = buildDefaultEdgeColor()
      const emphasizedColor = buildEmphasizedEdgeColor(state)
      const edgeUpdates = []
      edgesDataSet.forEach((edge) => {
        const fromH = hidden.has(String(edge.from))
        const toH = hidden.has(String(edge.to))
        if (fromH || toH) {
          edgeUpdates.push({
            id: edge.id,
            hidden: true,
            width: EDGE_NORMAL_WIDTH,
            color: defaultColor,
            font: buildEdgeFont(labelVisible)
          })
          return
        }
        const inHighlight = isInEdgeIdSet(edgeIds, edge.id)
        edgeUpdates.push({
          id: edge.id,
          hidden: false,
          width: inHighlight ? EDGE_NORMAL_WIDTH + EDGE_ACTIVE_WIDTH_DELTA : EDGE_NORMAL_WIDTH,
          color: inHighlight ? emphasizedColor : defaultColor,
          font: buildEdgeFont(labelVisible)
        })
      })
      if (edgeUpdates.length) {
        edgesDataSet.update(edgeUpdates)
      }
    }

    // 所有传入的 idSet 均已统一为 String-keyed（见 getIncidentEdgeIdSet/getPersistentHiddenSet），
    // 直接 String 查找即可，避免对集合的线性回退扫描
    function isInEdgeIdSet (idSet, edgeId) {
      return idSet.has(String(edgeId))
    }

    function applyCurrentVisibilityState () {
      const hasHoveredNode = hoveredNodeIdRef.value !== null && hoveredNodeIdRef.value !== undefined
      const hasSelectedNode = selectedNodeIdRef.value !== null && selectedNodeIdRef.value !== undefined
      const hoveredMatchesSelected = hasHoveredNode && hasSelectedNode &&
        String(hoveredNodeIdRef.value) === String(selectedNodeIdRef.value)
      if (hasSelectedNode && (!hasHoveredNode || hoveredMatchesSelected)) {
        applyNodeFocusVisibility(selectedNodeIdRef.value, 'selected')
        return
      }
      if (hasHoveredNode) {
        applyNodeFocusVisibility(hoveredNodeIdRef.value, 'hover')
        return
      }
      if (hasSelectedNode) {
        applyNodeFocusVisibility(selectedNodeIdRef.value, 'selected')
        return
      }
      applyPersistentVisibility()
    }

    let prevEntityIds = null
    let prevEdgeIds = null
    let layoutReady = false

    function ensurePhysicsOff () {
      if (!network) {
        return
      }
      const updates = []
      nodesDataSet.forEach((node) => {
        updates.push({ id: node.id, fixed: false })
      })
      if (updates.length) {
        nodesDataSet.update(updates)
      }
      network.setOptions({ physics: { enabled: false } })
    }

    /**
     * 边数超阈值时降低渲染成本：贝塞尔曲线切直线、关闭悬停高亮重算。
     * 用 renderReductionApplied 记录当前状态，仅在大小图切换时 setOptions，避免重复触发重绘。
     */
    function applyRenderCostReduction () {
      if (!network) {
        return
      }
      const isLargeGraph = edgesDataSet.length > EDGE_COUNT_RENDER_THRESHOLD ||
        nodesDataSet.length > NODE_COUNT_RENDER_THRESHOLD
      if (renderReductionApplied === isLargeGraph) {
        return
      }
      renderReductionApplied = isLargeGraph
      network.setOptions({
        // 大图/小图都用直线；平行边的曲率是逐边选项，不受这里覆盖
        edges: { smooth: false },
        interaction: { hover: !isLargeGraph }
      })
    }

    /**
     * 主题切换：只重设颜色 options 并原地更新 DataSet，绝不重建 Network
     * （重建会丢节点坐标/视口/固定状态）。
     */
    function applyThemeToNetwork () {
      if (!network) {
        return
      }
      refreshGraphVisColors()
      refreshNodePaint()
      network.setOptions({
        nodes: { font: buildNodeFont() },
        edges: { color: buildDefaultEdgeColor() },
        groups: buildGroupsOption()
      })
      applyEdgeLabelDisplayMode()
      applyCurrentVisibilityState()
      network.redraw()
      scheduleUpdateExpandOverlays()
    }

    function syncDataToVis () {
      adjacencyDirty = true // 图数据同步后，邻接表缓存标记为过期，闭包计算时按需重建
      overlayStaticDirty = true
      rebuildParallelEdgeMap()
      const positionCache = loadPositionCache()
      const currentEntities = entities.value
      const currentEdges = edges.value
      const currentEntityIds = new Set(currentEntities.map((e) => e.entity_id || e.id))
      const currentEdgeIds = new Set(currentEdges.map((e) => e.edge_id || e.id))

      const isFirstSync = prevEntityIds === null
      const shouldFullSync = isFirstSync || (currentEntityIds.size === 0 && currentEdgeIds.size === 0)

      if (shouldFullSync) {
        nodeNameById = new Map()
        const visNodes = currentEntities.map((e) => entityToVisNode(e, positionCache))
        const visEdges = currentEdges.map(edgeToVisEdge)
        nodesDataSet.clear()
        edgesDataSet.clear()
        if (visNodes.length) {
          nodesDataSet.add(visNodes)
        }
        if (visEdges.length) {
          edgesDataSet.add(visEdges)
        }
        prevEntityIds = new Set(currentEntityIds)
        prevEdgeIds = new Set(currentEdgeIds)
      } else {
        const currentPositions = network ? getPositions() : {}
        const resolvePosition = (id, fromNode) => {
          const fromCache = positionCache[id]
          if (fromCache && Number.isFinite(fromCache.x) && Number.isFinite(fromCache.y)) {
            return fromCache
          }
          if (fromNode && fromNode.x != null && fromNode.y != null && Number.isFinite(fromNode.x) && Number.isFinite(fromNode.y)) {
            return { x: fromNode.x, y: fromNode.y }
          }
          const fromNetwork = currentPositions[id]
          if (fromNetwork && Number.isFinite(fromNetwork.x) && Number.isFinite(fromNetwork.y)) {
            return fromNetwork
          }
          return null
        }

        const addedEntities = currentEntities.filter((e) => !prevEntityIds.has(e.entity_id || e.id))
        const removedEntityIds = [...prevEntityIds].filter((id) => !currentEntityIds.has(id))
        const updatedEntities = currentEntities.filter((e) => {
          const id = e.entity_id || e.id
          return prevEntityIds.has(id) && currentEntityIds.has(id)
        })

        const addedEdges = currentEdges.filter((e) => !prevEdgeIds.has(e.edge_id || e.id))
        const removedEdgeIds = [...prevEdgeIds].filter((id) => !currentEdgeIds.has(id))
        const updatedEdges = currentEdges.filter((e) => {
          const id = e.edge_id || e.id
          return prevEdgeIds.has(id) && currentEdgeIds.has(id)
        })

        // ⚠️ 所有增删改都必须**批量提交**：vis-network 在每个 DataSet 事件后都会整图重绘，
        // 逐条 update 的代价是 O(变更数 × 全图重绘)。实测 250 节点/900 边时
        // 「limit 50 → 250」的增量同步会因此把主线程锁死 60 秒以上。
        if (removedEntityIds.length) {
          nodesDataSet.remove(removedEntityIds)
        }
        removedEntityIds.forEach((id) => nodeNameById.delete(String(id)))
        if (removedEdgeIds.length) {
          edgesDataSet.remove(removedEdgeIds)
        }

        const occupied = toFinitePositionList(currentPositions)
        const anchor = getAnchorFromOccupied(occupied)
        let distributedIndex = 0
        const addedNodes = []
        addedEntities.forEach((e) => {
          const node = entityToVisNode(e, positionCache)
          const pos = resolvePosition(node.id, e)
          if (pos && Number.isFinite(Number(pos.x)) && Number.isFinite(Number(pos.y))) {
            node.x = Number(pos.x)
            node.y = Number(pos.y)
          } else {
            const existing = nodesDataSet.get(node.id)
            if (existing && Number.isFinite(existing.x) && Number.isFinite(existing.y)) {
              node.x = existing.x
              node.y = existing.y
            } else {
              const distributed = getDistributedPositionByIndex(
                distributedIndex,
                occupied,
                anchor,
                getScale(),
                node.id
              )
              node.x = distributed.x
              node.y = distributed.y
              distributedIndex += 1
            }
          }
          addedNodes.push(node)
          if (Number.isFinite(node.x) && Number.isFinite(node.y)) {
            occupied.push({ id: node.id, x: node.x, y: node.y })
          }
        })
        if (addedNodes.length) {
          nodesDataSet.add(addedNodes)
        }
        const addedEdgeItems = addedEdges.map(edgeToVisEdge)
        if (addedEdgeItems.length) {
          edgesDataSet.add(addedEdgeItems)
        }

        const updatedNodeItems = []
        const lateAddedNodes = []
        updatedEntities.forEach((e) => {
          const id = e.entity_id || e.id
          const node = entityToVisNode(e, positionCache)
          const existing = nodesDataSet.get(id)
          const pos = resolvePosition(id, e)
          if (existing) {
            const update = { id, label: node.label, group: node.group, font: buildNodeFont() }
            if (pos && Number.isFinite(Number(pos.x)) && Number.isFinite(Number(pos.y))) {
              update.x = Number(pos.x)
              update.y = Number(pos.y)
            } else if (Number.isFinite(existing.x) && Number.isFinite(existing.y)) {
              update.x = existing.x
              update.y = existing.y
            }
            updatedNodeItems.push(update)
          } else {
            if (pos) {
              node.x = pos.x
              node.y = pos.y
            }
            lateAddedNodes.push(node)
          }
        })
        if (updatedNodeItems.length) {
          nodesDataSet.update(updatedNodeItems)
        }
        if (lateAddedNodes.length) {
          nodesDataSet.add(lateAddedNodes)
        }
        const updatedEdgeItems = []
        const lateAddedEdges = []
        updatedEdges.forEach((e) => {
          const id = e.edge_id || e.id
          const edge = edgeToVisEdge(e)
          if (edgesDataSet.get(id)) {
            updatedEdgeItems.push(edge)
          } else {
            lateAddedEdges.push(edge)
          }
        })
        if (updatedEdgeItems.length) {
          edgesDataSet.update(updatedEdgeItems)
        }
        if (lateAddedEdges.length) {
          edgesDataSet.add(lateAddedEdges)
        }

        prevEntityIds = new Set(currentEntityIds)
        prevEdgeIds = new Set(currentEdgeIds)
      }

      // 仅当布局已就绪（稳定化完成或使用缓存）且为增量同步时才关闭物理，避免首次进入时在稳定化前关闭导致节点聚在中心
      applyEdgeLabelDisplayMode()
      applyCurrentVisibilityState()
      applyRenderCostReduction()
      if (!shouldFullSync && layoutReady) {
        vueNextTick(() => ensurePhysicsOff())
      }
    }

    /** 边数过多时用网格给节点赋初始坐标，避免力导向长时间占满主线程 */
    function applySimpleGridLayout () {
      const ids = nodesDataSet.getIds()
      const n = ids.length
      if (n === 0) {
        return
      }
      const cols = Math.max(1, Math.ceil(Math.sqrt(n)))
      const spacing = 220
      // 批量提交：逐条 update 会触发 n 次重绘（500 节点时叠加重叠微调直接卡死）
      nodesDataSet.update(ids.map((id, i) => ({
        id,
        x: (i % cols) * spacing,
        y: Math.floor(i / cols) * spacing
      })))
    }

    function initNetwork () {
      if (!containerRef.value) {
        return
      }
      refreshGraphVisColors()
      refreshNodePaint()
      const positionCache = loadPositionCache()
      const hasCachedPositions = Object.keys(positionCache).length > 0
      const edgeCount = edgesDataSet.length
      const nodeCount = nodesDataSet.length
      const hasTooManyEdges = edgeCount > EDGE_COUNT_PHYSICS_THRESHOLD ||
        nodeCount > NODE_COUNT_PHYSICS_THRESHOLD
      const isLargeGraph = edgeCount > EDGE_COUNT_RENDER_THRESHOLD ||
        nodeCount > NODE_COUNT_RENDER_THRESHOLD
      renderReductionApplied = isLargeGraph
      if (hasTooManyEdges && !hasCachedPositions) {
        applySimpleGridLayout()
      }
      const data = { nodes: nodesDataSet, edges: edgesDataSet }
      const options = {
        width: '100%',
        height: '100%',
        autoResize: true,
        nodes: {
          shape: 'custom',
          size: NODE_DOT_RADIUS,
          ctxRenderer: drawPrototypeNode,
          font: buildNodeFont()
        },
        edges: {
          width: EDGE_NORMAL_WIDTH,
          color: buildDefaultEdgeColor(),
          hoverWidth: EDGE_ACTIVE_WIDTH_DELTA,
          selectionWidth: EDGE_ACTIVE_WIDTH_DELTA,
          chosen: {
            edge (values, edgeId, selected, hovering) {
              if (!selected && !hovering) {
                return
              }
              values.width = EDGE_NORMAL_WIDTH + EDGE_ACTIVE_WIDTH_DELTA
              const colors = getGraphVisColors()
              values.color = selected ? colors.edgeSelected : colors.edgeHover
            }
          },
          // 直线连线（不是 cubicBezier 曲线）；仅平行边在 edgeToVisEdge 里逐边定制曲率
          smooth: false
        },
        groups: buildGroupsOption(),
        physics: {
          enabled: !hasCachedPositions && !hasTooManyEdges,
          stabilization: { iterations: 200 },
          barnesHut: {
            gravitationalConstant: -8000,
            centralGravity: 0.2,
            springLength: 200,
            springConstant: 0.04,
            avoidOverlap: 1
          }
        },
        interaction: {
          dragNodes: hasCachedPositions || hasTooManyEdges,
          dragView: false,
          zoomView: true,
          hover: !isLargeGraph
        }
      }
      network = new Network(containerRef.value, data, options)

      let panning = false
      let panStartView = null
      let panStartClient = null

      function getCanvasPosition (clientX, clientY) {
        const el = containerRef.value
        if (!el) {
          return { x: 0, y: 0 }
        }
        const rect = el.getBoundingClientRect()
        return { x: clientX - rect.left, y: clientY - rect.top }
      }

      function onCanvasMouseDown (e) {
        if (!network || panning) {
          return
        }
        const pos = getCanvasPosition(e.clientX, e.clientY)
        const nodeId = network.getNodeAt(pos)
        const edgeId = network.getEdgeAt(pos)
        if (nodeId != null || edgeId != null) {
          return
        }
        panning = true
        panStartView = network.getViewPosition()
        panStartClient = { x: e.clientX, y: e.clientY }
      }

      function onCanvasMouseMove (e) {
        if (!panning || !panStartView || !panStartClient || !network) {
          return
        }
        const dx = e.clientX - panStartClient.x
        const dy = e.clientY - panStartClient.y
        network.moveTo({
          position: { x: panStartView.x - dx, y: panStartView.y - dy },
          animation: false
        })
      }

      function onCanvasMouseUp () {
        panning = false
        panStartView = null
        panStartClient = null
      }

      const el = containerRef.value
      if (el) {
        el.addEventListener('mousedown', onCanvasMouseDown)
        window.addEventListener('mousemove', onCanvasMouseMove)
        window.addEventListener('mouseup', onCanvasMouseUp)
      }
      panCleanup = () => {
        if (el) {
          el.removeEventListener('mousedown', onCanvasMouseDown)
        }
        window.removeEventListener('mousemove', onCanvasMouseMove)
        window.removeEventListener('mouseup', onCanvasMouseUp)
        panCleanup = null
      }
      network.on('destroy', () => {
        if (panCleanup) {
          panCleanup()
        }
      })

      const DBL_CLICK_MS = 400
      let lastClick = { type: null, id: null, time: 0 }
      network.on('click', (params) => {
        const dom = params.pointer?.DOM || {}
        const rect = containerRef.value?.getBoundingClientRect()
        const toViewport = (dx, dy) => ({
          x: rect ? dx + rect.left : dx,
          y: rect ? dy + rect.top : dy
        })
        const pos = toViewport(dom.x ?? 0, dom.y ?? 0)
        const now = Date.now()
        if (params.nodes.length > 0) {
          const id = params.nodes[0]
          selectedNodeIdRef.value = id
          applyCurrentVisibilityState()
          const entity = entities.value.find((e) => (e.entity_id || e.id) === id)
          if (entity) {
            if (lastClick.type === 'node' && lastClick.id === id && now - lastClick.time < DBL_CLICK_MS) {
              lastClick = { type: null, id: null, time: 0 }
              emit('node-double-click', entity)
              return
            }
            lastClick = { type: 'node', id, time: now }
            emit('node-click', entity, pos)
          }
        } else if (params.edges.length > 0) {
          const id = params.edges[0]
          selectedNodeIdRef.value = null
          applyCurrentVisibilityState()
          const edge = edges.value.find((e) => (e.edge_id || e.id) === id)
          if (edge) {
            if (lastClick.type === 'edge' && lastClick.id === id && now - lastClick.time < DBL_CLICK_MS) {
              lastClick = { type: null, id: null, time: 0 }
              emit('edge-double-click', edge)
              return
            }
            lastClick = { type: 'edge', id, time: now }
            emit('edge-click', edge, pos)
          }
        } else {
          lastClick = { type: null, id: null, time: 0 }
          selectedNodeIdRef.value = null
          applyCurrentVisibilityState()
          emit('container-click')
        }
      })

      network.on('doubleClick', (params) => {
        if (params.nodes.length > 0) {
          const id = params.nodes[0]
          const entity = entities.value.find((e) => (e.entity_id || e.id) === id)
          if (entity) {
            emit('node-double-click', entity)
          }
        } else if (params.edges.length > 0) {
          const id = params.edges[0]
          const edge = edges.value.find((e) => (e.edge_id || e.id) === id)
          if (edge) {
            emit('edge-double-click', edge)
          }
        }
      })

      network.on('dragEnd', () => {
        const positions = getPositions()
        if (positions && Object.keys(positions).length > 0) {
          savePositionCache(positions)
        }
        scheduleUpdateExpandOverlays()
        emit('after-drawing')
      })

      network.on('afterDrawing', () => {
        applyNodeBorderClip()
        scheduleUpdateExpandOverlays()
        emit('after-drawing')
      })

      network.on('zoom', () => {
        if (network) {
          const scale = network.getScale()
          emit('zoom-change', scale)
        }
        // 大图缩放时临时隐藏边：vis-network 每个 wheel 事件都会整图重绘，
        // 1600+ 条边带箭头/标签时单帧 ~100ms（实测缩放只有 9fps）。
        // 缩放手势结束后 180ms 恢复，交互手感与 hideEdgesOnDrag 一致。
        hideEdgesDuringZoom()
        scheduleRestoreEdgesAfterZoom()
        scheduleUpdateExpandOverlays()
      })

      let lastHoverNodeId = null
      let hoverRecomputeRaf = null
      network.on('hoverNode', (params) => {
        const nodeId = params.node
        if (!nodeId) {
          return
        }
        // 同一节点反复进入（blur 后重新悬浮等）不再重复全量重算
        if (String(nodeId) === String(lastHoverNodeId)) {
          return
        }
        lastHoverNodeId = nodeId
        hoveredNodeIdRef.value = nodeId
        // rAF 合并：同帧内连续悬浮不同节点时只重算最后一次的目标，避免主线程抖动
        if (hoverRecomputeRaf !== null) {
          return
        }
        hoverRecomputeRaf = requestAnimationFrame(() => {
          hoverRecomputeRaf = null
          if (!network) {
            return
          }
          const current = hoveredNodeIdRef.value
          if (current === null || current === undefined) {
            return
          }
          applyNodeFocusVisibility(current, 'hover')
        })
      })

      network.on('hoverEdge', (params) => {
        if (edgeLabelModeRef.value !== 'hover') {
          return
        }
        const edgeId = params?.edge
        if (edgeId == null) {
          return
        }
        const prevId = hoveredEdgeIdRef.value
        if (prevId != null && prevId !== edgeId && edgesDataSet.get(prevId)) {
          edgesDataSet.update({
            id: prevId,
            label: '',
            font: buildEdgeFont(false)
          })
        }
        hoveredEdgeIdRef.value = edgeId
        if (edgesDataSet.get(edgeId)) {
          edgesDataSet.update({
            id: edgeId,
            label: '',
            font: buildEdgeFont(false)
          })
        }
        updateEdgeHoverPopover(edgeId, params?.pointer?.DOM)
      })

      network.on('blurEdge', () => {
        if (edgeLabelModeRef.value !== 'hover') {
          return
        }
        const edgeId = hoveredEdgeIdRef.value
        if (edgeId != null && edgesDataSet.get(edgeId)) {
          edgesDataSet.update({
            id: edgeId,
            label: '',
            font: buildEdgeFont(false)
          })
        }
        hoveredEdgeIdRef.value = null
        edgeHoverPopover.value = {
          visible: false,
          label: '',
          left: 0,
          top: 0
        }
      })

      network.on('mousemove', (params) => {
        if (edgeLabelModeRef.value !== 'hover') {
          return
        }
        const edgeId = hoveredEdgeIdRef.value
        if (edgeId == null) {
          return
        }
        updateEdgeHoverPopover(edgeId, params?.pointer?.DOM)
      })

      network.on('blurNode', () => {
        lastHoverNodeId = null
        if (hoverRecomputeRaf !== null) {
          cancelAnimationFrame(hoverRecomputeRaf)
          hoverRecomputeRaf = null
        }
        hoveredNodeIdRef.value = null
        applyCurrentVisibilityState()
        if (network) {
          network.redraw()
        }
      })

      network.on('stabilizationIterationsDone', () => {
        applyStabilizedState()
      })

      if (hasCachedPositions) {
        layoutReady = true
        vueNextTick(() => {
          setTimeout(() => {
            if (!network) {
              return
            }
            resolveOverlapsForAllNodes()
            // 先存基准坐标再收拢：缓存里保留未收拢的布局，下次加载按当时的画布重新收拢，
            // 避免在小窗口收拢后的坐标被持久化、回到大窗口仍然是一小团。
            const positions = getPositions()
            if (positions && Object.keys(positions).length > 0) {
              savePositionCache(positions)
            }
            compactLayoutToFit()
            network.moveTo({ scale: 1 })
            emit('zoom-change', 1)
          }, 0)
        })
      } else if (hasTooManyEdges && !hasCachedPositions) {
        layoutReady = true
        vueNextTick(() => {
          setTimeout(() => {
            if (!network) {
              return
            }
            resolveOverlapsForAllNodes()
            const positions = getPositions()
            if (positions && Object.keys(positions).length > 0) {
              savePositionCache(positions)
            }
            network.setOptions({
              physics: { enabled: false },
              interaction: { dragNodes: true, dragView: false, zoomView: true, hover: !isLargeGraph }
            })
            network.moveTo({ scale: 1 })
            emit('zoom-change', 1)
          }, 0)
        })
      }

      function applyStabilizedState () {
        if (!network) {
          return
        }
        layoutReady = true
        // 先停物理再收拢：否则收拢后的坐标还会被还在跑的力学模拟继续推开。
        network.setOptions({
          physics: { enabled: false },
          interaction: { dragNodes: true, dragView: false, zoomView: true, hover: !isLargeGraph }
        })
        resolveOverlapsForAllNodes()
        // 同 cached 分支：缓存保留收拢前的基准布局
        const positions = getPositions()
        if (positions && Object.keys(positions).length > 0) {
          savePositionCache(positions)
        }
        compactLayoutToFit()
        nodesDataSet.forEach((node) => {
          nodesDataSet.update({ id: node.id, fixed: false })
        })
        network.moveTo({ scale: 1 })
        emit('zoom-change', 1)
        emit('after-drawing')
      }
    }

    function getPositions () {
      if (!network) {
        return {}
      }
      const posMap = network.getPositions()
      if (!posMap) {
        return {}
      }
      const out = {}
      Object.keys(posMap).forEach((id) => {
        const p = posMap[id]
        const x = p && (typeof p.x === 'number' ? p.x : Number(p.x))
        const y = p && (typeof p.y === 'number' ? p.y : Number(p.y))
        if (Number.isFinite(x) && Number.isFinite(y)) {
          out[id] = { x, y }
        }
      })
      return out
    }

    /** 当前所有节点 x 的包围盒中心；没有有效坐标时返回 null */
    function getPositionsCenterX () {
      const xs = Object.values(getPositions())
        .map((p) => p.x)
        .filter((x) => Number.isFinite(x))
      return xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : null
    }

    /** 获取指定节点在画布上的坐标。先用 DataSet 中的实际 id 再查 posMap，避免键不一致导致取不到 */
    function getNodePosition (nodeId) {
      if (nodeId == null || nodeId === '' || !network) {
        return null
      }
      const posMap = network.getPositions()
      if (!posMap) {
        return null
      }
      let id = nodeId
      const positions = getPositions()
      let pos = positions[id] ?? positions[String(id)]
      if (!pos) {
        pos = positions[Number(id)]
      }
      if (!pos) {
        const key = Object.keys(posMap).find((k) => String(k) === String(nodeId))
        if (key) {
          pos = positions[key]
        }
      }
      if (!pos && nodesDataSet.length > 0) {
        const dataSetIds = nodesDataSet.getIds()
        const matchedId = dataSetIds.find((k) => String(k) === String(nodeId))
        if (matchedId != null) {
          pos = positions[matchedId]
        }
      }
      return pos && Number.isFinite(pos.x) && Number.isFinite(pos.y) ? { x: pos.x, y: pos.y } : null
    }

    /** 当前视图中心在画布坐标系下的坐标，用于无参考节点时的兜底落点。无法取得时返回固定值避免父组件拿到的永远是 null */
    function getViewCenterInCanvas () {
      if (!network) {
        return { x: 0, y: 0 }
      }
      try {
        if (typeof network.getViewPosition === 'function') {
          const v = network.getViewPosition()
          if (v && Number.isFinite(v.x) && Number.isFinite(v.y)) {
            return { x: v.x, y: v.y }
          }
        }
        const body = network.body
        if (body && body.view && body.view.translation) {
          const t = body.view.translation
          if (Number.isFinite(t.x) && Number.isFinite(t.y)) {
            const scale = getScale()
            return { x: -t.x / scale, y: -t.y / scale }
          }
        }
      } catch (e) { /* ignore */ }
      return { x: 0, y: 0 }
    }

    /** 当前画布缩放，用于按屏幕像素换算画布偏移 */
    function getScale () {
      if (!network) {
        return 1
      }
      const s = network.getScale()
      return Number.isFinite(s) && s > 0 ? s : 1
    }

    /** 节点中心最小间距（避免边缘重合）。约 2*半径 + 间隙 */
    const MIN_CENTER_DISTANCE = 44
    const OVERLAP_EPS = 1e-6
    const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))

    function normalizeScale (scale) {
      return Number.isFinite(scale) && scale > 0 ? scale : 1
    }

    function toFinitePositionList (positionsMap) {
      const list = []
      if (!positionsMap || typeof positionsMap !== 'object') {
        return list
      }
      Object.keys(positionsMap).forEach((id) => {
        const pos = positionsMap[id]
        if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
          list.push({ id, x: pos.x, y: pos.y })
        }
      })
      return list
    }

    function getAnchorFromOccupied (occupied) {
      if (!Array.isArray(occupied) || occupied.length === 0) {
        return getViewCenterInCanvas()
      }
      let sx = 0
      let sy = 0
      occupied.forEach((p) => {
        sx += p.x
        sy += p.y
      })
      return { x: sx / occupied.length, y: sy / occupied.length }
    }

    function adjustPositionWithOccupied (x, y, occupied, excludeId) {
      let px = x
      let py = y
      const maxIter = 24
      for (let iter = 0; iter < maxIter; iter++) {
        let overlap = false
        for (const pos of occupied) {
          if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
            continue
          }
          if (excludeId !== undefined && excludeId !== null && String(pos.id) === String(excludeId)) {
            continue
          }
          const dx = px - pos.x
          const dy = py - pos.y
          const d = Math.hypot(dx, dy)
          if (d < MIN_CENTER_DISTANCE) {
            const unitX = d > OVERLAP_EPS ? dx / d : Math.cos(iter * GOLDEN_ANGLE)
            const unitY = d > OVERLAP_EPS ? dy / d : Math.sin(iter * GOLDEN_ANGLE)
            const push = MIN_CENTER_DISTANCE - d
            px += unitX * push
            py += unitY * push
            overlap = true
          }
        }
        if (!overlap) {
          break
        }
      }
      return { x: px, y: py }
    }

    function getDistributedPositionByIndex (index, occupied, anchor, scale, excludeId) {
      const safeScale = normalizeScale(scale)
      const baseRadius = Math.max(MIN_CENTER_DISTANCE * 1.5, 96 / safeScale)
      const radialStep = Math.max(MIN_CENTER_DISTANCE * 1.1, 52 / safeScale)
      const i = Math.max(0, Number(index) || 0)
      const radius = baseRadius + Math.sqrt(i + 1) * radialStep
      const angle = i * GOLDEN_ANGLE
      const candidateX = anchor.x + radius * Math.cos(angle)
      const candidateY = anchor.y + radius * Math.sin(angle)
      return adjustPositionWithOccupied(candidateX, candidateY, occupied, excludeId)
    }

    /**
     * 将坐标 (x,y) 推离过近的已有节点，使与任意节点中心距不小于 MIN_CENTER_DISTANCE。
     * @param {number} x - 候选 x
     * @param {number} y - 候选 y
     * @param {string} [excludeId] - 不参与检测的节点 id（如即将新增的节点尚未入图）
     * @returns {{ x: number, y: number }}
     */
    function adjustPositionToAvoidOverlap (x, y, excludeId, positions) {
      // positions 由调用方按轮次快照传入：避免每次 getPositions() 的
      // N 次 O(N) 拷贝 + 16 轮全扫，否则大图会卡死。
      const snapshot = positions || getPositions()
      const minDist = MIN_CENTER_DISTANCE
      let px = x
      let py = y
      const maxIter = 16
      for (let iter = 0; iter < maxIter; iter++) {
        let overlap = false
        for (const [oid, pos] of Object.entries(snapshot)) {
          if (excludeId !== undefined && excludeId !== null && String(oid) === String(excludeId)) {
            continue
          }
          const dx = px - pos.x
          const dy = py - pos.y
          const d = Math.hypot(dx, dy)
          if (d < minDist && d > OVERLAP_EPS) {
            const push = (minDist - d) / d
            px += dx * push
            py += dy * push
            overlap = true
          }
        }
        if (!overlap) {
          break
        }
      }
      return { x: px, y: py }
    }

    /** 全图重叠微调时，仅当位移超过此阈值才更新节点，避免抖动 */
    const MIN_NUDGE_PIXELS = 0.5

    /**
     * 对当前图中所有节点做重叠检测并微调，使任意两节点中心距不小于 MIN_CENTER_DISTANCE。
     * 用于有缓存坐标且未跑物理时的兜底。
     */
    function resolveOverlapsForAllNodes () {
      if (!network) {
        return
      }
      // 大图直接跳过：O(n²·16) 且每次 update 都会触发重绘/展开按钮重算，
      // 500 节点实测能把页面锁死数分钟（用户侧表现为「图谱界面卡死」）。
      const nodeCount = nodesDataSet.length
      if (nodeCount > MAX_OVERLAP_RESOLVE_NODES) {
        return
      }
      const maxPasses = 6
      for (let pass = 0; pass < maxPasses; pass++) {
        const positions = getPositions()
        const ids = Object.keys(positions)
        let changed = false
        const updates = []
        for (const id of ids) {
          const pos = positions[id]
          if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
            continue
          }
          const adjusted = adjustPositionToAvoidOverlap(pos.x, pos.y, id, positions)
          const dx = adjusted.x - pos.x
          const dy = adjusted.y - pos.y
          if (Math.hypot(dx, dy) > MIN_NUDGE_PIXELS) {
            updates.push({ id, x: adjusted.x, y: adjusted.y })
            changed = true
          }
        }
        // 一轮只提交一次：逐条 update 会让 vis 每条都重绘一次
        if (updates.length) {
          nodesDataSet.update(updates)
        }
        if (!changed) {
          break
        }
      }
    }

    // 标签避让的纯几何逻辑在 ../lib/label-layout.ts（可单测）；这里只提供当前坐标与
    // canvas 文本宽度。节点名是固定 13px 的文本，位置收拢后长名字会互相压住。
    let labelMeasureCtx = null

    function measureNodeLabelWidth (name) {
      if (!labelMeasureCtx) {
        labelMeasureCtx = document.createElement('canvas').getContext('2d')
      }
      if (!labelMeasureCtx) {
        return 0
      }
      labelMeasureCtx.font = `${NODE_NAME_FONT_SIZE}px ${getNodePaint().fontFamily}`
      return labelMeasureCtx.measureText(name).width
    }

    /** 读取当前屏幕坐标做一次标签避让（必须在收拢与重叠微调之后再调用） */
    function separateLabelCollisions () {
      const positions = getPositions()
      const points = Object.keys(positions).map((id) => ({
        id,
        x: positions[id].x,
        y: positions[id].y
      }))
      const canvasW = containerRef.value ? containerRef.value.clientWidth : Infinity
      return separateOverlappingLabels(points, {
        labelOf: (id) => nodeNameById.get(String(id)) || '',
        measureWidth: measureNodeLabelWidth,
        labelOffsetY: NODE_NAME_OFFSET_Y,
        haloRadius: NODE_HALO_RADIUS,
        // 左右各留一个光环宽度，最外侧的节点与标签不贴边
        maxWidth: canvasW - 2 * NODE_HALO_RADIUS
      })
    }

    /**
     * 把整张图按比例收拢到画布内，保证 100% 缩放时所有节点可见。
     * 力导向布局与历史坐标缓存都可能让节点铺得比画布更大；这里以包围盒中心为锚点
     * 等比缩放坐标（节点/文字尺寸不变），再跑一次重叠微调。
     *
     * 目标尺寸与收拢阈值见 `lib/layout-fit.ts`。
     * `preserveView`：刷新后用缓存里的「未收拢」基准坐标重建节点时，只重做坐标收拢，
     * 不改用户当前的平移/缩放（收拢本身已经把视图居中过一次，这里不再 moveTo）。
     * `expand`：进出全屏后按新画布重排时置 true，过小的布局也会撑到目标尺寸。
     */
    function compactLayoutToFit (preserveView = false, expand = false) {
      if (!network || !containerRef.value) {
        return
      }
      const positions = getPositions()
      const ids = Object.keys(positions)
      if (ids.length < 2) {
        return
      }
      let minX = Infinity
      let minY = Infinity
      let maxX = -Infinity
      let maxY = -Infinity
      ids.forEach((id) => {
        const p = positions[id]
        if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
          return
        }
        minX = Math.min(minX, p.x)
        minY = Math.min(minY, p.y)
        maxX = Math.max(maxX, p.x)
        maxY = Math.max(maxY, p.y)
      })
      if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
        return
      }
      const fit = resolveLayoutFit({
        bounds: { minX, minY, maxX, maxY },
        canvas: {
          width: containerRef.value.clientWidth,
          height: containerRef.value.clientHeight
        },
        nodeCount: ids.length,
        expand
      })
      if (!fit) {
        return
      }
      const { scaleX, scaleY, centerX: cx, centerY: cy } = fit
      let labelSeparated = null
      if (fit.changed) {
        const updates = []
        ids.forEach((id) => {
          const p = positions[id]
          if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
            return
          }
          updates.push({
            id,
            x: cx + (p.x - cx) * scaleX,
            y: cy + (p.y - cy) * scaleY
          })
        })
        if (updates.length) {
          nodesDataSet.update(updates)
        }
        // 收拢后可能有个别节点中心距 < MIN_CENTER_DISTANCE，再推一次
        resolveOverlapsForAllNodes()
        // 节点名是固定像素绘制的，收拢后按实际宽度做一次标签分隔。
        // 读的是 DataSet 更新后的当前坐标（vis DataSet.update 同步生效），
        // 因此不会覆盖上一步的重叠微调。
        labelSeparated = separateLabelCollisions()
        if (labelSeparated) {
          nodesDataSet.update(labelSeparated.updates)
          // 横向避让可能把节点推到第三个节点旁，再跑一次最小中心距兜底
          resolveOverlapsForAllNodes()
        }
      }
      if (!preserveView) {
        // 视点中心下移半个预留高度 → 整张图在屏幕上上移，底部让给悬浮工具栏
        const viewCenterY = cy + LAYOUT_FIT_DEFAULTS.bottomSafe / 2
        const viewCenterX = labelSeparated ? (getPositionsCenterX() ?? cx) : cx
        network.moveTo({ position: { x: viewCenterX, y: viewCenterY }, scale: 1 })
        emit('zoom-change', 1)
      }
      if (fit.changed) {
        // 位置更新后 vis 的视口裁剪仍在用旧包围盒：第一帧只会刷新被裁节点的包围盒，
        // 第二帧才会真正画出来。连续重绘两次，避免「节点在画布内却没显示」。
        network.redraw()
        network.redraw()
      }
    }

    /**
     * 进出全屏后按新画布重排。
     *
     * 只平移相机会让节点坐标仍是小画布收拢后的那一团，换到大画布上仍挤在中间。
     * 这里先回到坐标缓存里的基准布局（未收拢），再按当前画布做一次收拢 / 撑开，
     * 最后以 100% 居中。不写回缓存：基准布局与画布尺寸无关，反复进出不会累积变形。
     */
    function relayoutForViewport () {
      if (!network || !containerRef.value) {
        return
      }
      const current = getPositions()
      const ids = Object.keys(current)
      if (ids.length < 2) {
        return
      }
      // 先让 vis 按新容器重算 canvas 尺寸（setSize 会按宽高比重算相机），
      // 否则 moveTo 之后的重绘会把 scale 再乘一次尺寸比例，节点被放大出画布。
      network.setSize()
      const cached = loadPositionCache()
      const baseUpdates = ids
        .filter((id) => Number.isFinite(cached?.[id]?.x) && Number.isFinite(cached?.[id]?.y))
        .map((id) => ({ id, x: cached[id].x, y: cached[id].y }))
      if (baseUpdates.length) {
        nodesDataSet.update(baseUpdates)
        resolveOverlapsForAllNodes()
      }
      compactLayoutToFit(false, true)
      // setSize 会清空画布；坐标没变化时 compactLayoutToFit 不会自行重绘，这里补一次。
      network.redraw()
    }

    /**
     * 在关联节点旁计算新节点位置，使屏幕上与关联节点隔 gapPixels 像素（两节点边缘间距）。
     * 优先使用 canvasToDOM/DOMtoCanvas；若不可用则用 scale 换算画布偏移兜底。
     */
    function getPositionForNewNodeNear (referenceNodeId, gapPixels = 138) {
      if (!referenceNodeId || !network) {
        return null
      }
      const refCanvas = getNodePosition(referenceNodeId)
      if (!refCanvas) {
        return null
      }
      const NODE_DIAMETER = 20
      const centerDistancePx = NODE_DIAMETER / 2 + gapPixels + NODE_DIAMETER / 2
      const occupied = toFinitePositionList(getPositions())
      const indexHint = Math.max(0, occupied.length - 1)
      const fallbackDistributed = () => {
        const distanceInCanvas = centerDistancePx / normalizeScale(getScale())
        const baseAnchor = { x: refCanvas.x, y: refCanvas.y }
        const distributed = getDistributedPositionByIndex(indexHint, occupied, baseAnchor, getScale(), null)
        const dx = distributed.x - baseAnchor.x
        const dy = distributed.y - baseAnchor.y
        const d = Math.hypot(dx, dy)
        if (d >= distanceInCanvas) {
          return distributed
        }
        const scaleK = distanceInCanvas / (d || 1)
        return adjustPositionWithOccupied(
          baseAnchor.x + dx * scaleK,
          baseAnchor.y + dy * scaleK,
          occupied,
          null
        )
      }
      if (typeof network.canvasToDOM === 'function' && typeof network.DOMtoCanvas === 'function') {
        let refDOM
        try {
          refDOM = network.canvasToDOM(refCanvas)
        } catch (e) {
          return fallbackDistributed()
        }
        if (!refDOM || !Number.isFinite(refDOM.x) || !Number.isFinite(refDOM.y)) {
          return fallbackDistributed()
        }
        const angle = indexHint * GOLDEN_ANGLE
        const dx = centerDistancePx * Math.cos(angle)
        const dy = centerDistancePx * Math.sin(angle)
        const newDOM = { x: refDOM.x + dx, y: refDOM.y + dy }
        try {
          const newCanvas = network.DOMtoCanvas(newDOM)
          if (newCanvas && Number.isFinite(newCanvas.x) && Number.isFinite(newCanvas.y)) {
            return adjustPositionWithOccupied(newCanvas.x, newCanvas.y, occupied, null)
          }
        } catch (e) {
          // ignore
        }
      }
      return fallbackDistributed()
    }

    /**
     * 添加节点。若传入 referenceEntityId 且 entityData 无有效坐标，在画布内计算「关联节点旁」坐标。
     * @param {Object} entityData - 实体数据，可含 x/y
     * @param {string} [referenceEntityId] - 关联实体 id，用于在画布内取位
     * @returns {{ x: number, y: number }} 实际使用的画布坐标，便于父组件写回缓存
     */
    function addNode (entityData, referenceEntityId) {
      const id = entityData.entity_id || entityData.id
      const name = resolveEntityDisplayName(entityData, id)
      nodeNameById.set(String(id), name)
      const rawType = entityData.entity_type || entityData.class || ''
      const group = resolveGroupKey(rawType, props.colorMap) || 'default'
      let x = Number(entityData.x)
      let y = Number(entityData.y)
      let hasPos = Number.isFinite(x) && Number.isFinite(y)

      if (!hasPos && referenceEntityId && network) {
        const near = getPositionForNewNodeNear(referenceEntityId, 138)
        if (near) {
          x = near.x
          y = near.y
          hasPos = true
        } else {
          const refPos = getNodePosition(referenceEntityId)
          const scale = getScale()
          if (refPos && Number.isFinite(scale) && scale > 0) {
            const occupied = toFinitePositionList(getPositions())
            const distributed = getDistributedPositionByIndex(
              Math.max(0, occupied.length - 1),
              occupied,
              refPos,
              scale,
              id
            )
            x = distributed.x
            y = distributed.y
            hasPos = true
          }
        }
      }
      if (!hasPos && network) {
        const occupied = toFinitePositionList(getPositions())
        const center = getAnchorFromOccupied(occupied)
        const distributed = getDistributedPositionByIndex(occupied.length, occupied, center, getScale(), id)
        if (distributed && Number.isFinite(distributed.x) && Number.isFinite(distributed.y)) {
          x = distributed.x
          y = distributed.y
          hasPos = true
        }
      }
      if (!hasPos) {
        x = 200
        y = 200
      }

      const adjusted = adjustPositionToAvoidOverlap(x, y, id)
      x = adjusted.x
      y = adjusted.y

      const node = {
        id,
        label: '',
        group,
        shape: 'custom',
        size: NODE_DOT_RADIUS,
        ctxRenderer: drawPrototypeNode
      }
      node.x = x
      node.y = y
      node.fixed = true
      nodesDataSet.add(node)
      if (prevEntityIds) {
        prevEntityIds.add(id)
      }
      vueNextTick(() => {
        ensurePhysicsOff()
        nodesDataSet.update({ id, fixed: false })
      })
      return { x, y }
    }

    function addEdge (edgeData) {
      const id = edgeData.edge_id || edgeData.id
      edgesDataSet.add(edgeToVisEdge(edgeData))
      if (prevEdgeIds) {
        prevEdgeIds.add(id)
      }
      vueNextTick(() => ensurePhysicsOff())
    }

    function updateNode (entityData) {
      const id = entityData.entity_id || entityData.id
      const positionCache = loadPositionCache()
      const node = entityToVisNode(entityData, positionCache)
      const existing = nodesDataSet.get(id)
      const currentPositions = network ? getPositions() : {}
      const pos = positionCache[id] || (entityData.x != null && entityData.y != null ? { x: entityData.x, y: entityData.y } : null) || currentPositions[id]
      if (existing) {
        const update = { id, label: node.label, group: node.group }
        if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
          update.x = pos.x
          update.y = pos.y
        }
        nodesDataSet.update(update)
      } else {
        if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
          node.x = pos.x
          node.y = pos.y
        }
        nodesDataSet.add(node)
        if (prevEntityIds) {
          prevEntityIds.add(id)
        }
      }
      vueNextTick(() => ensurePhysicsOff())
    }

    function updateEdge (edgeData) {
      const id = edgeData.edge_id || edgeData.id
      const edge = edgeToVisEdge(edgeData)
      if (edgesDataSet.get(id)) {
        edgesDataSet.update(edge)
      } else {
        edgesDataSet.add(edge)
        if (prevEdgeIds) {
          prevEdgeIds.add(id)
        }
      }
      vueNextTick(() => ensurePhysicsOff())
    }

    function removeNode (nodeId) {
      nodesDataSet.remove(nodeId)
      if (prevEntityIds) {
        prevEntityIds.delete(nodeId)
      }
      vueNextTick(() => ensurePhysicsOff())
    }

    function removeEdge (edgeId) {
      edgesDataSet.remove(edgeId)
      if (prevEdgeIds) {
        prevEdgeIds.delete(edgeId)
      }
      vueNextTick(() => ensurePhysicsOff())
    }

    function fit () {
      if (!network) {
        return
      }
      // fit 会缩放到「全部可见」，缩放比例随之变化；等动画结束再上报真实比例，
      // 否则工具栏的「缩放比例」会停在 100%，与实际显示不符。
      const reportScale = () => {
        network.off('animationFinished', reportScale)
        if (network) {
          emit('zoom-change', network.getScale())
          scheduleUpdateExpandOverlays()
        }
      }
      network.on('animationFinished', reportScale)
      network.fit({ animation: true })
    }

    /**
     * 无动画 fit：查询结果落定后调用。
     * 有动画版本会被紧随其后的画布重绘/尺寸变化打断（animationFinished 不触发，
     * 视口停在原处 → Limit 调小后节点全在视口外，画布看起来是空的）。
     */
    function fitImmediate () {
      if (!network) {
        return
      }
      network.fit({ animation: false })
      emit('zoom-change', network.getScale())
      scheduleUpdateExpandOverlays()
    }

    /**
     * 居中：保持当前缩放（不传 scale 时 moveTo 沿用 body.view.scale），仅平移使节点包围盒中心落在视口中心。
     * 父组件 GraphVisualization.centerGraph 已优先用 getNetwork() 直接调用，与子组件 expose 是否含 centerView 无关。
     */
    function centerView () {
      if (!network) {
        return
      }
      const canvas = network.canvas?.frame?.canvas
      if (!canvas || canvas.clientWidth === 0 || canvas.clientHeight === 0) {
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
      emit('zoom-change', network.getScale())
      scheduleUpdateExpandOverlays()
      emit('after-drawing')
    }

    function zoomIn () {
      if (network) {
        const s = network.getScale()
        network.moveTo({ scale: Math.min(s * 1.2, 5) })
        emit('zoom-change', network.getScale())
      }
    }

    function zoomOut () {
      if (network) {
        const s = network.getScale()
        network.moveTo({ scale: Math.max(s / 1.2, 0.2) })
        emit('zoom-change', network.getScale())
      }
    }

    function resetZoom () {
      if (network) {
        network.moveTo({ scale: 1 })
        emit('zoom-change', 1)
      }
    }

    function setZoomScale (scale) {
      if (!network) {
        return
      }
      const s = Number(scale)
      if (!Number.isFinite(s)) {
        return
      }
      network.moveTo({ scale: Math.max(0.2, Math.min(5, s)) })
      emit('zoom-change', network.getScale())
    }

    function getSnapshotDataUrl () {
      if (!network) {
        return ''
      }
      try {
        const internalCanvas = network?.canvas?.frame?.canvas
        if (internalCanvas && typeof internalCanvas.toDataURL === 'function') {
          return internalCanvas.toDataURL('image/png')
        }
      } catch (e) {
        // ignore and fallback
      }
      try {
        const domCanvas = containerRef.value?.querySelector?.('canvas')
        if (domCanvas && typeof domCanvas.toDataURL === 'function') {
          return domCanvas.toDataURL('image/png')
        }
      } catch (e) {
        return ''
      }
      return ''
    }

    function focusNode (nodeId) {
      if (network && nodeId != null) {
        network.focus(nodeId, { animation: true })
      }
    }

    function selectNodes (nodeIds) {
      const normalizedNodeIds = Array.isArray(nodeIds)
        ? nodeIds.filter(id => id !== null && id !== undefined)
        : []
      selectedNodeIdRef.value = normalizedNodeIds.length === 1 ? normalizedNodeIds[0] : null
      applyCurrentVisibilityState()
      if (network) {
        network.selectNodes(normalizedNodeIds)
      }
    }

    function destroyNetwork () {
      if (panCleanup) {
        panCleanup()
        panCleanup = null
      }
      if (network) {
        network.destroy()
        network = null
      }
      expandIconItems.value = []
      hoveredNodeIdRef.value = null
      selectedNodeIdRef.value = null
      hoveredEdgeIdRef.value = null
      edgeHoverPopover.value = {
        visible: false,
        label: '',
        left: 0,
        top: 0
      }
      prevEntityIds = null
      prevEdgeIds = null
      layoutReady = false
    }

    function resetAndRender () {
      clearPositionCache()
      destroyNetwork()
      vueNextTick(() => {
        syncDataToVis()
        vueNextTick(initNetwork)
      })
    }

    let resizeObserver = null
    let resizeNetworkRafScheduled = false

    /**
     * vis-network 的 autoResize 只监听 window resize；父级是 flex 布局时，
     * 控制面板高度变化（切查询类型、拖动面板）会让画布容器在窗口尺寸不变的情况下变矮，
     * 此时必须显式重绘，否则 canvas 仍按旧尺寸绘制、被 overflow:hidden 裁掉。
     *
     * 用 redraw() 而不是 setSize()：setSize 只改 canvas 尺寸（改宽高会清空画布），
     * 不会重绘，结果是一张空白画布；redraw() 内部先 emit("setSize") 按 100% 重新测量，再 _redraw()。
     */
    function scheduleResizeNetworkToContainer () {
      if (resizeNetworkRafScheduled) {
        return
      }
      resizeNetworkRafScheduled = true
      requestAnimationFrame(() => {
        resizeNetworkRafScheduled = false
        if (!network || !containerRef.value) {
          return
        }
        if (containerRef.value.clientWidth > 0 && containerRef.value.clientHeight > 0) {
          network.redraw()
        }
      })
    }

    onMounted(() => {
      syncDataToVis()
      vueNextTick(initNetwork)
      window.addEventListener(THEME_CHANGE_EVENT, applyThemeToNetwork)
      resizeObserver = new ResizeObserver(() => {
        scheduleResizeNetworkToContainer()
        scheduleUpdateExpandOverlays()
      })
      if (wrapperRef.value) {
        resizeObserver.observe(wrapperRef.value)
      }
    })

    onBeforeUnmount(() => {
      window.removeEventListener(THEME_CHANGE_EVENT, applyThemeToNetwork)
      if (resizeObserver) {
        resizeObserver.disconnect()
        resizeObserver = null
      }
      destroyNetwork()
    })

    watch(
      () => [entities.value, edges.value],
      () => {
        syncDataToVis()
        vueNextTick(() => scheduleUpdateExpandOverlays())
      },
      { deep: true }
    )

    /**
     * colorMap 随查询模式/结果变化时会重新计算；vis-network 的 groups 仅在 initNetwork 时写入，
     * 若不同步更新，图例（读最新 colorMap）与画布节点色会不一致。
     */
    watch(
      () => props.colorMap,
      () => {
        if (!network) {
          return
        }
        network.setOptions({ groups: buildGroupsOption() })
        applyCurrentVisibilityState()
        network.redraw()
        scheduleUpdateExpandOverlays()
      },
      { deep: true }
    )

    watch(
      () => [props.entityExpandStateMap, props.persistentlyHiddenNodeIds],
      () => {
        overlayStaticDirty = true
        vueNextTick(() => {
          syncVisibilityFromHiddenProps()
        })
      },
      { deep: true }
    )

    watch(
      () => props.resetToken,
      (newVal, oldVal) => {
        if (oldVal !== undefined && oldVal !== newVal) {
          resetAndRender()
        }
      }
    )

    watch(
      () => props.edgeLabelDisplayMode,
      (mode) => {
        edgeLabelModeRef.value = mode === 'hover' ? 'hover' : 'inline'
        hoveredEdgeIdRef.value = null
        applyEdgeLabelDisplayMode(edgeLabelModeRef.value)
      }
    )

    defineExpose({
      focusNode,
      selectNodes,
      zoomIn,
      zoomOut,
      resetZoom,
      setZoomScale,
      fit,
      fitImmediate,
      compactLayoutToFit,
      relayoutForViewport,
      centerView,
      getSnapshotDataUrl,
      setEdgeLabelMode,
      getScale,
      getNetwork,
      getNodePosition,
      getViewCenterInCanvas,
      getPositionForNewNodeNear,
      addNode,
      addEdge,
      updateNode,
      updateEdge,
      removeNode,
      removeEdge,
      refreshExpandOverlay,
      syncVisibilityFromHiddenProps
    })

    return {
      wrapperRef,
      containerRef,
      expandIconItems,
      edgeHoverPopover,
      handleExpandIconClick,
      t,
      AddIcon,
      RemoveIcon,
      addNode,
      addEdge,
      getPositionForNewNodeNear,
      getNodePosition,
      getViewCenterInCanvas,
      getScale,
      getNetwork,
      focusNode,
      selectNodes,
      zoomIn,
      zoomOut,
      resetZoom,
      setZoomScale,
      fit,
      fitImmediate,
      compactLayoutToFit,
      relayoutForViewport,
      getSnapshotDataUrl,
      setEdgeLabelMode,
      updateNode,
      updateEdge,
      removeNode,
      removeEdge
    }
  }
}
</script>

<style scoped>
.graph-canvas-vis {
  position: relative;
  width: 100%;
  height: 100%;
  /* 不设 min-height：画布高度由详情页 flex 布局分配，固定 300px 在
     「子图查询 + 小屏」时会超出 graph-container 被裁掉 */
  min-height: 0;
}

.graph-canvas-vis-core {
  width: 100%;
  height: 100%;
}

.graph-canvas-vis__expand-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}

.graph-canvas-vis__edge-popover {
  position: absolute;
  z-index: 3;
  pointer-events: none;
  transform: translate(-50%, -100%);
}

.graph-canvas-vis__edge-popover-content {
  position: relative;
  box-sizing: border-box;
  min-width: 64px;
  max-width: 320px;
  padding: 8px 12px;
  border: 1px solid var(--rs-border);
  border-radius: 8px;
  background: var(--rs-bg-card);
  color: var(--rs-text-2);
  font-size: 14px;
  line-height: 1.4;
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.graph-canvas-vis__edge-popover-content::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -6px;
  width: 10px;
  height: 10px;
  background: var(--rs-bg-card);
  border-right: 1px solid var(--rs-border);
  border-bottom: 1px solid var(--rs-border);
  transform: translateX(-50%) rotate(45deg);
}

.node-expand-fab-group {
  position: absolute;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 2px;
  pointer-events: none;
}

.node-expand-fab {
  position: relative;
  flex-shrink: 0;
  pointer-events: auto;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--rs-bg-card);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  /* 白底圆形按钮：固定投影（等价于规范写法 0 2px 6px + 细描边），不随画布缩放改 blur，避免发灰/错位 */
  box-shadow:
    0 0 0 1px rgba(0, 0, 0, 0.06),
    0 2px 6px rgba(0, 0, 0, 0.12);
}

.node-expand-fab:hover {
  filter: brightness(1.05);
  box-shadow:
    0 0 0 1px rgba(0, 0, 0, 0.08),
    0 3px 8px rgba(0, 0, 0, 0.14);
}

.node-expand-fab__img {
  display: block;
  flex-shrink: 0;
  /* add/remove 资源在 960 viewBox 内以 (450,450) 为几何中心，较中心点(480,480)偏左上；
     用百分比补偿，随图标缩放保持一致居中视觉。 */
  transform: translate(3.125%, 3.125%);
  transform-origin: center center;
}

/* 收起后：加号右侧隐藏子实体数量（绿色胶囊，与产品示意一致） */
.node-expand-fab__count {
  flex-shrink: 0;
  box-sizing: border-box;
  font-weight: 700;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  color: #fff;
  background: var(--rs-success);
  border-radius: 999px;
  text-align: center;
  white-space: nowrap;
  pointer-events: none;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
}
</style>
