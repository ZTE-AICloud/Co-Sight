/**
 * 知识库/检索/模型管理工作区页面文案。
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 */
export default {
  // 知识检索页（views/retrieve/RetrievePage.vue）
  retrieve: {
    title: '知识检索',
    subtitle: '选择知识库 → 输入问题 → 查看带来源的检索片段',
    selectKb: '选择知识库',
    typeVector: '向量',
    typeKeyword: '关键词',
    questionPlaceholder: '输入问题，例如：什么是向量数据库',
    search: '检索',
    /** 结果区统计行：命中 {count} 条 · 提问「{question}」 · {type}路 */
    meta: '命中 {count} 条 · 提问「{question}」 · {type}路',
    /** 空状态与查询无命中的 toast 共用（同一件事必须同一句话） */
    empty: '没有检索到结果',
    sourceLabel: '来源：',
    loadKbListFailed: '加载知识库列表失败：',
    searchFailed: '检索失败：'
  },
  // 知识图谱编辑器（views/kBase/components/GraphEditor/**）
  graphEditor: {
    /**
     * 节点选择弹窗标题。
     * ⚠️ 不能复用 `modules.kb.selectEntityType`：kb.js 里这个键名出现了两次
     * （'选择实体类型' 与 '请选择实体类型'），对象字面量后出现者赢，实际渲染的是
     * 「请选择实体类型」—— 复用会让本弹窗标题多一个「请」字。
     */
    selectEntityType: '选择实体类型',
    nodeTypeEntity: '实体',
    nodeTypeFault: '故障',
    nodeTypeEvent: '事件',
    nodeTypeResource: '资源',
    nodeTypeRootCause: '根因',
    nodeTypePlan: '计划',
    nodeTypeExamItem: '检查项',
    nodeTypeEntityDesc: '基础实体节点',
    nodeTypeFaultDesc: '故障类型节点',
    nodeTypeEventDesc: '事件类型节点',
    nodeTypeResourceDesc: '资源类型节点',
    nodeTypeRootCauseDesc: '根因分析节点',
    nodeTypePlanDesc: '解决方案节点',
    nodeTypeExamItemDesc: '检查项目节点',
    /** 关系方向（双向共用 modules.kb.directionBoth，这里只补缺的两个） */
    directionSelfLoop: '自环',
    directionOneWay: '单向',
    /** 属性面板在既非实体也非关系时的标题（modules.kb 里没有 propertyConfig） */
    propertyConfig: '属性配置'
  },
  // 文档知识库建库页及其上传/数据集列表（docKnowledgeLibrary、kBase/addData）
  docKb: {
    datasetListLoadFailed: '加载数据集列表失败',
    fileListLoadFailed: '加载文件列表失败',
    /** 同尺寸后缀列表的连接符（提示文案里形如 txt、md、pdf） */
    extListSeparator: '、'
  },
  // 切片编辑弹窗（views/kBase/UpdateSplitDataDialog.vue）
  splitDataDialog: {
    contentRequired: '请输入切片内容'
  },
  // 资产任务页（views/kBase/AssetTaskManage.vue）
  assetTask: {
    publishFailed: '发布失败'
  }
}
