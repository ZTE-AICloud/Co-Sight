/**
 * 检索编排画布的几何与端口计算。
 *
 * `nodeGeometry` / `workflowPort` / `workflowCurve` 在这里落成与 X6 解耦的纯函数：
 * 卡片尺寸、端口方位、贝塞尔曲线全部可单测，FlowDetail 只负责把结果写回 X6。
 *
 * 卡片宽 264、头高 52；正文按「算子行 / 上游输入行」的条数增长。
 * 注意：`height` 不含卡片上下 1px 描边，DOM 实际高度 = height + 2，
 * 这里用 `frameHeight` 表示 DOM 实际高度（X6 节点尺寸用它）。
 */

export const FLOW_NODE_WIDTH = 264
export const FLOW_NODE_HEADER_HEIGHT = 52
export const FLOW_FIXED_NODE_HEIGHT = 140
export const FLOW_OPERATOR_ROW_HEIGHT = 32
export const FLOW_ROW_GAP = 6

export const FLOW_MODULE_KEYS = {
  PRE_RETRIEVER: 'preretriever',
  RETRIEVER: 'retriever',
  POST_RETRIEVER: 'postretriever',
  RESPONSE_SYNTHESIZER: 'responsesynthesizer'
}

export const FLOW_FIXED_SHAPES = ['QUERY', 'RESPONSE']

/** QUERY / RESPONSE 是固定的开始 / 结束节点。 */
export function isFixedShape (shape) {
  return FLOW_FIXED_SHAPES.includes(shape)
}

/** 画布 shape → 后端 variables 里的算子数组键名。 */
export function moduleKeyOf (shape) {
  return FLOW_MODULE_KEYS[shape] || ''
}

/** 某个画布节点（后端 nodeConfigDTO）的算子数组。 */
export function getNodeOperators (nodeData = {}) {
  const key = moduleKeyOf(nodeData.shape || nodeData.componentType)
  const list = key ? nodeData.variables?.[key] : null
  return Array.isArray(list) ? list : []
}

/** 算子显示名：内置走 i18n，自定义用保存时的 operatorName。 */
export function operatorDisplayName (operator, translate = key => key) {
  if (!operator) {
    return '--'
  }
  if (operator.custom) {
    return operator.operatorName || operator.operator || '--'
  }
  const key = `ragFlow.${operator.operator}Operator`
  const label = translate(key)
  return !label || label === key ? (operator.operator || '--') : label
}

/** 去掉知识库选项的 `|#|dev` 发布状态后缀。 */
export function stripKbSuffix (name) {
  if (typeof name !== 'string') {
    return ''
  }
  const index = name.indexOf('|#|')
  return index >= 0 ? name.slice(0, index) : name
}

/** 一个检索算子绑定的知识库名（原始值，供名称映射用）。 */
export function collectOperatorSources (operator) {
  const kwargs = operator?.kwargs || {}
  if (operator?.operator === 'VectorRetriever') {
    return (kwargs.knowledge_info_list || []).flatMap(item => item?.knowledge_base_name || [])
  }
  const names = kwargs.knowledge_base_name
  if (Array.isArray(names)) {
    return names
  }
  return names ? [names] : []
}

/** 找不到映射时的短名：图谱库只显示「图谱知识库」，普通库去掉发布后缀。 */
export function shortKbName (name) {
  const value = stripKbSuffix(name)
  if (!value) {
    return ''
  }
  if (value.startsWith('graph_')) {
    return '图谱知识库'
  }
  return value
}

/**
 * 检索器卡片上的来源摘要（如 `企业知识图谱 · Top 5`）。
 * `resolveName` 可选，用于把 tableName 换成用户看到的知识库名称。
 */
export function sourceSummary (operators = [], resolveName = value => value, emptyLabel = '') {
  const first = operators[0]
  if (!first) {
    return { text: '', title: '' }
  }
  const names = [...new Set(collectOperatorSources(first).filter(Boolean))]
    .map(name => resolveName(name) || shortKbName(name))
  const topK = first?.kwargs?.top_k ?? first?.kwargs?.knowledge_info_list?.[0]?.top_k
  const top = Number.isFinite(Number(topK)) && topK !== '' && topK !== null && topK !== undefined
    ? `Top ${topK}`
    : ''
  const shown = names.length > 2
    ? `${names.slice(0, 2).join('、')} 等 ${names.length} 个`
    : (names.join('、') || emptyLabel)
  return {
    text: [shown, top].filter(Boolean).join(' · '),
    title: [names.join('、'), top].filter(Boolean).join(' · ')
  }
}

/** 节点输出字段（pre=query / retriever=documents / synth=answer）。 */
export function outputFieldKey (shape) {
  return {
    PRE_RETRIEVER: 'query',
    RETRIEVER: 'documents',
    POST_RETRIEVER: 'documents',
    RESPONSE_SYNTHESIZER: 'answer',
    QUERY: 'Question',
    RESPONSE: 'Answer'
  }[shape] || 'output'
}

/**
 * 卡片几何。`height` 不含描边；`frameHeight` 是 DOM / X6 实际高度。
 * `inputY` / `outputY` 是左右端口在卡片坐标系里的中心 y。
 */
