"""编排层默认 prompt —— 与 llama-index-core 0.10.31 保持一致。

来源与许可：llama-index-core 0.10.31（MIT License, Copyright (c) Jerry Liu；
完整许可文本见仓库根目录 `THIRD-PARTY-NOTICES.md`）。下列文本按原样复制，**不得改写**：
它们是送进模型的提示词，任何一个字符的漂移都会改变模型输出，
而 `tools/verify/verify-baseline-fingerprint.py` 会做对比。

对应关系（源路径均相对 llama-index-core/llama_index/core/）：
  * DEFAULT_CHOICE_SELECT_PROMPT_TMPL  <- prompts/default_prompts.py:DEFAULT_CHOICE_SELECT_PROMPT_TMPL
  * DEFAULT_TEXT_QA_PROMPT_TMPL  <- prompts/default_prompts.py:DEFAULT_TEXT_QA_PROMPT_TMPL
  * DEFAULT_SINGLE_SELECT_PROMPT_TMPL  <- selectors/prompts.py:DEFAULT_SINGLE_SELECT_PROMPT_TMPL
  * DEFAULT_NAME  <- tools/query_engine.py:DEFAULT_NAME
  * DEFAULT_DESCRIPTION  <- tools/query_engine.py:DEFAULT_DESCRIPTION
  * DEFAULT_SUMMARY_PROMPT_TMPL  <- prompts/default_prompts.py:DEFAULT_SUMMARY_PROMPT_TMPL

为什么是这几段：
  * CHOICE_SELECT  —— `LLMReranker` 未传 `choice_select_prompt`（`llm_reranker.py:18-20`），
    恒用库默认；
  * SINGLE_SELECT  —— 画布 kwargs 里 `prompt` 为空串时回落库默认（`query_routing.py:19-20`）；
  * TEXT_QA        —— 合成器 `simple_summarizer` 的 `get_response` 用到；
  * NAME/DESCRIPTION —— 条件路由的候选描述：`retriever.get_description()` 恒返回 None
    （`retriever/base.py:18-22`），`QueryEngineTool.from_defaults` 于是原样使用这两段。
"""
# ruff: noqa: E501  —— 文本按原样落盘，不按行宽折行

# 长度 753 字符；源：prompts/default_prompts.py
DEFAULT_CHOICE_SELECT_PROMPT_TMPL = "A list of documents is shown below. Each document has a number next to it along with a summary of the document. A question is also provided. \nRespond with the numbers of the documents you should consult to answer the question, in order of relevance, as well \nas the relevance score. The relevance score is a number from 1-10 based on how relevant you think the document is to the question.\nDo not include any documents that are not relevant to the question. \nExample format: \nDocument 1:\n<summary of document 1>\n\nDocument 2:\n<summary of document 2>\n\n...\n\nDocument 10:\n<summary of document 10>\n\nQuestion: <question>\nAnswer:\nDoc: 9, Relevance: 7\nDoc: 3, Relevance: 4\nDoc: 7, Relevance: 3\n\nLet's try this now: \n\n{context_str}\nQuestion: {query_str}\nAnswer:\n"

# 长度 188 字符；源：prompts/default_prompts.py
DEFAULT_TEXT_QA_PROMPT_TMPL = 'Context information is below.\n---------------------\n{context_str}\n---------------------\nGiven the context information and not prior knowledge, answer the query.\nQuery: {query_str}\nAnswer: '

# 长度 324 字符；源：selectors/prompts.py
DEFAULT_SINGLE_SELECT_PROMPT_TMPL = "Some choices are given below. It is provided in a numbered list (1 to {num_choices}), where each item in the list corresponds to a summary.\n---------------------\n{context_list}\n---------------------\nUsing only the choices above and not prior knowledge, return the choice that is most relevant to the question: '{query_str}'\n"

# 长度 17 字符；源：tools/query_engine.py
DEFAULT_NAME = 'query_engine_tool'

# 长度 111 字符；源：tools/query_engine.py
DEFAULT_DESCRIPTION = 'Useful for running a natural language query\nagainst a knowledge base and get back a natural language response.\n'

# 长度 154 字符；源：prompts/default_prompts.py
DEFAULT_SUMMARY_PROMPT_TMPL = 'Write a summary of the following. Try to use only the information provided. Try to include as many key details as possible.\n\n\n{context_str}\n\n\nSUMMARY:"""\n'

