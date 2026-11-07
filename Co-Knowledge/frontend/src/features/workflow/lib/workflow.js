// 编排卡片宽 264（端口与几何见 utils/flowGeometry.js）
export const DEFAULT_CUSTOM_NODE_WIDTH = 264
export const DEFAULT_CUSTOM_NODE_HEIGHT = 320

export const DEFAULT_SIDE_BAR_NODE_WIDTH = 270
export const DEFAULT_SIDE_BAR_NODE_HEIGHT = 40

export const DEFAULT_QUERY_NODE_HEIGHT = 140

export const QUERY_NODE_SHAPE = 'QUERY'
export const RESPONSE_NODE_SHAPE = 'RESPONSE'

export const OUTPUT_INTERVAL = 29

export const Preretriever = {
  input: {
    x: 0,
    y: 160
  },
  output: {
    x: 264,
    y: 160
  },
  output_with_1_incoming_edge: {
    y: 160
  }
}

// export const Retriever = {
//   input: {
//     x: 28,
//     y: 141
//   },
//   output: {
//     x: 214,
//     y: 196
//   },
//   output_with_1_incoming_edge: {
//     y: 228
//   }
// }

export const Retriever = {
  input: {
    x: 0,
    y: 160
  },
  output: {
    x: 264,
    y: 160
  },
  output_with_1_incoming_edge: {
    y: 160
  }
}

export const Postretriever = {
  input: {
    x: 0,
    y: 160
  },
  output: {
    x: 264,
    y: 160
  },
  output_with_1_incoming_edge: {
    y: 160
  }
}

export const ResponseSynthesizer = {
  input: {
    x: 0,
    y: 160
  },
  output: {
    x: 264,
    y: 160
  },
  output_with_1_incoming_edge: {
    y: 160
  }
}



// 英文提示词
export const preretrieverDefaultPromptEn = "You are an expert in question completion and rephrasing. I will provide you with the previous question and the current question, and you must complete the task of question completion and restructuring following the steps outlined below.\n\n###  \nSteps for question completion and restructuring (please follow these steps strictly in order):  \n1. If the current question is already a grammatically complete sentence, proceed directly to Step 3.  \n2. If the current question is not a grammatically complete sentence, determine whether it is semantically related to the previous question. If it is related, complete the current question based on the meaning of the previous one. If there is no connection, skip this step.  \n3. Rephrase the current question without considering the semantics of the previous question, returning it as a concise and clear grammatical structure.\n###  \n\nPrevious Question:  \n###  \n{last_question}  \n###  \n\nCurrent Question:  \n###  \n{current_question}  \n###  \n\nReturn the current question as the result in JSON format, for example: {{\"question\": \"xxxx\"}}";

export const responsesynthesizerDefaultPromptEn = "You are an intelligent Q&A assistant skilled at combining retrieved context with your own knowledge to deliver accurate, concise, and reliable responses. Please strictly follow these principles for every query:\n\n1. **Context is complete and relevant**  \n   If the retrieved information directly and fully answers the user’s question, provide a clear, concise answer based on it—do not cite sources or use redundant phrases like “according to the context.”\n\n2. **Context is partial or insufficient**  \n   If the context offers some clues but not enough to fully answer, and you possess complementary knowledge, seamlessly integrate both into a complete, coherent response. If the context is outdated, biased, or misleading—and you are confident your own knowledge is more accurate—prioritize your authoritative knowledge, and do not mention the context at all.\n\n3. **Context is irrelevant**  \n   If the retrieved content has no meaningful connection to the question in terms of topic, entities, time, or domain, ignore it entirely and respond as follows:  \n   - **Can answer clearly**: Provide a concise, well-supported answer directly.  \n   - **Question is ambiguous**: Ask 1–2 specific, targeted questions to help the user clarify their needs.  \n   - **Beyond your capability**: Politely decline, explaining you cannot provide a reliable answer. If you can offer related background or a reasonable inference, clearly label it as “possible,” “likely,” or “possibly,” and invite the user to provide additional details.\n\nAlways prioritize the user’s intent. Use natural, professional, and friendly language—avoid technical jargon (e.g., RAG, retrieval-augmented). Every response should sound as if it came from a knowledgeable, trustworthy expert.  \n\n**User query**: {query_str}  \n**Relevant context**: {context_str}";

