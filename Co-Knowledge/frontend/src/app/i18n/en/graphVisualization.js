/**
 * 图谱可视化组件文案。
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 */
export default {
  // 新增实体成功提示
  // 添加关系抽屉里的关系方向下拉选项
  direction: {
    fromTo: 'From {source} to {target}',
    fromNewToCurrent: 'From new entity to current entity',
    fromCurrentToNew: 'From current entity to new entity'
  }
}
