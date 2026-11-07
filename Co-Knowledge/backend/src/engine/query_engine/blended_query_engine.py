from abc import ABC

from engine.primitives.interfaces import RagQueryEngine

from engine import RagContext
from engine.query_engine import load_rag_operator, OperatorBean
from engine.query_engine.base import BaseRagQueryEngine
from engine.query_engine.multi_transform_query_engine import MultiTransformQueryEngine
from engine.query_engine.select_prompt_query_engine import SelectPromptQueryEngine


class BlendedQueryEngine(BaseRagQueryEngine, ABC):
    """
    混合检索工作流查询引擎
    """

    @classmethod
    def as_query_engine(cls, rag_context: RagContext) -> RagQueryEngine:
        operators = load_rag_operator(rag_context)
        workflow_nodes = rag_context.get_workflow_nodes()
        operator_bean = OperatorBean(operators, workflow_nodes)
        fusion_retriever = operator_bean.fusion_retriever
        if "websearch" in operators:
            operator_bean.retrievers.append(operators["websearch"])
        fusion_retriever.update_retrievers(operator_bean.retrievers)
        query_engine = SelectPromptQueryEngine(retriever=fusion_retriever,
                                               node_postprocessors=operator_bean.post_retrievers,
                                               response_synthesizer=operator_bean.get_first_response_synthesizer())
        return MultiTransformQueryEngine(query_engine=query_engine, query_transforms=operator_bean.query_transforms)
