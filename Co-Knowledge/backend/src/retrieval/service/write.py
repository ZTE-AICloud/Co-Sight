"""Public retrieval write surface used by document ingestion and KB lifecycle."""
from __future__ import annotations

from typing import Iterable

from retrieval.repository import vector_write_store


def build_metadata(metadata: dict, chunk_id) -> dict:
    return vector_write_store.build_metadata(metadata, chunk_id)


def save_chunks(chunk_table: str, chunks: Iterable[dict]) -> None:
    vector_write_store.save_chunks(chunk_table, chunks)


def save_vectors(vector_table: str, rows: list[dict]) -> None:
    vector_write_store.save_vectors(vector_table, rows)


def save_es_documents(kbase_id: str, file_id: str, nodes: list[dict]) -> None:
    vector_write_store.save_es_documents(kbase_id, file_id, nodes)


def update_es_document_by_node_id(kbase_id: str, node_id: str, key: str,
                                  metadata: dict) -> None:
    vector_write_store.update_es_document_by_node_id(kbase_id, node_id, key, metadata)


def delete_es_documents_by_query(kbase_id: str, field_name: str, values: list) -> None:
    vector_write_store.delete_es_documents_by_query(kbase_id, field_name, values)
