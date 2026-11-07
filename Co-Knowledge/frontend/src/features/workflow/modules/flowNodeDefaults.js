/**
 * 新拖入画布的业务节点默认变量。
 *
 * 与卡片 Node.vue 共用同一份定义：新增节点时父组件先把 variables 放进节点，
 * 卡片就不会再走「emit(initCardHandle) → 父组件回写」的异步路径，添加后可以
 * 立即打开配置抽屉。
 */
import {
  preretrieverDefaultPrompt,
  responsesynthesizerDefaultPrompt,
  default_RSS_no_context_prompt
} from '@/features/workflow/lib/workflow'
import {
  EXTERNAL_MODEL_RERANKER_OPERATOR,
  EXTERNAL_MODEL_RERANKER_PACKAGE
} from '@/features/workflow/lib/externalModelReranker'

const factories = {
  PRE_RETRIEVER: () => ({
    preretriever: [
      {
        id: 1,
        package: 'core.rag.pre_retriever.query_transform.query_rewrite',
        operator: 'LLMQueryRewriter',
        kwargs: {
          llm: '',
          prompt: preretrieverDefaultPrompt,
          multi_chat_limit: 0
        }
      }
    ]
  }),
  RETRIEVER: () => ({
    retriever: [
      {
        id: 1,
        package: 'core.rag.retriever.vector_retriever',
        operator: 'VectorRetriever',
        kwargs: {
          strategy: 0,
          embedding: '',
          knowledge_info_list: [
            {
              knowledge_base_name: [],
              priority: 10,
              top_k: 8,
              score: 0.3
            }
          ],
          desc_info: ''
        }
      }
    ]
  }),
  POST_RETRIEVER: () => ({
    postretriever: [
      {
        id: 2,
        package: EXTERNAL_MODEL_RERANKER_PACKAGE,
        operator: EXTERNAL_MODEL_RERANKER_OPERATOR,
        kwargs: {
          // 空串 = 跟随部署默认重排模型；抽屉里可显式改选注册表中的模型
          model: '',
          top_n: 4
        }
      }
    ]
  }),
  RESPONSE_SYNTHESIZER: () => ({
    responsesynthesizer: [
      {
        id: 1,
        package: 'core.rag.response_synthesizer.simple_summarizer',
        operator: 'RagSimpleSummarizer',
        kwargs: {
          'generator-config': [
            {
              llm: '',
              prompt: responsesynthesizerDefaultPrompt,
              top_k: 8,
              knowledge_base_name: [],
              no_context_prompt: default_RSS_no_context_prompt,
              temperature: 0.01
            }
          ]
        }
      }
    ]
  })
}

/** 返回一份全新的默认 variables；固定节点（QUERY/RESPONSE）返回 null。 */
export function createDefaultVariables (componentType) {
  const factory = factories[componentType]
  return factory ? factory() : null
}