export function nodeGeometry ({ shape, operatorCount = 0, inputCount = 0 } = {}) {
  if (isFixedShape(shape)) {
    return {
      width: FLOW_NODE_WIDTH,
      height: FLOW_FIXED_NODE_HEIGHT,
      frameHeight: FLOW_FIXED_NODE_HEIGHT,
      inputY: 109,
      outputY: 109
    }
  }
  const count = Math.max(1, operatorCount)
  const inputs = Math.max(1, inputCount)
  const operatorsHeight = count * FLOW_OPERATOR_ROW_HEIGHT + (count - 1) * FLOW_ROW_GAP
  const operatorsBlock = 14 + 18 + 8 + operatorsHeight + 14 + (shape === 'RETRIEVER' ? 28 : 0)
  const inputTop = FLOW_NODE_HEADER_HEIGHT + operatorsBlock
  const inputBlock = 18 + 8 + inputs * FLOW_OPERATOR_ROW_HEIGHT + (inputs - 1) * FLOW_ROW_GAP + 14
  const outputTop = inputTop + inputBlock
  const outputBlock = 18 + 8 + 28 + 14
  const height = outputTop + outputBlock
  return {
    width: FLOW_NODE_WIDTH,
    height,
    frameHeight: height + 2,
    inputY: inputTop + 26 + 16,
    outputY: outputTop + 26 + 14
  }
}

/**
 * 端口朝向的规则：
 * 同一列（水平中心接近）且对端全在下方 / 上方 → 下 / 上；对端全在左 / 右 → 左 / 右；
 * 其余保持 `fallbackSide`（删掉连线后端口不回弹）。
 */
export function portSide ({ node, peers = [], geometry, direction, fallbackSide }) {
  const aligned = peers.length > 0 &&
    peers.every(peer => Math.abs(peer.x - node.x) < geometry.width * 0.6)
  if (aligned && peers.every(peer => peer.y >= node.y + geometry.height + 16)) {
    return 'bottom'
  }
  if (aligned && peers.every(peer => peer.y + peer.height + 16 <= node.y)) {
    return 'top'
  }
  if (peers.length > 0 && peers.every(peer => peer.x + peer.width <= node.x - 16)) {
    return 'left'
  }
  if (peers.length > 0 && peers.every(peer => peer.x >= node.x + geometry.width + 16)) {
    return 'right'
  }
  return fallbackSide || (direction === 'output' ? 'right' : 'left')
}

/** 端口在卡片坐标系里的坐标。 */
export function portPosition ({ geometry, side, direction }) {
  const y = direction === 'input' ? geometry.inputY : geometry.outputY
  return {
    left: { x: 0, y },
    right: { x: geometry.width, y },
    top: { x: geometry.width / 2, y: 0 },
    bottom: { x: geometry.width / 2, y: geometry.height }
  }[side] || { x: direction === 'output' ? geometry.width : 0, y }
}

/** 端口离卡片边不超过这个距离才认为是这一侧的端口（像素）。 */
export const PORT_SIDE_TOLERANCE = 8

/**
 * 由端口坐标反推端口所在的一侧。
 *
 * 卡片 DOM 高是 `frameHeight`（比 `height` 多 2px 描边），端口 y 用的却是
 * `geometry.height`，所以下端口比 `node.getSize().height` 小 2px。按
 * 「y >= height - 0.5」判等会漏掉下端口，连线随之退化成左右朝向、先向外
 * 拐再绕回来。这里直接取离端口最近的一条边，2px 描边差不再影响判断。
 * 端口还没定位（坐标缺失或落在卡片中间）时返回空串，由调用方决定默认朝向。
 */
export function portSideFromPoint ({ x, y, width, height } = {}) {
  const pointX = Number(x)
  const pointY = Number(y)
  const nodeWidth = Number(width)
  const nodeHeight = Number(height)
  if (![pointX, pointY, nodeWidth, nodeHeight].every(Number.isFinite)) {
    return ''
  }
  const distances = [
    [pointX, 'left'],
    [nodeWidth - pointX, 'right'],
    [pointY, 'top'],
    [nodeHeight - pointY, 'bottom']
  ]
  const [distance, side] = distances.reduce((best, item) => (item[0] < best[0] ? item : best))
  return distance <= PORT_SIDE_TOLERANCE ? side : ''
}

/** 方位 → 贝塞尔控制柄方向。 */
export function directionOf (side) {
  return {
    left: { dx: -1, dy: 0 },
    right: { dx: 1, dy: 0 },
    top: { dx: 0, dy: -1 },
    bottom: { dx: 0, dy: 1 }
  }[side] || { dx: 0, dy: 0 }
}

/**
 * 三次贝塞尔：
 * 控制柄长度 = clamp(对向位移的一半, 32, 180)，且不超过两点距离的一半。
 * 返回值里带线中段（t=0.55）的箭头位置与角度。
 */
export function flowCurve (start, end, a, b) {
  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const handle = (port, other) => Math.min(180, Math.max(32, Math.abs(port.dx ? other.x : other.y) * 0.5), distance * 0.5)
  const h1 = handle(a, { x: end.x - start.x, y: end.y - start.y })
  const h2 = handle(b, { x: start.x - end.x, y: start.y - end.y })
  const c1 = { x: start.x + a.dx * h1, y: start.y + a.dy * h1 }
  const c2 = { x: end.x + b.dx * h2, y: end.y + b.dy * h2 }
  const point = t => {
    const u = 1 - t
    return {
      x: u ** 3 * start.x + 3 * u ** 2 * t * c1.x + 3 * u * t ** 2 * c2.x + t ** 3 * end.x,
      y: u ** 3 * start.y + 3 * u ** 2 * t * c1.y + 3 * u * t ** 2 * c2.y + t ** 3 * end.y
    }
  }
  const middle = point(0.55)
  const ahead = point(0.56)
  return {
    path: `M${start.x},${start.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${end.x},${end.y}`,
    arrow: {
      ...middle,
      angle: Math.atan2(ahead.y - middle.y, ahead.x - middle.x) * 180 / Math.PI
    }
  }
}
