import { Graph, Node } from '@antv/x6'
import { $t } from '@/app/i18n/i18n.js'

/**
 * Theme-aware colours for the X6 graph editor (GraphCanvas / template designer).
 *
 * The light values are the exact literals this file used before the dark theme,
 * so switching back to light reproduces the previous rendering. Dark values are
 * read from the semantic `--rs-graph-*` tokens at call time, which means newly
 * created cells and theme repaints both pick up the current theme without a
 * second registration pass.
 */
export interface GraphPalette {
  nodeFill: string
  nodeLabel: string
  portStroke: string
  portFill: string
  edgeStroke: string
  edgeDefaultStroke: string
  templateEdgeStroke: string
  edgeLabelFill: string
  edgeLabelBackground: string
  canvasBackground: string
  grid: string
  selection: string
  nodeSelectedStroke: string
  defaultNode: string
  nodeShadow: string
}

const LIGHT_GRAPH_PALETTE: GraphPalette = {
  nodeFill: '#FFFFFF',
  nodeLabel: '#262626',
  portStroke: '#1993FF',
  portFill: '#fff',
  edgeStroke: '#1993FF',
  edgeDefaultStroke: '#000000',
  templateEdgeStroke: '#0077FF',
  edgeLabelFill: '#000000',
  edgeLabelBackground: '#f5f5f5',
  canvasBackground: '#F5F4F9',
  grid: '#C0C0C0',
  selection: '#5F95FF',
  nodeSelectedStroke: '#1993FF',
  defaultNode: '#97c2fc',
  nodeShadow: 'rgba(0, 0, 0, 0.15)'
}

const readCssVar = (name: string, fallback: string): string => {
  if (typeof document === 'undefined' || !document.documentElement) {
    return fallback
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name)
    .trim()
  return value || fallback
}

export const isDarkGraphTheme = (): boolean => {
  if (typeof document === 'undefined' || !document.documentElement) {
    return false
  }
  return document.documentElement.classList.contains('dark')
}

export const getGraphPalette = (): GraphPalette => {
  if (!isDarkGraphTheme()) {
    return { ...LIGHT_GRAPH_PALETTE }
  }
  return {
    nodeFill: readCssVar('--rs-bg-elevated', '#13161c'),
    nodeLabel: readCssVar('--rs-text-primary', '#e9edf2'),
    portStroke: readCssVar('--rs-graph-port-stroke', '#7c8cff'),
    portFill: readCssVar('--rs-graph-port-fill', '#0b0d11'),
    edgeStroke: readCssVar('--rs-graph-edge', 'rgba(124, 140, 255, 0.55)'),
    edgeDefaultStroke: readCssVar('--rs-graph-edge', 'rgba(124, 140, 255, 0.55)'),
    templateEdgeStroke: readCssVar('--rs-graph-edge', 'rgba(124, 140, 255, 0.55)'),
    edgeLabelFill: readCssVar('--rs-text-primary', '#e9edf2'),
    edgeLabelBackground: readCssVar('--rs-bg-muted', '#14171c'),
    canvasBackground: readCssVar('--rs-graph-bg', '#080a0d'),
    grid: readCssVar('--rs-graph-grid', 'rgba(255, 255, 255, 0.08)'),
    selection: readCssVar('--rs-graph-selection', '#7c8cff'),
    nodeSelectedStroke: readCssVar('--rs-graph-selection', '#7c8cff'),
    defaultNode: readCssVar('--rs-bg-muted', '#14171c'),
    nodeShadow: 'rgba(0, 0, 0, 0.45)'
  }
}

/** Repaint an existing node in place (never touches its geometry or ports). */
export const applyNodeTheme = (node: Node, palette: GraphPalette = getGraphPalette()): void => {
  node.attr('body/fill', palette.nodeFill)
  node.attr('label/fill', palette.nodeLabel)
  node.getPorts().forEach(port => {
    // X6 的 PortMetadata.id 类型是可选的；没有 id 的端口无法按 id 定点重绘，跳过即可。
    if (!port.id) {
      return
    }
    node.portProp(port.id, 'attrs/circle/stroke', palette.portStroke)
    node.portProp(port.id, 'attrs/circle/fill', palette.portFill)
  })
}

// 工具：安全注册（顶层复用，避免重复定义导致 NLOC 膨胀）
const safeRegisterNode = (name: string, config: any) => {
  try {
    Graph.registerNode(name, config, true)
  } catch (error) {
    // 重复注册是幂等操作，静默忽略；其他错误才需要暴露
    if (!(error instanceof Error && error.message.includes('already registered'))) {
      console.error(`节点 ${name} 注册失败:`, error)
    }
  }
}

const safeRegisterEdge = (name: string, config: any) => {
  try {
    Graph.registerEdge(name, config, true)
  } catch (error) {
    // 重复注册是幂等操作，静默忽略；其他错误才需要暴露
    if (!(error instanceof Error && error.message.includes('already registered'))) {
      console.error(`边 ${name} 注册失败:`, error)
    }
  }
}

