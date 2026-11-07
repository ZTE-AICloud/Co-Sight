/**
 * 工作流发布态 → 可执行动作。
 *
 * 列表行菜单不能用一项 toggle 在「发布 / 取消发布」之间切换：工作流一旦发布过，
 * `publishType` 就变成 1（或保存草稿后的 2），菜单只剩「取消发布」——
 * **没有任何入口能把改完的草稿重新发布出去**，对话测试只能一直跑旧快照。
 *
 * 这里把「发布态 → 菜单动作」抽成纯函数，组件与单测共用同一份判定。
 */

/** 后端 `kb_workflow.publish_type` 的三个取值（见 workflow/service.py）。 */
export const PUBLISH_TYPE = {
  UNPUBLISHED: 0,
  PUBLISHED: 1,
  /** 发布后又保存过草稿：线上仍是旧快照，需要重新发布。 */
  MODIFIED_AFTER_PUBLISH: 2
}

/**
 * 行菜单规则（模板按这两个常量分支，避免再写一次魔法数字）：
 *
 * * 未发布（0）→ 只显示「发布」
 * * 已发布 / 发布后修改（1/2）→ 「重新发布」+「取消发布」两个**独立**动作
 */

/**
 * 批量发布的目标：未发布（0）与「发布后修改」（2）。
 *
 * 已发布且未修改（1）不需要再发一次；发布后修改的必须包含，否则批量发布
 * 对「改过草稿」的工作流永远是空操作。
 */
export function isBatchPublishTarget (row) {
  return [PUBLISH_TYPE.UNPUBLISHED, PUBLISH_TYPE.MODIFIED_AFTER_PUBLISH]
    .includes(Number(row?.publishType))
}
