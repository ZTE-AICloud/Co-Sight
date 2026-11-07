"""节点 metadata 的存储格式（平铺）与对外响应信封。

``metadata_`` **就是调用方那份 metadata 本身**，不存第二份副本，也没有旧框架
的类名与 doc-id 脚手架。键的插入顺序有契约意义：``to_search_doc`` 是把 dict
原样透给前端的，顺序变了响应字节就变了。

对外响应里的 node 仍是 TextNode 形状（前端与编排按它解析，是契约，不能动）。
信封里除 ``metadata`` 外的字段（``relationships`` / ``class_name`` / 模板 / …）
按固定字面量补齐。
"""

from __future__ import annotations

from typing import Any

# ----------------------------------------------------------------------
# 响应形状：TextNode 信封
# ----------------------------------------------------------------------

_ENVELOPE_LITERAL = {
    'embedding': None,
    'excluded_embed_metadata_keys': [
        'content_expand', 'context_expand_method', 'source'],
    'excluded_llm_metadata_keys': [],
    'relationships': {},
    'start_char_idx': 0,
    'text_template': '{metadata_str}\n\n{content}',
    'metadata_template': '{key}: {value}',
    'metadata_seperator': '\n',        # 拼写就是 seperator（历史拼写），别改
    'class_name': 'TextNode',
}


def node_envelope(metadata: Any, text, row_id=None, node_id=None) -> dict:
    """把一行原始记录包成 **TextNode 形状的 node**（响应形状，不是存储格式）。

    ``text`` 的键位保持不变、``id`` 追加在**末尾**；``end_char_idx`` 取 text 的长度。
    """
    node = {
        'id_': node_id,
        'embedding': _ENVELOPE_LITERAL['embedding'],
        'metadata': dict(metadata) if isinstance(metadata, dict) else {},
        'excluded_embed_metadata_keys': list(_ENVELOPE_LITERAL['excluded_embed_metadata_keys']),
        'excluded_llm_metadata_keys': list(_ENVELOPE_LITERAL['excluded_llm_metadata_keys']),
        'relationships': dict(_ENVELOPE_LITERAL['relationships']),
        'text': text,
        'start_char_idx': _ENVELOPE_LITERAL['start_char_idx'],
        'end_char_idx': len(text) if text is not None else 0,
        'text_template': _ENVELOPE_LITERAL['text_template'],
        'metadata_template': _ENVELOPE_LITERAL['metadata_template'],
        'metadata_seperator': _ENVELOPE_LITERAL['metadata_seperator'],
        'class_name': _ENVELOPE_LITERAL['class_name'],
    }
    node['text'] = text
    node['id'] = row_id
    return node
