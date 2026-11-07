import uuid

from parsing.common.logutil import log


class LCDocument:
    def __init__(self, page_content, metadata, doc_id=None):
        self.page_content = page_content
        self.metadata = metadata
        self.id = doc_id


def rewrite_source_metadata(docs: list, source: str):
    new_docs = []
    for doc in docs:
        metadata = doc.metadata if doc.metadata else {}  # 确保 metadata 不是 None
        new_doc = LCDocument(page_content=doc.page_content, metadata={**metadata, 'source': source})
        new_docs.append(new_doc)
    return new_docs


def parse_md_to_nodes(docs: list[LCDocument]):
    log.info("parse md to nodes start ...")
    log.info(f"chunk size is:{len(docs)}")
    nodes = [build_node(doc) for doc in docs]
    log.info("parse md to nodes end...")
    return nodes


def build_node(doc: LCDocument):
    return {
        "nodeId": str(uuid.uuid4()),
        "text": doc.page_content,
        "metadata": doc.metadata,
        "embedding": None
    }


def _safe_int(value):
    """
    安全地将值转换为整数
    如果值是字符串且包含逗号，取第一个值
    如果转换失败，返回 None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        # 如果是逗号分隔的字符串，取第一个值
        if ',' in value:
            value = value.split(',')[0].strip()
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def identify_duplicate_chunks(nodes: list, kbase_id: str, source: str = None):
    """
    识别重复的chunk并为它们分配相同的chunk_id
    参考 GraphExtractService.deduplicate_metadata 的实现方式，通过source和content_expand字段进行去重
    
    Args:
        nodes: 节点列表，每个节点包含 nodeId, text, metadata, embedding
        kbase_id: 知识库ID
        source: 数据源/文件名
    
    Returns:
        tuple: (nodes_with_chunk_id, chunks_list)
            - nodes_with_chunk_id: 包含chunkId的节点列表
            - chunks_list: 去重后的chunk数据列表
    """
    seen_combinations = set()  # 已见过的唯一标识组合
    unique_key_to_chunk_id = {}  # 唯一标识 -> chunk_id
    chunk_data_map = {}  # chunk_id -> chunk数据
    nodes_with_chunk_id = []
    
    for node in nodes:
        text = node.get("text", "")
        metadata = node.get("metadata", {})
        
        # 获取source和content_expand，参考 GraphExtractService.deduplicate_metadata 的实现
        node_source = source or metadata.get("source", "")
        content_expand = metadata.get("content_expand", "")
        
        # 创建唯一标识：优先使用 source + content_expand（与 GraphExtractService 保持一致）
        # 如果没有 content_expand，则使用 source + text
        if content_expand:
            unique_key = f"{node_source}|{content_expand}"
        else:
            unique_key = f"{node_source}|{text}"
        
        # 如果唯一标识已存在，使用相同的chunk_id；否则生成新的chunk_id
        if unique_key in seen_combinations:
            chunk_id = unique_key_to_chunk_id[unique_key]
            log.debug(f"发现重复chunk，使用已有chunk_id: source={node_source}, content_expand={content_expand[:50] if content_expand else 'N/A'}")
        else:
            chunk_id = str(uuid.uuid4())
            seen_combinations.add(unique_key)
            unique_key_to_chunk_id[unique_key] = chunk_id
            
            # 安全地获取chunkOrder，确保是整数类型
            chunk_order_value = metadata.get("chunk_index") or metadata.get("chunk_order")
            chunk_order = _safe_int(chunk_order_value)
            
            # 构建chunk数据
            chunk_data = {
                "id": chunk_id,
                "kbId": kbase_id,
                "source": node_source,
                "chunkOrder": chunk_order,
                "spiltType": metadata.get("spilt_type") or metadata.get("split_type"),
                # chunk 表 text 的语义是「完整上下文」（对应 supplement / 优化任务 full content）。
                # 系统算子 metadata 含 content_expand（v1 中 content_expand == page_content），沿用原值；
                # 自定义算子不产 content_expand，回退到节点正文 text，避免 chunk 表 text 为空，
                # 并使其与向量表/ES 存取的 page_content 一致。
                "text": content_expand or text,
                "label": metadata.get("label"),
                "tableName": metadata.get("table_name"),
                "tableId": metadata.get("table_id"),
                "metadata": metadata
            }
            chunk_data_map[chunk_id] = chunk_data
        
        # 为node分配chunkId（保持metadata.content_expand的原有值不变）
        # 只在metadata中添加chunk_id字段，不修改content_expand
        if "metadata" not in node or node["metadata"] is None:
            node["metadata"] = {}
        # 在metadata中添加chunk_id字段，便于kbase-ms后续使用
        node["chunk_id"] = chunk_id
        # 注意：不修改content_expand字段，保持其原有值
        nodes_with_chunk_id.append(node)
    
    # 构建去重后的chunks列表
    chunks_list = list(chunk_data_map.values())
    
    log.info(f"去重前: {len(nodes)} 个节点，去重后: {len(chunks_list)} 个唯一chunk")
    
    return nodes_with_chunk_id, chunks_list