<template>
  <WorkspaceShell
    class="advanced-flow"
    :class="{ 'is-flow-fullscreen': fullscreen }"
    back="/flow"
    :parent="$t('ragFlow.ragWorkflow')"
    :context="$t('modules.workflow.editOrchestration')"
    :title="workflowName"
    :icon="WorkflowIcon"
    :show-focus-action="false"
  >
    <template #subtitle>
      <!-- 先给出知识来源类型，再给模板类型；只绑图谱库时显示「图谱检索」 -->
      <span v-for="kind in sourceKinds" :key="kind" :class="['tag-soft', sourceKindOf(kind).tone]">
        <component :is="sourceKindOf(kind).icon" />{{ $t(sourceKindOf(kind).labelKey) }}
      </span>
      <span class="tag-soft blue">{{ workflowTypeLabel() }}</span>
      <span>{{ workflowId }}</span>
    </template>
    <template #actions>
      <!-- 全屏时页面头部整体隐藏，这两个主操作 Teleport 进画布的
           「编排与操作」浮层（同一个实例，不复制按钮）。 -->
      <!-- defer：目标节点由本组件自己的画布渲染，首帧早于它挂载；不加 defer 时
           Teleport 在挂载期解析不到目标（生产构建无警告，直接缓存 null），
           第一次进全屏会报 insertBefore of null。 -->
      <Teleport defer :disabled="!fullscreen" to="#flow-fullscreen-actions-target">
        <div class="flow-primary-actions">
          <!-- 试运行还没接后端：外观是禁用态（灰），但**点击仍给提示**（span 接 click，
               按钮 pointer-events:none 让事件落到 span 上），hover 还有 tooltip。
               不直接隐藏：工具栏三个动作是一组，隐藏会让其余按钮跳位，用户也无从得知
               这个能力存在。「看起来不可用 + 点了会解释为什么」是这里的最优解。 -->
          <el-tooltip :content="$t('modules.workflow.trialRunNotConnected')" placement="bottom">
            <span class="trial-run-wrap" @click="showTrialRunHint">
              <el-button class="button-compact trial-run-btn" disabled>
                <VideoPlay />{{ $t('modules.workflow.trialRun') }}
              </el-button>
            </span>
          </el-tooltip>
          <!-- 图还没落到当前工作流上（首次加载中、或刚切过来还没加载完）时不让点：
               此时保存存下去的会是空的/别的流的画布 -->
          <el-tooltip :content="$t('modules.workflow.saveDraftHint')" placement="bottom">
            <el-button
              class="button-compact"
              :loading="loading"
              :disabled="graphAppId !== $route.params.id"
              type="primary"
              @click="saveConfigHandler"
            >
              <Check />{{ $t('public.save') }}
            </el-button>
          </el-tooltip>
        </div>
      </Teleport>
    </template>

    <Teleport defer :disabled="!fullscreen" to="#flow-fullscreen-controls-target">
      <div class="workspace-toolbar">
        <div class="workspace-toolbar-group">
          <el-button class="button-compact" @click="toggleLibrary">
            <Plus />{{ $t('modules.workflow.addNode') }}
          </el-button>
          <el-button class="button-compact" @click="arrangeWorkflow">
            <Rank />{{ $t('modules.workflow.arrangeLayout') }}
          </el-button>
          <el-button class="button-compact" @click="checkConfig">
            <CircleCheck />{{ $t('modules.workflow.checkConfig') }}
          </el-button>
          <el-button class="button-compact" :disabled="loading" @click="undoChanges">
            <RefreshLeft />{{ $t('modules.workflow.undoChanges') }}
          </el-button>
        </div>
        <span class="workspace-toolbar-note text-caption" :title="$t('ragFlow.tips')">
          {{ $t('modules.workflow.graphStatWithOperators', { nodes: nodeCount, operators: operatorCount, edges: edgeCount }) }}
        </span>
      </div>
    </Teleport>

    <div
      class="flow-surface"
      :class="{ 'is-connecting': connectingSource }"
      @pointermove="updateClickConnection"
      @pointerleave="clearHoveredPort"
      @keydown="handleCanvasKeydown"
    >
      <div class="canvas-viewport" :class="{ 'is-fullscreen': fullscreen }">
        <div id="advancedFLow" class="canvas-world" />
        <div v-if="!fullscreen" class="canvas-hint text-caption">
          {{ connectingSource ? $t('modules.workflow.canvasHintConnecting') : $t('modules.workflow.canvasHint') }}
        </div>
        <div v-else class="canvas-fullscreen-context text-caption" :title="workflowName">
          <span class="flow-fullscreen-context">{{ workflowName }} · {{ $t('modules.workflow.graphStatWithOperators', { nodes: nodeCount, operators: operatorCount, edges: edgeCount }) }}</span>
        </div>
        <!-- 沉浸画布入口：与图谱详情一致，浮在画布右上角（全屏单入口） -->
        <div class="canvas-fullscreen-actions" @pointerdown.stop @mousedown.stop @touchstart.stop @wheel.stop>
          <el-button
            v-if="fullscreen"
            ref="toolsButton"
            class="button-compact"
            :aria-label="$t('modules.workflow.fullscreenTools')"
            :aria-expanded="toolsOpen"
            @click.stop="toolsOpen = !toolsOpen"
          >
            <Setting />{{ $t('modules.workflow.fullscreenTools') }}
          </el-button>
          <el-button
            ref="fullscreenButton"
            class="button-compact"
            :aria-label="fullscreen ? $t('modules.workflow.fullscreenExit') : $t('modules.workflow.fullscreenView')"
            :title="fullscreen ? $t('modules.workflow.fullscreenExit') : $t('modules.workflow.fullscreenView')"
            :aria-pressed="fullscreen"
            @click.stop="toggleFullscreen"
          >
            <component :is="fullscreen ? Close : FullScreen" />{{ fullscreen ? $t('modules.workflow.fullscreenExit') : $t('modules.workflow.fullscreenView') }}
          </el-button>
        </div>
        <!-- 「编排与操作」浮层：全屏后页头的试运行/保存与工具条 Teleport 到这里
             （同一实例，页头正常态还是原位置）。 -->
        <section
          v-show="fullscreen && toolsOpen"
          class="canvas-fullscreen-tools"
          :aria-label="$t('modules.workflow.fullscreenTools')"
          @pointerdown.stop @mousedown.stop @touchstart.stop @wheel.stop
        >
          <div class="flow-fullscreen-panel">
            <div class="flow-fullscreen-panel-header">
              <h2 class="text-secondary">{{ $t('modules.workflow.fullscreenToolsTitle') }}</h2>
              <div id="flow-fullscreen-actions-target" class="flow-primary-actions-target" />
            </div>
            <div id="flow-fullscreen-controls-target" />
          </div>
        </section>
        <div class="canvas-controls" @pointerdown.stop @mousedown.stop @touchstart.stop @wheel.stop>
          <button
            type="button"
            class="icon-button"
            :aria-label="$t('modules.workflow.zoomOut')"
            :title="$t('modules.workflow.zoomOut')"
            @click.stop="zoom('out')"
          >
            <Minus />
          </button>
          <button
            type="button"
            class="canvas-zoom canvas-zoom-reset text-caption"
            :aria-label="$t('modules.workflow.resetZoom')"
            :title="$t('modules.workflow.resetZoomTitle')"
            @click.stop="resetZoom"
          >{{ zoomPercent }}%</button>
          <button
            type="button"
            class="icon-button"
            :aria-label="$t('modules.workflow.zoomIn')"
            :title="$t('modules.workflow.zoomIn')"
            @click.stop="zoom('in')"
          >
            <Plus />
          </button>
          <span class="canvas-control-divider" />
          <button
            type="button"
            class="icon-button"
            :aria-label="$t('modules.workflow.fitCanvas')"
            :title="$t('modules.workflow.fitCanvas')"
            @click.stop="zoom('fit')"
          >
            <Aim />
          </button>
        </div>
        <!-- 连线状态条必须留在画布容器内：沉浸画布会盖住页面层，
             这两条提示放在画布右下角。 -->
        <div v-if="connectingSource" class="flow-floating-bar text-secondary" role="status">
          <span>{{ $t('modules.workflow.connectingFrom', { name: connectingSourceLabel }) }}</span>
          <el-button link @click="cancelConnection">{{ $t('public.cancel') }}</el-button>
        </div>
        <div v-else-if="selectedEdge" class="flow-floating-bar text-secondary" role="status">
          <span>{{ selectedEdge.sourceLabel }} → {{ selectedEdge.targetLabel }}</span>
          <el-button class="danger-action" link type="danger" @click="removeSelectedEdge">
            <Delete />{{ $t('modules.workflow.removeEdge') }}
          </el-button>
        </div>
        <!-- 必须留在 X6 容器（.canvas-world）之外：节点重建时 Vue 会对 Teleport
             锚点做 insertBefore，锚点落在 X6 容器内会报 "not a child of this node"。 -->
        <TeleportContainer />
      </div>
    </div>
    <el-drawer
      v-model="libraryVisible"
      direction="ltr"
      size="min(340px, 100vw)"
      append-to-body
      class="flow-library-drawer"
    >
      <template #header>
        <h2 class="workspace-panel-title text-section-title">
          {{ $t('modules.workflow.addNode') }}
        </h2>
      </template>
      <p class="workspace-panel-intro text-secondary">
        {{ $t('modules.workflow.addNodeIntro') }}
      </p>
      <button
        v-for="module in libraryModules"
        :key="module.shape"
        type="button"
        class="module-option"
        @click="addLibraryNode(module.shape)"
      >
        <span :class="['module-icon', module.tone]">
          <component :is="module.icon" />
        </span>
        <span>
          <strong class="text-body">{{ $t(module.labelKey) }}</strong>
          <span class="text-secondary">{{ module.operatorKeys.map(key => $t(key)).join(' / ') }}</span>
        </span>
        <Plus />
      </button>
    </el-drawer>

    <DrawerFrame
      ref="drawerFrameRef"
      :title="drawerTitle"
      :node-label="drawerBasics.label"
      :operator-count="drawerOperatorCount"
      :tone="drawerTone"
      :fixed="drawerFixed"
      :fixed-direction="drawerFixedDirection"
      :fixed-field="drawerFixedField"
      :upstreams="drawerBasics.upstreams"
      :upstream-options="drawerUpstreamOptions"
      @update:node-label="drawerBasics.label = $event"
      @update:upstreams="drawerBasics.upstreams = $event"
      @delete="deleteCurrentNode"
      @submitHandle="drawerSubmitHandle"
      @cancelHandle="drawerCancelHandle"
      @closed="drawerCancelHandle"
    >
      <component
        :is="dynamicComponent"
        v-if="dynamicComponent && isComponentLoaded"
        :ref="`${currentNodeData?.componentType}Ref`"
        :form-data="currentNodeData.variables"
        :node-id="currentNodeData.id"
        :component-type="currentNodeData?.componentType"
        @config-error="showDrawerError"
        @operator-count="drawerOperatorCount = $event"
      />
    </DrawerFrame>
  </WorkspaceShell>
</template>
<script setup>
import {
  Check, Plus, Minus, VideoPlay, CircleCheck, RefreshLeft, Aim, FullScreen, Close, Setting, Rank, Delete,
  MagicStick, Search, Histogram, ChatDotRound, Document, Share, Coin
} from '@/shared/lib/icons';
import { requestDeletion } from '@/shared/composables/deletion';
import WorkspaceShell from '@/app/layout/WorkspaceShell.vue';
import { WorkflowIcon } from '@/shared/ui/icons';
</script>
<script>
import { Graph, Shape } from '@antv/x6'
import { register, getTeleport } from '@antv/x6-vue-shape'
import { useNodeConfig, getGraphColors, withGraphColors } from '@/features/workflow/useNodeConfig'
import { replaceNodeVariables } from '@/features/workflow/lib/cellData'
import { THEME_CHANGE_EVENT } from '@/shared/lib/theme'
import {
  DEFAULT_CUSTOM_NODE_WIDTH, DEFAULT_CUSTOM_NODE_HEIGHT } from '@/features/workflow/lib/workflow'
import {
  directionOf,
  flowCurve,
  getNodeOperators,
  isFixedShape,
  moduleKeyOf,
  nodeGeometry,
  portPosition,
  portSide,
  portSideFromPoint
} from '@/features/workflow/lib/flowGeometry'
import QUERY from '@/features/workflow/modules/queryNode.vue'
import RESPONSE from '@/features/workflow/modules/responseNode.vue'
import PRE_RETRIEVER from '@/features/workflow/modules/preretriever/Node.vue'
import RETRIEVER from '@/features/workflow/modules/retriever/Node.vue'
import POST_RETRIEVER from '@/features/workflow/modules/postretriever/Node.vue'
import RESPONSE_SYNTHESIZER from '@/features/workflow/modules/responsesynthesizer/Node.vue'
import CalculatePort from '@/features/workflow/calculatePort'
import { getFlowConfig, saveFlowConfig, exportWorkFlow, checkSaveFlowConfig } from '@/features/workflow/api/workflow';
import DrawerFrame from '@/features/workflow/DrawerFrame.vue'
import { createDefaultVariables } from '@/features/workflow/modules/flowNodeDefaults'
import { download } from '@/shared/lib/utils';
import { v4 as uuidv4 } from 'uuid';
import { debounce } from 'lodash';
import { DEBOUNCETIMELONG } from '@/shared/constants/index.js';
import { h } from 'vue';
import { sourceKindMeta, sourceKindsFromOperators } from '@/features/workflow/lib/retrievalSources'