// 子任务 1：注册基础圆形节点（供各类型继承）
const registerBaseCircleNode = () => {
  const palette = getGraphPalette()
  safeRegisterNode('base-circle-node', {
    inherit: 'circle',
    width: 56,
    height: 56,
    markup: [
      {
        tagName: 'circle',
        selector: 'body'
      },
      {
        tagName: 'image',
        selector: 'icon'
      },
      {
        tagName: 'text',
        selector: 'label'
      }
    ],
    attrs: {
      body: {
        strokeWidth: 0,
        stroke: 'transparent',
        fill: palette.nodeFill,
        r: 28,
        filter: {
          name: 'dropShadow',
          args: {
            dx: 0,
            dy: 2,
            blur: 3,
            color: palette.nodeShadow
          }
        }
      },
      icon: {
        width: 24,
        height: 24,
        x: 16,
        y: 16,
        xlinkHref: require('@/assets/graph_entity.svg')
      },
      label: {
        fontSize: 12,
        fill: palette.nodeLabel,
        textAnchor: 'middle',
        textVerticalAnchor: 'top',
        refX: '50%',
        refY: '100%',
        y: 12,
        pointerEvents: 'none',
        fontWeight: 'normal'
      }
    },
    ports: {
      groups: {
        top: {
          position: 'top',
          attrs: {
            circle: {
              r: 3,
              magnet: true,
              stroke: palette.portStroke,
              strokeWidth: 1,
              fill: palette.portFill,
              style: {
                visibility: 'hidden' // 默认隐藏
              }
            }
          }
        },
        bottom: {
          position: 'bottom',
          attrs: {
            circle: {
              r: 3,
              magnet: true,
              stroke: palette.portStroke,
              strokeWidth: 1,
              fill: palette.portFill,
              style: {
                visibility: 'hidden' // 默认隐藏
              }
            }
          }
        },
        // 新增：固定端口分组（绝对坐标，基于节点局部坐标；你的圆节点宽高为 80）
        fixedLeft: {
          position: { name: 'absolute', args: { x: 0, y: 28 } },
          attrs: {
            circle: {
              r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill,
              style: { visibility: 'hidden' } // 默认隐藏
            }
          }
        },
        fixedRight: {
          position: { name: 'absolute', args: { x: 56, y: 28 } },
          attrs: {
            circle: {
              r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill,
              style: { visibility: 'hidden' } // 默认隐藏
            }
          }
        }
      },
      items: [
        { id: 'top', group: 'top' },
        { id: 'bottom', group: 'bottom' },
        // 新增两个固定端口实例（id 固定，便于定位）
        { id: 'fxL', group: 'fixedLeft' },
        { id: 'fxR', group: 'fixedRight' }
      ]
    }
  })
}

// 子任务 2：注册通用边及三种关系边
const registerCommonEdges = () => {
  const palette = getGraphPalette()
  // 自定义边 - 使用安全注册
  safeRegisterEdge('custom-edge', {
    inherit: 'edge',
    router: { name: 'orth' },
    connector: { name: 'rounded' },
    attrs: {
      line: {
        stroke: palette.edgeDefaultStroke,
        strokeWidth: 2,
        targetMarker: {
          name: 'classic',
          size: 8
        }
      }
    }
  })

  // 1. 单向箭头边
  safeRegisterEdge('single-arrow-edge', {
    inherit: 'edge',
    connector: { name: 'normal' },
    attrs: {
      line: {
        stroke: palette.edgeDefaultStroke,
        strokeWidth: 2,
        targetMarker: {
          name: 'classic',
          size: 8
        }
      }
    },
    defaultLabel: {
      markup: [
        {
          tagName: 'rect',
          selector: 'body'
        },
        {
          tagName: 'text',
          selector: 'label'
        }
      ],
      attrs: {
        label: {
          fill: palette.edgeLabelFill,
          fontSize: 12,
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          pointerEvents: 'none'
        },
        body: {
          ref: 'label',
          fill: palette.edgeLabelBackground,
          stroke: 'none',
          rx: 3,
          ry: 3,
          refWidth: '100%',
          refHeight: '100%',
          refX: 0,
          refY: 0
        }
      },
      position: {
        distance: 0.5
      }
    }
  })

  // 2. 双向箭头边
  safeRegisterEdge('double-arrow-edge', {
    inherit: 'edge',
    connector: { name: 'normal' },
    attrs: {
      line: {
        stroke: palette.edgeDefaultStroke,
        strokeWidth: 2,
        sourceMarker: {
          name: 'classic',
          size: 8
        },
        targetMarker: {
          name: 'classic',
          size: 8
        }
      }
    },
    defaultLabel: {
      markup: [
        {
          tagName: 'rect',
          selector: 'body'
        },
        {
          tagName: 'text',
          selector: 'label'
        }
      ],
      attrs: {
        label: {
          fill: palette.edgeLabelFill,
          fontSize: 12,
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          pointerEvents: 'none'
        },
        body: {
          ref: 'label',
          fill: palette.edgeLabelBackground,
          stroke: 'none',
          rx: 3,
          ry: 3,
          refWidth: '100%',
          refHeight: '100%',
          refX: 0,
          refY: 0
        }
      },
      position: {
        distance: 0.5
      }
    }
  })

  // 3. 自环边
  safeRegisterEdge('self-loop-edge', {
    inherit: 'edge',
    router: {
      name: 'er',
      args: {
        offset: 24,
        direction: 'T'
      }
    },
    connector: {
      name: 'rounded'
    },
    attrs: {
      line: {
        stroke: palette.edgeDefaultStroke,
        strokeWidth: 2,
        targetMarker: {
          name: 'classic',
          size: 8
        }
      }
    },
    defaultLabel: {
      markup: [
        {
          tagName: 'rect',
          selector: 'body'
        },
        {
          tagName: 'text',
          selector: 'label'
        }
      ],
      attrs: {
        label: {
          fill: palette.edgeLabelFill,
          fontSize: 12,
          textAnchor: 'middle',
          textVerticalAnchor: 'middle',
          pointerEvents: 'none'
        },
        body: {
          ref: 'label',
          fill: palette.edgeLabelBackground,
          stroke: 'none',
          rx: 3,
          ry: 3,
          refWidth: '100%',
          refHeight: '100%',
          refX: 0,
          refY: 0
        }
      },
      position: {
        distance: 0.5
      }
    }
  })
}

