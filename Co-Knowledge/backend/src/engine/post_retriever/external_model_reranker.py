"""外部重排模型算子：把候选切片交给已注册的 rerank 端点排序、按 source 合并。

模型由模型注册表决定（Qwen3-Reranker-4B 等）。
"""

import os
import time
from typing import Dict, Optional, List, Tuple

from engine.primitives.models import QueryBundle, TextNode

from engine.common import const
from engine.gateways.llm_proxy_client import invoke_rerank_client, query_rerank_model
from engine.post_retriever.base import BaseRagPostRetriever
from engine.retriever import RagNodeWithScore
from engine.logutil import logger
from engine.http_utils import escape

# 常量定义
MAX_NODES_FOR_RERANK = 100
MAX_NODES_FOR_COPILOT_RERANK = 100
DEFAULT_TOP_N = 3
DEFAULT_SCORE_THRESHOLD = -100
MAX_OVERLAP_LENGTH = 200


def _extract_text_content(node: RagNodeWithScore) -> str:
    """提取节点的文本内容（去除expand_format包装）"""
    return node.text[len(const.expand_format):-len(const.expand_format)]


def _extract_clean_source(node: RagNodeWithScore) -> str:
    """提取节点的清理后的source（去除source_format包装和扩展名）"""
    source = node.node.metadata.get('source', '')
    clean_source = source.replace(const.source_format, '')
    return os.path.splitext(clean_source)[0]


def _build_copilot_text(node: RagNodeWithScore) -> str:
    """为NIA Copilot构建组合文本（source:text_content格式）"""
    clean_source = _extract_clean_source(node)
    text_content = _extract_text_content(node)
    return f"{clean_source}:{text_content}" if clean_source else text_content


def _get_node_by_content(nodes: List[RagNodeWithScore], content: str, for_nia_copilot: bool = False) -> Optional[
    RagNodeWithScore]:
    """根据内容查找对应的节点"""
    for node in nodes:
        if for_nia_copilot:
            combined_text = _build_copilot_text(node)
            if combined_text == content:
                return node
        else:
            if _extract_text_content(node) == content:
                return node
    return None


def _remove_overlap(prev_text: str, next_text: str, max_overlap: int = MAX_OVERLAP_LENGTH) -> str:
    """移除相邻文本之间的重叠部分"""
    if not prev_text or not next_text:
        return next_text
    max_check = min(len(prev_text), len(next_text), max_overlap)
    for i in range(max_check, 0, -1):
        if prev_text.endswith(next_text[:i]):
            return next_text[i:]
    return next_text


