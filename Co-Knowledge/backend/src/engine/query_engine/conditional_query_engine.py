from abc import ABC

from engine.primitives.components.fusion import QueryFusionRetriever
from engine.primitives.components.query_engine import RouterQueryEngine
from engine.primitives.interfaces import RagNodePostprocessor, RagQueryEngine, RagSynthesizer
from engine.primitives.models import QueryEngineTool

from engine import RagContext
from engine.pre_retriever.query_selector.base import BaseRagSelector
from engine.pre_retriever.query_transform.base import BaseRagQueryTransform
from engine.query_engine import load_rag_operator
from engine.query_engine.base import BaseRagQueryEngine
from engine.query_engine.multi_transform_query_engine import MultiTransformQueryEngine
from engine.query_engine.select_prompt_query_engine import SelectPromptQueryEngine
from engine.retriever.base import BaseRagRetriever
from engine.retriever.fusion_retriever import FusionRetriever


class ConditionalQueryEngine(BaseRagQueryEngine, ABC):
    """
    条件工作流查询引擎
    """

    @classmethod
    def as_query_engine(cls, rag_context: RagContext) -> RagQueryEngine:
        query_transforms, query_selector, query_engine_tools = _get_conditional_operators(rag_context)
        router_query_engine = RouterQueryEngine(selector=query_selector,
                                                query_engine_tools=query_engine_tools,
                                                llm=query_selector._llm)
        return MultiTransformQueryEngine(query_engine=router_query_engine, query_transforms=query_transforms)


def _get_conditional_operators(rag_context):
    query_transforms = []
    query_selector = None
    query_engine_tools = []
    operators = load_rag_operator(rag_context)
    workflow_nodes = rag_context.get_workflow_nodes()
    for node in workflow_nodes:
        operator = operators.get(node)
        if isinstance(operator, BaseRagQueryTransform):
            query_transforms.append(operator)
        elif isinstance(operator, BaseRagSelector):
            query_selector = operator
        elif isinstance(operator, BaseRagRetriever):
            if "websearch" in operators:
                retriever = FusionRetriever.from_args(config_dict={"top_k": None})
                retriever.update_retrievers([operator, operators["websearch"]])
            else:
                retriever = operator
            chain_nodes = rag_context.get_chain_all_nodes(node)
            post_retrievers, response_synthesizer = _build_operator_chain(chain_nodes, operators)
            query_engine_tool = _build_query_engine_tool(retriever, post_retrievers, response_synthesizer)
            query_engine_tools.append(query_engine_tool)
    return query_transforms, query_selector, query_engine_tools




def _build_query_engine_tool(retriever, post_retrievers, response_synthesizer):
    query_engine = SelectPromptQueryEngine(retriever=retriever,
                                           response_synthesizer=response_synthesizer,
                                           node_postprocessors=post_retrievers)
    if isinstance(retriever, QueryFusionRetriever):
        description = retriever._retrievers[0].get_description()
    else:
        description = retriever.get_description()
    return QueryEngineTool.from_defaults(query_engine=query_engine,
                                         description=description)


def _build_operator_chain(chain_nodes, operators):
    post_retrievers = []
    response_synthesizer = None
    for next_node in chain_nodes:
        next_operator = operators.get(next_node)
        if isinstance(next_operator, RagNodePostprocessor):
            post_retrievers.append(next_operator)
        elif isinstance(next_operator, RagSynthesizer):
            response_synthesizer = next_operator
    return post_retrievers, response_synthesizer
