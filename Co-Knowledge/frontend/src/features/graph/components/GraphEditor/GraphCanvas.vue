<template>
  <div class="graph-canvas">
    <div ref="containerRef" class="x6-container"></div>

    <!-- 右键菜单 -->
    <div v-if="contextMenuVisible"
         :style="contextMenuStyle"
         class="context-menu"
         @click.stop>
<!--      <div class="menu-header">-->
<!--        <span class="menu-title">{{ selectedContextNode?.getData()?.name || '节点操作' }}</span>-->
<!--      </div>-->

      <div class="menu-divider"></div>

      <div class="menu-item" @click="copyNode" :class="{ disabled: !hasSelectedNode }">
        <el-icon class="menu-icon"><CopyDocument /></el-icon>
        <span class="menu-text">{{ proxy.$t('public.copy') }}</span>
      </div>

      <div class="menu-item" @click="pasteNode" :class="{ disabled: !hasCopiedNode }">
        <el-icon class="menu-icon"><DocumentCopy /></el-icon>
        <span class="menu-text">{{ proxy.$t('public.paste') }}</span>
      </div>

      <!-- <div class="menu-divider"></div>

      <div class="menu-item danger" @click="deleteNode">
        <el-icon class="menu-icon"><Delete /></el-icon>
        <span class="menu-text">删除</span>
      </div> -->
    </div>

  </div>
</template>

<script setup lang="ts">
import {ref, onMounted, defineExpose, computed, nextTick, onUnmounted, getCurrentInstance} from 'vue'
import { Graph, Node, Edge, Shape} from '@antv/x6'
import { History } from '@antv/x6-plugin-history'
import { Selection } from '@antv/x6-plugin-selection'
import { Keyboard } from '@antv/x6-plugin-keyboard'
import { Clipboard } from '@antv/x6-plugin-clipboard'
import { Transform } from '@antv/x6-plugin-transform'
import {registerCustomNodes, getNodeDefaultProperties, getGraphPalette, applyNodeTheme} from '@/features/graph/lib/nodeFactory'
import { THEME_CHANGE_EVENT } from '@/shared/lib/theme'
import { CopyDocument, Delete, DocumentCopy } from '@/shared/lib/icons'
import { getFullCircleVertices } from './geometry'

const { proxy } = getCurrentInstance() as any

const containerRef = ref<HTMLElement>()
let graph: Graph | null = null

const emit = defineEmits(['node-select', 'edge-select', 'canvas-click', 'initialized'])

// 初始化状态
const isInitialized = ref(false)

// 连线模式状态（提前声明，供下方工具函数与 initGraph 使用）
const connectionMode = ref<'single' | 'double' | 'self' | null>('single')
const isConnectingEnabled = ref(true)

// 简化版本的连线模式控制
const setConnectionMode = (mode: 'single' | 'double' | 'self' | null) => {
  connectionMode.value = mode

  if (!graph) {
    console.warn('Graph对象不存在')
    return
  }

  // 简单的状态控制，实际连线在 createEdgeByMode 中处理
  isConnectingEnabled.value = mode !== null

}

// 选边样式：根据模式返回形状与颜色，降低 initGraph 复杂度
const getEdgeStyleByMode = (mode: 'single' | 'double' | 'self' | null) => {
  const { edgeStroke } = getGraphPalette()
  switch (mode) {
    case 'double':
      return { shape: 'double-arrow-edge', color: edgeStroke }
    case 'self':
      return { shape: 'self-loop-edge', color: edgeStroke }
    case 'single':
    default:
      return { shape: 'single-arrow-edge', color: edgeStroke }
  }
}

// 创建边：根据当前模式创建，抽离出 initGraph 的分支
// 关键：这个函数在拖拽连线时被调用，返回的Edge对象会作为预览线显示
const createEdgeByMode = () => {
  const { shape, color } = getEdgeStyleByMode(connectionMode.value)

  // 使用Shape.Edge而不是new Edge，确保预览线可见
  const edge = new Shape.Edge({
    shape,
    attrs: {
      line: {
        stroke: color,         // 连线颜色（当前主题）
        strokeWidth: 2,        // 连线宽度 2px
        targetMarker: {        // 添加箭头标记
          name: 'classic',
          size: 6,
          fill: color,
          stroke: color
        }
      }
    },
    data: {
      direction: connectionMode.value || 'single',
      color,
      lightStroke: '#1993FF',
      enabled: isConnectingEnabled.value
    }
  })

  return edge
}

// 校验边创建
const validateNewEdge = ({ edge }: { edge: any }) => {
  if (!isConnectingEnabled.value) {
    return false
  }
  const targetNode = edge.getTargetNode()
  if (!targetNode) {
    return false
  }
  // 允许所有连线模式（包括自环）
  return true
}

// 校验连接点
const validateConnectionPoints = ({ sourceMagnet, targetMagnet }: any) => {
  if (!isConnectingEnabled.value) {
    return false
  }
  if (!sourceMagnet || !targetMagnet) {
    return false
  }
  // 允许所有连线（包括自环）
  return true
}

