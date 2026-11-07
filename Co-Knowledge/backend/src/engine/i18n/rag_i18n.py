i18n = {
    'required_param_missing': {
        'zh': '参数非法：{}，不能为空或null。',
        'en': 'Invalid parameter: {}, cannot be empty or null.'
    },
    'request-knowledgebase-failed': {
        'zh': '从知识库获取相关知识信息失败，请稍后重试。',
        'en': 'Retrieve related context from knowledegebase failed, please try again later.'
    },
    'request-knowledge-graph-failed': {
        'zh': '从图谱知识库检索失败，请检查该图谱库是否已完成抽取，以及检索器是否配置了向量模型。',
        'en': 'Knowledge graph retrieval failed. Check that the graph has been extracted and '
              'that the retriever has an embedding model configured.'
    },
    'request-llm-gateway-failed': {
        'zh': '使用大模型进行RAG总结失败，请稍后重试',
        'en': 'Synthesize response of RAG by LLM failed, please try again later'
    },
    'no-llm-available': {
        'zh': '当前环境上无可用大模型，请注册大模型。',
        'en': 'No LLM is available in the current environment, please register LLM.'
    },
    'knowledgebase-not-imported': {
        'zh': '环境上未导入知识库，请导入知识库后再试。',
        'en': 'The knowledge base is not imported in the environment, please import the knowledge base and try again.'
    },
    'bad-status-code': {
        'zh': '请求{}失败，请稍后重试。',
        'en': 'Request service {} failed, please try again.'
    },
    'only-support-sequential-hybrid': {
        'zh': '指定知识库进行问答，仅支持顺序和混合检索，请检查。',
        'en': 'Specify the knowledge base for Q&A, only supporting sequential and hybrid retrieval. Please check.'
    },
    'question_not_match_desc_info':{
        'zh': '根据当前信息无法回答，请细化知识检索的“desc_info”字段后重试。',
        'en': 'Unable to answer based on current information, please refine the "desc_info" field of the knowledge retrieval and try again.'
    },
    'request-llm-failed': {
        'zh': '与大模型通讯失败，请检查模型适配层服务是否正常。',
        'en': 'Communication with the LLM has failed, please check whether the model gateway is normal.'
    },
    'question_length_over_limit': {
        'zh': '问题长度限制为{}，当前输入的问题长度为{}，请检查。',
        'en': 'The question length is limited to {}, but the current input question length is {}. Please verify.'
    },
    'parameter_length_limit_illegal': {
        'zh': '非法字段：{}，取值必须为小于{}的正整数。',
        'en': 'Invalid field: {}, the value must be a positive integer less than {}.'
    },
}

# ---------------------------------------------------------------------------
# 编排运行时新增的错误码
# 一律「显式失败」：宁可返回错误码，也不返回一个看起来成功、其实什么都没有的结果。
# ---------------------------------------------------------------------------
i18n.update({
    'llm-empty-content': {
        'zh': '大模型返回了空内容（finish_reason={}），无法继续。请检查模型端点与 max_tokens 配置。',
        'en': 'The model returned empty content (finish_reason={}). Check the model endpoint and max_tokens.'
    },
    'llm-empty-content-truncated': {
        'zh': '大模型只输出了推理内容就被 token 预算截断（finish_reason=length），没有可用的答案。'
              '推理模型需要更大的 max_tokens，当前配置为 {}。',
        'en': 'The model only produced reasoning content and was cut off by the token budget '
              '(finish_reason=length), leaving no answer. Reasoning models need a larger max_tokens; '
              'current setting is {}.'
    },
    'request-model-gateway-failed': {
        'zh': '调用生成模型失败，请稍后重试。',
        'en': 'Call the generation model failed, please try again later.'
    },
    'published-workflow-not-found': {
        'zh': '知识检索 {} 没有已发布的版本，请先在画布上保存并发布。',
        'en': 'Knowledge retrieval {} has no published version; save and publish it first.'
    },
    'workflow-has-no-operator': {
        'zh': '已发布的知识检索 {} 里没有任何算子，无法执行。',
        'en': 'The published knowledge retrieval {} has no operator, so it cannot run.'
    },
    'rerank-endpoint-not-configured': {
        'zh': '当前部署没有配置重排（rerank）端点，ExternalModelReranker 算子无法工作。',
        'en': 'No rerank endpoint is configured in this deployment, so ExternalModelReranker cannot work.'
    },
    'rerank-model-not-configured': {
        'zh': '画布选择的重排模型 {} 未在模型注册表中配置，请重新选择后再试。',
        'en': 'The rerank model {} selected on the canvas is not configured in the model registry. '
              'Pick another model and try again.'
    },
})

i18n.update({
    'web-search-not-supported': {
        'zh': '当前版本不支持联网检索（enableWebSearch）。',
        'en': 'Web search (enableWebSearch) is not supported in this version.'
    },
})

i18n.update({
    'workflow-config-invalid': {
        'zh': '知识检索 {} 的配置形状不合法（{}），无法执行。请在画布上检查算子配置后重新发布。',
        'en': 'Knowledge retrieval {} has an invalid config shape ({}), so it cannot run. '
              'Check the operators on the canvas and publish again.'
    },
})
