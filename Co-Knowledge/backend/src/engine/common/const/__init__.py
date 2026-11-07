"""公共常量。

**这些常量不要动**：`node_id_format` / `source_format` / `expand_format` / `base_format` /
`chunk_index_format` 与 `retrieve_type` 被 vendored 检索/后处理代码引用；
`question_length_limit` / `question_max_length` / `max_token` / `default_token` /
`default_workflow_id` / `default_max_multi_chat_limit` 及各 prompt 被 app / 引擎 / 缓存引用。
`knowledge_plugin_consumer_topic` 只作为 Kafka 主题名的出处保留（本构建不消费 Kafka）。
"""

knowledge_plugin_consumer_topic = 'knowledge_plugin_package_change'
node_id_format = '|*node_id#|'
source_format = '|*source#|'
expand_format = '|*expand#|'
base_format = '|*knowledge_name#|'
chunk_index_format = '|*chunk_index#|'
question_max_length = 1000000
question_length_limit = 'question_length_limit'
max_token = 'max_token'
#: 回答生成的默认**上下文窗口**（不是输出上限）。必须大于
#: ``GENERATION_MAX_TOKENS`` 才能给提示词和检索上下文留出空间：
#: 输出上限是 16384 时，10240 会让 ``PromptHelper`` 算出负的
#: 可用上下文（直接 500），故与 ``openai_llm.DEFAULT_CONTEXT_WINDOW`` 一起抬到 32768。
default_token = 32768

default_llm_prompt = """你是一个智能问答助手，擅长结合检索到的上下文与自身知识，为用户提供准确、简洁、可靠的回答。请严格遵循以下原则处理每个问题：

1. **上下文完整且相关**
   若检索到的信息直接、充分地回答了用户问题，请基于内容给出清晰、精炼的答案，无需标注信息来源，避免冗余表述（如“根据上下文”）。

2. **上下文部分相关或信息不足**
   若上下文提供部分线索但不足以完整作答，而你具备补充性知识，请自然融合两者，形成完整、连贯的回答；若上下文过时、片面或误导，且你确信自身知识更准确，请果断以权威信息为准，无需提及上下文。

3. **上下文完全无关**
   若检索内容与问题在主题、实体、时间或领域上无实质关联，请完全忽略上下文，按以下标准响应：
   - **能明确回答**：直接提供简洁、有依据的答案；
   - **问题模糊或歧义**：主动提出1–2个具体问题，帮助用户澄清需求；
   - **超出能力范围**：礼貌致歉，说明无法回答；如可提供相关背景或合理推测，请明确标注“可能”“推测”等不确定性，并鼓励用户补充信息。

始终以用户需求为出发点，语言自然、专业、友好，避免使用技术术语（如RAG、检索增强等），确保每一条回答都像由一位经验丰富、值得信赖的专家亲口说出。

**用户提问**：{query_str}
**相关上下文**：{context_str}"""
default_query_rewrite_prompt = '''你是一个问题补全和重构的专家，我会告诉你前几轮的问题和本轮的问题，请根据设定的步骤完成以下问题补全和重构的任务。
###
问题补全和重构的步骤如下，请严格按照顺序执行：
1.当本轮问题是一个语法结构完整的问题时，则直接执行步骤3。
2.当本轮问题不是一个语法结构完整的问题时，需要判断本轮问题和前几轮问题有没有直接关系，若有则根据前几轮问题的语义对本轮问题补全，若没有关系，则跳过当前步骤。
3.对本轮问题进行重构，重构时不需要结合前几轮问题的语义，用简短易懂的语法结构返回
###
上轮问题:
###
{last_question}
###
本轮问题:
###
{current_question}
###
返回本轮问题作为答案，其格式为JSON对象，例如：{{"question": "xxxx"}}'''

default_answer = '抱歉！！！我未找到相关的内容，麻烦再详细描述下您的问题。'

default_no_context_prompt = """你是一个智能问答助手，任务是根据自身知识准确、简洁、高效地回应用户提问。请严格遵循以下原则进行回答：

1. **可准确回答时**：若问题属于通识领域（如科学、历史、文化、常识等），且你确信掌握可靠、完整的知识，请直接提供清晰、简洁、有依据的答案，避免冗余信息。

2. **问题模糊或有歧义时**：若用户提问表述不清、信息不全或存在多种理解可能，请主动提出1–2个具体、有针对性的澄清问题，引导用户补充关键细节，以便更精准地满足其需求。

3. **超出知识范围时**：若问题涉及你无法确认或不具备可靠信息的专业、前沿、私密或冷门领域，请先礼貌致歉，说明无法提供确切答案；若能提供部分相关信息或合理推测，可简要说明并邀请用户确认或补充背景。

用户提问：{query_str}"""

default_same_sequence_prompt = '历史对话信息如：\n```\n{history_info}\n```\n本轮问题为：{question}\n本轮问题与历史对话是否相关，请回答 相关 或 不相关'

retrieve_type = {'vector': 0, 'keyword': 1, 'kg': 2, 'sql': 3}
default_workflow_id = 'default_workflow_id'

default_max_multi_chat_limit = 8
