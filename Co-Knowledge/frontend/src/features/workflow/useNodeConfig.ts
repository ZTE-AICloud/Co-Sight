import {
  DEFAULT_CUSTOM_NODE_WIDTH, DEFAULT_CUSTOM_NODE_HEIGHT,
  DEFAULT_QUERY_NODE_HEIGHT, QUERY_NODE_SHAPE, RESPONSE_NODE_SHAPE,
  DEFAULT_SIDE_BAR_NODE_WIDTH, DEFAULT_SIDE_BAR_NODE_HEIGHT,
  Preretriever, Retriever, Postretriever, ResponseSynthesizer
} from '@/features/workflow/lib/workflow';
import { ComponentEnum } from './types';

/*
 * 画布配色唯一真值：主题层定义的 --rs-graph-*（light / dark 各一套）。
 * X6 的连线与链接桩颜色写在 JS attrs 里，CSS 覆盖不到，所以这里在**调用时**
 * 读一次当前主题的变量；主题切换由 CustomizedAdvancedFlow 监听
 * ragstudio:theme-change 后原地刷新已有 cell，不重建 Graph。
 * 读不到变量时回落到默认浅色值，保证浅色主题零变化。
 */
export function getGraphColors (): { edge: string, portFill: string, portStroke: string } {
  const read = (name: string, fallback: string): string => {
    if (typeof window === 'undefined' || !document?.documentElement) {
      return fallback
    }
    const value = window.getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim()
    return value || fallback
  }
  return {
    edge: read('--rs-edge', '#8faedc'),
    portFill: read('--rs-graph-port-fill', '#E6F1FF'),
    portStroke: read('--rs-graph-port-stroke', '#0077FF')
  }
}

/**
 * 把当前主题的链接桩颜色写进一份节点配置（原地），用于拖动新增节点。
 * 只改 fill/stroke，不动 r / 位置 / magnet 等几何与交互属性。
 */
export function withGraphColors<T> (config: T): T {
  const { portFill, portStroke } = getGraphColors()
  const groups = (config as any)?.ports?.groups || {}
  Object.keys(groups).forEach(key => {
    const attrs = groups[key]?.attrs
    if (attrs?.circle) {
      attrs.circle.fill = portFill
      attrs.circle.stroke = portStroke
    }
    if (attrs?.dot) {
      attrs.dot.fill = portStroke
    }
  })
  return config
}

const initialGraphColors = getGraphColors()

export const CommonMarkupConfig = [
  // 端点 9px 视觉，另加一层透明大圆做命中区
  {
    tagName: 'circle',
    selector: 'hit',
    attrs: {
      r: 9,
      magnet: true,
      fill: 'transparent',
      stroke: 'transparent',
      pointerEvents: 'all'
    }
  },
  {
    tagName: 'circle',
    selector: 'circle'
  },
  {
    tagName: 'circle',
    selector: 'dot'
  }
]
export const defaultDotConfig = {
  magnet: true,
  fill: initialGraphColors.portStroke,
  r: 0
}
const CommonGroupsConfig = {
  // 输入链接桩群组定义
  in: {
    markup: CommonMarkupConfig,
    position: {
      name: 'absolute',
      args: { x: 0, y: 0 }
    },
    attrs: {
      circle: {
        r: 4.5,
        magnet: true,
        stroke: initialGraphColors.portStroke,
        strokeWidth: 1.5,
        fill: initialGraphColors.portFill
      },
      dot: defaultDotConfig
    }
  },
  // 输出链接桩群组定义
  out: {
    markup: CommonMarkupConfig,
    position: {
      name: 'absolute',
      args: { x: 0, y: 0 }
    },
    attrs: {
      circle: {
        r: 4.5,
        magnet: true,
        stroke: initialGraphColors.portStroke,
        strokeWidth: 1.5,
        fill: initialGraphColors.portFill
      },
      dot: defaultDotConfig
    }
  }
}
const TargetGroupsConfig = {
  in: {
    markup: CommonMarkupConfig,
    position: {
      name: 'absolute',
      args: { x: 0, y: 0 }
    },
    attrs: {
      circle: {
        r: 4.5,
        magnet: true,
        stroke: initialGraphColors.portStroke,
        strokeWidth: 1.5,
        fill: initialGraphColors.portFill
      },
      dot: defaultDotConfig
    }
  }
}
const TargetPortConfig = {
  groups: TargetGroupsConfig,
  items: [
    {
      id: 'target-port',
      group: 'in',
      args: {
        x: 0,
        y: 109
      }
    }
  ]
}

export const PreRetrieverPortConfig = {
  groups: CommonGroupsConfig,
  items: [
    {
      id: 'preretriever_input',
      group: 'in',
      args: {
        x: Preretriever.input.x,
        y: Preretriever.input.y
      }
    },
    {
      id: 'preretriever_output',
      group: 'out',
      args: {
        x: Preretriever.output.x,
        y: Preretriever.output.y
      }
    }
  ]
}