onMounted(async() => {

  // 先注册自定义节点（只在第一次挂载时注册）
  registerCustomNodes()


  // 等待DOM完全渲染
  await nextTick()

  // 如果容器还是不存在，等待更多时间
  let retryCount = 0
  while (!containerRef.value && retryCount < 10) {
    await new Promise(resolve => setTimeout(resolve, 100))
    retryCount++
  }

  if (!containerRef.value) {
    console.error('容器引用仍然不存在，初始化失败，重试次数:', retryCount)
    return
  }

  try {
    // 然后初始化图形
    await initGraph()

    // 最后绑定事件
    bindEvents()

    // 监听窗口大小变化
    window.addEventListener('resize', handleResize)
    // 主题切换时原地重绘（vis-network/X6 的颜色在 options 里，CSS 覆盖不到）
    applyGraphTheme()
    window.addEventListener(THEME_CHANGE_EVENT, applyGraphTheme)

    isInitialized.value = true

    // 通知父组件初始化完成
    emit('initialized', true)

  } catch (error) {
    console.error('GraphCanvas 初始化失败:', error)
    console.error('错误堆栈:', error.stack)
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  window.removeEventListener(THEME_CHANGE_EVENT, applyGraphTheme)
  if (graph) {
    graph.dispose()
    graph = null
  }
})

const initGraph = async () => {

  if (!containerRef.value) {
    throw new Error('容器引用不存在')
  }

  // 等待容器完全渲染
  await nextTick()

  // 获取容器的实际尺寸
  const rect = containerRef.value.getBoundingClientRect()

  let width = rect.width || containerRef.value.clientWidth
  let height = rect.height || containerRef.value.clientHeight

  // 如果尺寸为0，使用默认值
  if (width === 0) {
    width = 800
    console.warn('容器宽度为0，使用默认值800')
  }
  if (height === 0) {
    height = 600
    console.warn('容器高度为0，使用默认值600')
  }


  const palette = getGraphPalette()

  try {
    graph = new Graph({
      container: containerRef.value,
      width: width,
      height: height,
      background: {
        color: palette.canvasBackground  // 主题取色
      },
      grid: {
        size: 25,      // 网格大小 25px
        visible: true, // 显示网格
        type: 'dot',   // 点状网格
        args: {
          color: palette.grid,  // 点的颜色（主题取色）
          thickness: 2          // 点的半径 2px
        }
      },
      mousewheel: {
        enabled: true,
        zoomAtMousePosition: true,
        modifiers: null,  // 移除修饰键限制,直接滚轮缩放
        minScale: 0.5,
        maxScale: 3
      },
      panning: true,  // 启用画布拖拽平移,与RAG工作流一致
      connecting: {
        router: 'normal',
        connector: {
          name: 'smooth'  // 使用平滑连接器,与RAG工作流一致
        },
        anchor: 'midSide',  // 改为midSide锚点,与RAG工作流一致
        connectionPoint: 'boundary',
        allowBlank: false,
        allowLoop: true,        // 允许自环
        allowNode: false,       // 不允许连接到节点本体
        allowEdge: false,       // 不允许连接到边
        allowPort: true,        // 允许连接到端口
        snap: {
          radius: 20
        },
        // 连接点校验（提取到独立函数）
        validateConnection: validateConnectionPoints,

        // 创建边（提取到独立函数）
        createEdge: createEdgeByMode,

        // 新增边校验（提取到独立函数）
        validateEdge: validateNewEdge,

        validateConnection({ sourceMagnet, targetMagnet }) {
          // 如果没有启用连线模式，不允许连接
          if (!isConnectingEnabled.value) {
            return false
          }

          // 验证连接点
          if (!sourceMagnet || !targetMagnet) {
            return false
          }

          // 允许所有连线（包括自环）
          return true
        }

      },

      highlighting: {
        magnetAdsorbed: {
          name: 'stroke',
          args: {
            attrs: {
              fill: palette.portStroke,  // 连接点高亮颜色（主题取色）
              stroke: palette.portStroke
            }
          }
        }
      },
      translating: {
        restrict: true
      },
      keyboard: true,
      clipboard: true
    })

    // 注册插件
    graph
      .use(new Selection({
        enabled: true,            // 启用选择插件
        multiple: true,           // 允许多选

        movable: true,            // 选中元素可移动
        showNodeSelectionBox: false,   // 禁用默认选择框，使用自定义样式
        showEdgeSelectionBox: true,      // 新增：显示边的选中态
        selectCellOnMoved: true,      // 移动时保持选中
        strict: false,            // 允许部分选中

        // 禁用自动选择新添加的节点
        selectNodeOnMoved: false,

        // 禁用框选功能，避免拖动画布时出现框选框
        rubberband: false,

        // 选择框样式
        className: 'my-selection',

        // 内容配置
        content: false,

        // 过滤器：哪些元素可以被选择
        filter: (cell) => {
          // 可以选择所有节点和边
          return cell.isNode() || cell.isEdge()
        }
      }))
      .use(new Keyboard({
        enabled: true
      }))
      .use(new Transform({
        resizing: false,
        rotating: false
      }))
      .use(new History({
        enabled: true
      }))
      .use(new Clipboard({
        enabled: true
      }))


  } catch (error) {
    console.error('创建 Graph 对象失败:', error)
    throw error
  }
}

// 设置边选中/取消选中的高亮样式
const setEdgeHighlight = (edge: any, active: boolean) => {
  try {
    edge?.attr?.('line/stroke', getGraphPalette().edgeStroke)  // 连线颜色跟随主题
    edge?.attr?.('line/strokeWidth', 2)  // 连线宽度统一为 2px
  } catch (e) {
    console.warn('setEdgeHighlight failed:', e)
  }
}

// 显示节点端口
const showNodePorts = (node: any) => {
  try {
    const ports = node.getPorts()
    ports?.forEach?.((port: any) => {
      node.portProp(port.id, 'attrs/circle/style/visibility', 'visible')
    })
  } catch (e) {
    console.warn('showNodePorts failed:', e)
  }
}

// 隐藏节点端口
const hideNodePorts = (node: any) => {
  try {
    const ports = node.getPorts()
    ports?.forEach?.((port: any) => {
      node.portProp(port.id, 'attrs/circle/style/visibility', 'hidden')
    })
  } catch (e) {
    console.warn('hideNodePorts failed:', e)
  }
}

// 设置节点选中样式（圆形蓝色边框）
const setNodeSelectedStyle = (node: any, selected: boolean) => {
  try {
    if (selected) {
      // 选中时显示圆形边框（颜色跟随主题）
      node.attr('body/strokeWidth', 1)
      node.attr('body/stroke', getGraphPalette().nodeSelectedStroke)
    } else {
      // 未选中时隐藏边框
      node.attr('body/strokeWidth', 0)
      node.attr('body/stroke', 'transparent')
    }
  } catch (e) {
    console.warn('setNodeSelectedStyle failed:', e)
  }
}

/**
 * 主题切换：只重绘颜色，不触碰 cells 的几何、层级或端口位置。
 * `ragstudio:theme-change` 事件由 lib/theme.ts 派发；这里原地更新已有 cell，
 * 新节点/新连线在创建时各自按当前主题取色。
 */
const applyGraphTheme = () => {
  if (!graph) {
    return
  }
  const palette = getGraphPalette()
  const dark = document.documentElement.classList.contains('dark')

  graph.drawBackground({ color: palette.canvasBackground })
  graph.drawGrid({ type: 'dot', args: { color: palette.grid, thickness: 2 } })

  graph.getNodes().forEach((node) => {
    applyNodeTheme(node, palette)
    if (graph?.isSelected(node)) {
      node.attr('body/stroke', palette.nodeSelectedStroke)
    }
  })

  graph.getEdges().forEach((edge) => {
    // 模板设计器创建的边原本是 #0077FF，画布创建的边是 #1993FF；
    // 记录在 data.lightStroke 里，切回浅色时还原各自的原色。
    const lightStroke = edge.getData()?.lightStroke
    const stroke = !dark && lightStroke ? lightStroke : palette.edgeStroke
    edge.attr('line/stroke', stroke)
    if (edge.attr('line/targetMarker')) {
      edge.attr('line/targetMarker/fill', stroke)
      edge.attr('line/targetMarker/stroke', stroke)
    }
    if (edge.attr('line/sourceMarker')) {
      edge.attr('line/sourceMarker/fill', stroke)
      edge.attr('line/sourceMarker/stroke', stroke)
    }
    if (edge.getLabels().length > 0) {
      edge.attr('label/fill', palette.edgeLabelFill)
      edge.attr('body/fill', palette.edgeLabelBackground)
    }
  })
}

// 处理窗口大小变化
const handleResize = () => {
  if (graph && containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    const width = rect.width || containerRef.value.clientWidth
    const height = rect.height || containerRef.value.clientHeight

    graph.resize(width, height)
  }
}

// 重新调整画布大小的方法
const resizeGraph = () => {
  handleResize()
}

const bindEvents = () => {
  if (!graph) {
    console.error('Graph 对象不存在，无法绑定事件')
    return
  }



  // 节点点击事件 - 只选中，不打开抽屉
  graph.on('node:click', ({ e }) => {
    e.stopPropagation()
    if (e.ctrlKey || e.metaKey) {
      // 按住 Ctrl/Command 时仅做多选
      return
    }
    // 单击只选中节点，不触发 node-select 事件（不打开抽屉）
    // X6 的 Selection 插件会自动处理选中状态
  })

  // 移除鼠标悬停显示端口的功能
  // 端口只在节点被选中时通过 selection:changed 事件显示

  // 双击事件 - 打开抽屉
  graph.on('node:dblclick', ({ node, e }) => {
    e.stopPropagation()
    // 双击时触发 node-select 事件，打开右侧抽屉
    emit('node-select', node)
  })

  // 边点击事件
  graph.on('edge:click', ({ edge, e }) => {
    e.stopPropagation()
    if (e.ctrlKey || e.metaKey) {
      // 交给选择插件处理选中，不打开抽屉
      return
    }
    emit('edge-select', edge)
  })

  // 画布点击事件
  graph.on('blank:click', () => {

    // 隐藏所有节点的端口
    const nodes = graph.getNodes()
    nodes.forEach(node => hideNodePorts(node))

    emit('canvas-click')
  })

  //连线事件
  graph.on('edge:connected', ({ edge }) => {
    const sNode = edge.getSourceNode()
    const tNode = edge.getTargetNode()
    const sPort = (edge.getSource() as any).port as string
    const tPort = (edge.getTarget() as any).port as string

    if (!graph || !sNode) {
      return
    }

    // 检测是否为自环连线（同一个节点）
    const isSelfLoop = sNode.id === tNode?.id

    // 自环连线处理：使用弧线（er 路由）
    if (isSelfLoop) {
      // 如果是 self 模式，要求同端口；其他模式允许不同端口
      if (connectionMode.value === 'self' && sPort !== tPort) {
        edge.remove()
        return
      }

      const edgeStroke = getGraphPalette().edgeStroke
      const newEdge = graph.addEdge({
        shape: 'self-loop-edge',
        source: { cell: sNode.id, port: sPort },
        target: { cell: sNode.id, port: sPort },
        connector: { name: 'smooth' }, // 使用平滑连接器
        attrs: {
          line: {
            stroke: edgeStroke,  // 连线颜色（当前主题）
            strokeWidth: 2,     // 连线宽度 2px
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
        data: { lightStroke: '#1993FF' },
        vertices: getFullCircleVertices(sNode, sPort) // 使用完整圆形自环顶点
      })

      edge.remove()
      emit('edge-select', newEdge)
      return
    }

    // 非自环：直线
    const shapeName = connectionMode.value === 'double' ? 'double-arrow-edge' : 'single-arrow-edge'
    const edgeStroke = getGraphPalette().edgeStroke
    const newEdge = graph.addEdge({
      shape: shapeName,
      source: { cell: sNode.id, port: sPort },
      target: { cell: tNode?.id || sNode.id, port: tPort },
      connector: { name: 'smooth' },  // 使用平滑连接器
      attrs: {
        line: {
          stroke: edgeStroke,  // 连线颜色（当前主题）
          strokeWidth: 2,     // 连线宽度 2px
          fill: 'none',
          targetMarker: {
            name: 'classic',
            size: 6,
            fill: edgeStroke,
            stroke: edgeStroke
          }
        }
      },
      data: { lightStroke: '#1993FF' }
    })

    edge.remove()
    emit('edge-select', newEdge)
  })


  // 右键菜单 - 改进版
  graph.on('node:contextmenu', ({ node, e }) => {
    e.preventDefault()
    e.stopPropagation()

    selectedContextNode.value = node
    contextMenuVisible.value = true

    // 确保菜单不会超出屏幕边界
    const menuWidth = 200
    const menuHeight = 160
    let left = e.clientX
    let top = e.clientY

    if (left + menuWidth > window.innerWidth) {
      left = window.innerWidth - menuWidth - 10
    }
    if (top + menuHeight > window.innerHeight) {
      top = window.innerHeight - menuHeight - 10
    }

    contextMenuStyle.value = {
      left: left + 'px',
      top: top + 'px'
    }
  })

  // 画布右键菜单（可选）
  graph.on('blank:contextmenu', ({ e }) => {
    e.preventDefault()

    selectedContextNode.value = null
    contextMenuVisible.value = true

    contextMenuStyle.value = {
      left: e.clientX + 'px',
      top: e.clientY + 'px'
    }
  })

  // 点击其他地方关闭右键菜单
  document.addEventListener('click', (e) => {
    // 检查是否点击在菜单内部
    const menu = (e.target as HTMLElement)?.closest('.context-menu')
    if (!menu) {
      contextMenuVisible.value = false
    }
  })

  // ESC键关闭菜单
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      contextMenuVisible.value = false
    }
  })

  // 键盘快捷键支持
  document.addEventListener('keydown', (e) => {
    // 检查当前焦点是否在可编辑元素中（input、textarea、contenteditable 等）
    const activeElement = document.activeElement
    const isEditableElement = activeElement && (
      activeElement.tagName === 'INPUT' ||
      activeElement.tagName === 'TEXTAREA' ||
      activeElement.getAttribute('contenteditable') === 'true' ||
      activeElement.closest('[contenteditable="true"]') !== null
    )

    // 如果焦点在可编辑元素中，不拦截快捷键，让浏览器执行默认行为
    if (isEditableElement) {
      return
    }

    // 检查是否有元素被选中
    const selectedCells = graph?.getSelectedCells() || []
    const selectedNodes = selectedCells.filter(cell => cell.isNode())
    const selectedEdges = selectedCells.filter(cell => cell.isEdge())

    if (e.ctrlKey || e.metaKey) {
      switch (e.key.toLowerCase()) {
        case 'c':
          if (selectedNodes.length > 0) {
            e.preventDefault()
            selectedContextNode.value = selectedNodes[0]
            copyNode()
          }
          break
        case 'v':
          if (hasCopiedNode.value) {
            e.preventDefault()
            pasteNode()
          }
          break
        default:
          break
      }
    } else if (e.key === 'Delete' && (selectedNodes.length > 0 || selectedEdges.length > 0)) {
      e.preventDefault()
      // if (selectedNodes.length > 0) {
      //   selectedContextNode.value = selectedNodes[0]
      //   deleteNode()
      // }
      if (selectedEdges.length > 0) {
        selectedEdges.forEach((edge: any) => edge.remove())
      }
    }
  })

  // 监听节点添加事件，确保新节点端口默认隐藏—— 目前多余，无需此代码也能解决实体4个白点问题
  // graph.on('node:added', ({ node }) => {
  //   console.log('node:added 事件触发:', node.id)
  //   // 立即隐藏端口和边框
  //   hideNodePorts(node)
  //   setNodeSelectedStyle(node, false)
  //   // 取消选中状态
  //   if (graph.isSelected(node)) {
  //     graph.unselect(node)
  //   }
  // })

  // 添加节点移动时的防重叠检测
  graph.on('node:moved', ({ node }) => {
    checkAndResolveOverlap(node)
  })

  // 添加节点移动中的实时检测
  graph.on('node:moving', ({ node }) => {
    checkAndPreventOverlap(node)
  })

  // 选择变化事件
  graph.on('selection:changed', ({ added, removed }) => {

    // 处理新选中的元素
    added?.forEach?.((cell: any) => {
      if (cell.isEdge && cell.isEdge()) {
        setEdgeHighlight(cell, true)
      } else if (cell.isNode && cell.isNode()) {
        // 选中节点时显示端口和圆形边框
        showNodePorts(cell)
        setNodeSelectedStyle(cell, true)
      }
    })

    // 处理取消选中的元素
    removed?.forEach?.((cell: any) => {
      if (cell.isEdge && cell.isEdge()) {
        setEdgeHighlight(cell, false)
      } else if (cell.isNode && cell.isNode()) {
        // 取消选中节点时隐藏端口和圆形边框
        hideNodePorts(cell)
        setNodeSelectedStyle(cell, false)
      }
    })
  })

  // 框选开始
  graph.on('selection:started', () => {
  })

  // 框选结束
  graph.on('selection:finished', () => {
    // 手动将矩形范围内的边加入选中并高亮
    selectEdgesInRubberband()
  })

  // 多个元素移动事件
  graph.on('cell:moved', () => {
    // 如果需要，可以在这里处理移动后的逻辑
  })

  // 边鼠标抬起兜底：Ctrl 选择保持选中
  graph.on('edge:mouseup', ({ edge, e }) => {
    if (e.ctrlKey || e.metaKey) {
      setTimeout(() => {
        if (!graph?.isSelected(edge)) {
          graph?.addToSelection?.(edge)
        }
        setEdgeHighlight(edge, true)
      }, 0)
    }
  })

}