const { queryNodeConfig, responseNodeConfig,
  PreRetrieverNodeConfig, RetrieverNodeConfig, PostRetrieverNodeConfig,
  ResponseSynthesizerNodeConfig } = useNodeConfig();

const TeleportContainer = getTeleport()

/**
 * edgePath()：先画到目标节点左侧的入口点。
 * 用 `max(60, 水平距离 * 0.45)` 作控制点偏移，环回边（目标在源左侧且
 * 高度接近）从节点上方绕回；这里注册成 X6 connector。
 */
Graph.registerConnector('flow-prototype', (source, target) => {
  const x = source.x
  const y = source.y
  const tx = target.x
  const ty = target.y
  if (tx < x && Math.abs(ty - y) < 30) {
    // top 取节点顶边再上移 30；端口在节点顶边下 72，故此处减 102
    const top = Math.min(y, ty) - 102
    return `M${x},${y} C${x + 40},${y} ${x + 40},${top} ${x},${top} L${tx},${top} C${tx - 40},${top} ${tx - 40},${ty} ${tx},${ty}`
  }
  const bend = Math.max(60, Math.abs(tx - x) * 0.45)
  return `M${x},${y} C${x + bend},${y} ${tx - bend},${ty} ${tx},${ty}`
}, true)

/** .flow-edge：1.6px 圆头细线；颜色/悬停由 CSS（--flow-line）接管。 */
function edgeLineAttrs () {
  return {
    stroke: getGraphColors().edge,
    strokeWidth: 1.6,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    vectorEffect: 'non-scaling-stroke',
    // X6 默认在终点画 classic 箭头；方向由线中段 12×10 箭头表达（t=0.55），
    // 终点箭头会与之重复（短连线几乎叠在一起），这里显式清掉。
    targetMarker: null
  }
}

/**
 * 连接器读取端口所在的一侧，返回贝塞尔控制柄方向。
 * 端口坐标是节点坐标系里的绝对坐标，节点尺寸 = 卡片实际尺寸；
 * 预览边没有目标 cell 时退回左右方向。
 */
function portDirectionFor (edge, end) {
  const nodeId = end === 'source' ? edge.getSourceCellId() : edge.getTargetCellId()
  const portId = end === 'source' ? edge.getSourcePortId() : edge.getTargetPortId()
  const node = nodeId ? edge.model?.getCell(nodeId) : null
  if (!node || !portId) {
    return directionOf(end === 'source' ? 'right' : 'left')
  }
  const args = node.getPort(portId)?.args || {}
  const size = node.getSize()
  // 下端口 y = geometry.height，而节点高 = frameHeight（多 2px 描边），
  // 不能按 0.5px 容差判等，否则会退回左右朝向、把连线画成绕回来的圈。
  const side = portSideFromPoint({ x: args.x, y: args.y, width: size.width, height: size.height })
  return directionOf(side || (end === 'source' ? 'right' : 'left'))
}

Graph.registerConnector('flow-adaptive', (source, target, routePoints, options, view) => {
  const edge = view?.cell
  const a = edge ? portDirectionFor(edge, 'source') : directionOf('right')
  // 预览边还没有目标 cell：控制柄取起点的反方向（{dx:-a.dx}）
  const b = edge && edge.getTargetCellId()
    ? portDirectionFor(edge, 'target')
    : { dx: -a.dx, dy: -a.dy }
  return flowCurve(
    { x: source.x, y: source.y },
    { x: target.x, y: target.y },
    a,
    b
  ).path
}, true)

