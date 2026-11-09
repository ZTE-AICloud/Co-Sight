#!/usr/bin/env python3
"""数据入库骨架 — 文档切块 → 向量生成 → 批量写入 → 建索引。

用法: cd <技能目录> && python3 scripts/insert_data.py <文档.md> [集合名]
默认切块: 500 字符 / 50 重叠; 默认集合名 rag_kb。
"""
import sys
from typing import List

from kb_builder import VectorCollectionBuilder

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
DEFAULT_COLLECTION = "rag_kb"


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """滑窗切块, 保留重叠上下文。"""
    if len(text) <= size:
        return [text]
    chunks = []
    step = size - overlap
    for start in range(0, len(text), step):
        piece = text[start : start + size]
        if piece.strip():
            chunks.append(piece)
        if start + size >= len(text):
            break
    return chunks


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python3 insert_data.py <文档.md> [集合名]")
        return 2
    doc_path = sys.argv[1]
    collection = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_COLLECTION

    with open(doc_path, encoding="utf-8") as f:
        text = f.read()
    chunks = chunk_text(text)
    print(f"切块完成: {len(chunks)} 块（{CHUNK_SIZE}/{CHUNK_OVERLAP}）")

    builder = VectorCollectionBuilder()
    builder.init_embedding()  # 密钥缺失会显式抛错（fail-closed）
    result = builder.embed_and_insert(collection, chunks)
    print(f"写入完成: {result['inserted']} 条 → {collection}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