export const LLMDefaultPromptEn = "Here are some choices. They are provided in a numbered list (from 1 to {num_choices}), where each item in the list corresponds to a summary.\n---------------------\n{context_list}\n---------------------\nUsing only the above choices and not prior knowledge, return the choice most relevant to the question \"{query_str}.\"";

export const default_RSS_no_context_promptEn = "You are an intelligent Q&A assistant tasked with accurately, concisely, and efficiently responding to user inquiries. Please strictly adhere to the following principles when answering:\n\n1. **When able to answer accurately**: If the question falls within the realm of general knowledge (e.g., science, history, culture, common sense) and you are confident in possessing reliable, complete knowledge, provide a clear, concise, and evidence-based answer directly, avoiding unnecessary elaboration.\n\n2. **When the question is ambiguous or unclear**: If the user’s query is poorly phrased, lacks sufficient information, or admits multiple interpretations, proactively ask 1–2 specific, targeted clarification questions to guide the user in providing essential details, enabling a more precise response.\n\n3. **When beyond your knowledge scope**: If the question involves a professional, cutting-edge, private, or obscure topic for which you lack confirmed or reliable information, politely apologize and state that you cannot provide a definitive answer. If you can offer partial relevant information or a reasonable inference, briefly indicate this and invite the user to confirm or provide additional context.\n\nUser query: {query_str}";


// 中文提示词
const preretrieverDefaultPromptZh = '你是一个问题补全和重构的专家，我会告诉你上轮的问题和本轮的问题，请根据设定的步骤完成以下问题补全和重构的任务。\n    ###\n    问题补全和重构的步骤如下，请严格按照顺序执行：\n    1.当本轮问题是一个语法结构完整的问题时，则直接执行步骤3。\n    2.当本轮问题不是一个语法结构完整的问题时，需要判断本轮问题和上轮问题有没有直接关系，若有则根据上轮问题的语义对本轮问题补全，若没有关系，则跳过当前步骤。\n    3.对本轮问题进行重构，重构时不需要结合上轮问题的语义，用简短易懂的语法结构返回\n    ###\n    上轮问题:\n    ###\n    {last_question}\n    ###\n    本轮问题:\n    ###\n    {current_question}\n    ###\n    返回本轮问题作为答案，其格式为JSON对象，例如：{{\"question\": \"xxxx\"}}';

const responsesynthesizerDefaultPromptZh = '你是一个智能问答助手，擅长结合检索到的上下文与自身知识，为用户提供准确、简洁、可靠的回答。请严格遵循以下原则处理每个问题：\n\n1. **上下文完整且相关**\n   若检索到的信息直接、充分地回答了用户问题，请基于内容给出清晰、精炼的答案，无需标注信息来源，避免冗余表述（如“根据上下文”）。\n\n2. **上下文部分相关或信息不足**\n   若上下文提供部分线索但不足以完整作答，而你具备补充性知识，请自然融合两者，形成完整、连贯的回答；若上下文过时、片面或误导，且你确信自身知识更准确，请果断以权威信息为准，无需提及上下文。\n\n3. **上下文完全无关**\n   若检索内容与问题在主题、实体、时间或领域上无实质关联，请完全忽略上下文，按以下标准响应：\n   - **能明确回答**：直接提供简洁、有依据的答案；\n   - **问题模糊或歧义**：主动提出1–2个具体问题，帮助用户澄清需求；\n   - **超出能力范围**：礼貌致歉，说明无法回答；如可提供相关背景或合理推测，请明确标注“可能”“推测”等不确定性，并鼓励用户补充信息。\n\n始终以用户需求为出发点，语言自然、专业、友好，避免使用技术术语（如RAG、检索增强等），确保每一条回答都像由一位经验丰富、值得信赖的专家亲口说出。\n\n**用户提问**：{query_str}\n**相关上下文**：{context_str}';