class ExternalModelReranker(BaseRagPostRetriever):
    # 原为 pydantic `Field(description=...)`（库的基类 `BaseNodePostprocessor` 是 BaseModel）；
    # 摘库后基类变成普通 ABC，字段声明退化为类型注记，`__init__` 直接赋值。
    config_info: Dict

    def __init__(self, config_info: Dict):
        self.config_info = config_info

    def _postprocess_nodes(self,
                           nodes: List[RagNodeWithScore],
                           query_bundle: Optional[QueryBundle] = None) -> List[RagNodeWithScore]:
        """对节点进行rerank后处理"""
        if query_bundle is None:
            raise ValueError("Query bundle must be provided.")
        if len(nodes) == 0:
            logger.info('nodes is empty when rerank.')
            return []

        for_nia_copilot = self.config_info.get('for_nia_copilot', False)
        if for_nia_copilot:
            return self._postprocess_for_copilot(nodes, query_bundle)
        else:
            return self._postprocess_standard(nodes, query_bundle)

    def _postprocess_standard(self, nodes: List[RagNodeWithScore], query_bundle: QueryBundle) -> List[RagNodeWithScore]:
        """标准模式的rerank处理（带合并逻辑）"""
        texts = [_extract_text_content(node) for node in nodes]
        logger.info('Start to rerank, node size=[%s]' % len(texts))

        # 调用rerank服务
        rerank_result = self._invoke_rerank(query_bundle.query_str, texts[:MAX_NODES_FOR_RERANK])

        # 构建节点字典
        nodes_dict: Dict[str, RagNodeWithScore] = {
            _extract_text_content(node): node for node in nodes
        }

        top_n = self.config_info.get('top_n', DEFAULT_TOP_N)
        selected_texts = rerank_result[:top_n]
        backup_texts = rerank_result[top_n:]

        # 处理选中的文本
        selected_sources, chunks_group_by_source = self._process_selected_texts(
            selected_texts, nodes_dict
        )

        # 处理备份文本（关联chunk）
        self._process_backup_texts(backup_texts, nodes_dict, selected_sources, chunks_group_by_source)

        # 合并并生成新节点
        new_nodes = self._merge_chunks_by_source(selected_sources, chunks_group_by_source)

        return new_nodes

    def _postprocess_for_copilot(self, nodes: List[RagNodeWithScore], query_bundle: QueryBundle) -> List[
        RagNodeWithScore]:
        """NIA Copilot模式的rerank处理（简单模式）"""
        texts = [_build_copilot_text(node) for node in nodes]
        logger.info('Start to rerank, node size=[%s]' % len(texts))

        # 调用rerank服务
        rerank_result = self._invoke_rerank(query_bundle.query_str, texts[:MAX_NODES_FOR_COPILOT_RERANK])

        # 根据结果查找节点
        top_n = self.config_info.get('top_n', DEFAULT_TOP_N)
        nodes_after_rerank = [
            _get_node_by_content(nodes, content, for_nia_copilot=True)
            for content in rerank_result[:top_n]
        ]
        nodes_after_rerank = [node for node in nodes_after_rerank if node is not None]

        return nodes_after_rerank

    def _invoke_rerank(self, query_str: str, texts: List[str]) -> List[str]:
        """调用rerank服务。

        画布上显式选了 ``model`` 就用它（并按「选不到就报错」的严格语义解析）；
        没选才回落到部署默认（注册表默认行 → ``RERANK_MODEL`` → 常量）。
        """
        start_time = time.time()
        headers = self.config_info.get('headers')
        username = escape(getattr(headers, 'username', ''))
        score_threshold = self.config_info.get('score', DEFAULT_SCORE_THRESHOLD)
        selected_model = str(self.config_info.get('model') or '').strip()
        result = invoke_rerank_client(
            selected_model or query_rerank_model(username),
            query_str,
            texts,
            score_threshold,
            strict_model=bool(selected_model),
        )
        logger.info('rerank cost time= %ss' % (time.time() - start_time))
        return result

    def _process_selected_texts(self, selected_texts: List[str], nodes_dict: Dict[str, RagNodeWithScore]) -> Tuple[
        Dict[str, str], Dict[str, Dict]]:
        """处理选中的文本，返回selected_sources和chunks_group_by_source"""
        selected_sources: Dict[str, str] = {}
        chunks_group_by_source: Dict[str, Dict] = {}

        for selected_text in selected_texts:
            node = nodes_dict.get(selected_text)
            if node is None:
                continue

            text_content = _extract_text_content(node)
            if selected_text != text_content:
                continue

            metadata = node.node.metadata
            source = metadata.get('source', 'Unknown').replace(const.source_format, '')
            related_chunk_ids = metadata.get('related_chunk_ids', [])

            chunk_info = {
                'text': selected_text,
                'order': metadata.get('chunk_order', metadata.get('chunk_id', 0)),
            }

            if source in selected_sources:
                source_chunk_dict = chunks_group_by_source.get(source, {})
                chunks = source_chunk_dict.get('chunks', [])
                chunks.append(chunk_info)

                combined = set(source_chunk_dict.get('related_ids', [])) | set(related_chunk_ids)
                source_chunk_dict['related_ids'] = list(combined)
            else:
                selected_sources[source] = node.base_name
                chunks_group_by_source[source] = {
                    'chunks': [chunk_info],
                    'related_ids': related_chunk_ids
                }

        return selected_sources, chunks_group_by_source

    def _process_backup_texts(self, backup_texts: List[str], nodes_dict: Dict[str, RagNodeWithScore],
                              selected_sources: Dict[str, str], chunks_group_by_source: Dict[str, Dict]):
        """处理备份文本，添加关联的chunk"""
        for backup_text in backup_texts:
            node = nodes_dict.get(backup_text)
            if node is None:
                continue

            metadata = node.node.metadata
            source = metadata.get('source', 'Unknown').replace(const.source_format, '')

            if not source or source not in selected_sources:
                continue

            source_chunk_dict = chunks_group_by_source.get(source, {})
            related_ids = source_chunk_dict.get('related_ids', [])
            chunk_id = metadata.get('chunk_id')

            if chunk_id and chunk_id in related_ids:
                chunks = source_chunk_dict.get('chunks', [])
                chunk_info = {
                    'text': backup_text,
                    'order': metadata.get('chunk_order', metadata.get('chunk_id', 0)),
                }
                chunks.append(chunk_info)

    def _merge_chunks_by_source(self, selected_sources: Dict[str, str],
                                chunks_group_by_source: Dict[str, Dict]) -> List[RagNodeWithScore]:
        """按source合并chunks并生成新节点"""
        new_nodes = []

        for selected_source, base_name in selected_sources.items():
            source_chunk_dict = chunks_group_by_source.get(selected_source, {})
            chunks = source_chunk_dict.get('chunks', [])
            def _order_key(c):
                o = c.get('order', 9999)
                try:
                    return int(o) if o is not None else 9999
                except (TypeError, ValueError):
                    return 9999
            chunks.sort(key=_order_key)

            if not chunks:
                continue

            # 合并文本
            merged_text = self._merge_chunk_texts(chunks)

            # 构建合并后的文档
            full_text = "".join(merged_text)
            merged_doc = f"{const.expand_format}Document：{selected_source}\n{full_text}{const.expand_format}"
            logger.debug("Merged document (with order-aware dedup):\n%s", merged_doc)

            # 创建新节点
            new_node = TextNode(
                text=merged_doc,
                metadata={
                    "source": f'{const.source_format}{selected_source}{const.source_format}',
                }
            )
            new_nodes.append(RagNodeWithScore(node=new_node, score=1.0, base_name=base_name))

        return new_nodes

    def _merge_chunk_texts(self, chunks: List[Dict]) -> List[str]:
        """合并chunk文本，处理重叠"""
        merged_text = [chunks[0]['text']]

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            curr_chunk = chunks[i]

            prev_order = prev_chunk.get('order')
            curr_order = curr_chunk.get('order')

            # 将 order 转为 int（API 可能返回字符串），只有连续整数才检查重叠
            try:
                prev_order_int = int(prev_order) if prev_order is not None else None
                curr_order_int = int(curr_order) if curr_order is not None else None
            except (TypeError, ValueError):
                prev_order_int, curr_order_int = None, None

            if (prev_order_int is not None and curr_order_int is not None
                    and curr_order_int == prev_order_int + 1):
                # 可能重叠，需要去重
                deduped_text = _remove_overlap(
                    prev_chunk['text'],
                    curr_chunk['text'],
                    max_overlap=MAX_OVERLAP_LENGTH
                )
                merged_text.append(deduped_text)
            else:
                # 不连续，不期望重叠，保持原样
                merged_text.append(curr_chunk['text'])

        return merged_text

    @classmethod
    def from_args(cls, config_dict: Dict) -> "BaseRagPostRetriever":
        return ExternalModelReranker(config_dict)