// 读取当前 rubberband 的屏幕矩形并转为画布坐标
const getRubberbandArea = () => {
  const el = containerRef.value?.querySelector('.x6-widget-selection-rubberband') as HTMLElement | null
  if (!el || !graph) {
    return null
  }
  const rect = el.getBoundingClientRect()
  const tl = graph.clientToLocal({ x: rect.left, y: rect.top })
  const br = graph.clientToLocal({ x: rect.right, y: rect.bottom })
  const x = Math.min(tl.x, br.x)
  const y = Math.min(tl.y, br.y)
  const width = Math.abs(br.x - tl.x)
  const height = Math.abs(br.y - tl.y)
  return { x, y, width, height }
}

const rectIntersects = (a: any, b: any) => {
  return !(a.x + a.width < b.x || b.x + b.width < a.x || a.y + a.height < b.y || b.y + b.height < a.y)
}

const selectEdgesInRubberband = () => {
  if (!graph) {
    return
  }
  const area = getRubberbandArea()
  if (!area) {
    return
  }
  const edges = graph.getEdges ? graph.getEdges() : []
  edges.forEach((edge: any) => {
    const bbox = edge.getBBox?.()
    if (!bbox) {
      return
    }
    const eb = { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height }
    if (rectIntersects(area, eb)) {
      graph.select?.(edge)
      setEdgeHighlight(edge, true)
    }
  })
}

