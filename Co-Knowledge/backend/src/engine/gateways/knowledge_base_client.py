"""检索适配器：知识库检索响应 → 编排运行时期望的 node 形状。

数据由进程内检索提供（``POST /api/co-knowledge/v1/retrieval``），
其余逻辑保持不变：
同样的过滤（丢掉没有 docs 的库）、同样的排序、同样的 `_calculate_select_base_size`、
同样的引用标记包装（`|*expand#|`/`|*source#|`/`|*knowledge_name#|`/`|*chunk_index#|`）——
这些标记是前端渲染引用的**事实契约**，改一个字符引用就散了。

字段对接：

    SearchResultVO.baseName        → 运行时的 base（引用里的知识库名）
    SearchDocVO.content            → metadata.content_expand（运行时的正文段）
    SearchDocVO.score              → 排序与打分
    SearchDocVO.chunkId            → metadata.node_id（**部分路径为 null**）
    SearchDocVO.sourceDocId        → metadata.source（**部分路径为 null**）
    SearchDocVO.metadata.chunk_index → 引用里的序号

> chunkId / sourceDocId 在部分检索路径上本来就是 null（见 SearchDocVO 的 javadoc），
> 所以引用与图片信息会稀疏 —— 这是数据源的真实形状，不是这里的 bug。

图谱检索（`invoke_knowledge_graph_client`）是**另一条数据源**：RKB 的图谱检索
（`POST /api/co-knowledge/v1/retrieval/graph`）。它返回的是图数据（实体/边/chunk），
由 `knowledgegraph_retriever` 自己转节点，所以这里只做「调用 + 显式失败」，不做形状转换。

> 编排并入 RKB 后，本模块的三条出站调用走**进程内** transport
> （`rkb_transport`），不再是 HTTP；URL 与地址类配置键一并删除。下面每处的
> 「状态码检查 → 业务码判定 → 抛 RagException」**保持不变** —— 那是报文形状契约。
"""
from __future__ import annotations

from typing import Dict, List

from engine.primitives.models import TextNode

from engine.common import const
from engine.common.exception.rag_exception import RagException
from engine.settings import Config
from engine.logutil import logger

#: Injected by the chat composition root; the engine never imports ``chat``.
_transport = None


def set_transport(transport) -> None:
    global _transport
    _transport = transport


def _get_transport():
    if _transport is None:
        raise RuntimeError(
            'RKB transport is not configured; call set_transport() from the composition root')
    return _transport

# 图谱检索走统一 REST 契约：2xx 的 body 就是结果对象，
# 没有 `{code, message, data}` 信封；失败是真实状态码 + problem+json。


def _node_class():
    """延迟导入 `RagNodeWithScore`。

    直写在模块顶部会形成循环：
        core.gateways.knowledge_base_client
          → core.rag.retriever（触发 core/rag/__init__.py）
          → core.rag.context.rag_context
          → core.gateways.knowledge_base_client（此时还没初始化完）
    放在函数里既保住循环安全，又不改类的身份（isinstance / 类型注解仍然一致）。
    """
    from engine.retriever import RagNodeWithScore
    return RagNodeWithScore

def invoke_knowledge_base_client(headers, body) -> List[RagNodeWithScore]:
    """调用检索接口，并转成运行时的节点列表。"""
    try:
        logger.info('invoke knowledge-base retrieve, body = %s' % (body,))
        response = _get_transport().post_retrieve(body, headers)
        if response.status_code < 200 or response.status_code >= 300:
            raise RagException(-2, 'bad-status-code', 'knowledge-base')

        payload = response.json()
        if not isinstance(payload, list):
            logger.warning('knowledge-base retrieve returned unexpected payload: %s',
                           type(payload).__name__)
            raise RagException(-2, 'request-knowledgebase-failed')
        results = payload
        data = [_to_runtime_base(item) for item in results]
        data = [node for node in data if len(node.get('docs')) > 0]
        sorted_data = sorted(data, key=lambda doc_info: doc_info.get('docs')[0].get('score'), reverse=True)
        selected_data = sorted_data[:_calculate_select_base_size(len(data))]
        logger.debug(f"retrieve select data is {selected_data}")
        return _to_nodes(selected_data)
    except RagException as e:
        logger.warning('invoke knowledge-base to retrieve related_contexts failed, reason is {}'.format(e.get_error_tag()))
        raise e
    except Exception as e:
        logger.warning('invoke knowledge-base to retrieve related_contexts failed, reason is {}'.format(str(e)))
        logger.exception(e)
        raise RagException(-2, 'request-knowledgebase-failed')


