from typing import Callable, Dict, List, Optional

from engine.common import const
from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.common.exception.rag_exception import RagException
from engine.gateways import llm_proxy_client
from engine.gateways.knowledge_base_client import invoke_list_vector_knowledge_bases
from engine.logutil import logger

#: Injected by the chat composition root; the engine never imports ``chat``.
_workflow_config_provider: Optional[Callable[[str, str], Dict]] = None


def set_workflow_config_provider(provider: Callable[[str, str], Dict]) -> None:
    global _workflow_config_provider
    _workflow_config_provider = provider


def _read_workflow_config(workflow_id: str, scope: str) -> Dict:
    """取画布配置：默认取**已发布快照**，scope='dev' 取草稿。"""
    if _workflow_config_provider is None:
        raise RuntimeError(
            'workflow config provider is not configured; '
            'pass it to build_query_engine() or set_workflow_config_provider()')
    return _workflow_config_provider(workflow_id, scope)


def _get_response_synthesizer_config(user_request, workflow_config_info):
    response_synthesizers = workflow_config_info.get('response-synthesizer', [])
    base_names = user_request.kwargs.get('base_names')
    if base_names and len(response_synthesizers) > 0:
        response_synthesizer = response_synthesizers[0]
        kwargs = response_synthesizer.get('kwargs')
        generator_config = kwargs.get('generator-config')[0]
        generator_config['knowledge_base_name'] = base_names
        kwargs['generator-config'] = [generator_config]
        response_synthesizer['kwargs'] = kwargs
        return [response_synthesizer]
    else:
        return response_synthesizers