// 检测并防止节点重叠
const checkAndPreventOverlap = (movingNode: any) => {
  if (!graph) {
    return
  }

  const movingBBox = movingNode.getBBox()
  const allNodes = graph.getNodes()

  for (const node of allNodes) {
    if (node.id === movingNode.id) {
      continue
    }

    const nodeBBox = node.getBBox()

    // 检测是否重叠
    if (isOverlapping(movingBBox, nodeBBox)) {
      // 计算安全位置
      const safePosition = calculateSafePosition(movingBBox, nodeBBox)
      movingNode.setPosition(safePosition.x, safePosition.y)
      break
    }
  }
}

// 检测并解决节点重叠
const checkAndResolveOverlap = (node: any) => {
  if (!graph) {
    return
  }

  const nodeBBox = node.getBBox()
  const allNodes = graph.getNodes()
  let hasOverlap = false

  for (const otherNode of allNodes) {
    if (otherNode.id === node.id) {
      continue
    }

    const otherBBox = otherNode.getBBox()

    if (isOverlapping(nodeBBox, otherBBox)) {
      hasOverlap = true
      // 移动当前节点到安全位置
      const safePosition = calculateSafePosition(nodeBBox, otherBBox)
      node.setPosition(safePosition.x, safePosition.y)
      break
    }
  }

  if (hasOverlap) {
    // 递归检查新位置是否还有重叠
    setTimeout(() => {
      checkAndResolveOverlap(node)
    }, 10)
  }
}

