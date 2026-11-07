/**
 * 知识图谱工作台文案。
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 */
export default {
  // 生成图谱对话框（GenerateGraphDialog.vue）
  // 上传校验里兜底的支持格式清单（CreateKnowledgeGraph.vue）
  defaultFileFormats: 'pdf、doc、docx、txt、md、xlsx、xls、csv',
  // 兜底文案（失败详情、错误消息里缺字段时用）
  common: {
    unknownFile: '未知文件',
    unknownError: '未知错误'
  },
  // 表单校验
  form: {
    descriptionMaxLength: '描述不能超过1000个字符'
  },
  // schema 数据校验（utils/schemaMapper.js；错误串由 KnowledgeGraphDetail 拼进 $message 展示）
  schemaValidation: {
    empty: 'schemaInfo数据为空',
    entitiesInvalid: 'entities字段缺失或格式不正确',
    edgesInvalid: 'edges字段缺失或格式不正确',
    entityMissingType: '实体{index}缺少entity_type字段',
    edgeMissingType: '边{index}缺少edge_type字段',
    processFailed: '验证过程出错: {message}'
  }
}
