/**
 * 知识图谱工作台文案。
 *
 * 同一个 key 必须在 zh/ 与 en/ 两侧同时存在（tests/unit/i18n.consistency.spec.js 会断言）。
 */
export default {
  // Generate graph dialog (GenerateGraphDialog.vue)
  defaultFileFormats: 'pdf, doc, docx, txt, md, xlsx, xls, csv',
  common: {
    unknownFile: 'Unknown file',
    unknownError: 'Unknown error'
  },
  form: {
    descriptionMaxLength: 'Description cannot exceed 1000 characters'
  },
  schemaValidation: {
    empty: 'schemaInfo data is empty',
    entitiesInvalid: 'The entities field is missing or malformed',
    edgesInvalid: 'The edges field is missing or malformed',
    entityMissingType: 'Entity {index} is missing the entity_type field',
    edgeMissingType: 'Edge {index} is missing the edge_type field',
    processFailed: 'Validation failed: {message}'
  }
}