// 判断两个矩形是否重叠
const isOverlapping = (rect1: any, rect2: any) => {
  const margin = 10 // 添加边距
  return !(
    rect1.x + rect1.width + margin <= rect2.x ||
    rect2.x + rect2.width + margin <= rect1.x ||
    rect1.y + rect1.height + margin <= rect2.y ||
    rect2.y + rect2.height + margin <= rect1.y
  )
}

// 计算安全位置
const calculateSafePosition = (movingRect: any, staticRect: any) => {
  const margin = 20

  // 尝试四个方向：右、左、下、上
  const positions = [
    { x: staticRect.x + staticRect.width + margin, y: movingRect.y }, // 右侧
    { x: staticRect.x - movingRect.width - margin, y: movingRect.y }, // 左侧
    { x: movingRect.x, y: staticRect.y + staticRect.height + margin }, // 下方
    { x: movingRect.x, y: staticRect.y - movingRect.height - margin }  // 上方
  ]

  // 选择第一个不会超出画布边界的位置
  const canvasRect = graph!.getGraphArea()

  for (const pos of positions) {
    if (
      pos.x >= 0 &&
      pos.y >= 0 &&
      pos.x + movingRect.width <= canvasRect.width &&
      pos.y + movingRect.height <= canvasRect.height
    ) {
      return pos
    }
  }

  // 如果都不合适，返回画布中心附近的随机位置
  return {
    x: Math.random() * (canvasRect.width - movingRect.width - 100) + 50,
    y: Math.random() * (canvasRect.height - movingRect.height - 100) + 50
  }
}

