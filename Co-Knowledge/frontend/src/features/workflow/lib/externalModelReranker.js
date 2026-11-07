// 外部重排模型算子的逻辑 ID 与包名。
//
// 算子类名是**持久化在画布 JSON / 已发布快照里的逻辑 ID**，改名字必须同步
// 后端 `default_packages_info` 与 `workflow/validation.py`。

export const EXTERNAL_MODEL_RERANKER_OPERATOR = 'ExternalModelReranker'
export const EXTERNAL_MODEL_RERANKER_PACKAGE =
  'core.rag.post_retriever.external_model_reranker'

export function isExternalModelReranker (operator) {
  return operator?.operator === EXTERNAL_MODEL_RERANKER_OPERATOR
}