def _to_runtime_base(result: Dict) -> Dict:
    """把一条 SearchResultVO 摊成运行时认的 `{base, docs: [{score, node}]}`。

    运行时的 `_to_nodes` 只从 `node.metadata` 里取 content_expand / node_id / source /
    chunk_index，所以这里把检索结果的平铺字段**填回 metadata**，
    让下游（重排、合成、引用）完全不用改。
    """
    base_name = result.get('baseName') or ''
    docs = []
    for doc in result.get('docs') or []:
        metadata = dict(doc.get('metadata') or {})
        # 可读文件名必须在下面被 sourceDocId 覆盖之前留一份：下游返回的
        # `metadata.source` 是文件名，而引用契约要求 `metadata.source` 放
        # sourceDocId。证据面板用 `source_name` 展示文件名（见 retrieval_evidence）。
        source_name = metadata.get('source')
        metadata['content_expand'] = _as_text(doc.get('content'))
        metadata['node_id'] = _as_text(doc.get('chunkId'))
        if doc.get('sourceDocId'):
            metadata['source'] = _as_text(doc.get('sourceDocId'))
        if 'chunk_index' in metadata:
            # 下游 `_to_nodes` 是拿这些值直接做字符串拼接的（`fmt + value + fmt`），
            # metadata 来自 JSON，chunk_index 可能是数字 —— 数字会让它 TypeError。
            # 在**适配器这一层**做类型归一，保持 vendored 的 `_to_nodes` 不动。
            metadata['chunk_index'] = _as_text(metadata.get('chunk_index'))
        docs.append({
            'score': doc.get('score') or 0,
            'source_name': _as_text(source_name),
            'node': {'metadata': metadata},
        })
    return {'base': base_name, 'docs': docs}


def _as_text(value) -> str:
    """None → 空串，其余 → str。见 `_to_runtime_base` 里关于字符串拼接的注释。"""
    return '' if value is None else str(value)


def _to_nodes(sorted_data: List[Dict]) -> List[RagNodeWithScore]:
    """引用标记与去重逻辑都在这里，任何改动都会影响前端引用渲染。"""
    rag_node_with_score = _node_class()
    texts, nodes = [], []
    for item in sorted_data:
        for doc in item.get('docs', []):
            node_json = doc.get('node', {})
            text = const.expand_format + node_json.get('metadata').get('content_expand') + const.expand_format
            if text not in texts:
                node_json['text'] = text
                # relationships存在和content_expand重复的现象，影响大模型总结，暂时置空
                node_json['relationships'] = {}
                node_id = node_json.get('metadata').get('node_id', '')
                node_json['metadata']['node_id'] = const.node_id_format + node_id + const.node_id_format
                source = node_json.get('metadata').get('source', '')
                node_json['metadata']['source'] = const.source_format + source + const.source_format
                node_json['metadata']['content_expand'] = ''
                base_name = item.get('base', '')
                node_json['metadata']['knowledge_name'] = const.base_format + base_name + const.base_format
                chunk_index = node_json.get('metadata').get('chunk_index', '')
                node_json['metadata']['chunk_index'] = const.chunk_index_format + chunk_index + const.chunk_index_format

                texts.append(text)
                node = TextNode.from_dict(node_json)
                # 见 `_to_runtime_base`：文件名放在 Node 的属性上而不是 metadata 里。
                # metadata 会被 `get_content(MetadataMode.LLM)` 拼进合成/重排提示词，
                # 属性不会；Fusion/LLMReranker 复用同一个 Node，属性会保留。
                source_name = doc.get('source_name')
                if source_name:
                    node.source_name = source_name
                nodes.append(rag_node_with_score(node=node, score=doc.get('score', 0), base_name=base_name))
    logger.info(f"to node result is {sorted(nodes, key=lambda x: x.score, reverse=True)}")
    return sorted(nodes, key=lambda x: x.score, reverse=True)


def _calculate_select_base_size(bases_size):
    if bases_size > 4:
        part_base_num = bases_size // 4
        return part_base_num if part_base_num > 4 else 4
    return bases_size


def invoke_knowledge_graph_client(headers, body) -> Dict:
    """调用 RKB 的图谱检索：`POST /api/co-knowledge/v1/retrieval/graph`。

    与其余端点同一契约：2xx 的 body 就是图数据对象；失败是真实
    HTTP 状态码 + problem+json。这里只做状态码检查，成功体直接返回。
    """
    try:
        logger.info('invoke knowledge graph, body = %s' % (body,))
        response = _get_transport().post_graph_retrieve(body, headers)
        if response.status_code < 200 or response.status_code >= 300:
            raise RagException(-2, 'bad-status-code', 'rag-knowledge-base')

        payload = response.json()
        if not isinstance(payload, dict):
            logger.warning('knowledge graph retrieve returned unexpected payload: %s',
                           type(payload).__name__)
            raise RagException(-2, 'request-knowledge-graph-failed')
        return payload
    except RagException as e:
        logger.warning('invoke knowledge graph to retrieve related_contexts failed, reason is {}'.format(e.get_error_tag()))
        raise e
    except Exception as e:
        logger.warning('invoke knowledge graph to retrieve related_contexts failed, reason is {}'.format(str(e)))
        logger.exception(e)
        raise RagException(-2, 'request-knowledge-graph-failed')


def invoke_list_vector_knowledge_bases() -> List[str]:
    """列出可用知识库的**表名**（运行时把它当 base 用）。

    数据来自知识库列表，取 `tableName` —— 与画布下拉存进算子 kwargs 的值同一个字段。
    """
    try:
        response = _get_transport().get_kbase_list()
        if response.status_code < 200 or response.status_code >= 300:
            raise RagException(-2, 'bad-status-code', 'knowledge-base')
        payload = response.json()
        if not isinstance(payload, list):
            raise RagException(-2, 'bad-status-code', 'knowledge-base')
        bases = [item.get('tableName') for item in payload if item.get('tableName')]
        if not bases:
            raise RagException(-2, 'knowledgebase-not-imported')
        return bases
    except RagException as re:
        raise re
    except Exception as e:
        logger.warning('list knowledge base failed, reason is {}'.format(str(e)))
        logger.exception(e)
        raise RagException(-2, 'request-knowledgebase-failed')