export default {
  name: 'CustomizedAdvancedFlow',
  components: {
    DrawerFrame,
    TeleportContainer
  },
  mixins: [CalculatePort],
  data () {
    return {
      graph: null,
      fullscreen: false,
      // 全屏时的「编排与操作」浮层：页头操作与工具条 Teleport 进去
      toolsOpen: false,
      // 「添加节点」放在抽屉里，画布默认占满整行；需要时点工具条按钮再展开。
      libraryVisible: false,
      currentNodeId: '',
      drawerInputs: [],
      libraryModules: [
        { shape: 'preretriever', labelKey: 'ragFlow.preretrieverTitle', tone: 'purple', icon: MagicStick, operatorKeys: ['ragFlow.LLMQueryRewriterOperator'] },
        { shape: 'retriever', labelKey: 'ragFlow.retrieverTitle', tone: 'orange', icon: Search, operatorKeys: ['ragFlow.KnowledgeGraphRetrieverOperator', 'ragFlow.FusionRetrieverOperator', 'ragFlow.VectorRetrieverOperator', 'ragFlow.KeywordRetrieverOperator'] },
        { shape: 'postretriever', labelKey: 'ragFlow.postretrieverTitle', tone: 'blue', icon: Histogram, operatorKeys: ['ragFlow.LLMRerankerOperator', 'ragFlow.ExternalModelRerankerOperator'] },
        { shape: 'responsesynthesizer', labelKey: 'ragFlow.responsesynthesizerTitle', tone: 'green', icon: ChatDotRound, operatorKeys: ['ragFlow.RagSimpleSummarizerOperator'] }
      ],
      nodeCount: 0,
      edgeCount: 0,
      operatorCount: 0,
      sourceKinds: [],
      selectedEdge: null,
      connectingSource: '',
      connectingSourceLabel: '',
      connectingPortId: '',
      connectionTargetId: '',
      previewEdgeId: '',
      hoveredPortEl: null,
      portSideCache: {},
      decorateFrame: null,
      decorateIdle: null,
      geometryFrame: null,
      drawerBasics: { label: '', upstreams: [] },
      drawerUpstreamOptions: [],
      drawerTone: 'blue',
      drawerFixed: false,
      drawerFixedDirection: '',
      drawerFixedField: '',
      drawerOperatorCount: 0,
      isEditMode: false, // 高级编排画布是否处于编辑模式
      isRunning: false,
      nodeLoaded: true,
      // 画布上这张图属于哪个工作流。切换工作流时先置空，等新数据真的落到图上再置成新 appId。
      // 保存时拿它和 saveAppId 比对，避免把 A 的图存进 B、或把刚清空还没加载完的空图存下去
      graphAppId: '',
      // 本次保存的目标工作流，在点击「保存」那一刻定下来，整条异步链都用它
      saveAppId: '',
      // 缩放条中间的百分比（随 X6 的 scale 事件更新）
      zoomPercent: 100,
      currentDragNodeId: '',
      jsonDTO: {},
      dynamicComponent: null,
      debounceTime: null,
      timerInterval: 300,
      drawerTitle: '',
      queryEngineType: '',
      loadSubmit: false,
      isComponentLoaded: false,
      workflowName: '',
      workflowId: '',
      // 发布态（GET /flow 的 publishType）：0 未发布 / 1 已发布 / 2 发布后修改。
      // 保存草稿不会改变线上快照；据此在保存成功后提示「要重新发布」。
      workflowPublishType: 0,
      currentNodeData: {
        label: '',
        componentType: '',
        variables: ''
      },
      version: 1,
      shapeAndPortIdMap: {
        PRE_RETRIEVER: 'preretriever',
        RETRIEVER: 'retriever',
        POST_RETRIEVER: 'postretriever',
        RESPONSE_SYNTHESIZER: 'responsesynthesizer'
      },
      queryengineMap: {
        SequentialQueryEngine: {
          id: 0,
          package: 'core.rag.query_engine.sequential_query_engine',
          operator: 'SequentialQueryEngine',
          desc: '',
          kwargs: {}
        },
        ConditionalQueryEngine: {
          id: 0,
          package: 'core.rag.query_engine.conditional_query_engine',
          operator: 'ConditionalQueryEngine',
          desc: '',
          kwargs: {}
        },
        BlendedQueryEngine: {
          id: 0,
          package: 'core.rag.query_engine.blended_query_engine',
          operator: 'BlendedQueryEngine',
          desc: '',
          kwargs: {}
        }
      },
      workflowTypeMap: {
        SequentialQueryEngine: this.$t('ragFlow.sequenceWorkflow'),
        ConditionalQueryEngine: this.$t('ragFlow.conditionWorkflow'),
        BlendedQueryEngine: this.$t('ragFlow.mixWorkflow')
      },
      debouncedInput: null,
      loading: false,
      // 等 X6 把视图渲染完（render:done）再做 100% 排版：提前量 DOM 会量不到
      // Vue 卡片，只能退回 1×1/250 的默认值，节点会叠在一起。
      pendingArrange: false,
      arrangeFallbackTimer: null,
      arrangeRetryTimer: null,
      lastCardSizeSignature: ''
    }
  },
  watch: {
    // 只换 id 时（#/flow/detail/A → #/flow/detail/B）属于同一路由只变参数，
    // Vue Router 会复用本组件实例、mounted 不会再跑 —— 不监听的话画布会一直
    // 停留在上一个工作流的图上（标题/URL 已经变了，图还是旧的）
    '$route.params.id' () {
      this.reloadAdvancedFlow();
    }
  },
  created () {
  },
  mounted () {
    this.initGraph();
    this.setGraphEventAndNodeInfo();
    this.getAdvancedFlowConfig();

    // 用 ResizeObserver 跟随容器：首帧量到的尺寸可能
    // 早于字体/布局落定，这里等画布盒子真正稳定后再让 X6 重算一次。
    const viewport = this.$el?.querySelector?.('.canvas-viewport')
    if (viewport && typeof ResizeObserver !== 'undefined') {
      this.canvasResizeObserver = new ResizeObserver(() => this.setGraphSize())
      this.canvasResizeObserver.observe(viewport)
    }
    window.addEventListener('resize', this.setGraphSize)
    window.addEventListener('keydown', this.handleFullscreenEsc)
    // 主题切换时原地重刷连线/链接桩的颜色（不重建 Graph，节点坐标与视口保持不变）
    this.themeChangeHandler = () => this.applyGraphTheme()
    window.addEventListener(THEME_CHANGE_EVENT, this.themeChangeHandler)
    this.connectionKeyHandler = event => this.handleConnectionKey(event)
    document.addEventListener('keydown', this.connectionKeyHandler, true)
  },
  beforeUnmount () {
    if (this.canvasResizeObserver) {
      this.canvasResizeObserver.disconnect()
      this.canvasResizeObserver = null
    }
    window.removeEventListener('resize', this.setGraphSize);
    window.removeEventListener('keydown', this.handleFullscreenEsc);
    if (this.themeChangeHandler) {
      window.removeEventListener(THEME_CHANGE_EVENT, this.themeChangeHandler)
      this.themeChangeHandler = null
    }
    // 排版是在等卡片 DOM 的轮询里完成的，离开页面时要停掉，避免对已销毁的图操作
    this.pendingArrange = false
    if (this.arrangeFallbackTimer) {
      clearTimeout(this.arrangeFallbackTimer)
    }
    if (this.arrangeRetryTimer) {
      clearTimeout(this.arrangeRetryTimer)
    }
    this.cancelConnection()
    if (this.connectionKeyHandler) {
      document.removeEventListener('keydown', this.connectionKeyHandler, true)
      this.connectionKeyHandler = null
    }
    if (this.decorateFrame) {
      cancelAnimationFrame(this.decorateFrame)
      this.decorateFrame = null
    }
    if (this.decorateIdle) {
      if (typeof window.cancelIdleCallback === 'function') {
        window.cancelIdleCallback(this.decorateIdle)
      } else {
        clearTimeout(this.decorateIdle)
      }
      this.decorateIdle = null
    }
    if (this.geometryFrame) {
      cancelAnimationFrame(this.geometryFrame)
      this.geometryFrame = null
    }
  },
  methods: {
    initGraph () {
      const { width, height } = this.getCanvasSize()
      this.graph = new Graph({
        container: document.getElementById('advancedFLow'),
        width,
        height,
        panning: true, // 画布支持拖拽平移
        mousewheel: { // 画布支持滚轮缩放（缩放范围 0.2–1.6）
          enabled: true,
          minScale: 0.2,
          maxScale: 1.6
        },
        interacting: () => {
          return true // 默认为false 即默认不让画布具备交互能力 即只读模式
        },
        connecting: { // 连线
          connector: {
            name: 'flow-adaptive'
          },
          // 端口坐标就是连线端点（x/y），不能再按节点边界裁一次
          anchor: 'center',
          connectionPoint: 'anchor',
          allowBlank: false,
          allowLoop: false,
          allowMulti: false,
          snap: {
            radius: 20
          },
          createEdge: () => {
            // 拖动中的预览边：虚线主色；连上后 edge:connected 会把样式还原
            const edge = new Shape.Edge({
              attrs: {
                line: {
                  ...edgeLineAttrs(),
                  strokeDasharray: '6 5'
                }
              },
              data: { preview: true }
            })
            return edge
          },
          validateMagnet: ({ magnet }) => {
            const group = magnet?.getAttribute('port-group') || magnet?.parentElement?.getAttribute('port-group')
            return group === 'out'
          },
          validateConnection: ({ sourceCell, targetCell, sourceMagnet, targetMagnet }) => {
            if (!sourceCell || !targetCell || sourceCell.id === targetCell.id) {
              return false
            }
            // 连线只允许从输出桩连到输入桩
            const sourceGroup = sourceMagnet?.getAttribute('port-group')
            const targetGroup = targetMagnet?.getAttribute('port-group') || targetMagnet?.parentElement?.getAttribute('port-group')
            if (sourceGroup !== 'out' || targetGroup !== 'in') {
              return false
            }
            if (this.graph.getEdges().some(edge =>
              edge.getSourceCellId() === sourceCell.id && edge.getTargetCellId() === targetCell.id
            )) {
              return false
            }
            return !this.wouldCreateCycle(sourceCell.id, targetCell.id)
          }
        }
      })
      this.zoomPercent = Math.round(this.graph.zoom() * 100)
      this.graph.on('scale', ({ sx }) => {
        this.zoomPercent = Math.round(sx * 100)
      })
    },
    /**
     * @description: 按当前主题的 --rs-graph-* 原地刷新已有连线与链接桩的颜色。
     *
     * 只写 paint 属性（line/stroke、circle/fill|stroke、dot/fill），
     * 不动 strokeWidth、r、端口位置、连接器与节点尺寸 —— 切换主题前后几何不变。
     * 版本/选区/视口都由 X6 自己保留，无需重建 Graph。
     */
    applyGraphTheme () {
      if (!this.graph) {
        return
      }
      const { portFill, portStroke } = getGraphColors()
      this.graph.getEdges().forEach(edgeCell => {
        // 描边与箭头 marker 一起重设：marker 的 fill/stroke 不随 line.stroke 自动更新
        edgeCell.attr('line', edgeLineAttrs())
      })
      this.graph.getNodes().forEach(node => {
        ;(node.getPorts() || []).forEach(port => {
          node.portProp(port.id, 'attrs/circle/stroke', portStroke)
          node.portProp(port.id, 'attrs/circle/fill', portFill)
          node.portProp(port.id, 'attrs/dot/fill', portStroke)
        })
      })
    },
    // 画布尺寸取「可见绘图区」（.canvas-viewport），不能用 document：
    // document 会把左侧栏也算进来，画布比可见区域更宽更高，右/下缘的节点会被裁掉。
    getCanvasSize () {
      const area = this.$el?.querySelector?.('.canvas-viewport')
      if (!area) {
        return {
          width: document.documentElement.clientWidth,
          height: document.documentElement.clientHeight
        }
      }
      const style = window.getComputedStyle(area)
      return {
        width: area.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0),
        height: area.clientHeight - parseFloat(style.paddingTop || 0) - parseFloat(style.paddingBottom || 0)
      }
    },
    /**
     * @description: 节点的**渲染尺寸**（画布坐标，不含当前缩放）。
     *
     * 不能直接用 node.getSize()：画布数据里的 size 是 1×1（模板就是这样），
     * Vue 卡片靠 CSS 溢出显示成 240px 宽、高度随内容变化。按 1×1 排版会让所有节点
     * 叠在一起。这里量卡片 DOM，再除以当前缩放换算回画布坐标。
     */
    getNodeDisplaySize (node) {
      const view = this.graph?.findViewByCell?.(node)
      const card = view?.container?.querySelector?.('.ai-card-frame')
      const rect = card?.getBoundingClientRect?.()
      const zoom = this.graph?.zoom?.() || 1
      if (rect && rect.width > 0 && rect.height > 0) {
        return { width: rect.width / zoom, height: rect.height / zoom }
      }
      return { width: DEFAULT_CUSTOM_NODE_WIDTH, height: DEFAULT_CUSTOM_NODE_HEIGHT }
    },
    /**
     * 进入工作流时：先让节点尺寸/端口符合卡片几何，再决定是否重排。
     *
     * 首次打开工作流时卡片几何可能与库里坐标不一致，按基准布局
     * 重排一次并记到 localStorage；之后保留用户自己拖动/保存的布局，只做适应画布。
     *
     * ⚠️ 不要再按「100% 下是否放得下」触发重排（原 `nodesFitViewport()` 分支）：
     * 那会在每次加载时把**库里存的布局**悄悄换成自动排版，而「撤销更改」重新
     * 拉的正是库里的布局 —— 用户什么都没改，点撤销却看到卡片全部挪位。
     * 放不下的情况交给 `zoom('fit')` 缩放展示，坐标本身不动。
     */
    applyInitialLayout () {
      if (!this.graph?.getNodes?.().length) {
        return
      }
      this.syncAllNodeGeometry()
      const key = `ragstudio:flow-layout-v016:${this.$route.params.id}`
      let migrated = false
      try {
        migrated = window.localStorage.getItem(key) === '1'
      } catch (error) {
        migrated = false
      }
      if (!migrated) {
        this.layoutWorkflowNodes()
        try {
          window.localStorage.setItem(key, '1')
        } catch (error) {
          // 无痕模式等场景写不了 localStorage：本次重排仍然生效
        }
      }
      this.$nextTick(() => this.zoom('fit'))
    },
    setGraphSize () {
      if (this.debounceTime) {
        clearTimeout(this.debounceTime);
      }
      this.debounceTime = setTimeout(() => {
        const { width, height } = this.getCanvasSize()
        this.graph.resize(width, height)
      }, this.timerInterval);
    },
    setGraphEventAndNodeInfo () {
      // 注册画布监听事件
      this.graphListenDone();
      this.graphListenConnected();
      this.graphListenRemoved();
      this.graphListenGeometry();
      this.graphListenPorts();

      // 注册自定义vue节点
      this.registerCustomNodeBundle();
    },
    // 在调用 fromJSON 或者 resetCells 后监听画布完成渲染事件
    graphListenDone () {
      this.graph.on('render:done', () => {
        this.nodeLoaded = false
        this.syncGraphStats()
        // 批量导入/新建后按当前主题刷一次连线与端口颜色（只改 paint）
        this.applyGraphTheme()
        // 视图（含 Vue 卡片 DOM）已就绪，这时量尺寸/排版才准确
        this.runPendingArrange()
      })
    },
    // render:done 后还不能立刻排版：x6-vue-shape 的卡片是 **Teleport** 到
    // foreignObject 里的，render:done 时卡片 DOM 还没挂上（querySelector 为空）。
    // 这里轮询等待「所有卡片都出现，且高度连续两次采样一致」，再做排版。
    runPendingArrange (attempt = 0) {
      if (!this.pendingArrange || this.arrangeRetryTimer) {
        return
      }
      if (attempt === 0 && this.arrangeFallbackTimer) {
        clearTimeout(this.arrangeFallbackTimer)
        this.arrangeFallbackTimer = null
      }
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          if (!this.pendingArrange || this.arrangeRetryTimer) {
            return
          }
          const nodes = this.graph?.getNodes?.() || []
          const cards = nodes.map(node => this.graph.findViewByCell(node)?.container?.querySelector?.('.ai-card-frame'))
          const allMounted = cards.length > 0 && cards.every(Boolean)
          // 高度可能随异步数据（知识库/模型下拉）二次增长，连续两次一致才认为稳定
          const signature = allMounted
            ? cards.map(card => Math.round(card.getBoundingClientRect().height)).join(',')
            : ''
          const stable = allMounted && signature === this.lastCardSizeSignature
          this.lastCardSizeSignature = signature
          if (!stable && attempt < 40) {
            this.arrangeRetryTimer = setTimeout(() => {
              this.arrangeRetryTimer = null
              this.runPendingArrange(attempt + 1)
            }, 50)
            return
          }
          this.pendingArrange = false
          this.lastCardSizeSignature = ''
          this.applyInitialLayout()
        })
      })
    },
    graphListenMouseenter () {
      this.graph.on('edge:mouseenter', ({ edge }) => {
        edge.addTools(
          {
            name: 'button-remove',
            args: { distance: -40 }
          }
        )
      })
    },
    graphListenMouseleave () {
      this.graph.on('edge:mouseleave', ({ cell }) => {
        if (cell.hasTool('button-remove')) {
          cell.removeTool('button-remove')
        }
      })
    },
    graphListenConnected () {
      this.graph.on('edge:connected', ({ edge }) => {
        // 拖动预览边连上后还原为正式连线（虚线 → 实线、去掉 preview 标记）
        if (edge.getData()?.preview) {
          edge.setData({ preview: false })
          edge.attr('line', edgeLineAttrs())
        }
        this.scheduleGeometrySync()
        this.scheduleEdgeDecorations()
        this.$nextTick(() => this.syncGraphStats())
        const source = edge.getSourceCell()
        const target = edge.getTargetCell()
        const sourcePortId = edge.getSourcePortId()
        const targetPortId = edge.getTargetPortId()

        // 当连线结束后 给线条终端加上同心圆样式
        target.portProp(targetPortId, {
          group: 'in',
          attrs: {
            dot: {
              magnet: true,
              fill: getGraphColors().portStroke,
              r: 4
            }
          }
        })

        // 如果存在定制化的连线的限制 在此设置

        target.setData({
          type: 'add',
          sourceNode: source.id,
          label: source.store.data.label,
          key: sourcePortId
        })
        // 更新输出连接桩位置
        this.updateOuputPortForSingleOutput(target)
      })
    },
    graphListenRemoved () {
      this.graph.on('edge:removed', ({ cell }) => {
        this.$nextTick(() => this.syncGraphStats())
        const target = this.graph.getCellById(cell.store.data.target.cell)
        const sourcePortId = cell.getSourcePortId()

        target && target.setData({
          type: 'remove',
          deleteInput: cell.store.data.source.cell,
          key: sourcePortId
        })

        if (target) {
          const incomingE = this.graph.getIncomingEdges(target.id)
          const numOfIncomingEdges = incomingE?.length
          // 如果一个连接桩 删除至没有进来的连线了 那么就把连接桩恢复成圆形样式
          if (!numOfIncomingEdges) {
            target.portProp(cell.getTargetPortId(), {
              group: 'in',
              attrs: {
                dot: {
                  magnet: true,
                  fill: getGraphColors().portFill,
                  r: 0
                }
              }
            })
          }
        }

        // 更新连接桩位置
        this.updateOuputPortForSingleOutput(target)
      })
    },
    /**
     * @description: 注册自定义VUE节点
     *
     * @param {string} shape 节点类型
     * 定义了 shape 以后 该名称可以用于配合graph的addNode和createNode方法中的shape属性联合使用
     * @param {VueShape} vueNode 即自定义的vue文件
     * */
    /**
     * 卡片几何：节点尺寸、端口方位、连线箭头都随「算子条数 / 上游输入数」变化。
     * 任何会影响几何的 X6 事件都只打一个 rAF 标记，同一帧里只重算一次。
     */
    graphListenGeometry () {
      const schedule = () => {
        this.scheduleGeometrySync()
        this.scheduleEdgeDecorations()
      }
      // 拖动过程中 X6 只发 node:moving（node:moved 要等松手），
      // 线中段箭头是自绘的，必须逐帧跟算，否则会停在原位、松手后才追上。
      this.graph.on('node:moving', () => this.scheduleEdgeDecorations())
      this.graph.on('node:moved', schedule)
      this.graph.on('node:resized', schedule)
      this.graph.on('node:added', schedule)
      this.graph.on('node:change:data', () => {
        schedule()
        this.syncGraphStats()
      })
      this.graph.on('edge:added', ({ edge }) => {
        if (!edge.getData()?.preview) {
          this.scheduleGeometrySync()
        }
        this.scheduleEdgeDecorations()
        this.syncGraphStats()
      })
      this.graph.on('edge:removed', () => {
        this.scheduleGeometrySync()
        this.scheduleEdgeDecorations()
        this.syncGraphStats()
      })
      this.graph.on('edge:connected', () => {
        this.scheduleGeometrySync()
        this.scheduleEdgeDecorations()
        this.syncGraphStats()
      })
      this.graph.on('scale', () => this.scheduleEdgeDecorations())
    },
    graphListenPorts () {
      this.graph.on('node:port:mousedown', ({ e }) => {
        this.portPointerDown = { x: e.clientX, y: e.clientY, dragged: false }
      })
      this.graph.on('node:port:mouseup', ({ e }) => {
        if (this.portPointerDown) {
          this.portPointerDown.dragged = Math.hypot(
            e.clientX - this.portPointerDown.x,
            e.clientY - this.portPointerDown.y
          ) > 4
        }
      })
      this.graph.on('node:port:click', ({ node, port }) => {
        // 拖动建立连线后浏览器仍可能补一个 click；有位移就不再进入点击模式
        const dragged = this.portPointerDown?.dragged
        this.portPointerDown = null
        if (dragged) {
          return
        }
        const config = node.getPort(port)
        if (!config) {
          return
        }
        if (config.group === 'out') {
          this.beginClickConnection(node, port)
        } else if (config.group === 'in' && this.connectingSource) {
          this.finishClickConnection(node)
        }
      })
      this.graph.on('edge:click', ({ edge }) => this.selectEdge(edge))
      this.graph.on('node:mousedown', ({ node }) => {
        if (!node) {
          return
        }
        this.selectedEdge = null
        this.selectNodeView(node.id)
      })
      this.graph.on('blank:click', () => {
        this.selectedEdge = null
        this.cancelConnection()
        this.clearNodeSelection()
        this.scheduleEdgeDecorations()
      })
    },
    moduleTitleKeyOf (shape) {
      return {
        PRE_RETRIEVER: 'ragFlow.preretrieverTitle',
        RETRIEVER: 'ragFlow.retrieverTitle',
        POST_RETRIEVER: 'ragFlow.postretrieverTitle',
        RESPONSE_SYNTHESIZER: 'ragFlow.responsesynthesizerTitle',
        QUERY: 'ragFlow.start',
        RESPONSE: 'ragFlow.end'
      }[shape] || ''
    },
    moduleTitleOf (shape) {
      const key = this.moduleTitleKeyOf(shape)
      return key ? this.$t(key) : ''
    },
    moduleToneOf (shape) {
      return {
        PRE_RETRIEVER: 'purple',
        RETRIEVER: 'orange',
        POST_RETRIEVER: 'blue',
        RESPONSE_SYNTHESIZER: 'green',
        QUERY: 'blue',
        RESPONSE: 'blue'
      }[shape] || 'blue'
    },
    /** source→target 是否会形成环：从 target 顺着出边能走回 source 即为环。 */
    wouldCreateCycle (sourceId, targetId) {
      return this.wouldCreateCycleInEdges(
        (this.graph?.getEdges?.() || [])
          .filter(edge => !edge.getData()?.preview)
          .map(edge => ({
            source: edge.getSourceCellId(),
            target: edge.getTargetCellId()
          })),
        sourceId,
        targetId
      )
    },
    wouldCreateCycleInEdges (edges, sourceId, targetId) {
      const outgoing = new Map()
      edges.forEach(edge => {
        if (!outgoing.has(edge.source)) {
          outgoing.set(edge.source, [])
        }
        outgoing.get(edge.source).push(edge.target)
      })
      const seen = new Set()
      const pending = [targetId]
      while (pending.length) {
        const id = pending.pop()
        if (id === sourceId) {
          return true
        }
        if (seen.has(id)) {
          continue
        }
        seen.add(id)
        pending.push(...(outgoing.get(id) || []))
      }
      return false
    },
    nodeVariables (node) {
      const data = node?.store?.data || {}
      return data.data?.variables ?? data.variables
    },
    nodeGeometryFor (node) {
      const shape = node?.shape || node?.store?.data?.shape
      const variables = this.nodeVariables(node)
      const operators = getNodeOperators({ shape, variables })
      const inputCount = (this.graph?.getIncomingEdges?.(node.id) || []).length
      return nodeGeometry({ shape, operatorCount: operators.length, inputCount })
    },
    scheduleGeometrySync () {
      if (this.geometryFrame) {
        return
      }
      this.geometryFrame = requestAnimationFrame(() => {
        this.geometryFrame = null
        this.syncAllNodeGeometry()
      })
    },
    /**
     * 让 X6 节点尺寸 / 端口坐标与卡片几何一致。
     *
     * 卡片宽度固定 264、高度由算子行和上游输入行决定；端口在左/右/上/下四边中
     * 选择朝向，删掉连线后保持上一次朝向（portSideCache）。
     */
    syncAllNodeGeometry () {
      if (!this.graph) {
        return
      }
      const infos = new Map()
      this.graph.getNodes().forEach(node => {
        const geometry = this.nodeGeometryFor(node)
        infos.set(node.id, { node, geometry })
        const size = node.getSize()
        if (Math.abs(size.width - geometry.width) > 0.5 || Math.abs(size.height - geometry.frameHeight) > 0.5) {
          node.resize(geometry.width, geometry.frameHeight, { silent: true })
        }
      })
      infos.forEach(({ node, geometry }) => {
        const position = node.getPosition()
        const peersFor = direction => {
          const edges = direction === 'output'
            ? (this.graph.getOutgoingEdges(node.id) || [])
            : (this.graph.getIncomingEdges(node.id) || [])
          return edges.map(edge => {
            const id = direction === 'output' ? edge.getTargetCellId() : edge.getSourceCellId()
            const peer = infos.get(id)
            if (!peer) {
              return null
            }
            const peerPosition = peer.node.getPosition()
            return {
              x: peerPosition.x,
              y: peerPosition.y,
              width: peer.geometry.width,
              height: peer.geometry.height
            }
          }).filter(Boolean)
        }
        const previous = this.portSideCache[node.id] || {}
        const outputSide = portSide({
          node: position,
          peers: peersFor('output'),
          geometry,
          direction: 'output',
          fallbackSide: previous.output
        })
        const inputSide = portSide({
          node: position,
          peers: peersFor('input'),
          geometry,
          direction: 'input',
          fallbackSide: previous.input
        })
        this.portSideCache[node.id] = { input: inputSide, output: outputSide }
        this.applyPortPosition(node, 'in', inputSide, 'input', geometry)
        this.applyPortPosition(node, 'out', outputSide, 'output', geometry)
      })
      this.scheduleEdgeDecorations()
    },
    applyPortPosition (node, group, side, direction, geometry) {
      const port = node.getPortsByGroup(group)?.[0]
      if (!port) {
        return
      }
      const point = portPosition({ geometry, side, direction })
      const current = port.args || {}
      if (Math.abs((current.x || 0) - point.x) < 0.01 && Math.abs((current.y || 0) - point.y) < 0.01) {
        return
      }
      node.portProp(port.id, 'args', point)
    },
    /** 线中段的实心箭头：在 t=0.55 处画 12×10、随缩放反比缩放、带画布底色描边。 */
    scheduleEdgeDecorations () {
      if (this.decorateFrame) {
        return
      }
      this.decorateFrame = requestAnimationFrame(() => {
        this.decorateFrame = null
        this.decorateEdges()
        // X6 的边视图更新（端口移动后的端点/路径重算）排在 requestIdleCallback 队列里，
        // 可能晚于这里的 rAF：箭头会先按旧端点贴一次，路径随后才变，箭头就留在了原地。
        // 收尾等空闲队列刷完再贴一次，箭头才落在最终曲线上。
        this.scheduleEdgeSettle()
      })
    },
    scheduleEdgeSettle () {
      if (this.decorateIdle) {
        return
      }
      const run = () => {
        this.decorateIdle = null
        this.decorateEdges()
      }
      if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
        this.decorateIdle = window.requestIdleCallback(run, { timeout: 120 })
      } else {
        this.decorateIdle = window.setTimeout(run, 0)
      }
    },
    decorateEdges () {
      if (!this.graph) {
        return
      }
      const zoom = this.graph.zoom() || 1
      this.graph.getEdges().forEach(edge => {
        const view = this.graph.findViewByCell(edge)
        if (!view?.container) {
          return
        }
        const preview = !!edge.getData()?.preview
        view.container.classList.toggle('flow-edge-preview', preview)
        view.container.classList.toggle('flow-connection', !preview)
        view.container.classList.toggle('selected', !preview && this.selectedEdge?.id === edge.id)
        if (preview) {
          return
        }
        const hit = view.container.querySelector('path')
        if (hit) {
          hit.setAttribute('tabindex', '0')
          hit.setAttribute('role', 'button')
          hit.setAttribute(
            'aria-label',
            this.$t('modules.workflow.selectEdgeLabel', {
              source: this.nodeDisplayName(edge.getSourceCellId()),
              target: this.nodeDisplayName(edge.getTargetCellId())
            })
          )
        }
        let arrow = view.container.querySelector('.flow-edge-direction')
        if (!arrow) {
          arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path')
          arrow.setAttribute('d', 'M-6,-5 L6,0 L-6,5 L-2,0 Z')
          arrow.setAttribute('class', 'flow-edge-direction')
          view.container.appendChild(arrow)
        }
        const source = view.sourcePoint
        const target = view.targetPoint
        if (!source || !target) {
          return
        }
        const a = portDirectionFor(edge, 'source')
        const b = portDirectionFor(edge, 'target')
        const connection = flowCurve(
          { x: source.x, y: source.y },
          { x: target.x, y: target.y },
          a,
          b
        )
        arrow.setAttribute(
          'transform',
          `translate(${connection.arrow.x},${connection.arrow.y}) rotate(${connection.arrow.angle}) scale(${1 / zoom})`
        )
      })
      this.decoratePortA11y()
    },
    /** X6 的端口是 SVG 圆点：补 tabindex/role/aria，支持键盘 Tab + Enter 连线。 */
    decoratePortA11y () {
      this.graph?.getNodes?.().forEach(node => {
        const view = this.graph.findViewByCell(node)
        const title = this.moduleTitleOf(node.shape) || node.store?.data?.label || node.id
        ;(node.getPorts() || []).forEach(port => {
          if (!port?.id) {
            return
          }
          const element = view?.container?.querySelector?.(`[port="${port.id}"]`)
          if (!element) {
            return
          }
          element.setAttribute('tabindex', '0')
          element.setAttribute('role', 'button')
          element.setAttribute(
            'aria-label',
            port.group === 'out'
              ? this.$t('modules.workflow.connectFromNode', { name: title })
              : this.$t('modules.workflow.connectToNode', { name: title })
          )
        })
      })
    },
    handleCanvasKeydown (event) {
      if (event.key !== 'Enter' && event.key !== ' ') {
        return
      }
      const portEl = event.target?.closest?.('.x6-port-body')
      if (!portEl) {
        const edgeEl = event.target?.closest?.('.x6-edge')
        const edge = edgeEl ? this.graph.getCellById(edgeEl.getAttribute('data-cell-id')) : null
        if (edge && !edge.getData()?.preview) {
          event.preventDefault()
          event.stopPropagation()
          this.selectEdge(edge)
        }
        return
      }
      event.preventDefault()
      event.stopPropagation()
      const group = portEl.getAttribute('port-group')
      const nodeId = portEl.closest('.x6-cell')?.getAttribute('data-cell-id')
      const portId = portEl.getAttribute('port')
      const node = nodeId ? this.graph.getCellById(nodeId) : null
      if (!node) {
        return
      }
      if (group === 'out') {
        this.beginClickConnection(node, portId)
      } else if (group === 'in' && this.connectingSource) {
        this.finishClickConnection(node)
      }
    },
    nodeDisplayName (id) {
      const node = this.graph?.getCellById?.(id)
      if (!node) {
        return id
      }
      return this.moduleTitleOf(node.shape) || node.store?.data?.label || id
    },
    selectEdge (edge) {
      this.cancelConnection()
      this.selectedEdge = {
        id: edge.id,
        sourceLabel: this.nodeDisplayName(edge.getSourceCellId()),
        targetLabel: this.nodeDisplayName(edge.getTargetCellId())
      }
      this.scheduleEdgeDecorations()
    },
    async removeSelectedEdge () {
      const edge = this.selectedEdge
      if (!edge) {
        return
      }
      const confirmed = await requestDeletion({
        resourceType: this.$t('modules.workflow.resourceEdge'),
        title: this.$t('modules.workflow.removeEdge'),
        warning: this.$t('modules.workflow.removeEdgeWarning'),
        description: this.$t('modules.workflow.removeEdgeDescription'),
        items: [{ id: edge.id, name: `${edge.sourceLabel} → ${edge.targetLabel}` }],
        verification: false,
        hint: this.$t('modules.workflow.removeEdgeHint'),
        confirmText: this.$t('modules.workflow.removeEdgeConfirm')
      })
      if (!confirmed) {
        return
      }
      this.selectedEdge = null
      this.graph.removeEdge(edge.id)
      this.scheduleEdgeDecorations()
    },
    selectNodeView (id) {
      this.clearNodeSelection()
      const node = this.graph?.getCellById?.(id)
      const view = node ? this.graph.findViewByCell(node) : null
      view?.container?.classList.add('selected')
    },
    clearNodeSelection () {
      this.graph?.getNodes?.().forEach(node => {
        this.graph.findViewByCell(node)?.container?.classList.remove('selected')
      })
    },
    handleConnectionKey (event) {
      if (event.key !== 'Escape') {
        return
      }
      if (this.connectingSource) {
        event.preventDefault()
        event.stopPropagation()
        this.cancelConnection()
        return
      }
      if (this.selectedEdge) {
        this.selectedEdge = null
        this.scheduleEdgeDecorations()
      }
    },
    /** 点击输出端点后进入「点击-点击」连线模式，并挂一条跟随鼠标的预览边。 */
    beginClickConnection (node, portId) {
      this.cancelConnection()
      this.selectedEdge = null
      this.clearNodeSelection()
      this.connectingSource = node.id
      this.connectingSourceLabel = this.nodeDisplayName(node.id)
      this.connectingPortId = portId
      const config = node.getPort(portId)
      const position = node.getPosition()
      const args = config?.args || { x: 0, y: 0 }
      const edge = new Shape.Edge({
        source: { cell: node.id, port: portId },
        target: { x: position.x + (args.x || 0), y: position.y + (args.y || 0) },
        attrs: {
          line: {
            ...edgeLineAttrs(),
            strokeDasharray: '6 5'
          }
        },
        zIndex: 0,
        data: { preview: true }
      })
      this.graph.addEdge(edge)
      this.previewEdgeId = edge.id
      this.scheduleEdgeDecorations()
    },
    updateClickConnection (event) {
      if (!this.connectingSource || !this.previewEdgeId) {
        return
      }
      const edge = this.graph.getCellById(this.previewEdgeId)
      if (!edge) {
        return
      }
      const point = this.graph.clientToLocal(event.clientX, event.clientY)
      edge.setTarget(point)
      const portEl = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.x6-port-body')
      const group = portEl?.getAttribute('port-group') || portEl?.parentElement?.getAttribute('port-group')
      const nodeId = portEl?.closest?.('.x6-cell')?.getAttribute('data-cell-id')
      const connectable = portEl && group === 'in' && nodeId &&
        nodeId !== this.connectingSource && !this.wouldCreateCycle(this.connectingSource, nodeId)
      if (this.hoveredPortEl && this.hoveredPortEl !== portEl) {
        this.hoveredPortEl.classList.remove('is-target')
      }
      this.hoveredPortEl = connectable ? portEl : null
      if (connectable) {
        portEl.classList.add('is-target')
      }
      this.connectionTargetId = connectable ? nodeId : ''
    },
    clearHoveredPort () {
      if (this.hoveredPortEl) {
        this.hoveredPortEl.classList.remove('is-target')
        this.hoveredPortEl = null
      }
      this.connectionTargetId = ''
    },
    finishClickConnection (target) {
      const sourceId = this.connectingSource
      const sourcePort = this.connectingPortId
      const targetPort = target.getPortsByGroup('in')?.[0]?.id
      if (!sourceId || !targetPort) {
        this.cancelConnection()
        return
      }
      if (sourceId === target.id || this.wouldCreateCycle(sourceId, target.id)) {
        this.$message.warning(this.$t('modules.workflow.connectionCycle'))
        this.cancelConnection()
        return
      }
      const exists = (this.graph.getEdges() || []).some(edge =>
        edge.getSourceCellId() === sourceId && edge.getTargetCellId() === target.id
      )
      if (!exists) {
        this.graph.addEdge({
          source: { cell: sourceId, port: sourcePort },
          target: { cell: target.id, port: targetPort },
          attrs: { line: edgeLineAttrs() }
        })
        this.$message.success(this.$t('modules.workflow.connectionCreated'))
      }
      this.cancelConnection()
      this.syncGraphStats()
    },
    cancelConnection () {
      this.clearHoveredPort()
      if (this.previewEdgeId && this.graph) {
        const edge = this.graph.getCellById(this.previewEdgeId)
        if (edge) {
          this.graph.removeEdge(edge)
        }
      }
      this.previewEdgeId = ''
      this.connectingSource = ''
      this.connectingSourceLabel = ''
      this.connectingPortId = ''
      this.connectionTargetId = ''
      if (this.graph && !this.currentNodeId) {
        this.clearNodeSelection()
      }
    },
    topologicalOrderNodes () {
      const nodes = this.graph?.getNodes?.() || []
      const degree = new Map(nodes.map(node => [node.id, (this.graph.getIncomingEdges(node.id) || []).length]))
      const queue = nodes.filter(node => degree.get(node.id) === 0)
      const result = []
      while (queue.length) {
        const node = queue.shift()
        result.push(node)
        for (const edge of this.graph.getOutgoingEdges(node.id) || []) {
          const targetId = edge.getTargetCellId()
          degree.set(targetId, degree.get(targetId) - 1)
          if (degree.get(targetId) === 0) {
            const target = this.graph.getCellById(targetId)
            if (target) {
              queue.push(target)
            }
          }
        }
      }
      nodes.forEach(node => {
        if (!result.includes(node)) {
          result.push(node)
        }
      })
      return result
    },
    /** 基准布局：拓扑序每列两张卡，列宽 264+76、上下间距 48。 */
    layoutWorkflowNodes () {
      const order = this.topologicalOrderNodes()
      if (!order.length) {
        return
      }
      const info = new Map(order.map(node => [node.id, this.nodeGeometryFor(node)]))
      const width = info.get(order[0].id).width
      order.forEach((node, index) => {
        const column = Math.floor(index / 2)
        const x = 60 + column * (width + 76)
        const y = index % 2
          ? 60 + info.get(order[index - 1].id).height + 48
          : 60
        node.position(x, y)
      })
      this.portSideCache = {}
      this.syncAllNodeGeometry()
    },
    arrangeWorkflow () {
      if (!this.graph?.getNodes?.().length) {
        return
      }
      this.toolsOpen = false
      this.layoutWorkflowNodes()
      this.$nextTick(() => this.zoom('fit'))
    },
    resetZoom () {
      if (!this.graph) {
        return
      }
      this.graph.zoomTo(1)
      this.scheduleEdgeDecorations()
    },
    showDrawerError (message) {
      this.$refs.drawerFrameRef?.showError?.(message)
    },
    registerCustomNode (shape, vueNode) {
      register({
        shape,
        component: {
          render: () => {
            return h(vueNode, {
              // 点击卡片右上角删除按钮 删除该节点
              onDeleteCardHandle: id => this.deleteNode(id),
              // 点击卡片右上角设置按钮 弹出设置抽屉
              onEditCardHandle: nodeInfo => this.editCardHandle(nodeInfo),
              onInitCardHandle: nodeInfo => this.initCardHandle(nodeInfo),
              // 点击卡片上的删除按钮
              onInputDeleteHandle: (inputVariable, id) => this.inputDeleteHandle(inputVariable, id)
            })
          }
        }
      })
    },
    /**
     * @description: 批量注册画布内需要使用到的自定义Vue节点
     * 内置了customNodes变量 该变量为一个对象 包含的是所有自定义Vue节点的集合
     */
    registerCustomNodeBundle () {
      const customNodes = {
        QUERY,
        RESPONSE,
        PRE_RETRIEVER,
        RETRIEVER,
        POST_RETRIEVER,
        RESPONSE_SYNTHESIZER
      }
      Object.keys(customNodes).forEach(node => {
        this.registerCustomNode(node, customNodes[node])
      })
    },
    // 切换到另一个工作流时重建画布。必须先清空旧节点再取数：切到「还没有草稿」的
    // 新工作流时后端返回空配置、走 initDefaultNode()，而它只在画布为空时才补默认节点，
    // 不清空的话画布上会继续留着上一个工作流的节点
    reloadAdvancedFlow () {
      // 清空之后这张图不再属于任何工作流，把归属一并清掉 —— 在新数据落地前点保存，
      // 会被 exportGraph 的 graphAppId 守卫拦下，不会把这张空图存进新工作流
      this.cancelConnection()
      this.selectedEdge = null
      this.clearNodeSelection()
      this.portSideCache = {}
      this.graph?.clearCells()
      this.graphAppId = ''
      // 路由参数变化时标题/版本也要跟着清空：请求失败（如 ID 不存在）时若保留旧值，
      // 页面会显示「上一个工作流的名称 + URL 里的新 ID」，与实际内容不一致。
      this.workflowName = ''
      this.workflowId = ''
      this.version = 1
      this.workflowPublishType = 0
      this.queryEngineType = ''
      this.nodeLoaded = false
      this.getAdvancedFlowConfig()
    },
    // 获取当前高级编排配置
    // shouldArrange：加载完成后是否检查/整理布局（始终 100%，不缩放）。
    // 保存后重新拉取时传 false，保持用户当前的视图与节点位置。
    getAdvancedFlowConfig (shouldArrange = true) {
      // 记下本次请求对应的 appId：连续切换工作流时先发出的请求可能后返回，
      // 拿旧返回渲染会把上一个工作流的图盖回新画布，所以只认当前 URL 对应的返回
      const requestAppId = this.$route.params.id
      // 404 由本页提示并回列表，跳过拦截器的通用 toast，避免一次失败弹两条；
      // 用 skipErrorMessage 而不是 skipErrorHandler，保留 401 的会话处理。
      getFlowConfig(requestAppId, { skipErrorMessage: true }).then(res => {
        if (requestAppId !== this.$route.params.id) {
          return
        }
        if (res.nodeConfigDTOList?.length) {
          this.version = res.version || 1
          this.workflowName = res.name || ''
          this.workflowId = res.appId || ''
          this.workflowPublishType = Number(res.publishType || 0)
          // this.currentAppVersion = res.currentAppVersion
          let nodeDTO = JSON.parse(JSON.stringify(res.nodeConfigDTOList))
          nodeDTO.forEach(item => {
            item.id = item.nodeId
            item.shape = item.componentType
            item.position = {
              x: item.xPosition,
              y: item.yPosition
            }
          })
          this.jsonDTO = nodeDTO
          this.importGraph(shouldArrange)
          this.graphAppId = requestAppId

          let queryengineObj = res.otherNodeConfigList.find(item => item.componentType === 'QUERY_ENGINE')
          this.queryEngineType = queryengineObj.variables.queryengine.operator
          this.$store.state.ragWorkflowType = this.queryEngineType
          // 是否实际使用结构化知识库（SQL检索算子）：不能仅凭工作流类型判断，
          // 顺序工作流同样可能绑定文档知识库
          this.$store.state.ragWorkflowIsStructKnowledge = this.checkIsStructKnowledgeFlow(res.nodeConfigDTOList)
        } else {
          // 新工作流还没有草稿时走这里。若只 initDefaultNode()，
          // queryEngineType 会保持 data() 里的 ''，exportGraph() 会写出
          // `variables.queryengine = queryengineMap[''] = undefined` —— 保存下来的画布
          // **没有编排引擎**，后端 preCheck 会直接拒（"画布缺少编排引擎"），等于新建的流存不下来。
          // 引擎只能由工作流模板推出来（节点里看不出来），所以后端 GET /flow 返回了 template。
          this.workflowName = res.name || ''
          this.workflowId = res.appId || ''
          this.version = res.version || 1
          this.workflowPublishType = Number(res.publishType || 0)
          this.queryEngineType = this.engineOfTemplate(res.template)
          this.$store.state.ragWorkflowType = this.queryEngineType
          this.nodeLoaded = false
          this.initDefaultNode()
          this.graphAppId = requestAppId
        }
      })
        .catch(error => {
          // 同上：路由已切走（或有更新的请求接管）时，不要再往画布上补默认节点
          if (requestAppId !== this.$route.params.id) {
            return
          }
          // 401 由会话层统一提示并跳登录；这里不要再补一条“加载失败”并初始化空画布。
          if (error?.status === 401) {
            return
          }
          // 不存在的 ID 不再渲染一个「看起来可编辑」的空画布：明确提示并回列表，
          // 否则用户会以为这是新建流程，保存时才收到 404。
          if (error?.status === 404) {
            this.$message.error(this.$t('modules.workflow.flowNotFound'))
            this.$router.replace({ name: 'flow' })
            return
          }
          this.$message.error(this.$t('modules.workflow.loadFailed'))
          this.nodeLoaded = false
          this.initDefaultNode()
          this.graphAppId = requestAppId
        })
        .finally(() => {
          this.loading = false;
        })
    },
    /**
     * @description: 工作流模板 → 编排引擎。
     * 模板取自后端 GET /flow 的返回（对应建流时选的 Sequential/Blended/Conditional），
     * 缺省与无法识别的一律按顺序引擎处理，与画布默认模板 Blended 不同 ——
     * 后者只是建流弹窗的默认选项，引擎必须显式定下来，否则会存出没有引擎的画布。
     */
    engineOfTemplate (template) {
      const mapper = {
        Sequential: 'SequentialQueryEngine',
        Blended: 'BlendedQueryEngine',
        Conditional: 'ConditionalQueryEngine'
      }
      return mapper[template] || 'SequentialQueryEngine'
    },
    /**
     * @description: 判断节点变量中是否包含 SQL 检索算子（结构化知识库特征）
     */
    isSqlOperatorVariables (variables) {
      const sqlOperatorNames = ['SqlRetriever', 'SqlExecutor', 'SqlRetrieverOperator', 'SqlExecutorOperator']
      return Object.values(variables || {}).some(ops => {
        return Array.isArray(ops) && ops.some(op => sqlOperatorNames.includes(op?.operator))
      })
    },
    /**
     * @description: 判断工作流是否实际使用结构化知识库（SQL检索算子）
     * 顺序工作流(SequentialQueryEngine)既可能绑定结构化知识库，也可能绑定文档知识库，
     * 因此不能仅凭工作流类型判断，需扫描各节点变量中是否存在 SQL 检索算子
     */
    checkIsStructKnowledgeFlow (nodeList) {
      return (nodeList || []).some(node => this.isSqlOperatorVariables(node.variables))
    },
    /**
     * @description: 从当前 graph 节点数据刷新结构化知识库标志，
     * 以覆盖会话中途修改检索器算子（SQL/向量）的场景
     */
    refreshStructKnowledgeFlag () {
      const nodes = this.graph?.getNodes?.() || []
      const isStruct = nodes.some(node => {
        const variables = node.store?.data?.data?.variables || node.store?.data?.variables
        return this.isSqlOperatorVariables(variables)
      })
      this.$store.state.ragWorkflowIsStructKnowledge = isStruct
    },
    initDefaultNode () {
      const result = this.graph.toJSON()
      if (!result.cells.length) {
        this.graph.addNode(queryNodeConfig())
        this.graph.addNode(responseNodeConfig())
        this.$nextTick(() => {
          this.syncAllNodeGeometry()
          this.layoutWorkflowNodes()
          this.zoom('fit')
          this.syncGraphStats()
        })
      }
    },
    /**
     * 新节点直接接在「结束」前面：
     * 结束节点原来的上游改接新节点，新节点再连到结束；这样添加后卡片立刻有输入。
     */
    insertNodeBeforeEnd (node) {
      const end = this.graph.getNodes().find(item => item.shape === 'RESPONSE')
      if (!end) {
        return
      }
      const targetPort = end.getPortsByGroup('in')?.[0]?.id
      const inputPort = node.getPortsByGroup('in')?.[0]?.id
      const outputPort = node.getPortsByGroup('out')?.[0]?.id
      if (!targetPort || !inputPort || !outputPort) {
        return
      }
      const incoming = this.graph.getIncomingEdges(end.id) || []
      incoming.forEach(edge => {
        const sourceId = edge.getSourceCellId()
        const sourcePort = edge.getSourcePortId()
        this.graph.removeEdge(edge.id)
        this.graph.addEdge({
          source: { cell: sourceId, port: sourcePort },
          target: { cell: node.id, port: inputPort },
          attrs: { line: edgeLineAttrs() }
        })
      })
      this.graph.addEdge({
        source: { cell: node.id, port: outputPort },
        target: { cell: end.id, port: targetPort },
        attrs: { line: edgeLineAttrs() }
      })
    },
    /** 按模块类型创建画布节点（沿用模板里的默认算子配置）。 */
    createLibraryNode (shape) {
      const templates = {
        preretriever: [PreRetrieverNodeConfig, 'PRE_RETRIEVER', 'PRE-'],
        retriever: [RetrieverNodeConfig, 'RETRIEVER', 'RE-'],
        postretriever: [PostRetrieverNodeConfig, 'POST_RETRIEVER', 'POST-'],
        responsesynthesizer: [ResponseSynthesizerNodeConfig, 'RESPONSE_SYNTHESIZER', 'SYN-']
      }
      const [template, componentType, prefix] = templates[shape] || templates.preretriever
      const config = JSON.parse(JSON.stringify(withGraphColors(template)))
      config.label = `${prefix}${this.generateRandomUUID()}`
      const node = this.graph.createNode(config)
      const variables = createDefaultVariables(componentType)
      const moduleKey = moduleKeyOf(componentType)
      if (variables && moduleKey) {
        variables[moduleKey].forEach((operator, index) => {
          operator.id = `${node.id}_${index + 1}`
        })
        node.setProp('variables', variables)
        node.setData({ variables })
      }
      return node
    },
    /**
     * @description: 从左侧「添加节点」抽屉里点选模块，放到当前视口中心。
     *
     * 添加节点是点击添加而不是拖动添加；位置取当前缩放/平移后的可视中心，并在
     * 与已有节点重叠时向下错开，避免新节点完全盖住旧节点。
     */
    addLibraryNode (shape) {
      const nodeCount = this.graph?.getNodes?.().length || 0
      if (nodeCount >= 60) {
        this.$message({
          message: this.$t('public.nodeLimit'),
          type: 'warning'
        })
        return
      }
      const node = this.createLibraryNode(shape)
      const container = this.graph.container
      const rect = container.getBoundingClientRect()
      const center = this.graph.clientToLocal(rect.left + rect.width / 2, rect.top + rect.height / 2)
      let x = Math.round(center.x - DEFAULT_CUSTOM_NODE_WIDTH / 2)
      let y = Math.round(center.y - 80)
      while (this.graph.getNodes().some(existing => {
        const position = existing.getPosition()
        return Math.abs(position.x - x) < 40 && Math.abs(position.y - y) < 40
      })) {
        y += 60
      }
      node.position(x, y)
      this.graph.addNode(node)
      this.insertNodeBeforeEnd(node)
      this.libraryVisible = false
      this.scheduleGeometrySync()
      this.syncGraphStats()
      const nodeId = node.id
      this.$nextTick(() => {
        const added = this.graph.getCellById(nodeId)
        if (!added) {
          return
        }
        this.editCardHandle({
          id: nodeId,
          componentType: added.shape,
          label: added.store?.data?.label,
          variables: added.store?.data?.variables
        }, nodeId)
      })
    },
    /**
     * @description: 新建节点到画布中
     *
     * @param {Object} nodeConfig 节点配置
     */
    addNode (nodeConfig) {
      this.graph.addNode(nodeConfig)
    },
    editCardHandle (nodeInfo, nodeId) {
      // 打开编辑抽屉前刷新结构化知识库标志，确保读取到检索器最新的算子配置
      this.toolsOpen = false
      this.refreshStructKnowledgeFlag()
      const id = nodeId || nodeInfo?.id || ''
      const node = this.graph?.getCellById?.(id)
      if (!node) {
        return
      }
      this.cancelConnection()
      this.selectedEdge = null
      this.currentNodeId = id
      this.currentNodeData = {
        id,
        componentType: node.shape,
        label: node.store?.data?.label || '',
        variables: this.nodeVariables(node) || null
      }
      const shape = node.shape
      this.drawerFixed = isFixedShape(shape)
      this.drawerTitle = this.moduleTitleOf(shape)
      this.drawerTone = this.moduleToneOf(shape)
      this.drawerOperatorCount = getNodeOperators({
        shape,
        variables: this.currentNodeData.variables
      }).length
      this.drawerFixedDirection = shape === 'QUERY'
        ? this.$t('modules.workflow.output')
        : this.$t('modules.workflow.inputs')
      this.drawerFixedField = shape === 'RESPONSE' ? 'Answer' : 'Question'
      const incoming = this.graph.getIncomingEdges(id) || []
      this.drawerBasics = {
        label: this.currentNodeData.label,
        upstreams: incoming.map(edge => edge.getSourceCellId())
      }
      this.drawerUpstreamOptions = this.graph.getNodes()
        .filter(candidate => candidate.id !== id && candidate.shape !== 'RESPONSE')
        .map(candidate => ({
          id: candidate.id,
          label: `${candidate.shape === 'QUERY'
            ? this.$t('modules.workflow.question')
            : this.moduleTitleOf(candidate.shape)} · ${candidate.store?.data?.label || candidate.id}`
        }))
      this.selectNodeView(id)
      this.isComponentLoaded = false
      this.dynamicComponent = null
      if (!this.drawerFixed) {
        const directory = this.shapeAndPortIdMap[shape]
        this.dynamicComponent = require(`../../features/workflow/modules/${directory}/Drawer`).default
        this.$nextTick(() => {
          this.isComponentLoaded = true
        })
      }
      this.$refs.drawerFrameRef?.openDrawer(shape)
    },
    /** 节点 / 连线 / 算子删除统一确认。 */
    async confirmNodeDeletion (id) {
      const node = this.graph?.getCellById?.(id)
      if (!node || node.shape === 'QUERY' || node.shape === 'RESPONSE') {
        return false
      }
      const operators = getNodeOperators({
        shape: node.shape,
        variables: this.nodeVariables(node)
      })
      return await requestDeletion({
        resourceType: this.$t('modules.workflow.resourceNode'),
        title: this.$t('modules.workflow.deleteNode'),
        warning: this.$t('modules.workflow.deleteNodeWarning'),
        description: this.$t('modules.workflow.deleteNodeDescription'),
        items: [{
          id,
          name: this.nodeDisplayName(id),
          meta: `${id} · ${this.$t('modules.workflow.operatorCountBadge', { count: operators.length })}`
        }],
        verification: false,
        hint: this.$t('modules.workflow.deleteNodeHint'),
        confirmText: this.$t('modules.workflow.deleteNodeConfirm')
      })
    },
    /** 删除节点后用「上游→下游」桥接连线，避免整条链路断掉。 */
    removeNodeWithBridge (id) {
      const incoming = this.graph.getIncomingEdges(id) || []
      const outgoing = this.graph.getOutgoingEdges(id) || []
      const bridges = []
      incoming.forEach(sourceEdge => {
        outgoing.forEach(targetEdge => {
          const sourceId = sourceEdge.getSourceCellId()
          const targetId = targetEdge.getTargetCellId()
          if (!sourceId || !targetId || sourceId === targetId) {
            return
          }
          const targetPort = this.graph.getCellById(targetId)?.getPortsByGroup('in')?.[0]?.id
          if (!targetPort) {
            return
          }
          const exists = this.graph.getEdges().some(edge =>
            edge.getSourceCellId() === sourceId && edge.getTargetCellId() === targetId
          )
          if (!exists) {
            bridges.push({
              source: { cell: sourceId, port: sourceEdge.getSourcePortId() },
              target: { cell: targetId, port: targetPort },
              attrs: { line: edgeLineAttrs() }
            })
          }
        })
      })
      this.graph.removeNode(id)
      bridges.forEach(edge => this.graph.addEdge(edge))
      this.scheduleGeometrySync()
      this.syncGraphStats()
    },
    async deleteCurrentNode () {
      const id = this.currentNodeId
      if (!id || !await this.confirmNodeDeletion(id)) {
        return
      }
      this.$refs.drawerFrameRef?.closeDrawer()
      this.clearNodeSelection()
      this.removeNodeWithBridge(id)
      this.currentNodeId = ''
    },
    /** 抽屉里的「输入连接」：从图中的入边实时取，删除即断开连线。 */
    refreshDrawerInputs () {
      if (!this.graph || !this.currentNodeId) {
        this.drawerInputs = [];
        return;
      }
      const edges = this.graph.getIncomingEdges(this.currentNodeId) || [];
      this.drawerInputs = edges.map(edge => {
        const sourceId = edge.getSourceCellId();
        const source = sourceId ? this.graph.getCellById(sourceId) : null;
        return {
          edgeId: edge.id,
          label: source?.store?.data?.label || sourceId || '--',
          port: edge.getSourcePortId() || ''
        };
      });
    },
    removeDrawerInput (edgeId) {
      this.graph.removeEdge(edgeId);
      this.$nextTick(() => this.refreshDrawerInputs());
    },
    async deleteNode (id) {
      if (!await this.confirmNodeDeletion(id)) {
        return
      }
      this.removeNodeWithBridge(id)
    },
    inputDeleteHandle (inputVariable, id) {
      const incomingE = this.graph.getIncomingEdges(id)
      incomingE && incomingE.forEach(item => {
        const sourcePortId = item.getSourcePortId()
        const sourceCell = item.getSourceCell()
        if (sourcePortId === inputVariable.key && sourceCell.id === inputVariable.sourceNode) {
          this.graph.removeEdge(item.id)
        }
      })
    },
    initCardHandle (nodeInfo) {
      const prop = nodeInfo.variables[this.shapeAndPortIdMap[nodeInfo.componentType]]
      if (prop) {
        for (let i = 0; i < prop.length; i++) {
          prop[i].id = `${nodeInfo.id}_${i + 1}`
        }
      }
      const target = this.graph.getCellById(nodeInfo.id)
      target.setProp('variables', nodeInfo.variables)
      target.setData({
        type: 'saveData',
        variables: nodeInfo.variables
      })
      this.scheduleGeometrySync()
      this.syncGraphStats()
    },
    saveConfigHandler () {
      this.toolsOpen = false
      // 保存是一条异步多步链（防抖 → 从图上导出 → check → 可能二次确认 → save），中途用户
      // 可能切走画布甚至切到别的工作流。目标 appId 在点击这一刻定死、整条链都用它，不能每次
      // 调用时现读 $route.params.id —— 否则 check 用的是 A、save 时路由已切到 B，
      // 会把 A 的画布内容写进 B。
      this.saveAppId = this.$route.params.id
      this.loading = true;
      if (this.debouncedInput) {
        // 取消之前的防抖函数
        this.debouncedInput.cancel();
      }
      // 创建新的防抖函数
      this.debouncedInput = debounce(() => {
        this.exportGraph()
      }, DEBOUNCETIMELONG);
      // 调用防抖函数
      this.debouncedInput();
    },
    /**
     * 保存成功提示：已发布的工作流要额外说明「这次只改了草稿」。
     * 对话测试/编排层只读发布快照，不说清楚的话用户会以为保存即生效。
     */
    notifySaveSuccess () {
      if (Number(this.workflowPublishType) !== 0) {
        this.$message({
          type: 'success',
          message: this.$t('modules.workflow.saveDraftOnlySuccess')
        })
        // 线上仍是旧快照：本地发布态同步成「发布后修改」
        this.workflowPublishType = 2
        return
      }
      this.$message({
        type: 'success',
        message: this.$t('public.saveSuccess')
      })
    },
    exportGraph () {
      // 防抖到期时，图可能已经不属于 saveAppId 了（用户切走了，或切过去的新流还没加载完、
      // 图上还是空的）—— 这时候存下去就是把别的内容/空图写进库里，直接放弃这次保存。
      if (this.graphAppId !== this.saveAppId) {
        this.loading = false
        return
      }
      const result = this.graph.toJSON()
      const cells = result.cells || []
      const nodes = cells.filter(item => item.shape !== 'edge')
      const edges = cells.filter(item => item.shape === 'edge' && !item.data?.preview)
      nodes.map(item => {
        item.nodeId = item.id || '';
        item.componentType = item.shape;
        item.xPosition = item.position.x;
        item.yPosition = item.position.y;
        item.outputVariables = [];
        item.inputVariables = [];
        const targetItem = this.graph.getCellById(item.id)
        // 该段是必要的，将当前的最新值赋到json体中
        item.variables = targetItem.store.data?.data?.variables;
      })
      edges.forEach(item => {
        let source = item.source.cell;
        let sourceKey = item.source.port;
        let target = item.target.cell;
        const input = nodes.find(item => item.id === source)

        input.outputVariables.push({
          key: sourceKey,
          targetNode: target
        })

        const output = nodes.find(item => item.id === target)

        output.inputVariables.push({
          key: sourceKey,
          sourceNode: source,
          label: this.graph.getCellById(source).store.data.label
        })
      })
      this.jsonDTO = nodes

      const edgesDTO = []
      edges.forEach(item => {
        edgesDTO.push({
          source: item.source.cell,
          target: item.target.cell
        })
      })

      const otherNodeConfigList = [
        {
          componentType: 'QUERY_ENGINE',
          inputVariables: [],
          variables: {
            queryengine: this.queryengineMap[this.queryEngineType]
          }
        }
      ]
      otherNodeConfigList.push(
        {
          componentType: 'EDGES',
          inputVariables: [],
          variables: {
            edges: edgesDTO
          }
        }
      )

      const params = {
        flowType: 'workflow',
        version: this.version,
        nodeConfigDTOList: this.jsonDTO,
        otherNodeConfigList
      }
      // 调用 check 接口
      checkSaveFlowConfig(this.saveAppId, params).then(res => {
        if (!res.success) {
          // 如果 check 接口返回 true，弹出二次确认弹框

          // 优先显示后端 preCheck 给出的原因（res.message，例如「编排引擎
          // BlendedQueryEngine 在当前版本不可执行」），否则警告内容与真实原因对不上，
          // 用户只能靠猜。后端没给原因时才回落到原文案。
          this.$confirm(res.message || this.$t('ragFlow.inferenceModelCheck', {
            name: this.workflowName || this.$route.params.id
          }), this.$t('public.save'), {
            confirmButtonText: this.$t('advancedFlow.yes'),
            cancelButtonText: this.$t('ragFlow.backEdit'),
            type: 'warning',
            describe: this.$t('ragFlow.inferenceModelCheck1')
          })
            .then(() => {
              // 点击二次确认弹框的确定按钮，调用 saveFlowConfig 接口
              saveFlowConfig(this.saveAppId, params)
                .then(() => {
                  this.notifySaveSuccess();
                  this.getAdvancedFlowConfig(false);
                })
                .catch(() => {
                  // to-do 保存接口如果失败 前端增加处理
                  this.loading = false;
                });
            })
            .catch(() => {
              // 点击二次确认弹框的取消按钮，关闭弹框，留在页面
              this.loading = false;
            });
        } else {
        // 如果 check 接口返回 false，直接调用 saveFlowConfig 接口
          saveFlowConfig(this.saveAppId, params)
            .then(() => {
              this.notifySaveSuccess();
              this.getAdvancedFlowConfig();
            })
            .catch(error => {
              // 失败提示由接口拦截器统一弹出，这里只记录并恢复按钮状态
              console.error('保存工作流配置失败:', error);
              this.loading = false;
            });
        }
      })
      // ⚠️ 这里必须留一个 catch，**不能**改成 finally：
      //   `checkSaveFlowConfig` 被 reject 时（网络/网关错，或业务前置校验失败），
      //   上面那段 then 整段都不执行，而唯一的 `loading = false` 都在**内层**
      //   saveFlowConfig 的 catch 里 → 保存按钮**永久转圈**。
      //   用 finally 也不行：内层「二次确认弹窗」是**没有被 return** 的游离链，
      //   外层在这里就已经 settle 了，finally 会在弹窗还开着时提前把按钮解冻。
        .catch(() => {
        // 错误提示由 api/base.js 的响应拦截器统一弹（业务码/HTTP 码各一条），此处只负责复位。
          this.loading = false;
        });
    },
    exportWorkflow () {
      exportWorkFlow(this.$route.params.id).then(res => {
        download(res, '', '')
      })
    },
    /** 把已加载节点的端口重置为新卡片几何（端口 id 不变，连线自动改挂）。 */
    normalizeNodePorts () {
      const templates = {
        PRE_RETRIEVER: PreRetrieverNodeConfig.ports,
        RETRIEVER: RetrieverNodeConfig.ports,
        POST_RETRIEVER: PostRetrieverNodeConfig.ports,
        RESPONSE_SYNTHESIZER: ResponseSynthesizerNodeConfig.ports,
        QUERY: queryNodeConfig().ports,
        RESPONSE: responseNodeConfig().ports
      }
      this.graph.getNodes().forEach(node => {
        const template = templates[node.shape]
        if (template) {
          node.setProp('ports', JSON.parse(JSON.stringify(template)))
        }
      })
    },
    importGraph (shouldArrange = true) {
      this.nodeLoaded = true
      if (this.jsonDTO) {
        //  fromJSON方法会把json的值全部塞进store.data,因此data.variable永远是有值的
        this.graph.fromJSON(this.jsonDTO)
        // 已加载画布可能带旧端口坐标；卡片几何变化后，必须把节点的 ports 重新
        // 钉到当前模板，否则连线会挂到卡片外
        this.normalizeNodePorts()

        Array.isArray(this.jsonDTO) && this.jsonDTO.forEach(item => {
          if (item.outputVariables) {
            item.outputVariables.forEach(element => {
              const targetNodeInfo = this.graph.getCellById(element.targetNode)
              this.graph.addEdge({
                source: {
                  cell: item.nodeId,
                  port: element.key
                },
                target: {
                  cell: element.targetNode,
                  port: targetNodeInfo.getPortsByGroup('in')[0].id
                },
                attrs: {
                  line: edgeLineAttrs()
                }
              })
            })
          }

          // 下列代码用于点击编辑 什么都没有动 直接保存 赋值variable
          const target = this.graph.getCellById(item.id)
          // 重新加载节点时，将后端返回的值赋给节点
          target.setData({
            type: 'displayData',
            variables: item.variables
          },
          {
            overwrite: true
          })
        })
      }
      // 尺寸/端口是数据层几何（不依赖卡片 DOM）：fromJSON 后立刻同步，
      // 否则 1×1 的节点会在 render:done 之前把端口/连线全摆在节点左上角。
      this.portSideCache = {}
      this.syncAllNodeGeometry()
      // 排版必须等 X6 把 Vue 卡片视图真正挂到 DOM 上（render:done）：
      // 在 nextTick/rAF 里量，foreignObject 还是 1×1、卡片 DOM 尚未挂载，
      // 只能退回默认尺寸，节点会叠在一起。这里只打标记，由 render:done 触发。
      if (shouldArrange) {
        this.pendingArrange = true
        if (this.arrangeFallbackTimer) {
          clearTimeout(this.arrangeFallbackTimer)
        }
        // 兜底：极端情况下 render:done 不触发（例如空图），别让排版一直悬着
        this.arrangeFallbackTimer = setTimeout(() => {
          this.arrangeFallbackTimer = null
          this.runPendingArrange()
        }, 500)
      }
    },
    /**
     * 抽屉里的「输入 · 上游节点」多选：只保留选中的入边，缺的补上。
     * 先按「删掉当前节点全部入边」的边集做环检测，避免删完一半才发现成环。
     */
    applyDrawerUpstreams (target, upstreams) {
      const targetPortId = target.getPortsByGroup('in')?.[0]?.id
      if (!targetPortId) {
        return this.$t('modules.workflow.noInputPort')
      }
      const desired = [...new Set((upstreams || []).filter(Boolean))]
      if (!desired.length) {
        return this.$t('modules.workflow.needUpstream')
      }
      const incoming = this.graph.getIncomingEdges(target.id) || []
      const keptEdges = (this.graph.getEdges() || []).filter(edge => edge.getTargetCellId() !== target.id)
      const edgeList = keptEdges.map(edge => ({
        source: edge.getSourceCellId(),
        target: edge.getTargetCellId()
      }))
      for (const sourceId of desired) {
        if (!this.graph.getCellById(sourceId)) {
          return this.$t('modules.workflow.upstreamMissing')
        }
        if (edgeList.some(edge => edge.source === sourceId && edge.target === target.id)) {
          continue
        }
        if (this.wouldCreateCycleInEdges(edgeList, sourceId, target.id)) {
          return this.$t('modules.workflow.connectionCycle')
        }
        edgeList.push({ source: sourceId, target: target.id })
      }
      incoming.forEach(edge => {
        if (!desired.includes(edge.getSourceCellId())) {
          this.graph.removeEdge(edge.id)
        }
      })
      desired.forEach(sourceId => {
        const exists = (this.graph.getIncomingEdges(target.id) || [])
          .some(edge => edge.getSourceCellId() === sourceId)
        if (exists) {
          return
        }
        const source = this.graph.getCellById(sourceId)
        const sourcePortId = source?.getPortsByGroup('out')?.[0]?.id
        if (!sourcePortId) {
          return
        }
        this.graph.addEdge({
          source: { cell: sourceId, port: sourcePortId },
          target: { cell: target.id, port: targetPortId },
          attrs: { line: edgeLineAttrs() }
        })
      })
      return ''
    },
    drawerSubmitHandle () {
      const componentRef = this.$refs[`${this.currentNodeData.componentType}Ref`]
      if (!componentRef) {
        return
      }
      // ⚠️ `validate()` 是**工厂**（返回回调式校验器），但**调用本身有副作用**：
      // 它内部跑 `validateAndStoreKnowledgeBaseNames()`，失败时弹
      // 「…知识资产已删除，请更新配置！」。取一次、判一次、用一次
      // （保持 `componentRef.validate()` 的方法调用形式，别先解构成裸函数再调 —— 那样会丢 `this`）。
      const validate = componentRef.validate
      if (typeof validate !== 'function') {
        return
      }
      const validator = componentRef.validate()
      if (typeof validator !== 'function') {
        return
      }
      validator(valid => {
        if (!valid) {
          return
        }
        const target = this.graph.getCellById(this.currentNodeData.id)
        if (!target) {
          return
        }
        const label = (this.drawerBasics.label || '').trim()
        if (!label) {
          this.showDrawerError(this.$t('modules.workflow.nodeNameRequired'))
          return
        }
        const upstreamError = this.applyDrawerUpstreams(target, this.drawerBasics.upstreams)
        if (upstreamError) {
          this.showDrawerError(upstreamError)
          return
        }
        const data = componentRef.sendOperatorListData()
        const moduleKey = this.shapeAndPortIdMap[this.currentNodeData.componentType]
        ;(data?.[moduleKey] || []).forEach(item => Reflect.deleteProperty(item, 'showConfig'))
        target.setProp('label', label)
        // 两份 variables 整体替换（默认深合并会把删掉的库/算子留在数组尾巴里，
        // 见 lib/cellData.js 的注释）
        replaceNodeVariables(target, data)
        this.currentNodeData.label = label
        this.currentNodeData.variables = data
        this.$refs.drawerFrameRef?.closeDrawer()
        this.clearNodeSelection()
        this.currentNodeId = ''
        this.scheduleGeometrySync()
        this.syncGraphStats()
        this.refreshStructKnowledgeFlag()
        this.$message.success(this.$t('modules.workflow.nodeApplied'))
      })
    },
    drawerCancelHandle () {
      this.clearNodeSelection()
      this.currentNodeId = ''
    },
    zoom (type = 'in') {
      // 按 15% 比例缩放，范围 0.2–1.6，缩放到画布中心。
      if (type === 'in' || type === 'out') {
        const factor = type === 'in' ? 1.15 : 1 / 1.15
        const next = Math.min(1.6, Math.max(0.2, this.graph.zoom() * factor))
        this.graph.zoom(next, { absolute: true })
        return
      }
      // 底部「适应画布」：与 fit() 语义一致 —— 按实测卡片
      // 尺寸算出能放下整张图的缩放（0.2–1.6，最多 100%），再居中/左上对齐。
      const nodes = this.graph?.getNodes?.() || []
      if (!nodes.length) {
        return
      }
      const { width, height } = this.getCanvasSize()
      const boxes = nodes.map(node => {
        const position = node.getPosition()
        const size = this.getNodeDisplaySize(node)
        return {
          left: position.x,
          top: position.y,
          right: position.x + size.width,
          bottom: position.y + size.height
        }
      })
      const minX = Math.min(...boxes.map(box => box.left))
      const minY = Math.min(...boxes.map(box => box.top))
      const contentWidth = Math.max(...boxes.map(box => box.right)) - minX
      const contentHeight = Math.max(...boxes.map(box => box.bottom)) - minY
      const padding = 60
      const zoom = Math.min(1.6, Math.max(0.2, Math.min(
        (width - padding) / Math.max(1, contentWidth),
        (height - padding) / Math.max(1, contentHeight),
        1
      )))
      this.graph.zoomTo(zoom)
      const translateX = contentWidth * zoom <= width - padding
        ? (width - contentWidth * zoom) / 2 - minX * zoom
        : 24 - minX * zoom
      const translateY = contentHeight * zoom <= height - padding
        ? (height - contentHeight * zoom) / 2 - minY * zoom
        : 24 - minY * zoom
      this.graph.translate(translateX, translateY)
    },
    generateRandomUUID () {
      let uuid = uuidv4()
      uuid = uuid.replace(/-/g, '')
      uuid = uuid.substring(0, 3)
      return uuid
    },
    // 端口 y 不再按「算子条数 × 24」硬算，统一交给卡片几何。
    updateOuputPortForSingleOutput () {
      this.scheduleGeometrySync()
    },
    updatePortAfterChangingOperators () {
      this.scheduleGeometrySync()
    },
    syncGraphStats () {
      const nodes = this.graph?.getNodes?.() || []
      this.nodeCount = nodes.length
      this.edgeCount = (this.graph?.getEdges?.() || []).filter(edge => !edge.getData()?.preview).length
      const operators = nodes.flatMap(node => getNodeOperators({
        shape: node.shape,
        variables: this.nodeVariables(node)
      }))
      this.operatorCount = operators.length
      this.sourceKinds = sourceKindsFromOperators(operators)
    },
    /** 来源类型 meta + 图标（模板里按 kind 取）。 */
    sourceKindOf (kind) {
      const icons = { knowledge: Document, graph: Share, database: Coin }
      return { ...sourceKindMeta(kind), icon: icons[kind] || Document }
    },
    /** 只绑图谱库的工作流展示为「图谱检索」，其余仍按编排引擎显示模板名。 */
    workflowTypeLabel () {
      if (this.sourceKinds.length === 1 && this.sourceKinds[0] === 'graph') {
        return this.$t('modules.workflow.graphRetrieval')
      }
      return this.workflowTypeMap[this.queryEngineType] || ''
    },
    toggleFullscreen () {
      this.fullscreen = !this.fullscreen
      // 进出全屏都收起「编排与操作」浮层
      this.toolsOpen = false
      // 全屏切换会改变画布可用尺寸，等布局落定后再让 X6 重新量一次
      this.$nextTick(() => {
        this.setGraphSize && this.setGraphSize()
        this.$refs.fullscreenButton?.$el?.focus?.()
      })
    },
    toggleLibrary () {
      // 「添加节点」是左侧抽屉：覆盖在画布上，不改变画布尺寸
      this.toolsOpen = false
      this.libraryVisible = !this.libraryVisible
    },
    /** Esc：抽屉/弹窗/下拉先自己消费；再收「编排与操作」浮层；最后才退出全屏。 */
    handleFullscreenEsc (event) {
      if (event.key !== 'Escape' || !this.fullscreen || event.defaultPrevented) {
        return
      }
      const overlayOpen = [...document.querySelectorAll('.el-drawer,.el-dialog,.el-message-box,.el-select__popper')]
        .some(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
      if (overlayOpen) {
        return
      }
      if (this.toolsOpen) {
        this.toolsOpen = false
        this.$refs.toolsButton?.$el?.focus?.()
        return
      }
      this.fullscreen = false
      this.$nextTick(() => this.setGraphSize && this.setGraphSize())
    },
    /** 试运行按钮是禁用态，点击由外层 span 接住（见模板注释 ③） */
    showTrialRunHint () {
      this.$message.info(this.$t('modules.workflow.trialRunNotConnected'))
    },
    checkConfig () {
      this.$message.info(this.$t('modules.workflow.checkConfigHint', {
        nodes: this.nodeCount,
        edges: this.edgeCount
      }))
    },
    undoChanges () {
      // 从服务端重新载入当前工作流，丢弃画布上尚未保存的改动。
      this.toolsOpen = false
      this.cancelConnection()
      this.selectedEdge = null
      this.clearNodeSelection()
      this.getAdvancedFlowConfig(false)
    },
    goBack () {
      // 历史实现会在「生产构建且不在 iframe 中」时跳出站点、回到外部门户；这套
      // 前提在独立部署下不成立——站点本身就在根路径、生产构建、且不在 iframe 中，
      // 跳转目标却不存在。请求会落到一个不存在的路径，nginx 的
      // `try_files $uri $uri/ /index.html` 把它回退成 index.html，而 hash
      // 又匹配不到任何路由，router-view 渲染为空 → 白屏卡死。
      // 详情页通常是从知识检索列表点进来的，所以优先真回退：能保留列表的分页/筛选状态，
      // 也不会在历史里堆出「列表 → 详情 → 列表」——那样点完页内返回再按浏览器返回键
      // 又会弹回详情页。直接深链打开详情页时应用内没有可回退的历史，兜底 push 到列表。
      if (this.$router.options.history.state?.back) {
        this.$router.back();
      } else {
        this.$router.push('/flow');
      }
    }
  }
}
</script>
<style lang="less" scoped>
/* 画布外层只负责占满剩余高度；
   边框/圆点背景/内距全部由 `styles/workspaces.css` 的 .canvas-viewport 提供。 */