export const RetrieverPortConfig = {
  groups: CommonGroupsConfig,
  items: [
    {
      id: 'retriever_input',
      group: 'in',
      args: {
        x: Retriever.input.x,
        y: Retriever.input.y
      }
    },
    {
      id: 'retriever_output',
      group: 'out',
      args: {
        x: Retriever.output.x,
        y: Retriever.output.y
      }
    }
  ]
}

export const PostRetrieverPortConfig = {
  groups: CommonGroupsConfig,
  items: [
    {
      id: 'postretriever_input',
      group: 'in',
      args: {
        x: Postretriever.input.x,
        y: Postretriever.input.y
      }
    },
    {
      id: 'postretriever_output',
      group: 'out',
      args: {
        x: Postretriever.output.x,
        y: Postretriever.output.y
      }
    }
  ]
}

export const ResponseSynthesizerPortConfig = {
  groups: CommonGroupsConfig,
  items: [
    {
      id: 'responsesynthesizer_input',
      group: 'in',
      args: {
        x: ResponseSynthesizer.input.x,
        y: ResponseSynthesizer.input.y
      }
    },
    {
      id: 'responsesynthesizer_output',
      group: 'out',
      args: {
        x: ResponseSynthesizer.output.x,
        y: ResponseSynthesizer.output.y
      }
    }
  ]
}

export const PreRetrieverNodeConfig = {
  width: DEFAULT_CUSTOM_NODE_WIDTH,
  height: DEFAULT_CUSTOM_NODE_HEIGHT,
  shape: ComponentEnum.PRE_RETRIEVER,
  label: 'PRE-',
  ports: PreRetrieverPortConfig
}

export const RetrieverNodeConfig = {
  width: DEFAULT_CUSTOM_NODE_WIDTH,
  height: DEFAULT_CUSTOM_NODE_HEIGHT,
  shape: ComponentEnum.RETRIEVER,
  label: 'RETRI-',
  ports: RetrieverPortConfig
}

export const PostRetrieverNodeConfig = {
  width: DEFAULT_CUSTOM_NODE_WIDTH,
  height: DEFAULT_CUSTOM_NODE_HEIGHT,
  shape: ComponentEnum.POST_RETRIEVER,
  label: 'POST-',
  ports: PostRetrieverPortConfig
}

export const ResponseSynthesizerNodeConfig = {
  width: DEFAULT_CUSTOM_NODE_WIDTH,
  height: DEFAULT_CUSTOM_NODE_HEIGHT,
  shape: ComponentEnum.RESPONSE_SYNTHESIZER,
  label: 'SYN-',
  ports: ResponseSynthesizerPortConfig
}

// 所有在画布中展示的节点配置
export function useNodeConfig () {
  function queryNodeConfig () {
    const { portFill, portStroke } = getGraphColors()
    return {
      x: 40,
      y: 40,
      width: DEFAULT_CUSTOM_NODE_WIDTH,
      height: DEFAULT_QUERY_NODE_HEIGHT,
      shape: QUERY_NODE_SHAPE,
      label: 'QUERY',
      ports: {
        groups: {
        // 输出链接桩群组定义
          out: {
            position: {
              name: 'absolute',
              args: { x: 0, y: 0 }
            },
            markup: CommonMarkupConfig,
            attrs: {
              hit: {
                r: 9,
                magnet: true,
                fill: 'transparent',
                stroke: 'transparent',
                pointerEvents: 'all'
              },
              circle: {
                r: 4.5,
                magnet: true,
                stroke: portStroke,
                strokeWidth: 1.5,
                fill: portFill
              }
            }
          }
        },
        items: [
          {
            id: 'text',
            group: 'out',
            args: {
              x: 264,
              y: 109
            }
          }
        ]
      }
    }
  }

  function responseNodeConfig () {
    return {
      x: 940,
      y: 40,
      width: DEFAULT_CUSTOM_NODE_WIDTH,
      height: DEFAULT_QUERY_NODE_HEIGHT,
      shape: RESPONSE_NODE_SHAPE,
      ports: TargetPortConfig
    }
  }
  return {
    queryNodeConfig,
    responseNodeConfig,
    PreRetrieverNodeConfig,
    RetrieverNodeConfig,
    PostRetrieverNodeConfig,
    ResponseSynthesizerNodeConfig
  }
}
// 在侧边栏中展示的节点配置
export function useSideBarNodeConfig () {
  function preretrieverSideBarNodeConfig () {
    return {
      id: 'preretriever',
      width: DEFAULT_SIDE_BAR_NODE_WIDTH,
      height: DEFAULT_SIDE_BAR_NODE_HEIGHT,
      shape: 'preretriever'
    }
  }
  return {
    preretrieverSideBarNodeConfig
  }
}

