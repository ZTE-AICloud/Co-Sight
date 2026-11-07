/**
 * 画布算子里的知识库名数组规范化。
 *
 * 背景：`knowledge_info_list[].knowledge_base_name` 里会存进
 * **同一个 tableName 的重复值**（重复保存遗留）。重复值在 el-select 多选上
 * 的表现是：点某个标签的 × 只删掉其中一份，同名标签原地不动 —— 看起来像「删不掉」；
 * 而 `collapse-tags` 又把后面的标签折成 `+N`，用户既看不到选了什么，也无法逐个删除。
 *
 * 加载与保存各收敛一次：重复值不再进 UI，也不再写回后端。
 */

/**
 * 知识库名去重（保序）。
 *
 * - 字符串按单元素数组处理；
 * - 其余非数组返回空数组，调用方按「没选」处理；
 * - 只丢掉 `null` / `undefined` / 空串，**不做类型转换**：数字形态的 pkId 转成
 *   字符串会让后端的名称匹配对不上。
 *
 * @param {unknown} names 原始库名（数组 / 字符串 / 其它）
 * @returns {Array<string|number>} 去重后的库名，保持首次出现的顺序
 */
export function uniqueKbNames (names) {
  if (typeof names === 'string') {
    return names ? [names] : []
  }
  if (!Array.isArray(names)) {
    return []
  }
  return [...new Set(names.filter(name => name !== null && name !== undefined && name !== ''))]
}