const LLMDefaultPromptZh = '以下是一些选择。它们以编号列表的形式提供（从1到{num_choices}），其中列表中的每一项对应一个摘要。\n---------------------\n{context_list}\n---------------------\n只使用上述选择而不使用先前的知识，返回与问题"{query_str}"最相关的选择。';

const default_RSS_no_context_promptZh = '你是一个智能问答助手，任务是根据自身知识准确、简洁、高效地回应用户提问。请严格遵循以下原则进行回答：\n\n1. **可准确回答时**：若问题属于通识领域（如科学、历史、文化、常识等），且你确信掌握可靠、完整的知识，请直接提供清晰、简洁、有依据的答案，避免冗余信息。\n\n2. **问题模糊或有歧义时**：若用户提问表述不清、信息不全或存在多种理解可能，请主动提出1–2个具体、有针对性的澄清问题，引导用户补充关键细节，以便更精准地满足其需求。\n\n3. **超出知识范围时**：若问题涉及你无法确认或不具备可靠信息的专业、前沿、私密或冷门领域，请先礼貌致歉，说明无法提供确切答案；若能提供部分相关信息或合理推测，可简要说明并邀请用户确认或补充背景。\n\n用户提问：{query_str}';

// 获取语言信息的函数
const getCurrentLanguage = () => {
  try {
    // 从 localStorage 获取语言设置
    const languageOption = localStorage.getItem('language-option');
    if (languageOption) {
      const lang = JSON.parse(languageOption);
      return lang === 'zh-CN' ? 'zh' : 'en';
    }

    // 如果 localStorage 中没有，检查环境变量
    const envLang = process.env.VUE_APP_LANG;
    if (envLang) {
      return envLang === 'zh-CN' ? 'zh' : 'en';
    }

    // 默认返回中文
    return 'zh';
  } catch (error) {
    console.error('Error getting language:', error);
    return 'zh'; // 默认中文
  }
};


const getI18nPrompt = (zhPrompt, enPrompt) => {
  const currentLang = getCurrentLanguage();
  return currentLang === 'zh' ? zhPrompt : enPrompt;
};

export const preretrieverDefaultPrompt = getI18nPrompt(preretrieverDefaultPromptZh, preretrieverDefaultPromptEn);
export const responsesynthesizerDefaultPrompt = getI18nPrompt(responsesynthesizerDefaultPromptZh, responsesynthesizerDefaultPromptEn);
export const LLMDefaultPrompt = getI18nPrompt(LLMDefaultPromptZh, LLMDefaultPromptEn);
export const default_RSS_no_context_prompt = getI18nPrompt(default_RSS_no_context_promptZh, default_RSS_no_context_promptEn);


export const mockKBData = {
  id: '工作流测试',
  name: '工作流测试'
}

export const defaultTopkMapper = {
  VectorRetriever: {
    BlendedQueryEngine: 15,
    SequentialQueryEngine: 30,
    ConditionalQueryEngine: 8
  },
  KeywordRetriever: {
    BlendedQueryEngine: 15,
    SequentialQueryEngine: 8,
    ConditionalQueryEngine: 8
  },
  FusionRetriever: {
    BlendedQueryEngine: 30,
    SequentialQueryEngine: 8,
    ConditionalQueryEngine: 8
  },
  KnowledgeGraphRetriever: {
    BlendedQueryEngine: 15,
    SequentialQueryEngine: 8,
    ConditionalQueryEngine: 8
  },
  LLMReranker: {
    BlendedQueryEngine: 5,
    SequentialQueryEngine: 5,
    ConditionalQueryEngine: 4
  },
  ExternalModelReranker: {
    BlendedQueryEngine: 5,
    SequentialQueryEngine: 5,
    ConditionalQueryEngine: 4
  },
  RagSimpleSummarizer: {
    BlendedQueryEngine: 5,
    SequentialQueryEngine: 5,
    ConditionalQueryEngine: 8
  }
}

export const default_BGM_score = 0;
