from ingestion.split.node_transfer import LCDocument, parse_md_to_nodes


def result_convert(json_list):
    """把切分算子返回的字典列表转成统一的 node 结构。

    RKB 进程内调用 ``TextSplitService`` 时，下游（重复 chunk 识别）
    只认含 ``nodeId`` 的 node 列表，所以这里固定走 ``parse_md_to_nodes``。
    """
    docs = []
    for item in json_list:
        page_content = item.get('content')
        metadata = item.get('metadata', {})
        # 创建 LCDocument 实例并添加到列表中
        document = LCDocument(page_content, metadata)
        docs.append(document)
    return parse_md_to_nodes(docs)