.flow-surface {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
}
/* 沉浸画布：整块画布铺满窗口，
   入口按钮浮在画布右上角，页头/工具条被盖住，Esc 退出。 */
.canvas-viewport.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 100;
  width: 100%;
  height: 100dvh;
  min-height: 0;
  border: 0;
  border-radius: 0;
}
/* 整理布局后布局从 y=60 起排，zoom('fit') 的居中/上对齐会把「开始」卡片
   顶边带到 ~32px，压到左上角提示行（16–41px）的最后 8–10px。提示行整体
   上移 12px（4px 起），保住 3px 间隙；全局 .canvas-hint 保持不动。 */
.flow-surface .canvas-hint {
  top: 4px;
}
.canvas-fullscreen-actions {
  position: absolute;
  z-index: 2;
  top: 16px;
  right: 18px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: calc(100% - 36px);
}
.canvas-fullscreen-actions .el-button {
  background: var(--rs-bg-card);
}
/* 画布右上角有按钮时，左下角提示文字让出宽度（同 .canvas-hint 规则）。 */
.canvas-viewport:has(.canvas-fullscreen-actions) .canvas-hint {
  max-width: calc(100% - 170px);
}
/* 全屏后页头整体隐藏，试运行/保存/工具条搬进「编排与操作」浮层 */
.advanced-flow.is-flow-fullscreen :deep(.workspace-header) {
  display: none;
}
/* 与左上提示行同理：全屏上下文（名称 + 统计）也上移 12px（22 → 10），
   否则 zoom('fit') 居中后「开始」卡片顶边（~32px）会压住文字（22–41px）。
   窄屏保持 56px（顶部按钮换行后另排）。 */
