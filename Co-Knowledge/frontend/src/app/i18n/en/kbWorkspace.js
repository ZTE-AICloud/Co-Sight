/**
 * 知识库/检索/模型管理工作区页面文案。
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 */
export default {
  // 知识检索页（views/retrieve/RetrievePage.vue）
  retrieve: {
    title: 'Knowledge Retrieval',
    subtitle: 'Select a knowledge base → enter a question → view retrieved chunks with sources',
    selectKb: 'Select a knowledge base',
    typeVector: 'Vector',
    typeKeyword: 'Keyword',
    questionPlaceholder: 'Enter a question, e.g. what is a vector database',
    search: 'Search',
    /** 结果区统计行：{count} hits · query "{question}" · {type} */
    meta: '{count} hits · query "{question}" · {type}',
    /** 空状态与查询无命中的 toast 共用（同一件事必须同一句话） */
    empty: 'No results found',
    sourceLabel: 'Source: ',
    loadKbListFailed: 'Failed to load knowledge base list: ',
    searchFailed: 'Search failed: '
  },
  // 知识图谱编辑器（views/kBase/components/GraphEditor/**）
  graphEditor: {
    /**
     * 节点选择弹窗标题。
     * ⚠️ 不能复用 `modules.kb.selectEntityType`：kb.js 里这个键名出现了两次
     * （'Select Entity Type' 与 'Please select entity type'），对象字面量后出现者赢，
     * 实际渲染的是「Please select entity type」。
     */
    selectEntityType: 'Select Entity Type',
    nodeTypeEntity: 'Entity',
    nodeTypeFault: 'Fault',
    nodeTypeEvent: 'Event',
    nodeTypeResource: 'Resource',
    nodeTypeRootCause: 'Root Cause',
    nodeTypePlan: 'Plan',
    nodeTypeExamItem: 'Check Item',
    nodeTypeEntityDesc: 'Basic entity node',
    nodeTypeFaultDesc: 'Fault type node',
    nodeTypeEventDesc: 'Event type node',
    nodeTypeResourceDesc: 'Resource type node',
    nodeTypeRootCauseDesc: 'Root cause analysis node',
    nodeTypePlanDesc: 'Solution node',
    nodeTypeExamItemDesc: 'Check item node',
    /** 关系方向（双向共用 modules.kb.directionBoth，这里只补缺的两个） */
    directionSelfLoop: 'Self-loop',
    directionOneWay: 'One-way',
    /** 属性面板在既非实体也非关系时的标题（modules.kb 里没有 propertyConfig） */
    propertyConfig: 'Property Configuration'
  },
  // 文档知识库建库页及其上传/数据集列表（docKnowledgeLibrary、kBase/addData）
  docKb: {
    datasetListLoadFailed: 'Failed to load dataset list',
    fileListLoadFailed: 'Failed to load file list',
    /** 同尺寸后缀列表的连接符（提示文案里形如 txt、md、pdf） */
    extListSeparator: ', '
  },
  // 切片编辑弹窗（views/kBase/UpdateSplitDataDialog.vue）
  splitDataDialog: {
    contentRequired: 'Please enter chunk content'
  },
  // 资产任务页（views/kBase/AssetTaskManage.vue）
  assetTask: {
    publishFailed: 'Publish failed'
  }
}