// 添加节点的方法需要返回节点实例
const addNode = (nodeType: string) => {
  if (!graph) {
    console.error('Graph 对象不存在，无法添加节点')
    console.error('请检查组件是否正确初始化')

    // 尝试重新初始化
    setTimeout(async () => {
      try {
        if (containerRef.value) {
          await initGraph()
          bindEvents()
          isInitialized.value = true
          emit('initialized', true)
        }
      } catch (error) {
        console.error('重新初始化失败:', error)
      }
    }, 100)

    return null
  }

  if (!isInitialized.value) {
    console.error('组件尚未完全初始化，无法添加节点')
    return null
  }


  try {
    const graphArea = graph.getGraphArea()
    const centerX = graphArea.width / 2
    const centerY = graphArea.height / 2

    // 在中心位置附近随机放置，避免重叠
    const randomOffset = () => Math.random() * 100 - 50

    const nodeData = getNodeDefaultProperties(nodeType)

    const node = graph.addNode({
      shape: `${nodeType}-node`,
      x: centerX + randomOffset(),
      y: centerY + randomOffset(),
      width: 56,
      height: 56,
      attrs: {
        label: {
          text: (nodeData as any).name || (nodeData as any).entity_type || nodeType
        }
      },
      data: nodeData
    })

    applyNodeTheme(node)



    // 立即确保新节点的端口是隐藏的
    hideNodePorts(node)
    setNodeSelectedStyle(node, false)

    // 检查并解决可能的重叠
    setTimeout(() => {
      checkAndResolveOverlap(node)
    }, 10)

    // 多次确保节点不会被自动选中
    setTimeout(() => {
      if (graph.isSelected(node)) {
        graph.unselect(node)
      }
      hideNodePorts(node)
      setNodeSelectedStyle(node, false)
    }, 50)

    setTimeout(() => {
      if (graph.isSelected(node)) {
        graph.unselect(node)
      }
      hideNodePorts(node)
      setNodeSelectedStyle(node, false)
    }, 150)

    return node
  } catch (error) {
    console.error('添加节点时发生错误:', error)
    return null
  }
}

// 更新节点属性
const updateNodeProperties = (nodeId: string, properties: any) => {
  if (!graph) {
    return
  }

  const node = graph.getCellById(nodeId) as Node
  if (node) {
    // 更新节点数据（深拷贝 properties 避免引用共享）
    // 注意：X6 的 setData 默认是深合并（ObjectExt.merge），可能导致数组元素残留。
    // 使用 replaceData（即 setData + overwrite: true）确保完全替换，避免残留。
    const updatedData = {
      ...node.getData(),
      ...properties,
      properties: properties.properties ? JSON.parse(JSON.stringify(properties.properties)) : []
    }
    node.replaceData(updatedData)

    // 更新节点显示标签 - 优先使用 name（实体类名），确保画布显示的类名和实际类名一致
    const displayName = properties.name || updatedData.name || properties.entity_type || updatedData.entity_type || 'Entity'
    node.setAttrs({
      label: {
        text: displayName
      }
    })
  }
}