.canvas-fullscreen-context {
  position: absolute;
  top: 10px;
  left: 18px;
  max-width: calc(100% - 300px);
  color: var(--rs-text-3);
  pointer-events: none;
}
.flow-fullscreen-context {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.canvas-fullscreen-tools {
  position: absolute;
  z-index: 3;
  top: 56px;
  right: 18px;
  width: min(700px, calc(100% - 36px));
  max-height: calc(100dvh - 140px);
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--rs-border);
  border-radius: var(--rs-radius);
  background: var(--rs-bg-card);
  box-shadow: 0 8px 28px #10224918;
}
.flow-fullscreen-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.flow-fullscreen-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--rs-border-soft);
}
.flow-fullscreen-panel-header h2 {
  margin: 0;
  font-weight: 600;
  color: var(--rs-text);
}
.flow-primary-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.flow-primary-actions-target {
  display: flex;
  align-items: center;
}
.flow-fullscreen-panel .workspace-toolbar {
  gap: 12px;
}
.flow-fullscreen-panel .workspace-toolbar-group,
.flow-fullscreen-panel .flow-primary-actions {
  gap: 8px;
}
.flow-fullscreen-panel .workspace-toolbar-note {
  width: 100%;
}
/* 浮层与左下角缩放条同层时，缩放条不被面板压住 */
.canvas-controls {
  z-index: 2;
}
@media (max-width: 700px) {
  .canvas-fullscreen-actions {
    top: 10px;
    right: 10px;
  }
  .canvas-fullscreen-context {
    top: 56px;
    left: 12px;
    max-width: calc(100% - 24px);
  }
  .canvas-fullscreen-tools {
    top: 84px;
    right: 10px;
    width: calc(100% - 20px);
  }
  .flow-fullscreen-panel .workspace-toolbar-group {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
  .flow-fullscreen-panel-header {
    flex-wrap: wrap;
  }
  .flow-floating-bar {
    bottom: 72px;
    right: 12px;
    max-width: calc(100% - 24px);
  }
}
/* 「添加节点」抽屉（左滑 340px）与模块卡片 */
.module-option {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 16px;
  border: 1px solid var(--rs-border);
  background: var(--rs-bg-card);
  border-radius: 8px;
  margin-bottom: 12px;
  text-align: left;
  color: var(--rs-text);
  cursor: pointer;
}
.module-option:hover {
  border-color: var(--rs-primary-border);
  background: var(--rs-bg-hover);
}
.module-option > span:nth-child(2) {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.module-option > span:nth-child(2) > span {
  color: var(--rs-text-3);
}
.module-option > svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--rs-text-3);
}
.module-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex-shrink: 0;
  color: var(--tone);
  background: var(--tint);
}
.module-icon svg {
  width: 20px;
  height: 20px;
}
/* ── 画布：卡片选中、端口、连线与箭头 ─────────────────────────────── */

