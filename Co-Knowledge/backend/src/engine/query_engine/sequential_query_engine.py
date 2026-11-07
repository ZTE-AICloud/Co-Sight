from abc import ABC

from engine.primitives.interfaces import RagQueryEngine

from engine.context.rag_context import RagContext
from engine.query_engine import load_rag_operator, OperatorBean
from engine.query_engine.base import BaseRagQueryEngine
from engine.query_engine.multi_transform_query_engine import MultiTransformQueryEngine
from engine.query_engine.select_prompt_query_engine import SelectPromptQueryEngine
from engine.retriever.fusion_retriever import FusionRetriever


class SequentialQueryEngine(BaseRagQueryEngine, ABC):
    """
    顺序工作流查询引擎
    """

    @classmethod
    def as_query_engine(cls, rag_context: RagContext) -> RagQueryEngine:
        operators = load_rag_operator(rag_context)
        workflow_nodes = rag_context.get_workflow_nodes()
        operator_bean = OperatorBean(operators, workflow_nodes)
        if "websearch" in operators:
            retriever = FusionRetriever.from_args(config_dict={"top_k": None})
            retriever.update_retrievers([operator_bean.retrievers[0], operators["websearch"]])
        else:
            retriever = operator_bean.retrievers[0]
        query_engine = SelectPromptQueryEngine(retriever=retriever,
                                               response_synthesizer=operator_bean.get_first_response_synthesizer(),
                                               node_postprocessors=operator_bean.post_retrievers)
        return MultiTransformQueryEngine(query_engine=query_engine, query_transforms=operator_bean.query_transforms)