// 更新边属性
const updateEdgeProperties = (edgeId: string, properties: any) => {
  if (!graph) {
    return
  }

  const edge = graph.getCellById(edgeId) as Edge
  if (edge) {
    // 注意：X6 的 setData 默认是深合并（ObjectExt.merge），可能导致数组元素残留。
    // 使用 replaceData（即 setData + overwrite: true）确保完全替换，避免残留。
    edge.replaceData({
      ...edge.getData(),
      ...properties,
      properties: properties.properties ? JSON.parse(JSON.stringify(properties.properties)) : []
    })

    // 更新边标签
    edge.setLabels([{
      attrs: {
        label: {
          text: properties.edge_type || 'contains',
          fill: '#666',
          fontSize: 12
        }
      }
    }])
  }
}

// 清空画布
const clearCanvas = () => {
  if (graph) {
    graph.clearCells()
  }
}

// 导出数据
const exportData = () => {
  if (graph) {
    return graph.toJSON()
  }
  return null
}

// Export graph data for schema creation
const exportForSchema = () => {
  if (!graph) {
    return { nodes: [], edges: [] }
  }

  const cells = graph.getCells()
  const nodes: any[] = []
  const edges: any[] = []

  cells.forEach((cell) => {
    if (cell.isNode()) {
      const nodeData = cell.getData() || {}
      nodes.push({
        id: cell.id,
        shape: cell.shape,
        data: {
          name: nodeData.name || '',
          description: nodeData.description || '',
          entity_type: nodeData.entity_type || nodeData.name || '',
          properties: nodeData.properties || []
        }
      })
    } else if (cell.isEdge()) {
      const edgeData = cell.getData() || {}
      const source = cell.getSource()
      const target = cell.getTarget()

      // 获取边的vertices（自闭环需要）
      const vertices = cell.getVertices() || []

      edges.push({
        id: cell.id,
        shape: cell.shape,
        source,
        target,
        vertices: vertices.length > 0 ? vertices : undefined, // 只在有vertices时导出
        data: {
          edge_type: edgeData.edge_type || '',
          edge_desc: edgeData.edge_desc || '',
          direction: edgeData.direction || '',
          source_entity: edgeData.source_entity || '',
          target_entity: edgeData.target_entity || '',
          properties: edgeData.properties || []
        }
      })
    }
  })

  return { nodes, edges }
}

// 导出SVG
const exportSVG = () => {
  if (graph) {
    return graph.exportSVG()
  }
  return ''
}

// 撤销和重做方法
const undo = () => {
  if (graph && graph.canUndo()) {
    graph.undo()
  }
}

const redo = () => {
  if (graph && graph.canRedo()) {
    graph.redo()
  }
}

// 检查是否可以撤销/重做
const canUndo = computed(() => {
  return graph ? graph.canUndo() : false
})

const canRedo = computed(() => {
  return graph ? graph.canRedo() : false
})

// 加载数据
const loadData = (data: any) => {
  if (graph && data && data.cells) {
    graph.fromJSON(data)
  }
}

// 缩放控制
const zoomIn = () => {
  if (graph) {
    graph.zoom(0.1)
  }
}

const zoomOut = () => {
  if (graph) {
    graph.zoom(-0.1)
  }
}

const fitView = () => {
  if (graph) {
    graph.zoomToFit({ padding: 20 })
  }
}

// 右键菜单相关
const contextMenuVisible = ref(false)
const contextMenuStyle = ref({
  left: '0px',
  top: '0px'
})
const selectedContextNode = ref(null) // 当前右键选中的节点
const copiedNodeData = ref(null) // 复制的节点数据
const hasCopiedNode = computed(() => !!copiedNodeData.value)
const hasSelectedNode = computed(() => !!selectedContextNode.value)


// 复制节点
const copyNode = () => {
  // 如果没有选中的节点，直接返回
  if (!selectedContextNode.value) {
    return
  }

  // 复制节点的完整数据
  const nodeData = {
    shape: selectedContextNode.value.shape,
    size: selectedContextNode.value.getSize(),
    attrs: selectedContextNode.value.getAttrs(),
    data: selectedContextNode.value.getData(),
    ports: selectedContextNode.value.getPorts()
  }

  copiedNodeData.value = nodeData

  contextMenuVisible.value = false
}

// 粘贴节点功能
const pasteNode = () => {
  if (!copiedNodeData.value || !graph) {
    contextMenuVisible.value = false
    return
  }

  try {
    // 在鼠标位置附近粘贴新节点
    const menuX = parseInt(contextMenuStyle.value.left)
    const menuY = parseInt(contextMenuStyle.value.top)

    // 转换屏幕坐标到画布坐标
    const canvasPoint = graph.clientToLocal({ x: menuX + 50, y: menuY + 50 })

    // 生成新的节点名称（使用英文后缀）
    const originalName = copiedNodeData.value.data.name || copiedNodeData.value.data.entity_type || 'Entity'
    const newName = `${originalName}_Copy`

    const newNode = graph.addNode({
      shape: copiedNodeData.value.shape,
      x: canvasPoint.x,
      y: canvasPoint.y,
      width: copiedNodeData.value.size.width,
      height: copiedNodeData.value.size.height,
      attrs: {
        ...copiedNodeData.value.attrs,
        label: {
          text: newName
        }
      },
      data: {
        ...copiedNodeData.value.data,
        name: newName,
        entity_type: newName
      },
      ports: copiedNodeData.value.ports
    })

    applyNodeTheme(newNode)


    // 选中新粘贴的节点
    setTimeout(() => {
      emit('node-select', newNode)
    }, 100)

  } catch (error) {
    console.error('粘贴节点失败:', error)
  }

  contextMenuVisible.value = false
}

