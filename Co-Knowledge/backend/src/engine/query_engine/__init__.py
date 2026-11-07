from engine.primitives.components.fusion import QueryFusionRetriever
from engine.primitives.interfaces import RagNodePostprocessor, RagSynthesizer

from engine.pre_retriever.query_selector.base import BaseRagSelector
from engine.pre_retriever.query_transform.base import BaseRagQueryTransform
from engine.retriever.base import BaseRagRetriever
from engine.retriever.websearch_retriever import WebSearchRetriever
from engine.rag_utils import instance_operator


class OperatorBean:

    def __init__(
            self,
            operators,
            workflow_nodes
    ) -> None:
        query_transforms, query_selector, retrievers, fusion_retriever, post_retrievers, response_synthesizers \
            = [], None, [], None, [], []

        for node in workflow_nodes:
            operator = operators.get(node)
            if isinstance(operator, BaseRagQueryTransform):
                query_transforms.append(operator)
            elif isinstance(operator, BaseRagSelector):
                query_selector = operator
            elif isinstance(operator, BaseRagRetriever):
                retrievers.append(operator)
            elif isinstance(operator, QueryFusionRetriever):
                fusion_retriever = operator
            elif isinstance(operator, RagNodePostprocessor):
                post_retrievers.append(operator)
            elif isinstance(operator, RagSynthesizer):
                response_synthesizers.append(operator)

        self.query_transforms = query_transforms
        self.query_selector = query_selector
        self.retrievers = retrievers
        self.fusion_retriever = fusion_retriever
        self.post_retrievers = post_retrievers
        self.response_synthesizers = response_synthesizers

    def get_first_response_synthesizer(self):
        return self.response_synthesizers[0] if len(self.response_synthesizers) > 0 else None


def load_rag_operator(rag_context):
    user_request = rag_context.user_request
    request_headers = rag_context.request_headers

    operators = {}
    for operator_config in rag_context.get_operators():
        operator_id = operator_config.get('id')
        operator = _build_rag_operator(operator_config, request_headers, user_request)
        operators[operator_id] = operator
    if user_request.enableWebSearch:
        operators['websearch'] = WebSearchRetriever(request_headers, user_request.apiKey)
    return operators


def _pre_setting_params(config, user_request, request_headers):
    params = config.get('kwargs', {})
    params['headers'] = request_headers
    params['user_request'] = user_request
    return params


def _build_rag_operator(config, request_headers, user_request):
    params = _pre_setting_params(config, user_request, request_headers)
    return instance_operator(config.get('package'), config.get('operator'), params)
