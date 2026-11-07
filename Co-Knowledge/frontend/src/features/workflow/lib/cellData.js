/**
 * 画布节点「应用配置」的回写。
 *
 * 节点把配置存了两份（见 `docs` 与 `exportGraph()`）：
 *   - `store.data.data.variables` —— 画布那份：`nodeVariables()` 读它来打开抽屉，
 *     `exportGraph()` 保存时也以它为准；
 *   - `store.data.variables` —— 服务端那份（DTO 顶层 `variables`）。
 * 两份必须同时整体换掉。
 *
 * ⚠️ 不要用 `setData(x)` 的默认深合并：X6 内部走 lodash `merge`，
 * **数组按下标合并、旧的尾巴会保留**。删掉的知识库 / 算子会被原样留下，
 * 表现为「应用配置 → 重新打开，全回来了」。必须 `overwrite: true` 整体替换。
 *
 * @param {object} cell X6 节点
 * @param {object} variables 抽屉返回的最新算子配置
 */
export function replaceNodeVariables (cell, variables) {
  const previous = cell.getData() || {}
  cell.setProp('variables', variables)
  cell.setData({
    ...previous,
    type: 'saveData',
    variables
  }, {
    overwrite: true
  })
  return cell
}