// 删除节点功能（已注释，后续如有需要再放开）
// const deleteNode = () => {
//   if (selectedContextNode.value && graph) {
//     // 获取节点信息用于确认
//     const nodeName = selectedContextNode.value.getData()?.name || '此节点'

//     // 删除节点（包括连接的边）
//     selectedContextNode.value.remove()

//     console.log('节点已删除:', nodeName)

//     // 清除选中状态
//     selectedContextNode.value = null
//     emit('canvas-click') // 触发画布点击事件，清除选中状态
//   }

//   contextMenuVisible.value = false
// }

// 删除选中的元素（供外部调用）
const deleteSelectedCells = () => {
  if (!graph) {
    console.error('Graph not initialized')
    return 0
  }

  const selectedCells = graph.getSelectedCells()

  if (!selectedCells || selectedCells.length === 0) {
    return 0
  }

  const count = selectedCells.length

  // 删除所有选中的元素
  selectedCells.forEach((cell: any) => {
    cell.remove()
  })

  // 清除选中状态
  emit('canvas-click')

  return count
}

// 添加边（供外部调用）
const addEdge = (edgeConfig: any) => {
  if (!graph) {
    console.error('Graph not initialized')
    return null
  }

  try {
    const edge = graph.addEdge(edgeConfig)
    return edge
  } catch (error) {
    console.error('Failed to add edge:', error)
    return null
  }
}

// 注意：此处的连线模式相关变量与方法已在文件顶部声明，此块为重复定义，予以删除

defineExpose({
  addNode,
  addEdge, // 暴露添加边的方法
  updateNodeProperties,
  updateEdgeProperties,
  exportData,
  exportForSchema,
  exportSVG,
  undo,
  redo,
  canUndo,
  canRedo,
  loadData,
  zoomIn,
  zoomOut,
  fitView,
  resizeGraph,
  clearCanvas,
  setConnectionMode,
  getConnectionMode: () => connectionMode.value,
  deleteSelectedCells, // 暴露删除选中元素的方法
  graph  // 暴露graph对象供父组件访问
})


</script>

<style scoped>
.graph-canvas {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
}

.x6-container {
  width: 100%;
  height: 100%;
  position: relative;
}

.context-menu {
  position: fixed;
  background: var(--rs-bg-card);
  border: 1px solid var(--rs-border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  z-index: 2000;
  min-width: 120px;
  padding: 4px 0;
  font-size: 14px;
  user-select: none;
  backdrop-filter: blur(8px);
}

.menu-divider {
  height: 1px;
  background: var(--rs-border-soft);
  margin: 4px 8px;
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;

  .menu-icon {
    margin-right: 8px;
    font-size: 14px;
    color: var(--rs-text-2);
    transition: color 0.2s ease;
  }

  .menu-text {
    color: var(--rs-text);
    font-size: 14px;
  }

  &:hover:not(.disabled) {
    background: var(--rs-bg-soft);

    .menu-icon {
      color: var(--rs-primary);
    }

    .menu-text {
      color: var(--rs-primary);
    }
  }

  &.danger {
    .menu-icon {
      color: var(--rs-danger);
    }

    .menu-text {
      color: var(--rs-danger);
    }

    &:hover {
      background: color-mix(in srgb, var(--rs-danger) 8%, transparent);

      .menu-icon, .menu-text {
        color: var(--rs-danger);
      }
    }
  }

  &.disabled {
    cursor: not-allowed;
    opacity: 0.5;

    .menu-text, .menu-icon {
      color: var(--rs-text-3);
    }
  }
}


/* 强制显示连线 */
.x6-edge path {
  visibility: visible !important;
  opacity: 1 !important;
  display: block !important;
}

.x6-edge path[pointer-events="none"] {
  visibility: visible !important;
  opacity: 1 !important;
  display: block !important;
}

/* 框选样式 */
:deep(.my-rubberband) {
  border: 2px dashed var(--rs-primary);
  background-color: rgba(95, 149, 255, 0.1);
}

/* 选择框样式 */
:deep(.my-selection) {
  border: 2px solid var(--rs-primary);
  background-color: rgba(95, 149, 255, 0.05);
}

/* 选中节点的样式 */
:deep(.x6-widget-selection-rubberband) {
  border: 2px dashed var(--rs-primary);
  background-color: rgba(95, 149, 255, 0.1);
}

/* 选中状态的节点边框 */
:deep(.x6-widget-selection-box) {
  border: 2px solid var(--rs-primary);
  background: transparent;
}

/* 选中状态的控制点 */
:deep(.x6-widget-selection-box .x6-widget-selection-box-handle) {
  width: 8px;
  height: 8px;
  border: 2px solid var(--rs-primary);
  background: var(--rs-bg-card);
  border-radius: 50%;
}


/* 菜单动画 */
.context-menu {
  animation: menuFadeIn 0.15s ease-out;
}

@keyframes menuFadeIn {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(-4px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

</style>
