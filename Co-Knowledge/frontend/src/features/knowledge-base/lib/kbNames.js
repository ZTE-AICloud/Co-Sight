/**
 * 画布卡片上的知识库名称映射。
 *
 * 卡片只显示来源摘要（`企业知识图谱 · Top 5`），但后端节点里存的是 tableName
 * （`graph_xxx` / `feature_xxx`）。这里把 `getAllKBList` 的结果缓存成模块级
 * Map，多个检索器卡片共用一次请求；拿不到时回落到短名（图谱库显示「图谱知识库」）。
 */
import { getAllKBList } from '@/features/workflow/api/workflow'

let kbNamePromise = null
let kbNameMap = {}

function addOption (map, value, label) {
  if (value && label) {
    map[value] = label
    map[String(value).split('|#|')[0]] = label
  }
}

function buildMap (response) {
  const map = {}
  // 两种形状：`{running, dev}`（allStatusKbase 原始返回）与分组后的 `[{label, options}]`
  if (response && !Array.isArray(response) && (response.running || response.dev)) {
    ;[...(response.running || []), ...(response.dev || [])].forEach(item => {
      addOption(map, item?.tableName, item?.name)
    })
    return map
  }
  const groups = Array.isArray(response) ? response : []
  groups.forEach(group => {
    (group?.options || []).forEach(option => {
      addOption(map, option?.value, option?.label)
    })
  })
  return map
}

/** 预加载一次知识库名称（失败时保持空表，卡片走短名）。 */
export function loadKbNames () {
  if (!kbNamePromise) {
    kbNamePromise = Promise.resolve()
      .then(() => getAllKBList())
      .then(response => {
        kbNameMap = buildMap(response)
        return kbNameMap
      })
      .catch(() => {
        kbNamePromise = null
        return kbNameMap
      })
  }
  return kbNamePromise
}

/** 同步读取已缓存的显示名；未加载或未命中返回空串。 */
export function kbDisplayName (rawName) {
  if (!rawName) {
    return ''
  }
  return kbNameMap[rawName] || kbNameMap[String(rawName).split('|#|')[0]] || ''
}