/* 选中节点：主色描边 + 2px 弱光环（.flow-node.selected） */
.flow-surface .canvas-viewport :deep(.x6-node.selected .ai-card-frame) {
  border-color: var(--rs-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--rs-primary) 12%, transparent);
}

/* 端口：第一层是透明命中圆（r=9），第二层视觉圆 9px，白底 1.5px 描边 */
.flow-surface .canvas-viewport :deep(.x6-port-body > circle:nth-child(1)) {
  fill: transparent;
  stroke: transparent;
  pointer-events: all;
}
.flow-surface .canvas-viewport :deep(.x6-port-body > circle:nth-child(2)) {
  fill: var(--rs-bg-card, #ffffff);
  stroke: var(--rs-edge, #8faedc);
  stroke-width: 1.5px;
  cursor: crosshair;
  transition: fill 0.15s, stroke 0.15s;
}
.flow-surface .canvas-viewport :deep(.x6-port-body:hover > circle:nth-child(2)),
.flow-surface .canvas-viewport :deep(.x6-port-body.is-target > circle:nth-child(2)) {
  fill: var(--rs-primary);
  stroke: var(--rs-primary);
}
.flow-surface .canvas-viewport :deep(.x6-port-body:hover > circle:nth-child(1)),
.flow-surface .canvas-viewport :deep(.x6-port-body:focus-visible > circle:nth-child(1)),
.flow-surface .canvas-viewport :deep(.x6-port-body.is-target > circle:nth-child(1)) {
  stroke: color-mix(in srgb, var(--rs-primary) 16%, transparent);
  stroke-width: 8px;
}
.flow-surface .canvas-viewport :deep(.x6-port-body:focus) {
  outline: none;
}
.flow-surface .canvas-viewport :deep(.x6-port-body:focus-visible > circle:nth-child(2)) {
  fill: var(--rs-primary);
  stroke: var(--rs-primary);
}
/* 点击输出端点后：所有输入端点高亮，提示可落点 */
.flow-surface.is-connecting .canvas-viewport :deep(.x6-port-body[port-group='in'] > circle:nth-child(2)) {
  fill: var(--rs-bg-selected);
  stroke: var(--rs-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--rs-primary) 12%, transparent);
}
.flow-surface.is-connecting .canvas-viewport :deep(.x6-port-body[port-group='in']) {
  cursor: crosshair;
}

/* 连线：1.6px 蓝灰细线；悬停/选中主色 2px */
.flow-surface .canvas-viewport :deep(.flow-connection > path:nth-child(2)) {
  stroke: color-mix(in srgb, var(--rs-edge) 78%, var(--rs-primary) 22%);
  stroke-width: 1.6px;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: stroke 0.15s, stroke-width 0.15s;
}
.flow-surface .canvas-viewport :deep(.flow-connection:hover > path:nth-child(2)),
.flow-surface .canvas-viewport :deep(.flow-connection.selected > path:nth-child(2)),
.flow-surface .canvas-viewport :deep(.flow-connection > path:nth-child(1):focus-visible + path) {
  stroke: var(--rs-primary);
  stroke-width: 2px;
}
/* 线中段箭头：画布底色描边，保证压在网格上也清晰 */
.flow-surface .canvas-viewport :deep(.flow-edge-direction) {
  fill: color-mix(in srgb, var(--rs-primary) 75%, var(--rs-edge) 25%);
  stroke: var(--rs-canvas-bg, #f8fafd);
  stroke-width: 2.5px;
  stroke-linejoin: round;
  paint-order: stroke fill;
  pointer-events: none;
}
.flow-surface .canvas-viewport :deep(.flow-connection:hover .flow-edge-direction),
.flow-surface .canvas-viewport :deep(.flow-connection.selected .flow-edge-direction) {
  fill: var(--rs-primary);
}
/* 点击连线模式的预览边 */
.flow-surface .canvas-viewport :deep(.flow-edge-preview > path:nth-child(2)) {
  stroke: var(--rs-primary);
  stroke-width: 2px;
  stroke-dasharray: 6 5;
  stroke-linecap: round;
}

/* 右上角连线状态条 */
.flow-floating-bar {
  position: absolute;
  bottom: 18px;
  right: 18px;
  max-width: calc(100% - 230px);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  background: var(--rs-bg-card);
  border: 1px solid var(--rs-border);
  padding: 10px 14px;
  border-radius: 8px;
  box-shadow: 0 4px 12px #19264c08;
  z-index: 5;
  cursor: default;
}
</style>

<style lang="less" scoped>
/* 试运行按钮：外观禁用、点击仍可触发外层的提示。
   el-button[disabled] 自身不派发 click，所以让它不接收指针事件，
   事件落到外层 span（span 有 @click），鼠标指针仍显示禁用箭头。 */
.trial-run-wrap { display: inline-flex; }
.trial-run-wrap .trial-run-btn { pointer-events: none; cursor: not-allowed; }
</style>
