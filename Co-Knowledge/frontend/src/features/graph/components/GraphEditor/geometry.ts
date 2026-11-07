/**
 * 自环边顶点计算：在节点端口外侧画一个完整圆（实体半径的 0.75 倍）。
 */
export function getFullCircleVertices(node: any, port: string): Array<{ x: number; y: number }> {
  const { x, y } = node.getPosition()
  const nodeRadius = 28 // 实体半径
  const nodeCenter = { x: x + nodeRadius, y: y + nodeRadius }
  const circleRadius = nodeRadius * 0.75 // 自环圆的半径（实体的0.75倍）
  const segments = 20 // 更多分段形成更平滑的完整圆

  // 根据端口位置确定自环圆的中心位置（都向外偏移）
  let circleCenterX, circleCenterY, startAngle
  const offset = circleRadius + 8 // 圆心距离节点边缘的距离

  switch (port) {
    case 'top':
      circleCenterX = nodeCenter.x
      circleCenterY = nodeCenter.y - nodeRadius - offset
      startAngle = Math.PI * 0.5 // 从下方（90度）开始，这样圆弧向上外展
      break
    case 'bottom':
      circleCenterX = nodeCenter.x
      circleCenterY = nodeCenter.y + nodeRadius + offset
      startAngle = Math.PI * 1.5 // 从上方（270度）开始，这样圆弧向下外展
      break
    case 'fxL':
    case 'left':
      circleCenterX = nodeCenter.x - nodeRadius - offset
      circleCenterY = nodeCenter.y
      startAngle = 0 // 从右方（0度）开始，这样圆弧向左外展
      break
    default: // fxR, right
      circleCenterX = nodeCenter.x + nodeRadius + offset
      circleCenterY = nodeCenter.y
      startAngle = Math.PI // 从左方（180度）开始，这样圆弧向右外展
      break
  }

  const vertices = []

  // 生成完整圆上的点，从指定角度开始，确保圆弧向外展示
  for (let i = 1; i < segments; i++) {
    const angle = startAngle + (Math.PI * 2 * i) / segments
    vertices.push({
      x: circleCenterX + circleRadius * Math.cos(angle),
      y: circleCenterY + circleRadius * Math.sin(angle)
    })
  }

  return vertices
}