// 节点类型定义（数据驱动，避免重复）
const NODE_TYPES = [
  { type: 'entity', label: 'Entity', color: '#5F95FF' },
  { type: 'fault', label: 'Fault', color: '#F5222D' },
  { type: 'event', label: 'Event', color: '#FA541C' },
  { type: 'resource', label: 'Resource', color: '#13C2C2' },
  { type: 'rootCause', label: 'RootCause', color: '#722ED1' },
  { type: 'plan', label: 'Plan', color: '#FA8C16' },
  { type: 'examItem', label: 'ExamItem', color: '#8C8C8C' }
]

const buildTypeNodeConfig = (label: string, color: string) => {
  const palette = getGraphPalette()
  return {
    inherit: 'base-circle-node',
    attrs: {
      body: {
        stroke: color,
        fill: palette.nodeFill
      },
      label: {
        text: label,
        fill: palette.nodeLabel,
        textVerticalAnchor: 'top',
        refX: '50%',
        refY: '100%',
        y: 12
      }
    },
    ports: {
      groups: {
        top: {
          position: 'top',
          attrs: { circle: { r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill, style: { visibility: 'visible' } } }
        },
        bottom: {
          position: 'bottom',
          attrs: { circle: { r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill, style: { visibility: 'visible' } } }
        },
        fixedLeft: {
          position: { name: 'absolute', args: { x: 0, y: 28 } },
          attrs: { circle: { r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill, style: { visibility: 'visible' } } }
        },
        fixedRight: {
          position: { name: 'absolute', args: { x: 56, y: 28 } },
          attrs: { circle: { r: 3, magnet: true, stroke: palette.portStroke, strokeWidth: 1, fill: palette.portFill, style: { visibility: 'visible' } } }
        }
      },
      items: [
        { id: 'top', group: 'top' },
        { id: 'bottom', group: 'bottom' },
        { id: 'fxL', group: 'fixedLeft' },
        { id: 'fxR', group: 'fixedRight' }
      ]
    }
  }
}

const registerTypedCircleNodes = () => {
  NODE_TYPES.forEach(({ type, label, color }) => {
    safeRegisterNode(`${type}-node`, buildTypeNodeConfig(label, color))
  })
}

// 对外：总的注册入口（体量小、便于阅读，降低 NLOC）
export const registerCustomNodes = () => {
  registerBaseCircleNode()
  registerCommonEdges()
  registerTypedCircleNodes()
}

// 节点类型定义
type NodeType = 'entity' | 'fault' | 'event' | 'resource' | 'rootCause' | 'plan' | 'examItem'

// 获取节点默认属性
export const getNodeDefaultProperties = (nodeType: string) => {
  // 五种中文默认名复用图谱编辑器节点面板（NodePalette.vue）同名的节点类型键 ——
  // 同一种节点必须同一个词，另立一份 commonUi 键会各改各的。
  // ⚠️ entity / examItem 本来就是英文，保持原样：跟着翻译会改动 zh 下的渲染结果。
  const defaults: Record<NodeType, { name: string; description: string; attributes: any[] }> = {
    entity: { name: 'Entity', description: '', attributes: [] },
    fault: { name: $t('modules.kbWorkspace.graphEditor.nodeTypeFault'), description: '', attributes: [] },
    event: { name: $t('modules.kbWorkspace.graphEditor.nodeTypeEvent'), description: '', attributes: [] },
    resource: { name: $t('modules.kbWorkspace.graphEditor.nodeTypeResource'), description: '', attributes: [] },
    rootCause: { name: $t('modules.kbWorkspace.graphEditor.nodeTypeRootCause'), description: '', attributes: [] },
    plan: { name: $t('modules.kbWorkspace.graphEditor.nodeTypePlan'), description: '', attributes: [] },
    examItem: { name: 'ExamItem', description: '', attributes: [] }
  }
  return defaults[nodeType as NodeType] || { name: nodeType, description: '', attributes: [] }
}