class RagContext:

    def __init__(self, user_request: RagRequest, request_headers: RagRequestHeaders,
                 workflow_config_provider: Optional[Callable[[str, str], Dict]] = None):
        if workflow_config_provider is not None:
            set_workflow_config_provider(workflow_config_provider)
        self.user_request = user_request
        self.request_headers = request_headers

        workflow_config_info = _read_workflow_config(user_request.workflow_id, user_request.scope)
        self.query_engine = workflow_config_info.get('query-engine', {})
        self.pre_retrieval_config = workflow_config_info.get('pre-retriever', [])
        self.retrieval_config = self._get_retriever_config(user_request, workflow_config_info)
        self.post_retrieval_config = workflow_config_info.get('post-retriever', [])
        self.response_synthesizer_config = _get_response_synthesizer_config(user_request, workflow_config_info)
        self.workflow = workflow_config_info.get('workflow', {})
        self._update_default_workflow_config()

    def get_operators(self) -> List[Dict]:
        return self.pre_retrieval_config + self.retrieval_config + self.post_retrieval_config + self.response_synthesizer_config

    def get_workflow_nodes(self) -> List[str]:
        edges = self.workflow.get('edges', [])
        nodes = set([edge[0] for edge in edges] + [edge[1] for edge in edges])
        first_node = next((node for node in nodes if all(edge[1] != node for edge in edges)), None)
        if not first_node:
            return []
        bfs_traversal_nodes = [first_node]
        visited = set()
        while bfs_traversal_nodes:
            current_node = bfs_traversal_nodes.pop(0)
            if current_node in visited:
                continue
            visited.add(current_node)
            bfs_traversal_nodes.extend(edge[1] for edge in edges if edge[0] == current_node and edge[1] not in visited)
        return list(visited)

    def get_chain_all_nodes(self, current_node: str) -> List[str]:
        nodes = []
        self._scan_next_node(current_node, nodes)
        return nodes

    def _scan_next_node(self, current_node: str, nodes: List[str]):
        for edge in self.workflow.get('edges', []):
            if edge[0] == current_node and edge[1] not in nodes:
                nodes.append(edge[1])
                self._scan_next_node(edge[1], nodes)
                break

    def _update_default_workflow_config(self):
        if const.default_workflow_id == self.user_request.workflow_id:
            llm = llm_proxy_client.invoke_query_llm_info()
            logger.info('use default workflow to query, select environment LLM name: %s' % llm)
            self.pre_retrieval_config[0]["kwargs"]["llm"] = llm
            self.response_synthesizer_config[0]["kwargs"]["generator-config"][0]["llm"] = llm


    def _get_retriever_config(self, user_request, workflow_config_info):
        retrievers = workflow_config_info.get('retriever', [])
        base_names = user_request.kwargs.get('base_names')
        self._check_query_engine(base_names)
        current_workflow_id = workflow_config_info.get('workflow_id')
        if const.default_workflow_id == current_workflow_id and base_names is None:
            base_names = invoke_list_vector_knowledge_bases()
            logger.info('use default workflow to query, environment knowledge base name: %s' % str(base_names))

        # ------------------------------------------------------------------
        # ⚠️ 死分支（不可达）：以下「SqlRetriever + fallback_llm」两段保留着，
        # 但永远不会真正执行到它们：
        #
        #   1. 本仓**没有** `core/rag/retriever/sql_retriever.py`（它依赖 SQL 能力 /
        #      sql_executor 链路），`default_packages_info` 里也没有 'SqlRetriever'
        #      映射。快照里即便真有 operator == 'SqlRetriever' 的条目，实例化时也会在
        #      `rag_operator_loader.find_package_in_custom_operator_cache` 直接抛
        #      'workflow-has-no-operator'，走不到这个分支的产物。
        #   2. 因为 (1)，`_get_pre_retriever_llm()` 的返回值当前**没有任何消费者**；
        #      pre-retriever 没配 llm 时它会打日志并返回 None，除此之外无副作用。
        #
        # 将来若要支持 sql_retriever：补上 `default_packages_info.operator_packages`
        # 的 'SqlRetriever' 映射，这段就会自动生效 —— fallback_llm（pre-retriever 的
        # llm 名）随 kwargs['fallback_llm'] 传给算子，用于失败重试。
        # **来这里打开即可，别在别处另接。**
        # ------------------------------------------------------------------
        # Get fallback_llm from pre-retriever for SqlRetriever retry
        fallback_llm = self._get_pre_retriever_llm()

        if base_names:
            if const.default_workflow_id == current_workflow_id:
                workflow_config_info['response-synthesizer'][0]['kwargs']['generator-config'][0][
                    'knowledge_base_name'] = base_names

            for retriever in retrievers:
                if 'VectorRetriever' == retriever.get('operator'):
                    kwargs = retriever.get('kwargs')
                    knowledge_info = kwargs.get('knowledge_info_list')[0]
                    knowledge_info['knowledge_base_name'] = base_names
                    kwargs['knowledge_info_list'] = [knowledge_info]
                    retriever['kwargs'] = kwargs
                if 'KeywordRetriever' == retriever.get('operator'):
                    retriever['kwargs']["knowledge_base_name"] = base_names

        # Add fallback_llm to SqlRetriever for retry on failure
        # （死分支，见上方注释块：没有 vendor sql_retriever，这段永远找不到目标）
        for retriever in retrievers:
            if 'SqlRetriever' == retriever.get('operator'):
                kwargs = retriever.get('kwargs', {})
                if fallback_llm:
                    kwargs['fallback_llm'] = fallback_llm
                    logger.info(f"[RagContext] Added fallback_llm={fallback_llm} to SqlRetriever")
                retriever['kwargs'] = kwargs

        return retrievers

    def _get_pre_retriever_llm(self):
        """
        Get the LLM model name from pre-retriever config for SqlRetriever fallback.

        ⚠️ 当前返回值没有消费者：消费它的 SqlRetriever 分支是死分支（本仓未 vendor
        sql_retriever），详见 `_get_retriever_config` 里的注释块。

        :return: LLM model name from pre-retriever, or None if not found
        """
        for pre_retriever in self.pre_retrieval_config:
            llm = pre_retriever.get('kwargs', {}).get('llm')
            if llm:
                logger.info(f"[RagContext] Found pre-retriever LLM: {llm}")
                return llm
        return None

    def _check_query_engine(self, base_names):
        operator = self.query_engine.get('operator')
        if base_names and operator not in ['SequentialQueryEngine', 'BlendedQueryEngine']:
            raise RagException(-1, 'only-support-sequential-hybrid')
